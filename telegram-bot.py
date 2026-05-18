#!/usr/bin/env python3
"""
Phantom Node - Telegram Bot (Anti-Spam v2)
Skip old messages, short responses, single message
"""
import os
import json
import logging
import time
import urllib.request
import urllib.error

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_KEY = os.environ.get("API_KEY", "")
API_BASE = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED_CHATS = os.environ.get("ALLOWED_CHATS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("phantom")

SYSTEM_PROMPT = (
    "You are a concise coding assistant. Rules:\n"
    "1. Reply in 1-3 sentences max\n"
    "2. No markdown headers\n"
    "3. No bullet lists\n"
    "4. Code: max 10 lines\n"
    "5. Be direct, no pleasantries\n"
    "6. If unclear, say: 'Làm rõ câu hỏi'"
)


def api_chat(message, history=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-10:])
    messages.append({"role": "user", "content": message})

    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        f"{API_BASE}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        content = data["choices"][0]["message"]["content"]
        if not content:
            return "⚠️ No response"
        if len(content) > 1500:
            content = content[:1497] + "..."
        return content.strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        log.error(f"API HTTP {e.code}: {body}")
        return f"⚠️ API error {e.code}"
    except Exception as e:
        log.error(f"API error: {e}")
        return f"⚠️ Error: {str(e)[:100]}"


def tg_request(method, data=None, timeout=10):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req_data = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=req_data)
    if req_data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def main():
    if not BOT_TOKEN or not API_KEY:
        log.error("BOT_TOKEN or API_KEY not set!")
        return

    allowed = set(int(cid.strip()) for cid in ALLOWED_CHATS.split(",") if cid.strip())
    log.info(f"Bot started! Model: {MODEL}")
    log.info(f"Allowed chats: {allowed or 'ALL'}")

    # SKIP ALL OLD MESSAGES - get latest offset first
    log.info("Skipping old messages...")
    try:
        result = tg_request("getUpdates", {"offset": -1, "timeout": 1}, timeout=5)
        if result.get("result"):
            offset = result["result"][-1]["update_id"] + 1
            log.info(f"Skipped to offset {offset}")
        else:
            offset = 0
            log.info("No old messages")
    except Exception as e:
        log.warning(f"Skip failed: {e}, starting fresh")
        offset = 0

    history = {}

    while True:
        try:
            result = tg_request("getUpdates", {"offset": offset, "timeout": 30}, timeout=35)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                user_id = str(msg.get("from", {}).get("id", ""))
                text = msg.get("text", "")
                if not text:
                    continue

                # Skip non-allowed users
                if allowed and chat_id not in allowed:
                    log.info(f"Blocked user {user_id}")
                    continue

                # Skip bot's own messages
                if msg.get("from", {}).get("is_bot"):
                    continue

                log.info(f"[{user_id}] {text[:80]}")

                # Commands
                if text.lower() in ("/clear", "/reset"):
                    history.pop(chat_id, None)
                    tg_request("sendMessage", {"chat_id": chat_id, "text": "✅ Memory cleared"})
                    continue

                if text.lower() == "/start":
                    tg_request("sendMessage", {"chat_id": chat_id, "text": "🤖 Bot ready! Send code or questions."})
                    continue

                if text.lower() == "/status":
                    status = f"🤖 Model: `{MODEL}`\n📡 API: `{API_BASE}`"
                    tg_request("sendMessage", {"chat_id": chat_id, "text": status, "parse_mode": "Markdown"})
                    continue

                # Typing indicator
                try:
                    tg_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                except Exception:
                    pass

                # Update history
                if chat_id not in history:
                    history[chat_id] = []
                history[chat_id].append({"role": "user", "content": text})

                # Get response
                response = api_chat(text, history[chat_id])
                history[chat_id].append({"role": "assistant", "content": response})

                # Trim history
                if len(history[chat_id]) > 20:
                    history[chat_id] = history[chat_id][-20:]

                # Send ONE message
                try:
                    tg_request("sendMessage", {"chat_id": chat_id, "text": response})
                except Exception as e:
                    log.error(f"Send failed: {e}")

                log.info(f"Replied to {chat_id} ({len(response)} chars)")

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
