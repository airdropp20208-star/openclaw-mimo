---
name: video-dubbing
description: Professional video dubbing — transcribe, translate, TTS, combine
version: 1.0.0
tools:
  - exec
  - web_fetch
---

# Video Dubbing Skill

Dub videos from any language to Vietnamese using AI.

## When to Use

- User sends a video file
- User sends a YouTube/Bilibili link  
- User asks to translate/dub a video

## Workflow

1. Download video (if URL): `yt-dlp`
2. Extract audio: `ffmpeg`
3. Transcribe: `faster-whisper` (large-v3)
4. Translate: MiMo API
5. TTS: `edge-tts` (Vietnamese)
6. Combine: `ffmpeg`
7. Generate SRT subtitles

## Commands

```bash
# Download
yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best" -o "/tmp/input.mp4" URL

# Transcribe
python3 -c "from faster_whisper import WhisperModel; ..."

# TTS
edge-tts --voice vi-VN-HoaiMyNeural --text "text" --write-media output.mp3
```

## Config

Set `MIMO_API_KEY` env var for translation.
