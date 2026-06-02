---
name: video-dubbing
description: "Dubbing video: translate + TTS voice clone + subtitle burn"
version: 1.0.0
trigger:
  - "dub"
  - "vietsub"
  - "dubbing"
  - "translate video"
---

# 🎬 Video Dubbing Skill

Translate and dub videos with voice cloning.

## When to Use

User sends:
- Video URL (YouTube, Bilibili, TikTok)
- "dub <url>"
- "vietsub <url>"
- "translate this video"

## How It Works

1. **Download** video from URL
2. **Transcribe** audio (Whisper)
3. **Translate** to target language (MiMo)
4. **TTS** with voice cloning (OmniVoice)
5. **Combine** audio + video (FFmpeg)
6. **Send** result back

## Commands

### /dub <url>
Basic dubbing with default settings.

### /dub <url> --voice "female, young adult"
Custom voice style.

### /dub <url> --emotion happy
Dub with emotion.

### /dub <url> --target English
Translate to different language.

## Environment Variables

```bash
BOT_TOKEN=***           # Telegram bot token
MIMO_API_KEY=***        # MiMo API key (brain)
MIMO_API_BASE=https://api.xiaomimimo.com/v1
OMNIVOICE_API_URL=https://your-tunnel.trycloudflare.com  # TTS server
ALLOWED_CHATS=7563947218  # Allowed chat IDs
```

## Pipeline Config

```python
from engines.dubbing_engine import run_pipeline, DubConfig

config = DubConfig(
    mimo_api_key="***",
    mimo_api_base="https://api.xiaomimimo.com/v1",
    omnivoice_url="https://your-tunnel.trycloudflare.com",
    tts_engine="omnivoice",
    tts_instruct="female, vietnamese accent, natural",
    source_lang="Chinese",
    target_lang="Vietnamese",
)

result = run_pipeline(url="https://youtube.com/watch?v=xxx", config=config)
```

## Agent Integration

OpenClaw agent calls this skill when user sends video URL:

```python
# In OpenClaw agent
if message contains video URL:
    from engines.dubbing_engine import run_pipeline, DubConfig
    config = load_config()  # from env vars
    result = run_pipeline(url=url, config=config)
    send_video(result["output_video"])
```

## Pitfalls

1. **OmniVoice URL rotates** — Cloudflare tunnels change. Use health check before calling.
2. **Long videos take time** — 10+ minute videos can take 5-10 minutes to process.
3. **API rate limits** — MiMo and OmniVoice have rate limits. Add retry logic.
4. **File size limits** — Telegram has 50MB limit for videos. Compress if needed.
