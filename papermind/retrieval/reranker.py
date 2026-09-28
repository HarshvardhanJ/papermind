"""
reranker.py

Cross-encoder reranker for improving retrieval quality.
Uses a small transformer model to re-score query-document pairs.
"""

from sentence_transformers import CrossEncoder
import threading

_reranker = None
_reranker_lock = threading.Lock()


def get_reranker(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
    """Get or load the cross-encoder reranker (cached)."""
    global _reranker
    
    with _reranker_lock:
        if _reranker is None:
            _reranker = CrossEncoder(model_name)
        return _reranker


def rerank(query: str, results: list[dict], top_k: int | None = None) -> list[dict]:
    """
    Re-rank results using a cross-encoder.
    
    Args:
        query: The search query
        results: List of result dicts with 'text' field
        top_k: If provided, return only top_k results
    
    Returns:
        Re-ranked results with 'rerank_score' added
    """
    if not results:
        return []
    
    reranker = get_reranker()
    
    # Prepare pairs for cross-encoder
    pairs = [(query, r["text"]) for r in results]
    
    # Get scores
    scores = reranker.predict(pairs)
    
    # Add scores to results
    for i, r in enumerate(results):
        r["rerank_score"] = float(scores[i])
    
    # Sort by rerank score descending (higher = better)
    results.sort(key=lambda x: x["rerank_score"], reverse=True)
    
    if top_k:
        return results[:top_k]
    return results


def hybrid_rerank_search(query: str, top_k: int = 5, paper_ids: list[str] | None = None,
                         initial_k: int = 20, use_reranker: bool = True) -> list[dict]:
    """
    Full hybrid search + rerank pipeline.
    
    Args:
        query: Search query
        top_k: Final number of results
        paper_ids: Optional paper ID filter
        initial_k: Number of candidates to retrieve before reranking
        use_reranker: Whether to apply cross-encoder reranking
    
    Returns:
        Top-k re-ranked results
    """
    from papermind.retrieval.hybrid_search import hybrid_search
    
    # Step 1: Hybrid search to get candidates
    candidates = hybrid_search(query, top_k=initial_k, paper_ids=paper_ids)
    
    if not candidates:
        return []
    
    # Step 2: Rerank if enabled
    if use_reranker:
        candidates = rerank(query, candidates, top_k=top_k)
    else:
        candidates = candidates[:top_k]
    
    return candidates