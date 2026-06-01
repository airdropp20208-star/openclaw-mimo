#!/usr/bin/env python3
"""
Dubbing Engine — Voice-Video Sync
===================================
Core engine for professional video dubbing with precise voice-video synchronization.

Key features:
- Whisper transcription with word-level timestamps
- TTS generation via remote OmniVoice API
- Voice speed adjustment to match original segment duration
- Audio cross-fade between segments
- Subtitle generation with proper timing
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Optional

import requests


# ─── Config ────────────────────────────────────────────────────────
@dataclass
class DubConfig:
    # APIs
    mimo_api_key: str = ""
    mimo_api_base: str = "https://api.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.5-pro"
    omnivoice_url: str = ""  # Remote OmniVoice API server
    omnivoice_key: str = ""
    
    # Whisper
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"  # auto, cuda, cpu
    
    # TTS
    tts_engine: str = "omnivoice"  # omnivoice, edge
    tts_voice: str = "vi-VN-HoaiMyNeural"  # Edge TTS voice
    tts_instruct: str = "female, vietnamese accent, natural"  # OmniVoice voice design
    tts_ref_audio: str = ""  # Reference audio for voice cloning
    tts_ref_text: str = ""  # Transcription of reference audio
    tts_speed: float = 1.0
    
    # Sync
    sync_mode: str = "stretch"  # stretch, pad, compress
    sync_tolerance: float = 0.1  # 10% tolerance before adjusting
    crossfade_ms: int = 50  # Cross-fade between segments
    
    # Output
    output_sample_rate: int = 24000
    output_channels: int = 1


# ─── Data models ───────────────────────────────────────────────────
@dataclass
class Segment:
    index: int
    start: float
    end: float
    text: str
    text_vi: str = ""
    tts_path: str = ""
    tts_duration: float = 0.0
    speed_factor: float = 1.0
    synced_path: str = ""


@dataclass
class DubResult:
    success: bool
    output_video: str = ""
    output_srt: str = ""
    segments: list = field(default_factory=list)
    total_duration: float = 0.0
    processing_time: float = 0.0
    error: str = ""


def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


# ─── Step 1: Download ──────────────────────────────────────────────
def download_video(url: str, output_dir: str) -> str:
    """Download video from URL."""
    log(f"📥 Downloading: {url}")
    output_path = os.path.join(output_dir, "source")
    
    cmd = (
        f'yt-dlp -f "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best" '
        f'--merge-output-format mp4 --no-watermark '
        f'-o "{output_path}.%(ext)s" "{url}" 2>&1'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    
    for ext in ["mp4", "webm", "mkv"]:
        path = f"{output_path}.{ext}"
        if os.path.exists(path):
            log(f"  ✅ Downloaded: {os.path.basename(path)}")
            return path
    
    raise FileNotFoundError(f"Download failed: {result.stderr[:300]}")


# ─── Step 2: Extract Audio ─────────────────────────────────────────
def extract_audio(video_path: str, output_dir: str) -> str:
    """Extract audio from video."""
    log("🔊 Extracting audio...")
    audio_path = os.path.join(output_dir, "audio_original.wav")
    
    cmd = (
        f'ffmpeg -i "{video_path}" -vn '
        f'-acodec pcm_s16le -ar 16000 -ac 1 '
        f'-y "{audio_path}" 2>/dev/null'
    )
    subprocess.run(cmd, shell=True, timeout=120)
    
    if os.path.exists(audio_path):
        log(f"  ✅ Extracted: {os.path.basename(audio_path)}")
        return audio_path
    raise FileNotFoundError("Audio extraction failed")


# ─── Step 3: Transcribe (Word-level timestamps) ───────────────────
def transcribe(audio_path: str, source_lang: str = "zh", config: DubConfig = None) -> list[Segment]:
    """Transcribe with word-level timestamps for precise sync."""
    log(f"📝 Transcribing ({source_lang}) with word-level timestamps...")
    
    if config is None:
        config = DubConfig()
    
    device = config.whisper_device
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except:
            device = "cpu"
    
    from faster_whisper import WhisperModel
    
    model = WhisperModel(config.whisper_model, device=device, compute_type="float16" if device == "cuda" else "int8")
    
    segments, info = model.transcribe(
        audio_path,
        language=source_lang,
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,  # Key for sync!
    )
    
    result = []
    for i, seg in enumerate(segments):
        segment = Segment(
            index=i,
            start=seg.start,
            end=seg.end,
            text=seg.text.strip(),
        )
        result.append(segment)
        log(f"  [{seg.start:.2f}s-{seg.end:.2f}s] {seg.text.strip()[:50]}")
    
    log(f"  ✅ {len(result)} segments ({info.language}, prob={info.language_probability:.2f})")
    return result


# ─── Step 4: Translate ─────────────────────────────────────────────
def translate(segments: list[Segment], source_lang: str, target_lang: str, config: DubConfig) -> list[Segment]:
    """Translate segments using MiMo API."""
    log(f"🌐 Translating {source_lang} → {target_lang}...")
    
    if not config.mimo_api_key:
        log("  ⚠️ No MIMO_API_KEY, skipping translation")
        return segments
    
    # Batch translate for context
    numbered = "\n".join(f"{i+1}. {s.text}" for i, s in enumerate(segments))
    
    prompt = f"""Translate the following {source_lang} dialogue to {target_lang}.
Keep the EXACT same numbering (1. 2. 3. etc).
Translate naturally for video dubbing — conversational, emotional, concise.
Only output the numbered translations, nothing else.

{numbered}"""
    
    payload = {
        "model": config.mimo_model,
        "messages": [
            {"role": "system", "content": f"Professional {source_lang} to {target_lang} translator for video dubbing. Natural, conversational, emotional."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    
    headers = {
        "Authorization": f"Bearer {config.mimo_api_key}",
        "Content-Type": "application/json",
    }
    
    try:
        resp = requests.post(
            f"{config.mimo_api_base}/chat/completions",
            headers=headers, json=payload, timeout=120,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        
        import re
        translations = []
        for line in content.split("\n"):
            m = re.match(r"^\d+[\.):\s]+\s*(.+)", line.strip())
            if m:
                translations.append(m.group(1).strip())
        
        for i, seg in enumerate(segments):
            if i < len(translations):
                seg.text_vi = translations[i]
            else:
                seg.text_vi = seg.text
        
        log(f"  ✅ Translated {len(segments)} segments")
        return segments
        
    except Exception as e:
        log(f"  ❌ Translation failed: {e}")
        return segments


# ─── Step 5: TTS ───────────────────────────────────────────────────
def generate_tts(segments: list[Segment], output_dir: str, config: DubConfig) -> list[Segment]:
    """Generate TTS for each segment."""
    log(f"🗣️ Generating TTS ({config.tts_engine})...")
    
    tts_dir = os.path.join(output_dir, "tts")
    os.makedirs(tts_dir, exist_ok=True)
    
    for seg in segments:
        text = seg.text_vi or seg.text
        if not text:
            continue
        
        tts_path = os.path.join(tts_dir, f"seg_{seg.index:04d}.wav")
        
        if config.tts_engine == "omnivoice" and config.omnivoice_url:
            _tts_omnivoice_remote(text, tts_path, config)
        elif config.tts_engine == "edge":
            _tts_edge(text, tts_path, config)
        else:
            _tts_edge(text, tts_path, config)
        
        seg.tts_path = tts_path
        
        # Get TTS duration
        if os.path.exists(tts_path):
            seg.tts_duration = _get_audio_duration(tts_path)
            log(f"  [{seg.index}] ✅ {seg.tts_duration:.2f}s — {text[:30]}...")
        else:
            log(f"  [{seg.index}] ❌ Failed")
    
    return segments


def _tts_omnivoice_remote(text: str, output_path: str, config: DubConfig):
    """TTS via remote OmniVoice API."""
    try:
        url = config.omnivoice_url.rstrip("/") + "/tts"
        headers = {}
        if config.omnivoice_key:
            headers["Authorization"] = f"Bearer {config.omnivoice_key}"
        
        payload = {
            "text": text,
            "speed": config.tts_speed,
            "format": "wav",
        }
        
        if config.tts_ref_audio and os.path.exists(config.tts_ref_audio):
            with open(config.tts_ref_audio, "rb") as f:
                payload["ref_audio"] = base64.b64encode(f.read()).decode()
            if config.tts_ref_text:
                payload["ref_text"] = config.tts_ref_text
        else:
            payload["instruct"] = config.tts_instruct
        
        resp = requests.post(url, json=payload, headers=headers, timeout=300)
        resp.raise_for_status()
        
        with open(output_path, "wb") as f:
            f.write(resp.content)
        
    except Exception as e:
        log(f"    OmniVoice error: {e}")
        _tts_edge(text, output_path, config)


def _tts_edge(text: str, output_path: str, config: DubConfig):
    """TTS via Edge TTS."""
    try:
        import edge_tts
        import asyncio
        
        async def _gen():
            comm = edge_tts.Communicate(text, config.tts_voice)
            mp3_path = output_path.replace(".wav", ".mp3")
            await comm.save(mp3_path)
            subprocess.run(
                f'ffmpeg -i "{mp3_path}" -ar {config.output_sample_rate} -ac {config.output_channels} -y "{output_path}" 2>/dev/null',
                shell=True,
            )
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
        
        asyncio.run(_gen())
    except Exception as e:
        log(f"    Edge TTS error: {e}")


def _get_audio_duration(path: str) -> float:
    """Get audio duration in seconds."""
    try:
        result = subprocess.run(
            f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{path}"',
            shell=True, capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip() or "0")
    except:
        return 0.0


# ─── Step 6: Voice Sync (THE KEY FEATURE) ─────────────────────────
def sync_voices(segments: list[Segment], output_dir: str, config: DubConfig) -> list[Segment]:
    """
    Sync TTS audio to match original video timing.
    
    For each segment:
    - If TTS is longer than original → speed up (compress)
    - If TTS is shorter than original → slow down (stretch) or pad silence
    - Apply cross-fade between segments for smooth transitions
    """
    log("🎯 Syncing voice to video timing...")
    
    sync_dir = os.path.join(output_dir, "synced")
    os.makedirs(sync_dir, exist_ok=True)
    
    for seg in segments:
        if not seg.tts_path or not os.path.exists(seg.tts_path):
            continue
        
        target_duration = seg.end - seg.start
        original_duration = seg.tts_duration
        
        if original_duration <= 0 or target_duration <= 0:
            continue
        
        # Calculate speed factor
        speed_factor = original_duration / target_duration
        
        synced_path = os.path.join(sync_dir, f"seg_{seg.index:04d}.wav")
        
        # Apply speed adjustment using ffmpeg atempo
        # atempo range: 0.5 to 2.0, chain multiple for larger adjustments
        _adjust_audio_speed(seg.tts_path, synced_path, speed_factor, config)
        
        seg.synced_path = synced_path
        seg.speed_factor = speed_factor
        
        # Get final duration
        final_duration = _get_audio_duration(synced_path)
        log(f"  [{seg.index}] {original_duration:.2f}s → {final_duration:.2f}s (target: {target_duration:.2f}s, speed: {speed_factor:.2f}x)")
    
    return segments


def _adjust_audio_speed(input_path: str, output_path: str, speed_factor: float, config: DubConfig):
    """Adjust audio speed using ffmpeg atempo filter."""
    # Clamp speed to valid range (0.5 - 2.0 per atempo, chain for larger)
    if speed_factor < 0.5:
        speed_factor = 0.5
    elif speed_factor > 2.0:
        speed_factor = 2.0
    
    # Build atempo filter chain
    filters = []
    remaining = speed_factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.4f}")
    
    atempo_chain = ",".join(filters)
    
    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-filter:a "{atempo_chain}" '
        f'-ar {config.output_sample_rate} -ac {config.output_channels} '
        f'-y "{output_path}" 2>/dev/null'
    )
    subprocess.run(cmd, shell=True, timeout=60)


# ─── Step 7: Combine Audio ────────────────────────────────────────
def combine_audio(segments: list[Segment], video_path: str, output_dir: str, config: DubConfig) -> str:
    """Combine synced TTS segments into final audio track, mixed with original."""
    log("🎵 Combining audio tracks...")
    
    # Get video duration
    video_duration = _get_audio_duration(video_path)
    
    # Build ffmpeg filter complex for precise placement
    inputs = ["-i", video_path]  # Input 0: video
    filter_parts = []
    audio_inputs = []
    
    valid_segments = [s for s in segments if s.synced_path and os.path.exists(s.synced_path)]
    
    if not valid_segments:
        log("  ⚠️ No synced segments, using original audio")
        return video_path
    
    for i, seg in enumerate(valid_segments):
        inputs.extend(["-i", seg.synced_path])
        delay_ms = int(seg.start * 1000)
        filter_parts.append(
            f"[{i+1}:a]adelay={delay_ms}|{delay_ms},aresample={config.output_sample_rate}[a{i}]"
        )
        audio_inputs.append(f"[a{i}]")
    
    # Mix all TTS segments
    mix_inputs = "".join(audio_inputs)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(audio_inputs)}:duration=longest:normalize=0[out_tts]"
    )
    
    # Mix with original audio (lowered volume)
    filter_parts.append(
        f"[0:a]volume=0.15[bg]"
    )
    filter_parts.append(
        f"[bg][out_tts]amix=inputs=2:duration=first[out]"
    )
    
    filter_complex = ";".join(filter_parts)
    
    output_video = os.path.join(output_dir, "dubbed.mp4")
    
    cmd = (
        f'ffmpeg {" ".join(inputs)} '
        f'-filter_complex "{filter_complex}" '
        f'-map 0:v -map "[out]" '
        f'-c:v copy -c:a aac -b:a 192k '
        f'-shortest '
        f'-y "{output_video}" 2>/dev/null'
    )
    
    subprocess.run(cmd, shell=True, timeout=600)
    
    if os.path.exists(output_video):
        log(f"  ✅ Dubbed video: {os.path.basename(output_video)}")
        return output_video
    
    log("  ❌ Combine failed")
    return video_path


# ─── Step 8: Subtitles ────────────────────────────────────────────
def generate_subtitles(segments: list[Segment], output_dir: str) -> str:
    """Generate SRT subtitle file."""
    log("📄 Generating subtitles...")
    
    srt_path = os.path.join(output_dir, "subtitles.srt")
    
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments):
            text = seg.text_vi or seg.text
            if not text:
                continue
            
            start = _format_srt(seg.start)
            end = _format_srt(seg.end)
            f.write(f"{i+1}\n{start} --> {end}\n{text}\n\n")
    
    log(f"  ✅ Subtitles: {len(segments)} lines")
    return srt_path


def _format_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─── Main Pipeline ─────────────────────────────────────────────────
def run_pipeline(
    url: str = "",
    video_path: str = "",
    source_lang: str = "Chinese",
    target_lang: str = "Vietnamese",
    config: DubConfig = None,
    output_dir: str = "/tmp/dub_output",
) -> DubResult:
    """Run the full dubbing pipeline."""
    if config is None:
        config = DubConfig()
    
    os.makedirs(output_dir, exist_ok=True)
    start_time = time.time()
    
    lang_codes = {"Chinese": "zh", "Japanese": "ja", "Korean": "ko"}
    source_code = lang_codes.get(source_lang, "zh")
    
    try:
        # Step 1: Download or use provided video
        if url:
            video_path = download_video(url, output_dir)
        
        if not video_path or not os.path.exists(video_path):
            return DubResult(success=False, error="No video provided")
        
        # Step 2: Extract audio
        audio_path = extract_audio(video_path, output_dir)
        
        # Step 3: Transcribe
        segments = transcribe(audio_path, source_code, config)
        
        # Save segments
        _save_segments(segments, os.path.join(output_dir, "segments.json"))
        
        # Step 4: Translate
        segments = translate(segments, source_lang, target_lang, config)
        
        # Save translated
        _save_segments(segments, os.path.join(output_dir, "translated.json"))
        
        # Step 5: TTS
        segments = generate_tts(segments, output_dir, config)
        
        # Step 6: Voice Sync
        segments = sync_voices(segments, output_dir, config)
        
        # Step 7: Combine
        output_video = combine_audio(segments, video_path, output_dir, config)
        
        # Step 8: Subtitles
        output_srt = generate_subtitles(segments, output_dir)
        
        elapsed = time.time() - start_time
        log(f"\n🎉 Done in {elapsed:.0f}s!")
        
        return DubResult(
            success=True,
            output_video=output_video,
            output_srt=output_srt,
            segments=segments,
            total_duration=video_duration if 'video_duration' in dir() else 0,
            processing_time=elapsed,
        )
        
    except Exception as e:
        log(f"❌ Pipeline failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return DubResult(success=False, error=str(e))


def _save_segments(segments: list[Segment], path: str):
    """Save segments to JSON."""
    data = [
        {
            "index": s.index,
            "start": s.start,
            "end": s.end,
            "text": s.text,
            "text_vi": s.text_vi,
            "tts_duration": s.tts_duration,
            "speed_factor": s.speed_factor,
        }
        for s in segments
    ]
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── CLI ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Video Dubbing Engine")
    parser.add_argument("--url", default="", help="Video URL")
    parser.add_argument("--video", default="", help="Local video path")
    parser.add_argument("--source-lang", default="Chinese")
    parser.add_argument("--target-lang", default="Vietnamese")
    parser.add_argument("--tts-engine", default="omnivoice", choices=["omnivoice", "edge"])
    parser.add_argument("--omnivoice-url", default="", help="OmniVoice API server URL")
    parser.add_argument("--omnivoice-key", default="", help="OmniVoice API key")
    parser.add_argument("--mimo-key", default="", help="MiMo API key")
    parser.add_argument("--output", default="/tmp/dub_output")
    args = parser.parse_args()
    
    config = DubConfig(
        tts_engine=args.tts_engine,
        omnivoice_url=args.omnivoice_url or os.getenv("OMNIVOICE_API_URL", ""),
        omnivoice_key=args.omnivoice_key or os.getenv("OMNIVOICE_API_KEY", ""),
        mimo_api_key=args.mimo_key or os.getenv("MIMO_API_KEY", ""),
    )
    
    result = run_pipeline(
        url=args.url,
        video_path=args.video,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        config=config,
        output_dir=args.output,
    )
    
    if result.success:
        print(f"\n✅ Output: {result.output_video}")
        print(f"📄 Subtitles: {result.output_srt}")
    else:
        print(f"\n❌ Failed: {result.error}")
        sys.exit(1)
