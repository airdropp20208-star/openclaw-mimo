"""
Stability module for production-grade reliability patterns.

Provides circuit breakers, retry logic, health checks, watchdogs,
graceful shutdown, and memory monitoring — all stdlib-only and thread-safe.
"""

from __future__ import annotations

import atexit
import functools
import gc
import json
import logging
import os
import random
import signal
import socket
import statistics
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    """Possible states for a circuit breaker."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerStats:
    """Statistics snapshot for a circuit breaker."""
    name: str
    state: str
    failure_count: int
    success_count: int
    total_calls: int
    last_failure_time: Optional[float]
    last_success_time: Optional[float]
    half_open_calls: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CircuitBreakerError(Exception):
    """Raised when a circuit breaker is open and rejects a call."""

    def __init__(self, name: str, cooldown_remaining: float) -> None:
        self.name = name
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Circuit breaker '{name}' is OPEN. "
            f"Retry in {cooldown_remaining:.1f}s."
        )


class CircuitBreaker:
    """
    Circuit breaker implementation with CLOSED / OPEN / HALF_OPEN states.

    Usage::

        cb = CircuitBreaker("llm", failure_threshold=5, recovery_timeout=60)
        result = cb.call(my_function, arg1, arg2)

        # or as a decorator
        @cb.decorator
        def llm_call(prompt: str) -> str: ...

    Parameters
    ----------
    name : str
        Human-readable name for logging and stats.
    failure_threshold : int
        Consecutive failures before opening the circuit.
    recovery_timeout : float
        Seconds to wait before moving from OPEN to HALF_OPEN.
    half_open_max_calls : int
        Max test calls allowed in HALF_OPEN before deciding.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._total_calls = 0
        self._half_open_calls = 0
        self._last_failure_time: Optional[float] = None
        self._last_success_time: Optional[float] = None
        self._lock = threading.Lock()

    # -- state properties ---------------------------------------------------

    @property
    def state(self) -> CircuitState:
        """Current state, auto-transitions OPEN -> HALF_OPEN when timeout elapses."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                if (
                    self._last_failure_time is not None
                    and (time.monotonic() - self._last_failure_time) >= self.recovery_timeout
                ):
                    self._transition(CircuitState.HALF_OPEN)
            return self._state

    def _transition(self, new_state: CircuitState) -> None:
        """Internal state transition with logging."""
        old = self._state
        self._state = new_state
        logger.info(
            "CircuitBreaker '%s': %s -> %s",
            self.name, old.value, new_state.value,
        )
        if new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0

    # -- public API ---------------------------------------------------------

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """
        Execute *fn* through the circuit breaker.

        Raises ``CircuitBreakerError`` when the circuit is open.
        """
        with self._lock:
            self._total_calls += 1
            current_state = self._state

        if current_state == CircuitState.OPEN:
            remaining = self._cooldown_remaining()
            raise CircuitBreakerError(self.name, remaining)

        if current_state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls >= self.half_open_max_calls:
                    remaining = self._cooldown_remaining()
                    raise CircuitBreakerError(self.name, remaining)
                self._half_open_calls += 1

        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def decorator(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Decorator version of :meth:`call`."""
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(fn, *args, **kwargs)
        wrapper.circuit_breaker = self  # type: ignore[attr-defined]
        return wrapper

    # -- internals ----------------------------------------------------------

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            logger.warning(
                "CircuitBreaker '%s': failure #%d (threshold=%d, state=%s)",
                self.name, self._failure_count, self.failure_threshold, self._state.value,
            )
            if self._state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._transition(CircuitState.OPEN)

    def _on_success(self) -> None:
        with self._lock:
            self._success_count += 1
            self._last_success_time = time.monotonic()
            if self._state == CircuitState.HALF_OPEN:
                logger.info(
                    "CircuitBreaker '%s': HALF_OPEN recovery succeeded — closing",
                    self.name,
                )
                self._transition(CircuitState.CLOSED)
                self._failure_count = 0

    def _cooldown_remaining(self) -> float:
        if self._last_failure_time is None:
            return 0.0
        elapsed = time.monotonic() - self._last_failure_time
        return max(0.0, self.recovery_timeout - elapsed)

    def reset(self) -> None:
        """Reset the breaker to CLOSED with zero counters."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._half_open_calls = 0
            self._last_failure_time = None
            logger.info("CircuitBreaker '%s': reset to CLOSED", self.name)

    def stats(self) -> CircuitBreakerStats:
        return CircuitBreakerStats(
            name=self.name,
            state=self.state.value,
            failure_count=self._failure_count,
            success_count=self._success_count,
            total_calls=self._total_calls,
            last_failure_time=self._last_failure_time,
            last_success_time=self._last_success_time,
            half_open_calls=self._half_open_calls,
        )


# Convenience factory
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
    half_open_max_calls: int = 3,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that attaches a shared ``CircuitBreaker`` to a function.

    All decorated functions with the same *name* share the same breaker
    instance (registered in a module-level registry).
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        if name not in _circuit_breakers:
            _circuit_breakers[name] = CircuitBreaker(
                name, failure_threshold, recovery_timeout, half_open_max_calls,
            )
        cb = _circuit_breakers[name]

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return cb.call(fn, *args, **kwargs)

        wrapper.circuit_breaker = cb  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# 2. Retry with exponential back-off and jitter
# ---------------------------------------------------------------------------

class RetryExhausted(Exception):
    """Raised when all retry attempts have been exhausted."""

    def __init__(self, name: str, attempts: int, last_error: BaseException) -> None:
        self.name = name
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Retry '{name}' exhausted after {attempts} attempts. "
            f"Last error: {last_error}"
        )


class RetryWithBackoff:
    """
    Retry helper with exponential back-off and jitter.

    Usage::

        retry = RetryWithBackoff("api_call", max_retries=3)
        result = retry.call(requests.get, url)

        # or as decorator
        @retry.decorator
        def fetch(url): ...

        # combine with circuit breaker
        cb = CircuitBreaker("api")
        retry = RetryWithBackoff("api_call", circuit_breaker=cb)
    """

    def __init__(
        self,
        name: str = "default",
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: float = 0.5,
        circuit_breaker: Optional[CircuitBreaker] = None,
        retryable_exceptions: Tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        self.name = name
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter
        self.circuit_breaker = circuit_breaker
        self.retryable_exceptions = retryable_exceptions

    def _compute_delay(self, attempt: int) -> float:
        """Exponential back-off with full jitter capped at *max_delay*."""
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        jitter_range = delay * self.jitter
        delay += random.uniform(-jitter_range, jitter_range)
        return max(0.0, delay)

    def call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute *fn* with retries.  Returns the first successful result."""
        last_error: BaseException = Exception("unknown")
        for attempt in range(self.max_retries + 1):
            try:
                if self.circuit_breaker is not None:
                    return self.circuit_breaker.call(fn, *args, **kwargs)
                return fn(*args, **kwargs)
            except self.retryable_exceptions as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = self._compute_delay(attempt)
                    logger.warning(
                        "Retry '%s' attempt %d/%d failed: %s — retrying in %.2fs",
                        self.name, attempt + 1, self.max_retries, exc, delay,
                    )
                    time.sleep(delay)
                else:
                    logger.error(
                        "Retry '%s' exhausted after %d attempts. Last error: %s",
                        self.name, self.max_retries + 1, exc,
                    )
        raise RetryExhausted(self.name, self.max_retries + 1, last_error)

    def decorator(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(fn, *args, **kwargs)
        wrapper.retry = self  # type: ignore[attr-defined]
        return wrapper


# ---------------------------------------------------------------------------
# 3. Health Checker
# ---------------------------------------------------------------------------

@dataclass
class HealthResult:
    """Result of a single health check."""
    name: str
    healthy: bool
    message: str
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthReport:
    """Aggregate report from :meth:`HealthChecker.check_all`."""
    overall_healthy: bool
    checks: List[HealthResult]
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_healthy": self.overall_healthy,
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": self.timestamp,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


class HealthChecker:
    """
    Registry of named health checks.

    Usage::

        hc = HealthChecker()
        hc.add_check("db", check_database)
        report = hc.check_all()
        print(report.to_json(indent=2))
    """

    def __init__(self) -> None:
        self._checks: Dict[str, Callable[[], Tuple[bool, str]]] = {}

    def add_check(
        self, name: str, check_fn: Callable[[], Tuple[bool, str]]
    ) -> None:
        """Register a health check function that returns ``(healthy, message)``."""
        self._checks[name] = check_fn
        logger.debug("HealthChecker: registered check '%s'", name)

    def remove_check(self, name: str) -> None:
        self._checks.pop(name, None)

    def check_all(self) -> HealthReport:
        """Run every registered check and return an aggregate report."""
        results: List[HealthResult] = []
        for name, fn in self._checks.items():
            start = time.monotonic()
            try:
                healthy, message = fn()
            except Exception as exc:
                healthy, message = False, f"Check raised: {exc}"
                logger.exception("HealthCheck '%s' raised", name)
            latency = (time.monotonic() - start) * 1000
            results.append(HealthResult(name=name, healthy=healthy, message=message, latency_ms=latency))
        overall = all(r.healthy for r in results) if results else True
        return HealthReport(overall_healthy=overall, checks=results, timestamp=time.time())

    # -- built-in checks ----------------------------------------------------

    @staticmethod
    def disk_space(min_free_gb: float = 1.0) -> Tuple[bool, str]:
        """Check that at least *min_free_gb* GB is free on the current disk."""
        try:
            stat = os.statvfs(".")
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
            healthy = free_gb >= min_free_gb
            msg = f"{free_gb:.2f} GB free (threshold: {min_free_gb} GB)"
            return healthy, msg
        except OSError as exc:
            return False, f"Cannot stat disk: {exc}"

    @staticmethod
    def memory_usage(max_percent: float = 90.0) -> Tuple[bool, str]:
        """Check that memory usage stays below *max_percent*."""
        try:
            # /proc/meminfo is Linux-only but we're on Linux
            with open("/proc/meminfo", "r") as f:
                lines = f.readlines()
            mem = {}
            for line in lines:
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    val = int(parts[1])
                    mem[key] = val
            total = mem.get("MemTotal", 0)
            available = mem.get("MemAvailable", mem.get("MemFree", 0))
            if total == 0:
                return True, "Cannot determine memory (MemTotal=0)"
            used_percent = ((total - available) / total) * 100
            healthy = used_percent < max_percent
            msg = f"{used_percent:.1f}% used (threshold: {max_percent}%)"
            return healthy, msg
        except Exception as exc:
            return False, f"Cannot read memory info: {exc}"

    @staticmethod
    def api_reachable(host: str = "1.1.1.1", port: int = 443, timeout: float = 3.0) -> Tuple[bool, str]:
        """TCP-connect check to *host:port*."""
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True, f"{host}:{port} reachable"
        except (socket.timeout, OSError) as exc:
            return False, f"{host}:{port} unreachable: {exc}"


# ---------------------------------------------------------------------------
# 4. Watchdog
# ---------------------------------------------------------------------------

class Watchdog:
    """
    Monitors a callable and auto-restarts on failure.

    Usage::

        def worker():
            while True:
                do_work()

        wd = Watchdog(worker, max_restarts=5, cooldown=30)
        wd.start()      # runs in a daemon thread
        ...
        wd.stop()

    Parameters
    ----------
    target : callable
        The function to run.  Should loop internally or be designed to
        be restarted.
    max_restarts : int
        Maximum consecutive restarts before giving up.
    cooldown : float
        Base seconds to wait between restarts (escalates).
    escalate_factor : float
        Multiply cooldown by this on each consecutive failure.
    """

    def __init__(
        self,
        target: Callable[..., Any],
        args: tuple = (),
        kwargs: Optional[Dict[str, Any]] = None,
        max_restarts: int = 5,
        cooldown: float = 30.0,
        escalate_factor: float = 1.5,
    ) -> None:
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}
        self.max_restarts = max_restarts
        self.cooldown = cooldown
        self.escalate_factor = escalate_factor

        self._restart_count = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def _run(self) -> None:
        current_cooldown = self.cooldown
        while self._running and not self._stop_event.is_set():
            try:
                logger.info("Watchdog: starting target (attempt %d)", self._restart_count + 1)
                self._target(*self._args, **self._kwargs)
            except Exception:
                logger.exception("Watchdog: target crashed")
            if not self._running or self._stop_event.is_set():
                break
            with self._lock:
                self._restart_count += 1
                if self._restart_count > self.max_restarts:
                    logger.error(
                        "Watchdog: exceeded max_restarts (%d). Giving up.",
                        self.max_restarts,
                    )
                    self._running = False
                    return
                actual_cooldown = current_cooldown
                current_cooldown *= self.escalate_factor
            logger.warning(
                "Watchdog: restarting in %.1fs (restart %d/%d)",
                actual_cooldown, self._restart_count, self.max_restarts,
            )
            self._stop_event.wait(timeout=actual_cooldown)

    def start(self) -> None:
        """Start the monitored function in a daemon thread."""
        with self._lock:
            if self._running:
                logger.warning("Watchdog: already running")
                return
            self._running = True
            self._restart_count = 0
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="watchdog", daemon=True)
            self._thread.start()
        logger.info("Watchdog: started")

    def stop(self, timeout: float = 10.0) -> None:
        """Signal the watchdog to stop and wait for the thread to finish."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        logger.info("Watchdog: stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def restart_count(self) -> int:
        with self._lock:
            return self._restart_count


# ---------------------------------------------------------------------------
# 5. Graceful Shutdown
# ---------------------------------------------------------------------------

class GracefulShutdown:
    """
    Coordinates graceful process shutdown via signal handlers and
    registered cleanup callbacks.

    Usage::

        with GracefulShutdown() as sd:
            sd.register(my_cleanup)
            run_forever()

    Supports context-manager protocol; ``__enter__`` installs signal
    handlers, ``__exit__`` triggers cleanup.
    """

    DEFAULT_TIMEOUT = 30.0

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self._callbacks: List[Tuple[str, Callable[[], None]]] = []
        self._executed = False
        self._lock = threading.Lock()
        self._original_handlers: Dict[int, Any] = {}

    def register(self, callback: Callable[[], None], name: str = "") -> None:
        """Register a cleanup callback.  *name* is optional for logging."""
        with self._lock:
            self._callbacks.append((name or callback.__name__, callback))
        logger.debug("GracefulShutdown: registered cleanup '%s'", name or callback.__name__)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("GracefulShutdown: received %s", sig_name)
        # Don't re-enter
        with self._lock:
            if self._executed:
                return
            self._executed = True
        self._run_callbacks()

    def _run_callbacks(self) -> None:
        """Execute all registered callbacks with a global timeout."""
        logger.info(
            "GracefulShutdown: running %d cleanup callbacks (timeout=%.1fs)",
            len(self._callbacks), self.timeout,
        )

        def _worker() -> None:
            for name, cb in self._callbacks:
                try:
                    logger.info("GracefulShutdown: executing '%s'", name)
                    cb()
                except Exception:
                    logger.exception("GracefulShutdown: callback '%s' failed", name)

        t = threading.Thread(target=_worker, daemon=True, name="shutdown-cleanup")
        t.start()
        t.join(timeout=self.timeout)
        if t.is_alive():
            logger.error(
                "GracefulShutdown: cleanup timed out after %.1fs — exiting anyway",
                self.timeout,
            )
        else:
            logger.info("GracefulShutdown: all callbacks completed")

    def _install_handlers(self) -> None:
        """Install SIGTERM/SIGINT/SIGHUP handlers, saving originals."""
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            self._original_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self._signal_handler)
        logger.debug("GracefulShutdown: signal handlers installed")

    def _restore_handlers(self) -> None:
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
        logger.debug("GracefulShutdown: signal handlers restored")

    def shutdown_now(self) -> None:
        """Manually trigger shutdown (same as receiving SIGTERM)."""
        with self._lock:
            if self._executed:
                return
            self._executed = True
        self._run_callbacks()

    def __enter__(self) -> GracefulShutdown:
        self._install_handlers()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._restore_handlers()
        with self._lock:
            already_done = self._executed
            if not self._executed:
                self._executed = True
        if not already_done:
            self._run_callbacks()


# ---------------------------------------------------------------------------
# 6. Memory Monitor
# ---------------------------------------------------------------------------

class MemoryMonitor:
    """
    Tracks process memory usage over time and triggers GC / callbacks
    when a threshold is exceeded.

    Usage::

        mm = MemoryMonitor(max_bytes=500 * 1024 * 1024)
        mm.start(interval=30)
        ...
        mm.stop()

    Parameters
    ----------
    max_bytes : int
        Threshold in bytes.  When the process RSS exceeds this,
        the monitor calls GC and the registered cleanup callback.
    cleanup_fn : optional callable
        Invoked when the threshold is exceeded (after GC).
    history_size : int
        Number of recent samples to keep for statistics.
    """

    def __init__(
        self,
        max_bytes: int = 500 * 1024 * 1024,
        cleanup_fn: Optional[Callable[[], None]] = None,
        history_size: int = 100,
    ) -> None:
        self.max_bytes = max_bytes
        self.cleanup_fn = cleanup_fn
        self.history_size = history_size

        self._samples: List[Tuple[float, int]] = []  # (timestamp, rss_bytes)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cleanup_count = 0

    @staticmethod
    def get_rss_bytes() -> int:
        """Return current RSS in bytes using /proc/self/statm (Linux)."""
        try:
            with open("/proc/self/statm", "r") as f:
                parts = f.read().split()
            # fields: size resident shared text lib data dt (in pages)
            resident_pages = int(parts[1])
            page_size = os.sysconf("SC_PAGE_SIZE")
            return resident_pages * page_size
        except Exception:
            return 0

    def _sample(self) -> int:
        rss = self.get_rss_bytes()
        with self._lock:
            self._samples.append((time.time(), rss))
            if len(self._samples) > self.history_size:
                self._samples = self._samples[-self.history_size:]
        return rss

    def _monitor_loop(self, interval: float) -> None:
        while not self._stop_event.is_set():
            rss = self._sample()
            if rss > self.max_bytes:
                logger.warning(
                    "MemoryMonitor: RSS %d bytes exceeds threshold %d bytes — running GC",
                    rss, self.max_bytes,
                )
                collected = gc.collect()
                logger.info("MemoryMonitor: gc.collect freed %d objects", collected)
                with self._lock:
                    self._cleanup_count += 1
                if self.cleanup_fn is not None:
                    try:
                        self.cleanup_fn()
                    except Exception:
                        logger.exception("MemoryMonitor: cleanup_fn failed")
            self._stop_event.wait(timeout=interval)

    def start(self, interval: float = 30.0) -> None:
        """Start periodic sampling in a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("MemoryMonitor: already running")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True, name="mem-monitor",
        )
        self._thread.start()
        logger.info("MemoryMonitor: started (interval=%.1fs, max=%d bytes)", interval, self.max_bytes)

    def stop(self) -> None:
        """Stop the monitoring thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("MemoryMonitor: stopped")

    def stats(self) -> Dict[str, Any]:
        """Return memory statistics as a JSON-serialisable dict."""
        with self._lock:
            rss_values = [s[1] for s in self._samples]
        if not rss_values:
            return {"samples": 0, "cleanup_count": self._cleanup_count}
        return {
            "samples": len(rss_values),
            "current_bytes": rss_values[-1],
            "min_bytes": min(rss_values),
            "max_bytes": max(rss_values),
            "mean_bytes": statistics.mean(rss_values),
            "median_bytes": statistics.median(rss_values),
            "stdev_bytes": statistics.stdev(rss_values) if len(rss_values) > 1 else 0.0,
            "cleanup_count": self._cleanup_count,
        }

    def force_gc(self) -> int:
        """Force a garbage collection cycle and return number of collected objects."""
        collected = gc.collect()
        logger.info("MemoryMonitor: forced gc.collect freed %d objects", collected)
        return collected

    def force_sample(self) -> int:
        """Take an immediate sample and return current RSS in bytes."""
        return self._sample()
