     1|#!/usr/bin/env python3
     2|"""
     3|OpenClaw MiMo — Telegram Dubbing Agent
     4|========================================
     5|Professional dubbing bot that works like a real agent.
     6|- Receives video URLs or files via Telegram
     7|- Processes with full dubbing pipeline
     8|- Returns dubbed video with subtitles
     9|- Supports voice cloning, emotion control
    10|- Tracks job history and status
    11|
    12|Usage:
    13|  BOT_TOKEN=xxx python3 telegram_agent.py
    14|"""
    15|
    16|import asyncio
    17|import json
    18|import os
    19|import sys
    20|import time
    21|import traceback
    22|from pathlib import Path
    23|
    24|from telegram import (
    25|    Bot,
    26|    Update,
    27|    InlineKeyboardButton,
    28|    InlineKeyboardMarkup,
    29|)
    30|from telegram.ext import (
    31|    Application,
    32|    CommandHandler,
    33|    MessageHandler,
    34|    CallbackQueryHandler,
    35|    ContextTypes,
    36|    filters,
    37|)
    38|from telegram.constants import ParseMode, ChatAction
    39|
    40|# ─── Config ────────────────────────────────────────────────────────
    41|BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    42|ALLOWED_CHATS = [int(x) for x in os.getenv("ALLOWED_CHATS", "").split(",") if x.strip()]
    43|DATA_DIR = os.getenv("DATA_DIR", "/tmp/openclaw-mimo")
    44|LOG_FILE = os.path.join(DATA_DIR, "agent.log")
    45|
    46|# APIs
    47|MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
    48|MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")
    49|MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
    50|OMNIVOICE_URL = os.getenv("OMNIVOICE_API_URL", "")
    51|OMNIVOICE_KEY = os.getenv("OMNIVOICE_API_KEY", "")
    52|
    53|# Default settings
    54|DEFAULT_SOURCE_LANG = "Chinese"
    55|DEFAULT_TARGET_LANG = "Vietnamese"
    56|DEFAULT_TTS_ENGINE = "omnivoice"
    57|DEFAULT_VOICE = "female, vietnamese accent, natural"
    58|DEFAULT_EMOTION = "neutral"
    59|DEFAULT_SUBTITLE_STYLE = "professional"
    60|
    61|
    62|# ─── State Management ──────────────────────────────────────────────
    63|class AgentState:
    64|    """Per-user agent state."""
    65|    
    66|    def __init__(self):
    67|        self.jobs = {}  # job_id -> {status, result, ...}
    68|        self.settings = {}  # user_id -> settings
    69|        self.current_job = None
    70|    
    71|    def get_settings(self, user_id: int) -> dict:
    72|        if user_id not in self.settings:
    73|            self.settings[user_id] = {
    74|                "source_lang": DEFAULT_SOURCE_LANG,
    75|                "target_lang": DEFAULT_TARGET_LANG,
    76|                "tts_engine": DEFAULT_TTS_ENGINE,
    77|                "voice": DEFAULT_VOICE,
    78|                "emotion": DEFAULT_EMOTION,
    79|                "subtitle_style": DEFAULT_SUBTITLE_STYLE,
    80|            }
    81|        return self.settings[user_id]
    82|    
    83|    def create_job(self, user_id: int, video_url: str = "", video_path: str = "") -> str:
    84|        job_id = f"job_{int(time.time())}_{user_id}"
    85|        self.jobs[job_id] = {
    86|            "id": job_id,
    87|            "user_id": user_id,
    88|            "video_url": video_url,
    89|            "video_path": video_path,
    90|            "status": "pending",
    91|            "created_at": time.time(),
    92|            "result": None,
    93|            "error": None,
    94|        }
    95|        return job_id
    96|    
    97|    def update_job(self, job_id: str, **kwargs):
    98|        if job_id in self.jobs:
    99|            self.jobs[job_id].update(kwargs)
   100|
   101|
   102|state = AgentState()
   103|
   104|
   105|# ─── Logging ───────────────────────────────────────────────────────
   106|def log(msg, level="INFO"):
   107|    ts = time.strftime("%Y-%m-%d %H:%M:%S")
   108|    line = f"[{ts}] [{level}] {msg}"
   109|    print(line, flush=True)
   110|    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
   111|    with open(LOG_FILE, "a") as f:
   112|        f.write(line + "\n")
   113|
   114|
   115|# ─── Access Control ────────────────────────────────────────────────
   116|def is_allowed(update: Update) -> bool:
   117|    if not ALLOWED_CHATS:
   118|        return True
   119|    return update.effective_chat.id in ALLOWED_CHATS
   120|
   121|
   122|# ─── Command Handlers ──────────────────────────────────────────────
   123|async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
   124|    """Handle /start command."""
   125|    if not is_allowed(update):
   126|        await update.message.reply_text("⛔ Access denied.")
   127|        return
   128|    
   129|    await update.message.reply_text(
   130|        "🎬 **OpenClaw MiMo — Dubbing Agent**\n\n"
   131|        "Gửi video URL hoặc file video để vietsub tự động.\n\n"
   132|        "**Lệnh:**\n"
   133|        "/dub `<url>` — Vietsub video từ URL\n"
   134|        "/settings — Xem/sửa cài đặt\n"
   135|        "/status — Xem trạng thái jobs\n"
   136|        "/help — Hướng dẫn sử dụng\n\n"
   137|        "**Cài đặt hiện tại:**\n"
   138|        f"• Ngôn ngữ: {DEFAULT_SOURCE_LANG} → {DEFAULT_TARGET_LANG}\n"
   139|        f"• TTS: {DEFAULT_TTS_ENGINE}\n"
   140|        f"• Giọng: {DEFAULT_VOICE}\n"
   141|        f"• Emotion: {DEFAULT_EMOTION}\n"
   142|        f"• Subtitle: {DEFAULT_SUBTITLE_STYLE}",
   143|        parse_mode=ParseMode.MARKDOWN,
   144|    )
   145|
   146|
   147|async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
   148|    """Handle /help command."""
   149|    if not is_allowed(update):
   150|        return
   151|    
   152|    await update.message.reply_text(
   153|        "📖 **Hướng dẫn sử dụng**\n\n"
   154|        "**Cách dùng:**\n"
   155|        "1. Gửi URL video (YouTube, Bilibili, TikTok...)\n"
   156|        "2. Hoặc gõ `/dub <url>`\n"
   157|        "3. Chờ bot xử lý (2-10 phút tùy độ dài)\n"
   158|        "4. Nhận video đã vietsub\n\n"
   159|        "**Lệnh:**\n"
   160|        "/dub `<url>` — Vietsub video\n"
   161|        "/dub `<url>` `--emotion happy` — Vietsub với emotion\n"
   162|        "/dub `<url>` `--voice male, vietnamese` — Chọn giọng\n"
   163|        "/settings — Xem/sửa cài đặt\n"
   164|        "/status — Xem trạng thái\n"
   165|        "/cancel — Hủy job đang chạy\n\n"
   166|        "**Emotion:** neutral, happy, sad, angry, excited, calm\n\n"
   167|        "**Ví dụ:**\n"
   168|        "`/dub https://youtube.com/watch?v=xxx --emotion happy`\n"
   169|        "`/dub https://bilibili.com/video/xxx --voice male, southern vietnamese`",
   170|        parse_mode=ParseMode.MARKDOWN,
   171|    )
   172|
   173|
   174|async def cmd_dub(update: Update, context: ContextTypes.DEFAULT_TYPE):
   175|    """Handle /dub command."""
   176|    if not is_allowed(update):
   177|        await update.message.reply_text("⛔ Access denied.")
   178|        return
   179|    
   180|    if not context.args:
   181|        await update.message.reply_text(
   182|            "❌ Cung cấp URL video.\n"
   183|            "Ví dụ: `/dub https://youtube.com/watch?v=xxx`",
   184|            parse_mode=ParseMode.MARKDOWN,
   185|        )
   186|        return
   187|    
   188|    url = context.args[0]
   189|    settings = state.get_settings(update.effective_chat.id)
   190|    
   191|    # Parse optional args
   192|    for arg in context.args[1:]:
   193|        if arg.startswith("--emotion"):
   194|            idx = context.args.index(arg)
   195|            if idx + 1 < len(context.args):
   196|                settings["emotion"] = context.args[idx + 1]
   197|        elif arg.startswith("--voice"):
   198|            idx = context.args.index(arg)
   199|            if idx + 1 < len(context.args):
   200|                settings["voice"] = " ".join(context.args[idx + 1:])
   201|    
   202|    await _start_dub_job(update, url, settings)
   203|
   204|
   205|async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
   206|    """Handle /settings command."""
   207|    if not is_allowed(update):
   208|        return
   209|    
   210|    settings = state.get_settings(update.effective_chat.id)
   211|    
   212|    keyboard = [
   213|        [
   214|            InlineKeyboardButton("🌐 Ngôn ngữ", callback_data="set_lang"),
   215|            InlineKeyboardButton("🗣️ TTS Engine", callback_data="set_tts"),
   216|        ],
   217|        [
   218|            InlineKeyboardButton("🎤 Giọng", callback_data="set_voice"),
   219|            InlineKeyboardButton("😊 Emotion", callback_data="set_emotion"),
   220|        ],
   221|        [
   222|            InlineKeyboardButton("📄 Subtitle", callback_data="set_subtitle"),
   223|        ],
   224|    ]
   225|    
   226|    await update.message.reply_text(
   227|        f"⚙️ **Cài đặt hiện tại:**\n\n"
   228|        f"• Nguồn: {settings['source_lang']}\n"
   229|        f"• Đích: {settings['target_lang']}\n"
   230|        f"• TTS: {settings['tts_engine']}\n"
   231|        f"• Giọng: {settings['voice']}\n"
   232|        f"• Emotion: {settings['emotion']}\n"
   233|        f"• Subtitle: {settings['subtitle_style']}\n\n"
   234|        f"Nhấn nút để thay đổi:",
   235|        parse_mode=ParseMode.MARKDOWN,
   236|        reply_markup=InlineKeyboardMarkup(keyboard),
   237|    )
   238|
   239|
   240|async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
   241|    """Handle /status command."""
   242|    if not is_allowed(update):
   243|        return
   244|    
   245|    user_jobs = [
   246|        j for j in state.jobs.values()
   247|        if j["user_id"] == update.effective_chat.id
   248|    ]
   249|    
   250|    if not user_jobs:
   251|        await update.message.reply_text("📭 Chưa có jobs nào.")
   252|        return
   253|    
   254|    lines = []
   255|    for j in user_jobs[-5:]:  # Last 5 jobs
   256|        status_emoji = {"pending": "⏳", "running": "🔄", "done": "✅", "failed": "❌"}.get(j["status"], "❓")
   257|        elapsed = time.time() - j["created_at"]
   258|        lines.append(
   259|            f"{status_emoji} `{j['id'][:20]}...` — {j['status']} ({elapsed:.0f}s)"
   260|        )
   261|    
   262|    await update.message.reply_text(
   263|        "📊 **Jobs gần đây:**\n\n" + "\n".join(lines),
   264|        parse_mode=ParseMode.MARKDOWN,
   265|    )
   266|
   267|
   268|# ─── Message Handlers ──────────────────────────────────────────────
   269|async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
   270|    """Handle messages containing URLs."""
   271|    if not is_allowed(update):
   272|        return
   273|    
   274|    text = update.message.text.strip()
   275|    settings = state.get_settings(update.effective_chat.id)
   276|    
   277|    # Check if it's a URL
   278|    if text.startswith("http") and any(domain in text for domain in [
   279|        "youtube.com", "youtu.be", "bilibili.com", "b23.tv",
   280|        "tiktok.com", "instagram.com", "twitter.com", "x.com",
   281|        "facebook.com", "vimeo.com", "dailymotion.com",
   282|    ]):
   283|        await _start_dub_job(update, text, settings)
   284|
   285|
   286|async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
   287|    """Handle uploaded video files."""
   288|    if not is_allowed(update):
   289|        return
   290|    
   291|    video = update.message.video or update.message.document
   292|    if not video:
   293|        return
   294|    
   295|    await update.message.reply_text("📹 Đang tải video...")
   296|    
   297|    # Download video
   298|    os.makedirs(DATA_DIR, exist_ok=True)
   299|    file_path = os.path.join(DATA_DIR, f"input_{int(time.time())}.mp4")
   300|    
   301|    tg_file = await context.bot.get_file(video.file_id)
   302|    await tg_file.download_to_drive(file_path)
   303|    
   304|    settings = state.get_settings(update.effective_chat.id)
   305|    await _start_dub_job(update, "", settings, video_path=file_path)
   306|
   307|
   308|async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
   309|    """Handle inline keyboard callbacks."""
   310|    query = update.callback_query
   311|    await query.answer()
   312|    
   313|    if not is_allowed(update):
   314|        return
   315|    
   316|    data = query.data
   317|    settings = state.get_settings(update.effective_chat.id)
   318|    
   319|    if data == "set_lang":
   320|        keyboard = [
   321|            [
   322|                InlineKeyboardButton("🇨🇳 Chinese", callback_data="lang_Chinese"),
   323|                InlineKeyboardButton("🇯🇵 Japanese", callback_data="lang_Japanese"),
   324|                InlineKeyboardButton("🇰🇷 Korean", callback_data="lang_Korean"),
   325|            ],
   326|        ]
   327|        await query.edit_message_text(
   328|            "🌐 Chọn ngôn ngữ nguồn:",
   329|            reply_markup=InlineKeyboardMarkup(keyboard),
   330|        )
   331|    
   332|    elif data.startswith("lang_"):
   333|        lang = data.replace("lang_", "")
   334|        settings["source_lang"] = lang
   335|        await query.edit_message_text(f"✅ Đã set ngôn ngữ nguồn: {lang}")
   336|    
   337|    elif data == "set_tts":
   338|        keyboard = [
   339|            [
   340|                InlineKeyboardButton("🎤 OmniVoice (Clone)", callback_data="tts_omnivoice"),
   341|                InlineKeyboardButton("🔊 Edge TTS (Free)", callback_data="tts_edge"),
   342|            ],
   343|        ]
   344|        await query.edit_message_text(
   345|            "🗣️ Chọn TTS engine:",
   346|            reply_markup=InlineKeyboardMarkup(keyboard),
   347|        )
   348|    
   349|    elif data.startswith("tts_"):
   350|        engine = data.replace("tts_", "")
   351|        settings["tts_engine"] = engine
   352|        await query.edit_message_text(f"✅ Đã set TTS: {engine}")
   353|    
   354|    elif data == "set_voice":
   355|        keyboard = [
   356|            [
   357|                InlineKeyboardButton("👩 Nữ tự nhiên", callback_data="voice_female, vietnamese accent, natural"),
   358|                InlineKeyboardButton("👨 Nam tự nhiên", callback_data="voice_male, vietnamese accent, natural"),
   359|            ],
   360|            [
   361|                InlineKeyboardButton("👩 Nữ miền Nam", callback_data="voice_female, southern vietnamese accent"),
   362|                InlineKeyboardButton("👨 Nam miền Nam", callback_data="voice_male, southern vietnamese accent"),
   363|            ],
   364|        ]
   365|        await query.edit_message_text(
   366|            "🎤 Chọn giọng đọc:",
   367|            reply_markup=InlineKeyboardMarkup(keyboard),
   368|        )
   369|    
   370|    elif data.startswith("voice_"):
   371|        voice = data.replace("voice_", "")
   372|        settings["voice"] = voice
   373|        await query.edit_message_text(f"✅ Đã set giọng: {voice}")
   374|    
   375|    elif data == "set_emotion":
   376|        keyboard = [
   377|            [
   378|                InlineKeyboardButton("😐 Neutral", callback_data="emo_neutral"),
   379|                InlineKeyboardButton("😊 Happy", callback_data="emo_happy"),
   380|                InlineKeyboardButton("😢 Sad", callback_data="emo_sad"),
   381|            ],
   382|            [
   383|                InlineKeyboardButton("😠 Angry", callback_data="emo_angry"),
   384|                InlineKeyboardButton("🎉 Excited", callback_data="emo_excited"),
   385|                InlineKeyboardButton("😌 Calm", callback_data="emo_calm"),
   386|            ],
   387|        ]
   388|        await query.edit_message_text(
   389|            "😊 Chọn emotion:",
   390|            reply_markup=InlineKeyboardMarkup(keyboard),
   391|        )
   392|    
   393|    elif data.startswith("emo_"):
   394|        emo = data.replace("emo_", "")
   395|        settings["emotion"] = emo
   396|        await query.edit_message_text(f"✅ Đã set emotion: {emo}")
   397|    
   398|    elif data == "set_subtitle":
   399|        keyboard = [
   400|            [
   401|                InlineKeyboardButton("Professional", callback_data="sub_professional"),
   402|                InlineKeyboardButton("Anime", callback_data="sub_anime"),
   403|                InlineKeyboardButton("Minimal", callback_data="sub_minimal"),
   404|            ],
   405|        ]
   406|        await query.edit_message_text(
   407|            "📄 Chọn style subtitle:",
   408|            reply_markup=InlineKeyboardMarkup(keyboard),
   409|        )
   410|    
   411|    elif data.startswith("sub_"):
   412|        style = data.replace("sub_", "")
   413|        settings["subtitle_style"] = style
   414|        await query.edit_message_text(f"✅ Đã set subtitle: {style}")
   415|
   416|
   417|# ─── Dubbing Job ───────────────────────────────────────────────────
   418|async def _start_dub_job(update: Update, url: str, settings: dict, video_path: str = ""):
   419|    """Start a dubbing job."""
   420|    user_id = update.effective_chat.id
   421|    
   422|    # Create job
   423|    job_id = state.create_job(user_id, video_url=url, video_path=video_path)
   424|    state.update_job(job_id, status="running")
   425|    
   426|    # Send status message
   427|    status_msg = await update.message.reply_text(
   428|        f"🎬 **Bắt đầu vietsub...**\n\n"
   429|        f"• URL: `{url or 'File upload'}`\n"
   430|        f"• Ngôn ngữ: {settings['source_lang']} → {settings['target_lang']}\n"
   431|        f"• TTS: {settings['tts_engine']}\n"
   432|        f"• Emotion: {settings['emotion']}\n\n"
   433|        f"⏳ Đang xử lý... (2-10 phút)",
   434|        parse_mode=ParseMode.MARKDOWN,
   435|    )
   436|    
   437|    # Run pipeline in thread
   438|    asyncio.create_task(_run_dub_pipeline(job_id, status_msg, settings))
   439|
   440|
   441|async def _run_dub_pipeline(job_id: str, status_msg, settings: dict):
   442|    """Run the dubbing pipeline."""
   443|    job = state.jobs[job_id]
   444|    
   445|    try:
   446|        # Update status
   447|        await status_msg.edit_text(
   448|            status_msg.text_markup.replace("⏳ Đang xử lý...", "📥 Đang tải video..."),
   449|            parse_mode=ParseMode.MARKDOWN,
   450|        )
   451|        
   452|        # Import and run engine
   453|        sys.path.insert(0, os.path.dirname(__file__))
   454|        from engines.dubbing_engine import run_pipeline, DubConfig
   455|        
   456|        output_dir = os.path.join(DATA_DIR, job_id)
   457|        os.makedirs(output_dir, exist_ok=True)
   458|        
   459|        config = DubConfig(
   460|            mimo_api_key=MIMO_API_KEY,
   461|            mimo_api_base=MIMO_API_BASE,
   462|            mimo_model=MIMO_MODEL,
   463|            omnivoice_url=OMNIVOICE_URL,
   464|            omnivoice_key=OMNIVOICE_KEY,
   465|            tts_engine=settings["tts_engine"],
   466|            tts_instruct=settings["voice"],
   467|            tts_emotion=settings["emotion"],
   468|            subtitle_style=settings["subtitle_style"],
   469|            output_dir=output_dir,
   470|        )
   471|        
   472|        result = run_pipeline(
   473|            url=job["video_url"],
   474|            video_path=job["video_path"],
   475|            source_lang=settings["source_lang"],
   476|            target_lang=settings["target_lang"],
   477|            config=config,
   478|        )
   479|        
   480|        if result["success"]:
   481|            state.update_job(job_id, status="done", result=result)
   482|            
   483|            # Send result
   484|            output_video = result["output_video"]
   485|            if os.path.exists(output_video):
   486|                await status_msg.edit_text(
   487|                    f"✅ **Vietsub thành công!**\n\n"
   488|                    f"• Thời gian: {result['processing_time']:.0f}s\n"
   489|                    f"• Số segments: {result['segments']}\n"
   490|                    f"• Video: `{output_video}`",
   491|                    parse_mode=ParseMode.MARKDOWN,
   492|                )
   493|                
   494|                # Send video
   495|                with open(output_video, "rb") as f:
   496|                    await status_msg.reply_video(
   497|                        video=f,
   498|                        caption=f"🎬 {job['video_url'][:50]}...",
   499|                    )
   500|                
   501|                # Send subtitles
   502|                srt_path = result.get("output_srt", "")
   503|                if srt_path and os.path.exists(srt_path):
   504|                    with open(srt_path, "rb") as f:
   505|                        await status_msg.reply_document(
   506|                            document=f,
   507|                            filename="subtitles.srt",
   508|                            caption="📄 Phụ đề SRT",
   509|                        )
   510|            else:
   511|                await status_msg.edit_text("❌ Không tìm thấy output video.")
   512|        else:
   513|            state.update_job(job_id, status="failed", error=result.get("error"))
   514|            await status_msg.edit_text(
   515|                f"❌ **Vietsub thất bại:**\n`{result.get('error', 'Unknown error')}`",
   516|                parse_mode=ParseMode.MARKDOWN,
   517|            )
   518|    
   519|    except Exception as e:
   520|        log(f"Job {job_id} failed: {e}\n{traceback.format_exc()}")
   521|        state.update_job(job_id, status="failed", error=str(e))
   522|        await status_msg.edit_text(
   523|            f"❌ **Lỗi:**\n`{str(e)[:500]}`",
   524|            parse_mode=ParseMode.MARKDOWN,
   525|        )
   526|
   527|
   528|# ─── Main ──────────────────────────────────────────────────────────
   529|def main():
   530|    if not BOT_TOKEN:
   531|        print("❌ Set BOT_TOKEN environment variable!")
   532|        sys.exit(1)
   533|    
   534|    log("🎬 OpenClaw MiMo Telegram Agent starting...")
   535|    log(f"  Allowed chats: {ALLOWED_CHATS or 'ALL'}")
   536|    log(f"  OmniVoice API: {OMNIVOICE_URL or 'NOT SET'}")
   537|    log(f"  MiMo API: {MIMO_API_BASE}")
   538|    
   539|    app = Application.builder().token(BOT_TOKEN).build()
   540|    
   541|    # Commands
   542|    app.add_handler(CommandHandler("start", cmd_start))
   543|    app.add_handler(CommandHandler("help", cmd_help))
   544|    app.add_handler(CommandHandler("dub", cmd_dub))
   545|    app.add_handler(CommandHandler("settings", cmd_settings))
   546|    app.add_handler(CommandHandler("status", cmd_status))\n    app.add_handler(CommandHandler("tts", cmd_tts))
   547|    
   548|    # Callbacks
   549|    app.add_handler(CallbackQueryHandler(handle_callback))
   550|    
   551|    # Messages
   552|    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, handle_video))
   553|    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
   554|    
   555|    log("✅ Bot started! Listening...")
   556|    app.run_polling(allowed_updates=Update.ALL_TYPES)
   557|
   558|
   559|

# ─── TTS Command ────────────────────────────────────────────────────
async def cmd_tts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /tts command — test OmniVoice TTS."""
    user_id = update.effective_chat.id
    
    if not context.args:
        await update.message.reply_text(
            "🎤 **OmniVoice TTS**\n\n"
            "Sử dụng: `/tts <text>`\n"
            "Hoặc: `/tts <text> --mode design --voice "female, young adult"`\n\n"
            "Modes: `auto`, `design`, `clone`\n"
            "Example: `/tts Xin chào các bạn! --mode design --voice "female, vietnamese"`",
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
   560|    main()
   561|