"""
embedder.py

Thin wrapper around sentence-transformers. Kept as its own module
(rather than calling the library directly wherever needed) so the
model is loaded exactly once and so swapping models later means
changing one file, not every call site.

PAPERMIND_OFFLINE_EMBED:
    A deterministic, dependency-free fallback embedder used only when
    this env var is set to "1". It exists because sandboxed/offline
    dev environments sometimes cannot reach huggingface.co to download
    model weights on first run. It is NOT used in normal operation --
    on a machine with regular internet access, sentence-transformers
    downloads once, caches locally, and every future call is local and
    free. This flag is a development convenience, not the real design.
"""

import hashlib
import math
import os
import re

MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, runs on CPU, ~80MB, downloads once

_model = None
_OFFLINE = os.environ.get("PAPERMIND_OFFLINE_EMBED") == "1"


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
    return _model


# ---------------------------------------------------------------------
# Offline fallback: hashed bag-of-words, L2-normalized.
# Not semantically meaningful in the way a real embedding model is --
# it captures word overlap, not synonymy or paraphrase similarity --
# but it is enough to exercise the ChromaDB storage/retrieval plumbing
# without a network call, which is all it is used for here.
# ---------------------------------------------------------------------

_DIM = 384

def _hashing_embed(text: str) -> list[float]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    vec = [0.0] * _DIM
    for w in words:
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        vec[h % _DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if _OFFLINE:
        return [_hashing_embed(t) for t in texts]
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=False, batch_size=32)
    return embeddings.tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
