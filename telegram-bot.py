#!/usr/bin/env python3
"""
Phantom Node - Telegram Bot
Telegram → Open Interpreter → DeepSeek V4 (via ds2api) → FREE
"""
import os
import json
import logging
import time
import threading
import urllib.request
import urllib.error
from interpreter import interpreter

# Config
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DS2API_URL = os.environ.get("DS2API_URL", "http://localhost:5001/v1")
API_KEY = os.environ.get("API_KEY", "sk-phantom")
MODEL = os.environ.get("MODEL", "deepseek-v4-pro-nothinking")
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("phantom")

# Configure Open Interpreter to use ds2api
interpreter.llm.model = f"openai/{MODEL}"
interpreter.llm.api_key = API_KEY
interpreter.llm.api_base = DS2API_URL
interpreter.auto_run = True
interpreter.safe_mode = "off"
interpreter.system_message = """You are Phantom Node, a powerful AI coding assistant running on a GitHub Actions VPS.
You can write and execute code, install packages, and perform system tasks.
Be helpful, concise, and get things done efficiently.
When the user asks you to code something, write and execute it directly."""


def tg_request(method, data=None, timeout=10):
    """Telegram API request."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    req_data = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=req_data)
    if req_data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def chat_with_interpreter(message, history=None):
    """Send message to Open Interpreter and get response."""
    try:
        # Build conversation for interpreter
        messages = []
        if history:
            for msg in history[-10:]:  # last 10 messages
                messages.append({"role": msg["role"], "type": "message", "content": msg["content"]})

        messages.append({"role": "user", "type": "message", "content": message})

        # Run interpreter
        response_parts = []
        for chunk in interpreter.chat(messages, stream=True, display=False):
            if chunk.get("type") == "message" and chunk.get("role") == "assistant":
                if chunk.get("content"):
                    response_parts.append(chunk["content"])

        return "\n".join(response_parts) if response_parts else "No response from interpreter."

    except Exception as e:
        log.error(f"Interpreter error: {e}")
        return f"Error: {str(e)[:500]}"


def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN not set!")
        return

    allowed = set(uid.strip() for uid in ALLOWED_USERS.split(",") if uid.strip())
    log.info(f"Bot started! Model: {MODEL}")
    log.info(f"ds2api: {DS2API_URL}")
    log.info(f"Open Interpreter: configured")
    log.info(f"Allowed users: {allowed or 'ALL'}")

    offset = 0
    history = {}  # Per-user conversation history

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

                # Access control
                if allowed and user_id not in allowed:
                    log.info(f"Blocked user {user_id}")
                    continue

                log.info(f"[{user_id}] {text[:100]}")

                # Typing indicator
                try:
                    tg_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                except Exception:
                    pass

                # Handle /clear command
                if text.lower() in ("/clear", "/reset"):
                    history.pop(chat_id, None)
                    tg_request("sendMessage", {"chat_id": chat_id, "text": "Memory cleared."})
                    continue

                # Handle /status command
                if text.lower() == "/status":
                    status = f"""*Phantom Node Status*
Model: `{MODEL}`
API: `{DS2API_URL}`
History: {len(history.get(chat_id, []))} messages"""
                    tg_request("sendMessage", {"chat_id": chat_id, "text": status, "parse_mode": "Markdown"})
                    continue

                # Build history
                if chat_id not in history:
                    history[chat_id] = []
                history[chat_id].append({"role": "user", "content": text})

                # Call Open Interpreter
                response = chat_with_interpreter(text, history[chat_id])
                history[chat_id].append({"role": "assistant", "content": response})

                # Trim history
                if len(history[chat_id]) > 20:
                    history[chat_id] = history[chat_id][-20:]

                # Send reply (split if > 4096 chars)
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
