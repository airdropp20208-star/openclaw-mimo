---
name: video-dubbing
description: Professional video dubbing with OmniVoice TTS — transcribe, translate, voice clone, combine
version: 1.0.0
tools:
  - exec
  - web_fetch
---

# 🎬 Video Dubbing Skill (OmniVoice)

Professional video dubbing using OmniVoice for voice cloning and TTS.

## When to Use

- User sends a video file
- User sends a YouTube/Bilibili link
- User asks to translate/dub a video
- User wants voice cloning

## OmniVoice Features

- **Voice Cloning**: Clone any voice from 3-10s reference audio
- **Voice Design**: Create voices by description (female, vietnamese accent...)
- **600+ Languages**: Including Vietnamese
- **Fast Inference**: 40x faster than real-time

## Workflow

### 1. Download Video (if URL)

```bash
pip install -q yt-dlp
yt-dlp -f "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" \
  -o "/tmp/dub_input.mp4" --merge-output-format mp4 "VIDEO_URL"
```

### 2. Extract Audio

```bash
ffmpeg -i /tmp/dub_input.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 -y /tmp/dub_audio.wav
```

### 3. Transcribe (Whisper)

```bash
pip install -q faster-whisper
python3 << 'PYEOF'
from faster_whisper import WhisperModel
import json

model = WhisperModel("large-v3", device="cpu", compute_type="int8")
segments, info = model.transcribe("/tmp/dub_audio.wav", language="zh", vad_filter=True, beam_size=5)

data = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
with open("/tmp/dub_segments.json", "w") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
PYEOF
```

### 4. Translate (MiMo API)

```bash
python3 << 'PYEOF'
import json, urllib.request, re

with open("/tmp/dub_segments.json") as f:
    segments = json.load(f)

numbered = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(segments))

payload = json.dumps({
    "model": "mimo-v2.5",
    "messages": [
        {"role": "system", "content": "Professional donghua translator. Chinese to Vietnamese. Natural phrasing. Keep numbering."},
        {"role": "user", "content": f"Translate:\n{numbered}"}
    ],
    "max_tokens": 4000,
    "temperature": 0.3
}).encode()

req = urllib.request.Request(
    "https://api.xiaomimimo.com/v1/chat/completions",
    data=payload,
    headers={"Content-Type": "application/json", "Authorization": "Bearer MIMO_API_KEY"}
)

with urllib.request.urlopen(req, timeout=60) as resp:
    content = json.loads(resp.read())["choices"][0]["message"]["content"]

translations = [re.match(r"^\d+[\.\)]\s*(.+)", l.strip()).group(1) 
                for l in content.strip().split("\n") 
                if re.match(r"^\d+[\.\)]", l.strip())]

for i, seg in enumerate(segments):
    seg["translated"] = translations[i] if i < len(translations) else seg["text"]

with open("/tmp/dub_segments.json", "w") as f:
    json.dump(segments, f, ensure_ascii=False, indent=2)
PYEOF
```

### 5. Generate TTS with OmniVoice

```bash
pip install -q omnivoice torch torchaudio soundfile

python3 << 'PYEOF'
import json, os
from omnivoice import OmniVoice
import soundfile as sf
import torch

# Load model (cached after first load)
print("Loading OmniVoice model...")
model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cpu",  # Use "cuda:0" if GPU available
    dtype=torch.float32
)
print("Model loaded!")

with open("/tmp/dub_segments.json") as f:
    segments = json.load(f)

# Optional: Use voice cloning with reference audio
# ref_audio = "/path/to/reference_voice.wav"  # 3-10 seconds
# ref_text = "Transcription of reference audio"

for i, seg in enumerate(segments):
    if not seg.get("translated"):
        continue
    
    tts_file = f"/tmp/dub_tts_{i:04d}.wav"
    
    try:
        # Voice Design mode (no reference needed)
        audio = model.generate(
            text=seg["translated"],
            instruct="female, vietnamese accent, natural",  # Voice description
            speed=1.0
        )
        
        # Or Voice Cloning mode (if ref_audio available):
        # audio = model.generate(
        #     text=seg["translated"],
        #     ref_audio=ref_audio,
        #     ref_text=ref_text
        # )
        
        sf.write(tts_file, audio[0], 24000)
        seg["tts_file"] = tts_file
        print(f"[{i+1}/{len(segments)}] Generated: {seg['translated'][:30]}...")
    except Exception as e:
        print(f"Error on segment {i}: {e}")
        seg["tts_file"] = ""

with open("/tmp/dub_segments.json", "w") as f:
    json.dump(segments, f, ensure_ascii=False, indent=2)
PYEOF
```

### 6. Combine Audio

```bash
python3 << 'PYEOF'
import json, subprocess, os

with open("/tmp/dub_segments.json") as f:
    segments = json.load(f)

filter_parts = []
inputs = []
idx = 0
for seg in segments:
    tts = seg.get("tts_file", "")
    if not tts or not os.path.exists(tts):
        continue
    inputs.append(f'-i "{tts}"')
    delay_ms = int(seg["start"] * 1000)
    filter_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms},aresample=44100[a{idx}]")
    idx += 1

if not filter_parts:
    print("No TTS files generated!")
    exit(1)

mix = "".join(f"[a{i}]" for i in range(idx))
filter_parts.append(f"{mix}amix=inputs={idx}:duration=longest[out]")

cmd = f'ffmpeg -i /tmp/dub_input.mp4 {" ".join(inputs)} -filter_complex "{";".join(filter_parts)}" -map "[out]" -y /tmp/dub_audio_out.wav'
subprocess.run(cmd, shell=True, capture_output=True, timeout=120)

subprocess.run(
    'ffmpeg -i /tmp/dub_input.mp4 -i /tmp/dub_audio_out.wav -c:v copy -map 0:v:0 -map 1:a:0 -shortest -y /tmp/dubbed_output.mp4',
    shell=True, capture_output=True, timeout=120
)

print("✅ Video dubbed successfully!")
PYEOF
```

### 7. Generate SRT Subtitles

```bash
python3 << 'PYEOF'
import json

with open("/tmp/dub_segments.json") as f:
    segments = json.load(f)

srt = ""
for i, seg in enumerate(segments):
    if not seg.get("translated"):
        continue
    start = f"{int(seg['start']//3600):02d}:{int(seg['start']%3600//60):02d}:{int(seg['start']%60):02d},{int(seg['start']%1*1000):03d}"
    end = f"{int(seg['end']//3600):02d}:{int(seg['end']%3600//60):02d}:{int(seg['end']%60):02d},{int(seg['end']%1*1000):03d}"
    srt += f"{i+1}\n{start} --> {end}\n{seg['translated']}\n\n"

with open("/tmp/dubbed_output.srt", "w") as f:
    f.write(srt)

print(f"✅ Generated {len(segments)} subtitle lines")
PYEOF
```

## Output Files

- `/tmp/dubbed_output.mp4` — Dubbed video
- `/tmp/dubbed_output.srt` — Vietnamese subtitles

## Voice Cloning Example

```python
# Clone a specific voice
audio = model.generate(
    text="Xin chào các bạn",
    ref_audio="/path/to/voice_sample.wav",  # 3-10 seconds
    ref_text="Đây là mẫu giọng"  # Optional, auto-transcribed if omitted
)
```

## Voice Design Examples

```python
# Female Vietnamese
audio = model.generate(text="Xin chào", instruct="female, vietnamese accent")

# Male, deep voice
audio = model.generate(text="Xin chào", instruct="male, deep voice, southern vietnamese")

# Young female, energetic
audio = model.generate(text="Xin chào", instruct="female, young, energetic")
```

## Requirements

- Python 3.10+
- PyTorch (CPU or GPU)
- OmniVoice: `pip install omnivoice`
- FFmpeg
- faster-whisper
- MiMo API key (for translation)
