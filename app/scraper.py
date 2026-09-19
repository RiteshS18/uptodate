"""
Fetches a URL and extracts all possible raw text content.

Strategy cascade (fires automatically on 403 or empty response):
  1. Direct httpx fetch with realistic browser headers + UA rotation
  2. Google Cache  (webcache.googleusercontent.com)
  3. Wayback Machine / Archive.org  (latest snapshot)
  4. Playwright headless Chromium  (real browser, JS-executed, passes most bot checks)

Extraction cascade (applied to the HTML):
  1. Substack __NEXT_DATA__ JSON  (fast, clean, JS-free)
  2. trafilatura  (best for standard article/blog pages)
  3. BS4 full-page fallback  (supplementary or sole source)

Both cascades report which strategy succeeded via the returned dict's
'fetch_strategy' and 'extraction_method' keys.  If all strategies yield
< _MIN_TEXT_CHARS of text, ExtractionFailed is raised rather than returning
an empty/near-empty text field silently.
"""

from __future__ import annotations

import json
import logging
import random
import re

import httpx
import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TIMEOUT = 30.0

# Minimum character count for extracted text to be considered usable.
_MIN_TEXT_CHARS = 200


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class ExtractionFailed(Exception):
    """
    Raised by scrape_url() when all extraction strategies yield < _MIN_TEXT_CHARS
    of text, or when fetch_html() exhausts every fetch strategy.

    Attributes:
        error_code: Machine-readable reason ('no_content', 'fetch_blocked',
                    'timeout', 'dns_error').
        detail:     Human-readable description.
    """
    def __init__(self, error_code: str, detail: str):
        super().__init__(detail)
        self.error_code = error_code
        self.detail = detail


# ---------------------------------------------------------------------------
# User-Agent pool
# ---------------------------------------------------------------------------

_POLITE_UA = "BackstoryNewsReader/1.0 (+https://github.com/RiteshS18/uptodate; bot@backstory.internal)"

_USER_AGENTS = [
    _POLITE_UA,
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.4.1 Safari/605.1.15"
    ),
]


def _make_headers(ua: str, referer: str | None = None) -> dict:
    """Construct a full set of realistic browser request headers."""
    headers = {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;"
            "q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }
    if referer:
        headers["Referer"] = referer
        headers["Sec-Fetch-Site"] = "same-origin"
    return headers


# Default headers used by fetcher.py and feed_discovery.py on import.
HEADERS = _make_headers(_USER_AGENTS[0])


# ---------------------------------------------------------------------------
# Strategy 1 — Direct fetch with UA rotation
# ---------------------------------------------------------------------------

async def _fetch_direct(url: str) -> str | None:
    """
    Try UAs in order or random order. If Wikimedia/Wikipedia, prioritize polite bot UA.
    Returns HTML on first success, or raises the last httpx.HTTPStatusError if all attempts return 403.
    """
    # Prioritize polite identifier for sites that require it (e.g. Wikipedia)
    if "wikipedia.org" in url.lower() or "wikimedia.org" in url.lower():
        agents = [_POLITE_UA] + [ua for ua in _USER_AGENTS if ua != _POLITE_UA]
    else:
        agents = _USER_AGENTS.copy()
        random.shuffle(agents)

    last_exc: Exception | None = None
    for ua in agents:
        try:
            async with httpx.AsyncClient(
                timeout=TIMEOUT,
                headers=_make_headers(ua),
                follow_redirects=True,
                cookies={},
            ) as client:
                resp = await client.get(url)
                if resp.status_code == 403:
                    last_exc = httpx.HTTPStatusError(
                        "403 Forbidden", request=resp.request, response=resp
                    )
                    continue
                resp.raise_for_status()
                return resp.text
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                last_exc = e
                continue
            raise
        except httpx.RequestError:
            raise

    # All UAs returned 403 — re-raise so fetch_html() can escalate.
    if last_exc:
        raise last_exc
    return None


# ---------------------------------------------------------------------------
# Strategy 2 — Google Cache
# ---------------------------------------------------------------------------

async def _fetch_google_cache(url: str) -> str | None:
    """Fetch the Google-cached version of the page."""
    cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}&hl=en"
    ua = random.choice(_USER_AGENTS)
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers=_make_headers(ua),
            follow_redirects=True,
        ) as client:
            resp = await client.get(cache_url)
            if resp.status_code == 200 and len(resp.text) > 500:
                logger.info("Google Cache succeeded for %s", url)
                return resp.text
    except Exception as exc:
        logger.debug("Google Cache failed for %s: %s", url, exc)
    return None


# ---------------------------------------------------------------------------
# Strategy 3 — Wayback Machine (Archive.org)
# ---------------------------------------------------------------------------

async def _fetch_wayback(url: str) -> str | None:
    """Fetch the most recent Wayback Machine snapshot."""
    api_url = f"https://archive.org/wayback/available?url={url}"
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            meta = await client.get(api_url)
            meta.raise_for_status()
            data = meta.json()
            snapshot = (
                data.get("archived_snapshots", {})
                .get("closest", {})
                .get("url")
            )
            if not snapshot:
                logger.debug("No Wayback snapshot found for %s", url)
                return None

            ua = random.choice(_USER_AGENTS)
            page = await client.get(
                snapshot,
                headers=_make_headers(ua),
                follow_redirects=True,
                timeout=TIMEOUT,
            )
            if page.status_code == 200 and len(page.text) > 500:
                logger.info("Wayback Machine succeeded for %s", url)
                return page.text
    except Exception as exc:
        logger.debug("Wayback Machine failed for %s: %s", url, exc)
    return None


# ---------------------------------------------------------------------------
# Strategy 4 — Playwright headless browser
# ---------------------------------------------------------------------------

async def _fetch_playwright(url: str) -> str | None:
    """
    Launch a real headless Chromium browser. Executes JavaScript, handles
    redirects, and passes most Cloudflare/Imperva bot challenges.
    Falls back gracefully if Playwright is not installed.
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        logger.warning("Playwright not installed — skipping headless browser fallback.")
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1920,1080",
                ],
            )
            context = await browser.new_context(
                user_agent=random.choice(_USER_AGENTS),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/New_York",
                # Stealth: hide navigator.webdriver
                java_script_enabled=True,
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )

            # Mask automation fingerprint
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            """)

            page = await context.new_page()

            # Human-like: random delay before navigating
            await page.wait_for_timeout(random.randint(500, 1500))

            response = await page.goto(url, wait_until="networkidle", timeout=45000)

            if response and response.status == 403:
                await browser.close()
                logger.warning("Playwright also got 403 for %s", url)
                return None

            # Wait for dynamic content to settle
            await page.wait_for_timeout(random.randint(1000, 2500))

            html = await page.content()
            await browser.close()

            if html and len(html) > 500:
                logger.info("Playwright succeeded for %s", url)
                return html

    except Exception as exc:
        logger.warning("Playwright failed for %s: %s", url, exc)

    return None


# ---------------------------------------------------------------------------
# Unified fetch_html — runs cascade, returns (html, strategy_name)
# ---------------------------------------------------------------------------

async def fetch_html(url: str) -> tuple[str, str]:
    """
    Attempt fetch strategies in order; return ``(html, strategy_name)``
    for the first that succeeds.

    strategy_name is one of: 'direct', 'google_cache', 'wayback', 'playwright'.

    Raises:
        ExtractionFailed(error_code='fetch_blocked'): all four strategies failed.
        ExtractionFailed(error_code='timeout'):       read/connect timeout.
        ExtractionFailed(error_code='dns_error'):     hostname not resolvable.
        httpx.HTTPStatusError:                        non-403 HTTP errors (re-raised).
    """
    # 1. Direct fetch
    try:
        html = await _fetch_direct(url)
        if html:
            return html, "direct"
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ExtractionFailed("no_content", f"Page returned 404 Not Found for {url}") from e
        if e.response.status_code != 403:
            raise ExtractionFailed("fetch_blocked", f"Site returned HTTP {e.response.status_code} for {url}") from e
        logger.info("Direct fetch 403 for %s — trying fallbacks…", url)
    except httpx.TimeoutException as e:
        raise ExtractionFailed(
            "timeout", f"Request timed out fetching {url}: {e}"
        ) from e
    except httpx.ConnectError as e:
        err_str = str(e).lower()
        if any(kw in err_str for kw in ("getaddrinfo", "nodename", "name or service not known")):
            raise ExtractionFailed(
                "dns_error", f"DNS resolution failed for {url}: {e}"
            ) from e
        raise ExtractionFailed("fetch_blocked", f"Connection error fetching {url}: {e}") from e

    # 2. Google Cache
    html = await _fetch_google_cache(url)
    if html:
        return html, "google_cache"

    # 3. Wayback Machine
    html = await _fetch_wayback(url)
    if html:
        return html, "wayback"

    # 4. Playwright headless browser
    html = await _fetch_playwright(url)
    if html:
        return html, "playwright"

    # All strategies exhausted
    raise ExtractionFailed(
        "fetch_blocked",
        (
            f"All fetch strategies (direct, Google Cache, Wayback Machine, Playwright) "
            f"failed for {url}. The site may be heavily bot-protected or down."
        ),
    )


# ---------------------------------------------------------------------------
# Boilerplate stripping
# ---------------------------------------------------------------------------

# CSS selectors for common non-article noise injected into article pages.
_BOILERPLATE_SELECTORS = [
    # Cookie / GDPR consent banners
    "[class*='cookie']", "[id*='cookie']",
    "[class*='consent']", "[id*='consent']",
    "[class*='gdpr']", "[id*='gdpr']",
    # Subscribe / newsletter CTAs
    "[class*='subscribe']", "[id*='subscribe']",
    "[class*='newsletter-cta']", "[class*='signup-cta']",
    "[class*='paywall']", "[id*='paywall']",
    # Related articles / recommended widgets
    "[class*='related']", "[id*='related']",
    "[class*='recommended']", "[id*='recommended']",
    "[class*='more-stories']", "[class*='also-read']",
    "[class*='read-more']",
    # Comment sections
    "#comments", ".comments", "[id*='disqus']",
    "[class*='comment-section']", "[class*='comments-area']",
    # Social share bars
    "[class*='share-bar']", "[class*='social-share']",
    "[class*='share-buttons']", "[class*='share-icons']",
    # Ads / sponsored content
    "[class*='advertisement']", "[class*='ad-unit']",
    "[class*='sponsor']", "[id*='sponsor']",
]


def _strip_boilerplate(soup: BeautifulSoup) -> None:
    """
    Remove common non-article noise elements from a parsed page in-place.
    Called before any text extraction to keep output clean.
    """
    # Always strip these structural/noise tags first.
    for tag in soup(["script", "style", "noscript", "nav", "footer",
                     "header", "aside", "form", "button", "svg",
                     "img", "iframe", "meta", "link"]):
        tag.decompose()

    # Selector-based boilerplate removal.
    for selector in _BOILERPLATE_SELECTORS:
        for el in soup.select(selector):
            el.decompose()


# ---------------------------------------------------------------------------
# Text extractors
# ---------------------------------------------------------------------------

def _extract_with_trafilatura(html: str) -> dict:
    """Primary extraction — best for article/blog pages."""
    extracted = trafilatura.extract(
        html,
        include_comments=False,  # comments are boilerplate unless this IS a forum
        include_tables=True,
        include_links=False,
        output_format="json",
        with_metadata=True,
        favor_recall=True,
        no_fallback=False,
    )
    if not extracted:
        return {}
    data = json.loads(extracted)
    return {
        "title":  data.get("title"),
        "author": data.get("author"),
        "date":   data.get("date"),
        "text":   data.get("text", "") or "",
    }


def _extract_substack(html: str) -> dict | None:
    """
    Substack injects full article JSON into <script id="__NEXT_DATA__">.
    Parse it for clean title + body text without needing Playwright.
    Returns a dict {title, author, date, text} or None if not a Substack page.
    """
    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
    if not script_tag or not script_tag.string:
        return None

    try:
        data = json.loads(script_tag.string)
        # Substack's Next.js page props path
        props = data.get("props", {}).get("pageProps", {})
        post = props.get("post") or props.get("publication", {})
        if not post:
            return None

        title = post.get("title") or post.get("name")
        author = None
        authors = post.get("publishedBylines") or post.get("bylines") or []
        if authors:
            author = ", ".join(a.get("name", "") for a in authors if a.get("name"))

        # body_html → strip boilerplate tags, then extract text
        body_html = post.get("body_html") or post.get("description") or ""
        if body_html:
            body_soup = BeautifulSoup(body_html, "html.parser")
            _strip_boilerplate(body_soup)
            text = body_soup.get_text(separator="\n\n", strip=True)
        else:
            text = ""

        date = post.get("post_date") or ""
        if not isinstance(date, str):
            date = ""

        if text:
            logger.info("Substack __NEXT_DATA__ extraction succeeded")
            return {
                "title":  title,
                "author": author,
                "date":   date[:10] if date else None,
                "text":   text,
            }
    except Exception as exc:
        logger.debug("Substack extraction failed: %s", exc)

    return None


def _extract_with_bs4(html: str) -> str:
    """
    Full-page text extraction via BeautifulSoup.
    Strips boilerplate first, then targets article containers,
    falling back to the full page if no suitable container is found.
    Targets newsletter-specific article containers first.
    """
    soup = BeautifulSoup(html, "html.parser")
    _strip_boilerplate(soup)

    # Try newsletter/article-specific containers first.
    article_selectors = [
        "article",
        "[class*='post-content']",
        "[class*='article-body']",
        "[class*='entry-content']",
        "[class*='content-body']",
        "[class*='prose']",
        "main",
        ".post",
        ".article",
    ]
    for selector in article_selectors:
        container = soup.select_one(selector)
        if container:
            lines = []
            for element in container.find_all(
                ["p", "h1", "h2", "h3", "h4", "h5", "h6",
                 "li", "td", "th", "blockquote", "pre", "code"]
            ):
                text = element.get_text(separator=" ", strip=True)
                if text and len(text) > 20:
                    lines.append(text)
            result = "\n\n".join(lines)
            if len(result) > 300:
                return result

    # Full-page fallback
    lines = []
    for element in soup.find_all(
        ["p", "h1", "h2", "h3", "h4", "h5", "h6",
         "li", "td", "th", "blockquote", "pre", "code",
         "article", "section", "main"]
    ):
        text = element.get_text(separator=" ", strip=True)
        if text and len(text) > 20:
            lines.append(text)

    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def scrape_url(url: str) -> dict:
    """
    Fetch and extract article or video text from *url*.
    """
    # 0. Check if this is a YouTube video or channel URL
    from app.youtube import is_youtube_url, extract_youtube_content, extract_video_id
    if is_youtube_url(url) and extract_video_id(url):
        try:
            yt_data = await extract_youtube_content(url)
            return {
                "title": yt_data.get("title"),
                "author": yt_data.get("author"),
                "date": yt_data.get("published_date"),
                "text": yt_data.get("text"),
                "thumbnail_url": yt_data.get("thumbnail_url"),
                "is_video": True,
                "video_id": yt_data.get("video_id"),
                "extraction_method": yt_data.get("extraction_method"),
                "fetch_strategy": "direct",
                "is_listing": False,
            }
        except Exception as exc:
            logger.warning("YouTube extraction failed for %s: %s", url, exc)
            raise ExtractionFailed("no_content", f"Could not retrieve transcript or captions for YouTube video: {exc}")

    html, fetch_strategy = await fetch_html(url)

    # 0b. Check if the page is a listing / hub / category index page
    if is_listing_page(html, url):
        return {
            "title": None,
            "author": None,
            "date": None,
            "text": "",
            "is_listing": True,
            "html": html,
            "extraction_method": "listing_detector",
            "fetch_strategy": fetch_strategy,
        }

    # 1. Substack-specific extraction
    substack_result = _extract_substack(html)
    if substack_result and len(substack_result.get("text", "")) >= _MIN_TEXT_CHARS:
        return {
            **substack_result,
            "extraction_method": "substack_next_data",
            "fetch_strategy":    fetch_strategy,
        }

    # 2. trafilatura
    result    = _extract_with_trafilatura(html)
    main_text = result.get("text", "")

    # 3. BS4 fallback / supplement
    bs4_text = _extract_with_bs4(html)

    if len(main_text.strip()) < _MIN_TEXT_CHARS:
        # trafilatura got nothing useful — try BS4.
        if len(bs4_text.strip()) >= _MIN_TEXT_CHARS:
            main_text = bs4_text
            extraction_method = "bs4_fallback"
        else:
            # Both strategies failed — structured error, not a silent empty return.
            raise ExtractionFailed(
                "no_content",
                (
                    f"All extraction strategies (Substack JSON, trafilatura, BS4) "
                    f"returned less than {_MIN_TEXT_CHARS} characters of text for {url}. "
                    f"The page may be paywalled, JS-rendered, or contain no article-like content."
                ),
            )
    elif len(bs4_text) > len(main_text) * 1.5:
        # BS4 captured significantly more — merge both.
        main_text = main_text + "\n\n---\n\n" + bs4_text
        extraction_method = "trafilatura"
    else:
        extraction_method = "trafilatura"

    return {
        "title":             result.get("title"),
        "author":            result.get("author"),
        "date":              result.get("date"),
        "text":              main_text,
        "extraction_method": extraction_method,
        "fetch_strategy":    fetch_strategy,
    }


# ---------------------------------------------------------------------------
# Listing / Category / Hub Page Detection
# ---------------------------------------------------------------------------

def is_listing_page(html: str, url: str) -> bool:
    """
    Detect whether a page is a listing, hub, or category index page (rather than a single article).

    Heuristics:
    1. Link density (ratio of anchor-tag text to total visible text).
    2. Count of standalone headline links (links containing headings or article-like titles).
    3. Absence of continuous body prose paragraphs.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()

    all_text = soup.get_text(strip=True)
    if not all_text:
        return False

    links = soup.find_all("a", href=True)

    # Check for standalone headline links (links containing headings or title-like text not embedded in paragraphs)
    headline_links = set()
    for a in links:
        txt = a.get_text(strip=True)
        has_heading = bool(a.find(["h1", "h2", "h3", "h4", "h5", "h6"]))
        is_title_like = len(txt) > 25 and " " in txt
        if (has_heading or is_title_like) and not a.find_parent("p"):
            headline_links.add(a["href"])

    # Count distinct prose paragraphs with substantial content (> 120 chars)
    long_paragraphs = [
        p.get_text(strip=True)
        for p in soup.find_all("p")
        if len(p.get_text(strip=True)) > 120 and len(p.find_all("a")) <= 4
    ]

    # Calculate link text density
    link_text = "".join([a.get_text(strip=True) for a in links])
    link_density = len(link_text) / max(1, len(all_text))

    # If the page has extensive continuous prose and few standalone headline cards, it is an article
    if len(long_paragraphs) >= 4 and len(headline_links) < 15 and link_density < 0.45:
        return False

    # If the page has many standalone headline cards and very few body paragraphs, it is a listing page
    if len(headline_links) >= 6 and len(long_paragraphs) <= 3:
        return True

    # High link density indicates index/hub/category pages
    if link_density > 0.50 and len(long_paragraphs) <= 2:
        return True

    return False

