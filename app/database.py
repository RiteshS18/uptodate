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
    type             TEXT NOT NULL CHECK (type IN ('rss', 'website')),
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
    """Create tables if they don't exist. Called once at app startup."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
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
    its id either way.  Safe to call on every poll — idempotent.

    Args:
        url:         The homepage or feed URL (used as the unique key).
        source_type: 'rss' or 'website'.
        name:        Human-readable label (defaults to the URL itself).
        feed_url:    Pre-discovered feed URL (only for rss sources).

    Returns:
        The source's UUID string.
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
            ON CONFLICT(url) DO NOTHING
            """,
            (source_id, url, source_type, label, feed_url, now),
        )
        await db.commit()
        # Re-fetch in case another source_id was already stored for this URL.
        cursor = await db.execute("SELECT id FROM sources WHERE url = ?", (url,))
        row = await cursor.fetchone()
        return row["id"] if row else source_id
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

    Args:
        source_id:         The source UUID.
        last_seen_marker:  ISO-8601 datetime string of the newest item seen
                           (pass None to only update last_checked_at).
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

