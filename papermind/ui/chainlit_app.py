"""Chainlit UI for PaperMind.

Run with: chainlit run papermind.ui.chainlit_app -p 8001
"""

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import chainlit as cl

from papermind.ingestion.pipeline import ingest_pdf
from papermind.query.pipeline import answer_query
from papermind.storage.database import init_db
from papermind.ui.auth import auth_callback
from papermind.ui.chat_db import (
    ChatFile,
    ChatMessage,
    ChatSession,
    ChatSessionLocal,
    init_chat_db,
)
from papermind.ui.components.citations import append_citation_tooltips
from papermind.ui.data_layer import ChatHistoryDataLayer


@cl.data_layer
def chainlit_data_layer():
    return ChatHistoryDataLayer()


@cl.on_app_startup
async def initialize_chat_storage():
    init_chat_db()


def _status_label(status: str) -> str:
    labels = {
        "queued": "Queued",
        "parsing": "Reading PDF",
        "chunking": "Preparing sections",
        "embedding": "Indexing for search",
        "extracting": "Extracting paper details",
        "complete": "Ready to search",
        "duplicate": "Already indexed",
        "failed": "Could not index",
    }
    status = status or "queued"
    return labels.get(status, status.replace("_", " ").capitalize())


def _files_panel_content(session_id: str) -> str:
    with ChatSessionLocal() as db:
        files = (
            db.query(ChatFile)
            .filter(ChatFile.session_id == session_id)
            .order_by(ChatFile.uploaded_at.desc())
            .all()
        )
        rows = []
        for file in files:
            status = file.status or "queued"
            if status == "queued" and file.paper_id:
                status = "complete"
            rows.append((file.filename, status, file.error_message))

    if not rows:
        return "## Your library\n\nNo papers in this chat yet. Upload a PDF to add it to your searchable library."

    lines = ["## Your library", ""]
    for filename, status, error in rows:
        icon = "✅" if status in {"complete", "duplicate"} else "❌" if status == "failed" else "⏳"
        lines.append(f"**{filename}**  \n{icon} {_status_label(status)}")
        if error:
            lines.append(f"\n_{error}_")
        lines.append("")
    return "\n".join(lines)


async def _open_files_sidebar(session_id: str) -> None:
    await cl.ElementSidebar.set_title("Your papers")
    element = cl.Text(
        name="Files",
        content=_files_panel_content(session_id),
        display="inline",
    )
    await cl.ElementSidebar.set_elements([element], key=f"files-{session_id}-{uuid.uuid4().hex}")


@cl.action_callback("open_files")
async def open_files(action: cl.Action):
    session_id = cl.user_session.get("session_id")
    if session_id:
        await _open_files_sidebar(session_id)


@cl.on_chat_start
async def on_chat_start():
    init_chat_db()
    init_db()

    user = cl.user_session.get("user")
    user_id = getattr(user, "identifier", "local")
    session_id = cl.context.session.thread_id
    cl.user_session.set("session_id", session_id)

    with ChatSessionLocal() as db:
        db.add(ChatSession(id=session_id, owner_id=user_id, title="New chat"))
        db.query(ChatSession).filter(ChatSession.owner_id.is_(None)).update(
            {ChatSession.owner_id: user_id}, synchronize_session=False
        )
        db.commit()

    await _open_files_sidebar(session_id)
    await cl.Message(
        content="Upload scientific PDFs and ask questions across your collection. Your library is in the right panel; hover a source number to preview its citation.",
        author="PaperMind",
        actions=[cl.Action(name="open_files", payload={}, label="Open files", icon="files")],
    ).send()


@cl.on_chat_resume
async def on_chat_resume(thread: dict):
    init_chat_db()
    init_db()
    session_id = thread["id"]
    cl.user_session.set("session_id", session_id)
    await _open_files_sidebar(session_id)


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")
    if not session_id:
        return

    uploads = [
        element for element in (message.elements or [])
        if isinstance(element, cl.File)
    ]
    if uploads:
        for file in uploads:
            if not file.name.lower().endswith(".pdf"):
                await cl.Message(
                    content=f"`{file.name}` was skipped. PaperMind currently accepts PDF files.",
                    author="PaperMind",
                ).send()
                continue
            await process_uploaded_file_with_progress(file, session_id)
        return

    question = (message.content or "").strip()
    if not question:
        return

    user = cl.user_session.get("user")
    user_id = getattr(user, "identifier", "local")
    with ChatSessionLocal() as db:
        user_msg = ChatMessage(
            id=str(uuid.uuid4()), session_id=session_id, role="user", content=question
        )
        db.add(user_msg)
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session and session.title in {"New chat", "Untitled chat", None}:
            session.title = question[:72]
        if session:
            session.owner_id = user_id
            session.updated_at = datetime.now(timezone.utc)
        db.commit()

    answer_msg = cl.Message(content="Searching your papers…", author="PaperMind")
    await answer_msg.send()
    try:
        result = await asyncio.to_thread(
            answer_query,
            question,
            top_k=5,
            synthesize=True,
            use_hybrid=True,
            use_reranker=True,
        )
        citations = [
            {
                "index": index,
                "title": source.get("title", "Unknown"),
                "section": source.get("section", ""),
                "text": source.get("text", "")[:500],
                "distance": source.get("relevance_distance"),
            }
            for index, source in enumerate(result.get("sources", []), 1)
        ]
        answer = result.get("answer") or "I couldn't find an answer in the available papers."
        answer = append_citation_tooltips(answer, citations)
        with ChatSessionLocal() as db:
            db.add(ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=answer,
                citations=citations,
            ))
            db.commit()

        answer_msg.content = answer
        answer_msg.actions = [
            cl.Action(name="open_files", payload={}, label="Files", icon="files")
        ]
        await answer_msg.update()
    except Exception as exc:
        answer_msg.content = f"I couldn't complete that search: {exc}"
        with ChatSessionLocal() as db:
            db.add(ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=answer_msg.content,
                citations=[],
            ))
            db.commit()
        await answer_msg.update()


async def process_uploaded_file_with_progress(file: cl.File, session_id: str) -> None:
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.name).name
    file_path = upload_dir / uuid.uuid4().hex / safe_name
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(file.content)
    file_hash = hashlib.sha256(file.content).hexdigest()

    chat_file_id = str(uuid.uuid4())
    with ChatSessionLocal() as db:
        db.add(ChatFile(
            id=chat_file_id,
            session_id=session_id,
            filename=safe_name,
            file_path=str(file_path),
            status="queued",
        ))
        session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
        if session:
            session.updated_at = datetime.now(timezone.utc)
            if session.title in {"New chat", "Untitled chat", None}:
                session.title = Path(safe_name).stem[:72]
        db.commit()

    status_message = cl.Message(
        content=f"**{safe_name}** · Upload received\n\n⏳ Starting ingestion…",
        author="PaperMind",
        actions=[cl.Action(name="open_files", payload={}, label="Open files", icon="files")],
    )
    await status_message.send()

    ingestion = asyncio.create_task(asyncio.to_thread(
        ingest_pdf, str(file_path), run_extraction=True, max_words=200, overlap_words=50
    ))
    previous_status = "queued"
    paper_id = None
    while not ingestion.done():
        with ChatSessionLocal() as db:
            chat_file = db.query(ChatFile).filter(ChatFile.id == chat_file_id).first()
            if chat_file:
                chat_file.status = "parsing"
            db.commit()

        from papermind.storage.database import get_session
        from papermind.storage.models import Paper

        with get_session() as db:
            paper = db.query(Paper).filter(Paper.file_hash == file_hash).first()
            if paper:
                paper_id = paper.id
                current_status = paper.ingestion_status or "parsing"
                if current_status != previous_status:
                    previous_status = current_status
                    status_message.content = f"**{safe_name}** · {_status_label(current_status)}"
                    await status_message.update()

        if previous_status != "queued":
            with ChatSessionLocal() as db:
                chat_file = db.query(ChatFile).filter(ChatFile.id == chat_file_id).first()
                if chat_file:
                    chat_file.status = previous_status
                    chat_file.paper_id = paper_id
                db.commit()
        await asyncio.sleep(0.8)

    try:
        result = await ingestion
        paper_id = result.get("paper_id") or paper_id
        final_status = result.get("status", "failed")
        error = result.get("error") if final_status == "failed" else None
        with ChatSessionLocal() as db:
            chat_file = db.query(ChatFile).filter(ChatFile.id == chat_file_id).first()
            if chat_file:
                chat_file.paper_id = paper_id
                chat_file.status = final_status
                chat_file.error_message = error
            db.commit()

        if final_status in {"complete", "duplicate"}:
            detail = f" · {result.get('chunks', 0)} chunks indexed" if final_status == "complete" else " · this paper is already in the library"
            status_message.content = f"✅ **{safe_name}** · {_status_label(final_status)}{detail}"
        else:
            status_message.content = f"❌ **{safe_name}** · {_status_label(final_status)}"
            if error:
                status_message.content += f"\n\n{error}"
        await status_message.update()
    except Exception as exc:
        with ChatSessionLocal() as db:
            chat_file = db.query(ChatFile).filter(ChatFile.id == chat_file_id).first()
            if chat_file:
                chat_file.status = "failed"
                chat_file.error_message = str(exc)
            db.commit()
        status_message.content = f"❌ **{safe_name}** · Ingestion failed\n\n{exc}"
        await status_message.update()


@cl.on_settings_update
async def on_settings_update(settings):
    pass


@cl.password_auth_callback
def chainlit_auth_callback(username: str, password: str):
    return auth_callback(username, password)


@cl.set_starters
async def set_starters():
    return [
        cl.Starter(label="Transformer BLEU score", message="What is the BLEU score on WMT 2014 English-German for the Transformer big model?", icon="📊"),
        cl.Starter(label="FlashAttention", message="How does FlashAttention improve attention computation?", icon="⚡"),
        cl.Starter(label="Explain RAG", message="What is retrieval-augmented generation?", icon="🔍"),
        cl.Starter(label="Compare BERT and RoBERTa", message="How does RoBERTa differ from BERT?", icon="🤖"),
    ]
