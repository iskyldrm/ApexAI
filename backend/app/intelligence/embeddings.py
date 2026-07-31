"""Vector embeddings + semantic_search (G.1-G.5).

Embeds text into vectors and stores them for cosine-similarity search.
Two backends:
- In-memory (default for tests + dev)
- pgvector (production) — when pgvector extension is installed

If ``sentence-transformers`` isn't installed, falls back to a deterministic
hash-based embedding (same approach as ``cost.semantic``).

The agent runtime uses this via the ``semantic_search`` tool:
    semantic_search("find the auth middleware") → top-5 matching code chunks
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any


logger = logging.getLogger(__name__)


EMBEDDING_DIM = 384  # sentence-transformers all-MiniLM-L6-v2 dimension


# ---------------------------------------------------------------------------
# Embedding providers
# ---------------------------------------------------------------------------


class EmbeddingProvider:
    """Base interface — embed(text) → list[float]."""

    def embed(self, text: str) -> list[float]:  # pragma: no cover - abstract
        raise NotImplementedError

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    @property
    def dim(self) -> int:
        return EMBEDDING_DIM


class HashEmbeddingProvider(EmbeddingProvider):
    """Deterministic fallback — same text → same vector. Not semantically
    meaningful, but stable enough for tests + offline use.
    """

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        for token in text.lower().split():
            h = hashlib.sha256(token.encode()).digest()
            for i in range(EMBEDDING_DIM):
                vec[i] += (h[i % len(h)] / 255.0) - 0.5
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class SentenceTransformerProvider(EmbeddingProvider):
    """Real semantic embeddings using sentence-transformers.

    Lazy-loads the model on first embed() call. Downloads ~80MB the first
    time; subsequent calls are millisecond-fast.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model = None
        self._model_name = model_name

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        try:
            model = self._load()
            vec = model.encode(text, normalize_embeddings=True)
            return [float(x) for x in vec]
        except Exception as e:
            logger.warning("SentenceTransformerProvider failed: %s", e)
            return HashEmbeddingProvider().embed(text)


def get_default_provider() -> EmbeddingProvider:
    """Return the configured provider.

    Set ``APEXAI_EMBEDDING_PROVIDER=sentence_transformers`` to force the
    real model; otherwise the hash provider is used (no download needed).
    """
    choice = os.environ.get("APEXAI_EMBEDDING_PROVIDER", "hash").lower()
    if choice == "sentence_transformers":
        try:
            return SentenceTransformerProvider()
        except Exception:
            logger.warning("Falling back to HashEmbeddingProvider")
    return HashEmbeddingProvider()


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------


@dataclass
class StoredVector:
    """One row in the in-memory store."""

    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


class InMemoryVectorStore:
    """Simple cosine-similarity search."""

    def __init__(self) -> None:
        self._items: list[StoredVector] = []

    def add(
        self,
        id: str,
        text: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        # Replace if id exists, else append
        for i, item in enumerate(self._items):
            if item.id == id:
                self._items[i] = StoredVector(
                    id=id, text=text, vector=vector, metadata=metadata or {}
                )
                return
        self._items.append(StoredVector(id=id, text=text, vector=vector, metadata=metadata or {}))


    def search(
        self,
        query_vector: list[float],
        *,
        limit: int = 5,
        threshold: float = -1.0,
    ) -> list[StoredVector]:
        """Return up to ``limit`` items above ``threshold`` cosine similarity.

        Default threshold is -1.0 (the minimum possible value) so callers
        who don't filter get the full ranking.
        """
        scored = []
        for item in self._items:
            sim = _cosine(query_vector, item.vector)
            if sim >= threshold:
                scored.append((sim, item))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def __len__(self) -> int:
        return len(self._items)


# Singleton — production would back this with pgvector
_store: InMemoryVectorStore | None = None


def get_vector_store() -> InMemoryVectorStore:
    global _store
    if _store is None:
        _store = InMemoryVectorStore()
    return _store


def reset_for_tests() -> None:
    global _store
    _store = None


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


# ---------------------------------------------------------------------------
# High-level helper: index + search
# ---------------------------------------------------------------------------


def index_text(
    *,
    id: str,
    text: str,
    metadata: dict[str, Any] | None = None,
    provider: EmbeddingProvider | None = None,
) -> list[float]:
    """Embed + store a single text. Returns the vector."""
    p = provider or get_default_provider()
    vec = p.embed(text)
    get_vector_store().add(id=id, text=text, vector=vec, metadata=metadata or {})
    return vec


def semantic_search(
    query: str,
    *,
    limit: int = 5,
    threshold: float = -1.0,
    provider: EmbeddingProvider | None = None,
) -> list[dict[str, Any]]:
    """Embed the query, search the store, return top-k matches.

    Returns: list of {"id": str, "text": str, "score": float, "metadata": dict}
    """
    p = provider or get_default_provider()
    q_vec = p.embed(query)
    matches = get_vector_store().search(q_vec, limit=limit, threshold=threshold)
    return [
        {
            "id": m.id,
            "text": m.text,
            "score": _cosine(q_vec, m.vector),
            "metadata": m.metadata,
        }
        for m in matches
    ]