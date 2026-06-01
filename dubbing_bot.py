#!/usr/bin/env python3
"""
🎬 OpenClaw Dubbing Studio — Professional Video Dubbing Bot

A dedicated Telegram bot for professional video dubbing.
Not a general chatbot. A specialized dubbing service.

Features:
- Send video → Auto dub to Vietnamese
- Send YouTube/Bilibili link → Download + Dub
- Batch dubbing queue
- Real-time progress tracking
- Professional subtitle generation
- Voice cloning support
"""

import asyncio
import json
import logging
import mimetypes
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_KEY = os.environ.get("API_KEY", "")
API_BASE = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED_CHATS = set()
ALLOWED_CHATS_RAW = os.environ.get("ALLOWED_CHATS", "")

if ALLOWED_CHATS_RAW:
    try:
        ALLOWED_CHATS = {int(c.strip()) for c in ALLOWED_CHATS_RAW.split(",") if c.strip()}
    except ValueError:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("studio")

_shutdown = False

def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True

# ---------------------------------------------------------------------------
# Telegram API
# ---------------------------------------------------------------------------

_TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

def tg(method: str, data: dict = None, timeout: int = 10) -> dict:
    url = f"{_TG_BASE}/{method}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())

def send(chat_id: int, text: str, parse_mode: str = None):
    try:
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if len(text) <= 4096:
            tg("sendMessage", payload)
        else:
            for i in range(0, len(text), 4096):
                payload["text"] = text[i:i+4096]
                tg("sendMessage", payload)
                time.sleep(0.1)
    except Exception as e:
        logger.error("Send failed: %s", e)

def send_video(chat_id: int, file_path: str, caption: str = ""):
    try:
        mime = mimetypes.guess_type(file_path)[0] or "video/mp4"
        boundary = f"----Studio{int(time.time()*1000)}"
        fname = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            fdata = f.read()
        caption = caption.replace("\r", "").replace("\n", " ")[:1024]
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="video"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{_TG_BASE}/sendVideo", data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        urllib.request.urlopen(req, timeout=120)
    except Exception as e:
        logger.error("Send video failed: %s", e)

def send_audio(chat_id: int, file_path: str, caption: str = ""):
    try:
        mime = mimetypes.guess_type(file_path)[0] or "audio/mpeg"
        boundary = f"----Studio{int(time.time()*1000)}"
        fname = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            fdata = f.read()
        caption = caption.replace("\r", "").replace("\n", " ")[:1024]
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="{fname}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(f"{_TG_BASE}/sendAudio", data=body)
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        urllib.request.urlopen(req, timeout=120)
    except Exception as e:
        logger.error("Send audio failed: %s", e)

def send_chat_action(chat_id: int, action: str = "typing"):
    try:
        tg("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=5)
    except Exception:
        pass

def download_file(file_id: str, file_name: str) -> str:
    try:
        info = tg("getFile", {"file_id": file_id}, timeout=15)
        if not info.get("ok"):
            return None
        file_path = info["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        safe_name = os.path.basename(file_name).replace("..", "_")
        local = f"/tmp/{safe_name}"
        req = urllib.request.Request(url)
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
# Job Queue
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, job_id: str, chat_id: int, video_path: str, source: str, target: str):
        self.job_id = job_id
        self.chat_id = chat_id
        self.video_path = video_path
        self.source = source
        self.target = target
        self.status = "queued"  # queued, processing, done, error
        self.progress = 0
        self.output = ""
        self.error = ""
        self.created_at = time.time()
    
    def to_dict(self):
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "source": self.source,
            "target": self.target,
            "created_at": self.created_at,
        }

class JobQueue:
    def __init__(self):
        self.jobs = {}
        self.queue = []
        self.processing = False
    
    def add(self, job: Job):
        self.jobs[job.job_id] = job
        self.queue.append(job)
        logger.info("Job added: %s (queue: %d)", job.job_id, len(self.queue))
    
    def get_next(self) -> Optional[Job]:
        for job in self.queue:
            if job.status == "queued":
                return job
        return None
    
    def update(self, job_id: str, **kwargs):
        if job_id in self.jobs:
            for k, v in kwargs.items():
                setattr(self.jobs[job_id], k, v)

queue = JobQueue()

# ---------------------------------------------------------------------------
# Dubbing Worker
# ---------------------------------------------------------------------------

def run_dub_job(job: Job):
    """Process a dubbing job."""
    from studio import DubStudio
    
    job.status = "processing"
    job.progress = 10
    send_chat_action(job.chat_id, "upload_video")
    send(job.chat_id, f"🎬 Đang xử lý...\n📝 {os.path.basename(job.video_path)}\n🌐 {job.source} → {job.target}")
    
    try:
        studio = DubStudio(api_key=API_KEY, api_base=API_BASE, model=MODEL)
        
        output_path = f"/tmp/dubbed_{job.job_id}.mp4"
        result = studio.dub(
            video_path=job.video_path,
            output_path=output_path,
            source=job.source,
            target=job.target,
            generate_subs=True,
        )
        
        if result["success"]:
            job.status = "done"
            job.output = result.get("file", output_path)
            job.progress = 100
            
            # Send result
            send_video(job.chat_id, job.output, caption=f"✅ Video đã dịch ({job.source}→{job.target})")
            
            # Send subtitle if exists
            sub_file = result.get("subtitle", "")
            if sub_file and os.path.exists(sub_file):
                send(job.chat_id, f"📄 Subtitle: {os.path.basename(sub_file)}")
        else:
            job.status = "error"
            job.error = result.get("output", "Unknown error")
            send(job.chat_id, f"❌ Lỗi: {job.error[:200]}")
    
    except Exception as e:
        job.status = "error"
        job.error = str(e)
        send(job.chat_id, f"❌ Lỗi xử lý: {str(e)[:200]}")
        logger.exception("Dub job failed")

# ---------------------------------------------------------------------------
# Language Detection
# ---------------------------------------------------------------------------

LANG_MAP = {
    "zh": "zh", "cn": "zh", "chinese": "zh", "trung": "zh", "tiếng trung": "zh",
    "en": "en", "english": "en", "anh": "en", "tiếng anh": "en",
    "ja": "ja", "japanese": "ja", "nhật": "ja", "tiếng nhật": "ja",
    "ko": "ko", "korean": "ko", "hàn": "ko", "tiếng hàn": "ko",
    "vi": "vi", "vietnamese": "vi", "việt": "vi", "tiếng việt": "vi",
}

def detect_source_lang(text: str) -> str:
    """Detect source language from user message."""
    text_lower = text.lower()
    
    # Check for explicit language mention
    for key, lang in LANG_MAP.items():
        if key in text_lower:
            return lang
    
    # Default: assume Chinese (most common for donghua)
    return "zh"

def parse_dub_command(text: str) -> dict:
    """Parse dubbing command from user message."""
    text_lower = text.lower().strip()
    
    # Extract source language
    source = "zh"
    target = "vi"
    
    # Check for language pairs
    if "sang tiếng việt" in text_lower or "sang việt" in text_lower or "→ vi" in text_lower:
        target = "vi"
    if "tiếng trung" in text_lower or "từ trung" in text_lower or "zh" in text_lower:
        source = "zh"
    elif "tiếng anh" in text_lower or "từ anh" in text_lower or "en" in text_lower:
        source = "en"
    elif "tiếng nhật" in text_lower or "từ nhật" in text_lower or "ja" in text_lower:
        source = "ja"
    elif "tiếng hàn" in text_lower or "từ hàn" in text_lower or "ko" in text_lower:
        source = "ko"
    
    return {"source": source, "target": target}

# ---------------------------------------------------------------------------
# Message Handlers
# ---------------------------------------------------------------------------

def handle_video(msg: dict, chat_id: int):
    """Handle video message."""
    video = msg.get("video") or msg.get("document")
    if not video:
        return
    
    fid = video.get("file_id", "")
    fname = video.get("file_name", f"video_{int(time.time())}.mp4")
    fsize = video.get("file_size", 0)
    
    if fsize > 100 * 1024 * 1024:
        send(chat_id, "❌ Video quá lớn (tối đa 100MB)")
        return
    
    # Parse caption for language
    caption = msg.get("caption", "")
    params = parse_dub_command(caption) if caption else {"source": "zh", "target": "vi"}
    
    send_chat_action(chat_id, "download")
    send(chat_id, "📥 Đang tải video...")
    
    local = download_file(fid, fname)
    if not local:
        send(chat_id, "❌ Không tải được video")
        return
    
    # Create job
    job_id = f"job_{int(time.time())}"
    job = Job(job_id, chat_id, local, params["source"], params["target"])
    queue.add(job)
    
    # Process immediately (single-threaded for simplicity)
    run_dub_job(job)

def handle_url(msg: dict, chat_id: int):
    """Handle URL message (YouTube, Bilibili, etc.)."""
    text = msg.get("text", "")
    
    # Extract URL
    url_match = re.search(r'https?://[^\s]+', text)
    if not url_match:
        return
    
    url = url_match.group(0)
    
    # Parse language
    params = parse_dub_command(text)
    
    send_chat_action(chat_id, "typing")
    send(chat_id, f"📥 Đang tải video...\n🔗 {url[:60]}...")
    
    # Download
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from tools_video import video_download
        
        dl_result = video_download(url, f"/tmp/url_{int(time.time())}.mp4")
        if not dl_result["success"]:
            send(chat_id, f"❌ Tải video thất bại: {dl_result['output'][:200]}")
            return
        
        local = dl_result["file"]
    except Exception as e:
        send(chat_id, f"❌ Lỗi tải video: {str(e)[:200]}")
        return
    
    # Create and run job
    job_id = f"job_{int(time.time())}"
    job = Job(job_id, chat_id, local, params["source"], params["target"])
    queue.add(job)
    run_dub_job(job)

def handle_command(text: str, chat_id: int):
    """Handle commands."""
    lower = text.lower().strip()
    
    if lower in ("/start", "/help"):
        send(chat_id, """🎬 *OpenClaw Dubbing Studio*

*Cách sử dụng:*

📹 *Gửi video:*
   Gửi video + caption: `dịch sang tiếng việt`
   → Bot tự động dịch và gửi lại

🔗 *Gửi link:*
   `https://youtu.be/... dịch sang tiếng việt`
   `https://www.bilibili.com/... dịch trung → vi`

📝 *Lệnh:*
   /status — Xem hàng đợi
   /help — Hướng dẫn

🌐 *Ngôn ngữ hỗ trợ:*
   🇨🇳 Trung (zh) → 🇻🇳 Việt
   🇬🇧 Anh (en) → 🇻🇳 Việt
   🇯🇵 Nhật (ja) → 🇻🇳 Việt
   🇰🇷 Hàn (ko) → 🇻🇳 Việt

⚡ *Tốc độ:*
   Video 5 phút ≈ 2-3 phút xử lý
   Video 30 phút ≈ 10-15 phút xử lý""")
    
    elif lower == "/status":
        queued = sum(1 for j in queue.jobs.values() if j.status == "queued")
        processing = sum(1 for j in queue.jobs.values() if j.status == "processing")
        done = sum(1 for j in queue.jobs.values() if j.status == "done")
        
        send(chat_id, f"""📊 *Trạng thái hệ thống*

⏳ Chờ xử lý: {queued}
🔄 Đang xử lý: {processing}
✅ Hoàn thành: {done}
📁 Tổng job: {len(queue.jobs)}""")
    
    else:
        return False
    return True

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _shutdown
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        sys.exit(1)
    if not API_KEY:
        logger.error("API_KEY not set!")
        sys.exit(1)
    
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    
    logger.info("=" * 50)
    logger.info("🎬 OpenClaw Dubbing Studio")
    logger.info("Model: %s", MODEL)
    logger.info("Allowed: %s", ALLOWED_CHATS or "all")
    logger.info("=" * 50)
    
    # Get offset
    try:
        r = tg("getUpdates", {"offset": -1, "timeout": 1}, timeout=5)
        offset = r["result"][-1]["update_id"] + 1 if r.get("result") else 0
    except Exception:
        offset = 0
    
    while not _shutdown:
        try:
            result = tg("getUpdates", {"offset": offset, "timeout": 30}, timeout=60)
            
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
                
                # Check allowed
                if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS:
                    continue
                
                text = msg.get("text", "")
                
                # Handle video
                if msg.get("video") or (msg.get("document") and msg["document"].get("file_name", "").endswith(('.mp4', '.avi', '.mov', '.mkv'))):
                    handle_video(msg, chat_id)
                    continue
                
                # Handle URL
                if text and ("http://" in text or "https://" in text):
                    handle_url(msg, chat_id)
                    continue
                
                # Handle commands
                if text and text.startswith("/"):
                    if handle_command(text, chat_id):
                        continue
                
                # Handle text (assume it's a dub request with URL)
                if text and not msg.get("from", {}).get("is_bot"):
                    send(chat_id, "📝 Gửi video hoặc link YouTube/Bilibili để dịch!")
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Poll error: %s", e)
            time.sleep(5)

if __name__ == "__main__":
    main()
