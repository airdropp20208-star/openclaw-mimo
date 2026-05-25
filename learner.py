"""
Learning Module — extracts patterns from successful tasks, stores reusable skills.

The learner enables Hermes to:
1. Record successful task executions with context
2. Extract reusable patterns (tool sequences, approaches, gotchas)
3. Build a skill library that grows over time
4. Suggest relevant skills when similar tasks appear
5. Rank skills by success rate and recency
"""

import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SKILLS_FILE = os.path.join(_DATA_DIR, "hermes_skills.json")


class Skill:
    """A learned skill/pattern from past successful tasks."""

    def __init__(
        self,
        skill_id: str,
        name: str,
        description: str,
        category: str = "general",
        tool_sequence: Optional[list[str]] = None,
        template: Optional[str] = None,
        triggers: Optional[list[str]] = None,  # keywords that match this skill
        success_count: int = 1,
        fail_count: int = 0,
        created_at: Optional[str] = None,
        last_used: Optional[str] = None,
        examples: Optional[list[dict]] = None,
    ):
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.category = category
        self.tool_sequence = tool_sequence or []
        self.template = template
        self.triggers = triggers or []
        self.success_count = success_count
        self.fail_count = fail_count
        self.created_at = created_at or datetime.now().isoformat()
        self.last_used = last_used or self.created_at
        self.examples = examples or []

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return round(self.success_count / total * 100, 1) if total > 0 else 0.0

    @property
    def score(self) -> float:
        """Ranking score: higher = more useful."""
        rate = self.success_rate / 100
        # Recency bonus (exponential decay over 30 days)
        try:
            last = datetime.fromisoformat(self.last_used)
            days_ago = (datetime.now() - last).days
            recency = max(0.1, 2.718 ** (-days_ago / 30))
        except (ValueError, TypeError):
            recency = 0.5
        return round(rate * recency * (1 + self.success_count * 0.1), 3)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tool_sequence": self.tool_sequence,
            "template": self.template,
            "triggers": self.triggers,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "examples": self.examples,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        valid = {k for k in cls.__init__.__code__.co_varnames if k != "self"}
        return cls(**{k: v for k, v in data.items() if k in valid})


class TaskRecord:
    """Record of a completed task for pattern extraction."""

    def __init__(
        self,
        task_id: str,
        user_request: str,
        tools_used: list[str],
        success: bool,
        duration_sec: float = 0,
        output_summary: str = "",
        timestamp: Optional[str] = None,
        extracted_pattern: Optional[dict] = None,
    ):
        self.task_id = task_id
        self.user_request = user_request
        self.tools_used = tools_used
        self.success = success
        self.duration_sec = duration_sec
        self.output_summary = output_summary
        self.timestamp = timestamp or datetime.now().isoformat()
        self.extracted_pattern = extracted_pattern

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class Learner:
    """
    Learning engine.

    Records task executions, extracts patterns, and builds a skill library.
    """

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self._skills: list[Skill] = []
        self._records: list[dict] = []
        self._skill_counter = 0
        self._record_counter = 0
        self._max_records = 200  # Keep last 200 task records
        self._load()

    # --- Persistence ---

    def _load(self) -> None:
        try:
            with open(SKILLS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            chat_data = data.get(str(self.chat_id), {})
            self._skills = [Skill.from_dict(s) for s in chat_data.get("skills", [])]
            self._records = chat_data.get("records", [])
            self._skill_counter = chat_data.get("skill_counter", 0)
            self._record_counter = chat_data.get("record_counter", 0)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self._skills = []
            self._records = []
            self._skill_counter = 0
            self._record_counter = 0

    def _save(self) -> None:
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            data = {}
            try:
                with open(SKILLS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            data[str(self.chat_id)] = {
                "skills": [s.to_dict() for s in self._skills],
                "records": self._records[-self._max_records:],
                "skill_counter": self._skill_counter,
                "record_counter": self._record_counter,
            }
            tmp = SKILLS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, SKILLS_FILE)
        except Exception as e:
            logger.error("Failed to save skills: %s", e)

    # --- Task Recording ---

    def record_task(
        self,
        user_request: str,
        tools_used: list[str],
        success: bool,
        duration_sec: float = 0,
        output_summary: str = "",
    ) -> TaskRecord:
        """Record a completed task execution."""
        self._record_counter += 1
        record = TaskRecord(
            task_id=f"t{self._record_counter}",
            user_request=user_request,
            tools_used=tools_used,
            success=success,
            duration_sec=duration_sec,
            output_summary=output_summary[:500],
        )
        self._records.append(record.to_dict())

        # Trim old records
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

        self._save()
        logger.info("Recorded task %s: success=%s, tools=%s", record.task_id, success, tools_used)
        return record

    # --- Pattern Extraction ---

    def extract_pattern(self, record: dict, llm_fn=None) -> Optional[dict]:
        """
        Extract a reusable pattern from a task record.

        Without LLM: basic pattern from tool sequence.
        With LLM: richer pattern with description, triggers, template.
        """
        if not record.get("success") or not record.get("tools_used"):
            return None

        tools = record["tools_used"]

        if llm_fn:
            prompt = f"""Analyze this successful task and extract a reusable generalized pattern.
Focus on the STRATEGY rather than the specific instance.

User asked: {record['user_request']}
Tools used: {', '.join(tool for tool in tools)}
Output summary: {record.get('output_summary', '')}

Return a JSON object with:
- "name": short skill name (e.g. "Web Research & PPT Generation")
- "description": generalized strategy (e.g. "Search for info, summarize, and convert to slides")
- "category": [coding, research, file_ops, web, conversion, presentation, general]
- "triggers": 3-5 keywords or phrases that represent the INTENT
- "template": step-by-step instructions for an AI to repeat this strategy
- "principles": 2-3 general principles learned from this task (e.g. "Always check file exists before reading")

Return ONLY the JSON object."""

            try:
                response = llm_fn(
                    [{"role": "user", "content": prompt}],
                    max_tokens=300,
                )
                text = response.strip()
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    pattern = json.loads(text[start:end])
                    if isinstance(pattern, dict) and "name" in pattern:
                        return pattern
            except Exception as e:
                logger.warning("LLM pattern extraction failed: %s", e)

        # Fallback: basic pattern
        return {
            "name": f"Use {' → '.join(tools[:3])}",
            "description": f"Task pattern using {', '.join(tools)}",
            "category": _categorize_tools(tools),
            "triggers": _extract_triggers_from_request(record.get("user_request", "")),
            "template": None,
        }

    def learn_from_task(
        self,
        user_request: str,
        tools_used: list[str],
        success: bool,
        duration_sec: float = 0,
        output_summary: str = "",
        llm_fn=None,
    ) -> Optional[Skill]:
        """
        Full learning pipeline: record task → extract pattern → create/update skill.

        Returns the created/updated Skill, or None if nothing was learned.
        """
        # Record the task
        record = self.record_task(
            user_request=user_request,
            tools_used=tools_used,
            success=success,
            duration_sec=duration_sec,
            output_summary=output_summary,
        )

        # Only learn from successful tasks
        if not success:
            return None

        # Extract pattern
        pattern = self.extract_pattern(record.to_dict(), llm_fn=llm_fn)
        if not pattern:
            return None

        # Check if a similar skill already exists
        existing = self._find_similar_skill(pattern.get("name", ""), pattern.get("triggers", []))
        if existing:
            # Update existing skill
            existing.success_count += 1
            existing.last_used = datetime.now().isoformat()
            # Merge triggers
            for t in pattern.get("triggers", []):
                if t not in existing.triggers:
                    existing.triggers.append(t)
            self._save()
            logger.info("Updated skill %s: %s (successes: %d)", existing.skill_id, existing.name, existing.success_count)
            return existing

        # Create new skill
        self._skill_counter += 1
        skill = Skill(
            skill_id=f"s{self._skill_counter}",
            name=pattern.get("name", f"Pattern {self._skill_counter}"),
            description=pattern.get("description", ""),
            category=pattern.get("category", "general"),
            tool_sequence=tools_used,
            template=pattern.get("template"),
            triggers=pattern.get("triggers", []),
            examples=[{
                "request": _sanitize(user_request[:100]),
                "tools": tools_used,
                "duration": duration_sec,
            }],
        )
        self._skills.append(skill)
        self._save()
        logger.info("Created skill %s: %s", skill.skill_id, skill.name)
        return skill

    def _find_similar_skill(self, name: str, triggers: list[str]) -> Optional[Skill]:
        """Find an existing skill with similar name or triggers."""
        name_lower = name.lower()
        for skill in self._skills:
            if skill.name.lower() == name_lower:
                return skill
            # Match by trigger overlap — require 2+ matches to avoid false positives
            if triggers and skill.triggers:
                overlap = set(t.lower() for t in triggers) & set(t.lower() for t in skill.triggers)
                if len(overlap) >= 2:
                    return skill
        return None

    # --- Skill Retrieval ---

    def get_relevant_skills(self, user_message: str, top_k: int = 3) -> list[Skill]:
        """Find skills relevant to a user message."""
        msg_lower = user_message.lower()
        msg_words = set(re.findall(r'\w+', msg_lower))

        scored = []
        for skill in self._skills:
            # Calculate relevance score
            trigger_match = 0
            for t in skill.triggers:
                if t.lower() in msg_lower:
                    trigger_match += 2
                elif any(w in t.lower() for w in msg_words):
                    trigger_match += 1

            if trigger_match > 0:
                final_score = trigger_match * skill.score
                scored.append((final_score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    def get_skill(self, skill_id: str) -> Optional[Skill]:
        for s in self._skills:
            if s.skill_id == skill_id:
                return s
        return None

    def get_all_skills(self) -> list[Skill]:
        """Get all skills sorted by score."""
        return sorted(self._skills, key=lambda s: s.score, reverse=True)

    def get_skills_by_category(self, category: str) -> list[Skill]:
        return [s for s in self._skills if s.category == category]

    def delete_skill(self, skill_id: str) -> bool:
        before = len(self._skills)
        self._skills = [s for s in self._skills if s.skill_id != skill_id]
        if len(self._skills) < before:
            self._save()
            return True
        return False

    def record_failure(self, skill_id: str) -> None:
        """Record that a skill failed (decreases success rate)."""
        for s in self._skills:
            if s.skill_id == skill_id:
                s.fail_count += 1
                self._save()
                return

    # --- Statistics ---

    def get_stats(self) -> dict:
        """Get learning statistics."""
        total_records = len(self._records)
        successful = sum(1 for r in self._records if r.get("success"))
        return {
            "total_tasks": total_records,
            "successful_tasks": successful,
            "success_rate": round(successful / total_records * 100, 1) if total_records > 0 else 0,
            "total_skills": len(self._skills),
            "categories": list(set(s.category for s in self._skills)),
        }

    def export_for_prompt(self) -> str:
        """Export top skills as context for LLM prompt."""
        top_skills = self.get_all_skills()[:5]
        if not top_skills:
            return ""

        lines = ["[LEARNED SKILLS — apply these patterns when relevant]"]
        for s in top_skills:
            tools_str = " → ".join(s.tool_sequence) if s.tool_sequence else "none"
            lines.append(f"- {s.name}: {s.description} (tools: {tools_str}, success: {s.success_rate}%)")
            if s.template:
                lines.append(f"  Template: {s.template}")
        return "\n".join(lines)

    def get_summary(self) -> str:
        """Human-readable summary of learned skills."""
        stats = self.get_stats()
        lines = [
            f"🧠 *Learning Summary*",
            f"Tasks: {stats['total_tasks']} ({stats['success_rate']}% success)",
            f"Skills: {stats['total_skills']}",
            f"Categories: {', '.join(stats['categories']) or 'none'}",
        ]

        skills = self.get_all_skills()
        if skills:
            lines.append("\n*Top Skills:*")
            for s in skills[:8]:
                lines.append(
                    f"  📚 {s.skill_id}: {s.name}\n"
                    f"     {s.description[:60]}\n"
                    f"     Tools: {' → '.join(s.tool_sequence[:3])}\n"
                    f"     Success: {s.success_rate}% ({s.success_count} uses)"
                )

        return "\n".join(lines)


# --- Helpers ---

def _sanitize(text: str) -> str:
    """Remove potentially sensitive data from text."""
    import re
    # Remove email addresses
    text = re.sub(r'\S+@\S+\.\S+', '[email]', text)
    # Remove potential API keys (long alphanumeric strings)
    text = re.sub(r'\b[A-Za-z0-9_-]{20,}\b', '[key]', text)
    # Remove potential passwords
    text = re.sub(r'(?i)(password|passwd|pwd|secret|token)\s*[=:]\s*\S+', r'\1=[redacted]', text)
    return text


def _categorize_tools(tools: list[str]) -> str:
    """Categorize based on tools used."""
    tool_set = set(tools)
    if tool_set & {"code_execute", "shell"}:
        return "coding"
    if tool_set & {"web_search", "browse", "google_search"}:
        return "research"
    if tool_set & {"file_read", "file_write", "file_list"}:
        return "file_ops"
    if tool_set & {"convert"}:
        return "conversion"
    if tool_set & {"ppt"}:
        return "presentation"
    return "general"


def _extract_triggers_from_request(request: str) -> list[str]:
    """Extract keyword triggers from a user request."""
    # Common action keywords
    action_words = []
    lower = request.lower()
    patterns = [
        (r'\b(search|find|look up)\b', 'search'),
        (r'\b(read|open|show|display)\b', 'file_read'),
        (r'\b(write|create|save|generate)\b', 'file_write'),
        (r'\b(convert|transform|change)\b', 'convert'),
        (r'\b(execute|run|install)\b', 'shell'),
        (r'\b(browse|visit|fetch)\b', 'browse'),
        (r'\b(ppt|presentation|slides)\b', 'ppt'),
    ]
    for regex, trigger in patterns:
        if re.search(regex, lower):
            action_words.append(trigger)

    # Add content keywords (nouns)
    words = re.findall(r'\b[a-zA-Z]{3,}\b', lower)
    content_words = [w for w in words if w not in {
        'the', 'and', 'for', 'with', 'this', 'that', 'from', 'have', 'your',
        'please', 'want', 'need', 'make', 'give', 'show', 'find', 'help',
    }][:3]
    action_words.extend(content_words)

    return action_words[:5]
