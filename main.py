#!/usr/bin/env python3
"""
Hermes-OpenManus multi-agent system — entry point.

Initialises all modules (LLM client, memory, skills, bot) from environment
variables and starts the Telegram polling loop.

Enhanced with config validation, structured logging with rotation,
PID file management, crash recovery, and startup health checks.
"""

from __future__ import annotations

import atexit
import json
import logging
import logging.handlers
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.client import LLMClient
from src.memory.context import ConversationContext
from src.memory.skills import SkillManager
from src.bot.telegram import TelegramBot

# ---------------------------------------------------------------------------
# Optional stability imports
# ---------------------------------------------------------------------------

_HAS_STABILITY = False
try:
    from src.core.stability import GracefulShutdown, HealthChecker, MemoryMonitor

    _HAS_STABILITY = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------

BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
API_BASE: str = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL: str = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED_CHATS_RAW: str = os.environ.get("ALLOWED_CHATS", "")
RATE_LIMIT: float = float(os.environ.get("RATE_LIMIT", "2"))
MAX_HISTORY: int = int(os.environ.get("MAX_HISTORY", "24"))
MEMORY_FILE: str = os.environ.get("MEMORY_FILE", "/tmp/phantom_memory.json")
SKILLS_DIR: str = os.environ.get("SKILLS_DIR", "skills")
HISTORY_FILE: str = os.environ.get("HISTORY_FILE", "")
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
LOG_FILE: str = os.environ.get("LOG_FILE", "")
PID_FILE: str = os.environ.get("PID_FILE", "")

# Collect API keys: prefer comma-separated API_KEYS, fall back to single API_KEY
API_KEYS_RAW: str = os.environ.get("API_KEYS", "")
SINGLE_KEY: str = os.environ.get("API_KEY", "")

API_KEYS: list[str] = [k.strip() for k in API_KEYS_RAW.split(",") if k.strip()]
if not API_KEYS and SINGLE_KEY:
    API_KEYS = [SINGLE_KEY]

# Global uptime tracker
_START_TIME: float = 0.0


# ---------------------------------------------------------------------------
# Structured logging with rotation
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Configure root logger with structured format and optional file rotation."""
    global _START_TIME
    _START_TIME = time.time()

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    root_logger.addHandler(console)

    # File handler with rotation (if configured)
    if LOG_FILE:
        try:
            log_path = Path(LOG_FILE)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                LOG_FILE,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            root_logger.addHandler(file_handler)
        except Exception as exc:
            # Fall back to console-only
            logging.warning("Could not set up log file %s: %s", LOG_FILE, exc)

    # Quiet noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.setLevel(level)
    logger.info("Logging configured (level=%s, file=%s)", LOG_LEVEL, LOG_FILE or "stdout")


# ---------------------------------------------------------------------------
# PID file management
# ---------------------------------------------------------------------------

def write_pid_file() -> Optional[Path]:
    """Write the current PID to a file for process management."""
    if not PID_FILE:
        return None
    pid_path = Path(PID_FILE)
    try:
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        atexit.register(_cleanup_pid_file, pid_path)
        return pid_path
    except Exception as exc:
        logging.warning("Could not write PID file %s: %s", PID_FILE, exc)
        return None


def _cleanup_pid_file(pid_path: Path) -> None:
    """Remove PID file on exit."""
    try:
        if pid_path.exists():
            # Only remove if it contains our PID
            stored = pid_path.read_text(encoding="utf-8").strip()
            if stored == str(os.getpid()):
                pid_path.unlink()
    except Exception:
        logging.warning("Could not remove PID file on cleanup", exc_info=True)


def check_existing_process() -> bool:
    """Check if another instance is already running via PID file.

    Returns True if another process appears to be running.
    """
    if not PID_FILE:
        return False
    pid_path = Path(PID_FILE)
    if not pid_path.exists():
        return False
    try:
        old_pid = int(pid_path.read_text(encoding="utf-8").strip())
        # Check if process is still alive
        os.kill(old_pid, 0)
        return True  # Process exists
    except (ProcessLookupError, ValueError, PermissionError):
        return False  # Process dead or PID invalid


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def validate_config() -> list[str]:
    """Validate all required configuration variables.

    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []

    if not BOT_TOKEN:
        errors.append("BOT_TOKEN is required")
    if not API_KEYS:
        errors.append("API_KEYS (or API_KEY) is required")
    if RATE_LIMIT < 0:
        errors.append("RATE_LIMIT must be >= 0")
    if MAX_HISTORY < 1:
        errors.append("MAX_HISTORY must be >= 1")

    # Validate API_BASE URL format
    if not API_BASE.startswith(("http://", "https://")):
        errors.append("API_BASE must start with http:// or https://")

    return errors


# ---------------------------------------------------------------------------
# Startup health checks
# ---------------------------------------------------------------------------

def run_startup_checks() -> bool:
    """Run pre-flight health checks before starting the bot.

    Returns True if all checks pass.
    """
    logger = logging.getLogger(__name__)
    all_ok = True

    # Check memory file directory is writable
    try:
        mem_dir = Path(MEMORY_FILE).parent
        mem_dir.mkdir(parents=True, exist_ok=True)
        test_file = mem_dir / ".hermes_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        logger.info("✓ Memory directory writable: %s", mem_dir)
    except Exception as exc:
        logger.error("✗ Memory directory not writable: %s", exc)
        all_ok = False

    # Check skills directory exists
    skills_dir = PROJECT_ROOT / SKILLS_DIR
    if skills_dir.exists():
        logger.info("✓ Skills directory exists: %s", skills_dir)
    else:
        logger.warning("⚠ Skills directory not found (will be created): %s", skills_dir)
        try:
            skills_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.error("✗ Cannot create skills directory: %s", exc)
            all_ok = False

    # Quick API key validation (at least a few chars)
    for i, key in enumerate(API_KEYS):
        if len(key) < 10:
            logger.warning("⚠ API key %d appears too short (%d chars)", i, len(key))

    return all_ok


# ---------------------------------------------------------------------------
# Crash recovery
# ---------------------------------------------------------------------------

def run_with_crash_recovery() -> None:
    """Run the main function with crash recovery and auto-restart.

    Catches uncaught exceptions, logs them, and attempts a restart
    with exponential backoff.
    """
    logger = logging.getLogger(__name__)
    max_restarts = 5
    restart_delay = 5.0

    for attempt in range(max_restarts + 1):
        try:
            if attempt > 0:
                logger.info("Restart attempt %d/%d after %.0fs delay...",
                            attempt, max_restarts, restart_delay)
                time.sleep(restart_delay)
                restart_delay = min(restart_delay * 2, 300.0)  # Cap at 5 minutes

            main()
            # If main() returns normally, we're done
            break

        except KeyboardInterrupt:
            logger.info("Interrupted by user, exiting.")
            break

        except SystemExit as exc:
            logger.info("SystemExit with code %s", exc.code)
            sys.exit(exc.code)

        except Exception as exc:
            logger.critical("Uncaught exception (attempt %d/%d): %s",
                            attempt + 1, max_restarts, exc, exc_info=True)

            if attempt >= max_restarts:
                logger.critical("Max restarts (%d) reached. Exiting.", max_restarts)
                sys.exit(1)

            # Memory cleanup before restart
            import gc
            gc.collect()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Wire up all modules and start the bot."""
    setup_logging()
    logger = logging.getLogger(__name__)

    # Check for existing instance
    if check_existing_process():
        logger.error("Another instance is already running (PID file: %s). Exiting.", PID_FILE)
        sys.exit(1)

    # Write PID file
    write_pid_file()

    # Validate configuration
    config_errors = validate_config()
    if config_errors:
        for err in config_errors:
            logger.error("Config error: %s", err)
        sys.exit(1)

    # Parse allowed chats
    allowed_chats: set[int] = set()
    if ALLOWED_CHATS_RAW:
        try:
            allowed_chats = {int(c.strip()) for c in ALLOWED_CHATS_RAW.split(",") if c.strip()}
        except ValueError:
            logger.warning("Invalid ALLOWED_CHATS format, allowing all chats")

    # Resolve skills directory relative to project root
    skills_dir = PROJECT_ROOT / SKILLS_DIR

    logger.info("=" * 60)
    logger.info("Hermes-OpenManus multi-agent system starting up")
    logger.info("=" * 60)
    logger.info("PID: %d", os.getpid())
    logger.info("Model: %s", MODEL)
    logger.info("API base: %s", API_BASE)
    logger.info("API keys: %d configured", len(API_KEYS))
    logger.info("Allowed chats: %s", allowed_chats or "all")
    logger.info("Skills dir: %s", skills_dir)
    logger.info("Memory file: %s", MEMORY_FILE)
    logger.info("Stability module: %s", "available" if _HAS_STABILITY else "not available")

    # Run startup checks
    if not run_startup_checks():
        logger.warning("Some startup checks failed, continuing anyway...")

    # --- Initialise modules ---

    llm = LLMClient(
        api_keys=API_KEYS,
        api_base=API_BASE,
        model=MODEL,
        timeout=120,
        max_retries=3,
    )

    context = ConversationContext(
        max_messages=MAX_HISTORY,
        system_prompt=(
            "You are PhantomBot v8 — an AI assistant with a full VPS toolchain.\n"
            "You can execute shell commands, browse the web, convert files, generate images, "
            "and use MCP tools.\n"
            "Reply in the user's language. Be concise. Use markdown when helpful."
        ),
        persist_path=HISTORY_FILE or None,
    )

    skills = SkillManager(skills_dir=skills_dir)

    bot = TelegramBot(
        bot_token=BOT_TOKEN,
        llm=llm,
        context=context,
        skills=skills,
        allowed_chats=allowed_chats,
        rate_limit=RATE_LIMIT,
        memory_file=MEMORY_FILE,
    )

    # Pre-flight LLM health check (non-blocking, best-effort)
    try:
        llm_health = llm.check_api_health()
        if llm_health.get("healthy"):
            logger.info("✓ LLM API health check passed")
        else:
            logger.warning("⚠ LLM API health check reports issues: endpoint_reachable=%s",
                           llm_health.get("endpoint_reachable"))
    except Exception as exc:
        logger.warning("LLM health check failed (non-fatal): %s", exc)

    logger.info("All modules initialised. Starting bot...")

    # Run the bot (this blocks until shutdown)
    bot.run()


if __name__ == "__main__":
    run_with_crash_recovery()
