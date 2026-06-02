#!/usr/bin/env python3
"""
Pipeline Executor — Pure Mechanical Execution
==============================================
NO brain. NO intelligence. Just does what it's told.

Takes a decisions.json (created by Hermes brain) and executes:
1. Download video
2. Extract audio
3. Transcribe (Whisper)
4. [DECISIONS APPLIED: translations, emotions, voice params]
5. TTS generation
6. Voice sync
7. Audio processing
8. Video combine
9. Subtitle burn

Usage:
  python3 execute.py --decisions decisions.json --video-url "https://..." --output /tmp/output
  python3 execute.py --decisions decisions.json --video-path /path/to/video.mp4 --output /tmp/output
"""

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


# ═══════════════════════════════════════════════════════════════════
# MECHANICAL STEPS — No thinking, just doing
# ═══════════════════════════════════════════════════════════════════

def download_video(url: str, output_dir: str) -> str:
    log("Download video...")
    output_path = os.path.join(output_dir, "source")
    cmd = (
        f'yt-dlp -f "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best" '
        f'--merge-output-format mp4 --no-watermark '
        f'-o "{output_path}.%(ext)s" "{url}" 2>&1'
    )
    subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=600)
    for ext in ["mp4", "webm", "mkv"]:
        path = f"{output_path}.{ext}"
        if os.path.exists(path):
            log(f"  OK: {os.path.basename(path)}")
            return path
    raise FileNotFoundError("Download failed")


def extract_audio(video_path: str, output_dir: str) -> str:
    log("Extract audio...")
    audio_path = os.path.join(output_dir, "audio.wav")
    cmd = f'ffmpeg -i "{video_path}" -vn -acodec pcm_s16le -ar 16000 -ac 1 -y "{audio_path}" 2>/dev/null'
    subprocess.run(cmd, shell=True, timeout=120)
    if os.path.exists(audio_path):
        log(f"  OK: {os.path.basename(audio_path)}")
        return audio_path
    raise FileNotFoundError("Audio extraction failed")


def transcribe(audio_path: str, source_lang: str) -> list[dict]:
    log(f"Transcribe ({source_lang})...")
    from faster_whisper import WhisperModel
    
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = WhisperModel("large-v3", device=device, compute_type="float16" if device == "cuda" else "int8")
    
    segments, info = model.transcribe(audio_path, language=source_lang, beam_size=5, vad_filter=True, word_timestamps=True)
    
    result = []
    for i, seg in enumerate(segments):
        result.append({
            "index": i, "start": seg.start, "end": seg.end,
            "text": seg.text.strip(),
        })
    
    log(f"  OK: {len(result)} segments")
    return result


def generate_tts(segments: list[dict], output_dir: str, decisions: dict) -> list[dict]:
    log("Generate TTS...")
    tts_dir = os.path.join(output_dir, "tts")
    os.makedirs(tts_dir, exist_ok=True)
    
    tts_config = decisions.get("tts", {})
    omnivoice_url = tts_config.get("omnivoice_url", os.getenv("OMNIVOICE_API_URL", ""))
    voice_instruct = tts_config.get("voice_instruct", "female, vietnamese accent, natural")
    emotion_default = tts_config.get("emotion", "neutral")
    
    # Try OmniVoice, fallback to Edge TTS
    tts_engine = None
    if omnivoice_url:
        try:
            from engines.tts_engine import ProfessionalTTS, TTSConfig
            tts_config_obj = TTSConfig(
                api_url=omnivoice_url,
                voice_instruct=voice_instruct,
                emotion=emotion_default,
            )
            tts_engine = ProfessionalTTS(tts_config_obj)
        except:
            pass
    
    for seg in segments:
        text = seg.get("text_vi") or seg.get("text", "")
        if not text:
            continue
        
        tts_path = os.path.join(tts_dir, f"seg_{seg['index']:04d}.wav")
        
        # Get per-segment emotion from decisions
        emotion = seg.get("emotion", emotion_default)
        
        if tts_engine:
            try:
                tts_engine.generate(text, tts_path, emotion=emotion)
                seg["tts_path"] = tts_path
                seg["tts_duration"] = tts_engine.get_duration(tts_path)
            except Exception as e:
                log(f"  [{seg['index']}] OmniVoice failed: {e}, using Edge TTS")
                _tts_edge(text, tts_path, seg)
        else:
            _tts_edge(text, tts_path, seg)
        
        if seg.get("tts_path"):
            log(f"  [{seg['index']}] OK: {seg.get('tts_duration', 0):.2f}s")
    
    return segments


def _tts_edge(text: str, tts_path: str, seg: dict):
    """Edge TTS fallback."""
    import asyncio
    import edge_tts
    
    mp3_path = tts_path.replace(".wav", ".mp3")
    
    async def _gen():
        comm = edge_tts.Communicate(text, "vi-VN-HoaiMyNeural")
        await comm.save(mp3_path)
    
    asyncio.run(_gen())
    subprocess.run(f'ffmpeg -i "{mp3_path}" -ar 24000 -ac 1 -y "{tts_path}" 2>/dev/null', shell=True, timeout=30)
    if os.path.exists(mp3_path):
        os.remove(mp3_path)
    
    seg["tts_path"] = tts_path
    out = subprocess.run(
        f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{tts_path}"',
        shell=True, capture_output=True, text=True,
    ).stdout.strip()
    seg["tts_duration"] = float(out) if out else 0.0


def sync_voice(segments: list[dict], output_dir: str) -> list[dict]:
    log("Sync voice to timing...")
    sync_dir = os.path.join(output_dir, "synced")
    os.makedirs(sync_dir, exist_ok=True)
    
    for seg in segments:
        if not seg.get("tts_path") or not os.path.exists(seg["tts_path"]):
            continue
        
        target = seg["end"] - seg["start"]
        if target <= 0:
            continue
        
        synced_path = os.path.join(sync_dir, f"seg_{seg['index']:04d}.wav")
        speed = seg["tts_duration"] / target if target > 0 else 1.0
        speed = max(0.5, min(2.0, speed))
        
        # Build atempo chain
        filters = []
        remaining = speed
        while remaining > 2.0:
            filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            filters.append("atempo=0.5")
            remaining /= 0.5
        filters.append(f"atempo={remaining:.4f}")
        
        cmd = f'ffmpeg -i "{seg["tts_path"]}" -filter:a "{",".join(filters)}" -y "{synced_path}" 2>/dev/null'
        subprocess.run(cmd, shell=True, timeout=60)
        seg["synced_path"] = synced_path
        seg["speed_factor"] = speed
    
    return segments


def process_audio(segments: list[dict], output_dir: str) -> list[dict]:
    log("Process audio...")
    processed_dir = os.path.join(output_dir, "processed")
    os.makedirs(processed_dir, exist_ok=True)
    
    for seg in segments:
        src = seg.get("synced_path")
        if not src or not os.path.exists(src):
            continue
        
        dst = os.path.join(processed_dir, f"seg_{seg['index']:04d}.wav")
        
        # Normalize + compress in one pass
        cmd = (
            f'ffmpeg -i "{src}" '
            f'-af "acompressor=threshold=-20dB:ratio=4:attack=5:release=50,'
            f'loudnorm=I=-16:TP=-1.5:LRA=11" '
            f'-ar 48000 -ac 1 -y "{dst}" 2>/dev/null'
        )
        subprocess.run(cmd, shell=True, timeout=30)
        seg["processed_path"] = dst
    
    return segments


def combine_video(segments: list[dict], video_path: str, output_dir: str) -> str:
    log("Combine video...")
    valid = [s for s in segments if s.get("processed_path") and os.path.exists(s["processed_path"])]
    if not valid:
        log("  No processed segments")
        return video_path
    
    inputs = ["-i", video_path]
    filter_parts = []
    
    for i, seg in enumerate(valid):
        inputs.extend(["-i", seg["processed_path"]])
        delay_ms = int(seg["start"] * 1000)
        filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms},aresample=48000[a{i}]")
    
    mix = "".join(f"[a{i}]" for i in range(len(valid)))
    filter_parts.append(f"{mix}amix=inputs={len(valid)}:duration=longest:normalize=0[out_tts]")
    filter_parts.append("[0:a]volume=0.12[bg]")
    filter_parts.append("[bg][out_tts]amix=inputs=2:duration=first[out]")
    
    output = os.path.join(output_dir, "dubbed_raw.mp4")
    cmd = f'ffmpeg {" ".join(inputs)} -filter_complex "{";".join(filter_parts)}" -map 0:v -map "[out]" -c:v copy -c:a aac -b:a 192k -shortest -y "{output}" 2>/dev/null'
    subprocess.run(cmd, shell=True, timeout=600)
    
    return output if os.path.exists(output) else video_path


def burn_subtitles(segments: list[dict], video_path: str, output_dir: str, style: str = "professional") -> str:
    log("Burn subtitles...")
    srt_path = os.path.join(output_dir, "subtitles.srt")
    
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments):
            text = seg.get("text_vi") or seg.get("text", "")
            if not text:
                continue
            start = _srt_time(seg["start"])
            end = _srt_time(seg["end"])
            f.write(f"{i+1}\n{start} --> {end}\n{text}\n\n")
    
    output = os.path.join(output_dir, "dubbed.mp4")
    cmd = ["ffmpeg", "-i", video_path, "-vf", f"subtitles={srt_path}", "-c:v", "libx264", "-crf", "18", "-c:a", "copy", "-y", output]
    subprocess.run(cmd, shell=True, timeout=300)
    subprocess.run(cmd, timeout=300)
    if os.path.exists(output):
        return output
    # Fallback: copy without subtitles
    import shutil
    shutil.copy2(video_path, output)
    return output


def _srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ═══════════════════════════════════════════════════════════════════
# MAIN: Execute decisions from Hermes brain
# ═══════════════════════════════════════════════════════════════════

def execute(decisions: dict, video_url: str = "", video_path: str = "", output_dir: str = "/tmp/dub_output") -> dict:
    """
    Execute a dubbing pipeline with pre-made decisions from Hermes.
    
    decisions format:
    {
      "translations": [
        {"index": 0, "text_vi": "...", "emotion": "happy", "voice": "vi-female-natural"},
        ...
      ],
      "tts": {
        "omnivoice_url": "...",
        "voice_instruct": "...",
        "emotion": "neutral"
      },
      "subtitle_style": "professional",
      "audio": {
        "target_lufs": -16,
        "compress": true
      }
    }
    """
    os.makedirs(output_dir, exist_ok=True)
    start = time.time()
    
    try:
        # 1. Download
        if video_url:
            video_path = download_video(video_url, output_dir)
        if not video_path or not os.path.exists(video_path):
            return {"success": False, "error": "No video"}
        
        # 2. Extract audio
        audio_path = extract_audio(video_path, output_dir)
        
        # 3. Transcribe
        source_lang = decisions.get("source_lang", "zh")
        segments = transcribe(audio_path, source_lang)
        
        # 4. Apply Hermes decisions (translations + emotions)
        translations = decisions.get("translations", [])
        for seg in segments:
            for t in translations:
                if t.get("index") == seg["index"]:
                    seg["text_vi"] = t.get("text_vi", "")
                    seg["emotion"] = t.get("emotion", "neutral")
                    break
        
        # Save segments for reference
        with open(os.path.join(output_dir, "segments.json"), "w") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        
        # 5. TTS
        segments = generate_tts(segments, output_dir, decisions)
        
        # 6. Sync
        segments = sync_voice(segments, output_dir)
        
        # 7. Process
        segments = process_audio(segments, output_dir)
        
        # 8. Combine
        dubbed = combine_video(segments, video_path, output_dir)
        
        # 9. Subtitles
        style = decisions.get("subtitle_style", "professional")
        final = burn_subtitles(segments, dubbed, output_dir, style)
        
        elapsed = time.time() - start
        log(f"Done in {elapsed:.0f}s!")
        
        return {
            "success": True,
            "output_video": final,
            "output_srt": os.path.join(output_dir, "subtitles.srt"),
            "segments": len(segments),
            "processing_time": elapsed,
        }
        
    except Exception as e:
        log(f"Failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", required=True, help="Decisions JSON from Hermes brain")
    parser.add_argument("--video-url", default="")
    parser.add_argument("--video-path", default="")
    parser.add_argument("--output", default="/tmp/dub_output")
    args = parser.parse_args()
    
    with open(args.decisions) as f:
        decisions = json.load(f)
    
    result = execute(decisions, args.video_url, args.video_path, args.output)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["success"] else 1)
