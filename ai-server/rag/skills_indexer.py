"""
Skills Indexer
==============
Semantic indexing of learned skills from JSON files.

Features:
- Index all skills from the skills directory
- Auto-index new skills when saved
- Search skills by semantic similarity
- Update index when skills change
- Converts skills to searchable documents
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

from .rag_pipeline import RAGPipeline, get_rag_pipeline
from .vector_store import SearchResult

logger = logging.getLogger(__name__)

# Default skills directory (matches skills_learner.py)
SKILLS_DIR = Path(os.environ.get("HERMES_SKILLS_DIR", Path.home() / ".hermes" / "skills"))


class SkillsIndexer:
    """Semantic indexer for the Hermes skills library.

    Reads skill JSON files, converts them to searchable documents,
    and maintains a vector index for semantic search.

    Usage::

        indexer = SkillsIndexer()
        indexer.index_all()  # Index all skill files

        # Search
        results = indexer.search("convert video to gif")
        for r in results:
            print(f"{r.score:.3f} - {r.metadata.get('topic', 'unknown')}")

        # Watch for changes
        indexer.auto_index_new_skills()
    """

    def __init__(
        self,
        skills_dir: str | Path | None = None,
        pipeline: Optional[RAGPipeline] = None,
    ) -> None:
        """Initialize the skills indexer.

        Args:
            skills_dir: Directory containing skill JSON files.
            pipeline: Optional RAGPipeline instance. Created if None.
        """
        self._skills_dir = Path(skills_dir) if skills_dir else SKILLS_DIR
        self._pipeline = pipeline or get_rag_pipeline()
        self._indexed_hashes: dict[str, str] = {}  # filename -> content hash
        self._load_index_state()

    def _state_path(self) -> Path:
        """Path to the index state file."""
        return self._skills_dir / ".index_state.json"

    def _load_index_state(self) -> None:
        """Load previously indexed file hashes."""
        state_path = self._state_path()
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text(encoding="utf-8"))
                self._indexed_hashes = data.get("hashes", {})
                logger.debug("Loaded index state: %d files tracked", len(self._indexed_hashes))
            except Exception as exc:
                logger.warning("Failed to load index state: %s", exc)
                self._indexed_hashes = {}

    def _save_index_state(self) -> None:
        """Persist the index state."""
        try:
            state_path = self._state_path()
            data = {
                "hashes": self._indexed_hashes,
                "last_updated": time.time(),
            }
            state_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save index state: %s", exc)

    def _file_hash(self, filepath: Path) -> str:
        """Compute content hash for a file."""
        content = filepath.read_text(encoding="utf-8")
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def skill_to_document(self, skill_data: dict[str, Any], filename: str) -> dict[str, Any]:
        """Convert a skill dict to a searchable document.

        Args:
            skill_data: The skill JSON data.
            filename: Source filename.

        Returns:
            Dict with 'text' and 'metadata' keys.
        """
        parts: list[str] = []
        metadata: dict[str, Any] = {
            "source": "skills",
            "filename": filename,
            "type": "skill",
        }

        # Name
        name = skill_data.get("name", "unnamed")
        parts.append(f"Skill: {name}")
        metadata["topic"] = name

        # Trigger keywords
        keywords = skill_data.get("trigger_keywords", [])
        if keywords:
            parts.append(f"Trigger keywords: {', '.join(keywords)}")
            metadata["keywords"] = keywords

        # Description (if present)
        if desc := skill_data.get("description", ""):
            parts.append(f"Description: {desc}")

        # Steps
        steps = skill_data.get("steps", [])
        if steps:
            parts.append("Steps:")
            for i, step in enumerate(steps, 1):
                parts.append(f"  {i}. {step}")
            metadata["step_count"] = len(steps)

        # Result template
        if template := skill_data.get("result_template", ""):
            parts.append(f"Expected result: {template}")

        # Stats
        metadata["success_count"] = skill_data.get("success_count", 0)
        if last_used := skill_data.get("last_used"):
            metadata["last_used"] = last_used

        return {
            "text": "\n".join(parts),
            "metadata": metadata,
        }

    def index_all(self) -> int:
        """Index all skill JSON files in the skills directory.

        Returns:
            Number of skills indexed.
        """
        if not self._skills_dir.exists():
            logger.warning("Skills directory does not exist: %s", self._skills_dir)
            return 0

        count = 0
        for json_file in self._skills_dir.glob("*.json"):
            if json_file.name.startswith("."):
                continue
            try:
                if self._index_file(json_file):
                    count += 1
            except Exception as exc:
                logger.warning("Failed to index %s: %s", json_file.name, exc)

        self._save_index_state()
        logger.info("Indexed %d skills from %s", count, self._skills_dir)
        return count

    def _index_file(self, filepath: Path) -> bool:
        """Index a single skill file. Returns True if newly indexed/updated."""
        filename = filepath.name
        current_hash = self._file_hash(filepath)

        # Check if already indexed with same hash
        if self._indexed_hashes.get(filename) == current_hash:
            return False

        # Read and parse skill
        content = filepath.read_text(encoding="utf-8")
        try:
            skill_data = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON in %s: %s", filename, exc)
            return False

        # Convert to document
        doc = self.skill_to_document(skill_data, filename)

        # Index it
        self._pipeline.index_document(doc["text"], metadata=doc["metadata"])

        # Track hash
        self._indexed_hashes[filename] = current_hash
        return True

    def index_skill(self, skill_data: dict[str, Any], filename: str = "") -> str:
        """Index a single skill from a dict (e.g., after saving a new skill).

        Args:
            skill_data: The skill data dict.
            filename: Optional filename for tracking.

        Returns:
            The document ID.
        """
        doc = self.skill_to_document(skill_data, filename)
        doc_id = self._pipeline.index_document(doc["text"], metadata=doc["metadata"])

        if filename:
            self._indexed_hashes[filename] = hashlib.sha256(
                json.dumps(skill_data, sort_keys=True).encode()
            ).hexdigest()[:16]
            self._save_index_state()

        return doc_id

    def auto_index_new_skills(self) -> int:
        """Check for new or changed skill files and index them.

        This is designed to be called periodically or on skill save events.

        Returns:
            Number of new/updated skills indexed.
        """
        if not self._skills_dir.exists():
            return 0

        count = 0
        for json_file in self._skills_dir.glob("*.json"):
            if json_file.name.startswith("."):
                continue
            try:
                if self._index_file(json_file):
                    count += 1
                    logger.info("Auto-indexed skill: %s", json_file.name)
            except Exception as exc:
                logger.warning("Failed to auto-index %s: %s", json_file.name, exc)

        if count > 0:
            self._save_index_state()
            logger.info("Auto-indexed %d new/updated skills", count)

        return count

    def remove_skill(self, filename: str) -> bool:
        """Remove a skill from the index by filename.

        Args:
            filename: The skill JSON filename.

        Returns:
            True if removed.
        """
        # Remove from tracking
        if filename in self._indexed_hashes:
            del self._indexed_hashes[filename]
            self._save_index_state()

        # Note: We can't easily remove from the vector store by filename alone,
        # but the hash tracking ensures it won't be re-indexed until the state is reset.
        return True

    def rebuild(self) -> int:
        """Force a complete rebuild of the skills index.

        Returns:
            Number of skills indexed.
        """
        self._indexed_hashes.clear()
        self._pipeline.clear()
        count = self.index_all()
        logger.info("Skills index rebuilt: %d documents", count)
        return count

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Search skills by semantic similarity.

        Args:
            query: The search query.
            top_k: Number of results.

        Returns:
            List of SearchResult objects.
        """
        return self._pipeline.retrieve(query, top_k=top_k)

    def search_with_keywords(
        self,
        query: str,
        keywords: list[str] | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]:
        """Search with both semantic similarity and keyword matching.

        Combines semantic search with keyword presence boost.

        Args:
            query: The search query.
            keywords: Additional keywords to boost.
            top_k: Number of results.

        Returns:
            List of SearchResult objects.
        """
        # Get semantic results
        results = self._pipeline.retrieve(query, top_k=top_k * 2)

        if not keywords:
            return results[:top_k]

        # Boost results that contain keywords
        for result in results:
            text_lower = result.text.lower()
            keyword_boost = sum(
                0.1 for kw in keywords if kw.lower() in text_lower
            )
            result.score = min(1.0, result.score + keyword_boost)

        # Re-sort by boosted score
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def get_stats(self) -> dict[str, Any]:
        """Return indexer statistics."""
        return {
            "skills_dir": str(self._skills_dir),
            "indexed_files": len(self._indexed_hashes),
            "total_documents": self._pipeline.get_document_count(),
            "pipeline_stats": self._pipeline.stats(),
        }


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_default_indexer: Optional[SkillsIndexer] = None


def get_skills_indexer(**kwargs: Any) -> SkillsIndexer:
    """Get or create the default skills indexer singleton."""
    global _default_indexer
    if _default_indexer is None:
        _default_indexer = SkillsIndexer(**kwargs)
    return _default_indexer


def search_similar_skills(query: str, top_k: int = 5) -> list[SearchResult]:
    """Convenience: search skills by semantic similarity.

    Args:
        query: The search query.
        top_k: Number of results.

    Returns:
        List of SearchResult objects.
    """
    return get_skills_indexer().search(query, top_k=top_k)
