"""
pipeline.py (query)

Orchestrates a single user query end to end:
retrieve relevant chunks -> look up their paper titles -> synthesize
a cited answer.
"""

from papermind.retrieval.vector_store import search
from papermind.query.synthesizer import synthesize_answer
from papermind.storage.database import get_session
from papermind.storage.models import Paper


def answer_query(question: str, top_k: int = 5, synthesize: bool = True) -> dict:
    """
    Returns:
        {
            "question": str,
            "answer": str | None,       # None if synthesize=False
            "sources": [
                {"paper_id": ..., "title": ..., "section": ..., "text": ...},
                ...
            ]
        }

    synthesize=False is useful for the evaluation harness, which only
    needs the retrieved chunk IDs and should never spend an LLM call.
    """
    chunks = search(question, top_k=top_k)

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
            "relevance_distance": c["distance"],
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

    return {"question": question, "answer": answer, "note": note, "sources": sources}
