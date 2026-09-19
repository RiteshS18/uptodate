"""
Fetch-what's-new logic for RSS and website sources.

For RSS sources: parses the feed and compares entries against the stored
last_seen_marker + seen_urls to yield only truly new items, then marks
those URLs as seen and updates the source's last_seen_marker.

For website sources: scrapes the homepage, extracts article-like links,
diffs against the stored seen_urls set, then marks new links as seen.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from time import mktime
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.database import get_db, mark_seen, update_source_last_checked
from app.scraper import HEADERS, TIMEOUT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Path segments that almost never point to articles.
_SKIP_SEGMENTS = {
    "about", "contact", "privacy", "terms", "login", "signup", "register",
    "search", "tag", "tags", "category", "categories", "author", "authors",
    "page", "cart", "checkout", "account", "faq", "help", "sitemap",
    "subscribe", "unsubscribe", "wp-login", "wp-admin", "archive",
    "newsletter", "feed", "rss", "atom", "video", "videos", "photo", "photos",
    "live", "trending", "web-stories", "info", "advertise", "apps", "app",
    "topic", "topics", "section", "sections", "shows", "show", "hub", "hubs",
}

# Platforms where depth-1 paths (e.g. /post-slug) are valid articles.
_DEPTH1_PLATFORMS = {
    "substack.com",
    "medium.com",
    "ghost.io",
    "beehiiv.com",
    "buttondown.email",
    "mailchimp.com",
    "convertkit.com",
    "revue.co",
    "tinyletter.com",
}


def is_article_link(href: str, base_domain: str) -> bool:
    """Heuristic: does this URL look like an article on the same domain?"""
    parsed = urlparse(href)

    # Must be same domain (or relative link that was already resolved).
    if parsed.netloc and parsed.netloc.replace("www.", "") != base_domain.replace("www.", ""):
        return False

    path = parsed.path.rstrip("/")
    if not path or path == "/":
        return False

    # Reject obvious file types.
    if re.search(r"\.(css|js|png|jpg|jpeg|gif|svg|ico|pdf|zip|xml|json|webp|mp4|mp3)$", path, re.I):
        return False

    segments = [s for s in path.split("/") if s]
    if not segments:
        return False

    # Skip if any segment is a known non-article keyword.
    if any(seg.lower() in _SKIP_SEGMENTS for seg in segments):
        return False

    last_seg = segments[-1].lower()

    # Substack: allow /p/<slug>  (depth 2 starting with 'p')
    if len(segments) == 2 and segments[0].lower() == "p":
        return True

    # Medium: allow /@user/<slug> or /<slug>-<hash> patterns
    if len(segments) == 2 and segments[0].startswith("@"):
        return True

    # Check if last segment is a specific article slug
    is_slug = ("-" in last_seg and len(last_seg) >= 5) or bool(re.search(r"(?:article|story|post|news|\d{3,})", last_seg, re.I))

    # For known newsletter/blog platforms, allow depth 1 (single slug)
    bare_domain = base_domain.replace("www.", "")
    if any(bare_domain == p or bare_domain.endswith("." + p) for p in _DEPTH1_PLATFORMS):
        return len(segments) >= 1 and (len(last_seg) >= 5 or is_slug)

    # General news and blog sites require at least depth 2 or an explicit article slug
    if len(segments) < 2:
        return ("-" in last_seg and len(last_seg) >= 18)

    return is_slug


# Keep the private alias so any existing callers aren't broken.
_is_article_link = is_article_link


def _entry_published_dt(entry) -> datetime | None:
    """Extract a timezone-aware datetime from a feedparser entry, or None."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc)
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime.fromtimestamp(mktime(entry.updated_parsed), tz=timezone.utc)
    return None


def _entry_id(entry) -> str:
    """Stable identifier for a feed entry (guid > link > title)."""
    return entry.get("id") or entry.get("link") or entry.get("title", "")


# ---------------------------------------------------------------------------
# RSS / Atom fetcher
# ---------------------------------------------------------------------------

async def fetch_new_items_rss(source: dict) -> list[dict]:
    """
    Parse the feed and return items newer than the stored marker.

    After returning, marks all new URLs as seen in ``seen_urls`` and
    updates the source's ``last_seen_marker`` to the newest item's
    ``published_at`` (if available).

    Each returned dict has keys: url, title, author, published_at.
    """
    feed_url = source["feed_url"]
    source_id = source["id"]
    last_marker = source.get("last_seen_marker")

    # feedparser is synchronous — acceptable for typical feed sizes.
    feed = feedparser.parse(feed_url)

    if feed.bozo and not feed.entries:
        logger.warning("Feed parse error for %s: %s", feed_url, feed.bozo_exception)
        return []

    # Load existing seen URLs for this source.
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT url FROM seen_urls WHERE source_id = ?", (source_id,)
        )
        seen: set[str] = {row["url"] for row in await cursor.fetchall()}
    finally:
        await db.close()

    # Determine the marker datetime for comparison.
    marker_dt: datetime | None = None
    if last_marker:
        try:
            marker_dt = datetime.fromisoformat(last_marker)
        except ValueError:
            marker_dt = None

    new_items: list[dict] = []
    for entry in feed.entries:
        link = entry.get("link", "")
        if not link or link in seen:
            continue

        pub_dt = _entry_published_dt(entry)

        # If we have a date-based marker, skip entries at or before it.
        if marker_dt and pub_dt and pub_dt <= marker_dt:
            continue

        new_items.append({
            "url":          link,
            "title":        entry.get("title"),
            "author":       entry.get("author"),
            "published_at": pub_dt.isoformat() if pub_dt else None,
        })

    # Sort newest-first so the caller can easily pick the top marker.
    new_items.sort(
        key=lambda x: x.get("published_at") or "",
        reverse=True,
    )

    logger.info("RSS source %s: %d new items found", source["name"], len(new_items))

    if new_items:
        # Persist seen URLs so future polls don't re-return the same items.
        await mark_seen(source_id, [item["url"] for item in new_items])

        # Advance the marker to the newest item's published_at (if dated).
        newest_marker = new_items[0].get("published_at")
        await update_source_last_checked(source_id, last_seen_marker=newest_marker)
    else:
        await update_source_last_checked(source_id)

    return new_items


# ---------------------------------------------------------------------------
# Website (no-feed) fetcher
# ---------------------------------------------------------------------------

async def fetch_new_items_website(source: dict) -> list[dict]:
    """
    Scrape the homepage and return article links not previously seen.

    After returning, marks all new URLs as seen in ``seen_urls``.
    """
    source_id = source["id"]
    url = source["url"]
    base_domain = urlparse(url).netloc

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers=HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("Failed to fetch homepage %s: %s", url, exc)
        return []

    soup = BeautifulSoup(html, "html.parser")
    seen_normalized: set[str] = set()   # dedup within this crawl
    candidate_links: list[str] = []

    for a_tag in soup.find_all("a", href=True):
        href = urljoin(url, a_tag["href"])
        if is_article_link(href, base_domain):
            parsed = urlparse(href)
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
            if normalized not in seen_normalized:
                seen_normalized.add(normalized)
                candidate_links.append(normalized)

    # Diff against seen_urls in the database.
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT url FROM seen_urls WHERE source_id = ?", (source_id,)
        )
        db_seen: set[str] = {row["url"] for row in await cursor.fetchall()}
    finally:
        await db.close()

    new_items: list[dict] = []
    for link in candidate_links:
        if link not in db_seen:
            new_items.append({
                "url":          link,
                "title":        None,   # will be filled during scraping
                "author":       None,
                "published_at": None,
            })

    logger.info("Website source %s: %d new links found", source["name"], len(new_items))

    if new_items:
        await mark_seen(source_id, [item["url"] for item in new_items])

    await update_source_last_checked(source_id)
    return new_items


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

async def fetch_new_items(source: dict) -> list[dict]:
    """Route to the correct fetcher based on source type."""
    src_type = source.get("type", "website")
    url = source.get("url", "")

    if src_type in ("youtube_channel", "youtube") or "youtube.com" in url or "youtu.be" in url:
        from app.youtube import resolve_channel_id, get_channel_rss_url
        if not source.get("feed_url") or "youtube.com/feeds/videos.xml" not in source.get("feed_url", ""):
            channel_id = await resolve_channel_id(url)
            if channel_id:
                source["feed_url"] = get_channel_rss_url(channel_id)
        if source.get("feed_url"):
            return await fetch_new_items_rss(source)
        return []

    if src_type == "rss":
        return await fetch_new_items_rss(source)
    else:
        return await fetch_new_items_website(source)
