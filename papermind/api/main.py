"""
main.py

FastAPI app. Six endpoints, matching the API surface described in the
project's technical design doc:

    POST   /papers            upload a PDF, ingest it synchronously
    GET    /papers            list all papers + their status
    GET    /papers/{id}       get one paper's full metadata
    GET    /papers/{id}/status  poll ingestion status
    DELETE /papers/{id}       remove a paper from both stores
    POST   /query             ask a question across the corpus

Ingestion runs synchronously in this prototype (the request blocks
until parsing/chunking/embedding/extraction finish) rather than as a
background task with polling. That is a deliberate simplification for
a first working version -- a 10-page paper ingests in a few seconds
without extraction, so the wait is acceptable at prototype scale. A
production version would push this to a background task (FastAPI's
BackgroundTasks or a proper queue like Celery) and have the client
poll /papers/{id}/status, which is why that endpoint already exists
even though nothing makes it wait right now.
"""

import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, ConfigDict

from papermind.storage.database import init_db, get_session
from papermind.storage.models import Paper
from papermind.ingestion.pipeline import ingest_pdf
from papermind.retrieval.vector_store import (
    delete_paper as delete_paper_vectors,
    count as vector_count,
)
from papermind.query.pipeline import answer_query

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PaperMind", version="0.1.0", lifespan=lifespan)


# Schemas for request/response bodies


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    synthesize: bool = True


class PaperSummary(BaseModel):
    id: str
    filename: str
    title: str | None
    ingestion_status: str
    error_message: str | None

    model_config = ConfigDict(from_attributes=True)


# Endpoints


@app.post("/papers")
async def upload_paper(file: UploadFile = File(...), extract: bool = True):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    dest = UPLOAD_DIR / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    result = ingest_pdf(str(dest), run_extraction=extract)

    if result["status"] == "failed":
        raise HTTPException(422, result["error"])

    return result


@app.get("/papers")
def list_papers() -> list[PaperSummary]:
    with get_session() as session:
        papers = session.query(Paper).all()
        return [PaperSummary.model_validate(p) for p in papers]


@app.get("/papers/{paper_id}")
def get_paper(paper_id: str):
    with get_session() as session:
        paper = session.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise HTTPException(404, "Paper not found")
        return {
            "id": paper.id,
            "filename": paper.filename,
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "key_claim": paper.key_claim,
            "main_result": paper.main_result,
            "limitations": paper.limitations,
            "metadata": paper.extra_metadata,
            "ingestion_status": paper.ingestion_status,
            "error_message": paper.error_message,
            "chunk_count": len(paper.chunks),
        }


@app.get("/papers/{paper_id}/status")
def get_status(paper_id: str):
    with get_session() as session:
        paper = session.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise HTTPException(404, "Paper not found")
        return {
            "id": paper.id,
            "status": paper.ingestion_status,
            "error": paper.error_message,
        }


@app.delete("/papers/{paper_id}")
def delete_paper(paper_id: str):
    with get_session() as session:
        paper = session.query(Paper).filter(Paper.id == paper_id).first()
        if not paper:
            raise HTTPException(404, "Paper not found")
        session.delete(paper)  # cascades to ChunkRecord rows

    delete_paper_vectors(paper_id)
    return {"deleted": paper_id}


@app.post("/query")
def query(request: QueryRequest):
    if vector_count() == 0:
        raise HTTPException(400, "No papers indexed yet. Upload a paper first.")
    return answer_query(
        request.question, top_k=request.top_k, synthesize=request.synthesize
    )


@app.get("/health")
def health():
    return {"status": "ok", "chunks_indexed": vector_count()}
