#!/usr/bin/env python3
"""
OpenClaw MiMo Dubbing Agent
============================
Agent that controls video dubbing pipeline.

Flow:
1. User sends video URL to OpenClaw
2. OpenClaw triggers this agent
3. Agent runs: Download → Transcribe → Translate → TTS → Combine
4. Agent returns dubbed video

Usage:
  # As OpenClaw skill
  from agent import dubbing_agent
  result = dubbing_agent(url="https://youtube.com/...", target_lang="Vietnamese")
  
  # As standalone
  BOT_TOKEN=*** python3 agent.py
"""

import os
import sys
import time
import asyncio
from pathlib import Path

# Add parent to path
sys.path.insert(0, os.path.dirname(__file__))

from engines.dubbing_engine import run_pipeline, DubConfig
from tools.tts_omnivoice import OmniVoiceTTS

# AGI Brain
try:
    from brain import AGIBrain
    HAS_BRAIN = True
except ImportError:
    HAS_BRAIN = False

# ─── Config ────────────────────────────────────────────────────────
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
MIMO_API_BASE = os.getenv("MIMO_API_BASE", "https://api.xiaomimimo.com/v1")
MIMO_MODEL = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
OMNIVOICE_URL = os.getenv("OMNIVOICE_API_URL", "")
OMNIVOICE_KEY = os.getenv("OMNIVOICE_API_KEY", "")
DATA_DIR = os.getenv("DATA_DIR", "/tmp/openclaw-dubbing")


class DubbingAgent:
    """OpenClaw agent for video dubbing."""
    
    def __init__(self):
        self.config = DubConfig(
            mimo_api_key=MIMO_API_KEY,
            mimo_api_base=MIMO_API_BASE,
            mimo_model=MIMO_MODEL,
            omnivoice_url=OMNIVOICE_URL,
            omnivoice_key=OMNIVOICE_KEY,
        )
        self.tts = OmniVoiceTTS(OMNIVOICE_URL) if OMNIVOICE_URL else None
    
    def check_health(self) -> dict:
        """Check all services health."""
        return {
            "mimo": bool(MIMO_API_KEY),
            "omnivoice": self.tts.health() if self.tts else False,
            "omnivoice_url": OMNIVOICE_URL,
            "brain": HAS_BRAIN,
        }
    
    def dub(self, url: str = "", video_path: str = "",
            source_lang: str = "Chinese",
            target_lang: str = "Vietnamese",
            voice: str = "female, vietnamese accent, natural",
            emotion: str = "neutral",
            subtitle_style: str = "professional") -> dict:
        """
        Dub a video.
        
        Args:
            url: Video URL (YouTube, Bilibili, etc.)
            video_path: Local video file path (alternative to url)
            source_lang: Source language
            target_lang: Target language
            voice: Voice instruct for OmniVoice
            emotion: Emotion style
            subtitle_style: Subtitle style
        
        Returns:
            {"success": bool, "output_video": str, "error": str, ...}
        """
        try:
            # Update config with per-request settings
            config = DubConfig(
                mimo_api_key=self.config.mimo_api_key,
                mimo_api_base=self.config.mimo_api_base,
                mimo_model=self.config.mimo_model,
                omnivoice_url=self.config.omnivoice_url,
                omnivoice_key=self.config.omnivoice_key,
                tts_engine="omnivoice",
                tts_instruct=voice,
                tts_emotion=emotion,
                subtitle_style=subtitle_style,
                output_dir=os.path.join(DATA_DIR, f"job_{int(time.time())}"),
            )
            
            os.makedirs(config.output_dir, exist_ok=True)
            
            result = run_pipeline(
                url=url,
                video_path=video_path,
                source_lang=source_lang,
                target_lang=target_lang,
                config=config,
            )
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
    
    def tts_generate(self, text: str, mode: str = "auto",
                     voice: str = None, ref_audio: str = None,
                     ref_text: str = None) -> dict:
        """Generate TTS audio."""
        if not self.tts:
            return {"success": False, "error": "OmniVoice not configured"}
        
        try:
            if mode == "design":
                path = self.tts.design(text, voice or "female, vietnamese accent, natural")
            elif mode == "clone":
                path = self.tts.clone(text, ref_audio, ref_text)
            else:
                path = self.tts.synthesize(text)
            
            return {"success": True, "output": path}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ─── Global Agent Instance ─────────────────────────────────────────
_agent = None

def get_agent() -> DubbingAgent:
    """Get or create agent instance."""
    global _agent
    if _agent is None:
        _agent = DubbingAgent()
    return _agent


    def analyze(self, video_url: str = "", video_path: str = "") -> dict:
        """Analyze a video without dubbing — returns brain insights."""
        if not self.tts:
            return {"success": False, "error": "Services not configured"}
        
        try:
            config = DubConfig(
                mimo_api_key=self.config.mimo_api_key,
                mimo_api_base=self.config.mimo_api_base,
                mimo_model=self.config.mimo_model,
                omnivoice_url=self.config.omnivoice_url,
                output_dir=os.path.join(DATA_DIR, f"analysis_{int(time.time())}"),
            )
            os.makedirs(config.output_dir, exist_ok=True)
            
            # Download + transcribe only
            from engines.dubbing_engine import step_download, step_extract_audio, step_transcribe
            lang_codes = {"Chinese": "zh", "Japanese": "ja", "Korean": "ko", "English": "en"}
            
            if video_url:
                video_path = step_download(video_url, config.output_dir)
            audio_path = step_extract_audio(video_path, config.output_dir)
            segments = step_transcribe(audio_path, "zh", config)
            
            # Brain analysis
            if HAS_BRAIN:
                brain = AGIBrain(config.mimo_api_key, config.mimo_api_base, config.mimo_model)
                analysis = brain.analyze(segments, "Chinese", "Vietnamese")
                return {"success": True, "analysis": analysis, "segments": len(segments)}
            
            return {"success": True, "segments": len(segments), "analysis": {}}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def brain_stats(self) -> dict:
        """Get brain learning statistics."""
        if HAS_BRAIN:
            brain = AGIBrain()
            return brain.learner.get_stats()
        return {"error": "Brain not available"}


# ─── Convenience Functions (for OpenClaw skill) ─────────────────────
def dub_video(url: str, **kwargs) -> dict:
    """Dub a video from URL."""
    return get_agent().dub(url=url, **kwargs)

def dub_file(path: str, **kwargs) -> dict:
    """Dub a local video file."""
    return get_agent().dub(video_path=path, **kwargs)

def generate_tts(text: str, **kwargs) -> dict:
    """Generate TTS audio."""
    return get_agent().tts_generate(text, **kwargs)

def health_check() -> dict:
    """Check agent health."""
    return get_agent().check_health()


def analyze_video(url: str = "", video_path: str = "") -> dict:
    """Analyze video content without dubbing."""
    return get_agent().analyze(url=url, video_path=video_path)

def brain_stats() -> dict:
    """Get brain learning stats."""
    return get_agent().brain_stats()


# ─── Telegram Bot Mode ──────────────────────────────────────────────
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--telegram":
    """Run as Telegram bot."""
    from telegram_agent import main
    main()
