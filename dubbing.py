#!/usr/bin/env python3
"""
Donghua Dubbing Pipeline
========================
Download → Transcribe → Translate → TTS → Combine → Output

Usage:
  python dubbing.py --url "https://..." --source-lang Chinese --target-lang Vietnamese

Environment:
  VIDEO_URL, SOURCE_LANG, TARGET_LANG, TTS_ENGINE
  MIMO_API_KEY, MIMO_API_BASE, MIMO_MODEL
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ─── Config ────────────────────────────────────────────────────────
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")  # auto, cuda, cpu
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
TTS_ENGINE = os.getenv("TTS_ENGINE", "omnivoice")

# Language codes
LANG_CODES = {
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko",
    "Vietnamese": "vi",
    "English": "en",
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_cmd(cmd, timeout=300):
    """Run shell command and return output."""
    log(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        log(f"  ERROR: {result.stderr[:500]}")
    return result


# ─── Step 1: Download Video ────────────────────────────────────────
def download_video(url, output_dir):
    """Download video from YouTube/Bilibili/etc."""
    log("📥 Downloading video...")
    output_path = os.path.join(output_dir, "source")
    
    cmd = (
        f'yt-dlp -f "bestvideo[height<=1080]+bestaudio/best[height<=1080]" '
        f'--merge-output-format mp4 '
        f'--no-watermark '
        f'-o "{output_path}.%(ext)s" '
        f'"{url}"'
    )
    result = run_cmd(cmd, timeout=600)
    
    # Find the downloaded file
    for ext in ["mp4", "webm", "mkv"]:
        path = f"{output_path}.{ext}"
        if os.path.exists(path):
            log(f"  ✅ Downloaded: {path}")
            return path
    
    # Fallback: find any file matching source.*
    import glob
    files = glob.glob(f"{output_path}.*")
    if files:
        log(f"  ✅ Downloaded: {files[0]}")
        return files[0]
    
    raise FileNotFoundError(f"Download failed: {result.stderr[:200]}")


# ─── Step 2: Extract Audio ─────────────────────────────────────────
def extract_audio(video_path, output_dir):
    """Extract audio track from video."""
    log("🔊 Extracting audio...")
    audio_path = os.path.join(output_dir, "audio_original.wav")
    
    cmd = (
        f'ffmpeg -i "{video_path}" '
        f'-vn -acodec pcm_s16le -ar 16000 -ac 1 '
        f'-y "{audio_path}" 2>/dev/null'
    )
    run_cmd(cmd)
    
    if os.path.exists(audio_path):
        log(f"  ✅ Audio extracted: {audio_path}")
        return audio_path
    raise FileNotFoundError("Audio extraction failed")


# ─── Step 3: Transcribe with Whisper ───────────────────────────────
def transcribe(audio_path, source_lang):
    """Transcribe audio using faster-whisper."""
    log(f"📝 Transcribing ({source_lang})...")
    
    lang_code = LANG_CODES.get(source_lang, "zh")
    
    # Auto-detect device
    device = WHISPER_DEVICE
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except:
            device = "cpu"
    
    from faster_whisper import WhisperModel
    
    model = WhisperModel(WHISPER_MODEL, device=device, compute_type="float16" if device == "cuda" else "int8")
    
    segments, info = model.transcribe(
        audio_path,
        language=lang_code,
        beam_size=5,
        vad_filter=True,
    )
    
    # Collect segments with timestamps
    transcript = []
    for seg in segments:
        transcript.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })
        log(f"  [{seg.start:.1f}s-{seg.end:.1f}s] {seg.text.strip()}")
    
    log(f"  ✅ Transcribed {len(transcript)} segments ({info.language}, prob={info.language_probability:.2f})")
    return transcript


# ─── Step 4: Translate with MiMo ──────────────────────────────────
def translate_segments(transcript, source_lang, target_lang):
    """Translate transcript using MiMo API."""
    log(f"🌐 Translating {source_lang} → {target_lang}...")
    
    if not MIMO_API_KEY:
        log("  ⚠️ No MIMO_API_KEY set, using edge-tts fallback (no translation)")
        return transcript  # Return as-is, TTS will handle
    
    import requests
    
    # Batch translate (send all text at once for context)
    full_text = "\n".join([s["text"] for s in transcript])
    
    prompt = f"""Translate the following {source_lang} text to {target_lang}.
Keep the same line structure (one translation per line).
Maintain natural, conversational tone suitable for donghua dubbing.
Only output the translation, no explanations.

{full_text}"""
    
    headers = {
        "Authorization": f"Bearer {MIMO_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": MIMO_MODEL,
        "messages": [
            {"role": "system", "content": f"You are a professional {source_lang} to {target_lang} translator specializing in Chinese donghua (animation) dialogue. Translate naturally, preserving emotional tone and cultural context."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    
    try:
        resp = requests.post(
            f"{MIMO_API_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        translated_text = resp.json()["choices"][0]["message"]["content"].strip()
        
        # Split back into segments
        translated_lines = translated_text.split("\n")
        
        # Match lines to segments
        for i, seg in enumerate(transcript):
            if i < len(translated_lines):
                seg["text_vi"] = translated_lines[i].strip()
            else:
                seg["text_vi"] = seg["text"]  # Fallback
        
        log(f"  ✅ Translated {len(transcript)} segments")
        for seg in transcript[:3]:
            log(f"    {seg['text'][:30]}... → {seg.get('text_vi', '')[:30]}...")
        
        return transcript
        
    except Exception as e:
        log(f"  ❌ Translation failed: {e}")
        return transcript


# ─── Step 5: Generate TTS ─────────────────────────────────────────
def generate_tts(transcript, output_dir, engine="omnivoice"):
    """Generate TTS audio for each segment."""
    log(f"🗣️ Generating TTS ({engine})...")
    
    tts_dir = os.path.join(output_dir, "tts_segments")
    os.makedirs(tts_dir, exist_ok=True)
    
    for i, seg in enumerate(transcript):
        text = seg.get("text_vi", seg["text"])
        if not text:
            continue
        
        tts_path = os.path.join(tts_dir, f"seg_{i:04d}.wav")
        
        if engine == "omnivoice":
            _tts_omnivoice(text, tts_path)
        elif engine == "edge":
            _tts_edge(text, tts_path)
        else:
            _tts_edge(text, tts_path)  # Fallback
        
        seg["tts_path"] = tts_path
        
        if os.path.exists(tts_path):
            log(f"  [{i}] ✅ {tts_path}")
        else:
            log(f"  [{i}] ❌ Failed: {tts_path}")
    
    return transcript


def _tts_omnivoice(text, output_path):
    """TTS using OmniVoice (needs GPU)."""
    try:
        import torch
        from omnivoice import OmniVoice
        import soundfile as sf
        
        # Lazy load model
        if not hasattr(_tts_omnivoice, "_model"):
            log("    Loading OmniVoice model...")
            _tts_omnivoice._model = OmniVoice.from_pretrained(
                "k2-fsa/OmniVoice",
                device_map="cuda" if torch.cuda.is_available() else "cpu",
                dtype=torch.float32,
            )
            log("    ✅ OmniVoice model loaded")
        
        audio = _tts_omnivoice._model.generate(
            text=text,
            language="Vietnamese",
            speed=1.0,
        )
        sf.write(output_path, audio[0], _tts_omnivoice._model.sampling_rate)
        
    except Exception as e:
        log(f"    OmniVoice error: {e}")
        # Fallback to edge
        _tts_edge(text, output_path)


def _tts_edge(text, output_path):
    """TTS using Microsoft Edge (free, fast)."""
    try:
        import edge_tts
        
        async def _gen():
            comm = edge_tts.Communicate(text, "vi-VN-HoaiMyNeural")
            mp3_path = output_path.replace(".wav", ".mp3")
            await comm.save(mp3_path)
            # Convert to WAV
            subprocess.run(
                f'ffmpeg -i "{mp3_path}" -ar 24000 -ac 1 -y "{output_path}" 2>/dev/null',
                shell=True,
            )
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
        
        asyncio.run(_gen())
        
    except Exception as e:
        log(f"    Edge TTS error: {e}")


# ─── Step 6: Combine Audio ────────────────────────────────────────
def combine_audio(transcript, video_path, output_dir):
    """Combine TTS segments with original video audio."""
    log("🎵 Combining audio tracks...")
    
    tts_dir = os.path.join(output_dir, "tts_segments")
    combined_tts = os.path.join(output_dir, "tts_combined.wav")
    
    # Create silence file
    silence = os.path.join(output_dir, "silence.wav")
    subprocess.run(
        f'ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t 0.1 -y "{silence}" 2>/dev/null',
        shell=True,
    )
    
    # Build concat list
    concat_list = os.path.join(output_dir, "concat.txt")
    with open(concat_list, "w") as f:
        for seg in transcript:
            tts_path = seg.get("tts_path", "")
            if tts_path and os.path.exists(tts_path):
                f.write(f"file '{os.path.abspath(tts_path)}'\n")
                f.write(f"file '{os.path.abspath(silence)}'\n")
    
    # Concat TTS segments
    subprocess.run(
        f'ffmpeg -f concat -safe 0 -i "{concat_list}" -c copy -y "{combined_tts}" 2>/dev/null',
        shell=True,
    )
    
    if not os.path.exists(combined_tts):
        log("  ❌ Failed to combine TTS audio")
        return video_path
    
    # Mix with original video audio (lower original volume)
    output_video = os.path.join(output_dir, "dubbed.mp4")
    
    # Get TTS duration
    result = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{combined_tts}"',
        shell=True, capture_output=True, text=True,
    )
    tts_duration = float(result.stdout.strip() or "0")
    
    # Get video duration
    result = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{video_path}"',
        shell=True, capture_output=True, text=True,
    )
    video_duration = float(result.stdout.strip() or "0")
    
    log(f"  TTS duration: {tts_duration:.1f}s, Video duration: {video_duration:.1f}s")
    
    # If TTS is shorter than video, pad with silence
    if tts_duration < video_duration:
        pad_duration = video_duration - tts_duration
        pad_silence = os.path.join(output_dir, "pad_silence.wav")
        subprocess.run(
            f'ffmpeg -f lavfi -i anullsrc=r=24000:cl=mono -t {pad_duration} -y "{pad_silence}" 2>/dev/null',
            shell=True,
        )
        with open(concat_list, "a") as f:
            f.write(f"file '{os.path.abspath(pad_silence)}'\n")
        subprocess.run(
            f'ffmpeg -f concat -safe 0 -i "{concat_list}" -c copy -y "{combined_tts}" 2>/dev/null',
            shell=True,
        )
    
    # Mix: original audio (low) + TTS audio (loud)
    cmd = (
        f'ffmpeg -i "{video_path}" -i "{combined_tts}" '
        f'-filter_complex "'
        f'[0:a]volume=0.15[bg];'
        f'[1:a]volume=1.0[tts];'
        f'[bg][tts]amix=inputs=2:duration=first[out]'
        f'" '
        f'-map 0:v -map "[out]" '
        f'-c:v copy -c:a aac -b:a 192k '
        f'-shortest '
        f'-y "{output_video}" 2>/dev/null'
    )
    run_cmd(cmd, timeout=600)
    
    if os.path.exists(output_video):
        log(f"  ✅ Dubbed video: {output_video}")
        return output_video
    
    log("  ❌ Failed to combine, returning original")
    return video_path


# ─── Step 7: Generate Subtitles ────────────────────────────────────
def generate_subtitles(transcript, output_dir):
    """Generate SRT subtitle file."""
    log("📄 Generating subtitles...")
    
    srt_path = os.path.join(output_dir, "subtitles.srt")
    
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(transcript):
            text = seg.get("text_vi", seg["text"])
            start = seg["start"]
            end = seg["end"]
            
            f.write(f"{i+1}\n")
            f.write(f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n")
            f.write(f"{text}\n\n")
    
    log(f"  ✅ Subtitles: {srt_path}")
    return srt_path


def _format_srt_time(seconds):
    """Convert seconds to SRT timestamp format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─── Main Pipeline ─────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Donghua Dubbing Pipeline")
    parser.add_argument("--url", required=True, help="Video URL")
    parser.add_argument("--source-lang", default="Chinese", choices=["Chinese", "Japanese", "Korean"])
    parser.add_argument("--target-lang", default="Vietnamese", choices=["Vietnamese", "English"])
    parser.add_argument("--tts-engine", default=TTS_ENGINE, choices=["omnivoice", "edge"])
    parser.add_argument("--output", default="/tmp/output", help="Output directory")
    args = parser.parse_args()
    
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    
    log(f"🎬 Donghua Dubbing Pipeline")
    log(f"  URL: {args.url}")
    log(f"  {args.source_lang} → {args.target_lang}")
    log(f"  TTS: {args.tts_engine}")
    log(f"  Output: {output_dir}")
    log("")
    
    start_time = time.time()
    
    try:
        # Step 1: Download
        video_path = download_video(args.url, output_dir)
        
        # Step 2: Extract audio
        audio_path = extract_audio(video_path, output_dir)
        
        # Step 3: Transcribe
        transcript = transcribe(audio_path, args.source_lang)
        
        # Save transcript
        with open(os.path.join(output_dir, "transcript.json"), "w") as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
        
        # Step 4: Translate
        transcript = translate_segments(transcript, args.source_lang, args.target_lang)
        
        # Save translated transcript
        with open(os.path.join(output_dir, "translated.json"), "w") as f:
            json.dump(transcript, f, ensure_ascii=False, indent=2)
        
        # Step 5: TTS
        transcript = generate_tts(transcript, output_dir, args.tts_engine)
        
        # Step 6: Combine
        output_video = combine_audio(transcript, video_path, output_dir)
        
        # Step 7: Subtitles
        srt_path = generate_subtitles(transcript, output_dir)
        
        elapsed = time.time() - start_time
        log(f"\n🎉 Done in {elapsed:.0f}s!")
        log(f"  Video: {output_video}")
        log(f"  Subtitles: {srt_path}")
        log(f"  Transcript: {os.path.join(output_dir, 'translated.json')}")
        
        return 0
        
    except Exception as e:
        log(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
