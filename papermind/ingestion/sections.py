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
  - Docling sometimes emits figure captions and table captions as headings
    (e.g., "Figure 1:", "Table 1:", "Scaled Dot-Product Attention").
    These are filtered out and their content merged with the previous section.
  - References, Acknowledgements, Appendix sections are dropped entirely.
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

FIGURE_HEADING_RES = [
    re.compile(r"^figure\s+\d+", re.IGNORECASE),
    re.compile(r"^table\s+\d+", re.IGNORECASE),
    re.compile(r"^fig\.\s*\d+", re.IGNORECASE),
]

SKIP_SECTION_RES = [
    re.compile(r"^references?$", re.IGNORECASE),
    re.compile(r"^acknowledgements?$", re.IGNORECASE),
    re.compile(r"^acknowledgments?$", re.IGNORECASE),
    re.compile(r"^appendix$", re.IGNORECASE),
]

CAPTION_CONTENT_RES = [
    re.compile(r"^figure\s+\d+", re.IGNORECASE),
    re.compile(r"^table\s+\d+", re.IGNORECASE),
    re.compile(r"^fig\.\s*\d+", re.IGNORECASE),
]


def _strip_noise(text: str) -> str:
    for pattern in NOISE_RES:
        text = pattern.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _drop_author_tables(text: str) -> str:
    def replace(match: re.Match) -> str:
        return "" if "@" in match.group(0) else match.group(0)

    return TABLE_BLOCK_RE.sub(replace, text)


def _is_figure_heading(heading: str) -> bool:
    heading_lower = heading.strip().lower()
    for pattern in FIGURE_HEADING_RES:
        if pattern.match(heading_lower):
            return True
    return False


def _is_skip_section(heading: str) -> bool:
    heading_lower = heading.strip().lower()
    for pattern in SKIP_SECTION_RES:
        if pattern.match(heading_lower):
            return True
    return False


def _contains_email(text: str) -> bool:
    return "@" in text and "." in text


def _is_caption_only_content(content: str) -> bool:
    """Check if content is mostly just a figure/table caption and image placeholders."""
    stripped = _strip_noise(content).strip()
    if not stripped:
        return True
    first_line = stripped.split("\n")[0].strip().lower()
    for pattern in CAPTION_CONTENT_RES:
        if pattern.match(first_line):
            return True
    return False


def _should_drop_heading(heading: str, content: str, idx: int) -> tuple[bool, str]:
    """
    Returns (should_drop, reason).
    reason can be: 'skip_section', 'figure_heading', 'title_block_email', 'caption_only'
    """
    if _is_skip_section(heading):
        return True, 'skip_section'
    if _is_figure_heading(heading):
        return True, 'figure_heading'
    if idx == 0 and _contains_email(content):
        return True, 'title_block_email'
    if _is_caption_only_content(content):
        return True, 'caption_only'
    return False, ''


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

    # First pass: determine which headings to drop
    drop_info = []  # list of (should_drop, reason)
    for idx, (heading, content) in enumerate(raw):
        should_drop, reason = _should_drop_heading(heading, content, idx)
        drop_info.append((should_drop, reason))

    # Second pass: build sections, merging dropped content with previous kept section
    sections = []
    current_section: Section | None = None

    for idx, (heading, content) in enumerate(raw):
        should_drop, reason = drop_info[idx]

        if idx <= 1:
            content = _drop_author_tables(content)

        content = _strip_noise(content)

        if should_drop:
            # Merge figure heading and caption-only content with previous section.
            # Skip sections (References, etc.) are dropped entirely without merging.
            if reason in ('figure_heading', 'caption_only') and current_section is not None and content:
                current_section.content += "\n\n" + content
            continue

        # Not dropped - start a new section
        if content:
            current_section = Section(heading, content)
            sections.append(current_section)
        else:
            current_section = None

    return sections