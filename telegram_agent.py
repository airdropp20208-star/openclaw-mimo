#!/usr/bin/env python3
"""
OpenClaw MiMo — Telegram Dubbing Agent
========================================
Professional dubbing bot that works like a real agent.
- Receives video URLs or files via Telegram
- Processes with full dubbing pipeline
- Returns dubbed video with subtitles
- Supports voice cloning, emotion control
- Tracks job history and status

Usage:
  BOT_TOKEN=xxx python3 telegram_agent.py
"""

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

from telegram import (
    Bot,
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode, ChatAction

# ─── Config ────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ALLOWED_CHATS = [int(x) for x in os.getenv("ALLOWED_CHATS", "").split(",") if x.strip()]
DATA_DIR = os.getenv("DATA_DIR", "/tmp/openclaw-mimo")
LOG_FILE = os.path.join(DATA_DIR, "agent.log")

# APIs
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
OMNIVOICE_URL = os.getenv("OMNIVOICE_API_URL", "")
OMNIVOICE_KEY = os.getenv("OMNIVOICE_API_KEY", "")

# Default settings
DEFAULT_SOURCE_LANG = "Chinese"
DEFAULT_TARGET_LANG = "Vietnamese"
DEFAULT_TTS_ENGINE = "omnivoice"
DEFAULT_VOICE = "female, vietnamese accent, natural"
DEFAULT_EMOTION = "neutral"
DEFAULT_SUBTITLE_STYLE = "professional"

# AGI Brain
try:
    from brain import AGIBrain
    HAS_BRAIN = True
except ImportError:
    HAS_BRAIN = False


# ─── State Management ──────────────────────────────────────────────
class AgentState:
    """Per-user agent state."""
    
    def __init__(self):
        self.jobs = {}  # job_id -> {status, result, ...}
        self.settings = {}  # user_id -> settings
        self.current_job = None
    
    def get_settings(self, user_id: int) -> dict:
        if user_id not in self.settings:
            self.settings[user_id] = {
                "source_lang": DEFAULT_SOURCE_LANG,
                "target_lang": DEFAULT_TARGET_LANG,
                "tts_engine": DEFAULT_TTS_ENGINE,
                "voice": DEFAULT_VOICE,
                "emotion": DEFAULT_EMOTION,
                "subtitle_style": DEFAULT_SUBTITLE_STYLE,
            }
        return self.settings[user_id]
    
    def create_job(self, user_id: int, video_url: str = "", video_path: str = "") -> str:
        job_id = f"job_{int(time.time())}_{user_id}"
        self.jobs[job_id] = {
            "id": job_id,
            "user_id": user_id,
            "video_url": video_url,
            "video_path": video_path,
            "status": "pending",
            "created_at": time.time(),
            "result": None,
            "error": None,
        }
        return job_id
    
    def update_job(self, job_id: str, **kwargs):
        if job_id in self.jobs:
            self.jobs[job_id].update(kwargs)


state = AgentState()


# ─── Logging ───────────────────────────────────────────────────────
def log(msg, level="INFO"):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ─── Access Control ────────────────────────────────────────────────
def is_allowed(update: Update) -> bool:
    if not ALLOWED_CHATS:
        return True
    return update.effective_chat.id in ALLOWED_CHATS


# ─── Command Handlers ──────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_allowed(update):
        await update.message.reply_text("⛔ Access denied.")
        return
    
    await update.message.reply_text(
        "🎬 **OpenClaw MiMo — Dubbing Agent**\n\n"
        "Gửi video URL hoặc file video để vietsub tự động.\n\n"
        "**Lệnh:**\n"
        "/dub `<url>` — Vietsub video từ URL\n"
        "/settings — Xem/sửa cài đặt\n"
        "/status — Xem trạng thái jobs\n"
        "/analyze <url> — 🧠 Phân tích video\n        /think <text> — 🧠 Suy nghi ve dich\n        /brain — 🧠 Xem stats brain\n        /help — Hướng dẫn sử dụng\n\n"
        "**Cài đặt hiện tại:**\n"
        f"• Ngôn ngữ: {DEFAULT_SOURCE_LANG} → {DEFAULT_TARGET_LANG}\n"
        f"• TTS: {DEFAULT_TTS_ENGINE}\n"
        f"• Giọng: {DEFAULT_VOICE}\n"
        f"• Emotion: {DEFAULT_EMOTION}\n"
        f"• Subtitle: {DEFAULT_SUBTITLE_STYLE}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    if not is_allowed(update):
        return
    
    await update.message.reply_text(
        "📖 **Hướng dẫn sử dụng**\n\n"
        "**Cách dùng:**\n"
        "1. Gửi URL video (YouTube, Bilibili, TikTok...)\n"
        "2. Hoặc gõ `/dub <url>`\n"
        "3. Chờ bot xử lý (2-10 phút tùy độ dài)\n"
        "4. Nhận video đã vietsub\n\n"
        "**Lệnh:**\n"
        "/dub `<url>` — Vietsub video\n"
        "/dub `<url>` `--emotion happy` — Vietsub với emotion\n"
        "/dub `<url>` `--voice male, vietnamese` — Chọn giọng\n"
        "/settings — Xem/sửa cài đặt\n"
        "/status — Xem trạng thái\n"
        "/cancel — Hủy job đang chạy\n\n"
        "**Emotion:** neutral, happy, sad, angry, excited, calm\n\n"
        "**Ví dụ:**\n"
        "`/dub https://youtube.com/watch?v=xxx --emotion happy`\n"
        "`/dub https://bilibili.com/video/xxx --voice male, southern vietnamese`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_dub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /dub command."""
    if not is_allowed(update):
        await update.message.reply_text("⛔ Access denied.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ Cung cấp URL video.\n"
            "Ví dụ: `/dub https://youtube.com/watch?v=xxx`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    
    url = context.args[0]
    settings = state.get_settings(update.effective_chat.id)
    
    # Parse optional args
    for arg in context.args[1:]:
        if arg.startswith("--emotion"):
            idx = context.args.index(arg)
            if idx + 1 < len(context.args):
                settings["emotion"] = context.args[idx + 1]
        elif arg.startswith("--voice"):
            idx = context.args.index(arg)
            if idx + 1 < len(context.args):
                settings["voice"] = " ".join(context.args[idx + 1:])
    
    await _start_dub_job(update, url, settings)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /settings command."""
    if not is_allowed(update):
        return
    
    settings = state.get_settings(update.effective_chat.id)
    
    keyboard = [
        [
            InlineKeyboardButton("🌐 Ngôn ngữ", callback_data="set_lang"),
            InlineKeyboardButton("🗣️ TTS Engine", callback_data="set_tts"),
        ],
        [
            InlineKeyboardButton("🎤 Giọng", callback_data="set_voice"),
            InlineKeyboardButton("😊 Emotion", callback_data="set_emotion"),
        ],
        [
            InlineKeyboardButton("📄 Subtitle", callback_data="set_subtitle"),
        ],
    ]
    
    await update.message.reply_text(
        f"⚙️ **Cài đặt hiện tại:**\n\n"
        f"• Nguồn: {settings['source_lang']}\n"
        f"• Đích: {settings['target_lang']}\n"
        f"• TTS: {settings['tts_engine']}\n"
        f"• Giọng: {settings['voice']}\n"
        f"• Emotion: {settings['emotion']}\n"
        f"• Subtitle: {settings['subtitle_style']}\n\n"
        f"Nhấn nút để thay đổi:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    if not is_allowed(update):
        return
    
    user_jobs = [
        j for j in state.jobs.values()
        if j["user_id"] == update.effective_chat.id
    ]
    
    if not user_jobs:
        await update.message.reply_text("📭 Chưa có jobs nào.")
        return
    
    lines = []
    for j in user_jobs[-5:]:  # Last 5 jobs
        status_emoji = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}.get(j["status"], "❓")
        elapsed = time.time() - j["created_at"]
        lines.append(
            f"{status_emoji} `{j['id'][:20]}...` — {j['status']} ({elapsed:.0f}s)"
        )
    
    await update.message.reply_text(
        "📊 **Jobs gần đây:**\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Message Handlers ──────────────────────────────────────────────
async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages containing URLs."""
    if not is_allowed(update):
        return
    
    text = update.message.text.strip()
    settings = state.get_settings(update.effective_chat.id)
    
    # Check if it's a URL
    if text.startswith("http") and any(domain in text for domain in [
        "youtube.com", "youtu.be", "bilibili.com", "b23.tv",
        "tiktok.com", "instagram.com", "twitter.com", "x.com",
        "facebook.com", "vimeo.com", "dailymotion.com",
    ]):
        await _start_dub_job(update, text, settings)


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded video files."""
    if not is_allowed(update):
        return
    
    video = update.message.video or update.message.document
    if not video:
        return
    
    await update.message.reply_text("📹 Đang tải video...")
    
    # Download video
    os.makedirs(DATA_DIR, exist_ok=True)
    file_path = os.path.join(DATA_DIR, f"input_{int(time.time())}.mp4")
    
    tg_file = await context.bot.get_file(video.file_id)
    await tg_file.download_to_drive(file_path)
    
    settings = state.get_settings(update.effective_chat.id)
    await _start_dub_job(update, "", settings, video_path=file_path)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()
    
    if not is_allowed(update):
        return
    
    data = query.data
    settings = state.get_settings(update.effective_chat.id)
    
    if data == "set_lang":
        keyboard = [
            [
                InlineKeyboardButton("🇨🇳 Chinese", callback_data="lang_Chinese"),
                InlineKeyboardButton("🇯🇵 Japanese", callback_data="lang_Japanese"),
                InlineKeyboardButton("🇰🇷 Korean", callback_data="lang_Korean"),
            ],
        ]
        await query.edit_message_text(
            "🌐 Chọn ngôn ngữ nguồn:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    
    elif data.startswith("lang_"):
        lang = data.replace("lang_", "")
        settings["source_lang"] = lang
        await query.edit_message_text(f"✅ Đã set ngôn ngữ nguồn: {lang}")
    
    elif data == "set_tts":
        keyboard = [
            [
                InlineKeyboardButton("🎤 OmniVoice (Clone)", callback_data="tts_omnivoice"),
                InlineKeyboardButton("🔊 Edge TTS (Free)", callback_data="tts_edge"),
            ],
        ]
        await query.edit_message_text(
            "🗣️ Chọn TTS engine:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    
    elif data.startswith("tts_"):
        engine = data.replace("tts_", "")
        settings["tts_engine"] = engine
        await query.edit_message_text(f"✅ Đã set TTS: {engine}")
    
    elif data == "set_voice":
        keyboard = [
            [
                InlineKeyboardButton("👩 Nữ tự nhiên", callback_data="voice_female, vietnamese accent, natural"),
                InlineKeyboardButton("👨 Nam tự nhiên", callback_data="voice_male, vietnamese accent, natural"),
            ],
            [
                InlineKeyboardButton("👩 Nữ miền Nam", callback_data="voice_female, southern vietnamese accent"),
                InlineKeyboardButton("👨 Nam miền Nam", callback_data="voice_male, southern vietnamese accent"),
            ],
        ]
        await query.edit_message_text(
            "🎤 Chọn giọng đọc:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    
    elif data.startswith("voice_"):
        voice = data.replace("voice_", "")
        settings["voice"] = voice
        await query.edit_message_text(f"✅ Đã set giọng: {voice}")
    
    elif data == "set_emotion":
        keyboard = [
            [
                InlineKeyboardButton("😐 Neutral", callback_data="emo_neutral"),
                InlineKeyboardButton("😊 Happy", callback_data="emo_happy"),
                InlineKeyboardButton("😢 Sad", callback_data="emo_sad"),
            ],
            [
                InlineKeyboardButton("😠 Angry", callback_data="emo_angry"),
                InlineKeyboardButton("🎉 Excited", callback_data="emo_excited"),
                InlineKeyboardButton("😌 Calm", callback_data="emo_calm"),
            ],
        ]
        await query.edit_message_text(
            "😊 Chọn emotion:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    
    elif data.startswith("emo_"):
        emo = data.replace("emo_", "")
        settings["emotion"] = emo
        await query.edit_message_text(f"✅ Đã set emotion: {emo}")
    
    elif data == "set_subtitle":
        keyboard = [
            [
                InlineKeyboardButton("Professional", callback_data="sub_professional"),
                InlineKeyboardButton("Anime", callback_data="sub_anime"),
                InlineKeyboardButton("Minimal", callback_data="sub_minimal"),
            ],
        ]
        await query.edit_message_text(
            "📄 Chọn style subtitle:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    
    elif data.startswith("sub_"):
        style = data.replace("sub_", "")
        settings["subtitle_style"] = style
        await query.edit_message_text(f"✅ Đã set subtitle: {style}")


# ─── Dubbing Job ───────────────────────────────────────────────────
async def _start_dub_job(update: Update, url: str, settings: dict, video_path: str = ""):
    """Start a dubbing job."""
    user_id = update.effective_chat.id
    
    # Create job
    job_id = state.create_job(user_id, video_url=url, video_path=video_path)
    state.update_job(job_id, status="running")
    
    # Send status message
    status_msg = await update.message.reply_text(
        f"🎬 **Bắt đầu vietsub...**\n\n"
        f"• URL: `{url or 'File upload'}`\n"
        f"• Ngôn ngữ: {settings['source_lang']} → {settings['target_lang']}\n"
        f"• TTS: {settings['tts_engine']}\n"
        f"• Emotion: {settings['emotion']}\n\n"
        f"⏳ Đang xử lý... (2-10 phút)",
        parse_mode=ParseMode.MARKDOWN,
    )
    
    # Run pipeline in thread
    asyncio.create_task(_run_dub_pipeline(job_id, status_msg, settings))


async def _run_dub_pipeline(job_id: str, status_msg, settings: dict):
    """Run the dubbing pipeline."""
    job = state.jobs[job_id]
    
    try:
        # Update status
        await status_msg.edit_text(
            status_msg.text_markup.replace("⏳ Đang xử lý...", "📥 Đang tải video..."),
            parse_mode=ParseMode.MARKDOWN,
        )
        
        # Import and run engine
        sys.path.insert(0, os.path.dirname(__file__))
        from engines.dubbing_engine import run_pipeline, DubConfig
        
        output_dir = os.path.join(DATA_DIR, job_id)
        os.makedirs(output_dir, exist_ok=True)
        
        config = DubConfig(
            mimo_api_key=MIMO_API_KEY,
            mimo_api_base=MIMO_API_BASE,
            mimo_model=MIMO_MODEL,
            omnivoice_url=OMNIVOICE_URL,
            omnivoice_key=OMNIVOICE_KEY,
            tts_engine=settings["tts_engine"],
            tts_instruct=settings["voice"],
            tts_emotion=settings["emotion"],
            subtitle_style=settings["subtitle_style"],
            output_dir=output_dir,
        )
        
        result = run_pipeline(
            url=job["video_url"],
            video_path=job["video_path"],
            source_lang=settings["source_lang"],
            target_lang=settings["target_lang"],
            config=config,
        )
        
        if result["success"]:
            state.update_job(job_id, status="done", result=result)
            
            # Send result
            output_video = result["output_video"]
            if os.path.exists(output_video):
                await status_msg.edit_text(
                    f"✅ **Vietsub thành công!**\n\n"
                    f"• Thời gian: {result['processing_time']:.0f}s\n"
                    f"• Số segments: {result['segments']}\n"
                    f"• Video: `{output_video}`",
                    parse_mode=ParseMode.MARKDOWN,
                )
                
                # Send video
                with open(output_video, "rb") as f:
                    await status_msg.reply_video(
                        video=f,
                        caption=f"🎬 {job['video_url'][:50]}...",
                    )
                
                # Send subtitles
                srt_path = result.get("output_srt", "")
                if srt_path and os.path.exists(srt_path):
                    with open(srt_path, "rb") as f:
                        await status_msg.reply_document(
                            document=f,
                            filename="subtitles.srt",
                            caption="📄 Phụ đề SRT",
                        )
            else:
                await status_msg.edit_text("❌ Không tìm thấy output video.")
        else:
            state.update_job(job_id, status="failed", error=result.get("error"))
            await status_msg.edit_text(
                f"❌ **Vietsub thất bại:**\n`{result.get('error', 'Unknown error')}`",
                parse_mode=ParseMode.MARKDOWN,
            )
    
    except Exception as e:
        log(f"Job {job_id} failed: {e}\n{traceback.format_exc()}")
        state.update_job(job_id, status="failed", error=str(e))
        await status_msg.edit_text(
            f"❌ **Lỗi:**\n`{str(e)[:500]}`",
            parse_mode=ParseMode.MARKDOWN,
        )


# ─── Brain Commands ─────────────────────────────────────────────────
async def cmd_think(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text(
            "S\u01b0 d\u1ee5ng: /think <text c\u1ea7n d\u1ecbch>")
        return
    text = " ".join(context.args)
    status_msg = await update.message.reply_text("\ud83e\udde0 \u0110ang suy ngh\u1ec9...")
    try:
        if HAS_BRAIN:
            from brain import AGIBrain
            brain = AGIBrain(MIMO_API_KEY, MIMO_API_BASE, MIMO_MODEL)
            result = brain.thinker.think_deeply(text, source_lang="auto", target_lang="Vietnamese")
            thinking = result.get("thinking_process", "")
            options = result.get("translation_options", [result.get("best_option", text)])
            chosen = result.get("chosen_option", text)
            response = f"**Qu\u00e1 tr\u00ecnh suy ngh\u1ec9:**\n{thinking}\n\n"
            if options:
                response += "**3 ph\u01b0\u01a1ng \u00e1n:**\n"
                for i, opt in enumerate(options[:3]):
                    t = opt.get("text", str(opt)) if isinstance(opt, dict) else str(opt)
                    response += f"{i+1}. {t}\n"
            response += f"\n**Chosen:** {chosen}"
            await status_msg.edit_text(response[:4000], parse_mode=ParseMode.MARKDOWN)
        else:
            await status_msg.edit_text("Brain ch\u01b0a available.")
    except Exception as e:
        await status_msg.edit_text(f"Error: {str(e)[:300]}")


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not context.args:
        await update.message.reply_text("S\u01b0 d\u1ee5ng: /analyze <video URL>")
        return
    url = context.args[0]
    status_msg = await update.message.reply_text("\ud83d\udd0d \u0110ang ph\u00e2n t\u00edch video...")
    try:
        import subprocess
        cmd = f'yt-dlp --dump-json --no-download "{url}" 2>/dev/null'
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            await status_msg.edit_text("Kh\u00f4ng th\u1ec3 l\u1ea5y info video.")
            return
        info = json.loads(proc.stdout)
        title = info.get("title", "Unknown")
        duration = info.get("duration", 0)
        desc = info.get("description", "")[:500]
        channel = info.get("uploader", "Unknown")
        analysis = f"**\u0110\u00e1nh gi\u00e1 video:**\n\n"
        analysis += f"**Title:** {title}\n**Channel:** {channel}\n**Duration:** {duration//60}m{duration%60}s\n\n"
        analysis += f"**M\u00f4 t\u1ea3:**\n{desc}"
        await status_msg.edit_text(analysis[:4000], parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await status_msg.edit_text(f"Error: {str(e)[:300]}")


async def cmd_brain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if HAS_BRAIN:
        try:
            from brain import AGIBrain
            brain = AGIBrain(MIMO_API_KEY, MIMO_API_BASE, MIMO_MODEL)
            learning = brain.adaptive.get_learning_summary()
            response = (
                "\ud83e\udde0 **Brain Stats**\n\n"
                f"\u00b7 Genres: {learning.get('genres_learned', 0)}\n"
                f"\u00b7 Lang pairs: {learning.get('lang_pairs_learned', 0)}\n"
                f"\u00b7 Experiments: {learning.get('total_experiments', 0)}\n"
                f"\u00b7 Avg quality: {learning.get('avg_quality', 0)}\n"
                f"\u00b7 Best: {learning.get('best_genre', 'none')}\n\n"
                "\ud83c\udfaf Modules: 11/11 OK | AGI: ~50%"
            )
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await update.message.reply_text(f"Brain error: {str(e)[:200]}")
    else:
        await update.message.reply_text("Brain ch\u01b0a available. Set MIMO_API_KEY.")


# ─── Main ──────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        print("❌ Set BOT_TOKEN environment variable!")
        sys.exit(1)
    
    log("🎬 OpenClaw MiMo Telegram Agent starting...")
    log(f"  Allowed chats: {ALLOWED_CHATS or 'ALL'}")
    log(f"  OmniVoice API: {OMNIVOICE_URL or 'NOT SET'}")
    log(f"  MiMo API: {MIMO_API_BASE}")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("dub", cmd_dub))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("think", cmd_think))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("brain", cmd_brain))
    app.add_handler(CommandHandler("tts", cmd_tts))
    
    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Messages
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_video))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    
    log("✅ Bot started! Listening...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)




# ─── TTS Command ────────────────────────────────────────────────────
async def cmd_tts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tts command — test OmniVoice TTS."""
    user_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text(
            "🎤 **OmniVoice TTS**\n\n"
            "Sử dụng: /tts <text>\n"
            "Hoặc: /tts <text> --mode design --voice female, young adult\n\n"
            "Modes: auto, design, clone\n"
            "Example: /tts Xin chào các bạn! --mode design --voice female, vietnamese",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    
    text = " ".join(context.args)
    mode = "auto"
    voice = "female, vietnamese accent, natural"
    
    # Parse flags
    if "--mode" in context.args:
        idx = context.args.index("--mode")
        if idx + 1 < len(context.args):
            mode = context.args[idx + 1]
    
    if "--voice" in context.args:
        idx = context.args.index("--voice")
        if idx + 1 < len(context.args):
            voice = context.args[idx + 1]
    
    # Send processing message
    status_msg = await update.message.reply_text(f"🎤 Đang tạo audio...\nMode: {mode}")
    
    try:
        from tools.tts_omnivoice import OmniVoiceTTS
        tts = OmniVoiceTTS()
        
        if not tts.health():
            await status_msg.edit_text("❌ OmniVoice server offline!")
            return
        
        if mode == "design":
            path = tts.design(text, voice)
        else:
            path = tts.synthesize(text)
        
        # Send audio
        with open(path, "rb") as audio:
            await update.message.reply_voice(voice=audio, caption=f"🎤 {mode}: {text[:50]}...")
        
        await status_msg.delete()
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)[:200]}")

if __name__ == "__main__":
    main()
