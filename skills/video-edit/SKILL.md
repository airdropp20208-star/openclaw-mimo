---
name: video-edit
description: "Video editing — cut, merge, overlay subtitles, extract clips, add watermarks"
version: 1.0.0
tools:
  - exec
---

# ✂️ Video Edit Skill

Video editing operations using FFmpeg.

## When to Use

- Cut/trim video segments
- Merge multiple videos
- Overlay subtitles (hardcoded or soft)
- Extract audio from video
- Add watermarks/logos
- Resize/reformat video

## Operations

### Cut/Trim

```bash
# Cut from 1:30 to 3:45
ffmpeg -i input.mp4 -ss 00:01:30 -to 00:03:45 -c copy output.mp4

# Cut first 30 seconds
ffmpeg -i input.mp4 -t 30 -c copy output.mp4
```

### Merge Videos

```bash
# Create file list
echo "file 'part1.mp4'
file 'part2.mp4'" > list.txt

# Merge
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4
```

### Hardcode Subtitles

```bash
# Burn SRT subtitles into video
ffmpeg -i video.mp4 -vf "subtitles=subtitles.srt:force_style='FontSize=24,PrimaryColour=&H00FFFFFF'" output.mp4

# With custom style
ffmpeg -i video.mp4 -vf "subtitles=subtitles.srt:force_style='FontName=Noto Sans CJK,FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2'" output.mp4
```

### Extract Clip

```bash
# Extract 30-second clip starting at 2:00
ffmpeg -i input.mp4 -ss 00:02:00 -t 30 -c copy clip.mp4
```

### Resize

```bash
# Scale to 720p
ffmpeg -i input.mp4 -vf "scale=-1:720" output.mp4

# Scale to 1080p with padding
ffmpeg -i input.mp4 -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" output.mp4
```

### Add Watermark

```bash
# Image watermark (top-right)
ffmpeg -i video.mp4 -i logo.png -filter_complex "overlay=W-w-10:10" output.mp4

# Text watermark
ffmpeg -i video.mp4 -vf "drawtext=text='© Channel':fontsize=24:fontcolor=white:x=W-tw-10:y=10" output.mp4
```

### Extract Audio

```bash
# Extract audio as WAV
ffmpeg -i video.mp4 -vn -acodec pcm_s16le -ar 16000 -ac 1 audio.wav

# Extract audio as MP3
ffmpeg -i video.mp4 -vn -acodec libmp3lame -q:a 2 audio.mp3
```

### Replace Audio Track

```bash
# Replace video audio with new audio
ffmpeg -i video.mp4 -i new_audio.wav -c:v copy -map 0:v:0 -map 1:a:0 -shortest output.mp4
```

### Mix Audio Tracks

```bash
# Mix original (low volume) + dubbed (full volume)
ffmpeg -i video.mp4 -i dubbed.wav \
  -filter_complex "[0:a]volume=0.15[bg];[1:a]volume=1.0[dub];[bg][Dub]amix=inputs=2:duration=first[out]" \
  -map 0:v -map "[out]" -c:v copy output.mp4
```

## Python Helper

```python
import subprocess

def run_ffmpeg(cmd):
    """Run FFmpeg command."""
    result = subprocess.run(
        f'ffmpeg {cmd} 2>&1',
        shell=True, capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        raise Exception(f"FFmpeg failed: {result.stderr[:500]}")
    return result

def get_duration(path):
    """Get media duration in seconds."""
    result = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{path}"',
        shell=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip() or "0")
```
