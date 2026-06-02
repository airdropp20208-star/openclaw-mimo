#!/usr/bin/env python3
"""
Strategy Selector — Intelligent Dubbing Strategy
=================================================
Analyzes content and selects optimal strategy:
- Translation approach (literal vs adaptive vs creative)
- TTS voice strategy (single speaker vs multi-speaker)
- Audio processing pipeline (minimal vs studio)
- Subtitle strategy (presence, timing, style)
- Pacing strategy (match original vs natural Vietnamese)
"""


class StrategySelector:
    """Auto-select dubbing strategy based on content analysis."""
    
    def __init__(self, context_engine=None, emotion_detector=None):
        self.context_engine = context_engine
        self.emotion_detector = emotion_detector
    
    def select(self, segments: list[dict], context: dict) -> dict:
        """
        Select comprehensive dubbing strategy.
        Returns strategy config for the pipeline.
        """
        genre = context.get("genre", "casual")
        formality = context.get("formality", "casual")
        target_audience = context.get("target_audience", "general")
        humor_type = context.get("humor_type", "none")
        
        # ─── Translation Strategy ──────────────────────────────
        translation = self._select_translation(genre, formality, humor_type)
        
        # ─── TTS Strategy ──────────────────────────────────────
        tts = self._select_tts(segments, context)
        
        # ─── Audio Processing Strategy ─────────────────────────
        audio = self._select_audio(genre, target_audience)
        
        # ─── Subtitle Strategy ─────────────────────────────────
        subtitle = self._select_subtitle(genre, formality)
        
        # ─── Pacing Strategy ───────────────────────────────────
        pacing = self._select_pacing(genre, segments)
        
        # ─── Quality Level ─────────────────────────────────────
        quality = self._select_quality(target_audience)
        
        return {
            "translation": translation,
            "tts": tts,
            "audio": audio,
            "subtitle": subtitle,
            "pacing": pacing,
            "quality": quality,
            "cultural_adapt": translation.get("adaptive", True),
        }
    
    def _select_translation(self, genre: str, formality: str, humor_type: str) -> dict:
        """Select translation approach."""
        strategy = {
            "method": "adaptive",  # adaptive, literal, creative
            "temperature": 0.3,
            "preserve_slang": True,
            "preserve_humor": humor_type != "none",
            "preserve_cultural_refs": True,
        }
        
        if genre == "news":
            strategy["method"] = "adaptive"
            strategy["temperature"] = 0.2  # More precise for news
            strategy["preserve_humor"] = False
        elif genre == "comedy":
            strategy["method"] = "creative"
            strategy["temperature"] = 0.5  # More creative for comedy
            strategy["preserve_humor"] = True
        elif genre == "tutorial":
            strategy["method"] = "adaptive"
            strategy["temperature"] = 0.15  # Precise for tutorials
        elif genre == "drama":
            strategy["method"] = "creative"
            strategy["temperature"] = 0.4
        elif genre == "documentary":
            strategy["method"] = "adaptive"
            strategy["temperature"] = 0.25
        
        if formality == "formal":
            strategy["preserve_slang"] = False
            strategy["temperature"] -= 0.1
        
        return strategy
    
    def _select_tts(self, segments: list[dict], context: dict) -> dict:
        """Select TTS strategy."""
        speakers = context.get("speakers", [])
        num_speakers = max(len(speakers), 1)
        
        return {
            "multi_speaker": num_speakers > 1,
            "num_speakers": num_speakers,
            "voice_matching": num_speakers > 1,
            "emotion_per_segment": True,
            "breath_preservation": True,
            "speed_variation": True,
            # Dynamic voice selection based on gender
            "voice_map": {
                "male": "vi-male-natural",
                "female": "vi-female-natural",
                "unknown": "vi-female-natural",
            },
        }
    
    def _select_audio(self, genre: str, audience: str) -> dict:
        """Select audio processing strategy."""
        strategy = {
            "normalize": True,
            "compress": True,
            "noise_gate": True,
            "eq_profile": "speech",
            "target_lufs": -16.0,
            "dynamic_compression": True,
        }
        
        if genre == "news":
            strategy["target_lufs"] = -14.0  # Slightly louder for news
            strategy["eq_profile"] = "speech"
        elif genre == "music" or genre == "drama":
            strategy["dynamic_compression"] = False  # Preserve dynamics
            strategy["eq_profile"] = "warm"
        elif genre == "tutorial":
            strategy["eq_profile"] = "speech"
            strategy["target_lufs"] = -16.0
        
        if audience == "elderly":
            strategy["target_lufs"] = -13.0  # Louder for elderly
        
        return strategy
    
    def _select_subtitle(self, genre: str, formality: str) -> dict:
        """Select subtitle strategy."""
        strategy = {
            "enabled": True,
            "style": "professional",
            "max_chars_per_line": 40,
            "min_duration": 1.0,
            "max_duration": 5.0,
            "position": "bottom",
        }
        
        if genre == "anime":
            strategy["style"] = "anime"
        elif genre == "tutorial":
            strategy["style"] = "professional"
            strategy["max_chars_per_line"] = 35  # Easier to read
        elif formality == "formal":
            strategy["style"] = "professional"
            strategy["max_chars_per_line"] = 45
        
        return strategy
    
    def _select_pacing(self, genre: str, segments: list[dict]) -> dict:
        """Select pacing strategy."""
        # Calculate average speaking rate
        if segments:
            durations = [s["end"] - s["start"] for s in segments if s["end"] > s["start"]]
            chars_per_sec = [len(s["text"]) / max(d, 0.1) for s, d in zip(segments, durations) if d > 0]
            avg_cps = sum(chars_per_sec) / max(len(chars_per_sec), 1)
        else:
            avg_cps = 5.0
        
        return {
            "match_original": True,  # Try to match original timing
            "allow_speed_range": [0.7, 1.3],  # Conservative speed range
            "preserve_pauses": True,
            "crossfade_ms": 50,
            "avg_chars_per_second": avg_cps,
            "max_speedup": 1.4,  # Don't speed up more than 1.4x
            "max_slowdown": 0.7,  # Don't slow down more than 0.7x
        }
    
    def _select_quality(self, audience: str) -> dict:
        """Select overall quality level."""
        return {
            "level": "high" if audience == "general" else "standard",
            "sample_rate": 48000,
            "bit_depth": 16,
            "video_crf": 18,
            "audio_bitrate": "192k",
        }
