"""
RSS/Atom feed auto-discovery.

Given a website URL, tries to find the corresponding feed URL by:
1. Parsing <link rel="alternate"> tags in the page HTML.
2. Probing common feed paths (/feed, /rss.xml, etc.) with HEAD then GET.
"""

import logging
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.scraper import HEADERS, TIMEOUT

logger = logging.getLogger(__name__)

# Common feed paths to probe when <link> discovery fails.
_COMMON_FEED_PATHS = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss.xml",
    "/atom.xml",
    "/feed.xml",
    "/index.xml",
    "/feeds/posts/default",   # Blogger
    "/?feed=rss2",            # WordPress
    "/feed.json",             # JSON Feed
    "/blog/feed",
    "/blog/rss",
    "/news/feed",
    "/posts/feed",
    "/api/rss",               # Ghost (some configs)
]

# Content-Type substrings that indicate a valid feed response.
_FEED_CONTENT_TYPES = (
    "xml", "rss", "atom",
    "text/xml", "application/xml",
    "application/json",       # JSON Feed
)

# First 2 KB to check for feed marker tags (for GET fallback validation).
_FEED_MARKERS = ("<rss", "<feed", "<channel", "\"version\": \"https://jsonfeed.org")


async def _fetch_page(url: str) -> str | None:
    """Fetch HTML, returning None on failure instead of raising."""
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers=HEADERS, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("Failed to fetch %s for feed discovery: %s", url, exc)
        return None


async def _probe_path(base_url: str, path: str) -> str | None:
    """
    Check whether *base_url + path* looks like a feed.

    Strategy:
      1. Send a HEAD request — fast, avoids downloading the body.
      2. If the server returns 405 Method Not Allowed, fall back to a GET
         and inspect the first 2 KB of the body for feed marker tags.
         (Needed for Substack, Ghost, and many CDN-fronted sites.)
    """
    candidate = urljoin(base_url, path)
    try:
        async with httpx.AsyncClient(
            timeout=8, headers=HEADERS, follow_redirects=True
        ) as client:
            try:
                resp = await client.head(candidate)
            except httpx.RequestError:
                return None

            if resp.status_code == 405:
                # HEAD not allowed — try GET with a small read window.
                try:
                    get_resp = await client.get(candidate)
                    if get_resp.status_code != 200:
                        return None
                    ct = get_resp.headers.get("content-type", "").lower()
                    snippet = get_resp.text[:2048].lower()
                    if any(t in ct for t in _FEED_CONTENT_TYPES) or any(
                        m in snippet for m in _FEED_MARKERS
                    ):
                        logger.debug("Feed confirmed via GET fallback: %s", candidate)
                        return candidate
                except httpx.RequestError:
                    pass
                return None

            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "").lower()
                if any(t in ct for t in _FEED_CONTENT_TYPES):
                    return candidate

    except (httpx.HTTPStatusError, httpx.RequestError):
        pass
    return None


async def discover_feed(url: str) -> str | None:
    """
    Try to find an RSS, Atom, or JSON Feed URL for the given website.

    Returns the feed URL if found, or None if no feed could be discovered.
    """
    html = await _fetch_page(url)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        # Look for <link rel="alternate" type="application/rss+xml" ...>
        # and  <link rel="alternate" type="application/atom+xml" ...>
        # and  <link rel="alternate" type="application/json" ...> (JSON Feed)
        for link in soup.find_all("link", rel="alternate"):
            link_type = (link.get("type") or "").lower()
            href = link.get("href")
            if href and any(t in link_type for t in ("rss", "atom", "json")):
                feed_url = urljoin(url, href)
                logger.info("Discovered feed via <link> tag: %s", feed_url)
                return feed_url

    # Fallback: probe common paths.
    for path in _COMMON_FEED_PATHS:
        result = await _probe_path(url, path)
        if result:
            logger.info("Discovered feed via path probing: %s", result)
            return result

    logger.info("No feed discovered for %s", url)
    return None
