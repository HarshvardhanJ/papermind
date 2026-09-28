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
    return paragraph.lstrip().startswith("|")


def chunk_section(section: Section, paper_id: str, max_words: int,
                  chunk_index_start: int) -> list[Chunk]:
    paragraphs = [p.strip() for p in section.content.split("\n\n") if p.strip()]

    chunks: list[Chunk] = []
    idx = chunk_index_start
    buffer: list[str] = []
    buffer_words = 0

    def emit(text: str, is_table: bool = False) -> None:
        nonlocal idx
        chunks.append(Chunk(text=text, section=section.heading, chunk_index=idx,
                            paper_id=paper_id, word_count=_word_count(text),
                            is_table=is_table))
        idx += 1

    def flush() -> None:
        nonlocal buffer, buffer_words
        if buffer:
            emit(" ".join(buffer).strip())
        buffer, buffer_words = [], 0

    for para in paragraphs:
        if _is_table(para):
            caption = None
            if buffer and buffer[-1].lower().startswith("table"):
                caption = buffer.pop()
            flush()
            emit(f"{caption}\n\n{para}" if caption else para, is_table=True)
            continue

        para_words = _word_count(para)
        if para_words > max_words:
            flush()
            for sentence in _split_sentences(para):
                s_words = _word_count(sentence)
                if buffer_words + s_words > max_words:
                    flush()
                buffer.append(sentence)
                buffer_words += s_words
            flush()
        elif buffer_words + para_words > max_words:
            flush()
            buffer, buffer_words = [para], para_words
        else:
            buffer.append(para)
            buffer_words += para_words

    flush()
    return chunks


def chunk_sections(sections: list[Section], paper_id: str, max_words: int = 200) -> list[Chunk]:
    all_chunks: list[Chunk] = []
    for section in sections:
        if _normalize(section.heading) in SKIP_SECTIONS:
            continue
        all_chunks.extend(chunk_section(section, paper_id, max_words, len(all_chunks)))
    return all_chunks
