"""
Hermes Brain – long-term memory and skill management.

Responsibilities
----------------
* Persistent JSON-file storage under ``~/.hermes/skills/``.
* Skill registration, retrieval, and search.
* Conversation context tracking (sliding window + summary).
* Post-task pattern extraction – after every completed task the brain
  analyses the interaction and stores reusable patterns/skills.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HERMES_HOME = Path.home() / ".hermes"
SKILLS_DIR = HERMES_HOME / "skills"
CONTEXT_DIR = HERMES_HOME / "context"

MAX_CONTEXT_MESSAGES = 40  # rolling window
MAX_SKILL_FILE_SIZE = 1024 * 512  # 512 KB per skill file


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """A single reusable skill / pattern."""
    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    prompt_template: str = ""
    tool_sequence: list[dict[str, Any]] = field(default_factory=list)
    success_rate: float = 1.0
    created_at: float = 0.0
    last_used: float = 0.0
    use_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConversationTurn:
    """One user ↔ assistant exchange."""
    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Brain
# ---------------------------------------------------------------------------

class HermesBrain:
    """Persistent memory and skill management for the Hermes agent."""

    def __init__(
        self,
        *,
        skills_dir: Path | str | None = None,
        context_dir: Path | str | None = None,
        llm_fn: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self._skills_dir = Path(skills_dir) if skills_dir else SKILLS_DIR
        self._context_dir = Path(context_dir) if context_dir else CONTEXT_DIR
        self._llm_fn = llm_fn

        # Ensure directories exist
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._context_dir.mkdir(parents=True, exist_ok=True)

        # In-memory caches
        self._skills_cache: dict[str, Skill] = {}
        self._context: list[ConversationTurn] = []
        self._current_task_id: str | None = None

        self._load_all_skills()

    # ------------------------------------------------------------------
    # Skill management
    # ------------------------------------------------------------------

    def save_skill(self, skill: Skill) -> None:
        """Persist a skill to disk and update the in-memory cache."""
        self._ensure_dirs()
        path = self._skill_path(skill.id)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(skill.to_dict(), fh, indent=2, ensure_ascii=False)
        self._skills_cache[skill.id] = skill
        logger.info("Skill saved: %s (%s)", skill.name, skill.id)

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Retrieve a skill by its unique id."""
        return self._skills_cache.get(skill_id)

    def search_skills(self, query: str, *, tags: list[str] | None = None) -> list[Skill]:
        """Fuzzy search across skill names, descriptions, and tags."""
        query_lower = query.lower()
        results: list[tuple[float, Skill]] = []

        for skill in self._skills_cache.values():
            # Simple relevance scoring
            score = 0.0
            if query_lower in skill.name.lower():
                score += 3.0
            if query_lower in skill.description.lower():
                score += 2.0
            if any(query_lower in tag.lower() for tag in skill.tags):
                score += 1.5

            if tags:
                tag_overlap = set(t.lower() for t in tags) & set(t.lower() for t in skill.tags)
                score += len(tag_overlap) * 0.5

            # Boost popular skills
            score += min(skill.use_count * 0.1, 2.0)

            if score > 0:
                results.append((score, skill))

        results.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in results]

    def list_skills(self) -> list[Skill]:
        """Return all stored skills."""
        return list(self._skills_cache.values())

    def delete_skill(self, skill_id: str) -> bool:
        """Remove a skill from disk and cache."""
        path = self._skill_path(skill_id)
        if path.exists():
            path.unlink()
        removed = self._skills_cache.pop(skill_id, None)
        return removed is not None

    # ------------------------------------------------------------------
    # Conversation context
    # ------------------------------------------------------------------

    def new_task(self, task_id: str) -> None:
        """Begin tracking a new task (resets context)."""
        self._current_task_id = task_id
        self._context.clear()
        self._load_context(task_id)
        logger.info("New task context: %s", task_id)

    def add_turn(self, role: str, content: str, **metadata: Any) -> None:
        """Append a conversation turn and enforce the sliding window."""
        turn = ConversationTurn(
            role=role,
            content=content,
            timestamp=time.time(),
            metadata=metadata,
        )
        self._context.append(turn)

        # Trim to window size
        if len(self._context) > MAX_CONTEXT_MESSAGES:
            overflow = self._context[: MAX_CONTEXT_MESSAGES // 2]
            self._context = self._context[MAX_CONTEXT_MESSAGES // 2 :]
            # Persist trimmed portion as a summary
            if self._current_task_id:
                self._append_summary(overflow)

        if self._current_task_id:
            self._save_context()

    def get_context_messages(self, limit: int | None = None) -> list[dict[str, str]]:
        """Return context in a format suitable for LLM prompts."""
        turns = self._context[-limit:] if limit else self._context
        return [{"role": t.role, "content": t.content} for t in turns]

    def get_full_prompt_context(self) -> list[dict[str, str]]:
        """Context with prior summaries prepended."""
        messages: list[dict[str, str]] = []

        if self._current_task_id:
            summary = self._load_summary(self._current_task_id)
            if summary:
                messages.append({
                    "role": "system",
                    "content": f"Prior context summary:\n{summary}",
                })

        messages.extend(self.get_context_messages())
        return messages

    def end_task(self) -> None:
        """Finalise a task – extract patterns and persist everything."""
        if self._current_task_id:
            self._save_context()
            self._extract_patterns()
            logger.info("Task ended: %s", self._current_task_id)
            self._current_task_id = None

    # ------------------------------------------------------------------
    # Pattern extraction
    # ------------------------------------------------------------------

    def extract_pattern_from_task(
        self,
        task_description: str,
        tool_sequence: list[dict[str, Any]],
        *,
        success: bool = True,
    ) -> Skill | None:
        """Manually register a pattern observed during a task."""
        if not tool_sequence:
            return None

        # Generate a deterministic ID from the tool sequence
        raw = json.dumps(tool_sequence, sort_keys=True)
        skill_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

        # Avoid duplicates
        if skill_id in self._skills_cache:
            existing = self._skills_cache[skill_id]
            existing.use_count += 1
            existing.last_used = time.time()
            existing.success_rate = (
                existing.success_rate * 0.9 + (1.0 if success else 0.0) * 0.1
            )
            self.save_skill(existing)
            return existing

        skill = Skill(
            id=skill_id,
            name=f"auto_{task_description[:40].replace(' ', '_')}",
            description=task_description[:200],
            tags=self._auto_tags(tool_sequence),
            prompt_template="",
            tool_sequence=tool_sequence,
            success_rate=1.0 if success else 0.0,
            created_at=time.time(),
            last_used=time.time(),
            use_count=1,
        )
        self.save_skill(skill)
        return skill

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _skill_path(self, skill_id: str) -> Path:
        return self._skills_dir / f"{skill_id}.json"

    def _ensure_dirs(self) -> None:
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._context_dir.mkdir(parents=True, exist_ok=True)

    def _load_all_skills(self) -> None:
        """Load every skill JSON from the skills directory."""
        for path in self._skills_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                skill = Skill(**{
                    k: v for k, v in data.items() if k in Skill.__dataclass_fields__
                })
                self._skills_cache[skill.id] = skill
            except Exception as exc:
                logger.warning("Failed to load skill %s: %s", path, exc)

        logger.info("Loaded %d skills from %s", len(self._skills_cache), self._skills_dir)

    def _context_file(self, task_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)
        return self._context_dir / f"{safe}_context.json"

    def _summary_file(self, task_id: str) -> Path:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", task_id)
        return self._context_dir / f"{safe}_summary.txt"

    def _save_context(self) -> None:
        if not self._current_task_id:
            return
        path = self._context_file(self._current_task_id)
        data = [asdict(t) for t in self._context]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    def _load_context(self, task_id: str) -> None:
        path = self._context_file(task_id)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self._context = [
                    ConversationTurn(**{
                        k: v for k, v in t.items() if k in ConversationTurn.__dataclass_fields__
                    })
                    for t in data
                ]
            except Exception as exc:
                logger.warning("Failed to load context for %s: %s", task_id, exc)

    def _append_summary(self, old_turns: list[ConversationTurn]) -> None:
        if not self._current_task_id:
            return
        path = self._summary_file(self._current_task_id)
        snippet = "\n".join(
            f"[{t.role}] {t.content[:300]}" for t in old_turns
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(snippet + "\n---\n")

    def _load_summary(self, task_id: str) -> str:
        path = self._summary_file(task_id)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _auto_tags(self, tool_sequence: list[dict[str, Any]]) -> list[str]:
        """Infer tags from the tool types used."""
        tags: set[str] = set()
        for step in tool_sequence:
            tool_name = step.get("tool", "")
            if "shell" in tool_name or "exec" in tool_name:
                tags.add("shell")
            if "browser" in tool_name or "web" in tool_name:
                tags.add("browser")
            if "file" in tool_name:
                tags.add("filesystem")
            if "search" in tool_name:
                tags.add("search")
            if "git" in tool_name:
                tags.add("git")
        return sorted(tags)

    def _extract_patterns(self) -> None:
        """Analyse the completed task context and extract reusable patterns."""
        if not self._llm_fn or not self._context:
            return

        # Build a prompt asking the LLM to identify a reusable pattern
        conversation = "\n".join(
            f"[{t.role}] {t.content[:500]}" for t in self._context[-10:]
        )
        system = (
            "You are an AI memory manager. Analyse the following conversation "
            "and determine if a reusable skill/pattern was demonstrated. "
            "If yes, respond with JSON:\n"
            '{"name": "<short_name>", "description": "<what it does>", '
            '"tags": ["<tag1>", ...], "tool_sequence": [{"tool": "<name>", "args": {...}}, ...]}\n'
            "If no reusable pattern, respond with: {\"pattern\": false}"
        )
        try:
            raw = self._llm_fn(system, conversation)
            match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
            if match:
                obj = json.loads(match.group())
                if obj.get("pattern") is False:
                    return
                skill_id = hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]
                skill = Skill(
                    id=skill_id,
                    name=obj.get("name", "unnamed"),
                    description=obj.get("description", ""),
                    tags=obj.get("tags", []),
                    tool_sequence=obj.get("tool_sequence", []),
                    created_at=time.time(),
                    last_used=time.time(),
                    use_count=1,
                )
                self.save_skill(skill)
                logger.info("Auto-extracted pattern: %s", skill.name)
        except Exception as exc:
            logger.debug("Pattern extraction skipped: %s", exc)
