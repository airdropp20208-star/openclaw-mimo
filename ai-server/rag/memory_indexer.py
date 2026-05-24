"""
Memory Indexer
==============
Semantic indexing of conversation history and long-term memory.

Features:
- Index conversation messages and exchanges
- Search by topic/content with semantic similarity
- Long-term memory retrieval
- Conversation summarization for compact indexing
- Temporal awareness (recency boosting)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .rag_pipeline import RAGPipeline, get_rag_pipeline
from .vector_store import SearchResult

logger = logging.getLogger(__name__)

# Default memory directory
MEMORY_DIR = Path(os.environ.get("HERMES_MEMORY_DIR", Path.home() / ".hermes" / "memory"))


class MemoryIndexer:
    """Semantic indexer for conversation history and long-term memory.

    Indexes conversation messages for semantic search, enabling the AI to
    recall relevant past interactions.

    Usage::

        indexer = MemoryIndexer()

        # Index a conversation
        indexer.index_conversation("user123", [
            {"role": "user", "content": "How do I deploy to AWS?"},
            {"role": "assistant", "content": "To deploy to AWS, use..."},
        ])

        # Search memory
        results = indexer.search("AWS deployment")
    """

    def __init__(
        self,
        memory_dir: str | Path | None = None,
        pipeline: Optional[RAGPipeline] = None,
        max_message_age_days: int = 90,
    ) -> None:
        """Initialize the memory indexer.

        Args:
            memory_dir: Directory containing conversation memory files.
            pipeline: Optional RAGPipeline. Created if None.
            max_message_age_days: Index messages up to this many days old.
        """
        self._memory_dir = Path(memory_dir) if memory_dir else MEMORY_DIR
        self._pipeline = pipeline or get_rag_pipeline()
        self._max_age_days = max_message_age_days
        self._indexed_conversations: dict[str, str] = {}  # conv_id -> hash

    def _format_message(
        self,
        role: str,
        content: str,
        conversation_id: str = "",
        timestamp: str = "",
    ) -> str:
        """Format a single message into searchable text."""
        parts = [f"[{role.upper()}]"]
        if timestamp:
            parts.append(f"Time: {timestamp}")
        if conversation_id:
            parts.append(f"Conversation: {conversation_id}")
        parts.append(content)
        return "\n".join(parts)

    def _summarize_conversation(self, messages: list[dict[str, str]]) -> str:
        """Create a compact summary of a conversation for indexing.

        Extracts the key topics and questions discussed.
        """
        if not messages:
            return ""

        topics: list[str] = []
        questions: list[str] = []
        key_points: list[str] = []

        for msg in messages:
            content = msg.get("content", "")
            role = msg.get("role", "").lower()

            if role == "user":
                questions.append(content[:200])
            elif role == "assistant":
                # Take first sentence as key point
                first_sentence = content.split(".")[0] if "." in content else content[:200]
                key_points.append(first_sentence)

        # Build summary
        parts = []
        if questions:
            parts.append(f"Questions asked: {'; '.join(questions[:5])}")
        if key_points:
            parts.append(f"Key responses: {'; '.join(key_points[:5])}")

        return "\n".join(parts)

    def index_conversation(
        self,
        conversation_id: str,
        messages: list[dict[str, str]],
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Index a conversation exchange.

        Args:
            conversation_id: Unique identifier for the conversation.
            messages: List of message dicts with 'role' and 'content'.
            metadata: Optional extra metadata.

        Returns:
            The document ID.
        """
        if not messages:
            return ""

        # Create conversation hash to detect changes
        conv_hash = hashlib.sha256(
            json.dumps(messages, ensure_ascii=False).encode()
        ).hexdigest()[:16]

        if self._indexed_conversations.get(conversation_id) == conv_hash:
            logger.debug("Conversation %s unchanged, skipping", conversation_id)
            return ""

        # Build searchable text from messages
        timestamp = messages[0].get("timestamp", datetime.now(timezone.utc).isoformat())
        text_parts: list[str] = []
        for msg in messages:
            text_parts.append(
                self._format_message(
                    role=msg.get("role", "unknown"),
                    content=msg.get("content", ""),
                    conversation_id=conversation_id,
                    timestamp=msg.get("timestamp", ""),
                )
            )

        full_text = "\n\n".join(text_parts)

        # Also create a summary for compact indexing
        summary = self._summarize_conversation(messages)

        # Index the full conversation
        meta = {
            "source": "conversation",
            "conversation_id": conversation_id,
            "message_count": len(messages),
            "timestamp": timestamp,
            "type": "conversation_full",
            **(metadata or {}),
        }
        doc_id = self._pipeline.index_document(full_text, metadata=meta)

        # Also index the summary as a separate document
        if summary:
            summary_meta = {
                "source": "conversation",
                "conversation_id": conversation_id,
                "type": "conversation_summary",
                "timestamp": timestamp,
                **(metadata or {}),
            }
            self._pipeline.index_document(summary, metadata=summary_meta)

        # Track
        self._indexed_conversations[conversation_id] = conv_hash

        logger.debug(
            "Indexed conversation %s (%d messages)", conversation_id, len(messages)
        )
        return doc_id

    def index_message(
        self,
        role: str,
        content: str,
        conversation_id: str = "",
        timestamp: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Index a single message.

        Args:
            role: Message role ('user', 'assistant', 'system').
            content: Message content.
            conversation_id: Optional conversation ID.
            timestamp: Optional timestamp.
            metadata: Optional extra metadata.

        Returns:
            The document ID.
        """
        text = self._format_message(
            role=role,
            content=content,
            conversation_id=conversation_id,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        )

        meta = {
            "source": "conversation",
            "role": role,
            "type": "message",
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }
        if conversation_id:
            meta["conversation_id"] = conversation_id

        return self._pipeline.index_document(text, metadata=meta)

    def index_from_file(self, filepath: str | Path) -> int:
        """Index memory from a JSON file.

        Expected format:
        {
            "conversation_id": "...",
            "messages": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ],
            "timestamp": "..."
        }

        Or a list of conversations:
        [
            {"conversation_id": "...", "messages": [...]},
            ...
        ]

        Args:
            filepath: Path to the JSON memory file.

        Returns:
            Number of conversations indexed.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            logger.warning("Memory file not found: %s", filepath)
            return 0

        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON in %s: %s", filepath.name, exc)
            return 0

        count = 0
        if isinstance(data, dict):
            # Single conversation
            conv_id = data.get("conversation_id", filepath.stem)
            messages = data.get("messages", [])
            if messages:
                self.index_conversation(conv_id, messages, metadata={"file": filepath.name})
                count = 1
        elif isinstance(data, list):
            # Multiple conversations
            for item in data:
                if isinstance(item, dict):
                    conv_id = item.get("conversation_id", f"conv_{count}")
                    messages = item.get("messages", [])
                    if messages:
                        self.index_conversation(conv_id, messages, metadata={"file": filepath.name})
                        count += 1

        logger.info("Indexed %d conversations from %s", count, filepath.name)
        return count

    def index_all_memory_files(self) -> int:
        """Index all memory JSON files in the memory directory.

        Returns:
            Total conversations indexed.
        """
        if not self._memory_dir.exists():
            logger.warning("Memory directory not found: %s", self._memory_dir)
            return 0

        total = 0
        for json_file in self._memory_dir.glob("*.json"):
            if json_file.name.startswith("."):
                continue
            total += self.index_from_file(json_file)

        return total

    def search(
        self,
        query: str,
        top_k: int = 5,
        recency_boost: float = 0.2,
    ) -> list[SearchResult]:
        """Search memory by semantic similarity.

        Args:
            query: The search query.
            top_k: Number of results.
            recency_boost: Boost factor for more recent messages (0.0 to 1.0).

        Returns:
            List of SearchResult objects, sorted by relevance.
        """
        results = self._pipeline.retrieve(query, top_k=top_k * 2)

        if recency_boost > 0:
            results = self._apply_recency_boost(results, recency_boost)

        # Deduplicate by conversation_id
        seen_convs: set[str] = set()
        deduplicated: list[SearchResult] = []
        for r in results:
            conv_id = r.metadata.get("conversation_id", r.id)
            if conv_id not in seen_convs:
                seen_convs.add(conv_id)
                deduplicated.append(r)

        return deduplicated[:top_k]

    def search_by_topic(self, topic: str, top_k: int = 5) -> list[SearchResult]:
        """Search memory filtered by topic.

        Args:
            topic: The topic to search for.
            top_k: Number of results.

        Returns:
            List of SearchResult objects.
        """
        # Use the topic as both the query and metadata filter
        results = self._pipeline.retrieve(topic, top_k=top_k * 3)

        # Boost results that mention the topic
        topic_lower = topic.lower()
        for r in results:
            if topic_lower in r.text.lower():
                r.score = min(1.0, r.score + 0.3)

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def get_long_term_memory(
        self,
        query: str,
        top_k: int = 10,
        min_score: float = 0.3,
    ) -> list[SearchResult]:
        """Retrieve relevant long-term memories.

        Returns higher-scoring results that represent significant
        past interactions.

        Args:
            query: The search query.
            top_k: Maximum number of results.
            min_score: Minimum relevance score.

        Returns:
            List of SearchResult objects.
        """
        results = self._pipeline.retrieve(query, top_k=top_k * 2)

        # Filter by minimum score and prefer full conversations over messages
        filtered: list[SearchResult] = []
        for r in results:
            if r.score >= min_score:
                # Boost full conversations
                if r.metadata.get("type") == "conversation_full":
                    r.score = min(1.0, r.score + 0.1)
                filtered.append(r)

        filtered.sort(key=lambda x: x.score, reverse=True)
        return filtered[:top_k]

    def _apply_recency_boost(
        self,
        results: list[SearchResult],
        boost_factor: float,
    ) -> list[SearchResult]:
        """Apply recency boost to search results."""
        now = time.time()

        for r in results:
            timestamp = r.metadata.get("timestamp", "")
            if not timestamp:
                continue

            try:
                # Parse ISO timestamp
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    age_days = (now - dt.timestamp()) / 86400.0
                else:
                    continue

                # Apply exponential decay boost
                recency = max(0.0, 1.0 - (age_days / self._max_age_days))
                r.score = min(1.0, r.score + recency * boost_factor)

            except (ValueError, TypeError):
                continue

        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def rebuild(self) -> int:
        """Force a complete rebuild of the memory index.

        Returns:
            Total conversations indexed.
        """
        self._indexed_conversations.clear()
        self._pipeline.clear()
        count = self.index_all_memory_files()
        logger.info("Memory index rebuilt: %d conversations", count)
        return count

    def get_stats(self) -> dict[str, Any]:
        """Return indexer statistics."""
        return {
            "memory_dir": str(self._memory_dir),
            "indexed_conversations": len(self._indexed_conversations),
            "total_documents": self._pipeline.get_document_count(),
            "max_age_days": self._max_age_days,
            "pipeline_stats": self._pipeline.stats(),
        }


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_indexer: Optional[MemoryIndexer] = None


def get_memory_indexer(**kwargs: Any) -> MemoryIndexer:
    """Get or create the default memory indexer singleton."""
    global _default_indexer
    if _default_indexer is None:
        _default_indexer = MemoryIndexer(**kwargs)
    return _default_indexer


def search_memory(query: str, top_k: int = 5) -> list[SearchResult]:
    """Convenience: search memory by semantic similarity.

    Args:
        query: The search query.
        top_k: Number of results.

    Returns:
        List of SearchResult objects.
    """
    return get_memory_indexer().search(query, top_k=top_k)
