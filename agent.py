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
- file_write: Write to a file. Args: {path: str, content: str}
- file_list: List directory. Args: {path?: str}
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
        self.max_tool_rounds = max_tool_rounds
        self.timeout = timeout
        self._key_idx = 0

        # Per-chat history
        self._history: dict[int, list[dict]] = {}
        self._max_history = 24

        logger.info(
            "HermesAgent initialized: model=%s, keys=%d, base=%s",
            model, len(api_keys), api_base,
        )

    def _next_key(self) -> str:
        key = self.api_keys[self._key_idx % len(self.api_keys)]
        self._key_idx += 1
        return key

    def _chat(self, messages: list[dict], max_tokens: int = 800, temperature: float = 0.3) -> str:
        """Send chat completion request to LLM."""
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode()

        last_error = None
        for _ in range(len(self.api_keys)):
            key = self._next_key()
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
                    return result["choices"][0]["message"]["content"].strip()
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    logger.warning("Key invalid (401), rotating...")
                    last_error = f"HTTP 401"
                    continue
                last_error = f"HTTP {e.code}: {e.reason}"
                break
            except Exception as e:
                last_error = str(e)
                break

        return f"⚠️ LLM error: {last_error}"

    def _llm_fn(self, messages: list[dict], max_tokens: int = 800) -> str:
        """LLM call wrapper for tools that need it (e.g. PPT)."""
        return self._chat(messages, max_tokens=max_tokens)

    def _parse_tool_call(self, text: str) -> Optional[dict]:
        """Try to extract a JSON tool call from LLM response."""
        text = text.strip()
        # Try to find JSON object
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            if start == -1:
                continue
            # Find matching end
            depth = 0
            for i in range(start, len(text)):
                if text[i] == start_char:
                    depth += 1
                elif text[i] == end_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[start : i + 1])
                            if isinstance(obj, dict) and "tool" in obj:
                                return obj
                            if isinstance(obj, list):
                                # Multiple tool calls — return first
                                for item in obj:
                                    if isinstance(item, dict) and "tool" in item:
                                        return item
                        except json.JSONDecodeError:
                            pass
                        break
        return None

    def _is_tool_response(self, text: str) -> bool:
        """Check if the response looks like a tool call."""
        text = text.strip()
        return text.startswith("{") and '"tool"' in text

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

        # Trim history
        if len(self._history[chat_id]) > self._max_history:
            self._history[chat_id] = self._history[chat_id][-self._max_history:]

        # Build messages for LLM
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self._history[chat_id])

        # Agent loop — allow multiple tool rounds
        response = ""
        for round_num in range(self.max_tool_rounds):
            response = self._chat(messages)

            # Check if LLM wants to use a tool
            tool_call = self._parse_tool_call(response)
            if tool_call:
                tool_name = tool_call.get("tool", "")
                tool_args = tool_call.get("args", {})

                logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_args)[:200])

                # Execute the tool
                result = execute_tool(tool_name, tool_args, llm_fn=self._llm_fn)
                tool_output = result.get("output", "")

                # Add tool call and result to messages
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": f"Tool result ({tool_name}):\n{tool_output}\n\nContinue with next tool call or give final response.",
                })

                # If tool produced a file, note it
                if result.get("file"):
                    messages[-1]["content"] += f"\nFile: {result['file']}"

                continue

            # No tool call — this is the final response
            self._history[chat_id].append({"role": "assistant", "content": response})
            return response

        # Max rounds reached — return last response
        self._history[chat_id].append({"role": "assistant", "content": response})
        return response

    def clear_history(self, chat_id: int) -> None:
        """Clear conversation history for a chat."""
        self._history.pop(chat_id, None)

    def chat_only(self, chat_id: int, user_message: str) -> str:
        """Simple chat without tool calling."""
        if chat_id not in self._history:
            self._history[chat_id] = []

        self._history[chat_id].append({"role": "user", "content": user_message})

        if len(self._history[chat_id]) > self._max_history:
            self._history[chat_id] = self._history[chat_id][-self._max_history:]

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self._history[chat_id])

        response = self._chat(messages)
        self._history[chat_id].append({"role": "assistant", "content": response})
        return response
