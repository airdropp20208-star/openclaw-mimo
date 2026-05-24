"""LLM client for Xiaomi MiMo (OpenAI-compatible API).

Handles key rotation, retry with exponential backoff, streaming support,
and structured output parsing. Uses only stdlib (urllib) — no external deps.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """Wrapper for an OpenAI-compatible chat completions endpoint.

    Parameters
    ----------
    api_keys:
        List of API keys. The client rotates through them automatically.
    api_base:
        Base URL of the API (e.g. ``https://api.xiaomimimo.com/v1``).
    model:
        Model identifier (e.g. ``mimo-v2.5``).
    timeout:
        HTTP timeout in seconds.
    max_retries:
        Number of retry attempts per request (with exponential backoff).
    backoff_base:
        Base delay in seconds between retries.
    """

    def __init__(
        self,
        api_keys: list[str],
        api_base: str = "https://api.xiaomimimo.com/v1",
        model: str = "mimo-v2.5",
        timeout: int = 120,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        if not api_keys:
            raise ValueError("At least one API key is required")
        self.api_keys: list[str] = list(api_keys)
        self.api_base: str = api_base.rstrip("/")
        self.model: str = model
        self.timeout: int = timeout
        self.max_retries: int = max_retries
        self.backoff_base: float = backoff_base
        self._key_index: int = 0
        logger.info(
            "LLMClient initialised – model=%s, keys=%d, base=%s",
            self.model,
            len(self.api_keys),
            self.api_base,
        )

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def _next_key(self) -> str:
        """Return the next API key using round-robin rotation."""
        key = self.api_keys[self._key_index % len(self.api_keys)]
        self._key_index += 1
        return key

    def _all_keys(self) -> list[str]:
        """Return all keys starting from the current index."""
        n = len(self.api_keys)
        start = self._key_index % n
        return [self.api_keys[(start + i) % n] for i in range(n)]

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _build_request(
        self,
        path: str,
        payload: dict[str, Any],
        api_key: str,
    ) -> urllib.request.Request:
        """Build an ``urllib.request.Request`` for the completions endpoint."""
        url = f"{self.api_base}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        return req

    def _do_request(
        self,
        path: str,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> Any:
        """Execute the HTTP request with key rotation and retry logic.

        On 401 errors, the client automatically tries the next key.
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            key = self._next_key()
            try:
                req = self._build_request(path, payload, key)
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                if stream:
                    return resp
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code == 401:
                    logger.warning("Auth failed with key index %d (401), rotating", self._key_index)
                    # Try remaining keys
                    for remaining_key in self._all_keys():
                        try:
                            req2 = self._build_request(path, payload, remaining_key)
                            resp2 = urllib.request.urlopen(req2, timeout=self.timeout)
                            if stream:
                                return resp2
                            raw2 = resp2.read().decode("utf-8")
                            return json.loads(raw2)
                        except urllib.error.HTTPError:
                            continue
                logger.warning(
                    "Request failed (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                time.sleep(self.backoff_base * (2 ** attempt))
            except urllib.error.URLError as exc:
                last_error = exc
                logger.warning(
                    "Network error (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                time.sleep(self.backoff_base * (2 ** attempt))
            except Exception as exc:
                last_error = exc
                logger.error("Unexpected error: %s", exc)
                break

        raise ConnectionError(f"All retries exhausted: {last_error}")

    # ------------------------------------------------------------------
    # Streaming support
    # ------------------------------------------------------------------

    def _stream_request(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> Generator[str, None, None]:
        """Execute a streaming request, yielding content chunks."""
        key = self._next_key()
        payload_copy = dict(payload)
        payload_copy["stream"] = True
        try:
            req = self._build_request(path, payload_copy, key)
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            buffer = ""
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        try:
                            event = json.loads(line[6:])
                            delta = event.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except Exception:
            logger.exception("Streaming request failed")
            return

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request and return the assistant's reply.

        Parameters
        ----------
        messages:
            List of ``{"role": ..., "content": ...}`` dicts.
        max_tokens:
            Maximum tokens in the response.
        temperature:
            Sampling temperature.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        try:
            result = self._do_request("/chat/completions", payload)
            return result["choices"][0]["message"]["content"].strip()
        except (ConnectionError, KeyError, IndexError) as exc:
            logger.error("Chat request failed: %s", exc)
            return f"LLM error: {exc}"

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
        temperature: float = 0.3,
    ) -> Generator[str, None, None]:
        """Stream chat completion chunks as they arrive.

        Yields individual content strings.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        yield from self._stream_request("/chat/completions", payload)

    def structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
    ) -> dict[str, Any]:
        """Request structured JSON output and parse it.

        Attempts to extract valid JSON from the response even if wrapped
        in markdown code fences.
        """
        messages = [
            {"role": "system", "content": f"{system_prompt}\nReply ONLY with valid JSON."},
            {"role": "user", "content": user_prompt},
        ]
        raw = self.chat(messages, max_tokens=max_tokens, temperature=temperature)
        return self._parse_json_response(raw)

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any]:
        """Attempt to extract and parse JSON from a model response.

        Handles code-fenced and plain JSON output.
        """
        # Strip code fences
        cleaned = text.strip()
        for fence in ("```json", "```"):
            if fence in cleaned:
                parts = cleaned.split(fence, 1)
                if len(parts) > 1:
                    cleaned = parts[1].split("```")[0].strip()
                    break

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from response: %s", cleaned[:200])
            return {}

    def simple_plan(self, task_description: str) -> dict[str, Any]:
        """Request a simple execution plan for a task.

        Returns a dict with keys: ``cmd``, ``needs``, ``fix_cmd``.
        """
        prompt = (
            f"User wants: {task_description}\n"
            f'Reply JSON: {{"cmd": "shell command", "needs": [], "fix_cmd": ""}}'
        )
        return self.structured_output(
            system_prompt="Reply only with valid JSON.",
            user_prompt=prompt,
            max_tokens=250,
        )
