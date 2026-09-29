"""Inline source previews for PaperMind answers."""

from typing import Any, Dict, List


def append_citation_tooltips(answer: str, citations: List[Dict[str, Any]]) -> str:
    """Render compact numbered source links with native hover titles."""
    if not citations:
        return answer

    references = []
    for citation in citations:
        details = [citation.get("title") or "Untitled paper"]
        if citation.get("section"):
            details.append(citation["section"])
        excerpt = " ".join((citation.get("text") or "").split())
        if excerpt:
            details.append(excerpt[:240] + ("…" if len(excerpt) > 240 else ""))
        tooltip = " · ".join(details).replace("\\", "&#92;").replace('"', "&quot;")
        references.append(f'[{citation.get("index", "?")}](# "{tooltip}")')

    return f"{answer.rstrip()}\n\n**Sources:** " + " · ".join(references)
