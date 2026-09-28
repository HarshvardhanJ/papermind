"""
vector_store.py

Thin interface over ChromaDB. Isolating it here (rather than calling
chromadb directly from the ingestion/query pipelines) means swapping
to Qdrant later, if the corpus ever outgrew ChromaDB, only requires
changing this one file.
"""

import os
import chromadb
from pathlib import Path

from papermind.retrieval.embedder import embed_texts, embed_query
from papermind.retrieval.hybrid_search import invalidate_bm25_cache

PERSIST_DIR = Path(os.environ.get("CHROMA_PERSIST_DIR", "data/chroma"))
PERSIST_DIR.mkdir(parents=True, exist_ok=True)

_client = None
_collection = None


def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(PERSIST_DIR))
        _collection = _client.get_or_create_collection(name="paper_chunks")
    return _collection


def add_chunks(chunks: list) -> None:
    """
    chunks: list of Chunk objects from chunker.py
    Embeds each chunk's text and stores it with metadata linking back
    to its paper and section.
    """
    if not chunks:
        return

    collection = get_collection()
    texts = [c.text for c in chunks]
    embeddings = embed_texts(texts)

    ids = [f"{c.paper_id}::{c.chunk_index}" for c in chunks]
    metadatas = [
        {"paper_id": c.paper_id, "section": c.section, "chunk_index": c.chunk_index, "is_table": c.is_table}
        for c in chunks
    ]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )
    invalidate_bm25_cache()


def search(query: str, top_k: int = 5, paper_ids: list[str] | None = None) -> list[dict]:
    """
    Returns top_k most similar chunks to the query.
    Optionally restricted to a list of paper_ids.
    """
    collection = get_collection()
    query_embedding = embed_query(query)

    where = {"paper_id": {"$in": paper_ids}} if paper_ids else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
    )

    hits = []
    if results["ids"] and results["ids"][0]:
        for i in range(len(results["ids"][0])):
            hits.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "section": results["metadatas"][0][i]["section"],
                "is_table": results["metadatas"][0][i].get("is_table", False),
                "paper_id": results["metadatas"][0][i]["paper_id"],
                "distance": results["distances"][0][i],
            })
    return hits


def delete_paper(paper_id: str) -> None:
    collection = get_collection()
    collection.delete(where={"paper_id": paper_id})
    invalidate_bm25_cache()


def count() -> int:
    return get_collection().count()
