#!/usr/bin/env python3
"""
OmniVoice API Client
====================
Call remote OmniVoice server from GitHub Actions or local script.

Usage:
  from omnivoice_client import OmniVoiceClient
  
  client = OmniVoiceClient("https://your-server:8880", api_key="xxx")
  
  # Voice Design
  audio_bytes = client.generate("Xin chào", instruct="female, vietnamese accent")
  
  # Voice Clone
  audio_bytes = client.generate("Hello", ref_audio="voice.wav", ref_text="sample")
  
  # Save
  client.save(audio_bytes, "output.wav")
"""

import base64
import os
from typing import Optional

import requests


class OmniVoiceClient:
    """Client for remote OmniVoice TTS API server."""
    
    def __init__(self, base_url: str, api_key: str = "", timeout: int = 300):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
    
    def health(self) -> dict:
        """Check server health."""
        resp = requests.get(f"{self.base_url}/health", timeout=10)
        resp.raise_for_status()
        return resp.json()
    
    def voices(self) -> list:
        """List available voice presets."""
        resp = requests.get(f"{self.base_url}/voices", timeout=10)
        resp.raise_for_status()
        return resp.json()["presets"]
    
    def generate(
        self,
        text: str,
        mode: str = "auto",
        instruct: str = "",
        ref_audio: str = "",
        ref_text: str = "",
        ref_audio_url: str = "",
        voice_preset: str = "",
        language: str = "",
        speed: float = 1.0,
        format: str = "wav",
    ) -> bytes:
        """
        Generate speech audio.
        
        Returns audio bytes (WAV or MP3).
        """
        payload = {
            "text": text,
            "mode": mode,
            "instruct": instruct,
            "ref_text": ref_text,
            "ref_audio_url": ref_audio_url,
            "voice_preset": voice_preset,
            "language": language,
            "speed": speed,
            "format": format,
        }
        
        # Handle local reference audio file
        if ref_audio and os.path.exists(ref_audio):
            with open(ref_audio, "rb") as f:
                payload["ref_audio"] = base64.b64encode(f.read()).decode()
        
        resp = requests.post(
            f"{self.base_url}/tts",
            json=payload,
            headers=self.headers,
            timeout=self.timeout,
        )
        
        if resp.status_code != 200:
            error = resp.text[:500]
            raise Exception(f"TTS failed ({resp.status_code}): {error}")
        
        return resp.content
    
    def generate_and_save(
        self,
        text: str,
        output_path: str,
        **kwargs,
    ) -> str:
        """Generate and save to file. Returns the output path."""
        format = kwargs.get("format", "wav")
        audio_bytes = self.generate(text, **kwargs)
        
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        
        return output_path
    
    def save(self, audio_bytes: bytes, output_path: str) -> str:
        """Save audio bytes to file."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return output_path
