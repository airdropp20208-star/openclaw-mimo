"""LLM client for Xiaomi MiMo (OpenAI-compatible API).

Handles key rotation, retry with exponential backoff, streaming support,
and structured output parsing. Self-contained — no external deps beyond stdlib.

Adapted from src/llm/client.py for the AI server context.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from collections import deque
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
        Global HTTP timeout in seconds.
    max_retries:
        Number of retry attempts per request (with exponential backoff).
    backoff_base:
        Base delay in seconds between retries.
    """

    def __init__(
        self,
        api_keys: list[str] | None = None,
        api_base: str | None = None,
        model: str | None = None,
        timeout: int = 120,
        max_retries: int = 3,
        backoff_base: float = 1.0,
    ) -> None:
        self.api_keys: list[str] = api_keys or self._env_keys()
        if not self.api_keys:
            raise ValueError(
                "No API keys provided. Set LLM_API_KEYS env var or pass api_keys."
            )
        self.api_base: str = (
            api_base or os.environ.get("LLM_API_BASE", "https://api.xiaomimimo.com/v1")
        ).rstrip("/")
        self.model: str = model or os.environ.get("LLM_MODEL", "mimo-v2.5")
        self.timeout: int = timeout
        self.max_retries: int = max_retries
        self.backoff_base: float = backoff_base
        self._key_index: int = 0
        self.fallback_message: str = (
            "⚠️ Service temporarily unavailable. Please try again shortly."
        )

        # Per-key state tracking
        self._key_failures: dict[str, int] = {}
        self._key_successes: dict[str, int] = {}
        self._last_key_error: dict[str, Optional[str]] = {}

        # Cache for graceful degradation
        self._cache: dict[str, Any] = {}
        self._cache_ttl: float = 300.0
        self._cache_timestamps: dict[str, float] = {}

        # Error tracking
        self._error_log: deque[tuple[float, str]] = deque(maxlen=200)
        self._total_requests: int = 0
        self._total_failures: int = 0

        logger.info(
            "LLMClient initialised – model=%s, keys=%d, base=%s",
            self.model,
            len(self.api_keys),
            self.api_base,
        )

    @staticmethod
    def _env_keys() -> list[str]:
        """Read API keys from LLM_API_KEYS env var (comma-separated)."""
        raw = os.environ.get("LLM_API_KEYS", "")
        return [k.strip() for k in raw.split(",") if k.strip()]

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

    def _record_key_failure(self, api_key: str, error: str) -> None:
        suffix = api_key[-8:]
        self._key_failures[suffix] = self._key_failures.get(suffix, 0) + 1
        self._last_key_error[suffix] = error

    def _record_key_success(self, api_key: str) -> None:
        suffix = api_key[-8:]
        self._key_successes[suffix] = self._key_successes.get(suffix, 0) + 1
        self._last_key_error[suffix] = None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _simple_hash(data: Any) -> str:
        try:
            s = json.dumps(data, sort_keys=True, default=str)
        except (TypeError, ValueError):
            s = str(data)
        h = 0
        for ch in s:
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        return format(h, "08x")

    def _cache_key(self, path: str, payload: dict[str, Any]) -> str:
        return f"{path}:{self._simple_hash(payload)}"

    def _get_cached(self, key: str) -> Optional[Any]:
        ts = self._cache_timestamps.get(key, 0)
        if time.time() - ts < self._cache_ttl and key in self._cache:
            return self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    def _clear_expired_cache(self) -> None:
        now = time.time()
        expired = [
            k for k, ts in self._cache_timestamps.items() if now - ts > self._cache_ttl
        ]
        for k in expired:
            self._cache.pop(k, None)
            self._cache_timestamps.pop(k, None)

    def _track_error(self, error: str) -> None:
        self._error_log.append((time.time(), error))
        self._total_failures += 1

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _build_request(
        self, path: str, payload: dict[str, Any], api_key: str
    ) -> urllib.request.Request:
        url = f"{self.api_base}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        return req

    def _do_request(
        self, path: str, payload: dict[str, Any]
    ) -> Any:
        """Execute the HTTP request with key rotation and retry logic."""
        self._total_requests += 1
        self._clear_expired_cache()

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            key = self._next_key()

            try:
                req = self._build_request(path, payload, key)
                resp = urllib.request.urlopen(req, timeout=self.timeout)
                raw = resp.read().decode("utf-8")
                result = json.loads(raw)

                self._record_key_success(key)
                cache_key = self._cache_key(path, payload)
                self._set_cached(cache_key, result)
                return result

            except Exception as exc:
                last_error = exc
                self._record_key_failure(key, str(exc))

                if isinstance(exc, urllib.error.HTTPError):
                    if exc.code == 401:
                        logger.warning(
                            "Auth failed with key index %d (401), rotating",
                            self._key_index,
                        )
                        for remaining_key in self._all_keys():
                            try:
                                req2 = self._build_request(path, payload, remaining_key)
                                resp2 = urllib.request.urlopen(req2, timeout=self.timeout)
                                raw2 = resp2.read().decode("utf-8")
                                result2 = json.loads(raw2)
                                self._record_key_success(remaining_key)
                                cache_key = self._cache_key(path, payload)
                                self._set_cached(cache_key, result2)
                                return result2
                            except urllib.error.HTTPError:
                                self._record_key_failure(remaining_key, "401")
                                continue
                    logger.warning(
                        "Request failed (attempt %d/%d): %s",
                        attempt + 1,
                        self.max_retries,
                        exc,
                    )
                    self._track_error(f"HTTP {exc.code}: {exc.reason}")
                elif isinstance(exc, urllib.error.URLError):
                    logger.warning(
                        "Network error (attempt %d/%d): %s",
                        attempt + 1,
                        self.max_retries,
                        exc,
                    )
                    self._track_error(f"URLError: {exc.reason}")
                else:
                    logger.error("Unexpected error: %s", exc)
                    self._track_error(f"Exception: {exc}")
                    break

                time.sleep(self.backoff_base * (2**attempt))

        # Try cache one more time as degradation
        cache_key = self._cache_key(path, payload)
        cached = self._get_cached(cache_key)
        if cached is not None:
            logger.warning("All retries failed — returning stale cache")
            return cached

        self._total_failures += 1
        raise ConnectionError(f"All retries exhausted: {last_error}")

    # ------------------------------------------------------------------
    # Streaming support
    # ------------------------------------------------------------------

    def _stream_request(
        self, path: str, payload: dict[str, Any]
    ) -> Generator[str, None, None]:
        """Execute a streaming request, yielding content chunks."""
        key = self._next_key()
        payload_copy = dict(payload)
        payload_copy["stream"] = True
        try:
            req = self._build_request(path, payload_copy, key)
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            self._record_key_success(key)
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
            self._record_key_failure(key, "Stream failed")
            self._track_error("Stream failed")
            yield self.fallback_message

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request and return the assistant's reply."""
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
            return self.fallback_message

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
        temperature: float = 0.3,
    ) -> Generator[str, None, None]:
        """Stream chat completion chunks as they arrive."""
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
        """Request structured JSON output and parse it."""
        messages = [
            {"role": "system", "content": f"{system_prompt}\nReply ONLY with valid JSON."},
            {"role": "user", "content": user_prompt},
        ]
        raw = self.chat(messages, max_tokens=max_tokens, temperature=temperature)
        return self._parse_json_response(raw)

    @staticmethod
    def _parse_json_response(text: str) -> dict[str, Any]:
        """Attempt to extract and parse JSON from a model response."""
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
        """Request a simple execution plan for a task."""
        prompt = (
            f"User wants: {task_description}\n"
            f'Reply JSON: {{"cmd": "shell command", "needs": [], "fix_cmd": ""}}'
        )
        return self.structured_output(
            system_prompt="Reply only with valid JSON.",
            user_prompt=prompt,
            max_tokens=250,
        )

    def check_api_health(self) -> dict[str, Any]:
        """Check the health of the API endpoint and all configured keys."""
        result: dict[str, Any] = {
            "healthy": True,
            "model": self.model,
            "api_base": self.api_base,
            "total_requests": self._total_requests,
            "total_failures": self._total_failures,
            "keys_count": len(self.api_keys),
            "per_key_stats": {},
            "recent_errors": list(self._error_log)[-10:],
        }

        for i, key in enumerate(self.api_keys):
            suffix = key[-8:]
            key_stat: dict[str, Any] = {
                "index": i,
                "failures": self._key_failures.get(suffix, 0),
                "successes": self._key_successes.get(suffix, 0),
                "last_error": self._last_key_error.get(suffix),
            }
            result["per_key_stats"][f"key_{i}"] = key_stat
            if key_stat["failures"] > key_stat["successes"] and key_stat["failures"] > 5:
                result["healthy"] = False

        return result

    def get_diagnostics(self) -> dict[str, Any]:
        """Return internal diagnostics for monitoring."""
        return {
            "model": self.model,
            "total_requests": self._total_requests,
            "total_failures": self._total_failures,
            "cache_size": len(self._cache),
            "recent_errors": list(self._error_log)[-20:],
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """Get or create the global LLM client singleton."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
