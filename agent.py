"""
Hermes Agent — core agent loop with tool calling.

Uses OpenAI-compatible API (Xiaomi MiMo) for LLM.
Tools are OpenManus-style (shell, file, browser, search, convert, ppt).
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Hermes — an AI assistant with a full VPS toolchain.
You can execute shell commands, browse the web, convert files, generate PPTs, and manage files.

When the user asks you to DO something (run commands, create files, search, convert, etc.),
you MUST use tools. Respond with a JSON tool call:

{"tool": "tool_name", "args": {"arg1": "value1", ...}}

Available tools:
- shell: Execute shell commands. Args: {command: str}
- file_read: Read a file. Args: {path: str}
- file_write: Write to /tmp. Args: {path: str, content: str}
- file_list: List /tmp. Args: {path?: str}
- browse: Fetch webpage. Args: {url: str}
- search: Web search. Args: {query: str}
- convert: Convert files. Args: {file_path: str, target_fmt: str}
- ppt: Generate PPT. Args: {content: str}

You can chain multiple tool calls. For each tool call, respond with ONLY the JSON.
After getting tool results, you can make another tool call or give a final text response.

When done with tools, give a clear text response to the user.
Reply in the user's language. Be concise. Use markdown when helpful.

IMPORTANT: Only use tools when the user asks you to DO something.
For simple questions and chat, just respond directly without tools."""


class HermesAgent:
    """
    Agent loop with tool calling.

    Flow:
    1. User message → LLM (with tool definitions)
    2. LLM returns tool call → execute tool → send result back to LLM
    3. Repeat until LLM gives final text response
    """

    def __init__(
        self,
        api_keys: list[str],
        api_base: str = "https://api.xiaomimimo.com/v1",
        model: str = "mimo-v2.5",
        max_tool_rounds: int = 10,
        timeout: int = 120,
    ):
        self.api_keys = api_keys
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_tool_rounds = max(1, min(max_tool_rounds, 10))
        self.timeout = timeout
        self._key_idx = 0

        # Per-chat history
        self._history: dict[int, list[dict]] = {}
        self._max_history = 24

        # Max chars for tool output injected into messages
        self._max_tool_output = 3000

        logger.info(
            "HermesAgent initialized: model=%s, keys=%d, base=%s",
            model, len(api_keys), api_base,
        )

    def _next_key(self) -> str:
        key = self.api_keys[self._key_idx % len(self.api_keys)]
        self._key_idx += 1
        return key

    def _chat(self, messages: list[dict], max_tokens: int = 800, temperature: float = 0.3) -> str:
        """Send chat completion request to LLM with key rotation and retry."""
        last_error = None
        for _ in range(len(self.api_keys)):
            key = self._next_key()
            payload = json.dumps({
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }).encode()
            req = urllib.request.Request(
                f"{self.api_base}/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read())
                    # Defensive access
                    choices = result.get("choices")
                    if not choices or not isinstance(choices, list):
                        last_error = "Empty choices in response"
                        continue
                    msg = choices[0].get("message", {})
                    content = msg.get("content", "")
                    if not content:
                        last_error = "Empty content in response"
                        continue
                    return content.strip()
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    logger.warning("Key invalid (401), rotating...")
                    last_error = f"HTTP 401"
                    continue
                last_error = f"HTTP {e.code}: {e.reason}"
                break
            except Exception as e:
                last_error = str(e)[:200]
                break

        logger.error("LLM error: %s", last_error)
        return f"⚠️ LLM error: {last_error}"

    def _llm_fn(self, messages: list[dict], max_tokens: int = 800) -> str:
        """LLM call wrapper for tools that need it (e.g. PPT)."""
        return self._chat(messages, max_tokens=max_tokens)

    def _parse_tool_call(self, text: str) -> Optional[dict]:
        """Extract a JSON tool call from LLM response."""
        text = text.strip()

        # Quick check — must contain "tool" key
        if '"tool"' not in text:
            return None

        # Try to find JSON object using bracket matching
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        if isinstance(obj, dict) and "tool" in obj:
                            # Validate args
                            args = obj.get("args", {})
                            if not isinstance(args, dict):
                                obj["args"] = {}
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        return None

    def _is_error_response(self, text: str) -> bool:
        """Check if response is an error (should not be saved to history)."""
        return text.startswith("⚠️ LLM error:")

    def _truncate_tool_output(self, output: str) -> str:
        """Truncate tool output to prevent message explosion."""
        if len(output) > self._max_tool_output:
            return output[:self._max_tool_output] + "\n... (truncated)"
        return output

    def process(self, chat_id: int, user_message: str) -> str:
        """
        Process a user message through the agent loop.

        Returns the final text response.
        """
        # Initialize history for this chat
        if chat_id not in self._history:
            self._history[chat_id] = []

        # Add user message
        self._history[chat_id].append({"role": "user", "content": user_message})

        # Trim history (keep pairs intact)
        if len(self._history[chat_id]) > self._max_history:
            # Keep even number of messages to maintain user/assistant pairs
            trim_to = self._max_history - (self._max_history % 2)
            self._history[chat_id] = self._history[chat_id][-trim_to:]

        # Build messages for LLM
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self._history[chat_id])

        # Agent loop — allow multiple tool rounds
        response = ""
        for round_num in range(self.max_tool_rounds):
            response = self._chat(messages)

            # Don't process error responses as tool calls
            if self._is_error_response(response):
                break

            # Check if LLM wants to use a tool
            tool_call = self._parse_tool_call(response)
            if tool_call:
                tool_name = str(tool_call.get("tool", ""))
                tool_args = tool_call.get("args", {})

                if not tool_name:
                    break

                logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_args, default=str)[:200])

                # Execute the tool
                result = execute_tool(tool_name, tool_args, llm_fn=self._llm_fn)
                tool_output = self._truncate_tool_output(result.get("output", ""))

                # Add tool call and result to messages (not history — these are transient)
                messages.append({"role": "assistant", "content": response})
                result_text = f"Tool result ({tool_name}):\n{tool_output}"
                if result.get("file"):
                    result_text += f"\nFile: {result['file']}"
                messages.append({"role": "user", "content": result_text})

                continue

            # No tool call — this is the final response
            break

        # Save to history (only if no error)
        if not self._is_error_response(response):
            self._history[chat_id].append({"role": "assistant", "content": response})

        return response or "⚠️ No response from AI."

    def clear_history(self, chat_id: int) -> None:
        """Clear conversation history for a chat."""
        self._history.pop(chat_id, None)

    def cleanup_old_chats(self, max_chats: int = 100) -> int:
        """Remove oldest chat histories if too many. Returns number removed."""
        if len(self._history) <= max_chats:
            return 0
        # Remove oldest half
        to_remove = len(self._history) - max_chats
        sorted_ids = sorted(self._history.keys())
        for chat_id in sorted_ids[:to_remove]:
            del self._history[chat_id]
        return to_remove

    def chat_only(self, chat_id: int, user_message: str) -> str:
        """Simple chat without tool calling."""
        if chat_id not in self._history:
            self._history[chat_id] = []

        self._history[chat_id].append({"role": "user", "content": user_message})

        if len(self._history[chat_id]) > self._max_history:
            trim_to = self._max_history - (self._max_history % 2)
            self._history[chat_id] = self._history[chat_id][-trim_to:]

        # Use simpler prompt for chat-only mode
        messages = [
            {"role": "system", "content": "You are Hermes, a helpful AI assistant. Reply in the user's language. Be concise."},
        ]
        messages.extend(self._history[chat_id])

        response = self._chat(messages)

        if not self._is_error_response(response):
            self._history[chat_id].append({"role": "assistant", "content": response})

        return response or "⚠️ No response from AI."
