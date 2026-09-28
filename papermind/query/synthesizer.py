"""
synthesizer.py

Takes retrieved chunks (from vector_store.search) and the original
question, and asks an LLM to produce a direct answer grounded only in
those chunks, with inline citations back to paper section.

This is kept as a separate, small step from retrieval on purpose:
retrieval quality (did we find the right chunks) and synthesis quality
(did we write a good answer from those chunks) are different failure
modes, and keeping them as separate functions is what let the earlier
evaluation harness measure retrieval alone, with no LLM involved.
"""

import os

SYSTEM_PROMPT = """You answer research questions using ONLY the provided
source excerpts. Every claim in your answer must be grounded in one of
the excerpts. Cite the source of each claim inline as [Paper: <section>].

If the excerpts do not contain enough information to answer the
question, say so explicitly. Do not use outside knowledge, and do not
guess."""


def _format_context(chunks: list[dict], paper_titles: dict[str, str] | None = None) -> str:
    paper_titles = paper_titles or {}
    parts = []
    for c in chunks:
        title = paper_titles.get(c["paper_id"], c["paper_id"][:8])
        parts.append(f"[Paper: {title} | Section: {c['section']}]\n{c['text']}")
    return "\n\n---\n\n".join(parts)


def synthesize_answer(question: str, chunks: list[dict],
                       paper_titles: dict[str, str] | None = None) -> str:
    if not chunks:
        return "No relevant information was found in the indexed papers for this question."

    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set -- synthesis requires an LLM API key.")

    client = Groq(api_key=api_key)
    context = _format_context(chunks, paper_titles)

    response = client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "openai/gpt-oss-120b"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nSource excerpts:\n\n{context}"},
        ],
    )
    return response.choices[0].message.content
