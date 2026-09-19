# Backstory — Text Extraction Module API Contract

This service provides robust, structured text extraction from web-based sources (RSS/Atom feeds, Substack, Ghost, Medium, WordPress blogs, news sites, and generic web pages).

---

## What This Module Does
- **Multi-strategy fetch cascade**: Direct `httpx` (with UA rotation) $\rightarrow$ Google Cache $\rightarrow$ Wayback Machine $\rightarrow$ Playwright headless Chromium.
- **Structured text extraction**: Substack `__NEXT_DATA__` JSON $\rightarrow$ Trafilatura $\rightarrow$ Boilerplate-stripped BeautifulSoup fallback.
- **Boilerplate removal**: Strips cookie banners, newsletter subscription popups, ads, comments, and social share widgets.
- **Source tracking & deduplication**: RSS date-marker comparison + SQLite `seen_urls` tracking.
- **Concurrent batch extraction**: Multi-URL extraction with concurrency control.

## What This Module Does NOT Do
- Video / audio transcription (owned by media ingestion teammate).
- LLM summarization / headline generation (owned by summarization teammate).
- Vector embeddings and chunking (owned by retrieval teammate).
- Cron-based scheduling (owned by orchestration teammate).

---

## API Endpoints

### 1. `POST /extract`
Extracts structured article text from a single webpage.

#### Request Body
```json
{
  "url": "https://example.com/article-slug"
}
```

#### Successful Response (`200 OK`)
```json
{
  "url": "https://example.com/article-slug",
  "title": "Understanding Modern Neural Architectures",
  "author": "Alice Johnson",
  "published_date": "2026-04-15T10:00:00Z",
  "text": "Full cleaned article body text...",
  "char_count": 1420,
  "extraction_method": "trafilatura",
  "fetch_strategy": "direct"
}
```

#### Error Responses (`422`, `502`, `504`)
```json
{
  "url": "https://example.com/empty-page",
  "error_code": "no_content",
  "detail": "All extraction strategies returned less than 200 characters of text."
}
```

---

### 2. `POST /extract/source-check`
A lightweight, fast "what's new" poll for an RSS/Atom feed or blog homepage. Diffs against already-seen URLs and marks new items as seen in the database.

#### Request Body
```json
{
  "source_url": "https://example.com/feed.xml",
  "source_type": "rss"
}
```
*`source_type` can be `"rss"` or `"website"`.*

#### Successful Response (`200 OK`)
```json
{
  "source_url": "https://example.com/feed.xml",
  "new_item_urls": [
    "https://example.com/blog/latest-post-1",
    "https://example.com/blog/latest-post-2"
  ],
  "checked_at": "2026-09-19T04:50:00.000Z"
}
```

---

### 3. `POST /extract/batch`
Scrapes multiple article URLs concurrently with rate limiting. Returns individual per-URL success or failure objects without failing the whole batch.

#### Request Body
```json
{
  "urls": [
    "https://example.com/post-1",
    "https://example.com/post-2"
  ],
  "max_concurrency": 5
}
```

#### Successful Response (`200 OK`)
```json
{
  "results": [
    {
      "url": "https://example.com/post-1",
      "title": "Post 1",
      "author": "Author",
      "published_date": "2026-01-01",
      "text": "Cleaned article text...",
      "char_count": 850,
      "extraction_method": "trafilatura",
      "fetch_strategy": "direct"
    },
    {
      "url": "https://example.com/post-2",
      "error_code": "no_content",
      "detail": "Page had < 200 characters"
    }
  ],
  "success_count": 1,
  "failure_count": 1
}
```

---

### 4. `GET /health`
Verifies SQLite database connectivity and Playwright headless browser availability.

#### Successful Response (`200 OK`)
```json
{
  "status": "ok",
  "version": "1.0.0",
  "db_ok": true,
  "playwright_ok": false
}
```

---

### 5. `POST /scrape` (Legacy Endpoint)
Provided for backwards compatibility with earlier scraper backend clients. Handles both single article URLs and site homepages.

---

## Machine-Readable Error Codes

| `error_code` | HTTP Status | Description |
|---|---|---|
| `no_content` | `422` | Page contains no usable article body (<200 characters extracted). |
| `fetch_blocked` | `502` | All fetch strategies (direct, Google Cache, Wayback, Playwright) were blocked (HTTP 403). |
| `dns_error` | `502` | Hostname could not be resolved. |
| `timeout` | `504` | Request timed out during fetching. |
| `parse_error` | `500` | Malformed page or feed that could not be parsed. |

---

## Example cURL Commands

```bash
# Health check
curl -X GET http://localhost:8000/health

# Single article extract
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://stratechery.com/2024/apple-and-meta/"}'

# Poll RSS feed for new items
curl -X POST http://localhost:8000/extract/source-check \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://stratechery.com/feed/", "source_type": "rss"}'

# Batch extract multiple URLs
curl -X POST http://localhost:8000/extract/batch \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://example.com/article-1", "https://example.com/article-2"], "max_concurrency": 4}'
```
