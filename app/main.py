"""
Main FastAPI application for the Backstory text-extraction service & newspaper UI.

Exposes endpoints for:
- GET /: Interactive Newspaper & Newsletter frontpage interface.
- POST /extract: Single URL text extraction with full strategy cascade.
- POST /extract/source-check: Cheap "what's new" poll for RSS feeds or website homepages.
- POST /extract/batch: Concurrent extraction of multiple article URLs.
- POST /scrape: Legacy universal endpoint for backwards compatibility.
- GET /health: Health check reporting DB and Playwright availability.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import (
    delete_source,
    get_all_sources,
    get_db,
    get_recent_processed_items,
    init_db,
    save_processed_item,
    upsert_source,
)
from app.dedup import deduplicate_and_cluster_stories
from app.feed_discovery import discover_feed
from app.fetcher import fetch_new_items, is_article_link
from app.models import (
    ArticleResult,
    BatchExtractRequest,
    BatchExtractResponse,
    CreateSourceRequest,
    ErrorCode,
    ExtractionError,
    ExtractRequest,
    HealthResponse,
    LegacyArticleResult,
    LegacyScrapeResponse,
    RefreshResponse,
    RelatedSource,
    ScrapeRequest,
    SourceCheckRequest,
    SourceCheckResponse,
    SourceModel,
)
from app.noise_filter import noise_filter
from app.scraper import (
    ExtractionFailed,
    _extract_substack,
    _extract_with_trafilatura,
    fetch_html,
    is_listing_page,
    scrape_url,
)
from app.summarizer import generate_newsletter_digest
from app.youtube import is_youtube_url, resolve_channel_id, get_channel_rss_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def refresh_all_sources() -> dict:
    """Check every stored source for new items. Called by both cron and manual trigger."""
    sources = await get_all_sources()
    results = {}
    for source in sources:
        source_dict = {
            "id": source["id"],
            "url": source["url"],
            "type": source["type"],
            "name": source["name"],
            "feed_url": source["feed_url"] or source["url"],
            "last_seen_marker": source["last_seen_marker"],
        }
        try:
            items = await fetch_new_items(source_dict)
            results[source["url"]] = len(items)
        except Exception as e:
            logger.error("Scheduled refresh failed for %s: %s", source["url"], e)
            results[source["url"]] = "error"
    return results


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database schema...")
    await init_db()
    scheduler.add_job(refresh_all_sources, "interval", minutes=30, id="refresh_all")
    scheduler.start()
    yield
    scheduler.shutdown()
    logger.info("Application shutdown.")


app = FastAPI(
    title="Backstory AI Front Page & Text Extraction Service",
    description=(
        "Production-ready text extraction, YouTube transcription, "
        "and AI-curated front page briefing engine for Backstory."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static Files & Frontend UI Mount
# ---------------------------------------------------------------------------

_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the interactive broadsheet newspaper and newsletter UI."""
    index_file = os.path.join(_STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {
        "service": "Backstory AI Front Page Service",
        "docs": "/docs",
        "health": "/health",
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_article_links(html: str, base_url: str) -> list[str]:
    """Extract unique article-like links from a webpage HTML, prioritizing primary section content."""
    base_domain = urlparse(base_url).netloc
    soup = BeautifulSoup(html, "html.parser")

    # Strip navigation header and footer chrome so we only discover main content articles
    for chrome_tag in soup(["header", "nav", "footer", "aside"]):
        chrome_tag.decompose()

    seen: set[str] = set()
    section_links: list[str] = []
    other_links: list[str] = []

    parsed_base = urlparse(base_url)
    base_subpath = parsed_base.path.strip("/").split("/")[0] if parsed_base.path.strip("/") else ""

    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        parsed = urlparse(href)
        normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
        if normalized not in seen and normalized != base_url.rstrip("/") and is_article_link(href, base_domain):
            seen.add(normalized)
            if base_subpath and base_subpath in parsed.path:
                section_links.append(normalized)
            else:
                other_links.append(normalized)

    return section_links + other_links


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

async def _scrape_and_process_article(url_str: str) -> ArticleResult:
    """
    Run full single-article or YouTube video extraction, noise-filtering, and newsletter summarization.
    If the URL is a listing/hub/category page, discovers sub-articles, extracts and
    summarizes each individually, and returns an ArticleResult containing the list.
    """
    res = await scrape_url(url_str)

    # 1. Listing / Category Hub page handling
    if res.get("is_listing"):
        html = res.get("html", "")
        article_links = _collect_article_links(html, url_str)
        if not article_links:
            raise ExtractionFailed(
                "no_content",
                f"Listing/category page detected at {url_str}, but could not find article links."
            )

        # Limit to top 8 articles from the hub
        target_links = article_links[:8]
        semaphore = asyncio.Semaphore(4)

        async def _process_sub(link: str) -> ArticleResult | None:
            async with semaphore:
                try:
                    sub_res = await scrape_url(link)
                    if sub_res.get("is_listing"):
                        return None
                    sub_text = sub_res.get("text", "").strip()
                    sub_title = sub_res.get("title")
                    passed, _ = await noise_filter(sub_text, sub_title)
                    if not passed:
                        return None
                    digest = await generate_newsletter_digest(
                        sub_text,
                        title=sub_title,
                        author=sub_res.get("author"),
                    )
                    return ArticleResult(
                        url=link,
                        title=sub_title,
                        author=sub_res.get("author"),
                        published_date=sub_res.get("date"),
                        text=sub_text,
                        char_count=len(sub_text),
                        extraction_method=sub_res.get("extraction_method"),
                        fetch_strategy=sub_res.get("fetch_strategy"),
                        summary=digest.get("summary"),
                        deck=digest.get("deck"),
                        takeaways=digest.get("takeaways"),
                        category=digest.get("category"),
                        thumbnail_url=sub_res.get("thumbnail_url"),
                        is_video=bool(sub_res.get("is_video")),
                        video_id=sub_res.get("video_id"),
                        is_listing=False,
                        article_count=1,
                    )
                except Exception as exc:
                    logger.warning("Failed to extract sub-article %s: %s", link, exc)
                    return None

        results = await asyncio.gather(*[_process_sub(l) for l in target_links])
        valid_articles = [a for a in results if a is not None]

        if not valid_articles:
            raise ExtractionFailed(
                "no_content",
                f"Discovered {len(target_links)} links on listing page {url_str}, but none yielded readable text."
            )

        lead = valid_articles[0]
        return ArticleResult(
            url=url_str,
            title=f"{lead.category or 'Category'} Dispatch: {len(valid_articles)} Top Stories",
            author="Editorial Wire",
            published_date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            text=lead.text,
            char_count=sum(a.char_count for a in valid_articles),
            extraction_method=lead.extraction_method,
            fetch_strategy=res.get("fetch_strategy", "direct"),
            summary=f"Curated {len(valid_articles)} separate stories from {urlparse(url_str).netloc}. Each story has been extracted and summarized independently.",
            deck=f"Top story: {lead.title}",
            takeaways=[f"{a.title}: {a.deck or (a.summary[:100] if a.summary else '')}" for a in valid_articles[:4]],
            category=lead.category or "General Dispatch",
            is_listing=True,
            article_count=len(valid_articles),
            articles=valid_articles,
        )

    # 2. Single article or YouTube video handling
    text = res.get("text", "").strip()
    title = res.get("title")

    # Noise filter check
    passed, filter_reason = await noise_filter(text, title)
    if not passed:
        logger.info("Filtered article/video %s: %s", url_str, filter_reason)
        raise ExtractionFailed("no_content", f"Item filtered as noise: {filter_reason}")

    digest = await generate_newsletter_digest(
        text,
        title=title,
        author=res.get("author"),
    )

    art = ArticleResult(
        url=url_str,
        title=title,
        author=res.get("author"),
        published_date=res.get("date"),
        text=text,
        char_count=len(text),
        extraction_method=res.get("extraction_method"),
        fetch_strategy=res.get("fetch_strategy"),
        summary=digest.get("summary"),
        deck=digest.get("deck"),
        takeaways=digest.get("takeaways"),
        category=digest.get("category"),
        thumbnail_url=res.get("thumbnail_url"),
        is_video=bool(res.get("is_video")),
        video_id=res.get("video_id"),
        is_listing=False,
        article_count=1,
        articles=None,
    )
    return art


# ---------------------------------------------------------------------------
# POST /extract — Single URL Extraction (with Listing/Hub Page Auto-Split)
# ---------------------------------------------------------------------------

@app.post(
    "/extract",
    response_model=ArticleResult,
    responses={
        422: {"model": ExtractionError, "description": "No readable content could be extracted."},
        502: {"model": ExtractionError, "description": "Site blocked requests or DNS failure."},
        504: {"model": ExtractionError, "description": "Request timed out fetching URL."},
    },
    summary="Extract clean article text / YouTube transcript and newsletter summary from a URL",
    description=(
        "Fetches a webpage or YouTube video, detects if it is a listing page or video, "
        "extracts structured text/transcript, and produces an executive newsletter briefing."
    ),
)
async def extract(request: ExtractRequest):
    url_str = str(request.url)
    try:
        return await _scrape_and_process_article(url_str)
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
    summary="Poll a source for new/unseen article or YouTube video URLs",
    description=(
        "Checks an RSS feed, YouTube channel, or website homepage for items that have not "
        "been seen previously in the database, marks them as seen, and updates markers."
    ),
)
async def source_check(request: SourceCheckRequest):
    url_str = str(request.source_url)
    source_type = request.source_type

    # Auto-detect source type if requested
    if source_type == "auto":
        if is_youtube_url(url_str):
            source_type = "youtube_channel"
        elif any(url_str.endswith(ext) for ext in [".xml", ".rss", ".atom"]) or "feed" in url_str:
            source_type = "rss"
        else:
            source_type = "website"

    feed_url = None
    if source_type in ("youtube_channel", "youtube"):
        channel_id = await resolve_channel_id(url_str)
        if channel_id:
            feed_url = get_channel_rss_url(channel_id)
    elif source_type == "rss":
        feed_url = url_str

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
# POST /extract/batch — Concurrent Multi-URL Extraction with Deduplication
# ---------------------------------------------------------------------------

@app.post(
    "/extract/batch",
    response_model=BatchExtractResponse,
    summary="Batch extract multiple article or YouTube URLs in parallel with semantic deduplication",
    description="Extracts clean text and summaries from a list of URLs concurrently and runs cross-source deduplication.",
)
async def extract_batch(request: BatchExtractRequest):
    semaphore = asyncio.Semaphore(request.max_concurrency)

    async def _extract_single(url_str: str) -> ArticleResult | ExtractionError:
        async with semaphore:
            try:
                return await _scrape_and_process_article(url_str)
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
    raw_results = await asyncio.gather(*tasks)

    # Separate successes for cross-source deduplication
    success_articles: list[ArticleResult] = []
    error_results: list[ExtractionError] = []

    for r in raw_results:
        if isinstance(r, ArticleResult):
            success_articles.append(r)
        else:
            error_results.append(r)

    # Run Cross-Source Semantic Deduplication if enabled
    if request.deduplicate and len(success_articles) > 1:
        dict_items = [a.model_dump() for a in success_articles]
        clustered_dicts = await deduplicate_and_cluster_stories(dict_items, similarity_threshold=0.82)
        final_articles = [ArticleResult(**d) for d in clustered_dicts]
    else:
        final_articles = success_articles

    combined_results: list[ArticleResult | ExtractionError] = list(final_articles) + list(error_results)

    return BatchExtractResponse(
        results=combined_results,
        success_count=len(final_articles),
        failure_count=len(error_results),
    )


# ---------------------------------------------------------------------------
# Followed Sources & Refresh Endpoints
# ---------------------------------------------------------------------------

@app.get("/sources", response_model=list[SourceModel], summary="List all followed sources")
async def list_sources():
    """Retrieve all followed YouTube channels, blogs, and RSS feeds."""
    sources = await get_all_sources()
    return [
        SourceModel(
            id=s["id"],
            url=s["url"],
            type=s["type"],
            name=s["name"],
            feed_url=s.get("feed_url"),
            last_checked_at=s.get("last_checked_at"),
            last_seen_marker=s.get("last_seen_marker"),
            created_at=s["created_at"],
        )
        for s in sources
    ]


@app.post("/sources", response_model=SourceModel, summary="Follow a new YouTube channel, blog, or RSS feed")
async def create_source(request: CreateSourceRequest):
    """Add a new followed source with automatic channel/feed resolution."""
    url = request.url.strip()
    src_type = request.source_type or "auto"

    if src_type == "auto":
        if is_youtube_url(url):
            src_type = "youtube_channel"
        elif any(url.endswith(ext) for ext in [".xml", ".rss", ".atom"]) or "feed" in url:
            src_type = "rss"
        else:
            src_type = "website"

    feed_url = None
    name = request.name or url

    if src_type in ("youtube_channel", "youtube"):
        channel_id = await resolve_channel_id(url)
        if channel_id:
            feed_url = get_channel_rss_url(channel_id)
            if not request.name:
                name = f"YouTube Channel ({channel_id})"

    source_id = await upsert_source(url, src_type, name=name, feed_url=feed_url)

    return SourceModel(
        id=source_id,
        url=url,
        type=src_type,
        name=name,
        feed_url=feed_url,
        last_checked_at=None,
        last_seen_marker=None,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@app.delete("/sources/{source_id}", summary="Unfollow a source")
async def remove_source(source_id: str):
    """Delete a followed source and its seen markers."""
    ok = await delete_source(source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"status": "deleted", "source_id": source_id}


@app.post("/refresh-all", summary="Check all stored sources for new items")
async def refresh_all_endpoint():
    return await refresh_all_sources()


@app.post("/refresh", response_model=RefreshResponse, summary="Manual refresh trigger across all followed sources")
async def trigger_refresh():
    """
    Manually triggers an immediate pull across all followed YouTube channels and blogs.
    """
    results = await refresh_all_sources()
    if isinstance(results, dict) and "new_items_count" in results:
        return RefreshResponse(
            status=results.get("status", "success"),
            new_items_count=results.get("new_items_count", 0),
            sources_checked=results.get("sources_checked", 0),
            errors_count=results.get("errors_count", 0),
            refreshed_at=results.get("refreshed_at", datetime.now(timezone.utc).isoformat()),
        )
    new_items_count = sum(v for v in results.values() if isinstance(v, int))
    errors_count = sum(1 for v in results.values() if v == "error")
    return RefreshResponse(
        status="success",
        new_items_count=new_items_count,
        sources_checked=len(results),
        errors_count=errors_count,
        refreshed_at=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/scheduler", summary="Get background cron scheduler status")
async def scheduler_status_endpoint():
    """Returns the background refresh schedule status, job details, and running state."""
    job = scheduler.get_job("refresh_all")
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "running": bool(scheduler.running),
        "job_id": "refresh_all",
        "interval": "30 minutes",
        "next_run_time": next_run,
    }


@app.get("/newspaper", summary="Get the latest daily newspaper briefing items")
async def get_daily_newspaper(limit: int = Query(default=30, ge=1, le=100)):
    """Retrieve the recent processed article & video stories from the database."""
    items = await get_recent_processed_items(limit=limit)
    return {"items": items, "count": len(items)}


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
