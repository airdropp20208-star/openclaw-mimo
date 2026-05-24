#!/usr/bin/env python3
"""
Hermes Bot — Telegram bot powered by Hermes Agent + OpenManus tools.

Usage:
    BOT_TOKEN=xxx API_KEY=xxx python bot.py
"""

import json
import logging
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
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


# ---------------------------------------------------------------------------
# Telegram API helpers
# ---------------------------------------------------------------------------

_TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def tg(method: str, data: dict | None = None, timeout: int = 10) -> dict:
    url = f"{_TG_BASE}/{method}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def send(chat_id: int, text: str) -> None:
    """Send a text message, splitting if over 4096 chars."""
    try:
        if len(text) <= 4096:
            tg("sendMessage", {"chat_id": chat_id, "text": text})
        else:
            for i in range(0, len(text), 4096):
                tg("sendMessage", {"chat_id": chat_id, "text": text[i : i + 4096]})
    except Exception as e:
        logger.error("Send failed: %s", e)


def send_chat_action(chat_id: int, action: str = "typing") -> None:
    try:
        tg("sendChatAction", {"chat_id": chat_id, "action": action})
    except Exception:
        pass


def send_document(chat_id: int, file_path: str, caption: str = "") -> None:
    """Upload a file as document."""
    try:
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        boundary = "----HermesBot"
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
        req = urllib.request.Request(f"{_TG_BASE}/sendDocument", data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
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
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# File download from Telegram
# ---------------------------------------------------------------------------

def download_file(file_id: str, file_name: str) -> str | None:
    """Download a file from Telegram to /tmp/."""
    try:
        info = tg("getFile", {"file_id": file_id})
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info['result']['file_path']}"
        local = f"/tmp/{file_name}"
        urllib.request.urlretrieve(url, local)
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
        offset = r["result"][-1]["update_id"] + 1 if r.get("result") else 0
    except Exception:
        offset = 0

    # Rate limiting
    last_response: dict[int, float] = {}

    while True:
        try:
            result = tg("getUpdates", {"offset": offset, "timeout": 30}, timeout=35)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
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
                send_chat_action(chat_id)

                lower = text.lower().strip()

                # --- Commands ---
                if lower in ("/clear", "/reset"):
                    agent.clear_history(chat_id)
                    send(chat_id, "✅ History cleared.")
                    continue

                if lower == "/start":
                    send(chat_id, HELP)
                    continue

                if lower == "/help":
                    send(chat_id, HELP)
                    continue

                if lower == "/health":
                    send(chat_id, (
                        f"🟢 *Hermes Agent*\n"
                        f"Model: `{MODEL}`\n"
                        f"Keys: `{len(_key_pool)}`\n"
                        f"API: `{API_BASE}`"
                    ))
                    continue

                if lower.startswith("/remember"):
                    content = text.replace("/remember", "").strip()
                    if not content:
                        send(chat_id, "Usage: /remember <what>")
                        continue
                    import hashlib
                    from datetime import datetime
                    memory = load_memory()
                    key = hashlib.md5(content.encode()).hexdigest()[:8]
                    memory[key] = {"text": content, "time": datetime.now().isoformat()}
                    save_memory(memory)
                    send(chat_id, f"✅ Remembered: {content}")
                    continue

                if lower == "/recall":
                    memory = load_memory()
                    if not memory:
                        send(chat_id, "No memories stored.")
                        continue
                    out = "🧠 Memory:\n\n" + "\n".join(
                        f"• {v['text']}" for v in memory.values()
                    )
                    send(chat_id, out[:4000])
                    continue

                # --- Agent processing ---
                try:
                    response = agent.process(chat_id, text)
                    send(chat_id, response)
                except Exception as e:
                    logger.exception("Agent error")
                    send(chat_id, f"⚠️ Error: {str(e)[:200]}")

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            break
        except Exception as e:
            logger.error("Poll error: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
