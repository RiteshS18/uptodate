"""
Main FastAPI application for the Backstory text-extraction service.

Exposes endpoints for:
- POST /extract: Single URL text extraction with full strategy cascade.
- POST /extract/source-check: Cheap "what's new" poll for RSS feeds or website homepages.
- POST /extract/batch: Concurrent extraction of multiple article URLs.
- POST /scrape: Legacy universal endpoint for backwards compatibility.
- GET /health: Health check reporting DB and Playwright availability.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from app.database import get_db, init_db, upsert_source
from app.feed_discovery import discover_feed
from app.fetcher import fetch_new_items, is_article_link
from app.models import (
    ArticleResult,
    BatchExtractRequest,
    BatchExtractResponse,
    ErrorCode,
    ExtractionError,
    ExtractRequest,
    HealthResponse,
    LegacyArticleResult,
    LegacyScrapeResponse,
    ScrapeRequest,
    SourceCheckRequest,
    SourceCheckResponse,
)
from app.scraper import (
    ExtractionFailed,
    _extract_substack,
    _extract_with_trafilatura,
    fetch_html,
    scrape_url,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure database schema is initialized on application startup."""
    logger.info("Initializing database schema...")
    await init_db()
    yield
    logger.info("Application shutdown.")


app = FastAPI(
    title="Backstory Text Extraction Service",
    description=(
        "Production-ready text extraction service for Backstory. "
        "Extracts clean, structured article text from RSS feeds, Substack, "
        "Ghost, WordPress, and arbitrary web pages."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_article_links(html: str, base_url: str) -> list[str]:
    """Extract unique article-like links from a webpage HTML."""
    base_domain = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[str] = []

    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        parsed = urlparse(href)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        if normalized not in seen and is_article_link(href, base_domain):
            seen.add(normalized)
            links.append(normalized)

    return links


async def _scrape_one_legacy(url: str) -> LegacyArticleResult | None:
    """Scrape a single article URL for the legacy endpoint, returning None on failure."""
    try:
        article = await scrape_url(url)
        text = article.get("text", "").strip()
        if not text:
            return None
        return LegacyArticleResult(
            url=url,
            title=article.get("title"),
            author=article.get("author"),
            published_date=article.get("date"),
            text=text,
            char_count=len(text),
        )
    except Exception as exc:
        logger.warning("Failed to scrape %s: %s", url, exc)
        return None


def _check_playwright_available() -> bool:
    """Check if Playwright chromium browser executable exists on disk."""
    try:
        from playwright.sync_api import sync_playwright
        import os
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            return bool(exe and os.path.exists(exe))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# POST /extract — Single URL Extraction
# ---------------------------------------------------------------------------

@app.post(
    "/extract",
    response_model=ArticleResult,
    responses={
        422: {"model": ExtractionError, "description": "No readable content could be extracted."},
        502: {"model": ExtractionError, "description": "Site blocked requests or DNS failure."},
        504: {"model": ExtractionError, "description": "Request timed out fetching URL."},
    },
    summary="Extract clean article text from a single URL",
    description=(
        "Fetches an article webpage using multi-strategy fallback "
        "(direct -> Google Cache -> Wayback -> Playwright) and extracts "
        "clean structured article text (Substack NEXT_DATA -> trafilatura -> BS4)."
    ),
)
async def extract(request: ExtractRequest):
    url_str = str(request.url)
    try:
        res = await scrape_url(url_str)
        return ArticleResult(
            url=url_str,
            title=res.get("title"),
            author=res.get("author"),
            published_date=res.get("date"),
            text=res.get("text", ""),
            char_count=len(res.get("text", "")),
            extraction_method=res.get("extraction_method"),
            fetch_strategy=res.get("fetch_strategy"),
        )
    except ExtractionFailed as e:
        status_code = 422 if e.error_code == "no_content" else (504 if e.error_code == "timeout" else 502)
        err_code = ErrorCode(e.error_code) if e.error_code in [m.value for m in ErrorCode] else ErrorCode.parse_error
        return JSONResponse(
            status_code=status_code,
            content=ExtractionError(
                url=url_str,
                error_code=err_code,
                detail=e.detail,
            ).model_dump(),
        )
    except Exception as e:
        logger.error("Unexpected error extracting %s: %s", url_str, e, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ExtractionError(
                url=url_str,
                error_code=ErrorCode.parse_error,
                detail=str(e),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /extract/source-check — "What's New" Polling
# ---------------------------------------------------------------------------

@app.post(
    "/extract/source-check",
    response_model=SourceCheckResponse,
    summary="Poll a source for new/unseen article URLs",
    description=(
        "Checks an RSS feed or website homepage for articles that have not "
        "been seen previously in the database, marks them as seen, and updates markers."
    ),
)
async def source_check(request: SourceCheckRequest):
    url_str = str(request.source_url)
    source_type = request.source_type

    feed_url = url_str if source_type == "rss" else None
    source_id = await upsert_source(
        url=url_str,
        source_type=source_type,
        name=url_str,
        feed_url=feed_url,
    )

    source_dict = {
        "id": source_id,
        "url": url_str,
        "type": source_type,
        "name": url_str,
        "feed_url": feed_url or url_str,
        "last_seen_marker": None,
    }

    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM sources WHERE id = ?", (source_id,))
        row = await cursor.fetchone()
        if row:
            source_dict["last_seen_marker"] = row["last_seen_marker"]
            if row["feed_url"]:
                source_dict["feed_url"] = row["feed_url"]
    finally:
        await db.close()

    if source_type == "rss" and not source_dict.get("feed_url"):
        discovered = await discover_feed(url_str)
        source_dict["feed_url"] = discovered or url_str

    items = await fetch_new_items(source_dict)
    new_urls = [item["url"] for item in items if item.get("url")]

    return SourceCheckResponse(
        source_url=url_str,
        new_item_urls=new_urls,
        checked_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# POST /extract/batch — Concurrent Multi-URL Extraction
# ---------------------------------------------------------------------------

@app.post(
    "/extract/batch",
    response_model=BatchExtractResponse,
    summary="Batch extract multiple article URLs in parallel",
    description="Extracts clean text from a list of URLs concurrently up to max_concurrency workers.",
)
async def extract_batch(request: BatchExtractRequest):
    semaphore = asyncio.Semaphore(request.max_concurrency)

    async def _extract_single(url_str: str) -> ArticleResult | ExtractionError:
        async with semaphore:
            try:
                res = await scrape_url(url_str)
                return ArticleResult(
                    url=url_str,
                    title=res.get("title"),
                    author=res.get("author"),
                    published_date=res.get("date"),
                    text=res.get("text", ""),
                    char_count=len(res.get("text", "")),
                    extraction_method=res.get("extraction_method"),
                    fetch_strategy=res.get("fetch_strategy"),
                )
            except ExtractionFailed as e:
                err_code = ErrorCode(e.error_code) if e.error_code in [m.value for m in ErrorCode] else ErrorCode.parse_error
                return ExtractionError(
                    url=url_str,
                    error_code=err_code,
                    detail=e.detail,
                )
            except Exception as e:
                return ExtractionError(
                    url=url_str,
                    error_code=ErrorCode.parse_error,
                    detail=str(e),
                )

    tasks = [_extract_single(str(u)) for u in request.urls]
    results = await asyncio.gather(*tasks)

    success_count = sum(1 for r in results if isinstance(r, ArticleResult))
    failure_count = len(results) - success_count

    return BatchExtractResponse(
        results=results,
        success_count=success_count,
        failure_count=failure_count,
    )


# ---------------------------------------------------------------------------
# POST /scrape — Legacy Backward-Compatible Endpoint
# ---------------------------------------------------------------------------

@app.post(
    "/scrape",
    response_model=LegacyScrapeResponse,
    summary="Legacy scrape endpoint for backwards compatibility",
    description="Extract content from a single article or blog homepage.",
)
async def scrape_legacy(
    request: ScrapeRequest,
    max_articles: int = Query(default=50, ge=1, le=200, description="Max articles to scrape from a site"),
    concurrency: int = Query(default=5, ge=1, le=20, description="Parallel scrape workers"),
):
    url = str(request.url)

    # Step 1: fetch page HTML
    try:
        html, _ = await fetch_html(url)
    except ExtractionFailed as e:
        if e.error_code == "fetch_blocked":
            raise HTTPException(
                status_code=403,
                detail="Site is blocking scrapers (403 Forbidden). Try a direct article URL.",
            )
        raise HTTPException(status_code=502, detail=e.detail)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Site returned HTTP {e.response.status_code}.")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach URL: {e}")

    # Step 2: check if it's a single article
    direct = _extract_substack(html) or _extract_with_trafilatura(html)
    direct_text = (direct or {}).get("text", "").strip()

    if len(direct_text) > 500:
        logger.info("Treating %s as a single article (%d chars)", url, len(direct_text))
        return LegacyScrapeResponse(
            source_url=url,
            article_count=1,
            articles=[
                LegacyArticleResult(
                    url=url,
                    title=(direct or {}).get("title"),
                    author=(direct or {}).get("author"),
                    published_date=(direct or {}).get("date"),
                    text=direct_text,
                    char_count=len(direct_text),
                )
            ],
        )

    # Step 3: discover article links
    logger.info("Treating %s as a site — discovering articles...", url)
    article_urls: list[str] = []

    feed_url = await discover_feed(url)
    if feed_url:
        logger.info("Found feed: %s", feed_url)
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:max_articles]:
            link = entry.get("link", "")
            if link:
                article_urls.append(link)

    if not article_urls:
        logger.info("No feed found — scraping homepage links")
        article_urls = _collect_article_links(html, url)[:max_articles]

    if not article_urls:
        raise HTTPException(
            status_code=422,
            detail="Could not discover any article links on this page.",
        )

    # Step 4: scrape all articles concurrently
    semaphore = asyncio.Semaphore(concurrency)

    async def _scrape_limited(u: str) -> LegacyArticleResult | None:
        async with semaphore:
            return await _scrape_one_legacy(u)

    results = await asyncio.gather(*[_scrape_limited(u) for u in article_urls])
    articles = [r for r in results if r is not None]

    if not articles:
        raise HTTPException(
            status_code=422,
            detail="Discovered article links but could not extract content from any of them.",
        )

    return LegacyScrapeResponse(
        source_url=url,
        article_count=len(articles),
        articles=articles,
    )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the service health status, version, SQLite DB status, and Playwright availability.",
)
async def health():
    db_ok = False
    try:
        db = await get_db()
        cursor = await db.execute("SELECT 1")
        row = await cursor.fetchone()
        if row and row[0] == 1:
            db_ok = True
        await db.close()
    except Exception as exc:
        logger.warning("Database health check failed: %s", exc)
        db_ok = False

    playwright_ok = _check_playwright_available()

    return HealthResponse(
        status="ok",
        version=app.version,
        db_ok=db_ok,
        playwright_ok=playwright_ok,
    )
