"""
Map-reduce summarization using gpt-4o-mini.

Long articles are split into chunks (reusing app/chunker.py), each chunk is
summarized individually (map), then the chunk summaries are combined into a
single coherent 2-5 sentence summary (reduce).
"""

import logging

from app.chunker import chunk_text
from app.embeddings import get_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_MAP_SYSTEM = """\
You are a concise summarizer for a news briefing app. \
Summarize the following section of an article. Focus on what is new, \
notable, or actionable. Write 2-4 sentences. Do not repeat the title."""

_REDUCE_SYSTEM = """\
You are a concise summarizer for a news briefing app. \
Below are summaries of individual sections from a single article. \
Combine them into one coherent summary of 2-5 sentences that captures \
the most important new or notable information from the full article. \
Do not merely list the sections — synthesize them into a natural paragraph."""


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

async def _llm_summarize(system: str, user: str) -> str:
    """Single chat-completion call to gpt-4o-mini."""
    client = get_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=350,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def summarize_item(text: str, title: str | None = None) -> str:
    """
    Summarize an article using map-reduce over its chunks.

    Args:
        text:  Full extracted article text.
        title: Article title (included as context in each prompt).

    Returns:
        A 2-5 sentence summary string.
    """
    chunks = chunk_text(text)
    if not chunks:
        return ""

    title_prefix = f"Article title: {title}\n\n" if title else ""

    # --- Map step: summarize each chunk individually ---
    chunk_summaries: list[str] = []
    for i, chunk in enumerate(chunks):
        user_msg = f"{title_prefix}Section {i + 1} of {len(chunks)}:\n\n{chunk}"
        summary = await _llm_summarize(_MAP_SYSTEM, user_msg)
        chunk_summaries.append(summary)
        logger.debug("Chunk %d/%d summarized (%d chars)", i + 1, len(chunks), len(summary))

    # --- Reduce step ---
    if len(chunk_summaries) == 1:
        return chunk_summaries[0]

    combined_input = (
        f"{title_prefix}"
        "Section summaries:\n\n"
        + "\n\n".join(
            f"[Section {i + 1}] {s}" for i, s in enumerate(chunk_summaries)
        )
    )
    final_summary = await _llm_summarize(_REDUCE_SYSTEM, combined_input)
    logger.info("Summarized article %r: %d chunks → %d char summary",
                title or "(untitled)", len(chunks), len(final_summary))
    return final_summary
