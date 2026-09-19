"""
Canonical Pydantic models for the Backstory text-extraction service.

All request / response shapes live here so teammates importing from this
service have a single well-typed reference.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExtractionMethod(str, Enum):
    """Which extraction strategy produced the article text."""
    substack_next_data = "substack_next_data"
    trafilatura        = "trafilatura"
    bs4_fallback       = "bs4_fallback"


class FetchStrategy(str, Enum):
    """Which fetch strategy obtained the HTML."""
    direct        = "direct"
    google_cache  = "google_cache"
    wayback       = "wayback"
    playwright    = "playwright"


class ErrorCode(str, Enum):
    fetch_blocked = "fetch_blocked"    # 403 after all fallbacks
    timeout       = "timeout"          # network/read timeout
    no_content    = "no_content"       # all extraction strategies < 200 chars
    parse_error   = "parse_error"      # malformed HTML / feed parse failure
    dns_error     = "dns_error"        # hostname not resolvable
    invalid_url   = "invalid_url"      # URL rejected before network call


# ---------------------------------------------------------------------------
# /extract  — single URL
# ---------------------------------------------------------------------------


class ExtractRequest(BaseModel):
    url: HttpUrl = Field(..., description="Article or webpage URL to extract text from.")

    model_config = {"json_schema_extra": {"example": {"url": "https://example.com/some-article"}}}


class ArticleResult(BaseModel):
    url:               str                        = Field(..., description="Canonical URL that was scraped.")
    title:             Optional[str]              = Field(None, description="Article title (None if not found).")
    author:            Optional[str]              = Field(None, description="Byline / author name.")
    published_date:    Optional[str]              = Field(None, description="Publication date in ISO-8601 format when available.")
    text:              str                        = Field(..., description="Full extracted article text, cleaned of boilerplate.")
    char_count:        int                        = Field(..., description="Character count of the extracted text.")
    extraction_method: Optional[ExtractionMethod] = Field(None, description="Which extraction strategy produced the text.")
    fetch_strategy:    Optional[FetchStrategy]    = Field(None, description="Which fetch strategy obtained the HTML.")
    summary:           Optional[str]              = Field(None, description="Executive summary of the article.")
    deck:              Optional[str]              = Field(None, description="Punchy sub-headline or deck.")
    takeaways:         Optional[list[str]]        = Field(None, description="Key bullet takeaways for newsletter format.")
    category:          Optional[str]              = Field(None, description="Classified category topic.")


class ExtractionError(BaseModel):
    url:        str       = Field(..., description="URL that failed extraction.")
    error_code: ErrorCode = Field(..., description="Machine-readable failure reason.")
    detail:     str       = Field(..., description="Human-readable explanation.")


# ---------------------------------------------------------------------------
# /extract/source-check  — cheap "what's new" poll
# ---------------------------------------------------------------------------


class SourceCheckRequest(BaseModel):
    source_url:  HttpUrl                   = Field(..., description="Homepage or feed URL to check for new articles.")
    source_type: Literal["rss", "website"] = Field(..., description="'rss' for RSS/Atom feeds; 'website' for plain HTML sites.")

    model_config = {"json_schema_extra": {"example": {
        "source_url": "https://example.com/blog",
        "source_type": "website",
    }}}


class SourceCheckResponse(BaseModel):
    source_url:    str       = Field(..., description="The checked source URL.")
    new_item_urls: list[str] = Field(..., description="URLs of articles not yet seen by this service.")
    checked_at:    datetime  = Field(..., description="UTC timestamp of this check.")


# ---------------------------------------------------------------------------
# /extract/batch  — parallel multi-URL scrape
# ---------------------------------------------------------------------------


class BatchExtractRequest(BaseModel):
    urls:            list[HttpUrl] = Field(..., description="List of article URLs to scrape.", min_length=1, max_length=200)
    max_concurrency: int           = Field(5, ge=1, le=20, description="Maximum parallel scrape workers.")

    model_config = {"json_schema_extra": {"example": {
        "urls": ["https://example.com/article-1", "https://example.com/article-2"],
        "max_concurrency": 5,
    }}}


class BatchExtractResponse(BaseModel):
    results:       list[ArticleResult | ExtractionError] = Field(..., description="Per-URL result (success or failure).")
    success_count: int                                    = Field(..., description="Number of URLs successfully extracted.")
    failure_count: int                                    = Field(..., description="Number of URLs that failed extraction.")


# ---------------------------------------------------------------------------
# POST /scrape  — legacy backward-compat shapes (kept as-is)
# ---------------------------------------------------------------------------


class ScrapeRequest(BaseModel):
    url: HttpUrl = Field(..., description="URL to scrape (single article or blog homepage).")


class LegacyArticleResult(BaseModel):
    """Legacy per-article shape returned by POST /scrape."""
    url:            str           = Field(..., description="Article URL.")
    title:          Optional[str] = Field(None)
    author:         Optional[str] = Field(None)
    published_date: Optional[str] = Field(None)
    text:           str           = Field(..., description="Extracted article text.")
    char_count:     int           = Field(..., description="Character count of extracted text.")


class LegacyScrapeResponse(BaseModel):
    """Legacy response shape returned by POST /scrape."""
    source_url:    str                       = Field(..., description="The source URL that was submitted.")
    article_count: int                       = Field(..., description="Number of articles found and extracted.")
    articles:      list[LegacyArticleResult] = Field(..., description="Extracted articles.")


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status:        str  = Field(..., description="'ok' if the service is healthy.")
    version:       str  = Field(..., description="Service version string.")
    db_ok:         bool = Field(..., description="True if SQLite DB is reachable and tables exist.")
    playwright_ok: bool = Field(..., description="True if Playwright Chromium binary is installed.")
