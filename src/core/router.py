"""
Intent Router for Hermes-OpenManus multi-agent system.

Classifies incoming user requests into three tiers:
  - simple_chat   → direct LLM response (fast path)
  - complex_task  → single-agent executor with tool use
  - multi_step    → coordinator distributes across agents

Uses a two-stage approach:
  1. Fast keyword / heuristic matching (no LLM call needed)
  2. LLM classification fallback when heuristics are uncertain
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class Intent(Enum):
    """High-level intent categories."""
    SIMPLE_CHAT = "simple_chat"
    COMPLEX_TASK = "complex_task"
    MULTI_STEP = "multi_step"


@dataclass(frozen=True)
class RoutingResult:
    """Immutable result returned by the router."""
    intent: Intent
    confidence: float  # 0.0 – 1.0
    matched_keywords: list[str] = field(default_factory=list)
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Keyword rules  (lower-case)
# ---------------------------------------------------------------------------

# Strong indicators that a real-world *task* is requested (tools needed).
_TASK_KEYWORDS: list[tuple[str, Intent]] = [
    # multi-step / orchestration
    ("and then", Intent.MULTI_STEP),
    ("after that", Intent.MULTI_STEP),
    ("first … then", Intent.MULTI_STEP),
    ("step by step", Intent.MULTI_STEP),
    ("build a project", Intent.MULTI_STEP),
    ("full stack", Intent.MULTI_STEP),
    ("set up and deploy", Intent.MULTI_STEP),
    ("research and write", Intent.MULTI_STEP),

    # single-agent executor
    ("run the command", Intent.COMPLEX_TASK),
    ("execute", Intent.COMPLEX_TASK),
    ("install", Intent.COMPLEX_TASK),
    ("create a file", Intent.COMPLEX_TASK),
    ("write a script", Intent.COMPLEX_TASK),
    ("search the web", Intent.COMPLEX_TASK),
    ("open the browser", Intent.COMPLEX_TASK),
    ("deploy", Intent.COMPLEX_TASK),
    ("debug", Intent.COMPLEX_TASK),
    ("fix this bug", Intent.COMPLEX_TASK),
    ("compile", Intent.COMPLEX_TASK),
    ("build", Intent.COMPLEX_TASK),
    ("test", Intent.COMPLEX_TASK),
    ("clone the repo", Intent.COMPLEX_TASK),
    ("git clone", Intent.COMPLEX_TASK),
    ("pip install", Intent.COMPLEX_TASK),
    ("npm install", Intent.COMPLEX_TASK),
    ("docker", Intent.COMPLEX_TASK),
]

# Indicators for simple chat (no tool needed).
_CHAT_KEYWORDS: list[str] = [
    "hello",
    "hi",
    "hey",
    "thanks",
    "thank you",
    "how are you",
    "who are you",
    "what can you do",
    "tell me a joke",
    "what is",
    "define",
    "explain",
    "meaning of",
]


# ---------------------------------------------------------------------------
# LLM classification prompt
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = """You are an intent classifier for a multi-agent AI assistant.
Given a user message, classify it as one of:
  - simple_chat   : casual conversation, questions, explanations, no tools needed
  - complex_task  : a single task requiring tool use (file ops, shell, browser, search)
  - multi_step    : a complex project requiring multiple coordinated steps

Return ONLY a JSON object:
{"intent": "<simple_chat|complex_task|multi_step>", "reasoning": "<one sentence>"}"""


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class IntentRouter:
    """Classify user messages and route them to the correct handler."""

    def __init__(
        self,
        *,
        llm_fn: Optional[Callable[[str, str], str]] = None,
        keyword_threshold: float = 0.75,
    ) -> None:
        """
        Parameters
        ----------
        llm_fn:
            ``system_prompt, user_prompt → assistant_text``.
            When *None*, only keyword heuristics are used.
        keyword_threshold:
            Minimum heuristic confidence before we trust the keyword match
            (avoids false positives on ambiguous messages).
        """
        self._llm_fn = llm_fn
        self._keyword_threshold = keyword_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, user_message: str) -> RoutingResult:
        """Classify *user_message* and return a :class:`RoutingResult`."""
        heuristic = self._heuristic_match(user_message)
        if heuristic is not None:
            return heuristic

        # Fall back to LLM classification
        if self._llm_fn is not None:
            return self._llm_classify(user_message)

        # No LLM available – default to COMPLEX_TASK (safe default)
        logger.warning("No LLM configured; defaulting to COMPLEX_TASK")
        return RoutingResult(
            intent=Intent.COMPLEX_TASK,
            confidence=0.5,
            reasoning="No LLM available for classification",
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _heuristic_match(self, text: str) -> Optional[RoutingResult]:
        """Return a confident result or *None* if uncertain."""
        lower = text.lower().strip()
        matches: list[tuple[Intent, str]] = []

        for pattern, intent in _TASK_KEYWORDS:
            if pattern in lower:
                matches.append((intent, pattern))

        if len(matches) >= 2:
            # Multiple task keywords → high confidence multi_step
            return RoutingResult(
                intent=Intent.MULTI_STEP,
                confidence=min(0.95, 0.6 + 0.15 * len(matches)),
                matched_keywords=[m[1] for m in matches],
            )

        if len(matches) == 1:
            intent, kw = matches[0]
            conf = 0.82
            if intent == Intent.COMPLEX_TASK and len(lower.split()) < 5:
                conf = 0.55  # very short task messages are ambiguous
            if conf >= self._keyword_threshold:
                return RoutingResult(
                    intent=intent,
                    confidence=conf,
                    matched_keywords=[kw],
                )

        # Check for simple chat
        chat_hits = [kw for kw in _CHAT_KEYWORDS if kw in lower]
        if chat_hits and not matches:
            return RoutingResult(
                intent=Intent.SIMPLE_CHAT,
                confidence=min(0.9, 0.6 + 0.1 * len(chat_hits)),
                matched_keywords=chat_hits,
            )

        return None  # uncertain → escalate to LLM

    def _llm_classify(self, user_message: str) -> RoutingResult:
        """Ask the LLM to classify the intent."""
        assert self._llm_fn is not None
        try:
            raw = self._llm_fn(_CLASSIFY_SYSTEM, user_message)
            return self._parse_llm_response(raw)
        except Exception as exc:
            logger.error("LLM classification failed: %s", exc)
            return RoutingResult(
                intent=Intent.COMPLEX_TASK,
                confidence=0.5,
                reasoning=f"LLM error: {exc}",
            )

    def _parse_llm_response(self, raw: str) -> RoutingResult:
        """Parse the JSON the LLM returned."""
        import json

        # Try to extract a JSON object from the text
        match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
        if not match:
            logger.warning("No JSON found in LLM response: %s", raw)
            return RoutingResult(
                intent=Intent.COMPLEX_TASK,
                confidence=0.5,
                reasoning="Could not parse LLM output",
            )

        obj = json.loads(match.group())
        intent_str = obj.get("intent", "complex_task")
        try:
            intent = Intent(intent_str)
        except ValueError:
            intent = Intent.COMPLEX_TASK

        return RoutingResult(
            intent=intent,
            confidence=0.7,
            reasoning=obj.get("reasoning", ""),
        )
