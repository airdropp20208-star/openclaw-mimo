#!/usr/bin/env python3
"""
OmniVoice TTS API Server
========================
FastAPI server for OmniVoice voice cloning + voice design.

Chạy trên GPU machine:
  python server.py --host 0.0.0.0 --port 8880

API endpoints:
  POST /tts          — Generate speech (voice clone/design/auto)
  POST /tts/batch    — Batch generate multiple texts
  GET  /voices       — List predefined voice presets
  GET  /health       — Health check
  GET  /             — Server info
"""

import argparse
import io
import os
import sys
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

# ─── Config ────────────────────────────────────────────────────────
MODEL_ID = os.getenv("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
DEVICE = os.getenv("OMNIVOICE_DEVICE", "auto")
CACHE_DIR = os.getenv("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
API_KEY = os.getenv("OMNIVOICE_API_KEY", "")  # Optional auth

# ─── App ───────────────────────────────────────────────────────────
app = FastAPI(
    title="OmniVoice TTS API",
    description="Voice cloning + voice design + 600 languages",
    version="1.0.0",
)

# Global model
_model = None
_model_config = {}

# ─── Voice presets ─────────────────────────────────────────────────
VOICE_PRESETS = {
    "vi-female-natural": "female, vietnamese accent, natural",
    "vi-male-natural": "male, vietnamese accent, natural",
    "vi-female-southern": "female, southern vietnamese accent",
    "vi-male-southern": "male, southern vietnamese accent",
    "vi-female-northern": "female, northern vietnamese accent",
    "vi-male-northern": "male, northern vietnamese accent",
    "en-female-american": "female, american english",
    "en-male-american": "male, american english",
    "zh-female-mandarin": "female, mandarin chinese",
    "zh-male-mandarin": "male, mandarin chinese",
    "ja-female": "female, japanese",
    "ja-male": "male, japanese",
    "ko-female": "female, korean",
    "ko-male": "male, korean",
}


# ─── Request/Response models ──────────────────────────────────────
class TTSRequest(BaseModel):
    text: str = Field(..., max_length=10000, description="Text to synthesize")
    mode: str = Field("auto", description="auto, clone, design")
    instruct: str = Field("", description='Voice design prompt (e.g. "female, vietnamese accent")')
    ref_audio: str = Field("", description="Base64 encoded reference audio for cloning")
    ref_text: str = Field("", description="Transcription of reference audio")
    ref_audio_url: str = Field("", description="URL to reference audio for cloning")
    voice_preset: str = Field("", description="Preset ID (e.g. vi-female-natural)")
    language: str = Field("", description="Language code (vi, en, zh, ja, ko...)")
    speed: float = Field(1.0, ge=0.5, le=2.0, description="Speech speed")
    format: str = Field("wav", description="Output format: wav, mp3")


class TTSBatchRequest(BaseModel):
    items: list[TTSRequest]


class TTSResponse(BaseModel):
    success: bool
    duration: float = 0.0
    sample_rate: int = 24000
    format: str = "wav"
    size: int = 0
    mode: str = "auto"
    processing_time: float = 0.0
    error: str = ""


# ─── Model loading ────────────────────────────────────────────────
def load_model():
    global _model, _model_config
    
    if _model is not None:
        return _model
    
    import torch
    from omnivoice import OmniVoice
    
    # Auto-detect device
    device = DEVICE
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    
    print(f"Loading OmniVoice model: {MODEL_ID} on {device}...", flush=True)
    t0 = time.time()
    
    _model = OmniVoice.from_pretrained(
        MODEL_ID,
        device_map=device,
        dtype=torch.float32 if device == "cpu" else torch.float16,
    )
    
    _model_config = {
        "device": device,
        "sample_rate": _model.sampling_rate,
        "model_id": MODEL_ID,
    }
    
    print(f"Model loaded in {time.time()-t0:.1f}s (device={device})", flush=True)
    return _model


# ─── Auth middleware ───────────────────────────────────────────────
def check_auth(authorization: str = ""):
    if not API_KEY:
        return True
    return authorization == f"Bearer {API_KEY}"


# ─── Routes ───────────────────────────────────────────────────────
@app.get("/")
def root():
    return {
        "service": "OmniVoice TTS API",
        "version": "1.0.0",
        "model": MODEL_ID,
        "device": _model_config.get("device", "loading..."),
        "endpoints": ["/tts", "/tts/batch", "/voices", "/health"],
    }


@app.get("/health")
def health():
    return {
        "status": "ok" if _model is not None else "loading",
        "model_loaded": _model is not None,
        "device": _model_config.get("device", "unknown"),
        "sample_rate": _model_config.get("sample_rate", 0),
    }


@app.get("/voices")
def list_voices():
    return {
        "presets": [{"id": k, "instruct": v} for k, v in VOICE_PRESETS.items()],
        "note": "Use --instruct with any custom description for voice design",
    }


@app.post("/tts", response_class=Response)
def generate_tts(req: TTSRequest):
    """Generate speech audio."""
    model = load_model()
    
    # Determine mode
    mode = req.mode
    instruct = req.instruct
    ref_audio_path = None
    
    # Resolve voice preset
    if req.voice_preset and req.voice_preset in VOICE_PRESETS:
        instruct = VOICE_PRESETS[req.voice_preset]
        mode = "design"
    
    # Determine mode from inputs
    if req.ref_audio or req.ref_audio_url:
        mode = "clone"
    elif instruct:
        mode = "design"
    else:
        mode = "auto"
    
    # Handle reference audio
    if req.ref_audio_url:
        # Download from URL
        import requests as req_lib
        try:
            resp = req_lib.get(req.ref_audio_url, timeout=30)
            resp.raise_for_status()
            ref_audio_data = io.BytesIO(resp.content)
            
            # Save to temp file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(resp.content)
                ref_audio_path = f.name
        except Exception as e:
            raise HTTPException(400, f"Failed to download ref audio: {e}")
    
    elif req.ref_audio:
        # Decode base64
        import base64, tempfile
        try:
            audio_bytes = base64.b64decode(req.ref_audio)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_bytes)
                ref_audio_path = f.name
        except Exception as e:
            raise HTTPException(400, f"Invalid base64 audio: {e}")
    
    # Build generation kwargs
    gen_kwargs = {"text": req.text, "speed": req.speed}
    
    if req.language:
        gen_kwargs["language"] = req.language
    
    if mode == "clone" and ref_audio_path:
        gen_kwargs["ref_audio"] = ref_audio_path
        if req.ref_text:
            gen_kwargs["ref_text"] = req.ref_text
    elif mode == "design" and instruct:
        gen_kwargs["instruct"] = instruct
    
    # Generate
    try:
        t0 = time.time()
        audio = model.generate(**gen_kwargs)
        processing_time = time.time() - t0
        
        audio_data = audio[0]
        audio_duration = len(audio_data) / model.sampling_rate
        
    except Exception as e:
        raise HTTPException(500, f"Generation failed: {e}")
    finally:
        # Cleanup temp file
        if ref_audio_path and os.path.exists(ref_audio_path):
            os.remove(ref_audio_path)
    
    # Encode to format
    import soundfile as sf
    import io
    
    if req.format == "mp3":
        # WAV first, then convert
        wav_buf = io.BytesIO()
        sf.write(wav_buf, audio_data, model.sampling_rate, format="WAV")
        wav_buf.seek(0)
        
        try:
            from pydub import AudioSegment
            audio_seg = AudioSegment.from_wav(wav_buf)
            mp3_buf = io.BytesIO()
            audio_seg.export(mp3_buf, format="mp3", bitrate="192k")
            audio_bytes = mp3_buf.getvalue()
            content_type = "audio/mpeg"
        except ImportError:
            # Fallback to WAV
            audio_bytes = wav_buf.getvalue()
            content_type = "audio/wav"
    else:
        wav_buf = io.BytesIO()
        sf.write(wav_buf, audio_data, model.sampling_rate, format="WAV")
        audio_bytes = wav_buf.getvalue()
        content_type = "audio/wav"
    
    return Response(
        content=audio_bytes,
        media_type=content_type,
        headers={
            "X-Audio-Duration": str(audio_duration),
            "X-Processing-Time": str(processing_time),
            "X-Sample-Rate": str(model.sampling_rate),
            "X-Mode": mode,
        },
    )


@app.post("/tts/batch")
def generate_tts_batch(req: TTSBatchRequest):
    """Batch generate multiple TTS clips."""
    results = []
    for i, item in enumerate(req.items):
        try:
            resp = generate_tts(item)
            results.append({
                "index": i,
                "success": True,
                "size": len(resp.body),
                "content_type": resp.media_type,
            })
        except HTTPException as e:
            results.append({
                "index": i,
                "success": False,
                "error": e.detail,
            })
    return {"results": results}


# ─── Main ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8880)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    
    # Pre-load model
    load_model()
    
    # Run server
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()
