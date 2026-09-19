"""
Unit tests for app/scraper.py extraction logic and strategy cascading.
"""

import pytest
from unittest.mock import AsyncMock, patch
from bs4 import BeautifulSoup

from app.scraper import (
    ExtractionFailed,
    _extract_substack,
    _extract_with_trafilatura,
    _extract_with_bs4,
    _strip_boilerplate,
    scrape_url,
)


def test_extract_substack_next_data(load_fixture):
    html = load_fixture("substack_post.html")
    result = _extract_substack(html)

    assert result is not None
    assert result["title"] == "The Future of AI Hardware Acceleration"
    assert result["author"] == "Carol Danvers"
    assert result["date"] == "2026-06-01"
    assert "Accelerated computing has fundamentally shifted" in result["text"]
    assert "memory bandwidth" in result["text"]


def test_extract_wordpress_trafilatura(load_fixture):
    html = load_fixture("wordpress_post.html")
    result = _extract_with_trafilatura(html)

    assert result is not None
    assert "Modern Neural Architectures" in (result.get("title") or "")
    assert "multi-head self-attention" in result.get("text", "")


def test_extract_ghost_trafilatura(load_fixture):
    html = load_fixture("ghost_post.html")
    result = _extract_with_trafilatura(html)

    assert result is not None
    assert "Building Resilient Distributed Systems" in (result.get("title") or "")
    assert "consensus algorithms" in result.get("text", "")


def test_extract_medium(load_fixture):
    html = load_fixture("medium_post.html")
    result = _extract_with_trafilatura(html)
    text = result.get("text", "") or _extract_with_bs4(html)

    assert "Mastering Asyncio" in (result.get("title") or "") or "Asyncio" in text
    assert "structured concurrency" in text


def test_extract_newspaper(load_fixture):
    html = load_fixture("newspaper_article.html")
    result = _extract_with_trafilatura(html)
    text = result.get("text", "") or _extract_with_bs4(html)

    assert "Climate Accord" in (result.get("title") or "") or "Climate Accord" in text
    assert "renewable energy transitions" in text


def test_boilerplate_stripped(load_fixture):
    html = load_fixture("wordpress_post.html")
    soup = BeautifulSoup(html, "html.parser")
    _strip_boilerplate(soup)
    cleaned_text = soup.get_text()

    # Boilerplate elements should be stripped
    assert "We use cookies to ensure you get the best experience" not in cleaned_text
    assert "Subscribe to our newsletter!" not in cleaned_text
    assert "Share on Twitter" not in cleaned_text
    assert "Great post! Thanks for sharing." not in cleaned_text


@pytest.mark.asyncio
async def test_no_content_raises_error(load_fixture):
    html = load_fixture("empty_page.html")
    with patch("app.scraper.fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (html, "direct")
        with pytest.raises(ExtractionFailed) as exc_info:
            await scrape_url("https://example.com/empty")

        assert exc_info.value.error_code == "no_content"


@pytest.mark.asyncio
async def test_scrape_url_reports_method_and_strategy(load_fixture):
    html = load_fixture("substack_post.html")
    with patch("app.scraper.fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (html, "direct")
        res = await scrape_url("https://example.com/substack-post")

        assert res["extraction_method"] == "substack_next_data"
        assert res["fetch_strategy"] == "direct"
        assert res["title"] == "The Future of AI Hardware Acceleration"
        assert len(res["text"]) >= 200
