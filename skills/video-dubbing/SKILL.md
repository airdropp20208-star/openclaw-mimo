---
name: video-dubbing
description: "Professional video dubbing with voice-video sync — download, transcribe, translate, TTS, sync, combine"
version: 2.0.0
tools:
  - exec
  - web_fetch
---

# 🎬 Video Dubbing Skill

Professional video dubbing with **precise voice-video synchronization**.

## When to Use

- User sends a video file or URL
- User asks to translate/dub a video
- User wants voice cloning from reference audio
- User wants Vietnamese subtitles

## Pipeline

```
Download → Extract Audio → Whisper Transcribe → MiMo Translate → TTS → Voice Sync → FFmpeg Combine
```

## Quick Start

### Via CLI (single command)

```bash
python3 engines/dubbing_engine.py \
  --url "VIDEO_URL" \
  --source-lang Chinese \
  --target-lang Vietnamese \
  --tts-engine omnivoice \
  --omnivoice-url "http://GPU_SERVER:8880" \
  --mimo-key "YOUR_KEY" \
  --output /tmp/output
```

### Via Python API

```python
from engines.dubbing_engine import run_pipeline, DubConfig

config = DubConfig(
    mimo_api_key="YOUR_KEY",
    omnivoice_url="http://GPU_SERVER:8880",
    tts_instruct="female, vietnamese accent, natural",
)

result = run_pipeline(
    url="https://youtube.com/watch?v=xxx",
    source_lang="Chinese",
    target_lang="Vietnamese",
    config=config,
    output_dir="/tmp/output",
)

print(result.output_video)  # /tmp/output/dubbed.mp4
print(result.output_srt)    # /tmp/output/subtitles.srt
```

## Voice Cloning

Provide reference audio (3-10 seconds) for voice cloning:

```python
config = DubConfig(
    tts_ref_audio="/path/to/voice_sample.wav",
    tts_ref_text="Transcription of the sample",  # Optional
)
```

Or via CLI:
```bash
python3 engines/dubbing_engine.py \
  --url "VIDEO_URL" \
  --omnivoice-url "http://GPU:8880" \
  # The engine will use voice cloning if ref_audio is provided
```

## Voice Video Sync

The engine automatically syncs TTS audio to match original video timing:

1. Whisper provides precise timestamps for each speech segment
2. TTS generates audio at natural speed
3. Engine adjusts speed (atempo) to match original duration
4. Segments are placed at exact timestamps with cross-fade
5. Mixed with original audio (lowered volume for background)

### Sync Modes

- `stretch` (default): Speed up/slow down TTS to match
- `pad`: Add silence padding if TTS is shorter
- `compress`: Only compress, never stretch

## Output Files

| File | Description |
|------|-------------|
| `dubbed.mp4` | Final dubbed video |
| `subtitles.srt` | Vietnamese subtitles |
| `segments.json` | Transcription segments |
| `translated.json` | Translated segments |
| `tts/` | Individual TTS audio files |
| `synced/` | Speed-adjusted TTS files |

## Requirements

- Python 3.10+
- FFmpeg
- faster-whisper
- edge-tts (fallback)
- requests
- MiMo API key
- OmniVoice API server (for voice cloning)
