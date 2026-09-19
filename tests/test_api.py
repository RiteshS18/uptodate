"""
Integration tests for FastAPI endpoints in app/main.py.
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.scraper import ExtractionFailed


def test_get_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "db_ok" in data
    assert "playwright_ok" in data
    assert data["db_ok"] is True


def test_post_extract_success(client):
    mock_result = {
        "title": "Test Title",
        "author": "Jane Doe",
        "date": "2026-05-01",
        "text": "This is a sufficiently long extracted article text containing substantive paragraphs of content.",
        "extraction_method": "trafilatura",
        "fetch_strategy": "direct",
    }
    with patch("app.main.scrape_url", new_callable=AsyncMock, return_value=mock_result):
        response = client.post("/extract", json={"url": "https://example.com/sample-article"})

    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://example.com/sample-article"
    assert data["title"] == "Test Title"
    assert data["author"] == "Jane Doe"
    assert data["published_date"] == "2026-05-01"
    assert data["extraction_method"] == "trafilatura"
    assert data["fetch_strategy"] == "direct"
    assert data["char_count"] == len(mock_result["text"])


def test_post_extract_no_content_failure(client):
    with patch("app.main.scrape_url", new_callable=AsyncMock) as mock_scrape:
        mock_scrape.side_effect = ExtractionFailed("no_content", "Page had <200 chars")
        response = client.post("/extract", json={"url": "https://example.com/empty-article"})

    assert response.status_code == 422
    data = response.json()
    assert data["url"] == "https://example.com/empty-article"
    assert data["error_code"] == "no_content"
    assert "Page had <200 chars" in data["detail"]


def test_post_extract_fetch_blocked_failure(client):
    with patch("app.main.scrape_url", new_callable=AsyncMock) as mock_scrape:
        mock_scrape.side_effect = ExtractionFailed("fetch_blocked", "All strategies 403")
        response = client.post("/extract", json={"url": "https://example.com/blocked-article"})

    assert response.status_code == 502
    data = response.json()
    assert data["url"] == "https://example.com/blocked-article"
    assert data["error_code"] == "fetch_blocked"


def test_post_source_check(client):
    mock_items = [
        {"url": "https://example.com/blog/article-1", "title": "Art 1"},
        {"url": "https://example.com/blog/article-2", "title": "Art 2"},
    ]
    with patch("app.main.fetch_new_items", new_callable=AsyncMock, return_value=mock_items):
        response = client.post(
            "/extract/source-check",
            json={"source_url": "https://example.com/feed.xml", "source_type": "rss"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["source_url"] == "https://example.com/feed.xml"
    assert len(data["new_item_urls"]) == 2
    assert "https://example.com/blog/article-1" in data["new_item_urls"]
    assert "checked_at" in data


def test_post_batch_extract(client):
    async def side_effect(url):
        if "fail" in url:
            raise ExtractionFailed("no_content", "Empty content")
        return {
            "title": "Success Title",
            "author": "Author",
            "date": "2026-01-01",
            "text": "Valid body text exceeding minimum threshold requirements.",
            "extraction_method": "trafilatura",
            "fetch_strategy": "direct",
        }

    with patch("app.main.scrape_url", side_effect=side_effect):
        response = client.post(
            "/extract/batch",
            json={
                "urls": [
                    "https://example.com/success-1",
                    "https://example.com/fail-2",
                    "https://example.com/success-3",
                ],
                "max_concurrency": 2,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success_count"] == 2
    assert data["failure_count"] == 1
    assert len(data["results"]) == 3
