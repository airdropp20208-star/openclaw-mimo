#!/usr/bin/env python3
"""
Phantom Node - Telegram Bot
Telegram → Open Interpreter → DeepSeek V4 (FREE via ds2api)
"""
import os
import subprocess
import json
import logging
import time

# Config
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ALLOWED_USERS = os.environ.get("ALLOWED_USERS", "").split(",")
WORKDIR = os.environ.get("WORKDIR", os.path.expanduser("~"))
DS2API_URL = os.environ.get("DS2API_URL", "http://localhost:5001/v1")
DS2API_KEY = os.environ.get("DS2API_KEY", "sk-phantom")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("phantom-bot")


def call_claude(message: str, timeout: int = 300) -> str:
    """Call Claude Code CLI with DeepSeek backend."""
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = DS2API_URL
    env["ANTHROPIC_API_KEY"] = DS2API_KEY
    env["HOME"] = os.path.expanduser("~")
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")

    cmd = [
        "claude", "-p", message,
        "--output-format", "json",
        "--max-turns", "20",
        "--bare",
    ]

    try:
        logger.info(f"Claude: {message[:80]}...")
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=WORKDIR, env=env,
        )
        logger.info(f"Exit: {result.returncode}")

        if result.returncode != 0:
            err = result.stderr[:500] if result.stderr else "No stderr"
            return f"Error ({result.returncode}): {err}"

        try:
            data = json.loads(result.stdout)
            return data.get("result", result.stdout[:3000])
        except json.JSONDecodeError:
            return result.stdout[:3000] or "No response"

    except subprocess.TimeoutExpired:
        return "Timeout"
    except FileNotFoundError:
        return "Error: claude not found"
    except Exception as e:
        return f"Error: {str(e)[:200]}"


def send_telegram(api: str, chat_id: int, text: str):
    """Send message to Telegram."""
    url = f"{api}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": text[:4000],
    }).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"}
        ), timeout=10)
    except:
        pass


def main():
    """Telegram bot - long polling."""
    import urllib.request

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    API = f"https://api.telegram.org/bot{BOT_TOKEN}"
    offset = 0

    logger.info("Phantom Bot started!")
    logger.info(f"DS2API: {DS2API_URL}")

    while True:
        try:
            url = f"{API}/getUpdates?offset={offset}&timeout=30"
            with urllib.request.urlopen(url, timeout=35) as resp:
                data = json.loads(resp.read())

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                user_id = str(msg.get("from", {}).get("id", ""))
                text = msg.get("text", "")

                if ALLOWED_USERS != [""] and user_id not in ALLOWED_USERS:
                    continue

                if not text:
                    continue

                logger.info(f"[{user_id}] {text[:100]}")

                # Typing indicator
                try:
                    urllib.request.urlopen(urllib.request.Request(
                        f"{API}/sendChatAction",
                        data=json.dumps({"chat_id": chat_id, "action": "typing"}).encode(),
                        headers={"Content-Type": "application/json"}
                    ), timeout=5)
                except:
                    pass

                # Call Claude Code
                response = call_claude(text)
                send_telegram(API, chat_id, response)
                logger.info(f"Replied to {chat_id}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
