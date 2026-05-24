"""Per-chat conversation context with sliding window management.

Maintains an in-memory conversation history for each chat, with configurable
window size and optional persistence to disk.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Default role/content structure for messages
MessageDict = dict[str, str]


class ConversationContext:
    """Manages per-chat conversation history with a sliding window.

    Parameters
    ----------
    max_messages:
        Maximum number of messages to retain per chat (the "sliding window").
    system_prompt:
        Default system prompt prepended to every context when requested.
    persist_path:
        Optional file path to persist conversation history across restarts.
        If ``None``, history lives only in memory.
    """

    def __init__(
        self,
        max_messages: int = 24,
        system_prompt: str = "",
        persist_path: Optional[str | Path] = None,
    ) -> None:
        self.max_messages: int = max_messages
        self.system_prompt: str = system_prompt
        self.persist_path: Optional[Path] = Path(persist_path) if persist_path else None
        # chat_id → list[dict]
        self._history: OrderedDict[int, list[MessageDict]] = OrderedDict()
        if self.persist_path:
            self._load()
        logger.info(
            "ConversationContext initialised (max_messages=%d, persist=%s)",
            self.max_messages,
            self.persist_path,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load history from the persistence file if it exists."""
        if not self.persist_path or not self.persist_path.exists():
            return
        try:
            raw: dict[str, Any] = json.loads(
                self.persist_path.read_text(encoding="utf-8")
            )
            for chat_id_str, msgs in raw.items():
                self._history[int(chat_id_str)] = msgs
            logger.info("Loaded history for %d chat(s)", len(self._history))
        except Exception:
            logger.exception("Failed to load conversation history")

    def _save(self) -> None:
        """Persist current history to disk."""
        if not self.persist_path:
            return
        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {str(k): v for k, v in self._history.items()}
            self.persist_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save conversation history")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_message(self, chat_id: int, role: str, content: str) -> None:
        """Append a message to a chat's history, enforcing the sliding window.

        Parameters
        ----------
        chat_id:
            The Telegram chat id.
        role:
            ``"user"``, ``"assistant"``, or ``"system"``.
        content:
            The message body.
        """
        entry: MessageDict = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if chat_id not in self._history:
            self._history[chat_id] = []

        self._history[chat_id].append(entry)

        # Slide window: keep only the last max_messages messages
        if len(self._history[chat_id]) > self.max_messages:
            self._history[chat_id] = self._history[chat_id][-self.max_messages:]

        # Move to end (most recently active)
        self._history.move_to_end(chat_id)
        self._save()

    def get_history(
        self,
        chat_id: int,
        include_system: bool = True,
        max_messages: Optional[int] = None,
    ) -> list[MessageDict]:
        """Return the conversation history for *chat_id*.

        Parameters
        ----------
        chat_id:
            The Telegram chat id.
        include_system:
            If ``True``, prepend the system prompt as the first message.
        max_messages:
            Override the default window size for this call.
        """
        messages: list[MessageDict] = []
        if include_system and self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        history = self._history.get(chat_id, [])
        limit = max_messages or len(history)
        messages.extend(history[-limit:])
        return messages

    def clear(self, chat_id: Optional[int] = None) -> None:
        """Clear history for a specific chat, or all chats if *chat_id* is ``None``."""
        if chat_id is not None:
            self._history.pop(chat_id, None)
            logger.info("Cleared history for chat %d", chat_id)
        else:
            self._history.clear()
            logger.info("Cleared all conversation history")
        self._save()

    def get_summary(self, chat_id: int, max_chars: int = 1000) -> str:
        """Return a plain-text summary of the conversation so far.

        This produces a lightweight overview rather than an LLM-generated summary.
        It includes message counts and recent exchanges.
        """
        history = self._history.get(chat_id, [])
        if not history:
            return "No conversation history."

        lines: list[str] = []
        lines.append(f"Conversation with {len(history)} message(s).")
        lines.append("")

        # Show the last few exchanges (up to max_chars total)
        truncated = False
        recent: list[MessageDict] = []
        char_count = 0
        for msg in reversed(history):
            preview = f"[{msg['role']}] {msg['content'][:120]}"
            if char_count + len(preview) > max_chars:
                truncated = True
                break
            recent.append(msg)
            char_count += len(preview)

        recent.reverse()
        for msg in recent:
            role = msg["role"].upper()
            content = msg["content"][:200]
            lines.append(f"{role}: {content}")

        if truncated:
            lines.append("... (earlier messages omitted)")

        return "\n".join(lines)

    def get_last_user_message(self, chat_id: int) -> Optional[str]:
        """Return the content of the most recent user message, or ``None``."""
        history = self._history.get(chat_id, [])
        for msg in reversed(history):
            if msg["role"] == "user":
                return msg["content"]
        return None

    def get_message_count(self, chat_id: int) -> int:
        """Return the number of messages stored for *chat_id*."""
        return len(self._history.get(chat_id, []))

    def get_active_chat_ids(self) -> list[int]:
        """Return a list of chat ids with stored history."""
        return list(self._history.keys())
