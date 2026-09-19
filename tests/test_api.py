"""
Integration tests for FastAPI endpoints in app/main.py.
"""

import pytest
from unittest.mock import patch, AsyncMock
from app.scraper import ExtractionFailed


def test_get_root_serves_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "The Backstory Chronicle" in response.text


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
        "text": "This is a sufficiently long extracted article text containing substantive paragraphs of content with in-depth analysis and insightful reporting on modern technological advances across multiple industries.",
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
        if "success-1" in url:
            return {
                "title": "Quantum Photonics Breakthrough in Silicon Processors",
                "author": "Dr. Vance",
                "date": "2026-01-01",
                "text": "Researchers have discovered a scalable technique to fabricate laser emitters directly into standard 3nm semiconductor nodes, drastically reducing interconnect latency and power consumption across modern enterprise server datacenters worldwide.",
                "extraction_method": "trafilatura",
                "fetch_strategy": "direct",
            }
        return {
            "title": "Deep Sea Marine Biology in Mariana Trench",
            "author": "Oceanographer Jane",
            "date": "2026-01-01",
            "text": "Explorers discovered a new bioluminescent species living near hydrothermal vents at depths exceeding ten thousand meters below sea level, showing unprecedented metabolic pathways under extreme atmospheric pressures.",
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


def test_post_extract_listing_page(client):
    listing_html = """
    <html>
      <body>
        <h1>Web Series Listing</h1>
        <div><a href="https://example.com/entertainment/emily-in-paris-season-5-review-article-12345678">Emily in Paris Season 5 Review</a></div>
        <div><a href="https://example.com/entertainment/indias-got-latent-episode-2-review-article-87654321">India's Got Latent 2</a></div>
        <div><a href="https://example.com/entertainment/the-early-spring-trailer-breakdown-article-99999999">The Early Spring Breakdown</a></div>
      </body>
    </html>
    """
    async def mock_scrape(url):
        if url == "https://example.com/entertainment/web-series":
            return {
                "title": None,
                "author": None,
                "date": None,
                "text": "",
                "is_listing": True,
                "html": listing_html,
                "extraction_method": "listing_detector",
                "fetch_strategy": "direct",
            }
        return {
            "title": f"Story: {url.split('/')[-1]}",
            "author": "Staff Reviewer",
            "date": "2026-09-19",
            "text": "A full-length substantive critique with multiple comprehensive paragraphs of analysis detailing the narrative arc, directing style, cinematography, and performances across the season.",
            "extraction_method": "trafilatura",
            "fetch_strategy": "direct",
        }

    with patch("app.main.scrape_url", side_effect=mock_scrape):
        response = client.post("/extract", json={"url": "https://example.com/entertainment/web-series"})

    assert response.status_code == 200
    data = response.json()
    assert data["is_listing"] is True
    assert data["article_count"] >= 3
    assert len(data["articles"]) >= 3
    for art in data["articles"]:
        assert art["url"].startswith("https://example.com/entertainment/")
        assert art["summary"] is not None


@pytest.mark.asyncio
async def test_refresh_all_sources_function():
    from app.main import refresh_all_sources

    mock_sources = [
        {
            "id": "src-1",
            "url": "https://example.com/feed1.xml",
            "type": "rss",
            "name": "Feed 1",
            "feed_url": "https://example.com/feed1.xml",
            "last_seen_marker": "marker-1",
        },
        {
            "id": "src-2",
            "url": "https://example.com/blog",
            "type": "website",
            "name": "Blog",
            "feed_url": None,
            "last_seen_marker": None,
        },
        {
            "id": "src-3",
            "url": "https://failing-site.com",
            "type": "website",
            "name": "Failing",
            "feed_url": None,
            "last_seen_marker": None,
        },
    ]

    async def mock_fetch(source_dict):
        if "failing" in source_dict["url"]:
            raise RuntimeError("Connection timed out")
        if source_dict["id"] == "src-1":
            return [{"url": "https://example.com/post1"}, {"url": "https://example.com/post2"}]
        return [{"url": "https://example.com/blog/1"}]

    with patch("app.main.get_all_sources", new_callable=AsyncMock, return_value=mock_sources), \
         patch("app.main.fetch_new_items", side_effect=mock_fetch):
        results = await refresh_all_sources()

    assert results["https://example.com/feed1.xml"] == 2
    assert results["https://example.com/blog"] == 1
    assert results["https://failing-site.com"] == "error"


def test_post_refresh_all_endpoint(client):
    mock_results = {
        "https://example.com/rss": 3,
        "https://news.ycombinator.com": 0,
        "https://failing-domain.org": "error",
    }
    with patch("app.main.refresh_all_sources", new_callable=AsyncMock, return_value=mock_results):
        response = client.post("/refresh-all")

    assert response.status_code == 200
    data = response.json()
    assert data["https://example.com/rss"] == 3
    assert data["https://news.ycombinator.com"] == 0
    assert data["https://failing-domain.org"] == "error"


def test_scheduler_status(client):
    response = client.get("/scheduler")
    assert response.status_code == 200
    data = response.json()
    assert "running" in data
    assert data["interval"] == "30 minutes"
    assert data["job_id"] == "refresh_all"
