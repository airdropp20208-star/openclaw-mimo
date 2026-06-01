---
name: video-dubbing
description: "Professional video dubbing — download, transcribe, translate, voice clone, sync, process, composite"
version: 2.0.0
tools:
  - exec
  - web_fetch
---

# 🎬 Professional Video Dubbing Skill

Full-featured dubbing pipeline with studio-grade quality.

## Pipeline

```
Download → Extract Audio → Whisper Transcribe (word-level)
    → MiMo Translate → OmniVoice TTS (voice clone + emotion)
    → Voice Sync (atempo) → Audio Process (normalize, compress, EQ)
    → Video Composite (subtitle burn, watermark) → Final Mix
```

## Quick Start

```bash
python3 engines/dubbing_engine.py \
  --url "VIDEO_URL" \
  --source-lang Chinese \
  --target-lang Vietnamese \
  --tts-engine omnivoice \
  --omnivoice-url "http://GPU:8880" \
  --voice-instruct "female, vietnamese accent, natural" \
  --emotion neutral \
  --subtitle-style professional \
  --output /tmp/output
```

## Components

### engines/dubbing_engine.py — Main Pipeline
Orchestrates all 9 steps with error handling.

### engines/audio_processor.py — Audio Processing
- Loudness normalization (EBU R128)
- Dynamic range compression
- Noise gate
- EQ matching (speech, warm, bright, female, male)
- Cross-fade with curves
- Breath detection

### engines/tts_engine.py — Professional TTS
- Voice cloning from reference audio
- Emotion-aware synthesis (happy, sad, angry, neutral, calm)
- Speed matching with pitch preservation
- Batch processing

### engines/video_compositor.py — Video Compositing
- Subtitle burning (professional, anime, minimal styles)
- Watermark overlay (image/text)
- Multi-track audio mixing
- Video editing (cut, merge, resize, intro/outro)

## Voice Cloning

```bash
# Clone voice from reference audio
python3 engines/dubbing_engine.py \
  --url "VIDEO_URL" \
  --tts-engine omnivoice \
  --omnivoice-url "http://GPU:8880" \
  --ref-audio /path/to/voice_sample.wav \
  --output /tmp/output
```

## Emotion Control

```python
config = DubConfig(tts_emotion="happy")  # or sad, angry, excited, calm
```

## Audio Quality

The engine applies professional audio processing:
1. **Noise gate** — removes background noise during silence
2. **EQ matching** — matches speaker frequency profile
3. **Dynamic range compression** — balances loud/quiet parts
4. **Loudness normalization** — EBU R128 standard (-16 LUFS)
