"""Persistent skill storage and retrieval as JSON files.

Each skill is stored as a separate JSON file in a configurable skills directory.
Skills have: name, trigger_keywords, steps, result_template, success_count, last_used.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Skill:
    """Represents a single stored skill."""

    __slots__ = (
        "id",
        "name",
        "trigger_keywords",
        "steps",
        "result_template",
        "success_count",
        "last_used",
        "created_at",
    )

    def __init__(
        self,
        skill_id: str,
        name: str,
        trigger_keywords: list[str],
        steps: list[str],
        result_template: str = "",
        success_count: int = 0,
        last_used: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> None:
        self.id: str = skill_id
        self.name: str = name
        self.trigger_keywords: list[str] = trigger_keywords
        self.steps: list[str] = steps
        self.result_template: str = result_template
        self.success_count: int = success_count
        self.last_used: Optional[str] = last_used
        self.created_at: str = created_at or datetime.now(timezone.utc).isoformat()

    # -- serialisation helpers --

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "trigger_keywords": self.trigger_keywords,
            "steps": self.steps,
            "result_template": self.result_template,
            "success_count": self.success_count,
            "last_used": self.last_used,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        return cls(
            skill_id=data.get("id", uuid.uuid4().hex[:8]),
            name=data.get("name", "unnamed"),
            trigger_keywords=data.get("trigger_keywords", []),
            steps=data.get("steps", []),
            result_template=data.get("result_template", ""),
            success_count=data.get("success_count", 0),
            last_used=data.get("last_used"),
            created_at=data.get("created_at"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> Skill:
        return cls.from_dict(json.loads(raw))

    def __repr__(self) -> str:
        return f"<Skill {self.name!r} keywords={self.trigger_keywords}>"


class SkillManager:
    """Stores and retrieves skills as JSON files in *skills_dir*.

    Parameters
    ----------
    skills_dir:
        Directory to persist skill JSON files in.  Created automatically if
        it does not exist.
    """

    def __init__(self, skills_dir: str | Path = "skills") -> None:
        self.skills_dir: Path = Path(skills_dir)
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Skill] = {}
        self._load_all()
        logger.info("SkillManager initialised – %d skill(s) loaded", len(self._cache))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        """Load every JSON file in the skills directory into *self._cache*."""
        self._cache.clear()
        for path in self.skills_dir.glob("*.json"):
            try:
                skill = Skill.from_json(path.read_text(encoding="utf-8"))
                self._cache[skill.id] = skill
            except Exception:
                logger.exception("Failed to load skill from %s", path)

    def _skill_path(self, skill: Skill) -> Path:
        """Return the filesystem path for a skill, sanitising the name."""
        safe_name = re.sub(r"[^a-zA-Z0-9_\-]", "_", skill.name.lower().strip())[:64]
        return self.skills_dir / f"{safe_name}_{skill.id}.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_skill(
        self,
        name: str,
        trigger_keywords: list[str],
        steps: list[str],
        result_template: str = "",
    ) -> Skill:
        """Create (or update) a skill and persist it to disk.

        Returns the created/updated :class:`Skill`.
        """
        # Check if a skill with the same name already exists → update it
        for existing in self._cache.values():
            if existing.name.lower() == name.lower():
                existing.trigger_keywords = trigger_keywords
                existing.steps = steps
                existing.result_template = result_template
                path = self._skill_path(existing)
                path.write_text(existing.to_json(), encoding="utf-8")
                logger.info("Updated skill: %s", existing.name)
                return existing

        skill = Skill(
            skill_id=uuid.uuid4().hex[:8],
            name=name,
            trigger_keywords=trigger_keywords,
            steps=steps,
            result_template=result_template,
        )
        self._cache[skill.id] = skill
        path = self._skill_path(skill)
        path.write_text(skill.to_json(), encoding="utf-8")
        logger.info("Saved skill: %s (%s)", skill.name, skill.id)
        return skill

    def find_skill(self, query: str) -> Optional[Skill]:
        """Find the best-matching skill for a free-text *query*.

        Matching strategy (descending priority):
        1. Exact keyword match (case-insensitive).
        2. Substring keyword match.
        3. Token-overlap score.

        Returns ``None`` if no skill matches above the threshold.
        """
        if not self._cache:
            return None

        query_lower = query.lower()
        tokens = set(re.findall(r"\w+", query_lower))

        best: Optional[Skill] = None
        best_score: float = 0.0

        for skill in self._cache.values():
            score = 0.0
            for kw in skill.trigger_keywords:
                kw_lower = kw.lower()
                if query_lower == kw_lower:
                    score += 3.0
                elif kw_lower in query_lower or query_lower in kw_lower:
                    score += 2.0
                elif tokens & set(re.findall(r"\w+", kw_lower)):
                    score += 1.0

            # Bonus for skills with higher success rate
            if skill.success_count > 0:
                score *= 1.0 + min(skill.success_count / 100.0, 1.0)

            if score > best_score:
                best_score = score
                best = skill

        if best and best_score >= 2.0:
            return best
        return None

    def update_success(self, skill_id: str) -> Optional[Skill]:
        """Increment *success_count* and update *last_used* for a skill."""
        skill = self._cache.get(skill_id)
        if not skill:
            logger.warning("update_success: unknown skill id %s", skill_id)
            return None

        skill.success_count += 1
        skill.last_used = datetime.now(timezone.utc).isoformat()

        path = self._skill_path(skill)
        path.write_text(skill.to_json(), encoding="utf-8")
        logger.info(
            "Updated success for %s → %d", skill.name, skill.success_count
        )
        return skill

    def list_skills(self) -> list[Skill]:
        """Return all stored skills, sorted by name."""
        return sorted(self._cache.values(), key=lambda s: s.name.lower())

    def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill by id. Returns ``True`` if deleted."""
        skill = self._cache.pop(skill_id, None)
        if not skill:
            return False
        path = self._skill_path(skill)
        if path.exists():
            path.unlink()
        logger.info("Deleted skill: %s (%s)", skill.name, skill_id)
        return True

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by id."""
        return self._cache.get(skill_id)

    def reload(self) -> None:
        """Re-read all skill files from disk."""
        self._load_all()
        logger.info("Skills reloaded – %d total", len(self._cache))
