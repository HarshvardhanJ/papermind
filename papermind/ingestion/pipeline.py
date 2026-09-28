"""
pipeline.py (ingestion)

Orchestrates the full ingestion of one PDF:

  parse (Docling -> markdown) -> sections -> chunk -> embed+store in ChromaDB -> store chunk records in
  SQL -> extract structured metadata -> update Paper status

Each step updates Paper.ingestion_status, so if the process crashes
partway through, the next startup's consistency check (see
storage/consistency.py) knows exactly which papers are incomplete.
"""

import hashlib
from pathlib import Path

from papermind.ingestion.sections import markdown_to_sections
from papermind.ingestion.chunker import chunk_sections
from papermind.retrieval.vector_store import add_chunks
from papermind.extraction.extractor import extract_metadata
from papermind.storage.database import get_session
from papermind.storage.models import Paper, ChunkRecord


def _parse_to_markdown(pdf_path: str) -> str:
    # Imported lazily: Docling is slow to import and loads model weights,
    # so nothing else (API startup, tests) should pay for it until a PDF
    # actually needs parsing.
    from papermind.ingestion.parser import parse_pdf_cached
    return parse_pdf_cached(Path(pdf_path))


def _file_hash(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ingest_pdf(pdf_path: str, run_extraction: bool = True) -> dict:
    """
    Returns a summary dict: {"paper_id", "status", "chunks", "error"}
    """
    filename = Path(pdf_path).name
    file_hash = _file_hash(pdf_path)

    # Duplicate check
    with get_session() as session:
        existing = session.query(Paper).filter(Paper.file_hash == file_hash).first()
        if existing:
            return {
                "paper_id": existing.id,
                "status": "duplicate",
                "chunks": 0,
                "error": f"Already indexed as '{existing.title or existing.filename}'",
            }

    paper = Paper(filename=filename, file_hash=file_hash, ingestion_status="parsing")
    with get_session() as session:
        session.add(paper)
        session.flush()
        paper_id = paper.id

    # --- Parse ---
    try:
        markdown = _parse_to_markdown(pdf_path)
        sections = markdown_to_sections(markdown)
    except Exception as e:
        _mark_failed(paper_id, f"Parsing failed: {e}")
        return {"paper_id": paper_id, "status": "failed", "chunks": 0, "error": str(e)}

    _update_status(paper_id, "chunking")

    # --- Chunk ---
    try:
        chunks = chunk_sections(sections, paper_id=paper_id)
    except Exception as e:
        _mark_failed(paper_id, f"Chunking failed: {e}")
        return {"paper_id": paper_id, "status": "failed", "chunks": 0, "error": str(e)}

    if not chunks:
        _mark_failed(paper_id, "No extractable text found (possibly a scanned PDF)")
        return {"paper_id": paper_id, "status": "failed", "chunks": 0, "error": "No text extracted"}

    _update_status(paper_id, "embedding")

    # --- Embed + store vectors ---
    try:
        add_chunks(chunks)
    except Exception as e:
        _mark_failed(paper_id, f"Embedding/storage failed: {e}")
        return {"paper_id": paper_id, "status": "failed", "chunks": 0, "error": str(e)}

    # --- Store chunk records in SQL (mirrors what's in ChromaDB) ---
    with get_session() as session:
        for c in chunks:
            session.add(ChunkRecord(
                paper_id=paper_id,
                section=c.section,
                chunk_index=c.chunk_index,
                text=c.text,
                word_count=c.word_count,
                is_table=c.is_table,
                chroma_id=f"{c.paper_id}::{c.chunk_index}",
            ))

    # --- Extract structured metadata ---
    if run_extraction:
        _update_status(paper_id, "extracting")
        try:
            extraction, error = extract_metadata(markdown)
        except Exception as e:
            extraction, error = None, str(e)

        if extraction:
            with get_session() as session:
                p = session.query(Paper).filter(Paper.id == paper_id).first()
                p.title = extraction.title
                p.authors = extraction.authors
                p.year = extraction.year
                p.key_claim = extraction.key_claim
                p.main_result = extraction.main_result
                p.limitations = extraction.limitations
                p.extra_metadata = extraction.dynamic_metadata
                p.ingestion_status = "complete"
        else:
            # Chunks are still stored and searchable -- only the
            # structured metadata is missing. Not a hard failure.
            _update_status(paper_id, "complete", error_message=f"Extraction failed: {error}")
    else:
        _update_status(paper_id, "complete")

    return {"paper_id": paper_id, "status": "complete", "chunks": len(chunks), "error": None}


def _update_status(paper_id: str, status: str, error_message: str | None = None):
    with get_session() as session:
        p = session.query(Paper).filter(Paper.id == paper_id).first()
        if p:
            p.ingestion_status = status
            if error_message:
                p.error_message = error_message


def _mark_failed(paper_id: str, error_message: str):
    _update_status(paper_id, "failed", error_message)


if __name__ == "__main__":
    import sys
    from papermind.storage.database import init_db

    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <path_to_pdf> [--no-extract]")
        sys.exit(1)

    init_db()
    run_extraction = "--no-extract" not in sys.argv
    result = ingest_pdf(sys.argv[1], run_extraction=run_extraction)
    print(result)
