# Scrape-to-VectorDB Backend

FastAPI backend that scrapes a URL (blog post, news article, newsletter page),
extracts the clean article text, embeds it with OpenAI, and stores it in a
local Chroma vector database for later use in an LLM/RAG pipeline.

## Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and add your OPENAI_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`.

## Endpoints

### `POST /scrape`
Scrape a URL, extract + chunk + embed the article, store it in Chroma.

```bash
curl -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.thehindu.com/some-article/"}'
```

Response:
```json
{
  "url": "...",
  "title": "...",
  "author": "...",
  "published_date": "...",
  "num_chunks": 4,
  "chunk_ids": ["...", "..."]
}
```

### `POST /search`
Sanity-check retrieval — semantic search over everything scraped so far.

```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "what happened in the article about X", "top_k": 3}'
```

### `GET /health`
Basic liveness check.

## Notes / things to consider as you extend this

- **Paywalled content**: sites like The Hindu gate some articles behind a
  subscription. An anonymous scraper will only get what's publicly visible
  in the HTML — trafilatura will just return less text or nothing.
- **JS-rendered pages**: this scraper uses `httpx` + `trafilatura`, which
  works for server-rendered HTML (most news/blog sites). If you hit a site
  that renders content client-side with JS, you'll need a headless browser
  (Playwright) instead — happy to add that as a fallback path.
- **Re-scraping the same URL**: chunk IDs are deterministic (derived from the
  URL), so re-scraping overwrites old chunks rather than duplicating them.
- **Rate limiting / robots.txt**: this scaffold doesn't enforce per-domain
  rate limits or robots.txt checks yet — worth adding before scraping any
  site at volume.
- **Async job pattern**: right now `/scrape` blocks until scraping + embedding
  finishes (fine for single articles, a few seconds). If you start batch-
  scraping many URLs at once, switch to `BackgroundTasks` or a task queue
  (Celery/RQ) with a job-status endpoint instead.
