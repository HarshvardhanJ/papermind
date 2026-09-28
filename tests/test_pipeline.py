"""
Tests that need no API key, no Docling and no model download.
Docling output is represented by tests/fixtures/sample_docling.md.
"""

from pathlib import Path

import pytest

from papermind.ingestion.sections import Section, markdown_to_sections
from papermind.ingestion.chunker import chunk_sections
from papermind.eval.evaluate import evaluate, is_hit

FIXTURE = (Path(__file__).parent / "fixtures" / "sample_docling.md").read_text()


# ---------------- sections ----------------


def test_headings_become_sections():
    headings = [s.heading for s in markdown_to_sections(FIXTURE)]
    for expected in ["Abstract", "1 Introduction", "3 Results"]:
        assert expected in headings
    assert "References" not in headings


def test_author_table_and_placeholders_are_removed():
    text = "\n".join(s.content for s in markdown_to_sections(FIXTURE))
    assert "@" not in text
    assert "<!--" not in text


def test_results_table_is_not_mistaken_for_author_table():
    results = next(s for s in markdown_to_sections(FIXTURE) if s.heading == "3 Results")
    assert "Detection limit" in results.content


def test_markdown_without_headings_falls_back_to_one_section():
    sections = markdown_to_sections("Just some text.\n\nMore text.")
    assert len(sections) == 1 and sections[0].heading == "document"


# ---------------- chunker ----------------


def chunks():
    return chunk_sections(markdown_to_sections(FIXTURE), paper_id="p1")


def test_references_are_dropped():
    assert all("Smith et al" not in c.text for c in chunks())


def test_table_is_its_own_chunk_with_caption():
    tables = [c for c in chunks() if c.is_table]
    assert len(tables) == 1
    assert tables[0].text.startswith("Table 1:")
    assert "PEDOT:PSS/AuPd" in tables[0].text


def test_prose_is_never_merged_into_a_table_chunk():
    for c in chunks():
        if c.is_table:
            assert "Room-temperature" not in c.text and "exhibited" not in c.text


def test_chunks_never_cross_sections():
    for c in chunks():
        if c.section == "Abstract":
            assert "chloroauric" not in c.text


def test_chunk_indices_are_sequential():
    assert [c.chunk_index for c in chunks()] == list(range(len(chunks())))


def test_long_paragraph_is_split_on_sentences():
    para = " ".join(f"Sentence number {i} has some words in it." for i in range(200))
    out = chunk_sections([Section("Methods", para)], paper_id="p1", max_words=50)
    assert len(out) > 1 and all(c.word_count <= 60 for c in out)


def test_is_hit_requires_all_keywords():
    assert is_hit("response time was 7.2 seconds", ["7.2 seconds"])
    assert not is_hit("response time was 7.2 seconds", ["7.2 seconds", "ethanol"])


# ---------------- end to end (parser stubbed) ----------------


@pytest.fixture()
def stub_parser(monkeypatch):
    monkeypatch.setattr(
        "papermind.ingestion.pipeline._parse_to_markdown", lambda _p: FIXTURE
    )


def test_ingest_search_and_eval(tmp_path, stub_parser):
    from papermind.storage.database import init_db
    from papermind.ingestion.pipeline import ingest_pdf

    init_db()
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-fake-1")

    result = ingest_pdf(str(pdf), run_extraction=False)
    assert result["status"] == "complete" and result["chunks"] > 0

    duplicate = ingest_pdf(str(pdf), run_extraction=False)
    assert duplicate["status"] == "duplicate"

    report = evaluate(
        [
            {
                "question": "What response time did the composite sensor achieve?",
                "expected_keywords": ["7.2 seconds"],
            },
            {
                "question": "How were the gold nanoparticles synthesized?",
                "expected_keywords": ["chloroauric"],
            },
            {
                "question": "Detection limit and response time of each sensor",
                "expected_keywords": ["Detection limit (ppm)"],
            },
        ],
        k=3,
    )
    assert report["hit_rate"] == 1.0


def test_api_upload_query_delete(tmp_path, stub_parser):
    from fastapi.testclient import TestClient
    from papermind.api.main import app

    with TestClient(app) as client:
        r = client.post(
            "/papers?extract=false",
            files={"file": ("second.pdf", b"%PDF-fake-2", "application/pdf")},
        )
        assert r.status_code == 200, r.text
        paper_id = r.json()["paper_id"]

        assert client.get(f"/papers/{paper_id}/status").json()["status"] == "complete"

        q = client.post(
            "/query", json={"question": "response time", "synthesize": False}
        )
        assert q.status_code == 200 and q.json()["sources"]

        assert (
            client.post(
                "/papers", files={"file": ("x.txt", b"hi", "text/plain")}
            ).status_code
            == 400
        )
        assert client.delete(f"/papers/{paper_id}").status_code == 200
        assert client.get(f"/papers/{paper_id}").status_code == 404
