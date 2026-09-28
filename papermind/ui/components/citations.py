"""
Citation formatting components for Chainlit UI.
"""

from typing import List, Dict, Any
import chainlit as cl


def format_citation_side_panel(citations: List[Dict[str, Any]]) -> str:
    """Format citations for side panel display."""
    if not citations:
        return "## 📚 Sources\n\nNo sources found for this answer."
    
    lines = ["## 📚 Sources\n"]
    for c in citations:
        lines.append(f"### [{c['index']}] {c['title']}")
        if c.get('section'):
            lines.append(f"**Section:** {c['section']}")
        if c.get('distance') is not None:
            relevance = 1 - c['distance'] if c['distance'] <= 1 else 0
            lines.append(f"**Relevance:** {relevance:.1%}")
        lines.append(f"**Excerpt:** {c.get('text', '')[:300]}...")
        lines.append("---")
    return "\n".join(lines)


def format_citation_inline(citations: List[Dict[str, Any]]) -> str:
    """Format citations as inline references [1], [2], etc."""
    if not citations:
        return ""
    refs = [f"[{c['index']}]" for c in citations]
    return " ".join(refs)


def create_citation_elements(citations: List[Dict[str, Any]]) -> List:
    """Create Chainlit elements for citations."""
    if not citations:
        return []
    
    content = format_citation_side_panel(citations)
    return [
        cl.Text(
            name="Citations",
            content=content,
            display="side"
        )
    ]