"""
SQLite database layer using aiosqlite.

Stores sources (RSS feeds and websites), processed items, and seen-URL sets
for deduplication. The DB file lives at ./data.db alongside the Chroma data.
"""

from __future__ import annotations

import aiosqlite
import os
import uuid
from datetime import datetime, timezone

DB_PATH = os.environ.get("SQLITE_DB_PATH", "./data.db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id               TEXT PRIMARY KEY,
    url              TEXT NOT NULL UNIQUE,
    type             TEXT NOT NULL,
    name             TEXT NOT NULL,
    feed_url         TEXT,
    last_checked_at  TEXT,
    last_seen_marker TEXT,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    title         TEXT,
    author        TEXT,
    published_at  TEXT,
    raw_text      TEXT,
    summary       TEXT,
    category      TEXT,
    thumbnail_url TEXT,
    is_video      INTEGER DEFAULT 0,
    video_id      TEXT,
    status        TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'filtered_out', 'processed')),
    filter_reason TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(source_id, url)
);

CREATE TABLE IF NOT EXISTS seen_urls (
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url       TEXT NOT NULL,
    PRIMARY KEY (source_id, url)
);
"""


async def init_db() -> None:
    """Create tables and migrate existing schemas if needed. Called once at app startup."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if sources table has legacy CHECK constraint
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sources'")
        row = await cursor.fetchone()
        if row and "CHECK (type IN ('rss', 'website'))" in row[0]:
            # Migrate sources table to support youtube_channel, youtube_video, etc.
            await db.execute("ALTER TABLE sources RENAME TO sources_old")
            await db.executescript("""
                CREATE TABLE sources (
                    id               TEXT PRIMARY KEY,
                    url              TEXT NOT NULL UNIQUE,
                    type             TEXT NOT NULL,
                    name             TEXT NOT NULL,
                    feed_url         TEXT,
                    last_checked_at  TEXT,
                    last_seen_marker TEXT,
                    created_at       TEXT NOT NULL
                );
                INSERT INTO sources (id, url, type, name, feed_url, last_checked_at, last_seen_marker, created_at)
                SELECT id, url, type, name, feed_url, last_checked_at, last_seen_marker, created_at FROM sources_old;
                DROP TABLE sources_old;
            """)

        await db.executescript(_SCHEMA)

        # Check and migrate items columns if missing
        cursor = await db.execute("PRAGMA table_info(items)")
        cols = [r[1] for r in await cursor.fetchall()]
        if "thumbnail_url" not in cols:
            await db.execute("ALTER TABLE items ADD COLUMN thumbnail_url TEXT")
        if "is_video" not in cols:
            await db.execute("ALTER TABLE items ADD COLUMN is_video INTEGER DEFAULT 0")
        if "video_id" not in cols:
            await db.execute("ALTER TABLE items ADD COLUMN video_id TEXT")

        # Enable foreign keys (off by default in SQLite).
        await db.execute("PRAGMA foreign_keys = ON")
        await db.commit()


async def get_db() -> aiosqlite.Connection:
    """
    Return an open connection with row_factory set to aiosqlite.Row so
    results behave like dicts.  Callers are responsible for closing.
    """
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

async def upsert_source(url: str, source_type: str, name: str | None = None, feed_url: str | None = None) -> str:
    """
    Insert a source row if one doesn't already exist for *url*, and return
    its id either way. Safe to call on every poll — idempotent.
    """
    now = datetime.now(timezone.utc).isoformat()
    source_id = str(uuid.uuid5(uuid.NAMESPACE_URL, url))
    label = name or url
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO sources (id, url, type, name, feed_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                type = excluded.type,
                name = coalesce(excluded.name, sources.name),
                feed_url = coalesce(excluded.feed_url, sources.feed_url)
            """,
            (source_id, url, source_type, label, feed_url, now),
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM sources WHERE url = ?", (url,))
        row = await cursor.fetchone()
        return row["id"] if row else source_id
    finally:
        await db.close()


async def get_all_sources() -> list[dict]:
    """Return every stored source as a dict, for scheduled refresh."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM sources")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def delete_source(source_id: str) -> bool:
    """Delete a followed source by ID."""
    db = await get_db()
    try:
        cursor = await db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        await db.commit()
        return cursor.rowcount > 0
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# seen_urls helpers
# ---------------------------------------------------------------------------

async def mark_seen(source_id: str, urls: list[str]) -> None:
    """
    Bulk-insert URLs into seen_urls for *source_id*.
    Uses INSERT OR IGNORE so duplicates are silently skipped.
    """
    if not urls:
        return
    db = await get_db()
    try:
        await db.executemany(
            "INSERT OR IGNORE INTO seen_urls (source_id, url) VALUES (?, ?)",
            [(source_id, u) for u in urls],
        )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Source marker helpers
# ---------------------------------------------------------------------------

async def update_source_last_checked(source_id: str, last_seen_marker: str | None = None) -> None:
    """
    Update last_checked_at (always) and optionally last_seen_marker for a source.
    """
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        if last_seen_marker:
            await db.execute(
                """
                UPDATE sources
                SET last_checked_at = ?, last_seen_marker = ?
                WHERE id = ?
                """,
                (now, last_seen_marker, source_id),
            )
        else:
            await db.execute(
                "UPDATE sources SET last_checked_at = ? WHERE id = ?",
                (now, source_id),
            )
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Items helpers
# ---------------------------------------------------------------------------

async def save_processed_item(item: dict) -> str:
    """Insert or update a processed story item in the database."""
    item_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    db = await get_db()
    try:
        await db.execute(
            """
            INSERT INTO items (id, source_id, url, title, author, published_at, raw_text, summary, category, thumbnail_url, is_video, video_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'processed', ?)
            ON CONFLICT(source_id, url) DO UPDATE SET
                title = excluded.title,
                summary = excluded.summary,
                category = excluded.category,
                thumbnail_url = excluded.thumbnail_url,
                is_video = excluded.is_video,
                video_id = excluded.video_id,
                status = 'processed'
            """,
            (
                item_id,
                item.get("source_id", "default"),
                item.get("url"),
                item.get("title"),
                item.get("author"),
                item.get("published_date") or item.get("published_at"),
                item.get("text") or item.get("raw_text"),
                item.get("summary"),
                item.get("category"),
                item.get("thumbnail_url"),
                1 if item.get("is_video") else 0,
                item.get("video_id"),
                now,
            ),
        )
        await db.commit()
        return item_id
    finally:
        await db.close()


async def get_recent_processed_items(limit: int = 50) -> list[dict]:
    """Fetch the latest processed items across all followed sources."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT i.*, s.name as source_name, s.type as source_type
            FROM items i
            LEFT JOIN sources s ON i.source_id = s.id
            WHERE i.status = 'processed'
            ORDER BY i.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()

