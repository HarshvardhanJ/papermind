"""
File upload components for Chainlit UI.
"""

import os
import chainlit as cl
from typing import List
from papermind.ui.chat_db import ChatSessionLocal, ChatFile


def format_files_list(files: List[ChatFile]) -> str:
    """Format uploaded files list for display."""
    if not files:
        return "No files uploaded yet. Drag & drop PDFs below."
    
    lines = []
    for f in files:
        status = "✅ Indexed" if f.paper_id else "⏳ Processing"
        lines.append(f"📄 **{f.filename}** {status}")
    return "\n".join(lines)


async def show_files_panel(session_id: str):
    """Display uploaded files in side panel."""
    with ChatSessionLocal() as db:
        files = db.query(ChatFile).filter(ChatFile.session_id == session_id).all()
    
    content = format_files_list(files)
    
    await cl.Message(
        content=content,
        author="Files",
        elements=[cl.Text(name="Uploaded Files", content=content, display="side")]
    ).send()


async def process_uploaded_file(file: cl.File, session_id: str):
    """Process uploaded PDF file."""
    if not file.name.lower().endswith('.pdf'):
        await cl.Message(content=f"❌ {file.name}: Only PDF files are supported").send()
        return
    
    # Save file to uploads directory
    upload_dir = "data/uploads"
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.name)
    
    with open(file_path, "wb") as f:
        f.write(file.content)
    
    # Save to chat database
    with ChatSessionLocal() as db:
        chat_file = ChatFile(
            id=__import__('uuid').uuid4().hex,
            session_id=session_id,
            filename=file.name,
            file_path=file_path,
            paper_id=None
        )
        db.add(chat_file)
        db.commit()
    
    # Ingest in background
    await cl.Message(content=f"Processing {file.name}...").send()
    
    try:
        from papermind.ingestion.pipeline import ingest_pdf
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
        
        await cl.Message(content=f"✅ {file.name} indexed ({result.get('chunks', 0)} chunks)").send()
    except Exception as e:
        await cl.Message(content=f"❌ Failed to process {file.name}: {str(e)}").send()
    
    # Refresh files panel
    await show_files_panel(session_id)