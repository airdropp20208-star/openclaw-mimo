"""
RAG (Retrieval Augmented Generation) Package
=============================================
Provides vector search and context retrieval for the Hermes multi-agent system.
Enables semantic search over skills, memory, and documents to enhance LLM reasoning.

Components:
    - embeddings: Text embedding providers (hash, sentence-transformers, OpenAI)
    - vector_store: Vector database backends (ChromaDB, FAISS, in-memory)
    - rag_pipeline: End-to-end RAG pipeline for document indexing and retrieval
    - skills_indexer: Semantic indexing of learned skills
    - memory_indexer: Indexing of conversation history and long-term memory
    - reranker: Result reranking, deduplication, and diversity filtering

Usage::

    from rag import get_rag_pipeline

    pipeline = get_rag_pipeline()
    pipeline.index_document("Important context about X", {"topic": "X"})
    results = pipeline.query_with_rag("Tell me about X")
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Lazy imports to avoid import errors when optional deps are missing
__all__ = [
    # Core pipeline
    "RAGPipeline",
    "get_rag_pipeline",
    # Embeddings
    "EmbeddingProvider",
    "SimpleHashEmbedding",
    "SentenceTransformerEmbedding",
    "OpenAIEmbedding",
    "get_embedding_provider",
    # Vector stores
    "VectorStore",
    "ChromaDBStore",
    "FAISSStore",
    "SimpleInMemoryStore",
    "get_vector_store",
    # Indexers
    "SkillsIndexer",
    "MemoryIndexer",
    # Reranker
    "Reranker",
    # Convenience
    "search_similar_skills",
    "search_memory",
]


def __getattr__(name: str):
    """Lazy-load submodules to gracefully handle missing optional dependencies."""
    if name in ("RAGPipeline", "get_rag_pipeline"):
        from .rag_pipeline import RAGPipeline, get_rag_pipeline
        return RAGPipeline if name == "RAGPipeline" else get_rag_pipeline

    if name in ("EmbeddingProvider", "SimpleHashEmbedding", "SentenceTransformerEmbedding",
                 "OpenAIEmbedding", "get_embedding_provider"):
        from .embeddings import (
            EmbeddingProvider, SimpleHashEmbedding, SentenceTransformerEmbedding,
            OpenAIEmbedding, get_embedding_provider,
        )
        _map = {
            "EmbeddingProvider": EmbeddingProvider,
            "SimpleHashEmbedding": SimpleHashEmbedding,
            "SentenceTransformerEmbedding": SentenceTransformerEmbedding,
            "OpenAIEmbedding": OpenAIEmbedding,
            "get_embedding_provider": get_embedding_provider,
        }
        return _map[name]

    if name in ("VectorStore", "ChromaDBStore", "FAISSStore", "SimpleInMemoryStore",
                 "get_vector_store"):
        from .vector_store import (
            VectorStore, ChromaDBStore, FAISSStore, SimpleInMemoryStore, get_vector_store,
        )
        _map = {
            "VectorStore": VectorStore,
            "ChromaDBStore": ChromaDBStore,
            "FAISSStore": FAISSStore,
            "SimpleInMemoryStore": SimpleInMemoryStore,
            "get_vector_store": get_vector_store,
        }
        return _map[name]

    if name == "SkillsIndexer":
        from .skills_indexer import SkillsIndexer
        return SkillsIndexer

    if name == "MemoryIndexer":
        from .memory_indexer import MemoryIndexer
        return MemoryIndexer

    if name == "Reranker":
        from .reranker import Reranker
        return Reranker

    # Convenience functions
    if name == "search_similar_skills":
        from .skills_indexer import search_similar_skills
        return search_similar_skills

    if name == "search_memory":
        from .memory_indexer import search_memory
        return search_memory

    raise AttributeError(f"module 'rag' has no attribute {name!r}")
