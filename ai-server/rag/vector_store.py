"""
Vector Store Backends
=====================
Persistent and in-memory vector databases with automatic fallback:

- ChromaDBStore: Persistent local vector DB (best for production)
- FAISSStore: Fast in-memory similarity search (best for speed)
- SimpleInMemoryStore: Numpy cosine similarity (zero deps fallback)

All stores implement the VectorStore ABC with add/search/delete/update/get_all.
Auto-save ensures data persistence across restarts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .embeddings import EmbeddingProvider, get_default_provider, get_embedding_provider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """A single search result with metadata."""

    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "score": self.score,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class VectorStore(ABC):
    """Abstract vector store interface."""

    name: str = "base"

    def __init__(self, embedding_provider: Optional[EmbeddingProvider] = None) -> None:
        self._embedder = embedding_provider or get_default_provider()

    @abstractmethod
    def add(self, text: str, metadata: Optional[dict[str, Any]] = None, id: str | None = None) -> str:
        """Add a document. Returns the assigned id."""
        ...

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Search for similar documents. Returns list of SearchResult."""
        ...

    @abstractmethod
    def search_by_vector(self, vector: list[float], top_k: int = 5) -> list[SearchResult]:
        """Search by embedding vector directly."""
        ...

    @abstractmethod
    def delete(self, id: str) -> bool:
        """Delete a document by id. Returns True if deleted."""
        ...

    @abstractmethod
    def update(self, id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> bool:
        """Update a document. Returns True if updated."""
        ...

    @abstractmethod
    def get_all(self) -> list[SearchResult]:
        """Return all documents."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return number of documents."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove all documents."""
        ...

    def persist(self) -> None:
        """Persist to disk (no-op for in-memory stores)."""
        pass


# ---------------------------------------------------------------------------
# ChromaDB Store
# ---------------------------------------------------------------------------


class ChromaDBStore(VectorStore):
    """Persistent vector store using ChromaDB.

    Features:
    - Automatic persistence to disk
    - Metadata filtering support
    - Handles deduplication by id
    """

    name: str = "chromadb"

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        collection_name: str = "hermes_rag",
        persist_directory: str | Path | None = None,
    ) -> None:
        super().__init__(embedding_provider)
        self._collection_name = collection_name
        self._persist_dir = str(
            persist_directory
            or os.environ.get("HERMES_RAG_DIR", Path.home() / ".hermes" / "rag_data")
        )
        self._client: Any = None
        self._collection: Any = None
        self._init_chromadb()

    def _init_chromadb(self) -> None:
        """Initialize ChromaDB client and collection."""
        try:
            import chromadb  # type: ignore[import-untyped]
            from chromadb.config import Settings  # type: ignore[import-untyped]

            os.makedirs(self._persist_dir, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self._persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB initialized: collection=%s, dir=%s, docs=%d",
                self._collection_name,
                self._persist_dir,
                self._collection.count(),
            )
        except ImportError:
            logger.warning(
                "ChromaDB not installed. Install with: pip install chromadb. "
                "Falling back to SimpleInMemoryStore."
            )
            raise
        except Exception as exc:
            logger.error("ChromaDB init failed: %s", exc)
            raise

    def _generate_id(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def add(self, text: str, metadata: Optional[dict[str, Any]] = None, id: str | None = None) -> str:
        doc_id = id or self._generate_id(text)
        meta = metadata or {}

        # Convert list/dict metadata values to strings (ChromaDB limitation)
        safe_meta = {}
        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool)):
                safe_meta[k] = v
            else:
                safe_meta[k] = json.dumps(v, ensure_ascii=False)

        embedding = self._embedder.embed_cached(text)

        # Upsert to handle duplicates
        self._collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[safe_meta],
        )
        return doc_id

    def add_batch(
        self,
        texts: list[str],
        metadatas: Optional[list[dict[str, Any]]] = None,
        ids: list[str] | None = None,
    ) -> list[str]:
        """Add multiple documents at once (more efficient)."""
        if not texts:
            return []

        doc_ids = ids or [self._generate_id(t) for t in texts]
        embeddings = self._embedder.embed_batch_cached(texts)

        safe_metas: list[dict[str, str | int | float | bool]] = []
        for meta in (metadatas or [{}] * len(texts)):
            safe = {}
            for k, v in meta.items():
                if isinstance(v, (str, int, float, bool)):
                    safe[k] = v
                else:
                    safe[k] = json.dumps(v, ensure_ascii=False)
            safe_metas.append(safe)

        self._collection.upsert(
            ids=doc_ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=safe_metas,
        )
        return doc_ids

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        embedding = self._embedder.embed_cached(query)
        return self.search_by_vector(embedding, top_k)

    def search_by_vector(self, vector: list[float], top_k: int = 5) -> list[SearchResult]:
        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_embeddings=[vector],
            n_results=min(top_k, self._collection.count()),
        )

        search_results: list[SearchResult] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity score: 1 - (distance / 2)
            dist = distances[i] if i < len(distances) else 1.0
            score = max(0.0, 1.0 - dist / 2.0)

            meta = metadatas[i] if i < len(metadatas) else {}
            # Deserialize JSON metadata values
            for k, v in meta.items():
                if isinstance(v, str) and v.startswith("{"):
                    try:
                        meta[k] = json.loads(v)
                    except (json.JSONDecodeError, TypeError):
                        pass

            search_results.append(SearchResult(
                id=doc_id,
                text=documents[i] if i < len(documents) else "",
                score=score,
                metadata=meta,
            ))

        return search_results

    def delete(self, id: str) -> bool:
        try:
            self._collection.delete(ids=[id])
            return True
        except Exception as exc:
            logger.warning("Failed to delete %s: %s", id, exc)
            return False

    def update(self, id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> bool:
        try:
            self.add(text, metadata=metadata, id=id)
            return True
        except Exception as exc:
            logger.warning("Failed to update %s: %s", id, exc)
            return False

    def get_all(self) -> list[SearchResult]:
        count = self._collection.count()
        if count == 0:
            return []

        results = self._collection.get(
            include=["documents", "metadatas"],
            limit=count,
        )

        output: list[SearchResult] = []
        for i, doc_id in enumerate(results.get("ids", [])):
            docs = results.get("documents", [])
            metas = results.get("metadatas", [])
            output.append(SearchResult(
                id=doc_id,
                text=docs[i] if i < len(docs) else "",
                score=0.0,
                metadata=metas[i] if i < len(metas) else {},
            ))
        return output

    def count(self) -> int:
        return self._collection.count()

    def clear(self) -> None:
        # Delete and recreate collection
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def persist(self) -> None:
        # ChromaDB auto-persists with PersistentClient
        pass


# ---------------------------------------------------------------------------
# FAISS Store
# ---------------------------------------------------------------------------


class FAISSStore(VectorStore):
    """Fast in-memory vector store using FAISS.

    Excellent for large datasets and fast approximate nearest-neighbor search.
    Does not persist automatically (call persist() to save).
    """

    name: str = "faiss"

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        persist_path: str | Path | None = None,
    ) -> None:
        super().__init__(embedding_provider)
        self._persist_path = str(
            persist_path
            or os.environ.get("HERMES_RAG_DIR", Path.home() / ".hermes" / "rag_data")
            / "faiss_index"
        )
        self._index: Any = None
        self._dimension: int = 0
        self._id_map: list[str] = []  # FAISS index -> doc id
        self._documents: dict[str, dict[str, Any]] = {}  # id -> {text, metadata, vector}
        self._init_faiss()

    def _init_faiss(self) -> None:
        try:
            import faiss  # type: ignore[import-untyped]

            # Try to load existing index
            if os.path.exists(self._persist_path):
                self._index = faiss.read_index(self._persist_path)
                self._dimension = self._index.d
                # Load metadata
                meta_path = self._persist_path + ".meta.json"
                if os.path.exists(meta_path):
                    with open(meta_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._id_map = data.get("id_map", [])
                    self._documents = data.get("documents", {})
                logger.info("FAISS index loaded: %d docs", len(self._id_map))
            else:
                # Will be initialized on first add
                self._index = None
                logger.info("FAISS store initialized (empty)")
        except ImportError:
            logger.warning(
                "FAISS not installed. Install with: pip install faiss-cpu"
            )
            raise
        except Exception as exc:
            logger.error("FAISS init failed: %s", exc)
            raise

    def _ensure_index(self, dim: int) -> None:
        """Create FAISS index if needed."""
        import faiss  # type: ignore[import-untyped]

        if self._index is None or self._dimension != dim:
            self._dimension = dim
            # Use IndexFlatIP for cosine similarity (after normalization)
            self._index = faiss.IndexFlatIP(dim)
            logger.info("Created FAISS index (dim=%d)", dim)

    def _generate_id(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def add(self, text: str, metadata: Optional[dict[str, Any]] = None, id: str | None = None) -> str:
        import faiss  # type: ignore[import-untyped]

        doc_id = id or self._generate_id(text)
        embedding = self._embedder.embed_cached(text)
        dim = len(embedding)

        self._ensure_index(dim)

        # Normalize for cosine similarity
        vec = self._l2_normalize([embedding])

        # If id already exists, update
        if doc_id in self._id_map:
            idx = self._id_map.index(doc_id)
            # FAISS IndexFlatIP doesn't support direct update; we rebuild
            # For simplicity, we remove and re-add (works for small-medium collections)
            self._remove_and_rebuild(idx, vec[0], doc_id, text, metadata or {})
        else:
            self._index.add(vec)  # type: ignore[union-attr]
            self._id_map.append(doc_id)
            self._documents[doc_id] = {
                "text": text,
                "metadata": metadata or {},
                "vector": embedding,
            }

        return doc_id

    def _remove_and_rebuild(
        self,
        idx: int,
        new_vec: Any,
        doc_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> None:
        """Rebuild index without the specified index (for updates/deletes)."""
        import faiss  # type: ignore[import-untyped]

        # Collect all vectors except the one to remove/update
        ids_to_keep = []
        vecs_to_keep = []
        for i, uid in enumerate(self._id_map):
            if i != idx:
                ids_to_keep.append(uid)
                vecs = self._documents[uid].get("vector", [])
                if vecs:
                    ids_to_keep[-1] = uid  # keep it
                    vecs_to_keep.append(vecs)

        # Add the new vector
        ids_to_keep.append(doc_id)
        vecs_to_keep.append(new_vec.tolist() if hasattr(new_vec, 'tolist') else list(new_vec))

        # Rebuild
        self._index = faiss.IndexFlatIP(self._dimension)
        if vecs_to_keep:
            import numpy as np
            mat = np.array(vecs_to_keep, dtype=np.float32)
            mat = self._l2_normalize(mat)
            self._index.add(mat)

        self._id_map = ids_to_keep
        self._documents[doc_id] = {
            "text": text,
            "metadata": metadata,
            "vector": new_vec.tolist() if hasattr(new_vec, 'tolist') else list(new_vec),
        }

    def _l2_normalize(self, vecs: Any) -> Any:
        """L2-normalize vectors for cosine similarity via inner product."""
        import numpy as np

        arr = np.array(vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        return arr / norms

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        embedding = self._embedder.embed_cached(query)
        return self.search_by_vector(embedding, top_k)

    def search_by_vector(self, vector: list[float], top_k: int = 5) -> list[SearchResult]:
        if self._index is None or self._index.ntotal == 0:
            return []

        import numpy as np

        query_vec = np.array([vector], dtype=np.float32)
        query_vec = self._l2_normalize(query_vec)

        k = min(top_k, self._index.ntotal)
        scores, indices = self._index.search(query_vec, k)  # type: ignore[union-attr]

        results: list[SearchResult] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._id_map):
                continue
            doc_id = self._id_map[idx]
            doc = self._documents.get(doc_id, {})
            results.append(SearchResult(
                id=doc_id,
                text=doc.get("text", ""),
                score=float(score),
                metadata=doc.get("metadata", {}),
            ))

        return results

    def delete(self, id: str) -> bool:
        if id not in self._id_map:
            return False
        idx = self._id_map.index(id)
        del self._documents[id]
        # Rebuild without this index
        self._remove_and_rebuild(idx, [0.0] * self._dimension, "", "", {})
        # Remove from _id_map (the rebuild inserted a dummy)
        if "" in self._id_map:
            self._id_map.remove("")
        return True

    def update(self, id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> bool:
        if id not in self._id_map:
            return False
        self.add(text, metadata=metadata, id=id)
        return True

    def get_all(self) -> list[SearchResult]:
        return [
            SearchResult(
                id=doc_id,
                text=doc.get("text", ""),
                score=0.0,
                metadata=doc.get("metadata", {}),
            )
            for doc_id, doc in self._documents.items()
        ]

    def count(self) -> int:
        return len(self._id_map)

    def clear(self) -> None:
        import faiss  # type: ignore[import-untyped]
        self._index = faiss.IndexFlatIP(self._dimension) if self._dimension else None
        self._id_map.clear()
        self._documents.clear()

    def persist(self) -> None:
        """Save index and metadata to disk."""
        if self._index is None:
            return
        import faiss  # type: ignore[import-untyped]

        os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
        faiss.write_index(self._index, self._persist_path)

        meta_path = self._persist_path + ".meta.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "id_map": self._id_map,
                "documents": self._documents,
            }, f, ensure_ascii=False, indent=2)
        logger.info("FAISS index persisted to %s (%d docs)", self._persist_path, len(self._id_map))


# ---------------------------------------------------------------------------
# Simple In-Memory Store (numpy cosine similarity)
# ---------------------------------------------------------------------------


class SimpleInMemoryStore(VectorStore):
    """Zero-dependency vector store using numpy for cosine similarity.

    Fallback when ChromaDB and FAISS are not available.
    Suitable for small to medium datasets (< 10K documents).
    Supports optional persistence to JSON.
    """

    name: str = "simple_in_memory"

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        persist_path: str | Path | None = None,
    ) -> None:
        super().__init__(embedding_provider)
        self._persist_path = str(
            persist_path
            or os.environ.get("HERMES_RAG_DIR", Path.home() / ".hermes" / "rag_data")
            / "simple_store.json"
        )
        self._documents: dict[str, dict[str, Any]] = {}  # id -> {text, metadata, vector}
        self._load()

    def _generate_id(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def add(self, text: str, metadata: Optional[dict[str, Any]] = None, id: str | None = None) -> str:
        doc_id = id or self._generate_id(text)
        embedding = self._embedder.embed_cached(text)

        self._documents[doc_id] = {
            "text": text,
            "metadata": metadata or {},
            "vector": embedding,
        }
        self._auto_save()
        return doc_id

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        embedding = self._embedder.embed_cached(query)
        return self.search_by_vector(embedding, top_k)

    def search_by_vector(self, vector: list[float], top_k: int = 5) -> list[SearchResult]:
        if not self._documents:
            return []

        try:
            import numpy as np

            query = np.array(vector, dtype=np.float32)
            query_norm = np.linalg.norm(query)
            if query_norm > 0:
                query = query / query_norm

            doc_ids = list(self._documents.keys())
            doc_vecs = np.array(
                [self._documents[did]["vector"] for did in doc_ids],
                dtype=np.float32,
            )

            # Normalize document vectors
            norms = np.linalg.norm(doc_vecs, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-10)
            doc_vecs = doc_vecs / norms

            # Cosine similarity
            scores = doc_vecs @ query

            # Top-k
            k = min(top_k, len(doc_ids))
            top_indices = np.argsort(scores)[::-1][:k]

            results: list[SearchResult] = []
            for idx in top_indices:
                did = doc_ids[idx]
                doc = self._documents[did]
                results.append(SearchResult(
                    id=did,
                    text=doc["text"],
                    score=float(scores[idx]),
                    metadata=doc.get("metadata", {}),
                ))
            return results

        except ImportError:
            # Pure Python fallback
            return self._search_pure_python(vector, top_k)

    def _search_pure_python(self, vector: list[float], top_k: int = 5) -> list[SearchResult]:
        """Cosine similarity without numpy."""
        import math

        def dot(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b))

        def norm(a: list[float]) -> float:
            return math.sqrt(sum(x * x for x in a))

        q_norm = norm(vector)
        if q_norm == 0:
            return []

        scored: list[tuple[str, float]] = []
        for doc_id, doc in self._documents.items():
            d_vec = doc["vector"]
            d_norm = norm(d_vec)
            if d_norm == 0:
                continue
            score = dot(vector, d_vec) / (q_norm * d_norm)
            scored.append((doc_id, score))

        scored.sort(key=lambda x: x[1], reverse=True)

        results: list[SearchResult] = []
        for doc_id, score in scored[:top_k]:
            doc = self._documents[doc_id]
            results.append(SearchResult(
                id=doc_id,
                text=doc["text"],
                score=score,
                metadata=doc.get("metadata", {}),
            ))
        return results

    def delete(self, id: str) -> bool:
        if id in self._documents:
            del self._documents[id]
            self._auto_save()
            return True
        return False

    def update(self, id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> bool:
        if id not in self._documents:
            return False
        self.add(text, metadata=metadata, id=id)
        return True

    def get_all(self) -> list[SearchResult]:
        return [
            SearchResult(
                id=did,
                text=doc["text"],
                score=0.0,
                metadata=doc.get("metadata", {}),
            )
            for did, doc in self._documents.items()
        ]

    def count(self) -> int:
        return len(self._documents)

    def clear(self) -> None:
        self._documents.clear()
        self._auto_save()

    def persist(self) -> None:
        self._save()

    def _save(self) -> None:
        """Save to JSON file."""
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            data = {
                did: {
                    "text": doc["text"],
                    "metadata": doc.get("metadata", {}),
                    # Store vector for persistence
                    "vector": doc.get("vector", []),
                }
                for did, doc in self._documents.items()
            }
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as exc:
            logger.warning("Failed to persist store: %s", exc)

    def _load(self) -> None:
        """Load from JSON file if it exists."""
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for did, doc in data.items():
                self._documents[did] = {
                    "text": doc["text"],
                    "metadata": doc.get("metadata", {}),
                    "vector": doc.get("vector", []),
                }
            logger.info("Loaded %d documents from %s", len(self._documents), self._persist_path)
        except Exception as exc:
            logger.warning("Failed to load store from %s: %s", self._persist_path, exc)

    def _auto_save(self, threshold: int = 50) -> None:
        """Auto-save every N additions."""
        if len(self._documents) % threshold == 0 and len(self._documents) > 0:
            self._save()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_vector_store(
    store_type: str = "auto",
    embedding_provider: Optional[EmbeddingProvider] = None,
    **kwargs: Any,
) -> VectorStore:
    """Get a vector store by type or auto-select the best available.

    Selection order (auto mode):
        1. ChromaDB (if installed)
        2. FAISS (if installed)
        3. SimpleInMemory (always available)

    Args:
        store_type: 'auto', 'chromadb', 'faiss', or 'simple'.
        embedding_provider: Optional embedding provider override.
        **kwargs: Extra args for the store constructor.

    Returns:
        A VectorStore instance.
    """
    if store_type == "auto":
        # Try ChromaDB
        try:
            store = ChromaDBStore(
                embedding_provider=embedding_provider,
                collection_name=kwargs.get("collection_name", "hermes_rag"),
                persist_directory=kwargs.get("persist_directory"),
            )
            logger.info("Auto-selected ChromaDB vector store")
            return store
        except Exception:
            pass

        # Try FAISS
        try:
            store = FAISSStore(
                embedding_provider=embedding_provider,
                persist_path=kwargs.get("persist_path"),
            )
            logger.info("Auto-selected FAISS vector store")
            return store
        except Exception:
            pass

        # Fallback
        logger.info("Using SimpleInMemoryStore (fallback)")
        return SimpleInMemoryStore(
            embedding_provider=embedding_provider,
            persist_path=kwargs.get("persist_path"),
        )

    store_lower = store_type.lower().strip()

    if store_lower in ("chromadb", "chroma"):
        return ChromaDBStore(
            embedding_provider=embedding_provider,
            collection_name=kwargs.get("collection_name", "hermes_rag"),
            persist_directory=kwargs.get("persist_directory"),
        )

    if store_lower in ("faiss",):
        return FAISSStore(
            embedding_provider=embedding_provider,
            persist_path=kwargs.get("persist_path"),
        )

    if store_lower in ("simple", "memory", "in_memory", "simple_in_memory"):
        return SimpleInMemoryStore(
            embedding_provider=embedding_provider,
            persist_path=kwargs.get("persist_path"),
        )

    raise ValueError(f"Unknown vector store type: {store_type!r}")
