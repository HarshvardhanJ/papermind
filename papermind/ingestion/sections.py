"""
sections.py

Turns the markdown that Docling exports into a list of (heading, content)
sections, which is what the chunker consumes.

Docling already did the hard layout work (reading order, headings, tables),
so this module only has to read that structure back out of the markdown:

  - '#', '##' or '###' lines start a new section.
  - '<!-- image -->' and '<!-- formula-not-decoded -->' placeholders are
    removed, since they carry no text to embed.
  - Docling renders the author/affiliation block as a pipe table. That
    block is useless for retrieval, so any table containing an email
    address in the title section is dropped.
"""

import re
from dataclasses import dataclass


@dataclass
class Section:
    heading: str
    content: str


HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)
NOISE_RES = [
    re.compile(r"<!--\s*image\s*-->", re.IGNORECASE),
    re.compile(r"<!--\s*formula-not-decoded\s*-->", re.IGNORECASE),
]
TABLE_BLOCK_RE = re.compile(r"(?:^[ \t]*\|.*\|[ \t]*\n?)+", re.MULTILINE)


def _strip_noise(text: str) -> str:
    for pattern in NOISE_RES:
        text = pattern.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _drop_author_tables(text: str) -> str:
    def replace(match: re.Match) -> str:
        return "" if "@" in match.group(0) else match.group(0)

    return TABLE_BLOCK_RE.sub(replace, text)


def markdown_to_sections(markdown: str) -> list[Section]:
    matches = list(HEADING_RE.finditer(markdown))

    if not matches:
        content = _strip_noise(markdown)
        return [Section("document", content)] if content else []

    raw: list[tuple[str, str]] = []
    preamble = markdown[: matches[0].start()]
    if preamble.strip():
        raw.append(("preamble", preamble))

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        raw.append((m.group(1).strip(), markdown[m.end():end]))

    sections = []
    for idx, (heading, content) in enumerate(raw):
        if idx <= 1:  # title block only; never touch tables deeper in the paper
            content = _drop_author_tables(content)
        content = _strip_noise(content)
        if content:
            sections.append(Section(heading, content))
    return sections
