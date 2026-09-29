"""
Chat database models and session management.
Separate from paper database - stores chat history and uploaded files.
"""

import os
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Text, DateTime, ForeignKey, JSON, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, relationship

CHAT_DB_URL = os.environ.get("CHAT_DATABASE_URL", "sqlite:///data/chat_history.db")

class ChatBase(DeclarativeBase):
    pass

class ChatSession(ChatBase):
    __tablename__ = "chat_sessions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=True)
    owner_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    files = relationship("ChatFile", back_populates="session", cascade="all, delete-orphan")

class ChatMessage(ChatBase):
    __tablename__ = "chat_messages"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSON, default=list)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    session = relationship("ChatSession", back_populates="messages")

class ChatFile(ChatBase):
    __tablename__ = "chat_files"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    paper_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="queued")
    error_message = Column(Text, nullable=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    session = relationship("ChatSession", back_populates="files")


chat_engine = create_engine(CHAT_DB_URL)
ChatSessionLocal = sessionmaker(bind=chat_engine, expire_on_commit=False)

def init_chat_db():
    ChatBase.metadata.create_all(chat_engine)
    # create_all does not add columns to existing databases.
    migrations = {
        "chat_sessions": {"owner_id": "VARCHAR"},
        "chat_files": {"status": "VARCHAR NOT NULL DEFAULT 'queued'", "error_message": "TEXT"},
    }
    with chat_engine.begin() as connection:
        for table, columns in migrations.items():
            existing = {column["name"] for column in inspect(chat_engine).get_columns(table)}
            for name, column_type in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_chat_sessions_owner_id ON chat_sessions (owner_id)"
        ))

def get_chat_session():
    """Context manager for chat database sessions."""
    session = ChatSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
