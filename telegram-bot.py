#!/usr/bin/env python3
"""
Phantom Node - Telegram Bot (Anti-Spam)
Short responses, single message per question
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
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("phantom")

# System prompt — force short responses
SYSTEM_PROMPT = (
    "You are a concise coding assistant. Rules:\n"
    "1. Reply in 1-3 sentences max\n"
    "2. No markdown headers (##, ###)\n"
    "3. No bullet point lists\n"
    "4. Code snippets: max 10 lines\n"
    "5. If user pastes code, fix it and return ONLY the fixed code, no explanation\n"
    "6. Never say 'I understand' or repeat user's question\n"
    "7. Be direct, no pleasantries"
)


def api_chat(message, history=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-10:])  # Keep last 10 messages only
    messages.append({"role": "user", "content": message})

    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": 500,  # Limit response length
        "temperature": 0.3,  # Lower = more focused
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
            return "No response"
        # Truncate if still too long (1500 chars max for Telegram)
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
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!")
        return
    if not API_KEY:
        log.error("API_KEY not set!")
        return

    allowed = set(uid.strip() for uid in ALLOWED_USERS.split(",") if uid.strip())
    log.info(f"Bot started! Model: {MODEL}, Max tokens: 500")
    log.info(f"Allowed users: {allowed or 'ALL'}")

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

                if allowed and user_id not in allowed:
                    continue

                log.info(f"[{user_id}] {text[:80]}")

                # Send typing indicator
                try:
                    tg_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                except Exception:
                    pass

                # Commands
                if text.lower() in ("/clear", "/reset"):
                    history.pop(chat_id, None)
                    tg_request("sendMessage", {"chat_id": chat_id, "text": "✅ Memory cleared"})
                    continue

                if text.lower() == "/status":
                    status = f"🤖 Model: `{MODEL}`\n📡 API: `{API_BASE}`"
                    tg_request("sendMessage", {"chat_id": chat_id, "text": status, "parse_mode": "Markdown"})
                    continue

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

                # Send ONE message only
                try:
                    tg_request("sendMessage", {
                        "chat_id": chat_id,
                        "text": response,
                    })
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
