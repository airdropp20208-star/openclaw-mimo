#!/usr/bin/env python3
"""
Phantom Node - Telegram Bot
Telegram -> Xiaomi MiMo API (FREE)
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


def api_chat(message, history=None):
    messages = []
    if history:
        messages.extend(history[-20:])
    messages.append({"role": "user", "content": message})

    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "max_tokens": 4096,
        "temperature": 0.7,
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
        return content.strip() if content else "No response"
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        log.error(f"API HTTP {e.code}: {body}")
        return f"API error {e.code}"
    except Exception as e:
        log.error(f"API error: {e}")
        return f"Error: {str(e)[:200]}"


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
    log.info(f"Bot started! Model: {MODEL}")
    log.info(f"API: {API_BASE}")
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

                log.info(f"[{user_id}] {text[:100]}")

                try:
                    tg_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                except Exception:
                    pass

                if text.lower() in ("/clear", "/reset"):
                    history.pop(chat_id, None)
                    tg_request("sendMessage", {"chat_id": chat_id, "text": "Memory cleared."})
                    continue

                if text.lower() == "/status":
                    status = f"*Phantom Node*\nModel: `{MODEL}`\nAPI: `{API_BASE}`"
                    tg_request("sendMessage", {"chat_id": chat_id, "text": status, "parse_mode": "Markdown"})
                    continue

                if chat_id not in history:
                    history[chat_id] = []
                history[chat_id].append({"role": "user", "content": text})

                response = api_chat(text, history[chat_id])
                history[chat_id].append({"role": "assistant", "content": response})

                if len(history[chat_id]) > 20:
                    history[chat_id] = history[chat_id][-20:]

                for i in range(0, len(response), 4096):
                    chunk = response[i:i+4096]
                    try:
                        tg_request("sendMessage", {"chat_id": chat_id, "text": chunk})
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
