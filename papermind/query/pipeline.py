"""
pipeline.py (query)

Orchestrates a single user query end to end:
extract filters from question -> filter papers via SQL -> retrieve relevant chunks
from matching papers -> look up their paper titles -> synthesize a cited answer.
"""

from papermind.retrieval.vector_store import search
from papermind.retrieval.hybrid_search import hybrid_search
from papermind.retrieval.reranker import hybrid_rerank_search
from papermind.query.synthesizer import synthesize_answer
from papermind.query.filters import extract_query_filters, apply_filters_to_query
from papermind.storage.database import get_session
from papermind.storage.models import Paper


def answer_query(question: str, top_k: int = 5, synthesize: bool = True,
                 use_hybrid: bool = True, use_reranker: bool = True) -> dict:
    """
    Returns:
        {
            "question": str,
            "answer": str | None,       # None if synthesize=False
            "sources": [
                {"paper_id": ..., "title": ..., "section": ..., "text": ...},
                ...
            ],
            "filters_applied": dict | None
        }

    synthesize=False is useful for the evaluation harness, which only
    needs the retrieved chunk IDs and should never spend an LLM call.
    use_hybrid: If True, use hybrid BM25+dense search. If False, use dense only.
    use_reranker: If True, apply cross-encoder reranking after retrieval.
    """
    # Step 1: Extract structured filters from the question
    filters = extract_query_filters(question)

    # Step 2: Apply filters via SQL to get matching paper IDs
    filtered_paper_ids = None
    if any([
        filters.title_contains,
        filters.author_name,
        filters.year,
        filters.year_min,
        filters.year_max,
        filters.extra_metadata_filters,
    ]):
        with get_session() as session:
            filtered_paper_ids = apply_filters_to_query(session, filters)

    # Step 3: Search within filtered papers (or all if no filters)
    if use_hybrid:
        if use_reranker:
            chunks = hybrid_rerank_search(question, top_k=top_k, paper_ids=filtered_paper_ids)
        else:
            chunks = hybrid_search(question, top_k=top_k, paper_ids=filtered_paper_ids)
    else:
        chunks = search(question, top_k=top_k, paper_ids=filtered_paper_ids)

    # If no results with filters, fall back to unfiltered search
    if not chunks and filtered_paper_ids:
        if use_hybrid:
            if use_reranker:
                chunks = hybrid_rerank_search(question, top_k=top_k, paper_ids=None)
            else:
                chunks = hybrid_search(question, top_k=top_k, paper_ids=None)
        else:
            chunks = search(question, top_k=top_k, paper_ids=None)

    paper_ids = list({c["paper_id"] for c in chunks})
    paper_titles = {}
    with get_session() as session:
        papers = session.query(Paper).filter(Paper.id.in_(paper_ids)).all()
        paper_titles = {p.id: (p.title or p.filename) for p in papers}

    sources = [
        {
            "paper_id": c["paper_id"],
            "title": paper_titles.get(c["paper_id"], "Unknown"),
            "section": c["section"],
            "text": c["text"],
            "relevance_distance": c.get("distance", c.get("bm25_score", c.get("rerank_score", 0))),
        }
        for c in chunks
    ]

    answer = None
    note = None
    if synthesize:
        try:
            answer = synthesize_answer(question, chunks, paper_titles)
        except RuntimeError as e:
            # Missing API key. Retrieval still worked, so return the
            # sources rather than failing the whole request.
            note = f"Answer synthesis unavailable: {e}. Showing retrieved sources only."

    filters_applied = None
    if filtered_paper_ids is not None:
        filters_applied = {
            "title_contains": filters.title_contains,
            "author_name": filters.author_name,
            "year": filters.year,
            "year_min": filters.year_min,
            "year_max": filters.year_max,
            "extra_metadata_filters": filters.extra_metadata_filters,
            "matched_paper_count": len(filtered_paper_ids),
        }

    return {
        "question": question,
        "answer": answer,
        "note": note,
        "sources": sources,
        "filters_applied": filters_applied,
    }