"""
models.py

SQLAlchemy models for the metadata store.

Uses generic sqlalchemy.JSON for the `metadata` column so the exact
same model code runs against SQLite (used here for a self-contained,
zero-setup prototype) or PostgreSQL (the intended production target)
just by changing DATABASE_URL. On Postgres this generic JSON column
still works correctly; to get JSONB's indexing and richer query
operators specifically, swap the import to
`sqlalchemy.dialects.postgresql.JSONB` -- a one-line change, not a
schema rewrite. See storage/database.py for the connection string.

Why SQLite for this prototype specifically: it requires no separate
server process, which makes `git clone && pip install && run` work
for anyone evaluating this project without them needing to install
and configure Postgres first. The schema and query patterns are
identical either way -- this is a deployment choice, not a design
compromise.
"""

import uuid
from datetime import datetime, timezone
import os

from sqlalchemy import Column, String, Integer, Text, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import DeclarativeBase, relationship

# Use JSONB for Postgres, JSON for SQLite
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/papermind.db")
USE_POSTGRES = DATABASE_URL.startswith("postgresql")
if USE_POSTGRES:
    from sqlalchemy.dialects.postgresql import JSONB as JSON_TYPE
else:
    from sqlalchemy import JSON as JSON_TYPE


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Paper(Base):
    __tablename__ = "papers"

    id = Column(String, primary_key=True, default=_uuid)
    filename = Column(String, nullable=False)
    file_hash = Column(String, unique=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # 'pending' | 'parsing' | 'chunking' | 'embedding' | 'extracting' | 'complete' | 'failed'
    ingestion_status = Column(String, default="pending")
    error_message = Column(Text, nullable=True)

    # Fixed fields every paper has, regardless of research domain
    title = Column(Text, nullable=True)
    authors = Column(JSON_TYPE, default=list)     # stored as JSON list, portable across SQLite/Postgres
    year = Column(Integer, nullable=True)
    key_claim = Column(Text, nullable=True)
    main_result = Column(Text, nullable=True)
    limitations = Column(Text, nullable=True)

    # Dynamic, domain-specific fields extracted by the LLM.
    # e.g. {"analyte": "acetone", "response_time_seconds": 7.2}
    extra_metadata = Column(JSON_TYPE, default=dict)

    chunks = relationship("ChunkRecord", back_populates="paper", cascade="all, delete-orphan")


class ChunkRecord(Base):
    """
    Mirrors what is stored in ChromaDB, so Postgres always knows which
    chunks exist for a paper even without querying the vector store --
    used by the consistency check between the two stores.
    """
    __tablename__ = "chunks"

    id = Column(String, primary_key=True, default=_uuid)
    paper_id = Column(String, ForeignKey("papers.id", ondelete="CASCADE"))
    section = Column(String)
    chunk_index = Column(Integer)
    text = Column(Text)
    word_count = Column(Integer)
    is_table = Column(Boolean, default=False)
    chroma_id = Column(String, unique=True)  # links to the vector in ChromaDB

    paper = relationship("Paper", back_populates="chunks")
