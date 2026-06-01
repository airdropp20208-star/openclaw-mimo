#!/usr/bin/env python3
"""
OpenClaw MiMo Bot — AI Agent for Video Editing + Vietnamese TTS.

Features:
- Send video → Bot edits/sends back processed video
- Text messages → Agent processes with tools
- OmniVoice TTS for Vietnamese voice generation
- Video editing: trim, concat, overlay, subtitle, watermark, etc.

Usage:
    BOT_TOKEN=xxx API_KEY=xxx python bot.py
"""

import hashlib
import json
import logging
import mimetypes
import os
import signal
import subprocess
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
logger = logging.getLogger("openclaw-bot")

_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    logger.info("Received signal %s, shutting down...", signum)
    _shutdown = True


# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

_TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""


def tg(method: str, data: dict | None = None, timeout: int = 10) -> dict:
    if not _TG_BASE:
        raise RuntimeError("BOT_TOKEN not set")
    url = f"{_TG_BASE}/{method}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def send(chat_id: int, text: str) -> None:
    if not text:
        return
    try:
        if len(text) <= 4096:
            tg("sendMessage", {"chat_id": chat_id, "text": text})
        else:
            for i in range(0, len(text), 4096):
                tg("sendMessage", {"chat_id": chat_id, "text": text[i : i + 4096]})
                time.sleep(0.1)
    except Exception as e:
        logger.error("Send failed to %d: %s", chat_id, e)


def send_chat_action(chat_id: int, action: str = "typing") -> None:
    try:
        tg("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=5)
    except Exception:
        pass


def send_video(chat_id: int, file_path: str, caption: str = "") -> None:
    """Send video file to Telegram."""
    try:
        mime = mimetypes.guess_type(file_path)[0] or "video/mp4"
        boundary = f"----OpenClawBot{int(time.time() * 1000)}"
        fname = os.path.basename(file_path).replace('"', "_")
        with open(file_path, "rb") as f:
            fdata = f.read()
        caption_clean = caption.replace("\r", "").replace("\n", " ")[:1024]
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption_clean}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="video"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{_TG_BASE}/sendVideo", data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.error("Send video failed: %s", e)


def send_document(chat_id: int, file_path: str, caption: str = "") -> None:
    """Send document/file to Telegram."""
    try:
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        boundary = f"----OpenClawBot{int(time.time() * 1000)}"
        fname = os.path.basename(file_path).replace('"', "_")
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.error("Send document failed: %s", e)


def send_audio(chat_id: int, file_path: str, caption: str = "") -> None:
    """Send audio/voice file to Telegram."""
    try:
        mime = mimetypes.guess_type(file_path)[0] or "audio/mpeg"
        boundary = f"----OpenClawBot{int(time.time() * 1000)}"
        fname = os.path.basename(file_path).replace('"', "_")
        with open(file_path, "rb") as f:
            fdata = f.read()
        caption_clean = caption.replace("\r", "").replace("\n", " ")[:1024]
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption_clean}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{_TG_BASE}/sendAudio", data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.error("Send audio failed: %s", e)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

MEMORY_DIR = "/tmp/hermes_memory"


def load_memory(chat_id: int = 0) -> dict:
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        path = os.path.join(MEMORY_DIR, f"{chat_id}.json")
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_memory(data: dict, chat_id: int = 0) -> None:
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        path = os.path.join(MEMORY_DIR, f"{chat_id}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        logger.error("Save memory failed: %s", e)


# ---------------------------------------------------------------------------
# File download
# ---------------------------------------------------------------------------

def download_file(file_id: str, file_name: str) -> str | None:
    try:
        info = tg("getFile", {"file_id": file_id}, timeout=15)
        if not info.get("ok") or "result" not in info:
            return None
        file_path = info["result"].get("file_path", "")
        if not file_path:
            return None
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        safe_name = os.path.basename(file_name).replace("..", "_").replace("/", "_")
        if not safe_name:
            safe_name = f"download_{int(time.time())}"
        local = f"/tmp/{safe_name}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
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
# Video processing helpers
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def is_video_file(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in VIDEO_EXTENSIONS


def is_audio_file(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in AUDIO_EXTENSIONS


def is_image_file(filename: str) -> bool:
    ext = os.path.splitext(filename.lower())[1]
    return ext in IMAGE_EXTENSIONS


def get_file_type(filename: str) -> str:
    if is_video_file(filename):
        return "video"
    elif is_audio_file(filename):
        return "audio"
    elif is_image_file(filename):
        return "image"
    return "document"


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

HELP = """🤖 *OpenClaw MiMo* — AI Agent Video Editing + TTS

*Cách dùng:*
📹 Gửi video + ghi chú cần edit → Bot tự xử lý
🗣 Gõ "tạo giọng: ..." → Tạo giọng tiếng Việt
💬 Gõ câu hỏi → Agent trả lời

*Video Commands:*
• Gửi video + "cắt 5 giây đầu"
• Gửi video + "thêm chữ Xin Chào"
• Gửi video + "trích xuất âm thanh"
• Gửi video + "tạo GIF"

*TTS Commands:*
• "tạo giọng: Xin chào các bạn"
• "giọng nam: Hello world"
• "giọng nữ: Chào mừng"

*Other Commands:*
/start — Help
/clear — Clear history
/health — System info
/goals — View goals
/skills — Learned skills"""


# ---------------------------------------------------------------------------
# Goal command parser
# ---------------------------------------------------------------------------

def parse_goal_command(text: str) -> tuple[str, str]:
    """Parse '/goal <action> <args>' → (action, args)."""
    parts = text.split(maxsplit=2)
    if len(parts) >= 3:
        return parts[1].lower(), parts[2]
    elif len(parts) == 2:
        return parts[1].lower(), ""
    return "", ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _auto_setup():
    """Check and install missing dependencies."""
    try:
        import markitdown
        import pptx
    except ImportError:
        logger.info("Installing missing dependencies...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "markitdown[all]", "python-pptx", "browser-use", "playwright"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])

def main():
    _auto_setup()
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        sys.exit(1)
    if not _key_pool:
        logger.error("API_KEY or API_KEYS not set!")
        sys.exit(1)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    allowed: set[int] = set()
    if ALLOWED_CHATS_RAW:
        try:
            allowed = {int(c.strip()) for c in ALLOWED_CHATS_RAW.split(",") if c.strip()}
        except ValueError:
            pass

    agent = HermesAgent(
        api_keys=_key_pool,
        api_base=API_BASE,
        model=MODEL,
        autonomous_mode=True,
        learning_mode=True,
    )

    logger.info("=" * 50)
    logger.info("OpenClaw MiMo Bot — model: %s", MODEL)
    logger.info("API keys: %d", len(_key_pool))
    logger.info("Allowed chats: %s", allowed or "all")
    logger.info("=" * 50)

    # Get initial offset
    try:
        r = tg("getUpdates", {"offset": -1, "timeout": 1}, timeout=5)
        offset = r["result"][-1]["update_id"] + 1 if r.get("result") else 0
    except Exception:
        offset = 0

    last_response: dict[int, float] = {}
    poll_errors = 0

    while not _shutdown:
        try:
            result = tg("getUpdates", {"offset": offset, "timeout": 30}, timeout=60)
            poll_errors = 0

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

                # --- Handle VIDEO messages ---
                if msg.get("video"):
                    if allowed and chat_id not in allowed:
                        continue
                    video = msg["video"]
                    fid = video.get("file_id", "")
                    fname = video.get("file_name", f"video_{int(time.time())}.mp4")
                    fsize = video.get("file_size", 0)
                    
                    if fsize > 50 * 1024 * 1024:
                        send(chat_id, "❌ Video quá lớn (tối đa 50MB)")
                        continue
                    
                    send_chat_action(chat_id, "upload_video")
                    send(chat_id, "📥 Đang tải video...")
                    local = download_file(fid, fname)
                    
                    if not local:
                        send(chat_id, "❌ Không tải được video")
                        continue
                    
                    # Get instruction from caption or ask
                    instruction = msg.get("caption", "").strip()
                    if not instruction:
                        send(chat_id, 
                            "✅ Đã nhận video!\n\n"
                            "Ghi chú cần edit:\n"
                            "• `cắt 5 giây đầu`\n"
                            "• `thêm chữ Xin Chào`\n"
                            "• `trích xuất âm thanh`\n"
                            "• `tạo GIF`\n"
                            "• `đổi tốc độ 2x`\n"
                            "• `resize 720p`"
                        )
                        continue
                    
                    # Process video with agent
                    send_chat_action(chat_id, "typing")
                    send(chat_id, f"🎬 Đang xử lý video...\n📝 Yêu cầu: {instruction}")
                    
                    try:
                        # Build prompt for agent
                        video_prompt = f"File video đã tải về: {local}\n\nYêu cầu xử lý: {instruction}\n\nHãy sử dụng các tool video_edit, video_info, video_composite để xử lý video. Sau khi xong, thông báo đường dẫn file kết quả."
                        
                        response = agent.process(chat_id, video_prompt)
                        
                        if not response or not response.strip():
                            response = "⚠️ Xử lý video thất bại"
                        
                        # Check if there's a result file to send
                        # Look for file paths in response
                        import re
                        file_matches = re.findall(r'(/[^\s\'"]+\.(mp4|avi|mov|mkv|gif|mp3|wav|png|jpg))', response)
                        
                        if file_matches:
                            for file_path, ext in file_matches:
                                if os.path.exists(file_path):
                                    if ext in VIDEO_EXTENSIONS or ext == 'gif':
                                        send_video(chat_id, file_path, caption="🎬 Video đã xử lý")
                                    elif ext in AUDIO_EXTENSIONS:
                                        send_audio(chat_id, file_path, caption="🔊 Audio đã trích xuất")
                                    elif ext in IMAGE_EXTENSIONS:
                                        send(chat_id, f"📎 File: {file_path}")
                        
                        send(chat_id, response)
                    except Exception as e:
                        logger.exception("Video processing error")
                        send(chat_id, f"❌ Lỗi xử lý video: {str(e)[:200]}")
                    
                    continue

                # --- Handle DOCUMENT messages ---
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
                        file_type = get_file_type(fname)
                        send(chat_id, f"📄 Saved: {local}\nType: {file_type}")
                    else:
                        send(chat_id, "Failed to download file")
                    continue

                # --- Handle VOICE messages ---
                if msg.get("voice"):
                    if allowed and chat_id not in allowed:
                        continue
                    voice = msg["voice"]
                    fid = voice.get("file_id", "")
                    fsize = voice.get("file_size", 0)
                    if fsize > 20 * 1024 * 1024:
                        send(chat_id, "Voice quá lớn (tối đa 20MB)")
                        continue
                    local = download_file(fid, f"voice_{int(time.time())}.ogg")
                    if local:
                        send(chat_id, f"🎤 Voice saved: {local}")
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
                    planner = agent._get_planner(chat_id)
                    active_goals = len(planner.get_active_goals())
                    send(chat_id, (
                        f"🟢 *OpenClaw MiMo*\n"
                        f"Model: `{MODEL}`\n"
                        f"Keys: `{len(_key_pool)}`\n"
                        f"API: `{API_BASE}`\n"
                        f"Active chats: `{chat_count}`\n"
                        f"Active goals: `{active_goals}`\n"
                        f"Learning: `on`\n"
                        f"Autonomous: `on`"
                    ))
                    continue

                # --- Goal commands ---
                if lower in ("/goals", "/goal"):
                    send(chat_id, agent.get_goals(chat_id))
                    continue

                if lower.startswith("/goal "):
                    action, args = parse_goal_command(text)
                    if action == "add":
                        if not args:
                            send(chat_id, "Usage: /goal add <description>")
                        else:
                            send(chat_id, "🤔 Planning...")
                            response = agent.add_goal(chat_id, args)
                            send(chat_id, response)
                    elif action == "done":
                        if not args:
                            send(chat_id, "Usage: /goal done <subtask_id>")
                        else:
                            send(chat_id, agent.complete_subtask(chat_id, args))
                    elif action == "delete":
                        if not args:
                            send(chat_id, "Usage: /goal delete <goal_id>")
                        else:
                            send(chat_id, agent.delete_goal(chat_id, args))
                    elif action == "pause":
                        if not args:
                            send(chat_id, "Usage: /goal pause <goal_id>")
                        else:
                            send(chat_id, agent.pause_goal(chat_id, args))
                    elif action == "resume":
                        if not args:
                            send(chat_id, "Usage: /goal resume <goal_id>")
                        else:
                            send(chat_id, agent.resume_goal(chat_id, args))
                    else:
                        send(chat_id, f"Unknown action: {action}\nUse: add, done, delete, pause, resume")
                    continue

                if lower == "/actions":
                    send(chat_id, "🤔 Analyzing goals...")
                    send(chat_id, agent.get_next_actions(chat_id))
                    continue

                # --- Learning commands ---
                if lower == "/skills":
                    send(chat_id, agent.get_skills(chat_id))
                    continue

                if lower.startswith("/skill "):
                    skill_id = text.split(maxsplit=1)[1].strip()
                    send(chat_id, agent.get_skill(chat_id, skill_id))
                    continue

                if lower == "/stats":
                    send(chat_id, agent.get_learning_stats(chat_id))
                    continue

                if lower == "/learn":
                    send(chat_id, "🧠 Analyzing recent tasks...")
                    stats = agent.get_learning_stats(chat_id)
                    send(chat_id, stats)
                    continue

                # --- Memory commands ---
                if lower.startswith("/remember"):
                    content = text.replace("/remember", "").strip()
                    if not content:
                        send(chat_id, "Usage: /remember <what>")
                        continue
                    memory = load_memory(chat_id)
                    key = hashlib.sha256(content.encode()).hexdigest()[:12]
                    memory[key] = {"text": content, "time": datetime.now().isoformat()}
                    save_memory(memory, chat_id)
                    send(chat_id, f"✅ Remembered: {content}")
                    continue

                if lower == "/recall":
                    memory = load_memory(chat_id)
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

                # --- TTS shortcut ---
                if lower.startswith("tạo giọng:") or lower.startswith("tạo giọng :"):
                    tts_text = text.split(":", 1)[1].strip() if ":" in text else ""
                    if not tts_text:
                        send(chat_id, "Usage: tạo giọng: <văn bản>")
                        continue
                    send_chat_action(chat_id, "typing")
                    try:
                        from tools_video import tts_generate
                        result = tts_generate(tts_text, engine="edge", voice="vi-VN-HoaiMyNeural")
                        if result["success"] and result.get("file"):
                            send_audio(chat_id, result["file"], caption="🗣 Giọng tiếng Việt")
                        else:
                            send(chat_id, f"❌ TTS failed: {result['output']}")
                    except Exception as e:
                        send(chat_id, f"❌ TTS error: {str(e)[:200]}")
                    continue

                if lower.startswith("giọng nam:") or lower.startswith("giọng nam :"):
                    tts_text = text.split(":", 1)[1].strip() if ":" in text else ""
                    if not tts_text:
                        send(chat_id, "Usage: giọng nam: <văn bản>")
                        continue
                    send_chat_action(chat_id, "typing")
                    try:
                        from tools_video import tts_generate
                        result = tts_generate(tts_text, engine="edge", voice="vi-VN-NamMinhNeural")
                        if result["success"] and result.get("file"):
                            send_audio(chat_id, result["file"], caption="🗣 Giọng nam")
                        else:
                            send(chat_id, f"❌ TTS failed: {result['output']}")
                    except Exception as e:
                        send(chat_id, f"❌ TTS error: {str(e)[:200]}")
                    continue

                if lower.startswith("giọng nữ:") or lower.startswith("giọng nữ :"):
                    tts_text = text.split(":", 1)[1].strip() if ":" in text else ""
                    if not tts_text:
                        send(chat_id, "Usage: giọng nữ: <văn bản>")
                        continue
                    send_chat_action(chat_id, "typing")
                    try:
                        from tools_video import tts_generate
                        result = tts_generate(tts_text, engine="edge", voice="vi-VN-HoaiMyNeural")
                        if result["success"] and result.get("file"):
                            send_audio(chat_id, result["file"], caption="🗣 Giọng nữ")
                        else:
                            send(chat_id, f"❌ TTS failed: {result['output']}")
                    except Exception as e:
                        send(chat_id, f"❌ TTS error: {str(e)[:200]}")
                    continue

                # --- Agent processing ---
                send_chat_action(chat_id)
                try:
                    removed = agent.cleanup_old_chats(max_chats=100)
                    if removed:
                        logger.info("Cleaned up %d old chat histories", removed)

                    start_time = time.time()
                    response = agent.process(chat_id, text)
                    
                    if not response or not response.strip():
                        response = "⚠️ Agent returned an empty response."
                    
                    send(chat_id, response)
                except Exception as e:
                    logger.exception("Agent error for chat %d", chat_id)
                    error_msg = f"⚠️ Error: {str(e)}"
                    if "401" in error_msg:
                        error_msg = "⚠️ API Key error. Please check your configuration."
                    elif "timeout" in error_msg.lower():
                        error_msg = "⚠️ Request timed out."
                    send(chat_id, error_msg)

        except KeyboardInterrupt:
            logger.info("Interrupted, shutting down...")
            break
        except Exception as e:
            poll_errors += 1
            backoff = min(poll_errors * 2, 60)
            logger.error("Poll error (%d): %s — retrying in %ds", poll_errors, e, backoff)
            time.sleep(backoff)


if __name__ == "__main__":
    main()
