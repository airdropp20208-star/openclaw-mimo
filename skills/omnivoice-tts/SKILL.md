---
name: omnivoice-tts
description: "OmniVoice TTS: voice cloning, design, auto synthesis via remote API"
version: 1.0.0
tools:
  - exec
  - file
---

# 🎤 OmniVoice TTS Tool

Text-to-Speech with voice cloning capability via OmniVoice API.

## When to Use

- Generate speech from text
- Clone voice from reference audio
- Design custom voices (female, male, young, old, accents)

## API Setup

Set environment variable:
```bash
export OMNIVOICE_API_URL="https://your-cloudflare-tunnel.trycloudflare.com"
```

Or pass `api_url` parameter to `OmniVoiceTTS()`.

## Usage

### 1. Auto Voice (no reference needed)

```python
from tools.tts_omnivoice import OmniVoiceTTS

tts = OmniVoiceTTS()
path = tts.synthesize("Xin chào các bạn!")
# Returns: /tmp/omnivoice_xxxxx.wav
```

### 2. Voice Design (choose style)

```python
tts = OmniVoiceTTS()
path = tts.design(
    text="Xin chào!",
    instruct="female, young adult, vietnamese accent"
)
```

**Valid instruct keywords:**
- Gender: `male`, `female`
- Age: `child`, `teenager`, `young adult`, `middle-aged`, `elderly`
- Pitch: `very low pitch`, `low pitch`, `moderate pitch`, `high pitch`, `very high pitch`
- Accent: `american accent`, `british accent`, `australian accent`, `chinese accent`, `indian accent`, `japanese accent`, `korean accent`, `vietnamese accent`
- Style: `whisper`

**Example instructs:**
- `"female, young adult, vietnamese accent"`
- `"male, elderly, british accent"`
- `"female, teenager, whisper"`

### 3. Voice Cloning (clone from reference)

```python
tts = OmniVoiceTTS()
path = tts.clone(
    text="Xin chào! Đây là giọng clone.",
    ref_audio_path="sample.wav",  # Reference audio file
    ref_text="Nội dung trong file mẫu",  # What's said in reference
    speed=0.9  # Optional: slower speed
)
```

**Requirements:**
- `ref_audio_path`: WAV or MP3 file (3-10 seconds recommended)
- `ref_text`: Accurate transcription of reference audio
- Clean audio (no background music/noise) for best results

## Tool Function (for OpenClaw agent)

```python
from tools.tts_omnivoice import tts_tool

# Auto voice
result = tts_tool("Xin chào!", mode="auto")

# Voice design
result = tts_tool("Xin chào!", mode="design", voice_instruct="female, young adult")

# Voice clone
result = tts_tool(
    "Xin chào!",
    mode="clone",
    ref_audio="sample.wav",
    ref_text="Đây là mẫu giọng"
)
```

**Returns:**
```json
{"success": true, "output": "/tmp/omnivoice_xxxxx.wav"}
```

## Health Check

```python
from tools.tts_omnivoice import OmniVoiceTTS

tts = OmniVoiceTTS()
if tts.health():
    print("Server OK")
else:
    print("Server offline")
```

## Pitfalls

1. **ref_text must match audio content** — Wrong transcription = wrong voice clone
2. **Clean audio required** — Background music/noise degrades quality
3. **Cloudflare tunnels rotate** — URL may change, check health before use
4. **Processing time** — Auto: ~3s, Design: ~2s, Clone: ~8-15s
5. **Output is 24kHz WAV** — Convert to MP3 if needed: `ffmpeg -i output.wav output.mp3`
