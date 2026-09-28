"""
Chainlit UI for PaperMind
Run with: chainlit run papermind.ui.chainlit_app -p 8001
"""

import os
import uuid
import chainlit as cl
from typing import List

from papermind.storage.database import init_db
from papermind.query.pipeline import answer_query
from papermind.ingestion.pipeline import ingest_pdf

from papermind.ui.chat_db import init_chat_db, ChatSessionLocal, ChatSession, ChatMessage, ChatFile
from papermind.ui.components.citations import format_citation_side_panel, create_citation_elements
from papermind.ui.components.file_upload import show_files_panel, process_uploaded_file
from papermind.ui.auth import auth_callback


@cl.on_chat_start
async def on_chat_start():
    init_chat_db()
    init_db()  # Initialize paper database
    
    # Create new chat session
    session_id = str(uuid.uuid4())
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("chat_history", [])
    
    with ChatSessionLocal() as db:
        session = ChatSession(id=session_id, title="New Chat")
        db.add(session)
        db.commit()
    
    # Welcome message
    await cl.Message(
        content="Welcome to PaperMind! Upload scientific PDFs and ask questions across your paper collection.",
        elements=[
            cl.Text(name="System", content="Ready to help with your research papers.", display="inline")
        ]
    ).send()
    
    # Show file upload section
    await show_files_panel(session_id)


@cl.on_message
async def on_message(message: cl.Message):
    session_id = cl.user_session.get("session_id")
    
    # Handle file uploads
    if message.elements:
        for element in message.elements:
            if isinstance(element, cl.File) and element.name.lower().endswith('.pdf'):
                await process_uploaded_file(element, session_id)
        await show_files_panel(session_id)
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
    
    # Get answer with citations
    result = answer_query(question, top_k=5, synthesize=True, use_hybrid=True, use_reranker=True)
    
    # Prepare citations for side panel
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
    
    # Send answer with side panel citations
    await cl.Message(
        content=result.get("answer", "No answer generated"),
        elements=create_citation_elements(citations)
    ).send()


@cl.on_settings_update
async def on_settings_update(settings):
    pass


@cl.password_auth_callback
def chainlit_auth_callback(username: str, password: str):
    return auth_callback(username, password)


# Settings
@cl.set_starters
async def set_starters():
    return [
        cl.Starter(
            label="What is the BLEU score of Transformer?",
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