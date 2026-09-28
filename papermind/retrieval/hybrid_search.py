"""
hybrid_search.py

Combines BM25 keyword search with dense vector search for better retrieval.
Uses reciprocal rank fusion (RRF) to merge results.
"""

from rank_bm25 import BM25Okapi
from papermind.storage.database import get_session
from papermind.storage.models import ChunkRecord
import threading

# Lazy imports to avoid circular dependency
def _get_dense_search():
    from papermind.retrieval.vector_store import search
    return search

def _get_collection():
    from papermind.retrieval.vector_store import get_collection
    return get_collection

_bm25_cache = None
_bm25_lock = threading.Lock()


def _build_bm25_corpus():
    """Build BM25 corpus from all chunks in ChromaDB."""
    get_collection = _get_collection()
    collection = get_collection()
    results = collection.get()
    
    if not results["documents"]:
        return [], []
    
    corpus = [doc.split() for doc in results["documents"]]
    metadatas = results["metadatas"]
    return corpus, metadatas


def get_bm25():
    """Get or build the BM25 index (cached)."""
    global _bm25_cache
    
    with _bm25_lock:
        if _bm25_cache is None:
            corpus, metadatas = _build_bm25_corpus()
            if corpus:
                _bm25_cache = BM25Okapi(corpus)
            else:
                _bm25_cache = None
        return _bm25_cache


def invalidate_bm25_cache():
    """Call this after adding new chunks to rebuild the index."""
    global _bm25_cache
    with _bm25_lock:
        _bm25_cache = None


def bm25_search(query: str, top_k: int = 5, paper_ids: list[str] | None = None) -> list[dict]:
    """
    BM25 keyword search over all chunks.
    Optionally filtered by paper_ids.
    """
    bm25 = get_bm25()
    if bm25 is None:
        return []
    
    tokenized_query = query.split()
    scores = bm25.get_scores(tokenized_query)
    
    # Get top-k indices
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k * 3]
    
    # Filter by paper_ids if provided
    get_collection = _get_collection()
    collection = get_collection()
    results = collection.get()
    metadatas = results["metadatas"]
    
    hits = []
    for idx in top_indices:
        if scores[idx] <= 0:
            continue
        meta = metadatas[idx]
        if paper_ids and meta["paper_id"] not in paper_ids:
            continue
        
        hits.append({
            "id": results["ids"][idx],
            "text": results["documents"][idx],
            "section": meta["section"],
            "is_table": meta.get("is_table", False),
            "paper_id": meta["paper_id"],
            "bm25_score": scores[idx],
        })
        
        if len(hits) >= top_k:
            break
    
    return hits


def rrf_fuse(dense_results: list[dict], bm25_results: list[dict], k: int = 60) -> list[dict]:
    """
    Reciprocal Rank Fusion (RRF) to combine dense and BM25 results.
    k is the RRF parameter (typically 60).
    """
    # Create rank mappings
    dense_ranks = {r["id"]: i + 1 for i, r in enumerate(dense_results)}
    bm25_ranks = {r["id"]: i + 1 for i, r in enumerate(bm25_results)}
    
    all_ids = set(dense_ranks.keys()) | set(bm25_ranks.keys())
    
    fused = []
    for doc_id in all_ids:
        rrf_score = 0
        if doc_id in dense_ranks:
            rrf_score += 1 / (k + dense_ranks[doc_id])
        if doc_id in bm25_ranks:
            rrf_score += 1 / (k + bm25_ranks[doc_id])
        fused.append((doc_id, rrf_score))
    
    # Sort by RRF score descending
    fused.sort(key=lambda x: x[1], reverse=True)
    
    # Merge metadata from either source
    id_to_result = {r["id"]: r for r in dense_results}
    id_to_result.update({r["id"]: r for r in bm25_results})
    
    return [id_to_result[doc_id] for doc_id, _ in fused]


def hybrid_search(query: str, top_k: int = 5, paper_ids: list[str] | None = None,
                  dense_weight: float = 0.5, use_rrf: bool = True) -> list[dict]:
    """
    Hybrid search combining dense vector search and BM25 keyword search.
    
    Args:
        query: Search query
        top_k: Number of results to return
        paper_ids: Optional list of paper IDs to filter by
        dense_weight: Weight for dense scores when not using RRF (0-1)
        use_rrf: If True, use RRF fusion. If False, use weighted score fusion.
    
    Returns:
        List of top_k chunks with combined scores
    """
    # Get more candidates from each for better fusion
    candidate_k = top_k * 3
    
    dense_search = _get_dense_search()
    dense_results = dense_search(query, top_k=candidate_k, paper_ids=paper_ids)
    bm25_results = bm25_search(query, top_k=candidate_k, paper_ids=paper_ids)
    
    if not dense_results and not bm25_results:
        return []
    elif not dense_results:
        return bm25_results[:top_k]
    elif not bm25_results:
        return dense_results[:top_k]
    
    if use_rrf:
        fused = rrf_fuse(dense_results, bm25_results)
    else:
        # Score-based fusion (normalize and weight)
        # This is simpler but less robust than RRF
        fused = _score_fuse(dense_results, bm25_results, dense_weight)
    
    return fused[:top_k]


def _score_fuse(dense_results: list[dict], bm25_results: list[dict], dense_weight: float) -> list[dict]:
    """Simple weighted score fusion as fallback."""
    # Normalize scores to 0-1
    def normalize(results, score_key):
        if not results:
            return {}
        scores = [r[score_key] for r in results]
        min_s, max_s = min(scores), max(scores)
        if max_s == min_s:
            return {r["id"]: 0.5 for r in results}
        return {r["id"]: (r[score_key] - min_s) / (max_s - min_s) for r in results}
    
    dense_norm = normalize(dense_results, "distance")
    bm25_norm = normalize(bm25_results, "bm25_score")
    
    # Note: lower distance = better for dense, higher bm25 = better
    # Invert dense
    dense_norm = {k: 1 - v for k, v in dense_norm.items()}
    
    all_ids = set(dense_norm.keys()) | set(bm25_norm.keys())
    id_to_result = {r["id"]: r for r in dense_results}
    id_to_result.update({r["id"]: r for r in bm25_results})
    
    fused_scores = {}
    for doc_id in all_ids:
        d_score = dense_norm.get(doc_id, 0)
        b_score = bm25_norm.get(doc_id, 0)
        fused_scores[doc_id] = dense_weight * d_score + (1 - dense_weight) * b_score
    
    sorted_ids = sorted(fused_scores.keys(), key=lambda k: fused_scores[k], reverse=True)
    return [id_to_result[doc_id] for doc_id in sorted_ids]