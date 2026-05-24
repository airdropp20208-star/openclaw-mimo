#!/usr/bin/env python3
"""
Hermes-OpenManus multi-agent system — entry point.

Initialises all modules (LLM client, memory, skills, bot) from environment
variables and starts the Telegram polling loop.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm.client import LLMClient
from src.memory.context import ConversationContext
from src.memory.skills import SkillManager
from src.bot.telegram import TelegramBot

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

# Collect API keys: prefer comma-separated API_KEYS, fall back to single API_KEY
API_KEYS_RAW: str = os.environ.get("API_KEYS", "")
SINGLE_KEY: str = os.environ.get("API_KEY", "")

API_KEYS: list[str] = [k.strip() for k in API_KEYS_RAW.split(",") if k.strip()]
if not API_KEYS and SINGLE_KEY:
    API_KEYS = [SINGLE_KEY]


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """Configure root logger with a clean format."""
    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Quiet noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.setLevel(level)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Wire up all modules and start the bot."""
    setup_logging()
    logger = logging.getLogger(__name__)

    # Validate required config
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is required. Exiting.")
        sys.exit(1)
    if not API_KEYS:
        logger.error("API_KEYS (or API_KEY) environment variable is required. Exiting.")
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
    logger.info("Model: %s", MODEL)
    logger.info("API base: %s", API_BASE)
    logger.info("API keys: %d configured", len(API_KEYS))
    logger.info("Allowed chats: %s", allowed_chats or "all")
    logger.info("Skills dir: %s", skills_dir)
    logger.info("Memory file: %s", MEMORY_FILE)

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

    logger.info("All modules initialised. Starting bot...")
    bot.run()


if __name__ == "__main__":
    main()
