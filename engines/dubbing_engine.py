#!/usr/bin/env python3
"""
Professional Dubbing Engine
============================
Full-featured dubbing pipeline with studio-grade quality.

Pipeline:
1. Download → Extract Audio → Whisper (word-level timestamps)
2. MiMo Translation (context-aware)
3. OmniVoice TTS (voice cloning + emotion)
4. Voice Sync (atempo matching)
5. Audio Processing (normalize, compress, EQ)
6. Video Compositing (subtitle burn, watermark)
7. Final Mix (multi-track, ducking)
"""

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field

# Local imports
from audio_processor import (
    normalize_loudness,
    compress_dynamics,
    process_dubbing_audio,
    crossfade_audio,
    detect_breaths,
)
from tts_engine import ProfessionalTTS, TTSConfig, prepare_reference_audio
from video_compositor import (
    SubtitleBurner,
    AudioMixer,
    VideoEditor,
    QUALITY_PRESETS,
)

import requests

# AGI Brain
try:
    from brain import AGIBrain
    from brain.human_thinker import HumanThinker
    HAS_BRAIN = True
except ImportError:
    HAS_BRAIN = False


# ─── Config ────────────────────────────────────────────────────────
@dataclass
class DubConfig:
    # APIs
    mimo_api_key: str = ""
    mimo_api_base: str = "https://api.xiaomimimo.com/v1"
    mimo_model: str = "mimo-v2.5-pro"
    omnivoice_url: str = ""
    omnivoice_key: str = ""
    
    # Whisper
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"
    
    # TTS
    tts_engine: str = "omnivoice"
    tts_instruct: str = "female, vietnamese accent, natural"
    tts_ref_audio: str = ""
    tts_ref_text: str = ""
    tts_emotion: str = "neutral"
    tts_speed: float = 1.0
    
    # Audio Processing
    normalize_audio: bool = True
    compress_audio: bool = True
    noise_gate: bool = True
    eq_profile: str = "speech"
    target_lufs: float = -16.0
    
    # Video
    video_quality: str = "1080p"
    subtitle_style: str = "professional"
    watermark_path: str = ""
    watermark_text: str = ""
    
    # Sync
    crossfade_ms: int = 50
    
    # Output
    output_dir: str = "/tmp/dub_output"
    
    # AGI Brain
    use_brain: bool = True
    max_retries: int = 2


def log(msg, level="INFO"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}", flush=True)


# ─── Pipeline Steps ────────────────────────────────────────────────

def step_download(url: str, output_dir: str) -> str:
    """Step 1: Download video."""
    log("📥 Step 1: Downloading video...")
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
            log(f"  ✅ Downloaded: {os.path.basename(path)}")
            return path
    
    raise FileNotFoundError("Download failed")


def step_extract_audio(video_path: str, output_dir: str) -> str:
    """Step 2: Extract audio."""
    log("🔊 Step 2: Extracting audio...")
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


def step_transcribe(audio_path: str, source_lang: str, config: DubConfig) -> list[dict]:
    """Step 3: Transcribe with word-level timestamps."""
    log(f"📝 Step 3: Transcribing ({source_lang})...")
    
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
        word_timestamps=True,
    )
    
    result = []
    for i, seg in enumerate(segments):
        result.append({
            "index": i,
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
            "text_vi": "",
            "tts_path": "",
            "tts_duration": 0.0,
            "synced_path": "",
            "speed_factor": 1.0,
        })
        log(f"  [{seg.start:.2f}s-{seg.end:.2f}s] {seg.text.strip()[:50]}")
    
    log(f"  ✅ {len(result)} segments")
    return result


def step_translate(segments: list[dict], source_lang: str, target_lang: str, config: DubConfig, brain_analysis: dict = None) -> list[dict]:
    """Step 4: Translate using MiMo API (brain-enhanced)."""
    log(f"🧠 Step 4: Translating {source_lang} → {target_lang} (brain-enhanced)...")
    
    if not config.mimo_api_key:
        log("  ⚠️ No MIMO_API_KEY, skipping translation")
        return segments
    
    # Batch translate for context
    numbered = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(segments))
    
    # Brain-enhanced translation prompt
    context_info = ""
    strategy_info = ""
    if brain_analysis:
        ctx = brain_analysis.get("context", {})
        strat = brain_analysis.get("strategy", {})
        translation_cfg = strat.get("translation", {})
        context_info = f"Context: Genre={ctx.get('genre', 'unknown')}, Formality={ctx.get('formality', 'casual')}, Audience={ctx.get('target_audience', 'general')}, Humor={ctx.get('humor_type', 'none')}"
        strategy_info = f"Method: {translation_cfg.get('method', 'adaptive')}, Preserve humor: {translation_cfg.get('preserve_humor', True)}"
    
    prompt = f"""Translate the following {source_lang} dialogue to {target_lang} for VIDEO DUBBING.
Keep the EXACT same numbering (1. 2. 3. etc).
Translate naturally — CONVERSATIONAL, EMOTIONAL, CONCISE.
The translations will be spoken aloud by a voice actor.
{context_info}
{strategy_info}

CRITICAL RULES:
- Keep the same emotional intensity as the original
- Use natural Vietnamese that people actually speak
- Preserve cultural references when possible
- Make humor funny in Vietnamese, not just literal
- Keep sentences short for voice acting

{numbered}

Output ONLY the numbered translations:""
    
    payload = {
        "model": config.mimo_model,
        "messages": [
            {"role": "system", "content": f"Professional {source_lang} to {target_lang} translator for video dubbing. Natural, conversational, emotional. Preserve cultural context."},
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
                seg["text_vi"] = translations[i]
            else:
                seg["text_vi"] = seg["text"]
        
        log(f"  ✅ Translated {len(segments)} segments")
        return segments
        
    except Exception as e:
        log(f"  ❌ Translation failed: {e}")
        return segments


def step_tts(segments: list[dict], output_dir: str, config: DubConfig) -> list[dict]:
    """Step 5: Generate TTS with voice cloning."""
    log(f"🗣️ Step 5: Generating TTS ({config.tts_engine})...")
    
    tts_dir = os.path.join(output_dir, "tts")
    os.makedirs(tts_dir, exist_ok=True)
    
    if config.tts_engine == "omnivoice" and config.omnivoice_url:
        tts_config = TTSConfig(
            api_url=config.omnivoice_url,
            api_key=config.omnivoice_key,
            voice_instruct=config.tts_instruct,
            ref_audio=config.tts_ref_audio,
            ref_text=config.tts_ref_text,
            emotion=config.tts_emotion,
            speed=config.tts_speed,
            normalize=config.normalize_audio,
        )
        tts = ProfessionalTTS(tts_config)
        
        for seg in segments:
            text = seg.get("text_vi") or seg["text"]
            if not text:
                continue
            
            tts_path = os.path.join(tts_dir, f"seg_{seg['index']:04d}.wav")
            
            try:
                tts.generate(text, tts_path, emotion=config.tts_emotion)
                seg["tts_path"] = tts_path
                seg["tts_duration"] = tts.get_duration(tts_path)
                log(f"  [{seg['index']}] ✅ {seg['tts_duration']:.2f}s — {text[:30]}...")
            except Exception as e:
                log(f"  [{seg['index']}] ❌ {e}")
    
    else:
        # Fallback to Edge TTS
        _tts_edge_batch(segments, tts_dir, config)
    
    return segments


def _tts_edge_batch(segments: list[dict], tts_dir: str, config: DubConfig):
    """Batch TTS using Edge TTS."""
    import edge_tts
    import asyncio
    
    for seg in segments:
        text = seg.get("text_vi") or seg["text"]
        if not text:
            continue
        
        tts_path = os.path.join(tts_dir, f"seg_{seg['index']:04d}.wav")
        mp3_path = tts_path.replace(".wav", ".mp3")
        
        try:
            async def _gen():
                comm = edge_tts.Communicate(text, "vi-VN-HoaiMyNeural")
                await comm.save(mp3_path)
            
            asyncio.run(_gen())
            
            # Convert to WAV
            subprocess.run(
                f'ffmpeg -i "{mp3_path}" -ar 24000 -ac 1 -y "{tts_path}" 2>/dev/null',
                shell=True, timeout=30,
            )
            if os.path.exists(mp3_path):
                os.remove(mp3_path)
            
            seg["tts_path"] = tts_path
            
            # Get duration
            out = subprocess.run(
                f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{tts_path}"',
                shell=True, capture_output=True, text=True,
            ).stdout.strip()
            seg["tts_duration"] = float(out) if out else 0.0
            
            log(f"  [{seg['index']}] ✅ {seg['tts_duration']:.2f}s — {text[:30]}...")
            
        except Exception as e:
            log(f"  [{seg['index']}] ❌ {e}")


def step_sync(segments: list[dict], output_dir: str, config: DubConfig) -> list[dict]:
    """Step 6: Sync TTS to match original timing."""
    log("🎯 Step 6: Syncing voice to video timing...")
    
    sync_dir = os.path.join(output_dir, "synced")
    os.makedirs(sync_dir, exist_ok=True)
    
    tts = ProfessionalTTS(TTSConfig()) if config.omnivoice_url else None
    
    for seg in segments:
        if not seg.get("tts_path") or not os.path.exists(seg["tts_path"]):
            continue
        
        target_duration = seg["end"] - seg["start"]
        original_duration = seg["tts_duration"]
        
        if original_duration <= 0 or target_duration <= 0:
            continue
        
        synced_path = os.path.join(sync_dir, f"seg_{seg['index']:04d}.wav")
        
        if tts:
            tts.adjust_speed(seg["tts_path"], synced_path, target_duration)
        else:
            # Direct ffmpeg atempo
            speed_factor = original_duration / target_duration
            speed_factor = max(0.5, min(2.0, speed_factor))
            
            filters = []
            remaining = speed_factor
            while remaining > 2.0:
                filters.append("atempo=2.0")
                remaining /= 2.0
            while remaining < 0.5:
                filters.append("atempo=0.5")
                remaining /= 0.5
            filters.append(f"atempo={remaining:.4f}")
            
            cmd = (
                f'ffmpeg -i "{seg["tts_path"]}" '
                f'-filter:a "{",".join(filters)}" '
                f'-y "{synced_path}" 2>/dev/null'
            )
            subprocess.run(cmd, shell=True, timeout=60)
        
        seg["synced_path"] = synced_path
        
        # Get final duration
        out = subprocess.run(
            f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{synced_path}"',
            shell=True, capture_output=True, text=True,
        ).stdout.strip()
        final_duration = float(out) if out else 0.0
        
        speed_factor = original_duration / target_duration if target_duration > 0 else 1.0
        seg["speed_factor"] = speed_factor
        
        log(f"  [{seg['index']}] {original_duration:.2f}s → {final_duration:.2f}s (target: {target_duration:.2f}s, speed: {speed_factor:.2f}x)")
    
    return segments


def step_audio_process(segments: list[dict], output_dir: str, config: DubConfig) -> list[dict]:
    """Step 7: Professional audio processing."""
    log("🎚️ Step 7: Processing audio...")
    
    processed_dir = os.path.join(output_dir, "processed")
    os.makedirs(processed_dir, exist_ok=True)
    
    for seg in segments:
        if not seg.get("synced_path") or not os.path.exists(seg["synced_path"]):
            continue
        
        processed_path = os.path.join(processed_dir, f"seg_{seg['index']:04d}.wav")
        
        try:
            process_dubbing_audio(
                seg["synced_path"],
                processed_path,
                target_lufs=config.target_lufs,
                compress=config.compress_audio,
                noise_gate=config.noise_gate,
                eq_profile=config.eq_profile,
            )
            seg["processed_path"] = processed_path
            log(f"  [{seg['index']}] ✅ Processed")
        except Exception as e:
            log(f"  [{seg['index']}] ⚠️ Processing failed: {e}")
            seg["processed_path"] = seg["synced_path"]
    
    return segments


def step_combine(segments: list[dict], video_path: str, output_dir: str, config: DubConfig) -> str:
    """Step 8: Combine into final video."""
    log("🎬 Step 8: Combining final video...")
    
    # Build audio track from segments
    valid_segments = [s for s in segments if s.get("processed_path") and os.path.exists(s["processed_path"])]
    
    if not valid_segments:
        log("  ⚠️ No processed segments, using original")
        return video_path
    
    # Create combined TTS audio with precise timing
    tts_audio = os.path.join(output_dir, "tts_combined.wav")
    
    inputs = ["-i", video_path]
    filter_parts = []
    
    for i, seg in enumerate(valid_segments):
        inputs.extend(["-i", seg["processed_path"]])
        delay_ms = int(seg["start"] * 1000)
        filter_parts.append(
            f"[{i+1}:a]adelay={delay_ms}|{delay_ms},aresample=48000[a{i}]"
        )
    
    mix_inputs = "".join(f"[a{i}]" for i in range(len(valid_segments)))
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(valid_segments)}:duration=longest:normalize=0[out_tts]"
    )
    filter_parts.append(f"[0:a]volume=0.12[bg]")
    filter_parts.append(f"[bg][out_tts]amix=inputs=2:duration=first[out]")
    
    filter_complex = ";".join(filter_parts)
    
    output_video = os.path.join(output_dir, "dubbed_raw.mp4")
    
    cmd = (
        f'ffmpeg {" ".join(inputs)} '
        f'-filter_complex "{filter_complex}" '
        f'-map 0:v -map "[out]" '
        f'-c:v copy -c:a aac -b:a 192k '
        f'-shortest '
        f'-y "{output_video}" 2>/dev/null'
    )
    subprocess.run(cmd, shell=True, timeout=600)
    
    if not os.path.exists(output_video):
        log("  ❌ Combine failed")
        return video_path
    
    log(f"  ✅ Raw dubbed video created")
    return output_video


def step_subtitles(segments: list[dict], video_path: str, output_dir: str, config: DubConfig) -> str:
    """Step 9: Burn subtitles."""
    log("📄 Step 9: Burning subtitles...")
    
    # Generate SRT
    srt_path = os.path.join(output_dir, "subtitles.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        for i, seg in enumerate(segments):
            text = seg.get("text_vi") or seg["text"]
            if not text:
                continue
            start = _format_srt(seg["start"])
            end = _format_srt(seg["end"])
            f.write(f"{i+1}\n{start} --> {end}\n{text}\n\n")
    
    # Burn into video
    output_video = os.path.join(output_dir, "dubbed.mp4")
    
    try:
        SubtitleBurner.burn(video_path, srt_path, output_video, config.subtitle_style)
        log(f"  ✅ Subtitles burned: {os.path.basename(output_video)}")
    except Exception as e:
        log(f"  ⚠️ Subtitle burn failed: {e}, using raw video")
        import shutil
        shutil.copy2(video_path, output_video)
    
    return output_video


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
    config: DubConfig | None = None,
) -> dict:
    """Run the full professional dubbing pipeline."""
    if config is None:
        config = DubConfig()
    
    output_dir = config.output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    lang_codes = {"Chinese": "zh", "Japanese": "ja", "Korean": "ko", "English": "en"}
    source_code = lang_codes.get(source_lang, "zh")
    
    start_time = time.time()
    brain_analysis = {}
    
    # Initialize AGI Brain
    brain = None
    if config.use_brain and HAS_BRAIN:
        try:
            brain = AGIBrain(config.mimo_api_key, config.mimo_api_base, config.mimo_model)
            log("🧠 AGI Brain initialized")
        except Exception as e:
            log(f"  ⚠️ Brain init failed: {e}")
    
    try:
        # Step 1: Download
        if url:
            video_path = step_download(url, output_dir)
        
        if not video_path or not os.path.exists(video_path):
            return {"success": False, "error": "No video provided"}
        
        # 🧠 Brain Step: Scene understanding (see the video)
        scene_data = {}
        if brain:
            try:
                log("👁️ Analyzing video scenes...")
                scene_data = brain.understand_scene(video_path)
                log(f"👁️ Scenes: {scene_data.get('keyframe_count', 0)} keyframes, mood={scene_data.get('visual_mood', {}).get('primary', '?')}")
            except Exception as e:
                log(f"  ⚠️ Scene analysis failed: {e}")
        
        # 🧠 Brain Step: Get adaptive strategy from past learning
        adaptive_strategy = {}
        if brain:
            try:
                adaptive_strategy = brain.get_adaptive_strategy(
                    scene_data.get("visual_mood", {}).get("primary", "unknown"),
                    source_lang, target_lang
                )
                log(f"🧠 Adaptive strategy confidence: {adaptive_strategy.get('confidence', 0):.0%}")
            except:
                pass
        
        # Step 2: Extract audio
        audio_path = step_extract_audio(video_path, output_dir)
        
        # Step 3: Transcribe
        segments = step_transcribe(audio_path, source_code, config)
        _save_json(segments, os.path.join(output_dir, "segments.json"))
        
        # 🧠 Brain Step: Deep analysis
        if brain:
            try:
                brain_analysis = brain.analyze(segments, source_lang, target_lang)
                genre = brain_analysis.get("context", {}).get("genre", "?")
                method = brain_analysis.get("strategy", {}).get("translation", {}).get("method", "?")
                log(f"🧠 Brain: genre={genre}, translation={method}")
                _save_json(brain_analysis, os.path.join(output_dir, "brain_analysis.json"))
            except Exception as e:
                log(f"  ⚠️ Brain analysis failed: {e}")
        
        # Step 4: Translate (brain-enhanced)
        segments = step_translate(segments, source_lang, target_lang, config, brain_analysis)
        
        # 🧠 Brain Step: Post-translation refinement
        if brain:
            try:
                segments = brain.post_translate(segments, brain_analysis)
                log("🧠 Brain post-translation refinement done")
            except Exception as e:
                log(f"  ⚠️ Brain refinement failed: {e}")
        
        # 🧠 Brain Step: Build emotional arc for consistency
        emotional_arc = {}
        if brain:
            try:
                emotional_arc = brain.build_emotional_arc(segments, brain_analysis.get("context", {}))
                segments = brain.apply_emotional_arc(segments, emotional_arc)
                log(f"🎭 Emotional arc: {emotional_arc.get('dominant_mood', '?')}, range={emotional_arc.get('emotional_range', [])}")
                _save_json(emotional_arc, os.path.join(output_dir, "emotional_arc.json"))
            except Exception as e:
                log(f"  ⚠️ Emotional continuity failed: {e}")
        
        _save_json(segments, os.path.join(output_dir, "translated.json"))
        
        # Step 5: TTS
        segments = step_tts(segments, output_dir, config)
        
        # Step 6: Voice Sync
        segments = step_sync(segments, output_dir, config)
        
        # Step 7: Audio Processing
        if config.normalize_audio or config.compress_audio:
            segments = step_audio_process(segments, output_dir, config)
        
        # Step 8: Combine
        dubbed_video = step_combine(segments, video_path, output_dir, config)
        
        # Step 9: Subtitles
        final_video = step_subtitles(segments, dubbed_video, output_dir, config)
        
        elapsed = time.time() - start_time
        # 🧠 Brain Step: Quality assessment
        quality_report = {}
        if brain:
            try:
                quality_report = brain.assess_and_retry(segments, output_dir, brain_analysis)
                score = quality_report.get("overall_score", 0)
                log(f"🧠 Quality score: {score}/100")
                
                # 🧠 Brain Step: Adaptive learning — record this result
                strategy_used = brain_analysis.get("strategy", {})
                strategy_used["genre"] = brain_analysis.get("context", {}).get("genre", "unknown")
                brain.record_job_result({
                    "quality_score": score,
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                }, strategy_used)
                log(f"🧠 Adaptive learning: recorded result for future optimization")
            except Exception as e:
                log(f"  ⚠️ Quality assessment failed: {e}")
        
        log(f"\n🎉 Done in {elapsed:.0f}s!")
        log(f"  📹 Video: {final_video}")
        log(f"  📄 Subtitles: {os.path.join(output_dir, 'subtitles.srt')}")
        if quality_report:
            log(f"  🧠 Quality: {quality_report.get('overall_score', 0)}/100")
        
        return {
            "success": True,
            "output_video": final_video,
            "output_srt": os.path.join(output_dir, "subtitles.srt"),
            "segments": len(segments),
            "processing_time": elapsed,
            "quality_score": quality_report.get("overall_score", 0),
            "brain_analysis": brain_analysis,
        }
        
    except Exception as e:
        log(f"❌ Pipeline failed: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def _save_json(data, path):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── CLI ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Professional Dubbing Engine")
    parser.add_argument("--url", default="")
    parser.add_argument("--video", default="")
    parser.add_argument("--source-lang", default="Chinese")
    parser.add_argument("--target-lang", default="Vietnamese")
    parser.add_argument("--tts-engine", default="omnivoice")
    parser.add_argument("--omnivoice-url", default="")
    parser.add_argument("--omnivoice-key", default="")
    parser.add_argument("--mimo-key", default="")
    parser.add_argument("--voice-instruct", default="female, vietnamese accent, natural")
    parser.add_argument("--ref-audio", default="")
    parser.add_argument("--emotion", default="neutral")
    parser.add_argument("--subtitle-style", default="professional")
    parser.add_argument("--output", default="/tmp/dub_output")
    args = parser.parse_args()
    
    config = DubConfig(
        tts_engine=args.tts_engine,
        omnivoice_url=args.omnivoice_url or os.getenv("OMNIVOICE_API_URL", ""),
        omnivoice_key=args.omnivoice_key or os.getenv("OMNIVOICE_API_KEY", ""),
        mimo_api_key=args.mimo_key or os.getenv("MIMO_API_KEY", ""),
        tts_instruct=args.voice_instruct,
        tts_ref_audio=args.ref_audio,
        tts_emotion=args.emotion,
        subtitle_style=args.subtitle_style,
        output_dir=args.output,
    )
    
    result = run_pipeline(
        url=args.url,
        video_path=args.video,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
        config=config,
    )
    
    sys.exit(0 if result["success"] else 1)
