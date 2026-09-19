import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.youtube import extract_video_id, is_youtube_url, get_channel_rss_url
from app.dedup import deduplicate_and_cluster_stories
from app.chunker import chunk_text
from app.summarizer import generate_newsletter_digest


def test_youtube_url_detection_and_id_extraction():
    assert is_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_youtube_url("https://youtu.be/dQw4w9WgXcQ")
    assert is_youtube_url("https://www.youtube.com/@mkbhd")
    assert not is_youtube_url("https://example.com/article")

    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=42") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_get_channel_rss_url():
    feed_url = get_channel_rss_url("UCBJycsmduvYEL83R_U4JriQ")
    assert feed_url == "https://www.youtube.com/feeds/videos.xml?channel_id=UCBJycsmduvYEL83R_U4JriQ"


@pytest.mark.asyncio
async def test_deduplicate_identical_cross_source_articles():
    articles = [
        {
            "url": "https://www.theverge.com/apple-silicon-m4-review",
            "title": "Apple Silicon M4 Review: The Next Epoch in Neural Processing",
            "text": "Apple has officially unveiled the M4 processor with upgraded neural acceleration engines and increased unified memory bandwidth.",
            "summary": "M4 chip offers massive gains in AI inference speed and memory throughput.",
            "deck": "A revolutionary leap in high-efficiency mobile compute.",
            "takeaways": ["4x faster NPU processing", "50% higher memory bandwidth"],
            "category": "Technology & AI"
        },
        {
            "url": "https://www.youtube.com/watch?v=kCc8FmEb1nY",
            "title": "Apple Silicon M4 Review: The Next Epoch in Neural Processing",
            "text": "Apple has officially unveiled the M4 processor with upgraded neural acceleration engines and increased unified memory bandwidth.",
            "summary": "M4 chip offers massive gains in AI inference speed and memory throughput.",
            "deck": "A revolutionary leap in high-efficiency mobile compute.",
            "takeaways": ["Comprehensive teardown of NPU dies", "Liquid cooling performance benchmarks"],
            "category": "Technology & AI"
        }
    ]

    deduped = await deduplicate_and_cluster_stories(articles, similarity_threshold=0.80)
    assert len(deduped) == 1
    master = deduped[0]
    assert master["cross_source_count"] == 2
    assert len(master["related_sources"]) == 2
    assert any(s["url"] == "https://www.theverge.com/apple-silicon-m4-review" for s in master["related_sources"])
    assert any(s["url"] == "https://www.youtube.com/watch?v=kCc8FmEb1nY" for s in master["related_sources"])


@pytest.mark.asyncio
async def test_chunking_and_hierarchical_summarization():
    long_text = "This is an in-depth transcript paragraph about system architecture and distributed consensus. " * 120
    assert len(long_text) > 8000

    chunks = chunk_text(long_text, max_chars=3000, overlap=300)
    assert len(chunks) >= 2

    # Verify hierarchical summary synthesizes chunks
    briefing = await generate_newsletter_digest(long_text, title="Distributed Consensus Engine")
    assert briefing is not None
    assert "summary" in briefing
    assert "deck" in briefing
    assert "takeaways" in briefing
    assert len(briefing["takeaways"]) >= 1


def test_sources_api_crud(client):
    # Test POST /sources
    post_res = client.post(
        "/sources",
        json={
            "name": "MKBHD Channel",
            "url": "https://www.youtube.com/@mkbhd",
            "source_type": "youtube_channel"
        }
    )
    assert post_res.status_code == 200
    created = post_res.json()
    assert created["name"] == "MKBHD Channel"
    source_id = created["id"]

    # Test GET /sources
    get_res = client.get("/sources")
    assert get_res.status_code == 200
    sources = get_res.json()
    assert isinstance(sources, list)
    assert any(s["id"] == source_id for s in sources)

    # Test DELETE /sources/{id}
    del_res = client.delete(f"/sources/{source_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


def test_manual_refresh_endpoint(client):
    with patch("app.main.refresh_all_sources", new_callable=AsyncMock) as mock_refresh:
        mock_refresh.return_value = {
            "status": "success",
            "sources_checked": 3,
            "new_items_count": 2,
            "errors_count": 0,
        }
        resp = client.post("/refresh")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["sources_checked"] == 3
        assert data["new_items_count"] == 2
