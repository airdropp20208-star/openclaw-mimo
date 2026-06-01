---
name: voice-sync
description: "Sync TTS audio to match video timing — speed adjustment, cross-fade, precise placement"
version: 1.0.0
tools:
  - exec
---

# 🎯 Voice-Video Sync Skill

Synchronize TTS audio with original video timing for natural dubbing.

## When to Use

- TTS audio is faster/slower than original speech
- Need to match lip sync in video
- Need smooth transitions between speech segments

## How It Works

### 1. Speed Adjustment (atempo)

FFmpeg `atempo` filter adjusts playback speed without changing pitch:

```bash
# Speed up 1.5x
ffmpeg -i input.wav -filter:a "atempo=1.5" output.wav

# Slow down 0.7x
ffmpeg -i input.wav -filter:a "atempo=0.7" output.wav

# Chain for extreme adjustments (0.25x to 4.0x)
ffmpeg -i input.wav -filter:a "atempo=2.0,atempo=0.8" output.wav
```

### 2. Precise Timestamp Placement

```bash
# Delay audio by 5.2 seconds
ffmpeg -i tts.wav -filter:a "adelay=5200|5200" delayed.wav

# Mix multiple segments at precise timestamps
ffmpeg -i video.mp4 -i seg1.wav -i seg2.wav -i seg3.wav \
  -filter_complex "
    [1:a]adelay=0|0[a1];
    [2:a]adelay=3500|3500[a2];
    [3:a]adelay=8200|8200[a3];
    [a1][a2][a3]amix=inputs=3:duration=longest[out]
  " \
  -map 0:v -map "[out]" -c:v copy output.mp4
```

### 3. Cross-Fade Between Segments

```bash
# Cross-fade 50ms between two audio segments
ffmpeg -i seg1.wav -i seg2.wav \
  -filter_complex "[0:a][1:a]acrossfade=d=0.05:c1=tri:c2=tri[out]" \
  -map "[out]" faded.wav
```

### 4. Speed Factor Calculation

```
speed_factor = tts_duration / target_duration

If factor > 1.0 → TTS is slower than original → speed up
If factor < 1.0 → TTS is faster than original → slow down
If factor ≈ 1.0 → Good match, no adjustment needed
```

## Usage from Python

```python
from engines.dubbing_engine import sync_voices, DubConfig

config = DubConfig(sync_mode="stretch", crossfade_ms=50)
segments = sync_voices(segments, output_dir, config)
```

## Tips

- Keep speed factor between 0.5x and 2.0x for natural sound
- Use cross-fade (50-100ms) to avoid clicks between segments
- For extreme speed changes, consider re-generating TTS with adjusted speed parameter
