"""LLM client for Xiaomi MiMo (OpenAI-compatible API).

Handles key rotation, retry with exponential backoff, streaming support,
and structured output parsing. Uses only stdlib (urllib) — no external deps.

Enhanced with circuit breaker, per-key timeouts, fallback responses,
and API health checking via the stability module (graceful fallback).
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import Any, Callable, Generator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional stability imports (graceful fallback)
# ---------------------------------------------------------------------------

_HAS_STABILITY = False
_CircuitBreakerCls: Any = None
_RetryWithBackoffCls: Any = None
_CircuitBreakerError: Any = None
_RetryExhausted: Any = None

try:
    from src.core.stability import (
        CircuitBreaker as _CB,
        CircuitBreakerError as _CBE,
        RetryExhausted as _RE,
        RetryWithBackoff as _RB,
    )

    _HAS_STABILITY = True
    _CircuitBreakerCls = _CB
    _CircuitBreakerError = _CBE
    _RetryExhausted = _RE
    _RetryWithBackoffCls = _RB
except ImportError:
    logger.debug("Stability module not available — using built-in resilience")


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
    circuit_breaker:
        Optional pre-configured circuit breaker instance. If not provided
        and the stability module is available, one is created automatically.
    per_key_timeout:
        Optional per-key timeout override (seconds). Falls back to *timeout*.
    fallback_message:
        Message returned when the circuit is open or all retries fail.
    """

    def __init__(
        self,
        api_keys: list[str],
        api_base: str = "https://api.xiaomimimo.com/v1",
        model: str = "mimo-v2.5",
        timeout: int = 120,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        circuit_breaker: Any = None,
        per_key_timeout: Optional[int] = None,
        fallback_message: str = "⚠️ Service temporarily unavailable. Please try again shortly.",
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
        self.fallback_message: str = fallback_message

        # Per-key timeout: dict mapping key suffix → timeout
        self._per_key_timeout: dict[str, int] = {}
        if per_key_timeout is not None:
            for key in self.api_keys:
                self._per_key_timeout[key[-8:]] = per_key_timeout

        # Per-key state tracking
        self._key_failures: dict[str, int] = {}
        self._key_successes: dict[str, int] = {}
        self._last_key_error: dict[str, Optional[str]] = {}

        # Circuit breaker (uses the stability module's CircuitBreaker API)
        if circuit_breaker is not None:
            self._circuit = circuit_breaker
        elif _HAS_STABILITY and _CircuitBreakerCls is not None:
            self._circuit = _CircuitBreakerCls(
                name="llm_api",
                failure_threshold=5,
                recovery_timeout=30.0,
                half_open_max_calls=2,
            )
        else:
            self._circuit = None

        # Request/response cache for graceful degradation
        self._cache: dict[str, Any] = {}
        self._cache_ttl: float = 300.0  # 5 minutes
        self._cache_timestamps: dict[str, float] = {}

        # Error tracking
        self._error_log: deque[tuple[float, str]] = deque(maxlen=200)
        self._total_requests: int = 0
        self._total_failures: int = 0

        # Retry helper
        if _HAS_STABILITY and _RetryWithBackoffCls is not None:
            self._retry: Any = _RetryWithBackoffCls(
                name="llm_retry",
                max_retries=max_retries,
                base_delay=backoff_base,
                max_delay=60.0,
                jitter=0.3,
            )
        else:
            self._retry = None

        logger.info(
            "LLMClient initialised – model=%s, keys=%d, base=%s, circuit_breaker=%s",
            self.model,
            len(self.api_keys),
            self.api_base,
            "yes" if self._circuit is not None else "no",
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

    def _get_key_timeout(self, api_key: str) -> int:
        """Return the timeout for a specific key."""
        suffix = api_key[-8:]
        return self._per_key_timeout.get(suffix, self.timeout)

    def _record_key_failure(self, api_key: str, error: str) -> None:
        """Track per-key failure counts."""
        suffix = api_key[-8:]
        self._key_failures[suffix] = self._key_failures.get(suffix, 0) + 1
        self._last_key_error[suffix] = error

    def _record_key_success(self, api_key: str) -> None:
        """Track per-key success counts."""
        suffix = api_key[-8:]
        self._key_successes[suffix] = self._key_successes.get(suffix, 0) + 1
        self._last_key_error[suffix] = None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _cache_key(self, path: str, payload: dict[str, Any]) -> str:
        """Generate a cache key from the request."""
        return f"{path}:{_simple_hash(payload)}"

    def _get_cached(self, key: str) -> Optional[Any]:
        """Return cached response if still valid."""
        ts = self._cache_timestamps.get(key, 0)
        if time.time() - ts < self._cache_ttl and key in self._cache:
            return self._cache[key]
        return None

    def _set_cached(self, key: str, value: Any) -> None:
        """Store a response in the cache."""
        self._cache[key] = value
        self._cache_timestamps[key] = time.time()

    def _clear_expired_cache(self) -> None:
        """Remove expired cache entries."""
        now = time.time()
        expired = [k for k, ts in self._cache_timestamps.items() if now - ts > self._cache_ttl]
        for k in expired:
            self._cache.pop(k, None)
            self._cache_timestamps.pop(k, None)

    # ------------------------------------------------------------------
    # Error tracking
    # ------------------------------------------------------------------

    def _track_error(self, error: str) -> None:
        """Record an error with timestamp."""
        self._error_log.append((time.time(), error))
        self._total_failures += 1

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
        Integrates with circuit breaker for graceful degradation.
        """
        self._total_requests += 1
        self._clear_expired_cache()

        # Check circuit breaker state directly (for fallback logic)
        if self._circuit is not None:
            cb_state = self._circuit.state
            if cb_state.value == "open":
                logger.warning("Circuit breaker OPEN — returning fallback/cache")
                cache_key = self._cache_key(path, payload)
                cached = self._get_cached(cache_key)
                if cached is not None:
                    logger.info("Returning cached response for circuit-open fallback")
                    return cached
                return {
                    "choices": [{"message": {"content": self.fallback_message}}],
                }

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            key = self._next_key()
            key_timeout = self._get_key_timeout(key)

            try:
                def _attempt_request(k: str = key, t: int = key_timeout) -> Any:
                    """Single request attempt."""
                    req = self._build_request(path, payload, k)
                    with urllib.request.urlopen(req, timeout=t) as resp:
                        raw = resp.read().decode("utf-8")
                    return json.loads(raw)

                # Execute through circuit breaker if available
                if self._circuit is not None:
                    result = self._circuit.call(_attempt_request)
                else:
                    result = _attempt_request()

                self._record_key_success(key)

                # Cache successful responses
                cache_key = self._cache_key(path, payload)
                self._set_cached(cache_key, result)

                return result

            except Exception as exc:
                last_error = exc
                self._record_key_failure(key, str(exc))

                # Distinguish error types for logging
                if _CircuitBreakerError is not None and isinstance(exc, _CircuitBreakerError):
                    logger.warning("Circuit breaker rejected request: %s", exc)
                    self._track_error(f"CircuitOpen: {exc}")
                    break  # Don't retry — circuit is open
                elif isinstance(exc, urllib.error.HTTPError):
                    if exc.code == 401:
                        logger.warning(
                            "Auth failed with key index %d (401), rotating",
                            self._key_index,
                        )
                        # Try remaining keys
                        for remaining_key in self._all_keys():
                            try:
                                r_timeout = self._get_key_timeout(remaining_key)
                                req2 = self._build_request(path, payload, remaining_key)
                                with urllib.request.urlopen(req2, timeout=r_timeout) as resp2:
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

                time.sleep(self.backoff_base * (2 ** attempt))

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
        self,
        path: str,
        payload: dict[str, Any],
    ) -> Generator[str, None, None]:
        """Execute a streaming request, yielding content chunks."""
        # Check circuit breaker state
        if self._circuit is not None:
            cb_state = self._circuit.state
            if cb_state.value == "open":
                logger.warning("Circuit breaker OPEN — returning fallback for stream")
                yield self.fallback_message
                return

        key = self._next_key()
        key_timeout = self._get_key_timeout(key)
        payload_copy = dict(payload)
        payload_copy["stream"] = True
        try:
            req = self._build_request(path, payload_copy, key)
            with urllib.request.urlopen(req, timeout=key_timeout) as resp:
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
            return self.fallback_message

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

    # ------------------------------------------------------------------
    # Health check & diagnostics
    # ------------------------------------------------------------------

    def check_api_health(self) -> dict[str, Any]:
        """Check the health of the API endpoint and all configured keys.

        Returns a dict with overall status and per-key diagnostics.
        """
        result: dict[str, Any] = {
            "healthy": True,
            "model": self.model,
            "api_base": self.api_base,
            "total_requests": self._total_requests,
            "total_failures": self._total_failures,
            "keys_count": len(self.api_keys),
            "per_key_stats": {},
            "circuit_breaker": None,
            "recent_errors": list(self._error_log)[-10:],
        }

        # Circuit breaker state
        if self._circuit is not None:
            cb_stats = self._circuit.stats()
            result["circuit_breaker"] = cb_stats.to_dict()
            if cb_stats.state == "open":
                result["healthy"] = False

        # Per-key stats
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

        # Quick liveness probe (optional lightweight GET)
        try:
            probe_url = f"{self.api_base}/models"
            probe_req = urllib.request.Request(probe_url)
            probe_req.add_header("Authorization", f"Bearer {self.api_keys[0]}")
            with urllib.request.urlopen(probe_req, timeout=10) as resp:
                result["endpoint_reachable"] = True
        except Exception as exc:
            result["endpoint_reachable"] = False
            result["endpoint_error"] = str(exc)
            result["healthy"] = False

        return result

    def get_diagnostics(self) -> dict[str, Any]:
        """Return internal diagnostics for monitoring."""
        return {
            "model": self.model,
            "total_requests": self._total_requests,
            "total_failures": self._total_failures,
            "cache_size": len(self._cache),
            "circuit_state": self._circuit.state.value if self._circuit else "no_circuit_breaker",
            "recent_errors": list(self._error_log)[-20:],
        }


# ---------------------------------------------------------------------------
# Simple hash helper for cache keys (no hashlib dependency)
# ---------------------------------------------------------------------------

def _simple_hash(data: Any) -> str:
    """Deterministic hash for cache keys using only stdlib."""
    try:
        s = json.dumps(data, sort_keys=True, default=str)
    except (TypeError, ValueError):
        s = str(data)
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return format(h, "08x")
