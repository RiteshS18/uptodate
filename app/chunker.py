"""
Simple character-based chunker with overlap, sized for good retrieval
granularity with OpenAI's text-embedding-3-small.
"""

import re

DEFAULT_MAX_CHARS = 3000   # ~600-750 tokens
DEFAULT_OVERLAP = 300      # keeps context across chunk boundaries


def chunk_text(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = end - overlap
    return chunks
