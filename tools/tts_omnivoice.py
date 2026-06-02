"""OmniVoice TTS Tool for OpenClaw
Call OmniVoice API for voice cloning, design, or auto TTS.
"""
import os
import requests
import base64
import tempfile
from pathlib import Path

# Default API URL (Cloudflare tunnel)
DEFAULT_OMNIVOICE_URL = os.getenv("OMNIVOICE_API_URL", "")


class OmniVoiceTTS:
    """OmniVoice TTS client for OpenClaw agent."""
    
    def __init__(self, api_url: str = None):
        self.api_url = (api_url or DEFAULT_OMNIVOICE_URL).rstrip("/")
    
    def health(self) -> bool:
        """Check if OmniVoice server is alive."""
        try:
            r = requests.get(f"{self.api_url}/health", timeout=5)
            return r.status_code == 200
        except:
            return False
    
    def synthesize(self, text: str, output_path: str = None) -> str:
        """Auto voice synthesis (no reference needed)."""
        r = requests.post(
            f"{self.api_url}/synthesize",
            json={"text": text},
            timeout=60
        )
        r.raise_for_status()
        
        if not output_path:
            output_path = tempfile.mktemp(suffix=".wav", prefix="omnivoice_")
        
        with open(output_path, "wb") as f:
            f.write(r.content)
        return output_path
    
    def design(self, text: str, instruct: str, output_path: str = None) -> str:
        """Voice design with style instruction.
        
        Valid instruct keywords (English):
        - Gender: male, female
        - Age: child, teenager, young adult, middle-aged, elderly
        - Pitch: very low pitch, low pitch, moderate pitch, high pitch, very high pitch
        - Accent: american, british, australian, canadian, chinese, indian, japanese, korean, portuguese, russian
        - Style: whisper
        
        Example: "female, young adult, vietnamese accent"
        """
        r = requests.post(
            f"{self.api_url}/design",
            json={"text": text, "instruct": instruct},
            timeout=60
        )
        r.raise_for_status()
        
        if not output_path:
            output_path = tempfile.mktemp(suffix=".wav", prefix="omnivoice_design_")
        
        with open(output_path, "wb") as f:
            f.write(r.content)
        return output_path
    
    def clone(self, text: str, ref_audio_path: str, ref_text: str, 
              speed: float = None, output_path: str = None) -> str:
        """Voice cloning from reference audio.
        
        Args:
            text: Text to generate
            ref_audio_path: Path to reference audio file (WAV/MP3)
            ref_text: Transcription of reference audio
            speed: Speaking speed (optional)
        """
        with open(ref_audio_path, "rb") as f:
            files = {"ref_audio": f}
            data = {
                "text": text,
                "ref_text": ref_text
            }
            if speed:
                data["speed"] = str(speed)
            
            r = requests.post(
                f"{self.api_url}/clone",
                files=files,
                data=data,
                timeout=120
            )
        r.raise_for_status()
        
        if not output_path:
            output_path = tempfile.mktemp(suffix=".wav", prefix="omnivoice_clone_")
        
        with open(output_path, "wb") as f:
            f.write(r.content)
        return output_path


# Tool function for OpenClaw agent
def tts_tool(text: str, mode: str = "auto", voice_instruct: str = None,
             ref_audio: str = None, ref_text: str = None, 
             speed: float = None, output: str = None) -> dict:
    """TTS tool for OpenClaw agent.
    
    Modes:
    - "auto": Auto voice (no reference needed)
    - "design": Voice design with instruct keywords
    - "clone": Voice cloning from reference audio
    
    Returns:
        {"success": bool, "output": str, "error": str}
    """
    try:
        tts = OmniVoiceTTS()
        
        if not tts.health():
            return {"success": False, "error": "OmniVoice server not reachable"}
        
        if mode == "auto":
            path = tts.synthesize(text, output)
        elif mode == "design":
            if not voice_instruct:
                return {"success": False, "error": "voice_instruct required for design mode"}
            path = tts.design(text, voice_instruct, output)
        elif mode == "clone":
            if not ref_audio or not ref_text:
                return {"success": False, "error": "ref_audio and ref_text required for clone mode"}
            path = tts.clone(text, ref_audio, ref_text, speed, output)
        else:
            return {"success": False, "error": f"Unknown mode: {mode}"}
        
        return {"success": True, "output": path}
    
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    # Test
    tts = OmniVoiceTTS()
    print(f"API URL: {tts.api_url}")
    print(f"Health: {tts.health()}")
    
    if tts.health():
        path = tts.synthesize("Xin chào, đây là test từ OpenClaw!")
        print(f"Output: {path}")
