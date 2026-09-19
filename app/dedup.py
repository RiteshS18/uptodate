"""
Cross-source deduplication engine for Backstory.

When multiple followed sources (e.g. a YouTube video, a blog post, and a newspaper article)
cover the same underlying story, this module clusters them by semantic similarity using
embeddings, collapses them into a single primary digest entry, and appends links to every
original source in `related_sources`.
"""

from __future__ import annotations

import logging
import numpy as np
from typing import Any

from app.embeddings import embed_texts

logger = logging.getLogger(__name__)


def _cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity between two dense embedding vectors."""
    a = np.array(vec1, dtype=np.float32)
    b = np.array(vec2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


async def deduplicate_and_cluster_stories(
    articles: list[dict],
    similarity_threshold: float = 0.82
) -> list[dict]:
    """
    Cluster and deduplicate a list of article/video dictionaries.

    If two or more items have semantic similarity >= similarity_threshold:
    - Retains the most comprehensive item as the master briefing.
    - Merges takeaways and key facts.
    - Appends all unique original sources to `related_sources`.
    
    Returns the list of consolidated, deduplicated story items.
    """
    if len(articles) <= 1:
        return articles

    # 1. Generate text representations for embedding
    texts_to_embed = []
    for art in articles:
        title = art.get("title") or ""
        summary = art.get("summary") or art.get("deck") or (art.get("text", "")[:300])
        category = art.get("category") or ""
        texts_to_embed.append(f"{category} | {title} | {summary}")

    try:
        embeddings = embed_texts(texts_to_embed)
    except Exception as exc:
        logger.warning("Embedding generation failed during deduplication: %s — returning raw articles.", exc)
        return articles

    n = len(articles)
    visited = [False] * n
    clustered_results: list[dict] = []

    for i in range(n):
        if visited[i]:
            continue

        visited[i] = True
        cluster_indices = [i]

        for j in range(i + 1, n):
            if visited[j]:
                continue
            sim = _cosine_similarity(embeddings[i], embeddings[j])
            if sim >= similarity_threshold:
                visited[j] = True
                cluster_indices.append(j)
                logger.info(
                    "Clustered duplicate story (sim=%.3f): '%s' <--> '%s'",
                    sim, articles[i].get("title"), articles[j].get("title")
                )

        # 2. Consolidate cluster into one primary item
        primary_idx = cluster_indices[0]
        # Choose the item with richest summary/text as lead
        for idx in cluster_indices:
            if len(articles[idx].get("text", "")) > len(articles[primary_idx].get("text", "")):
                primary_idx = idx

        lead_item = dict(articles[primary_idx])

        # Build list of all related original sources in this cluster
        related_sources = []
        seen_urls = set()

        for idx in cluster_indices:
            art = articles[idx]
            url = art.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                related_sources.append({
                    "title": art.get("title") or "Source Dispatch",
                    "url": url,
                    "author": art.get("author") or "Editorial",
                    "source_type": "youtube" if (art.get("is_video") or "youtube.com" in url or "youtu.be" in url) else "article",
                    "category": art.get("category"),
                })

        lead_item["related_sources"] = related_sources
        lead_item["cross_source_count"] = len(cluster_indices)

        # Merge key takeaways from other items in the cluster
        merged_takeaways = list(lead_item.get("takeaways") or [])
        for idx in cluster_indices:
            if idx == primary_idx:
                continue
            for t in (articles[idx].get("takeaways") or []):
                if t not in merged_takeaways and len(merged_takeaways) < 6:
                    merged_takeaways.append(t)

        if merged_takeaways:
            lead_item["takeaways"] = merged_takeaways

        clustered_results.append(lead_item)

    return clustered_results
