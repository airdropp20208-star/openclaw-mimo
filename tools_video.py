"""
Video Editing & TTS Tools for OpenClaw MiMo Agent.

Tools:
- video_edit: Cut, trim, merge, add subtitles, overlay text on video
- video_info: Get video metadata (duration, resolution, codec)
- tts_generate: Generate Vietnamese speech from text using OmniVoice/gTTS
- video_composite: Advanced composition (picture-in-picture, watermark, transitions)

All tools return {"success": bool, "output": str, "file": str optional}
"""

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from typing import Optional

# ============================================================
# VIDEO INFO
# ============================================================

def video_info(video_path: str) -> dict:
    """Get video metadata using ffprobe."""
    if not video_path or not os.path.exists(video_path):
        return {"success": False, "output": f"Video not found: {video_path}"}
    
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        video_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"success": False, "output": f"ffprobe error: {result.stderr[:500]}"}
        
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        duration = float(fmt.get("duration", 0))
        size_mb = int(fmt.get("size", 0)) / (1024 * 1024)
        
        video_stream = None
        audio_stream = None
        for s in data.get("streams", []):
            if s.get("codec_type") == "video" and not video_stream:
                video_stream = s
            elif s.get("codec_type") == "audio" and not audio_stream:
                audio_stream = s
        
        info_lines = [
            f"📹 Video: {os.path.basename(video_path)}",
            f"⏱ Duration: {duration:.1f}s ({int(duration//60)}m {int(duration%60)}s)",
            f"💾 Size: {size_mb:.1f} MB",
        ]
        
        if video_stream:
            w = video_stream.get("width", "?")
            h = video_stream.get("height", "?")
            fps = video_stream.get("r_frame_rate", "?")
            codec = video_stream.get("codec_name", "?")
            info_lines.append(f"🖥 Resolution: {w}x{h} | {codec} | {fps} fps")
        
        if audio_stream:
            acodec = audio_stream.get("codec_name", "?")
            sr = audio_stream.get("sample_rate", "?")
            ch = audio_stream.get("channels", "?")
            info_lines.append(f"🔊 Audio: {acodec} | {sr} Hz | {ch} ch")
        
        return {"success": True, "output": "\n".join(info_lines)}
    except Exception as e:
        return {"success": False, "output": f"Error: {str(e)[:500]}"}


# ============================================================
# VIDEO EDIT (cut, trim, merge, subtitle, text overlay)
# ============================================================

def video_edit(
    video_path: str,
    action: str,
    output_path: str = "",
    start: float = 0,
    end: float = 0,
    duration: float = 0,
    text: str = "",
    font_size: int = 24,
    font_color: str = "white",
    position: str = "center",
    bg_color: str = "black@0.6",
    subtitle_file: str = "",
    inputs: str = "",
    **kwargs
) -> dict:
    """
    Edit video with various actions.
    
    Actions:
    - trim: Cut video from start to end (seconds)
    - concat: Merge multiple videos (inputs = "file1.mp4,file2.mp4")
    - overlay_text: Add text overlay on video
    - add_subtitle: Add .srt subtitle file
    - extract_audio: Extract audio track to .mp3
    - remove_audio: Remove audio track
    - speed: Change speed (text = "2.0" for 2x, "0.5" for half)
    - resize: Resize video (text = "1280x720")
    - gif: Convert to GIF (text = "fps=10,width=480")
    - rotate: Rotate video (text = "90" for 90 degrees clockwise)
    """
    if not video_path or not os.path.exists(video_path):
        return {"success": False, "output": f"Video not found: {video_path}"}
    
    if not output_path:
        ext = os.path.splitext(video_path)[1]
        output_path = f"/tmp/edited_{int(time.time())}{ext}"
    
    action = action.lower().strip()
    
    try:
        if action == "trim":
            return _video_trim(video_path, output_path, start, end, duration)
        elif action == "concat":
            return _video_concat(video_path, output_path, inputs)
        elif action == "overlay_text":
            return _video_overlay_text(video_path, output_path, text, font_size, font_color, position, bg_color)
        elif action == "add_subtitle":
            return _video_add_subtitle(video_path, output_path, subtitle_file)
        elif action == "extract_audio":
            return _video_extract_audio(video_path, output_path)
        elif action == "remove_audio":
            return _video_remove_audio(video_path, output_path)
        elif action == "speed":
            return _video_speed(video_path, output_path, float(text or "1.0"))
        elif action == "resize":
            return _video_resize(video_path, output_path, text or "1280x720")
        elif action == "gif":
            return _video_to_gif(video_path, output_path, text or "fps=10,width=480")
        elif action == "rotate":
            return _video_rotate(video_path, output_path, int(text or "90"))
        else:
            return {"success": False, "output": f"Unknown action: {action}. Available: trim, concat, overlay_text, add_subtitle, extract_audio, remove_audio, speed, resize, gif, rotate"}
    except Exception as e:
        return {"success": False, "output": f"Video edit error: {str(e)[:500]}"}


def _video_trim(video_path, output_path, start, end, duration):
    """Cut video segment."""
    if end > 0:
        cmd = f'ffmpeg -i {shlex.quote(video_path)} -ss {start} -to {end} -c copy -y {shlex.quote(output_path)}'
    elif duration > 0:
        cmd = f'ffmpeg -i {shlex.quote(video_path)} -ss {start} -t {duration} -c copy -y {shlex.quote(output_path)}'
    else:
        cmd = f'ffmpeg -i {shlex.quote(video_path)} -ss {start} -c copy -y {shlex.quote(output_path)}'
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        return {"success": True, "output": f"✅ Trimmed: {output_path} ({size/(1024*1024):.1f} MB)", "file": output_path}
    return {"success": False, "output": f"Trim failed: {result.stderr[:500]}"}


def _video_concat(video_path, output_path, inputs_str):
    """Merge multiple videos."""
    files = [f.strip() for f in inputs_str.split(",") if f.strip()]
    if not files:
        return {"success": False, "output": "No input files provided"}
    
    # Create concat list file
    list_path = f"/tmp/concat_{int(time.time())}.txt"
    with open(list_path, "w") as f:
        for fp in files:
            if os.path.exists(fp):
                f.write(f"file '{os.path.abspath(fp)}'\n")
    
    cmd = f'ffmpeg -f concat -safe 0 -i {shlex.quote(list_path)} -c copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
    
    try:
        os.unlink(list_path)
    except:
        pass
    
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        return {"success": True, "output": f"✅ Concatenated {len(files)} videos -> {output_path} ({size/(1024*1024):.1f} MB)", "file": output_path}
    return {"success": False, "output": f"Concat failed: {result.stderr[:500]}"}


def _video_overlay_text(video_path, output_path, text, font_size, font_color, position, bg_color):
    """Add text overlay on video."""
    if not text:
        return {"success": False, "output": "No text provided"}
    
    # Map position
    pos_map = {
        "center": "x=(w-text_w)/2:y=(h-text_h)/2",
        "top": "x=(w-text_w)/2:y=50",
        "bottom": "x=(w-text_w)/2:y=h-text_h-50",
        "top-left": "x=50:y=50",
        "top-right": "x=w-text_w-50:y=50",
        "bottom-left": "x=50:y=h-text_h-50",
        "bottom-right": "x=w-text_w-50:y=h-text_h-50",
    }
    xy = pos_map.get(position, pos_map["center"])
    
    # Escape special chars for ffmpeg drawtext
    safe_text = text.replace("'", "'\\''").replace(":", "\\:")
    
    # Build filter string with separate x and y
    filter_str = f"drawtext=text='{safe_text}':fontsize={font_size}:fontcolor={font_color}:box=1:boxcolor={bg_color}:boxborderw=10:{xy}"
    
    cmd = f"ffmpeg -i {shlex.quote(video_path)} -vf \"{filter_str}\" -c:a copy -y {shlex.quote(output_path)}"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        return {"success": True, "output": f"✅ Text overlay added -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Overlay failed: {result.stderr[:500]}"}


def _video_add_subtitle(video_path, output_path, subtitle_file):
    """Add .srt subtitle to video."""
    if not subtitle_file or not os.path.exists(subtitle_file):
        return {"success": False, "output": f"Subtitle file not found: {subtitle_file}"}
    
    safe_sub = subtitle_file.replace("'", "'\\''").replace(":", "\\:")
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -vf "subtitles={safe_sub}" -c:a copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        return {"success": True, "output": f"✅ Subtitles added -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Subtitle failed: {result.stderr[:500]}"}


def _video_extract_audio(video_path, output_path):
    """Extract audio track."""
    if not output_path.endswith(('.mp3', '.wav', '.aac', '.ogg')):
        output_path = output_path.rsplit('.', 1)[0] + '.mp3'
    
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -q:a 0 -map a -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        return {"success": True, "output": f"✅ Audio extracted -> {output_path} ({size/(1024*1024):.1f} MB)", "file": output_path}
    return {"success": False, "output": f"Audio extraction failed: {result.stderr[:500]}"}


def _video_remove_audio(video_path, output_path):
    """Remove audio track."""
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -an -c:v copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        return {"success": True, "output": f"✅ Audio removed -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Remove audio failed: {result.stderr[:500]}"}


def _video_speed(video_path, output_path, speed):
    """Change video speed."""
    if speed <= 0 or speed > 10:
        return {"success": False, "output": "Speed must be between 0.1 and 10"}
    
    vf = f"setpts={1/speed}*PTS"
    af = f"atempo={min(speed, 2.0)}"
    if speed > 2.0:
        af = f"atempo=2.0,atempo={speed/2.0}"
    
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -vf "{vf}" -af "{af}" -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        return {"success": True, "output": f"✅ Speed changed ({speed}x) -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Speed change failed: {result.stderr[:500]}"}


def _video_resize(video_path, output_path, size_str):
    """Resize video."""
    match = re.match(r'(\d+)x(\d+)', size_str)
    if not match:
        return {"success": False, "output": f"Invalid size format: {size_str}. Use WxH like 1280x720"}
    
    w, h = match.group(1), match.group(2)
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -vf "scale={w}:{h}" -c:a copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        return {"success": True, "output": f"✅ Resized to {w}x{h} -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Resize failed: {result.stderr[:500]}"}


def _video_to_gif(video_path, output_path, params):
    """Convert video to GIF."""
    if not output_path.endswith('.gif'):
        output_path = output_path.rsplit('.', 1)[0] + '.gif'
    
    # Parse params
    fps = 10
    width = 480
    for p in params.split(","):
        p = p.strip()
        if p.startswith("fps="):
            fps = int(p.split("=")[1])
        elif p.startswith("width="):
            width = int(p.split("=")[1])
    
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -vf "fps={fps},scale={width}:-1:flags=lanczos" -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        return {"success": True, "output": f"✅ GIF created -> {output_path} ({size/(1024*1024):.1f} MB)", "file": output_path}
    return {"success": False, "output": f"GIF conversion failed: {result.stderr[:500]}"}


def _video_rotate(video_path, output_path, degrees):
    """Rotate video."""
    rot_map = {90: "1", 180: "2", 270: "3"}
    transpose = rot_map.get(degrees)
    if not transpose:
        return {"success": False, "output": f"Unsupported rotation: {degrees}°. Use 90, 180, or 270"}
    
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -vf "transpose={transpose}" -c:a copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        return {"success": True, "output": f"✅ Rotated {degrees}° -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Rotation failed: {result.stderr[:500]}"}


# ============================================================
# TTS - Text to Speech (Vietnamese)
# ============================================================

def tts_generate(
    text: str,
    output_path: str = "",
    voice: str = "vi-VN-HoaiMyNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
    engine: str = "edge"
) -> dict:
    """
    Generate speech from text.
    
    Engines:
    - edge: Microsoft Edge TTS (free, good Vietnamese voices)
    - gtts: Google TTS (free, basic quality)
    
    Vietnamese voices (edge engine):
    - vi-VN-HoaiMyNeural (female, natural)
    - vi-VN-NamMinhNeural (male, natural)
    """
    if not text:
        return {"success": False, "output": "No text provided"}
    
    if not output_path:
        output_path = f"/tmp/tts_{int(time.time())}.mp3"
    
    engine = engine.lower().strip()
    
    try:
        if engine == "edge":
            return _tts_edge(text, output_path, voice, rate, pitch)
        elif engine == "gtts":
            return _tts_gtts(text, output_path)
        else:
            return {"success": False, "output": f"Unknown engine: {engine}. Use 'edge' or 'gtts'"}
    except Exception as e:
        return {"success": False, "output": f"TTS error: {str(e)[:500]}"}


def _tts_edge(text, output_path, voice, rate, pitch):
    """Microsoft Edge TTS (free, high quality)."""
    try:
        import edge_tts
        import asyncio
        
        async def _generate():
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(output_path)
        
        asyncio.run(_generate())
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            return {"success": True, "output": f"✅ TTS generated -> {output_path} ({size/1024:.1f} KB)", "file": output_path}
        return {"success": False, "output": "TTS failed: no output file"}
    except ImportError:
        return {"success": False, "output": "edge-tts not installed. Run: pip install edge-tts"}


def _tts_gtts(text, output_path):
    """Google TTS (free, basic)."""
    try:
        from gtts import gTTS
        
        tts = gTTS(text=text, lang='vi')
        tts.save(output_path)
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            return {"success": True, "output": f"✅ TTS (gTTS) generated -> {output_path} ({size/1024:.1f} KB)", "file": output_path}
        return {"success": False, "output": "gTTS failed: no output file"}
    except ImportError:
        return {"success": False, "output": "gTTS not installed. Run: pip install gTTS"}


# ============================================================
# VIDEO COMPOSITE (advanced)
# ============================================================

def video_composite(
    video_path: str,
    action: str,
    output_path: str = "",
    overlay_path: str = "",
    position: str = "top-right",
    scale: float = 0.3,
    opacity: float = 1.0,
    watermark_text: str = "",
    transition: str = "fade",
    **kwargs
) -> dict:
    """
    Advanced video composition.
    
    Actions:
    - pip: Picture-in-picture (overlay one video on another)
    - watermark: Add text watermark
    - fade_in: Add fade-in effect
    - fade_out: Add fade-out effect
    - crossfade: Crossfade between two videos
    """
    if not video_path or not os.path.exists(video_path):
        return {"success": False, "output": f"Video not found: {video_path}"}
    
    if not output_path:
        ext = os.path.splitext(video_path)[1]
        output_path = f"/tmp/composite_{int(time.time())}{ext}"
    
    action = action.lower().strip()
    
    try:
        if action == "pip":
            return _composite_pip(video_path, overlay_path, output_path, position, scale)
        elif action == "watermark":
            return _composite_watermark(video_path, output_path, watermark_text)
        elif action == "fade_in":
            return _composite_fade(video_path, output_path, "in")
        elif action == "fade_out":
            return _composite_fade(video_path, output_path, "out")
        else:
            return {"success": False, "output": f"Unknown composite action: {action}. Available: pip, watermark, fade_in, fade_out"}
    except Exception as e:
        return {"success": False, "output": f"Composite error: {str(e)[:500]}"}


def _composite_pip(main_video, overlay_video, output_path, position, scale):
    """Picture-in-picture overlay."""
    if not overlay_video or not os.path.exists(overlay_video):
        return {"success": False, "output": f"Overlay video not found: {overlay_video}"}
    
    pos_map = {
        "top-left": "20:20",
        "top-right": "main_w-overlay_w-20:20",
        "bottom-left": "20:main_h-overlay_h-20",
        "bottom-right": "main_w-overlay_w-20:main_h-overlay_h-20",
        "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
    }
    xy = pos_map.get(position, pos_map["top-right"])
    
    filter_str = f"[1:v]scale=iw*{scale}:ih*{scale}[ov];[0:v][ov]overlay={xy}"
    cmd = f'ffmpeg -i {shlex.quote(main_video)} -i {shlex.quote(overlay_video)} -filter_complex "{filter_str}" -c:a copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        return {"success": True, "output": f"✅ PiP created -> {output_path}", "file": output_path}
    return {"success": False, "output": f"PiP failed: {result.stderr[:500]}"}


def _composite_watermark(video_path, output_path, text):
    """Add text watermark."""
    if not text:
        return {"success": False, "output": "No watermark text"}
    
    safe_text = text.replace("'", "'\\''").replace(":", "\\:")
    filter_str = f"drawtext=text='{safe_text}':fontsize=18:fontcolor=white@0.5:x=w-tw-20:y=20"
    
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -vf "{filter_str}" -c:a copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        return {"success": True, "output": f"✅ Watermark added -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Watermark failed: {result.stderr[:500]}"}


def _composite_fade(video_path, output_path, direction):
    """Add fade effect."""
    # Get duration first
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", video_path],
        capture_output=True, text=True, timeout=10
    )
    duration = float(probe.stdout.strip() or "10")
    fade_duration = min(2.0, duration / 4)
    
    if direction == "in":
        vf = f"fade=t=in:st=0:d={fade_duration}"
    else:
        start = max(0, duration - fade_duration)
        vf = f"fade=t=out:st={start}:d={fade_duration}"
    
    cmd = f'ffmpeg -i {shlex.quote(video_path)} -vf "{vf}" -c:a copy -y {shlex.quote(output_path)}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    
    if os.path.exists(output_path):
        return {"success": True, "output": f"✅ Fade {direction} added -> {output_path}", "file": output_path}
    return {"success": False, "output": f"Fade failed: {result.stderr[:500]}"}


# ============================================================
# TOOLS REGISTRY
# ============================================================

VIDEO_TOOLS = {
    "video_info": {
        "fn": video_info,
        "description": "Get video metadata. Args: {video_path: str}"
    },
    "video_edit": {
        "fn": video_edit,
        "description": """Edit video. Args: {video_path: str, action: str, ...}
Actions: trim, concat, overlay_text, add_subtitle, extract_audio, remove_audio, speed, resize, gif, rotate
Extra args: start, end, duration, text, font_size, font_color, position, subtitle_file, inputs"""
    },
    "video_composite": {
        "fn": video_composite,
        "description": """Advanced composition. Args: {video_path: str, action: str, ...}
Actions: pip, watermark, fade_in, fade_out
Extra args: overlay_path, position, scale, watermark_text"""
    },
    "tts_generate": {
        "fn": tts_generate,
        "description": """Generate speech from text. Args: {text: str, ...}
Engines: edge (Vietnamese voices), gtts
Vietnamese voices: vi-VN-HoaiMyNeural (female), vi-VN-NamMinhNeural (male)"""
    },
}
