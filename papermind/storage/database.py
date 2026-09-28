"""
database.py

Connection setup. DATABASE_URL controls which backend is used:

    sqlite:///data/papermind.db                        (default, zero setup)
    postgresql://user:pass@localhost:5432/papermind     (production)

Nothing else in the codebase needs to change to switch -- every other
module talks to the ORM models, never to raw SQL or a specific
backend's dialect.
"""

import os
from pathlib import Path
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from papermind.storage.models import Base

Path("data").mkdir(exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/papermind.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db():
    Base.metadata.create_all(engine)


@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
