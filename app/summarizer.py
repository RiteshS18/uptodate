"""
LLM and NLP summarization & newsletter processing engine.

Supports:
1. LLM-based newsletter synthesis using gpt-4o-mini (when OPENAI_API_KEY is present).
2. Intelligent extractive NLP summarization fallback (when OPENAI_API_KEY is not set or network fails).
3. Structured output: summary, punchy deck, bullet takeaways, category, and callout quote.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from app.chunker import chunk_text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback / Extractive NLP Summarizer
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with",
    "by", "about", "against", "between", "into", "through", "during", "before",
    "after", "above", "below", "from", "up", "down", "of", "off", "over", "under",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "this", "that", "these", "those", "it", "its", "they",
    "their", "we", "our", "you", "your", "he", "his", "she", "her", "which",
    "who", "whom", "what", "where", "when", "why", "how", "all", "each", "every",
    "both", "few", "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "can", "will", "just",
    "should", "now", "also", "would", "could", "may", "might", "shall", "must"
}


def _extractive_summarize(text: str, max_sentences: int = 4) -> dict:
    """
    High-quality extractive summarization using sentence position & word frequency scoring.
    Used as an immediate, zero-latency fallback when OpenAI API key is not configured.
    """
    # Clean text and split into sentences
    cleaned = re.sub(r'\s+', ' ', text).strip()
    raw_sentences = re.split(r'(?<=[.!?])\s+', cleaned)
    sentences = [s.strip() for s in raw_sentences if len(s.strip()) > 35]

    if not sentences:
        fallback = text[:300] + ("..." if len(text) > 300 else "")
        return {
            "summary": fallback,
            "deck": fallback[:120],
            "takeaways": [fallback],
            "category": "General Dispatch",
            "callout": fallback[:150],
        }

    # Calculate word frequencies
    words = re.findall(r'\b[a-zA-Z]{3,}\b', cleaned.lower())
    freq = {}
    for w in words:
        if w not in _STOPWORDS:
            freq[w] = freq.get(w, 0) + 1

    max_f = max(freq.values()) if freq else 1
    for w in freq:
        freq[w] = freq[w] / max_f

    # Score sentences based on word weights + position bias (early sentences carry more weight)
    scores = []
    for i, s in enumerate(sentences):
        s_words = re.findall(r'\b[a-zA-Z]{3,}\b', s.lower())
        score = sum(freq.get(w, 0) for w in s_words)
        if len(s_words) > 0:
            score = score / len(s_words)
        # Position boost for lead paragraphs
        if i < 3:
            score *= 1.4 - (i * 0.15)
        scores.append((score, i, s))

    # Pick top scoring sentences and restore original narrative order
    scores.sort(key=lambda x: x[0], reverse=True)
    top_chosen = sorted(scores[:max_sentences], key=lambda x: x[1])
    top_sentences = [item[2] for item in top_chosen]

    summary = " ".join(top_sentences)
    deck = sentences[0] if len(sentences[0]) < 180 else sentences[0][:170] + "..."

    # Extract bullet takeaways
    takeaways = []
    for s in top_sentences[:4]:
        # Trim leading conjunctions if needed
        clean_s = re.sub(r'^(However|Furthermore|Moreover|In addition|Therefore|Also),?\s*', '', s)
        takeaways.append(clean_s)

    # Classify category
    lower_text = cleaned.lower()
    if any(k in lower_text for k in ["entertainment", "web series", "series", "episode", "season", "show", "ott", "netflix", "drama", "actor", "actress", "film", "movie", "trailer", "roast", "comic", "superhero", "oscars", "bollywood"]):
        category = "Entertainment & Media"
    elif any(k in lower_text for k in ["church", "faith", "worship", "sacred", "pastor", "prayer", "spiritual"]):
        category = "Faith & Community"
    elif any(k in lower_text for k in ["ai", "model", "neural", "software", "algorithm", "gpu", "chip", "tech", "computing"]):
        category = "Technology & AI"
    elif any(k in lower_text for k in ["market", "economy", "stock", "dollar", "trade", "inflation", "bank", "fund"]):
        category = "Economy & Markets"
    elif any(k in lower_text for k in ["climate", "treaty", "energy", "accord", "summit", "nation", "diplomat"]):
        category = "Global Affairs"
    elif any(k in lower_text for k in ["culture", "philosophy", "history", "art", "music", "essay"]):
        category = "Culture & Philosophy"
    else:
        category = "General Dispatch"

    callout = top_sentences[0] if top_sentences else deck

    return {
        "summary": summary,
        "deck": deck,
        "takeaways": takeaways,
        "category": category,
        "callout": callout,
    }


# ---------------------------------------------------------------------------
# LLM Newsletter Summarizer (OpenAI gpt-4o-mini)
# ---------------------------------------------------------------------------

_NEWSLETTER_SYSTEM_PROMPT = """\
You are an expert executive editor for a high-end daily newspaper and newsletter briefing called 'The Backstory Chronicle'.
Given the article title and full text, produce a structured, high-value newsletter digest in valid JSON format with exactly these keys:
{
  "deck": "A single punchy, informative sub-headline (15-25 words) that hooks the reader and highlights the key takeaway.",
  "summary": "A 2-4 sentence executive summary synthesizing the most important insights and background context.",
  "takeaways": [
    "First critical bullet takeaway explaining what happened or why it matters",
    "Second notable fact, data point, or technical insight",
    "Third key implication or future outlook"
  ],
  "category": "One of: Technology & AI, Faith & Community, Economy & Markets, Global Affairs, Comics & Entertainment, Science & Health, Culture & Philosophy, or General Dispatch",
  "callout": "A memorable quote, thesis statement, or mission summary suitable for an editorial callout box."
}
Output ONLY valid JSON, with no markdown code fences or other text.
"""


async def generate_newsletter_digest(text: str, title: str | None = None, author: str | None = None) -> dict:
    """
    Generate an executive newsletter digest (summary, deck, takeaways, category, callout).
    Attempts LLM summarization if OPENAI_API_KEY is available; falls back seamlessly to
    extractive NLP summarization if unavailable or if an error occurs.
    """
    if not text or len(text.strip()) < 50:
        return {
            "summary": "No text content available to summarize.",
            "deck": "Briefing unavailable.",
            "takeaways": [],
            "category": "General Dispatch",
            "callout": "No content available."
        }

    api_key = os.environ.get("OPENAI_API_KEY")
    # If API key is not configured or is placeholder, use extractive summarizer
    if not api_key or "your_openai_api_key_here" in api_key or not api_key.startswith("sk-"):
        logger.info("OPENAI_API_KEY not active — using high-quality extractive NLP summarizer.")
        return _extractive_summarize(text)

    # Use LLM
    try:
        from app.embeddings import get_client
        client = get_client()

        # Limit input text to first ~8000 tokens for latency and cost efficiency
        sample_text = text[:12000]
        user_prompt = f"Article Title: {title or 'Untitled'}\nByline: {author or 'Unknown'}\n\nArticle Text:\n{sample_text}"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            max_tokens=500,
            messages=[
                {"role": "system", "content": _NEWSLETTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        data = json.loads(content)

        return {
            "summary": data.get("summary") or text[:300],
            "deck": data.get("deck") or (title or "Special Report"),
            "takeaways": data.get("takeaways") or [data.get("summary", "")],
            "category": data.get("category") or "General Dispatch",
            "callout": data.get("callout") or data.get("deck", ""),
        }

    except Exception as exc:
        logger.warning("LLM summarization failed (%s) — falling back to extractive summarizer.", exc)
        return _extractive_summarize(text)


# ---------------------------------------------------------------------------
# Legacy single string summarize helper
# ---------------------------------------------------------------------------

async def summarize_item(text: str, title: str | None = None) -> str:
    """Summarize an article into a 2-4 sentence string."""
    digest = await generate_newsletter_digest(text, title=title)
    return digest.get("summary", "")
