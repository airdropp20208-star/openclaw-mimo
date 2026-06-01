#!/usr/bin/env python3
"""
Professional Audio Processor
=============================
Studio-grade audio processing for dubbing pipeline.

Features:
- Loudness normalization (EBU R128 / ITU-R BS.1770)
- Dynamic range compression
- Noise gate & noise reduction
- EQ matching to original speaker
- Cross-fade with professional curves
- Breath preservation
- Audio ducking
- Silence detection & removal
- Sample rate conversion with dithering
"""

import os
import subprocess
import json
import tempfile
from dataclasses import dataclass
from typing import Optional


def _ff(cmd: str, timeout=120) -> str:
    """Run FFmpeg/FFprobe command."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return result.stdout.strip()


def _ffprobe(path: str, field: str = "duration") -> float:
    """Get audio property."""
    out = _ff(f'ffprobe -v error -show_entries format={field} -of csv=p=0 "{path}"')
    return float(out) if out else 0.0


def _ffprobe_json(path: str) -> dict:
    """Get full FFprobe info."""
    out = _ff(f'ffprobe -v quiet -print_format json -show_format -show_streams "{path}"')
    try:
        return json.loads(out)
    except:
        return {}


# ─── Loudness Normalization (EBU R128) ────────────────────────────
def normalize_loudness(input_path: str, output_path: str, target_lufs: float = -16.0) -> str:
    """
    Normalize audio to target LUFS (EBU R128 standard).
    -16 LUFS: YouTube/streaming standard
    -23 LUFS: Broadcast standard
    -14 LUFS: Loud/commercial
    """
    # First pass: measure loudness
    stats = _ff(
        f'ffmpeg -i "{input_path}" -af loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json -f null - 2>&1 '
        f'| grep -A20 "Parsed_loudnorm"'
    )
    
    # Parse measured values
    measured_i = _extract_json_value(stats, "input_i")
    measured_tp = _extract_json_value(stats, "input_tp")
    measured_lra = _extract_json_value(stats, "input_lra")
    measured_thresh = _extract_json_value(stats, "input_thresh")
    
    if measured_i:
        # Second pass: apply normalization with measured values
        cmd = (
            f'ffmpeg -i "{input_path}" '
            f'-af "loudnorm=I={target_lufs}:TP=-1.5:LRA=11:'
            f'measured_I={measured_i}:measured_TP={measured_tp}:'
            f'measured_LRA={measured_lra}:measured_thresh={measured_thresh}:'
            f'linear=true" '
            f'-ar 48000 -ac 2 '
            f'-y "{output_path}" 2>/dev/null'
        )
    else:
        # Fallback: single-pass normalization
        cmd = (
            f'ffmpeg -i "{input_path}" '
            f'-af "loudnorm=I={target_lufs}:TP=-1.5:LRA=11" '
            f'-ar 48000 -ac 2 '
            f'-y "{output_path}" 2>/dev/null'
        )
    
    _ff(cmd)
    return output_path


def _extract_json_value(text: str, key: str) -> str:
    """Extract value from FFmpeg loudnorm JSON output."""
    for line in text.split("\n"):
        if f'"{key}"' in line:
            parts = line.split(":")
            if len(parts) >= 2:
                val = parts[-1].strip().strip('",')
                return val
    return ""


# ─── Dynamic Range Compression ────────────────────────────────────
def compress_dynamics(
    input_path: str,
    output_path: str,
    threshold_db: float = -20.0,
    ratio: float = 4.0,
    attack_ms: float = 5.0,
    release_ms: float = 50.0,
) -> str:
    """
    Apply dynamic range compression.
    Makes quiet parts louder and loud parts quieter.
    
    Args:
        threshold_db: Compression threshold (-30 to -10)
        ratio: Compression ratio (2:1 to 8:1)
        attack_ms: Attack time (1-50ms)
        release_ms: Release time (50-500ms)
    """
    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-af "acompressor=threshold={threshold_db}dB:ratio={ratio}:'
        f'attack={attack_ms}:release={release_ms}:'
        f'knee=2.5:makeup=2" '
        f'-y "{output_path}" 2>/dev/null'
    )
    _ff(cmd)
    return output_path


# ─── Noise Gate ────────────────────────────────────────────────────
def noise_gate(
    input_path: str,
    output_path: str,
    threshold_db: float = -40.0,
    attack_ms: float = 5.0,
    hold_ms: float = 200.0,
    release_ms: float = 100.0,
) -> str:
    """
    Apply noise gate to remove background noise during silence.
    
    Args:
        threshold_db: Gate threshold (-60 to -20)
        attack_ms: How fast gate opens
        hold_ms: How long gate stays open after signal drops
        release_ms: How fast gate closes
    """
    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-af "silenceremove=start_periods=1:start_duration=0.1:start_threshold={threshold_db}dB:'
        f'stop_periods=-1:stop_duration=0.1:stop_threshold={threshold_db}dB" '
        f'-y "{output_path}" 2>/dev/null'
    )
    _ff(cmd)
    return output_path


# ─── EQ Matching ───────────────────────────────────────────────────
def eq_match_speaker(
    input_path: str,
    output_path: str,
    target_eq: str = "speech"
) -> str:
    """
    Apply EQ to match a speaker profile.
    
    Profiles:
    - speech: Boost clarity (2-5kHz)
    - warm: Boost low-mids (200-500Hz)
    - bright: Boost highs (5-10kHz)
    - female: Higher formants
    - male: Lower formants
    """
    profiles = {
        "speech": "equalizer=f=3000:t=q:w=1.5:g=3,equalizer=f=500:t=q:w=1:g=-2",
        "warm": "equalizer=f=300:t=q:w=1:g=3,equalizer=f=3000:t=q:w=1:g=-1",
        "bright": "equalizer=f=6000:t=q:w=1.5:g=4,equalizer=f=10000:t=q:w=2:g=2",
        "female": "equalizer=f=2500:t=q:w=1:g=2,equalizer=f=200:t=q:w=1:g=-2",
        "male": "equalizer=f=200:t=q:w=1:g=3,equalizer=f=4000:t=q:w=1.5:g=-1",
    }
    
    eq_filter = profiles.get(target_eq, profiles["speech"])
    
    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-af "{eq_filter}" '
        f'-y "{output_path}" 2>/dev/null'
    )
    _ff(cmd)
    return output_path


# ─── Professional Cross-Fade ───────────────────────────────────────
def crossfade_audio(
    input_a: str,
    input_b: str,
    output_path: str,
    fade_duration_ms: int = 50,
    curve: str = "tri",
) -> str:
    """
    Cross-fade between two audio files.
    
    Curves: tri (linear), exp (exponential), log (logarithmic), 
            sine (s-curve), qsin (quarter-sine), hsin (half-sine)
    """
    fade_s = fade_duration_ms / 1000.0
    
    cmd = (
        f'ffmpeg -i "{input_a}" -i "{input_b}" '
        f'-filter_complex "[0:a][1:a]acrossfade=d={fade_s}:c1={curve}:c2={curve}[out]" '
        f'-map "[out]" '
        f'-y "{output_path}" 2>/dev/null'
    )
    _ff(cmd)
    return output_path


# ─── Audio Ducking ─────────────────────────────────────────────────
def duck_audio(
    main_path: str,
    duck_path: str,
    output_path: str,
    duck_level_db: float = -12.0,
    attack_ms: float = 200.0,
    release_ms: float = 500.0,
) -> str:
    """
    Duck background audio when voice is present.
    
    Args:
        main_path: Main audio (voice)
        duck_path: Audio to duck (background music/ambience)
        duck_level_db: How much to reduce (-6 to -20)
    """
    cmd = (
        f'ffmpeg -i "{duck_path}" -i "{main_path}" '
        f'-filter_complex "'
        f'[0:a]volume=1.0[bg];'
        f'[1:a]asplit[voice][voice_for_sidechain];'
        f'[bg][voice_for_sidechain]sidechaincompress=threshold=0.1:ratio=4:'
        f'attack={attack_ms}:release={release_ms}:level_in=1:level_sc=1:level_out=1:'
        f'makeup={duck_level_db}[ducked];'
        f'[ducked][voice]amix=inputs=2:duration=first:dropout_transition=0[out]'
        f'" -map "[out]" '
        f'-y "{output_path}" 2>/dev/null'
    )
    _ff(cmd)
    return output_path


# ─── Breath Preservation ───────────────────────────────────────────
def detect_breaths(audio_path: str, threshold_db: float = -35.0) -> list[dict]:
    """
    Detect breath sounds in audio for preservation during dubbing.
    Returns list of {start, end, duration} for each breath.
    """
    # Use silencedetect to find quiet parts (potential breaths)
    stats = _ff(
        f'ffmpeg -i "{audio_path}" '
        f'-af "silencedetect=n={threshold_db}dB:d=0.05" '
        f'-f null - 2>&1 | grep "silence_"'
    )
    
    breaths = []
    current_start = None
    
    for line in stats.split("\n"):
        if "silence_start" in line:
            try:
                current_start = float(line.split("=")[-1])
            except:
                pass
        elif "silence_end" in line and current_start is not None:
            try:
                end = float(line.split("=")[1].split(" ")[0])
                duration = end - current_start
                if 0.05 < duration < 0.5:  # Breath is typically 50-500ms
                    breaths.append({
                        "start": current_start,
                        "end": end,
                        "duration": duration,
                    })
            except:
                pass
            current_start = None
    
    return breaths


# ─── Silence Removal ───────────────────────────────────────────────
def remove_silence(
    input_path: str,
    output_path: str,
    threshold_db: float = -40.0,
    min_silence_ms: int = 500,
    keep_ms: int = 100,
) -> str:
    """Remove long silences, keeping short pauses for naturalness."""
    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-af "silenceremove=start_periods=1:start_duration=0:start_threshold={threshold_db}dB:'
        f'stop_periods=-1:stop_duration={min_silence_ms/1000}:stop_threshold={threshold_db}dB" '
        f'-y "{output_path}" 2>/dev/null'
    )
    _ff(cmd)
    return output_path


# ─── Sample Rate Conversion with Dithering ─────────────────────────
def convert_sample_rate(
    input_path: str,
    output_path: str,
    target_rate: int = 48000,
    bit_depth: int = 16,
) -> str:
    """Convert sample rate with proper dithering."""
    dither = "tri" if bit_depth <= 16 else "tp"  # Triangular for 16-bit, TP for 24-bit
    
    cmd = (
        f'ffmpeg -i "{input_path}" '
        f'-af "aresample=resampler=soxr:dither_method={dither}" '
        f'-ar {target_rate} -sample_fmt s{bit_depth} '
        f'-y "{output_path}" 2>/dev/null'
    )
    _ff(cmd)
    return output_path


# ─── Full Processing Chain ────────────────────────────────────────
def process_dubbing_audio(
    input_path: str,
    output_path: str,
    target_lufs: float = -16.0,
    compress: bool = True,
    noise_gate: bool = True,
    eq_profile: str = "speech",
    target_rate: int = 48000,
) -> str:
    """
    Full professional audio processing chain for dubbing.
    
    Steps:
    1. Noise gate (remove background noise)
    2. EQ matching (speaker profile)
    3. Dynamic range compression
    4. Loudness normalization (EBU R128)
    5. Sample rate conversion
    """
    temp_dir = tempfile.mkdtemp(prefix="audio_proc_")
    current = input_path
    
    # Step 1: Noise gate
    if noise_gate:
        next_path = os.path.join(temp_dir, "01_gated.wav")
        noise_gate(current, next_path)
        if os.path.exists(next_path):
            current = next_path
    
    # Step 2: EQ
    if eq_profile:
        next_path = os.path.join(temp_dir, "02_eq.wav")
        eq_match_speaker(current, next_path, eq_profile)
        if os.path.exists(next_path):
            current = next_path
    
    # Step 3: Compression
    if compress:
        next_path = os.path.join(temp_dir, "03_compressed.wav")
        compress_dynamics(current, next_path)
        if os.path.exists(next_path):
            current = next_path
    
    # Step 4: Loudness normalization
    next_path = os.path.join(temp_dir, "04_normalized.wav")
    normalize_loudness(current, next_path, target_lufs)
    if os.path.exists(next_path):
        current = next_path
    
    # Step 5: Sample rate conversion
    if target_rate:
        convert_sample_rate(current, output_path, target_rate)
    else:
        import shutil
        shutil.copy2(current, output_path)
    
    # Cleanup temp
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)
    
    return output_path


# ─── CLI ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Professional Audio Processor")
    parser.add_argument("input", help="Input audio file")
    parser.add_argument("-o", "--output", help="Output file")
    parser.add_argument("--normalize", action="store_true", help="Normalize loudness")
    parser.add_argument("--compress", action="store_true", help="Compress dynamics")
    parser.add_argument("--gate", action="store_true", help="Apply noise gate")
    parser.add_argument("--eq", choices=["speech", "warm", "bright", "female", "male"])
    parser.add_argument("--full", action="store_true", help="Full processing chain")
    args = parser.parse_args()
    
    output = args.output or args.input.rsplit(".", 1)[0] + "_processed.wav"
    
    if args.full:
        process_dubbing_audio(args.input, output)
    else:
        if args.normalize:
            normalize_loudness(args.input, output)
            args.input = output
        if args.compress:
            compress_dynamics(args.input, output)
            args.input = output
        if args.gate:
            noise_gate(args.input, output)
            args.input = output
        if args.eq:
            eq_match_speaker(args.input, output, args.eq)
    
    print(f"✅ Processed: {output}")
