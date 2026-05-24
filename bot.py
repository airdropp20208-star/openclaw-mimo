#!/usr/bin/env python3
"""
Hermes Bot — Telegram bot powered by Hermes Agent + OpenManus tools.

Usage:
    BOT_TOKEN=xxx API_KEY=xxx python bot.py
"""

import hashlib
import json
import logging
import mimetypes
import os
import signal
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from agent import HermesAgent

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_BASE = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED_CHATS_RAW = os.environ.get("ALLOWED_CHATS", "")
RATE_LIMIT = float(os.environ.get("RATE_LIMIT", "2"))

# Key pool: API_KEYS (comma-separated) or single API_KEY
_key_pool = [k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()]
if not _key_pool:
    _single = os.environ.get("API_KEY", "")
    if _single:
        _key_pool = [_single]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("hermes-bot")

# Graceful shutdown
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    logger.info("Received signal %s, shutting down...", signum)
    _shutdown = True


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------

_TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""


def tg(method: str, data: dict | None = None, timeout: int = 10) -> dict:
    """Call Telegram Bot API with error handling."""
    if not _TG_BASE:
        raise RuntimeError("BOT_TOKEN not set")
    url = f"{_TG_BASE}/{method}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read())
        if not result.get("ok", True):
            desc = result.get("description", "Unknown error")
            logger.warning("Telegram API %s failed: %s", method, desc)
        return result


def send(chat_id: int, text: str) -> None:
    """Send a text message, splitting if over 4096 chars."""
    if not text:
        return
    try:
        if len(text) <= 4096:
            tg("sendMessage", {"chat_id": chat_id, "text": text})
        else:
            for i in range(0, len(text), 4096):
                tg("sendMessage", {"chat_id": chat_id, "text": text[i : i + 4096]})
                time.sleep(0.1)  # avoid flood
    except Exception as e:
        logger.error("Send failed to %d: %s", chat_id, e)


def send_chat_action(chat_id: int, action: str = "typing") -> None:
    try:
        tg("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=5)
    except Exception:
        pass


def send_document(chat_id: int, file_path: str, caption: str = "") -> None:
    """Upload a file as document."""
    try:
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        boundary = f"----HermesBot{int(time.time() * 1000)}"
        fname = os.path.basename(file_path)
        # Sanitize filename
        fname = fname.replace('"', "_").replace("\r", "").replace("\n", "")
        with open(file_path, "rb") as f:
            fdata = f.read()
        caption_clean = caption.replace("\r", "").replace("\n", " ")[:1024]
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption_clean}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{_TG_BASE}/sendDocument", data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.error("Send document failed: %s", result.get("description"))
    except Exception as e:
        logger.error("Send document failed: %s", e)


# ---------------------------------------------------------------------------
# Memory (simple JSON)
# ---------------------------------------------------------------------------

MEMORY_FILE = "/tmp/hermes_memory.json"


def load_memory() -> dict:
    try:
        with open(MEMORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_memory(data: dict) -> None:
    try:
        tmp = MEMORY_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, MEMORY_FILE)  # atomic write
    except Exception as e:
        logger.error("Save memory failed: %s", e)


# ---------------------------------------------------------------------------
# File download from Telegram
# ---------------------------------------------------------------------------

def download_file(file_id: str, file_name: str) -> str | None:
    """Download a file from Telegram to /tmp/."""
    try:
        info = tg("getFile", {"file_id": file_id}, timeout=15)
        if not info.get("ok") or "result" not in info:
            logger.error("getFile failed: %s", info.get("description"))
            return None
        file_path = info["result"].get("file_path", "")
        if not file_path:
            return None
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        local = f"/tmp/{file_name}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(local, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return local
    except Exception as e:
        logger.error("Download failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Help text
# ---------------------------------------------------------------------------

HELP = """🤖 *Hermes Agent* — AI + OpenManus Tools

Just chat with me and I'll help!

*Commands:*
/clear — Clear history
/remember <text> — Save to memory
/recall — View memory
/health — System health
/help — This message

*What I can do:*
🔧 Execute shell commands
🌐 Browse & search the web
📁 Read/write/convert files
📊 Generate PPT presentations
🧠 Remember things for you

Or just ask me anything!"""


# ---------------------------------------------------------------------------
# Main bot loop
# ---------------------------------------------------------------------------

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        sys.exit(1)
    if not _key_pool:
        logger.error("API_KEY or API_KEYS not set!")
        sys.exit(1)

    # Signal handlers
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Parse allowed chats
    allowed: set[int] = set()
    if ALLOWED_CHATS_RAW:
        try:
            allowed = {int(c.strip()) for c in ALLOWED_CHATS_RAW.split(",") if c.strip()}
        except ValueError:
            logger.warning("Invalid ALLOWED_CHATS, allowing all")

    # Create agent
    agent = HermesAgent(
        api_keys=_key_pool,
        api_base=API_BASE,
        model=MODEL,
    )

    logger.info("=" * 50)
    logger.info("Hermes Bot starting — model: %s", MODEL)
    logger.info("API keys: %d", len(_key_pool))
    logger.info("Allowed chats: %s", allowed or "all")
    logger.info("=" * 50)

    # Get initial offset
    try:
        r = tg("getUpdates", {"offset": -1, "timeout": 1}, timeout=5)
        if r.get("result"):
            offset = r["result"][-1]["update_id"] + 1
        else:
            offset = 0
    except Exception:
        offset = 0

    # Rate limiting
    last_response: dict[int, float] = {}

    # Poll error backoff
    poll_errors = 0
    MAX_POLL_BACKOFF = 60

    while not _shutdown:
        try:
            result = tg("getUpdates", {"offset": offset, "timeout": 30}, timeout=60)
            poll_errors = 0  # reset on success

            for update in result.get("result", []):
                if _shutdown:
                    break
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg.get("chat", {}).get("id")
                if chat_id is None:
                    continue
                text = msg.get("text", "")

                # Handle documents
                if msg.get("document"):
                    if allowed and chat_id not in allowed:
                        continue
                    doc = msg["document"]
                    fid = doc.get("file_id", "")
                    fname = doc.get("file_name", "unknown")
                    fsize = doc.get("file_size", 0)
                    if fsize > 50 * 1024 * 1024:
                        send(chat_id, "File too large (max 50MB)")
                        continue
                    send(chat_id, "Downloading...")
                    local = download_file(fid, fname)
                    if local:
                        send(chat_id, f"📄 Saved: {local}")
                    else:
                        send(chat_id, "Failed to download file")
                    continue

                if not text or msg.get("from", {}).get("is_bot"):
                    continue
                if allowed and chat_id not in allowed:
                    continue

                # Rate limiting
                now = time.time()
                if chat_id in last_response and now - last_response[chat_id] < RATE_LIMIT:
                    continue
                last_response[chat_id] = now

                logger.info("[%d] %s", chat_id, text[:100])

                lower = text.lower().strip()

                # --- Commands ---
                if lower in ("/clear", "/reset"):
                    agent.clear_history(chat_id)
                    send(chat_id, "✅ History cleared.")
                    continue

                if lower in ("/start", "/help"):
                    send(chat_id, HELP)
                    continue

                if lower == "/health":
                    chat_count = len(agent._history)
                    send(chat_id, (
                        f"🟢 *Hermes Agent*\n"
                        f"Model: `{MODEL}`\n"
                        f"Keys: `{len(_key_pool)}`\n"
                        f"API: `{API_BASE}`\n"
                        f"Active chats: `{chat_count}`"
                    ))
                    continue

                if lower.startswith("/remember"):
                    content = text.replace("/remember", "").strip()
                    if not content:
                        send(chat_id, "Usage: /remember <what>")
                        continue
                    memory = load_memory()
                    key = hashlib.sha256(content.encode()).hexdigest()[:12]
                    memory[key] = {"text": content, "time": datetime.now().isoformat()}
                    save_memory(memory)
                    send(chat_id, f"✅ Remembered: {content}")
                    continue

                if lower == "/recall":
                    memory = load_memory()
                    if not memory:
                        send(chat_id, "No memories stored.")
                        continue
                    lines = []
                    total = 0
                    for v in memory.values():
                        entry = f"• {v['text']}"
                        if total + len(entry) > 3900:
                            lines.append("... (truncated)")
                            break
                        lines.append(entry)
                        total += len(entry) + 1
                    send(chat_id, "🧠 Memory:\n\n" + "\n".join(lines))
                    continue

                # --- Agent processing ---
                send_chat_action(chat_id)
                try:
                    # Periodic cleanup
                    removed = agent.cleanup_old_chats(max_chats=100)
                    if removed:
                        logger.info("Cleaned up %d old chat histories", removed)

                    response = agent.process(chat_id, text)
                    send(chat_id, response)
                except Exception as e:
                    logger.exception("Agent error for chat %d", chat_id)
                    send(chat_id, "⚠️ Error processing your request. Try again.")

        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down...")
            break
        except Exception as e:
            poll_errors += 1
            backoff = min(poll_errors * 2, MAX_POLL_BACKOFF)
            logger.error("Poll error (%d): %s — retrying in %ds", poll_errors, e, backoff)
            time.sleep(backoff)

    logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
