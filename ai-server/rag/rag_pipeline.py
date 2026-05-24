"""
RAG Pipeline
=============
End-to-end Retrieval Augmented Generation pipeline.

Flow:
    index_document(text, metadata) → store in vector DB
    query_with_rag(query) → retrieve → augment → return enhanced prompt

Integrates embeddings, vector store, and reranker into a cohesive pipeline.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

from .embeddings import EmbeddingProvider, get_default_provider, get_embedding_provider
from .reranker import Reranker, RerankStrategy
from .vector_store import SearchResult, VectorStore, get_vector_store

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Complete RAG pipeline for the Hermes multi-agent system.

    Combines embedding, storage, retrieval, reranking, and prompt augmentation.

    Usage::

        pipeline = RAGPipeline()

        # Index documents
        pipeline.index_document("Python is a programming language", {"topic": "python"})
        pipeline.batch_index([
            {"text": "Machine learning overview", "metadata": {"topic": "ml"}},
            {"text": "Web scraping techniques", "metadata": {"topic": "web"}},
        ])

        # Query
        result = pipeline.query_with_rag("Tell me about Python")
        print(result["augmented_prompt"])

        # Or just retrieve context
        contexts = pipeline.retrieve("Tell me about Python", top_k=3)
    """

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        vector_store: Optional[VectorStore] = None,
        reranker: Optional[Reranker] = None,
        store_type: str = "auto",
        embedding_type: str = "auto",
        store_kwargs: Optional[dict[str, Any]] = None,
        embedding_kwargs: Optional[dict[str, Any]] = None,
        rerank_strategy: str = "combined",
        max_context_length: int = 8000,
    ) -> None:
        """Initialize the RAG pipeline.

        Args:
            embedding_provider: Embedding provider (auto-selected if None).
            vector_store: Vector store backend (auto-selected if None).
            reranker: Result reranker.
            store_type: Vector store type ('auto', 'chromadb', 'faiss', 'simple').
            embedding_type: Embedding type ('auto', 'hash', 'sentence_transformer', 'openai').
            store_kwargs: Extra kwargs for vector store constructor.
            embedding_kwargs: Extra kwargs for embedding provider constructor.
            rerank_strategy: Reranking strategy ('combined', 'score', 'keyword', 'diversity').
            max_context_length: Max chars for augmented context.
        """
        store_kwargs = store_kwargs or {}
        embedding_kwargs = embedding_kwargs or {}

        # Initialize embedding provider
        if embedding_provider:
            self._embedder = embedding_provider
        else:
            self._embedder = get_embedding_provider(embedding_type, **embedding_kwargs)

        # Initialize vector store
        if vector_store:
            self._store = vector_store
        else:
            self._store = get_vector_store(
                store_type,
                embedding_provider=self._embedder,
                **store_kwargs,
            )

        # Initialize reranker
        self._reranker = reranker or Reranker(strategy=rerank_strategy)

        # Config
        self._max_context_length = max_context_length

        # Stats
        self._index_count = 0
        self._query_count = 0
        self._total_index_time = 0.0
        self._total_query_time = 0.0

        logger.info(
            "RAGPipeline initialized: embedder=%s, store=%s, reranker=%s",
            self._embedder.name,
            self._store.name,
            self._reranker.strategy,
        )

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_document(self, text: str, metadata: Optional[dict[str, Any]] = None) -> str:
        """Index a single document.

        Args:
            text: Document text to index.
            metadata: Optional metadata (topic, source, timestamp, etc.).

        Returns:
            The assigned document ID.
        """
        start = time.monotonic()
        try:
            doc_id = self._store.add(text, metadata=metadata)
            self._index_count += 1
            elapsed = time.monotonic() - start
            self._total_index_time += elapsed
            logger.debug("Indexed document %s (%.3fs)", doc_id, elapsed)
            return doc_id
        except Exception as exc:
            logger.error("Failed to index document: %s", exc)
            raise

    def batch_index(self, documents: list[dict[str, Any]]) -> list[str]:
        """Index multiple documents at once.

        Args:
            documents: List of dicts with 'text' (required) and 'metadata' (optional).

        Returns:
            List of assigned document IDs.
        """
        start = time.monotonic()
        ids: list[str] = []
        for doc in documents:
            try:
                doc_id = self._store.add(
                    text=doc["text"],
                    metadata=doc.get("metadata"),
                    id=doc.get("id"),
                )
                ids.append(doc_id)
                self._index_count += 1
            except Exception as exc:
                logger.warning("Failed to index document: %s", exc)

        elapsed = time.monotonic() - start
        self._total_index_time += elapsed
        logger.info("Batch indexed %d/%d documents (%.3fs)", len(ids), len(documents), elapsed)
        return ids

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        return self._store.delete(doc_id)

    def update_document(self, doc_id: str, text: str, metadata: Optional[dict[str, Any]] = None) -> bool:
        """Update an existing document."""
        return self._store.update(doc_id, text, metadata)

    def get_document_count(self) -> int:
        """Return number of indexed documents."""
        return self._store.count()

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Retrieve relevant documents for a query.

        Args:
            query: The search query.
            top_k: Number of results to return.

        Returns:
            List of SearchResult objects, sorted by relevance.
        """
        start = time.monotonic()
        try:
            # Retrieve more candidates than needed for reranking
            fetch_k = min(top_k * 3, self._store.count())
            if fetch_k == 0:
                return []

            raw_results = self._store.search(query, top_k=fetch_k)

            # Rerank
            reranked = self._reranker.rerank(query, raw_results, top_k=top_k)

            elapsed = time.monotonic() - start
            self._query_count += 1
            self._total_query_time += elapsed

            logger.debug(
                "Retrieved %d results (from %d raw) in %.3fs",
                len(reranked),
                len(raw_results),
                elapsed,
            )
            return reranked

        except Exception as exc:
            logger.error("Retrieval failed: %s", exc)
            return []

    def retrieve_raw(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Retrieve without reranking (for debugging)."""
        return self._store.search(query, top_k=top_k)

    # ------------------------------------------------------------------
    # RAG: Augment & Query
    # ------------------------------------------------------------------

    def augment_prompt(self, query: str, context: list[SearchResult]) -> str:
        """Combine a query with retrieved context into an augmented prompt.

        Args:
            query: The original user query.
            context: Retrieved search results.

        Returns:
            An augmented prompt string ready for the LLM.
        """
        if not context:
            return query

        # Build context section
        context_parts: list[str] = []
        total_length = 0

        for i, result in enumerate(context, 1):
            text = result.text.strip()
            if not text:
                continue

            # Truncate if needed
            remaining = self._max_context_length - total_length
            if remaining <= 0:
                break
            if len(text) > remaining:
                text = text[:remaining] + "..."

            source = result.metadata.get("source", "")
            topic = result.metadata.get("topic", "")
            header = f"[{i}]"
            if source:
                header += f" Source: {source}"
            if topic:
                header += f" | Topic: {topic}"

            context_parts.append(f"{header}\n{text}")
            total_length += len(text)

        if not context_parts:
            return query

        context_block = "\n\n".join(context_parts)

        augmented = f"""Based on the following retrieved context, answer the user's question.
If the context doesn't contain relevant information, say so and answer based on your general knowledge.

--- Retrieved Context ---
{context_block}
--- End Context ---

User Question: {query}

Answer:"""
        return augmented

    def query_with_rag(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """Full RAG: retrieve context, augment prompt, return result.

        Args:
            query: The user's question.
            top_k: Number of context documents to retrieve.

        Returns:
            Dict with keys:
                - augmented_prompt: The full prompt ready for the LLM
                - context: List of retrieved SearchResult dicts
                - query: Original query
                - num_context: Number of context documents used
        """
        context = self.retrieve(query, top_k=top_k)
        augmented = self.augment_prompt(query, context)

        return {
            "augmented_prompt": augmented,
            "context": [r.to_dict() for r in context],
            "query": query,
            "num_context": len(context),
        }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def rebuild_index(self, source_path: str | Path | None = None) -> int:
        """Rebuild the index from source files.

        Scans for JSON files in the skills directory and re-indexes them.

        Args:
            source_path: Path to scan for JSON files. If None, uses
                         HERMES_SKILLS_DIR env var or ~/.hermes/skills/.

        Returns:
            Number of documents indexed.
        """
        skills_dir = Path(
            source_path
            or os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills")
        )

        if not skills_dir.exists():
            logger.warning("Skills directory not found: %s", skills_dir)
            return 0

        # Clear existing index
        self._store.clear()
        logger.info("Cleared index, rebuilding from %s", skills_dir)

        count = 0
        for json_file in skills_dir.glob("*.json"):
            try:
                import json

                content = json_file.read_text(encoding="utf-8")
                data = json.loads(content)

                # Build searchable text from skill fields
                searchable_text = self._skill_to_text(data, json_file.name)
                metadata = {
                    "source": "skills",
                    "filename": json_file.name,
                    "topic": data.get("name", json_file.stem),
                }

                self._store.add(searchable_text, metadata=metadata)
                count += 1

            except Exception as exc:
                logger.warning("Failed to index %s: %s", json_file.name, exc)

        logger.info("Rebuilt index: %d documents from %s", count, skills_dir)
        return count

    def _skill_to_text(self, skill_data: dict[str, Any], filename: str) -> str:
        """Convert a skill dict to searchable text."""
        parts: list[str] = []

        if name := skill_data.get("name", ""):
            parts.append(f"Skill: {name}")

        if keywords := skill_data.get("trigger_keywords", []):
            parts.append(f"Keywords: {', '.join(keywords)}")

        if steps := skill_data.get("steps", []):
            parts.append("Steps:")
            for i, step in enumerate(steps, 1):
                parts.append(f"  {i}. {step}")

        if template := skill_data.get("result_template", ""):
            parts.append(f"Expected result: {template}")

        return "\n".join(parts) if parts else filename

    def clear(self) -> None:
        """Clear the entire index."""
        self._store.clear()
        logger.info("Index cleared")

    def persist(self) -> None:
        """Persist the vector store to disk."""
        self._store.persist()
        logger.info("Index persisted")

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        """Return pipeline statistics."""
        return {
            "embedding_provider": self._embedder.name,
            "vector_store": self._store.name,
            "reranker_strategy": self._reranker.strategy,
            "document_count": self._store.count(),
            "index_count": self._index_count,
            "query_count": self._query_count,
            "avg_index_time": (
                self._total_index_time / self._index_count
                if self._index_count > 0
                else 0
            ),
            "avg_query_time": (
                self._total_query_time / self._query_count
                if self._query_count > 0
                else 0
            ),
        }


# ---------------------------------------------------------------------------
# Factory / Singleton
# ---------------------------------------------------------------------------

_default_pipeline: Optional[RAGPipeline] = None


def get_rag_pipeline(**kwargs: Any) -> RAGPipeline:
    """Get or create the default RAG pipeline singleton.

    Args:
        **kwargs: Forwarded to RAGPipeline constructor (only on first call).

    Returns:
        The singleton RAGPipeline instance.
    """
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = RAGPipeline(**kwargs)
    return _default_pipeline


def reset_rag_pipeline() -> None:
    """Reset the singleton pipeline (for testing)."""
    global _default_pipeline
    _default_pipeline = None
