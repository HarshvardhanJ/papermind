"""
Chainlit UI for PaperMind
Run with: chainlit run papermind.ui.chainlit_app -p 8001
"""

import os
import uuid
import asyncio
import chainlit as cl
from typing import List, Optional
from datetime import datetime

from papermind.storage.database import init_db
from papermind.query.pipeline import answer_query
from papermind.ingestion.pipeline import ingest_pdf

from papermind.ui.chat_db import (
    init_chat_db, ChatSessionLocal, ChatSession, ChatMessage, ChatFile
)
from papermind.ui.components.citations import format_citation_side_panel, create_citation_elements
from papermind.ui.components.file_upload import show_files_panel, process_uploaded_file
from papermind.ui.auth import auth_callback


# Store persistent elements in user session
async def get_or_create_elements(session_id: str):
    """Get or create persistent UI elements."""
    elements = cl.user_session.get("ui_elements")
    if elements is None:
        elements = {
            "files_panel": None,
            "citations_panel": None,
            "status_indicator": None,
        }
        cl.user_session.set("ui_elements", elements)
    return elements


async def update_files_panel(session_id: str, message: str = ""):
    """Update the files side panel with current file list."""
    with ChatSessionLocal() as db:
        files = db.query(ChatFile).filter(ChatFile.session_id == session_id).all()
    
    if not files:
        content = "📄 **No files uploaded yet.**\nDrag & drop PDFs below to get started."
    else:
        lines = ["## 📁 Uploaded Files\n"]
        for f in files:
            status = "✅ **Indexed**" if f.paper_id else "⏳ **Processing...**"
            uploaded = f.uploaded_at.strftime("%H:%M") if f.uploaded_at else ""
            lines.append(f"📄 **{f.filename}**  \n{status}  \n*Uploaded: {uploaded}*")
            lines.append("---")
        content = "\n".join(lines)
    
    # Use persistent element
    elements = await get_or_create_elements(session_id)
    if elements["files_panel"] is None:
        elements["files_panel"] = cl.Text(name="Files", content=content, display="side")
        await cl.Message(content="", elements=[elements["files_panel"]]).send()
    else:
        elements["files_panel"].content = content
        await elements["files_panel"].update()


async def show_ingestion_status(session_id: str, filename: str, status: str, progress: int = 0):
    """Show ingestion progress in the status panel."""
    elements = await get_or_create_elements(session_id)
    
    if status == "started":
        content = f"🔄 **Ingesting {filename}**\n\n"
    elif status == "parsing":
        content = f"📄 **Parsing {filename}** ({progress}%)\n\n"
    elif status == "chunking":
        content = f"✂️ **Chunking {filename}** ({progress}%)\n\n"
    elif status == "embedding":
        content = f"🔢 **Embedding {filename}** ({progress}%)\n\n"
    elif status == "extracting":
        content = f"🤖 **Extracting metadata {filename}** ({progress}%)\n\n"
    elif status == "complete":
        content = f"✅ **{filename} indexed successfully!**\n\n"
    elif status == "failed":
        content = f"❌ **Failed to ingest {filename}**\n\n"
    else:
        content = f"⏳ **{status} {filename}**\n\n"
    
    # Add progress bar
    if 0 < progress < 100:
        bar_len = 20
        filled = int(bar_len * progress / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        content += f"`{bar}` {progress}%"
    
    if elements["status_indicator"] is None:
        elements["status_indicator"] = cl.Text(name="Status", content=content, display="side")
        await cl.Message(content="", elements=[elements["status_indicator"]]).send()
    else:
        elements["status_indicator"].content = content
        await elements["status_indicator"].update()


async def clear_ingestion_status(session_id: str):
    """Clear the ingestion status panel."""
    elements = await get_or_create_elements(session_id)
    if elements["status_indicator"]:
        elements["status_indicator"].content = ""
        await elements["status_indicator"].update()


async def update_citations_panel(citations: list):
    """Update the citations side panel."""
    elements = await get_or_create_elements(cl.user_session.get("session_id"))
    content = format_citation_side_panel(citations)
    
    if elements["citations_panel"] is None:
        elements["citations_panel"] = cl.Text(name="Citations", content=content, display="side")
        await cl.Message(content="", elements=[elements["citations_panel"]]).send()
    else:
        elements["citations_panel"].content = content
        await elements["citations_panel"].update()


async def load_chat_history(session_id: str):
    """Load and display chat history."""
    with ChatSessionLocal() as db:
        messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at).all()
    
    if not messages:
        return
    
    # Replay messages
    for msg in messages:
        if msg.role == "user":
            await cl.Message(content=msg.content, author="You").send()
        else:
            citations = msg.citations or []
            if citations:
                await update_citations_panel(citations)
            await cl.Message(content=msg.content, author="PaperMind").send()


@cl.on_chat_start
async def on_chat_start():
    init_chat_db()
    init_db()
    
    # Create new chat session
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    
    with ChatSessionLocal() as db:
        session = ChatSession(id=session_id, title="New Chat")
        db.add(session)
        db.commit()
    
    # Initialize UI elements
    await get_or_create_elements(session_id)
    
    # Load chat history
    await load_chat_history(session_id)
    
    # Welcome message
    await cl.Message(
        content="Welcome to **PaperMind**! 📚\n\nUpload scientific PDFs and ask questions across your paper collection.",
        author="PaperMind"
    ).send()
    
    # Show files panel
    await update_files_panel(session_id)
    
    # Show empty status panel (ready state)
    elements = await get_or_create_elements(session_id)
    elements["status_indicator"] = cl.Text(name="Status", content="🟢 **Ready** — Upload a PDF or ask a question", display="side")
    await cl.Message(content="", elements=[elements["status_indicator"]]).send()


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")
    
    # Handle file uploads
    if message.elements:
        for element in message.elements:
            if isinstance(element, cl.File) and element.name.lower().endswith('.pdf'):
                # Show immediate feedback
                await show_ingestion_status(session_id, element.name, "started", 5)
                
                # Process with detailed progress
                await process_uploaded_file_with_progress(element, session_id)
                
                # Refresh files panel
                await update_files_panel(session_id)
        return
    
    # Process question
    question = message.content
    
    # Save user message
    with ChatSessionLocal() as db:
        user_msg = ChatMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="user",
            content=question
        )
        db.add(user_msg)
        db.commit()
    
    # Show thinking indicator
    thinking_msg = cl.Message(content="🤔 Thinking...", author="PaperMind")
    await thinking_msg.send()
    
    try:
        # Get answer with citations
        result = answer_query(question, top_k=5, synthesize=True, use_hybrid=True, use_reranker=True)
        
        # Prepare citations
        citations = []
        for i, source in enumerate(result.get("sources", []), 1):
            citations.append({
                "index": i,
                "title": source.get("title", "Unknown"),
                "section": source.get("section", ""),
                "text": source.get("text", "")[:500],
                "distance": source.get("relevance_distance", 0)
            })
        
        # Save assistant message
        with ChatSessionLocal() as db:
            asst_msg = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=result.get("answer", "No answer generated"),
                citations=citations
            )
            db.add(asst_msg)
            db.commit()
        
        # Update citations panel
        await update_citations_panel(citations)
        
        # Replace thinking message with answer
        thinking_msg.content = result.get("answer", "No answer generated")
        thinking_msg.elements = create_citation_elements(citations)
        await thinking_msg.update()
        
    except Exception as e:
        thinking_msg.content = f"❌ Error: {str(e)}"
        await thinking_msg.update()


async def process_uploaded_file_with_progress(file: cl.File, session_id: str):
    """Process uploaded PDF with detailed progress updates."""
    upload_dir = "data/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.name)
    
    # Save file
    await show_ingestion_status(session_id, file.name, "parsing", 10)
    with open(file_path, "wb") as f:
        f.write(file.content)
    
    # Save to chat database
    with ChatSessionLocal() as db:
        chat_file = ChatFile(
            id=str(uuid.uuid4()),
            session_id=session_id,
            filename=file.name,
            file_path=file_path,
            paper_id=None
        )
        db.add(chat_file)
        db.commit()
    
    # Ingest with progress simulation
    stages = [
        ("parsing", 20),
        ("chunking", 40),
        ("embedding", 70),
        ("extracting", 90),
        ("complete", 100)
    ]
    
    for stage, progress in stages:
        await show_ingestion_status(session_id, file.name, stage, progress)
        await asyncio.sleep(0.5)  # Small delay for visual feedback
    
    try:
        result = ingest_pdf(file_path, run_extraction=True, max_words=200, overlap_words=50)
        
        # Update with paper_id
        with ChatSessionLocal() as db:
            chat_file = db.query(ChatFile).filter(
                ChatFile.session_id == session_id,
                ChatFile.filename == file.name
            ).first()
            if chat_file:
                chat_file.paper_id = result.get("paper_id")
                db.commit()
        
        await show_ingestion_status(session_id, file.name, "complete", 100)
        await asyncio.sleep(1)
        await clear_ingestion_status(session_id)
        
    except Exception as e:
        await show_ingestion_status(session_id, file.name, "failed", 0)
        await cl.Message(content=f"❌ Failed to process {file.name}: {str(e)}", author="System").send()


@cl.on_settings_update
async def on_settings_update(settings):
    pass


@cl.password_auth_callback
def chainlit_auth_callback(username: str, password: str):
    return auth_callback(username, password)


@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="BLEU score of Transformer",
            message="What is the BLEU score on WMT 2014 English-German for the Transformer big model?",
            icon="📊"
        ),
        cl.Starter(
            label="How does FlashAttention work?",
            message="How does FlashAttention improve attention computation?",
            icon="⚡"
        ),
        cl.Starter(
            label="What is RAG?",
            message="What is RAG (Retrieval-Augmented Generation)?",
            icon="🔍"
        ),
        cl.Starter(
            label="Compare BERT and RoBERTa",
            message="How does RoBERTa differ from BERT?",
            icon="🤖"
        ),
    ]


if __name__ == "__main__":
    from chainlit.cli import run_chainlit
    run_chainlit(__file__)