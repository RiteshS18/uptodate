"""
Unit tests for app/fetcher.py feed and website polling logic.
"""

import pytest
import feedparser
from unittest.mock import patch, MagicMock, AsyncMock

from app.database import get_db, upsert_source, mark_seen
from app.fetcher import (
    fetch_new_items_rss,
    fetch_new_items_website,
    is_article_link,
)


def test_is_article_link():
    base = "example.com"
    # Valid article patterns
    assert is_article_link("https://example.com/blog/my-first-post", base) is True
    assert is_article_link("https://example.com/2026/04/article-title", base) is True
    assert is_article_link("https://example.com/news/tech-breakthrough", base) is True

    # Substack pattern
    assert is_article_link("https://example.substack.com/p/my-post", "example.substack.com") is True

    # Medium pattern
    assert is_article_link("https://medium.com/@author/great-story", "medium.com") is True

    # Non-article links
    assert is_article_link("https://example.com/about", base) is False
    assert is_article_link("https://example.com/contact", base) is False
    assert is_article_link("https://example.com/privacy", base) is False
    assert is_article_link("https://example.com/login", base) is False
    assert is_article_link("https://example.com/tag/ai", base) is False
    assert is_article_link("https://example.com/image.png", base) is False
    assert is_article_link("https://otherdomain.com/blog/post", base) is False


@pytest.mark.asyncio
async def test_rss_first_poll_no_marker(load_fixture):
    xml_data = load_fixture("rss_feed.xml")
    parsed_feed = feedparser.parse(xml_data)

    source_url = "https://example.com/rss.xml"
    source_id = await upsert_source(url=source_url, source_type="rss", name="Engineering Feed", feed_url=source_url)

    source = {
        "id": source_id,
        "url": source_url,
        "name": "Engineering Feed",
        "feed_url": source_url,
        "last_seen_marker": None,
    }

    with patch("feedparser.parse", return_value=parsed_feed):
        items = await fetch_new_items_rss(source)

    assert len(items) == 3
    assert items[0]["url"] == "https://example.com/blog/llm-pipelines"

    # Verify that seen_urls was populated in the database
    db = await get_db()
    cursor = await db.execute("SELECT url FROM seen_urls WHERE source_id = ?", (source_id,))
    seen = {row["url"] for row in await cursor.fetchall()}
    await db.close()

    assert len(seen) == 3
    assert "https://example.com/blog/llm-pipelines" in seen


@pytest.mark.asyncio
async def test_rss_incremental_poll_with_marker(load_fixture):
    xml_data = load_fixture("rss_feed.xml")
    parsed_feed = feedparser.parse(xml_data)

    source_url = "https://example.com/rss2.xml"
    source_id = await upsert_source(url=source_url, source_type="rss", name="Engineering Feed", feed_url=source_url)

    # Set marker to 2026-06-05 so that items from June 10 and June 15 are new, but June 01 is skipped
    source = {
        "id": source_id,
        "url": source_url,
        "name": "Engineering Feed",
        "feed_url": source_url,
        "last_seen_marker": "2026-06-05T00:00:00+00:00",
    }

    with patch("feedparser.parse", return_value=parsed_feed):
        items = await fetch_new_items_rss(source)

    assert len(items) == 2
    urls = [it["url"] for it in items]
    assert "https://example.com/blog/llm-pipelines" in urls
    assert "https://example.com/blog/sqlite-scaling" in urls
    assert "https://example.com/blog/vector-embeddings" not in urls


@pytest.mark.asyncio
async def test_rss_no_new_items(load_fixture):
    xml_data = load_fixture("rss_feed.xml")
    parsed_feed = feedparser.parse(xml_data)

    source_url = "https://example.com/rss3.xml"
    source_id = await upsert_source(url=source_url, source_type="rss", name="Engineering Feed", feed_url=source_url)

    # Pre-populate all URLs as seen
    await mark_seen(source_id, [
        "https://example.com/blog/llm-pipelines",
        "https://example.com/blog/sqlite-scaling",
        "https://example.com/blog/vector-embeddings",
    ])

    source = {
        "id": source_id,
        "url": source_url,
        "name": "Engineering Feed",
        "feed_url": source_url,
        "last_seen_marker": None,
    }

    with patch("feedparser.parse", return_value=parsed_feed):
        items = await fetch_new_items_rss(source)

    assert len(items) == 0


@pytest.mark.asyncio
async def test_website_poll(load_fixture):
    html = """
    <html>
        <body>
            <a href="/blog/post-1">Post 1</a>
            <a href="/blog/post-2">Post 2</a>
            <a href="/about">About Us</a>
        </body>
    </html>
    """
    source_url = "https://example.com"
    source_id = await upsert_source(url=source_url, source_type="website", name="Example Site")

    source = {
        "id": source_id,
        "url": source_url,
        "name": "Example Site",
    }

    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        items = await fetch_new_items_website(source)

    assert len(items) == 2
    urls = [it["url"] for it in items]
    assert "https://example.com/blog/post-1" in urls
    assert "https://example.com/blog/post-2" in urls

    # Second poll should return 0 new items because they were marked seen
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        items2 = await fetch_new_items_website(source)

    assert len(items2) == 0
