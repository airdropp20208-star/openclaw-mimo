"""Telegram bot — main polling loop and message routing.

Orchestrates all modules: LLM client, memory, skills, and command handlers.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from ..llm.client import LLMClient
from ..memory.context import ConversationContext
from ..memory.skills import SkillManager
from . import handlers

logger = logging.getLogger(__name__)

# System prompt for the AI chat
SYSTEM_PROMPT = """You are PhantomBot v8 — an AI assistant with a full VPS toolchain.
You can execute shell commands, browse the web, convert files, generate images, and use MCP tools.
Reply in the user's language. Be concise. Use markdown when helpful."""


class TelegramBot:
    """Telegram bot with long-polling and modular command routing.

    Parameters
    ----------
    bot_token:
        Telegram Bot API token.
    llm:
        Configured :class:`LLMClient` instance.
    context:
        Conversation history manager.
    skills:
        Persistent skill storage.
    allowed_chats:
        Optional set of allowed chat ids. Empty = allow all.
    rate_limit:
        Minimum seconds between responses per chat.
    system_prompt:
        System prompt for AI chat.
    memory_file:
        Path to the JSON memory file for /remember.
    """

    def __init__(
        self,
        bot_token: str,
        llm: LLMClient,
        context: Optional[ConversationContext] = None,
        skills: Optional[SkillManager] = None,
        allowed_chats: Optional[set[int]] = None,
        rate_limit: float = 2.0,
        system_prompt: str = SYSTEM_PROMPT,
        memory_file: str = "/tmp/phantom_memory.json",
    ) -> None:
        if not bot_token:
            raise ValueError("BOT_TOKEN is required")

        self.bot_token: str = bot_token
        self.llm: LLMClient = llm
        self.context: ConversationContext = context or ConversationContext(
            max_messages=24, system_prompt=system_prompt
        )
        self.skills: SkillManager = skills or SkillManager()
        self.allowed_chats: set[int] = allowed_chats or set()
        self.rate_limit: float = rate_limit
        self.system_prompt: str = system_prompt
        self.memory_file: str = memory_file

        self._tg_base: str = f"https://api.telegram.org/bot{bot_token}"
        self._last_response: dict[int, float] = {}
        self._offset: int = 0

        # Command → handler mapping
        self._command_handlers: dict[str, Any] = {
            "/start": handlers.handle_start,
            "/clear": handlers.handle_clear,
            "/reset": handlers.handle_clear,
            "/search": handlers.handle_search,
            "/convert": handlers.handle_convert,
            "/browse": handlers.handle_browse,
            "/analyze": handlers.handle_analyze,
            "/ppt": handlers.handle_ppt,
            "/mcp": handlers.handle_mcp,
            "/remember": handlers.handle_remember,
            "/recall": handlers.handle_recall,
            "/skills": handlers.handle_skills,
        }

        logger.info("TelegramBot initialised (rate_limit=%.1fs)", rate_limit)

    # ------------------------------------------------------------------
    # Telegram API helpers
    # ------------------------------------------------------------------

    def tg_api(self, method: str, data: Optional[dict] = None, timeout: int = 10) -> Any:
        """Call a Telegram Bot API method."""
        url = f"{self._tg_base}/{method}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body)
        if body:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            logger.exception("Telegram API error: %s", method)
            raise

    def send_message(self, chat_id: int, text: str) -> None:
        """Send a text message, splitting if over Telegram's 4096 char limit."""
        try:
            if len(text) <= 4096:
                self.tg_api("sendMessage", {"chat_id": chat_id, "text": text})
            else:
                for i in range(0, len(text), 4096):
                    self.tg_api("sendMessage", {"chat_id": chat_id, "text": text[i : i + 4096]})
        except Exception as exc:
            logger.error("Failed to send message to %d: %s", chat_id, exc)

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        """Send a chat action (typing, uploading_photo, etc.)."""
        try:
            self.tg_api("sendChatAction", {"chat_id": chat_id, "action": action})
        except Exception:
            pass  # Non-critical

    def send_document(self, chat_id: int, file_path: str, caption: str = "") -> None:
        """Upload a file as a document using multipart form data."""
        try:
            mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            boundary = "----PhantomBotV8"
            fname = os.path.basename(file_path)
            with open(file_path, "rb") as f:
                fdata = f.read()

            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="document"; filename="{fname}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode() + fdata + f"\r\n--{boundary}--\r\n".encode()

            req = urllib.request.Request(f"{self._tg_base}/sendDocument", data=body)
            req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            logger.error("Failed to send document %s: %s", file_path, exc)
            raise

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def load_memory(self) -> dict[str, Any]:
        """Load the /remember memory file."""
        try:
            with open(self.memory_file, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_memory(self, data: dict[str, Any]) -> None:
        """Persist the /remember memory file."""
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Access control & rate limiting
    # ------------------------------------------------------------------

    def _is_allowed(self, chat_id: int) -> bool:
        """Check if a chat is allowed to use the bot."""
        if not self.allowed_chats:
            return True
        return chat_id in self.allowed_chats

    def _rate_ok(self, chat_id: int) -> bool:
        """Check and enforce rate limiting for a chat."""
        now = time.time()
        last = self._last_response.get(chat_id, 0.0)
        if now - last < self.rate_limit:
            return False
        self._last_response[chat_id] = now
        return True

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------

    def _dispatch(self, chat_id: int, text: str) -> None:
        """Route a text message to the appropriate handler or AI chat."""
        lower = text.lower().strip()

        # Check command handlers
        for prefix, handler in self._command_handlers.items():
            if lower.startswith(prefix):
                try:
                    handler(self, chat_id, text)
                except Exception:
                    logger.exception("Handler error for %s", prefix)
                    self.send_message(chat_id, f"⚠️ Error handling {prefix}")
                return

        # Shell command prefix
        if lower.startswith("!cmd "):
            handlers.handle_cmd(self, chat_id, text)
            return
        if lower.startswith("!upload "):
            handlers.handle_upload(self, chat_id, text)
            return
        if lower == "!scan":
            handlers.handle_scan(self, chat_id, text)
            return
        if lower == "!ps":
            output = handlers.run_cmd("ps aux --sort=-%mem | head -15")
            self.send_message(chat_id, output)
            return

        # Smart execution: detect task-oriented keywords
        task_keywords = [
            "convert", "chuyen", "nen", "compress", "extract", "resize", "crop", "rotate",
            "merge", "split", "create", "generate", "make", "build", "compile", "download",
            "tai", "fetch", "parse", "edit", "modify", "video", "audio", "image", "anh",
            "file", "pdf", "mp3", "mp4", "png", "jpg", "cai", "install",
        ]
        if any(kw in lower for kw in task_keywords):
            self.send_message(chat_id, "Analysing...")
            self.send_chat_action(chat_id, "typing")
            try:
                plan = self.llm.simple_plan(text)
                cmd = plan.get("cmd", text)
                needs = plan.get("needs", [])
                fix_cmd = plan.get("fix_cmd", "")
                parts: list[str] = []
                if needs and fix_cmd:
                    parts.append(f"Installing: {', '.join(needs)}")
                    parts.append(handlers.run_cmd(fix_cmd, timeout=120)[:200])
                parts.append(f"$ {cmd}")
                output = handlers.run_cmd(cmd)
                # Auto-fix on common errors
                error_markers = ["not found", "No such file", "Permission denied", "command not found", "ModuleNotFoundError"]
                if any(e.lower() in output.lower() for e in error_markers):
                    parts.append("Auto-fixing...")
                    try:
                        fix = self.llm.structured_output(
                            "Fix the failed command.",
                            f"Failed: $ {cmd}\nError: {output[:500]}\nJSON: {{\"fix_cmd\":\"fix\",\"retry_cmd\":\"retry\"}}",
                        )
                        if fix.get("fix_cmd"):
                            handlers.run_cmd(fix["fix_cmd"], timeout=120)
                        output = handlers.run_cmd(fix.get("retry_cmd", cmd))
                    except Exception:
                        pass
                parts.append(output)
                self.send_message(chat_id, "\n".join(parts))
            except Exception:
                logger.exception("Smart execution failed")
                self.send_message(chat_id, handlers.run_cmd(text))
            return

        # Default: AI chat
        self.send_chat_action(chat_id, "typing")
        try:
            self.context.add_message(chat_id, "user", text)
            messages = self.context.get_history(chat_id)
            # Keep only the last 12 messages for API efficiency
            messages = messages[-12:]
            resp = self.llm.chat(messages, max_tokens=800, temperature=0.3)
            self.context.add_message(chat_id, "assistant", resp)
            self.send_message(chat_id, resp)
        except Exception:
            logger.exception("AI chat error")
            self.send_message(chat_id, "⚠️ AI error, try again.")

    # ------------------------------------------------------------------
    # Main polling loop
    # ------------------------------------------------------------------

    def _initialise_offset(self) -> None:
        """Get the current update offset to avoid processing old messages."""
        try:
            r = self.tg_api("getUpdates", {"offset": -1, "timeout": 1}, timeout=5)
            if r.get("result"):
                self._offset = r["result"][-1]["update_id"] + 1
            else:
                self._offset = 0
        except Exception:
            self._offset = 0
            logger.warning("Could not initialise offset, starting from 0")

    def poll_once(self) -> bool:
        """Poll for updates once and process them.

        Returns ``True`` if updates were received, ``False`` otherwise.
        """
        try:
            result = self.tg_api(
                "getUpdates",
                {"offset": self._offset, "timeout": 30},
                timeout=35,
            )
            updates = result.get("result", [])
            for update in updates:
                self._offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")

                # Handle documents
                if msg.get("document"):
                    if not self._is_allowed(chat_id):
                        continue
                    try:
                        handlers.handle_document(self, chat_id, msg["document"])
                    except Exception:
                        logger.exception("Document handler error")
                    continue

                if not text or msg.get("from", {}).get("is_bot"):
                    continue
                if not self._is_allowed(chat_id):
                    continue
                if not self._rate_ok(chat_id):
                    continue

                logger.info("[%d] %s", chat_id, text[:80])
                self.send_chat_action(chat_id, "typing")

                try:
                    self._dispatch(chat_id, text)
                except Exception:
                    logger.exception("Dispatch error for [%d]", chat_id)

            return bool(updates)

        except urllib.error.URLError as exc:
            logger.warning("Network error during poll: %s", exc)
            time.sleep(5)
        except Exception as exc:
            logger.error("Poll error: %s", exc)
            time.sleep(5)
        return False

    def run(self) -> None:
        """Start the bot polling loop. Runs until interrupted."""
        logger.info("Starting TelegramBot polling loop...")
        self._initialise_offset()
        logger.info("Bot running. Press Ctrl+C to stop.")

        while True:
            try:
                self.poll_once()
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception:
                logger.exception("Unexpected error in main loop")
                time.sleep(5)
