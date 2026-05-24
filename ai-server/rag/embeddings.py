"""
Embedding Providers
====================
Multiple embedding backends with automatic fallback:
- SimpleHashEmbedding: Fast hash-based (no deps, for testing)
- SentenceTransformerEmbedding: High-quality (optional sentence-transformers)
- OpenAIEmbedding: OpenAI-compatible API (MiMo, OpenAI, etc.)

All providers implement the EmbeddingProvider ABC and return list[float] vectors.
An LRU cache prevents re-embedding identical texts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class _EmbeddingCache:
    """Simple LRU cache for embeddings keyed by (provider_name, text)."""

    def __init__(self, max_size: int = 2048) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    def _key(self, provider: str, text: str) -> str:
        h = hashlib.sha256(f"{provider}::{text}".encode()).hexdigest()[:32]
        return h

    def get(self, provider: str, text: str) -> Optional[list[float]]:
        k = self._key(provider, text)
        if k in self._cache:
            self._hits += 1
            self._cache.move_to_end(k)
            return self._cache[k]
        self._misses += 1
        return None

    def put(self, provider: str, text: str, embedding: list[float]) -> None:
        k = self._key(provider, text)
        if k in self._cache:
            self._cache.move_to_end(k)
        self._cache[k] = embedding
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses, "size": len(self._cache)}

    def clear(self) -> None:
        self._cache.clear()


# Module-level singleton cache
_embedding_cache = _EmbeddingCache()


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Abstract embedding provider interface."""

    name: str = "base"

    def __init__(self) -> None:
        self._cache = _embedding_cache

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for *text*."""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for a list of texts."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""
        ...

    def embed_cached(self, text: str) -> list[float]:
        """Embed with caching."""
        cached = self._cache.get(self.name, text)
        if cached is not None:
            return cached
        vec = self.embed(text)
        self._cache.put(self.name, text, vec)
        return vec

    def embed_batch_cached(self, texts: list[str]) -> list[list[float]]:
        """Embed batch with caching."""
        results: list[list[float] | None] = [None] * len(texts)
        to_embed: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            cached = self._cache.get(self.name, text)
            if cached is not None:
                results[i] = cached
            else:
                to_embed.append((i, text))

        if to_embed:
            new_vecs = self.embed_batch([t for _, t in to_embed])
            for (idx, text), vec in zip(to_embed, new_vecs):
                results[idx] = vec
                self._cache.put(self.name, text, vec)

        return [r for r in results if r is not None]  # type: ignore[list-item]


# ---------------------------------------------------------------------------
# Simple hash-based embeddings (no external deps)
# ---------------------------------------------------------------------------


class SimpleHashEmbedding(EmbeddingProvider):
    """Fast hash-based embeddings for testing.

    Generates deterministic vectors using SHA-512 hash + bag-of-words.
    Not semantically meaningful but useful for:
    - Testing the pipeline end-to-end
    - Quick smoke tests without GPU/model downloads
    - Environments with strict dependency constraints

    Vectors are 64-dimensional and normalized.
    """

    name: str = "simple_hash"
    _DIM = 64  # SHA-512 produces 64 bytes = 64 floats

    def embed(self, text: str) -> list[float]:
        """Generate a hash-based embedding from text."""
        text_lower = text.lower().strip()

        # Use SHA-512 to get 512 float values
        h = hashlib.sha512(text_lower.encode("utf-8")).digest()
        # Each byte -> float in [-1, 1]
        vec = [(b - 128) / 128.0 for b in h]

        # Add bag-of-words signal: hash each word and mix into vector
        words = text_lower.split()
        for word in words:
            wh = hashlib.md5(word.encode()).digest()
            for i in range(min(len(wh), len(vec))):
                vec[i] += (wh[i] - 128) / 512.0

        # Normalize to unit vector
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]

        return vec

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def dimension(self) -> int:
        return self._DIM


# ---------------------------------------------------------------------------
# Sentence Transformers (optional)
# ---------------------------------------------------------------------------


class SentenceTransformerEmbedding(EmbeddingProvider):
    """High-quality embeddings using sentence-transformers library.

    Falls back gracefully if the library is not installed.
    Uses the 'all-MiniLM-L6-v2' model by default (fast, 384-dim).
    """

    name: str = "sentence_transformer"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str = "cpu") -> None:
        super().__init__()
        self._model_name = model_name
        self._device = device
        self._model: Any = None
        self._dim: int = 0

    def _load_model(self) -> Any:
        """Lazy-load the sentence-transformers model."""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading SentenceTransformer model: %s", self._model_name)
            self._model = SentenceTransformer(self._model_name, device=self._device)
            # Determine dimension from a test encode
            test_vec = self._model.encode(["test"], show_progress_bar=False)
            self._dim = len(test_vec[0]) if len(test_vec) > 0 else 384
            logger.info("SentenceTransformer ready (dim=%d)", self._dim)
            return self._model
        except ImportError:
            logger.warning(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )
            raise
        except Exception as exc:
            logger.error("Failed to load SentenceTransformer: %s", exc)
            raise

    def embed(self, text: str) -> list[float]:
        model = self._load_model()
        vec = model.encode([text], show_progress_bar=False)[0]
        return vec.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        vecs = model.encode(texts, show_progress_bar=False)
        return [v.tolist() for v in vecs]

    def dimension(self) -> int:
        if self._dim == 0:
            self._load_model()
        return self._dim


# ---------------------------------------------------------------------------
# OpenAI-compatible embeddings (MiMo, OpenAI, etc.)
# ---------------------------------------------------------------------------


class OpenAIEmbedding(EmbeddingProvider):
    """Embeddings via OpenAI-compatible API (works with MiMo, OpenAI, etc.).

    Uses the /v1/embeddings endpoint. Requires an API base URL and optionally
    an API key (can be set via OPENAI_API_KEY env var).
    """

    name: str = "openai_compatible"

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        timeout: float = 30.0,
    ) -> None:
        super().__init__()
        self._api_base = (
            api_base
            or os.environ.get("OPENAI_API_BASE", os.environ.get("OPENAI_BASE_URL", ""))
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._dim = dimensions
        self._timeout = timeout

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call the OpenAI-compatible embeddings endpoint."""
        import requests  # type: ignore[import-untyped]

        url = f"{self._api_base}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "input": texts,
            "model": self._model,
        }
        if self._dim:
            payload["dimensions"] = self._dim

        resp = requests.post(url, json=payload, headers=headers, timeout=self._timeout)
        resp.raise_for_status()
        data = resp.json()

        # Sort by index to maintain order
        embeddings = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        return [e["embedding"] for e in embeddings]

    def embed(self, text: str) -> list[float]:
        results = self._call_api([text])
        return results[0] if results else [0.0] * self._dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # Process in chunks of 2048 to avoid API limits
        chunk_size = 2048
        all_vecs: list[list[float]] = []
        for i in range(0, len(texts), chunk_size):
            chunk = texts[i : i + chunk_size]
            all_vecs.extend(self._call_api(chunk))
        return all_vecs

    def dimension(self) -> int:
        return self._dim


# ---------------------------------------------------------------------------
# Factory: auto-select best available provider
# ---------------------------------------------------------------------------


def get_embedding_provider(
    provider: str = "auto",
    **kwargs: Any,
) -> EmbeddingProvider:
    """Get an embedding provider by name or auto-select the best available.

    Provider selection order (auto mode):
        1. OpenAI-compatible (if OPENAI_API_KEY is set)
        2. SentenceTransformer (if installed)
        3. SimpleHash (always available, no deps)

    Args:
        provider: Provider name ('auto', 'hash', 'sentence_transformer',
                  'openai', or 'simple_hash').
        **kwargs: Extra arguments forwarded to the provider constructor.

    Returns:
        An EmbeddingProvider instance.
    """
    if provider == "auto":
        # Try OpenAI-compatible first
        api_key = kwargs.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
        api_base = kwargs.get("api_base") or os.environ.get(
            "OPENAI_API_BASE", os.environ.get("OPENAI_BASE_URL", "")
        )
        if api_key or api_base:
            try:
                p = OpenAIEmbedding(
                    api_base=api_base or None,
                    api_key=api_key or None,
                    model=kwargs.get("model", "text-embedding-3-small"),
                    dimensions=kwargs.get("dimensions", 1536),
                )
                logger.info("Auto-selected OpenAI-compatible embedding provider")
                return p
            except Exception as exc:
                logger.warning("Failed to init OpenAI embeddings: %s", exc)

        # Try sentence-transformers
        try:
            p = SentenceTransformerEmbedding(
                model_name=kwargs.get("model_name", "all-MiniLM-L6-v2"),
                device=kwargs.get("device", "cpu"),
            )
            # Force load to verify it works
            p.dimension()
            logger.info("Auto-selected SentenceTransformer embedding provider")
            return p
        except Exception:
            logger.info("SentenceTransformer not available")

        # Fallback to hash
        logger.info("Using SimpleHashEmbedding (fallback)")
        return SimpleHashEmbedding()

    provider_lower = provider.lower().strip()

    if provider_lower in ("hash", "simple_hash", "simple"):
        return SimpleHashEmbedding()

    if provider_lower in ("sentence_transformer", "sentence", "st", "minilm"):
        return SentenceTransformerEmbedding(
            model_name=kwargs.get("model_name", "all-MiniLM-L6-v2"),
            device=kwargs.get("device", "cpu"),
        )

    if provider_lower in ("openai", "openai_compatible", "api", "mimo"):
        return OpenAIEmbedding(
            api_base=kwargs.get("api_base"),
            api_key=kwargs.get("api_key"),
            model=kwargs.get("model", "text-embedding-3-small"),
            dimensions=kwargs.get("dimensions", 1536),
            timeout=kwargs.get("timeout", 30.0),
        )

    raise ValueError(f"Unknown embedding provider: {provider!r}")


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_provider: Optional[EmbeddingProvider] = None


def get_default_provider() -> EmbeddingProvider:
    """Get or create the default embedding provider singleton."""
    global _default_provider
    if _default_provider is None:
        _default_provider = get_embedding_provider("auto")
    return _default_provider


def embed_text(text: str) -> list[float]:
    """Convenience: embed a single text using the default provider."""
    return get_default_provider().embed_cached(text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Convenience: embed multiple texts using the default provider."""
    return get_default_provider().embed_batch_cached(texts)
