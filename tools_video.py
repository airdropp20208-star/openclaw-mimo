"""
Video Editing & TTS Tools for OpenClaw MiMo Agent.

Tools:
- video_edit: Cut, trim, merge, add subtitles, overlay text on video
- video_info: Get video metadata (duration, resolution, codec)
- tts_generate: Generate Vietnamese speech using OmniVoice (voice cloning) or Edge TTS fallback
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
    except Exception:
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
# TTS - Text to Speech (OmniVoice + Edge TTS fallback)
# ============================================================

# Lazy-loaded OmniVoice model
_omnivoice_model = None

def _get_omnivoice_model():
    """Lazy-load OmniVoice model (downloads on first use)."""
    global _omnivoice_model
    if _omnivoice_model is not None:
        return _omnivoice_model
    
    try:
        import torch
        from omnivoice import OmniVoice
        
        print("🔄 Loading OmniVoice model (first time may take 2-5 minutes)...")
        _omnivoice_model = OmniVoice.from_pretrained(
            "k2-fsa/OmniVoice",
            device_map="cpu",  # Use CPU if no GPU
            dtype=torch.float32
        )
        print("✅ OmniVoice model loaded!")
        return _omnivoice_model
    except Exception as e:
        print(f"⚠️ OmniVoice load failed: {e}")
        return None


def tts_generate(
    text: str,
    output_path: str = "",
    voice: str = "vi-VN-HoaiMyNeural",
    rate: str = "+0%",
    pitch: str = "+0Hz",
    engine: str = "omnivoice",
    ref_audio: str = "",
    ref_text: str = "",
    instruct: str = "",
    speed: float = 1.0,
    **kwargs
) -> dict:
    """
    Generate speech from text.
    
    Engines:
    - omnivoice: OmniVoice TTS (voice cloning + voice design) [DEFAULT]
    - edge: Microsoft Edge TTS (free, good Vietnamese voices)
    - gtts: Google TTS (free, basic quality)
    
    OmniVoice Modes:
    1. Voice Cloning: Provide ref_audio + ref_text (or auto-transcribe)
    2. Voice Design: Provide instruct (e.g., "female, vietnamese accent")
    3. Auto Voice: Just text, model chooses automatically
    
    Vietnamese voices (edge engine):
    - vi-VN-HoaiMyNeural (female, natural)
    - vi-VN-NamMinhNeural (male, natural)
    """
    if not text:
        return {"success": False, "output": "No text provided"}
    
    if not output_path:
        output_path = f"/tmp/tts_{int(time.time())}.wav"
    
    engine = engine.lower().strip()
    
    try:
        if engine == "omnivoice":
            return _tts_omnivoice(text, output_path, ref_audio, ref_text, instruct, speed)
        elif engine == "edge":
            return _tts_edge(text, output_path, voice, rate, pitch)
        elif engine == "gtts":
            return _tts_gtts(text, output_path)
        else:
            return {"success": False, "output": f"Unknown engine: {engine}. Use 'omnivoice', 'edge', or 'gtts'"}
    except Exception as e:
        return {"success": False, "output": f"TTS error: {str(e)[:500]}"}


def _tts_omnivoice(text, output_path, ref_audio, ref_text, instruct, speed):
    """OmniVoice TTS - Voice Cloning & Design."""
    model = _get_omnivoice_model()
    if model is None:
        return {"success": False, "output": "OmniVoice model not available. Use engine='edge' as fallback."}
    
    try:
        import torch
        import soundfile as sf
        
        # Prepare generation kwargs
        gen_kwargs = {"text": text, "speed": speed}
        
        # Mode 1: Voice Cloning (reference audio)
        if ref_audio and os.path.exists(ref_audio):
            gen_kwargs["ref_audio"] = ref_audio
            if ref_text:
                gen_kwargs["ref_text"] = ref_text
            mode = "Voice Cloning"
        # Mode 2: Voice Design (instruct)
        elif instruct:
            gen_kwargs["instruct"] = instruct
            mode = f"Voice Design ({instruct})"
        # Mode 3: Auto Voice
        else:
            mode = "Auto Voice"
        
        print(f"🎤 OmniVoice [{mode}]: Generating speech...")
        audio = model.generate(**gen_kwargs)
        
        # Save audio
        sf.write(output_path, audio[0], 24000)
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            return {
                "success": True, 
                "output": f"✅ OmniVoice [{mode}] -> {output_path} ({size/1024:.1f} KB)", 
                "file": output_path
            }
        return {"success": False, "output": "OmniVoice: no output file"}
    except Exception as e:
        return {"success": False, "output": f"OmniVoice error: {str(e)[:500]}"}


def _tts_edge(text, output_path, voice, rate, pitch):
    """Microsoft Edge TTS (free, high quality)."""
    if not output_path.endswith('.mp3'):
        output_path = output_path.rsplit('.', 1)[0] + '.mp3'
    
    try:
        import edge_tts
        import asyncio
        
        async def _generate():
            communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await communicate.save(output_path)
        
        asyncio.run(_generate())
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            return {"success": True, "output": f"✅ Edge TTS -> {output_path} ({size/1024:.1f} KB)", "file": output_path}
        return {"success": False, "output": "Edge TTS failed: no output file"}
    except ImportError:
        return {"success": False, "output": "edge-tts not installed. Run: pip install edge-tts"}


def _tts_gtts(text, output_path):
    """Google TTS (free, basic)."""
    if not output_path.endswith('.mp3'):
        output_path = output_path.rsplit('.', 1)[0] + '.mp3'
    
    try:
        from gtts import gTTS
        
        tts = gTTS(text=text, lang='vi')
        tts.save(output_path)
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            return {"success": True, "output": f"✅ gTTS -> {output_path} ({size/1024:.1f} KB)", "file": output_path}
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
        "description": """Generate speech from text. Args: {text: str, engine?: str, ...}
Engines: omnivoice (voice cloning/design), edge (Vietnamese voices), gtts
OmniVoice modes: ref_audio (clone), instruct (design), auto
Vietnamese voices (edge): vi-VN-HoaiMyNeural (female), vi-VN-NamMinhNeural (male)"""
    },
}


# ============================================================
# VIDEO DUBBING (Whisper + MiMo + TTS)
# ============================================================

def video_dub(
    video_path: str,
    output_path: str = "",
    source_lang: str = "zh",
    target_lang: str = "vi",
    api_key: str = "",
    api_base: str = "https://api.xiaomimimo.com/v1",
    model: str = "mimo-v2.5",
    tts_engine: str = "edge",
    tts_voice: str = "vi-VN-HoaiMyNeural",
    keep_original: bool = False,
    **kwargs
) -> dict:
    """
    Dub video: transcribe → translate → TTS → combine.
    
    Args:
        video_path: Input video file or YouTube URL
        source_lang: Source language (zh, en, ja, ko, etc.)
        target_lang: Target language (vi for Vietnamese)
        api_key: MiMo API key for translation
        tts_engine: TTS engine (edge, omnivoice)
        tts_voice: Voice for edge TTS
        keep_original: Keep original audio mixed with dubbed
    """
    import os, time, subprocess, json, re
    from pathlib import Path
    
    if not video_path:
        return {"success": False, "output": "No video provided"}
    
    if not output_path:
        output_path = f"/tmp/dubbed_{int(time.time())}.mp4"
    
    work_dir = f"/tmp/dub_work_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    
    try:
        # Step 0: Download YouTube if URL
        if "youtube.com" in video_path or "youtu.be" in video_path:
            print("📥 Downloading from YouTube...")
            yt_cmd = [
                "yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "-o", f"{work_dir}/input.%(ext)s",
                "--merge-output-format", "mp4",
                video_path
            ]
            result = subprocess.run(yt_cmd, capture_output=True, text=True, timeout=300)
            # Find downloaded file
            for f in os.listdir(work_dir):
                if f.startswith("input."):
                    video_path = os.path.join(work_dir, f)
                    break
            if not os.path.exists(video_path):
                return {"success": False, "output": f"YouTube download failed: {result.stderr[:500]}"}
            print(f"  ✅ Downloaded: {video_path}")
        
        if not os.path.exists(video_path):
            return {"success": False, "output": f"Video not found: {video_path}"}
        
        # Step 1: Extract audio
        print("[1/5] Extracting audio...")
        audio_path = f"{work_dir}/audio.wav"
        cmd = f'ffmpeg -i {shlex.quote(video_path)} -vn -acodec pcm_s16le -ar 16000 -ac 1 -y {shlex.quote(audio_path)}'
        subprocess.run(cmd, shell=True, capture_output=True, timeout=120)
        if not os.path.exists(audio_path):
            return {"success": False, "output": "Failed to extract audio"}
        print("  ✅ Audio extracted")
        
        # Step 2: Transcribe with Whisper
        print("[2/5] Transcribing with Whisper...")
        from faster_whisper import WhisperModel
        
        device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda:0"
        except Exception:
            pass
        
        compute = "float16" if "cuda" in device else "int8"
        whisper_model = WhisperModel("large-v3", device=device, compute_type=compute,
                                     download_root=str(Path.home() / ".cache" / "whisper"))
        
        segments, info = whisper_model.transcribe(
            audio_path, language=source_lang, vad_filter=True, beam_size=5
        )
        
        texts, timings = [], []
        for seg in segments:
            texts.append(seg.text.strip())
            timings.append([seg.start, seg.end])
        
        print(f"  ✅ {len(texts)} segments transcribed")
        
        if not texts:
            return {"success": False, "output": "No speech detected in video"}
        
        # Step 3: Translate with MiMo
        print("[3/5] Translating with MiMo...")
        import urllib.request
        
        translated = []
        for i in range(0, len(texts), 50):
            batch = texts[i:i+50]
            numbered = "\n".join(f"{j+1}. {t}" for j, t in enumerate(batch))
            
            prompt = f"""Translate these numbered lines from {source_lang} to {target_lang}.
Rules: Only output translations, numbered. Natural phrasing, not literal.

{numbered}"""
            
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": f"You are a professional video translator. Translate from {source_lang} to {target_lang}."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 4000,
                "temperature": 0.3
            }).encode()
            
            req = urllib.request.Request(
                f"{api_base}/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
            
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                content = result["choices"][0]["message"]["content"]
                
                # Parse numbered translations
                for line in content.strip().split("\n"):
                    line = line.strip()
                    match = re.match(r"^\d+[\.\)]\s*(.+)", line)
                    if match:
                        translated.append(match.group(1).strip())
        
        # Pad if needed
        while len(translated) < len(texts):
            translated.append(texts[len(translated)] if len(translated) < len(texts) else "")
        
        print(f"  ✅ {len(translated)} segments translated")
        
        # Step 4: Generate TTS
        print("[4/5] Generating TTS...")
        tts_segments = []
        
        for i, (text, timing) in enumerate(zip(translated, timings)):
            if not text:
                continue
            
            tts_path = f"{work_dir}/tts_{i:04d}.mp3"
            
            if tts_engine == "edge":
                result = tts_generate(text, tts_path, engine="edge", voice=tts_voice)
            else:
                result = tts_generate(text, tts_path, engine="omnivoice")
            
            if result["success"] and os.path.exists(tts_path):
                tts_segments.append({
                    "file": tts_path,
                    "start": timing[0],
                    "end": timing[1],
                    "text": text
                })
        
        print(f"  ✅ {len(tts_segments)} TTS segments generated")
        
        if not tts_segments:
            return {"success": False, "output": "TTS generation failed"}
        
        # Step 5: Combine audio with video
        print("[5/5] Combining audio with video...")
        
        # Build filter to place TTS at correct timestamps
        filter_inputs = ""
        filter_complex = ""
        
        for i, seg in enumerate(tts_segments):
            filter_inputs += f" -i {shlex.quote(seg['file'])}"
            delay_ms = int(seg["start"] * 1000)
            filter_complex += f"[{i}:a]adelay={delay_ms}|{delay_ms},aresample=44100[a{i}];"
        
        # Mix all delayed segments
        mix_inputs = "".join(f"[a{i}]" for i in range(len(tts_segments)))
        filter_complex += f"{mix_inputs}amix=inputs={len(tts_segments)}:duration=longest[voice];"
        
        if keep_original:
            filter_complex += f"[0:a]aresample=44100[orig];[orig][voice]amix=inputs=2:duration=first[out]"
        else:
            filter_complex += f"[voice]aresample=44100[out]"
        
        output_audio = f"{work_dir}/dubbed_audio.wav"
        full_cmd = f'ffmpeg -i {shlex.quote(video_path)} {filter_inputs} -filter_complex "{filter_complex}" -map "[out]" -y {shlex.quote(output_audio)}'
        subprocess.run(full_cmd, shell=True, capture_output=True, timeout=120)
        
        if not os.path.exists(output_audio):
            # Fallback: use first TTS segment
            output_audio = tts_segments[0]["file"]
        
        # Replace video audio
        final_cmd = f'ffmpeg -i {shlex.quote(video_path)} -i {shlex.quote(output_audio)} -c:v copy -map 0:v:0 -map 1:a:0 -shortest -y {shlex.quote(output_path)}'
        subprocess.run(final_cmd, shell=True, capture_output=True, timeout=120)
        
        # Cleanup
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            return {
                "success": True,
                "output": f"✅ Video dubbed ({source_lang}→{target_lang})\n📝 {len(translated)} segments\n📁 {output_path} ({size/(1024*1024):.1f} MB)",
                "file": output_path
            }
        
        return {"success": False, "output": "Failed to create final video"}
        
    except Exception as e:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        return {"success": False, "output": f"Dubbing error: {str(e)[:500]}"}


def youtube_download(url: str, output_path: str = "") -> dict:
    """Download video from YouTube."""
    import subprocess, os, time
    
    if not output_path:
        output_path = f"/tmp/ytdl_{int(time.time())}.mp4"
    
    work_dir = f"/tmp/ytdl_{int(time.time())}"
    os.makedirs(work_dir, exist_ok=True)
    
    try:
        cmd = [
            "yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "-o", f"{work_dir}/video.%(ext)s",
            "--merge-output-format", "mp4",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        for f in os.listdir(work_dir):
            if f.startswith("video."):
                src = os.path.join(work_dir, f)
                os.rename(src, output_path)
                break
        
        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            return {"success": True, "output": f"✅ Downloaded -> {output_path} ({size/(1024*1024):.1f} MB)", "file": output_path}
        
        return {"success": False, "output": f"Download failed: {result.stderr[:500]}"}
    except Exception as e:
        return {"success": False, "output": f"Download error: {str(e)[:500]}"}


# Add to VIDEO_TOOLS
VIDEO_TOOLS["video_dub"] = {
    "fn": video_dub,
    "description": """Dub video: transcribe → translate → TTS → combine.
Args: {video_path: str, source_lang: str, target_lang: str, api_key: str, ...}
Supports YouTube URLs directly.
Languages: zh (Chinese), en (English), ja (Japanese), ko (Korean) → vi (Vietnamese)"""
}
VIDEO_TOOLS["youtube_download"] = {
    "fn": youtube_download,
    "description": "Download YouTube video. Args: {url: str, output_path?: str}"
}
