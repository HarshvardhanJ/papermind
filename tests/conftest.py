"""Isolate every test run: temp SQLite DB and temp Chroma dir, offline embedder.
Must run before any papermind module is imported (they read env at import time)."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="papermind_test_")
os.environ["PAPERMIND_OFFLINE_EMBED"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["CHROMA_PERSIST_DIR"] = f"{_tmp}/chroma"
