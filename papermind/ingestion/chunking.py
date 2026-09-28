from _typeshed import sentinel
from ast import List
import re
from dataclasses import dataclass, field
from pathlib import Path

from annotated_types import Len
from numpy import place
from pydantic import conbytes


@dataclass
class Chunk:
    text: str
    section: str
    section_index: int
    chunk_index: int
    paper_id: str
    token_count: int
    is_table: bool


@dataclass
class Section:
    heading: str
    content: str


SKIP_SECTIONS = {
    "references",
    "acknowledgements",
    "acknowledgments",
    "appendix",
    "footnotes",
}

NOISE_PATTERNS = [
    re.compile(r"<!--\s*image\s*-->", re.IGNORECASE),
    re.compile(r"<!--\s*formula-not-decoded\s*-->", re.IGNORECASE),
    re.compile(r"\*\s*Equal contribution.*", re.IGNORECASE),
    re.compile(r"†\s*Work performed.*", re.IGNORECASE),
    re.compile(r"‡\s*Work performed.*", re.IGNORECASE),
]

HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)

TABLE_RE = re.compile(r"(\|.+\|\n\|[-| :]+\|\n(?:\|.+\|\n?)*)", re.MULTILINE)


## md Parsing


def _is_author_table(text: str) -> bool:
    lower = text.lower()
    return any(
        kw in lower for kw in ["@", "university", "institute", "lab", "research"]
    )


def parse_sections(markdown: str) -> list[Section]:
    matches = list(HEADING_RE.finditer(markdown))

    if not matches:
        return [Section(heading="document", content=markdown.strip())]

    sections = []

    preamble_text = markdown[: matches[0].start()].strip()
    if preamble_text:
        sections.append(Section(heading="preamble", content=preamble_text))

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        content_start = match.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        content = markdown[content_start:content_end].strip()
        sections.append(Section(heading=heading, content=content))

    return sections


def _should_skip(section: Section) -> bool:
    heading_lower = section.heading.lower().strip()
    heading_normalized = re.sub(r"^\d+(\.\d+)*\s+", "", heading_lower)

    return heading_normalized in SKIP_SECTIONS


def _clean_text(text: str) -> str:
    for pattern in NOISE_PATTERNS:
        text = pattern.sub("", text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


## table extraction


def _extract_table(text: str) -> tuple[str, list[str]]:
    tables = []
    placeholder_text = text

    for match in TABLE_RE.finditer(text):
        table_str = match.group(0).strip()

        if _is_author_table(table_str):
            placeholder_text = placeholder_text.replace(table_str, "", 1)
            continue

        placeholder = f"__TABLE_{len(tables)}__"
        tables.append(table_str)
        placeholder_text = placeholder_text.replace(table_str, placeholder, 1)
    return placeholder_text, tables


## text splitting


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [p.strip() for p in parts if p.strip()]


def _word_count(text: str) -> int:
    return len(text.split())


def _build_chunks_from_paragraph(
    paragraphs: list[str],
    tables: list[str],
    section_heading: str,
    section_index: int,
    paper_id: str,
    max_words: int,
    chunk_index_start: int,
) -> list[Chunk]:
    chunks = []
    chunk_index = chunk_index_start

    current_parts: list[str] = []
    current_words = 0

    def flush_current():
        nonlocal current_words, chunk_index
        if not current_parts:
            return
        text = "\n\n".join(current_parts).strip()
        if text:
            chunks.append(
                Chunk(
                    text=text,
                    section=section_heading,
                    section_index=section_index,
                    chunk_index=chunk_index,
                    paper_id=paper_id,
                    token_count=_word_count(text),
                    is_table=False,
                )
            )
            chunk_index += 1
        current_parts.clear()
        current_words = 0

    for para in paragraphs:
        table_match = re.fullmatch(r"__TABLE_(\d+)__", para.strip())
        if table_match:
            flush_current()
            table_idx = int(table_match.group(1))
            table_text = tables[table_idx]
            chunks.append(
                Chunk(
                    text=table_text,
                    section=section_heading,
                    section_index=section_index,
                    chunk_index=chunk_index,
                    paper_id=paper_id,
                    token_count=_word_count(table_text),
                    is_table=True,
                )
            )
            chunk_index += 1
            continue

        para_words = _word_count(para)

        if para_words > max_words:
            flush_current()
            sentences = _split_sentences(para)
            sent_buffer: list[str] = []
            sent_words = 0

            for sentence in sentences:
                s_words = _word_count(sentence)
                if sent_words + s_words > max_words and sent_buffer:
                    text = " ".join(sent_buffer).strip()
                    chunks.append(
                        Chunk(
                            text=text,
                            section=section_heading,
                            section_index=section_index,
                            chunk_index=chunk_index,
                            paper_id=paper_id,
                            token_count=_word_count(text),
                            is_table=False,
                        )
                    )
                    chunk_index += 1
                    sent_buffer = [sentence]
                    sent_words = s_words
                else:
                    sent_buffer.append(sentence)
                    sent_words += s_words

            if sent_buffer:
                text = " ".join(sent_buffer).strip()
                chunks.append(
                    Chunk(
                        text=text,
                        section=section_heading,
                        section_index=section_index,
                        chunk_index=chunk_index,
                        paper_id=paper_id,
                        token_count=_word_count(text),
                        is_table=False,
                    )
                )
                chunk_index += 1

            elif current_words + para_words > max_words:
                flush_current()
                current_parts.append(para)
                current_words = para_words

            else:
                current_parts.append(para)
                current_words += para_words

    flush_current()
    return chunks


def chunk_document(markdown: str, paper_id: str, max_words: int = 300) -> list[Chunk]:
    sections = parse_sections(markdown)
    all_chunks: list[Chunk] = []
    chunk_index = 0

    for section_index, section in enumerate(sections):
        if _should_skip(section):
            continue

        cleaned = _clean_text(section.content)
        if not cleaned:
            continue

        text_with_placeholders, tables = _extract_table(cleaned)
        paragraphs = _split_paragraphs(text_with_placeholders)

        if not paragraphs and not tables:
            continue

        new_chunks = _build_chunks_from_paragraph(
            paragraphs=paragraphs,
            tables=tables,
            section_heading=section.heading,
            section_index=section_index,
            paper_id=paper_id,
            max_words=max_words,
            chunk_index_start=chunk_index,
        )

        all_chunks.extend(new_chunks)
        chunk_index += len(new_chunks)

    return all_chunks
