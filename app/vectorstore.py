"""
Local, persistent Chroma vector store. Data is written to ./chroma_data
so it survives restarts.
"""

import uuid
import chromadb

_client = chromadb.PersistentClient(path="./chroma_data")
_collection = _client.get_or_create_collection(name="scraped_articles")


def upsert_chunks(
    url: str,
    title: str | None,
    author: str | None,
    published_date: str | None,
    chunks: list[str],
    embeddings: list[list[float]],
) -> list[str]:
    """
    Upserts one entry per chunk. IDs are deterministic (derived from the URL),
    so re-scraping the same URL overwrites its old chunks instead of duplicating them.
    """
    ids = [
        f"{uuid.uuid5(uuid.NAMESPACE_URL, url)}-{i}" for i in range(len(chunks))
    ]
    metadatas = [
        {
            "url": url,
            "title": title or "",
            "author": author or "",
            "published_date": published_date or "",
            "chunk_index": i,
        }
        for i in range(len(chunks))
    ]

    _collection.upsert(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return ids


def query(embedding: list[float], top_k: int = 5, url_filter: str | None = None) -> dict:
    """
    Similarity search. If url_filter is provided, results are restricted to
    chunks from that specific URL.
    """
    kwargs: dict = {"query_embeddings": [embedding], "n_results": top_k}
    if url_filter:
        kwargs["where"] = {"url": {"$eq": url_filter}}
    return _collection.query(**kwargs)
