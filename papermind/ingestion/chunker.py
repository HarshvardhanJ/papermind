"""
chunker.py

Splits each Section into retrieval-sized chunks.

Rules:
  - A chunk never crosses a section boundary.
  - Paragraphs are the primary unit; an over-long paragraph is split on
    sentence boundaries.
  - A markdown table is always its own chunk and is never split or merged
    with prose. If the paragraph just before it starts with "Table", that
    caption is attached, because the caption is what tells an embedding
    model what the numbers mean.
  - References, acknowledgements and appendix sections are dropped.
  - Optional overlap between consecutive chunks within a section.
"""

import re
from dataclasses import dataclass

from papermind.ingestion.sections import Section

SKIP_SECTIONS = {"references", "acknowledgements", "acknowledgments", "appendix"}


@dataclass
class Chunk:
    text: str
    section: str
    chunk_index: int
    paper_id: str
    word_count: int
    is_table: bool = False


def _normalize(heading: str) -> str:
    return re.sub(r"^[\d\.\s]+", "", heading).strip().lower()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [p.strip() for p in parts if p.strip()]


def _word_count(text: str) -> int:
    return len(text.split())


def _is_table(paragraph: str) -> bool:
    """Check if paragraph contains a markdown table (has a line starting with |)."""
    return any(line.lstrip().startswith("|") for line in paragraph.split("\n"))


def _split_with_overlap(sentences: list[str], max_words: int, overlap_words: int) -> list[str]:
    """
    Split sentences into chunks with overlap.
    Returns list of chunk texts.
    """
    if overlap_words <= 0:
        # No overlap - simple greedy packing
        chunks = []
        buffer = []
        buffer_words = 0
        
        for sent in sentences:
            s_words = _word_count(sent)
            if buffer_words + s_words > max_words:
                if buffer:
                    chunks.append(" ".join(buffer))
                buffer, buffer_words = [sent], s_words
            else:
                buffer.append(sent)
                buffer_words += s_words
        if buffer:
            chunks.append(" ".join(buffer))
        return chunks
    
    # With overlap - sliding window approach
    chunks = []
    window = []
    window_words = 0
    
    for sent in sentences:
        s_words = _word_count(sent)
        
        # Add sentence to window
        window.append(sent)
        window_words += s_words
        
        # If window exceeds max_words, emit chunk and slide
        while window_words > max_words and len(window) > 1:
            chunks.append(" ".join(window))
            # Slide: remove sentences from start until we have room for overlap
            removed_words = 0
            while window and removed_words < overlap_words:
                removed = window.pop(0)
                removed_words += _word_count(removed)
            window_words = sum(_word_count(s) for s in window)
        
        # Also emit if adding this sentence would exceed max_words with just this one
        if window_words > max_words and len(window) == 1:
            chunks.append(window[0])
            window, window_words = [], 0
    
    # Don't forget the last window
    if window:
        chunks.append(" ".join(window))
    
    return chunks


def _build_chunks_from_text(text: str, max_words: int, overlap_words: int) -> list[str]:
    """
    Split a section's text into overlapping chunks.
    Tables are handled separately - they are their own chunks.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    
    # First pass: identify table paragraphs and prose paragraphs
    prose_paragraphs = []
    table_chunks = []  # (position, chunk_text)
    
    for i, para in enumerate(paragraphs):
        if _is_table(para):
            # Check if previous paragraph is a caption
            caption = None
            if prose_paragraphs and prose_paragraphs[-1].lower().startswith("table"):
                caption = prose_paragraphs.pop()
            table_chunks.append((len(prose_paragraphs), f"{caption}\n\n{para}" if caption else para))
        else:
            prose_paragraphs.append(para)
    
    # If no overlap, just pack paragraphs greedily, splitting long ones
    if overlap_words <= 0:
        all_chunks = []
        buffer = []
        buffer_words = 0
        
        # Insert table chunks at their positions
        table_iter = iter(table_chunks)
        next_table = next(table_iter, None)
        
        for i, para in enumerate(prose_paragraphs):
            # Emit any tables at this position
            while next_table and next_table[0] == i:
                all_chunks.append(next_table[1])
                next_table = next(table_iter, None)
            
            para_words = _word_count(para)
            if para_words > max_words:
                # Split long paragraph into sentences
                flush_buffer = True
                if buffer:
                    all_chunks.append(" ".join(buffer))
                    buffer, buffer_words = [], 0
                sentences = _split_sentences(para)
                for sent in sentences:
                    s_words = _word_count(sent)
                    if buffer_words + s_words > max_words:
                        if buffer:
                            all_chunks.append(" ".join(buffer))
                        buffer, buffer_words = [sent], s_words
                    else:
                        buffer.append(sent)
                        buffer_words += s_words
            elif buffer_words + para_words > max_words:
                if buffer:
                    all_chunks.append(" ".join(buffer))
                buffer, buffer_words = [para], para_words
            else:
                buffer.append(para)
                buffer_words += para_words
        
        # Remaining tables at the end
        while next_table:
            all_chunks.append(next_table[1])
            next_table = next(table_iter, None)
        
        if buffer:
            all_chunks.append(" ".join(buffer))
        return all_chunks
    
    # With overlap: convert all prose to sentences, then apply sliding window
    all_sentences = []
    para_to_sent_idx = []  # Track which sentences belong to which paragraph
    
    for para in prose_paragraphs:
        sentences = _split_sentences(para)
        start_idx = len(all_sentences)
        all_sentences.extend(sentences)
        para_to_sent_idx.append((start_idx, len(all_sentences)))
    
    # Split into overlapping chunks
    prose_chunks = _split_with_overlap(all_sentences, max_words, overlap_words)
    
    # Insert table chunks at appropriate positions
    # For simplicity, we'll add tables as separate chunks without overlap
    all_chunks = []
    table_idx = 0
    
    for i, chunk in enumerate(prose_chunks):
        # Estimate position: chunk index / total chunks * num paragraphs
        # This is approximate but reasonable
        estimated_pos = (i / max(len(prose_chunks), 1)) * len(prose_paragraphs)
        
        # Add tables before this position
        while table_idx < len(table_chunks) and table_chunks[table_idx][0] <= estimated_pos:
            all_chunks.append(table_chunks[table_idx][1])
            table_idx += 1
        
        all_chunks.append(chunk)
    
    # Add remaining tables
    while table_idx < len(table_chunks):
        all_chunks.append(table_chunks[table_idx][1])
        table_idx += 1
    
    return all_chunks


def chunk_section(section: Section, paper_id: str, max_words: int,
                  chunk_index_start: int, overlap_words: int = 0) -> list[Chunk]:
    # Get chunk texts with overlap
    chunk_texts = _build_chunks_from_text(section.content, max_words, overlap_words)
    
    chunks = []
    for i, text in enumerate(chunk_texts):
        is_table = _is_table(text)
        chunks.append(Chunk(
            text=text,
            section=section.heading,
            chunk_index=chunk_index_start + i,
            paper_id=paper_id,
            word_count=_word_count(text),
            is_table=is_table,
        ))
    return chunks


def chunk_sections(sections: list[Section], paper_id: str, max_words: int = 200,
                   overlap_words: int = 0) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for section in sections:
        if _normalize(section.heading) in SKIP_SECTIONS:
            continue
        all_chunks.extend(chunk_section(section, paper_id, max_words, len(all_chunks), overlap_words))
    return all_chunks