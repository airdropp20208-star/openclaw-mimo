#!/usr/bin/env python3
"""
Emotional Continuity Engine — Consistent Emotional Arcs
=======================================================
Ensures emotions are CONSISTENT and BUILDING throughout the video:
- Maps the emotional arc of the entire video
- Ensures transitions between emotions are smooth
- Maintains character emotional consistency
- Builds tension and release like a real story
- Prevents jarring emotion jumps

Humans don't randomly switch emotions — they FLOW.
This module makes sure the dubbed audio FLOWS too.
"""

import json
from collections import defaultdict


class EmotionalContinuity:
    """Maintains consistent emotional arcs across the video."""
    
    def __init__(self):
        self.arc_cache = {}
    
    def build_arc(self, segments: list[dict], context: dict = None) -> dict:
        """
        Build a comprehensive emotional arc for the entire video.
        Returns a smooth emotion timeline that TTS can follow.
        """
        if not segments:
            return {"segments": [], "acts": [], "dominant_mood": "neutral"}
        
        total_duration = max(s.get("end", 0) for s in segments)
        
        # Step 1: Map raw emotions
        raw_emotions = []
        for seg in segments:
            raw_emotions.append({
                "start": seg.get("start", 0),
                "end": seg.get("end", 0),
                "position": seg.get("start", 0) / max(total_duration, 0.01),
                "emotion": seg.get("emotion", "neutral"),
                "text": seg.get("text", ""),
                "segment_index": seg.get("index", 0),
            })
        
        # Step 2: Identify narrative structure (beginning, middle, end)
        acts = self._identify_acts(raw_emotions, total_duration)
        
        # Step 3: Smooth transitions
        smoothed = self._smooth_transitions(raw_emotions, acts)
        
        # Step 4: Add tension/release beats
        with_tension = self._add_tension_release(smoothed, acts, context)
        
        # Step 5: Ensure character consistency
        consistent = self._ensure_character_consistency(with_tension)
        
        # Step 6: Build final timeline
        timeline = self._build_timeline(consistent, total_duration)
        
        return {
            "segments": consistent,
            "acts": acts,
            "timeline": timeline,
            "dominant_mood": self._dominant_mood(consistent),
            "emotional_range": self._emotional_range(consistent),
            "total_duration": total_duration,
        }
    
    def apply_arc(self, segments: list[dict], arc: dict) -> list[dict]:
        """
        Apply the emotional arc to segments.
        Adjusts emotions for smooth, natural flow.
        """
        timeline = arc.get("timeline", [])
        
        for seg in segments:
            pos = seg.get("start", 0) / max(arc.get("total_duration", 1), 0.01)
            
            # Find the corresponding arc entry
            for entry in timeline:
                if entry["start_pos"] <= pos <= entry["end_pos"]:
                    # Use the smoothed emotion, not the raw one
                    if seg.get("emotion") == "neutral" and entry.get("emotion") != "neutral":
                        seg["emotion"] = entry["emotion"]
                    seg["energy"] = entry.get("energy", 0.5)
                    seg["tempo"] = entry.get("tempo", "normal")
                    break
        
        return segments
    
    def _identify_acts(self, emotions: list[dict], total_duration: float) -> list[dict]:
        """Identify narrative acts (beginning, rising, climax, falling, resolution)."""
        if total_duration <= 0:
            return []
        
        # Simple act structure based on emotional intensity
        acts = [
            {"name": "opening", "start_pos": 0.0, "end_pos": 0.15, "expected_energy": "low"},
            {"name": "setup", "start_pos": 0.15, "end_pos": 0.3, "expected_energy": "medium-low"},
            {"name": "rising", "start_pos": 0.3, "end_pos": 0.5, "expected_energy": "medium"},
            {"name": "climax", "start_pos": 0.5, "end_pos": 0.7, "expected_energy": "high"},
            {"name": "falling", "start_pos": 0.7, "end_pos": 0.85, "expected_energy": "medium"},
            {"name": "resolution", "start_pos": 0.85, "end_pos": 1.0, "expected_energy": "low"},
        ]
        
        # Adjust based on actual emotional content
        for act in acts:
            segment_emotions = [
                e for e in emotions
                if act["start_pos"] <= e["position"] <= act["end_pos"]
            ]
            
            if segment_emotions:
                high_energy = sum(1 for e in segment_emotions 
                    if e["emotion"] in ("angry", "excited", "fearful", "surprised"))
                act["actual_energy"] = "high" if high_energy > len(segment_emotions) * 0.3 else "medium"
                act["dominant_emotion"] = self._most_common(
                    [e["emotion"] for e in segment_emotions]
                )
            else:
                act["actual_energy"] = act["expected_energy"]
                act["dominant_emotion"] = "neutral"
        
        return acts
    
    def _smooth_transitions(self, emotions: list[dict], acts: list[dict]) -> list[dict]:
        """
        Smooth emotion transitions.
        Humans don't jump from happy to angry instantly — there's a buildup.
        """
        if len(emotions) <= 1:
            return emotions
        
        smoothed = []
        for i, emo in enumerate(emotions):
            smoothed_emo = dict(emo)
            
            if i > 0:
                prev = emotions[i - 1]
                prev_emotion = prev["emotion"]
                curr_emotion = emo["emotion"]
                
                # If emotions are very different, add transition
                if prev_emotion != curr_emotion and not self._are_compatible(prev_emotion, curr_emotion):
                    # Create a transition at the start of current segment
                    smoothed_emo["is_transition_from"] = prev_emotion
                    smoothed_emo["transition_strength"] = 0.3  # Gradual transition
            
            smoothed.append(smoothed_emo)
        
        return smoothed
    
    def _add_tension_release(self, emotions: list[dict], acts: list[dict], context: dict = None) -> list[dict]:
        """Add tension and release beats for dramatic effect."""
        genre = (context or {}).get("genre", "casual")
        
        # Only add tension for dramatic content
        if genre in ("drama", "action", "horror", "romance"):
            for emo in emotions:
                pos = emo["position"]
                
                # Build tension before climax
                if 0.4 <= pos <= 0.55:
                    if emo["emotion"] in ("neutral", "calm"):
                        emo["emotion"] = "serious"
                        emo["energy"] = min(emo.get("energy", 0.5) + 0.1, 0.8)
                
                # Release after climax
                elif 0.7 <= pos <= 0.8:
                    if emo["emotion"] in ("angry", "excited", "fearful"):
                        emo["emotion"] = "calm"
                        emo["energy"] = max(emo.get("energy", 0.5) - 0.2, 0.2)
        
        return emotions
    
    def _ensure_character_consistency(self, emotions: list[dict]) -> list[dict]:
        """Ensure individual characters maintain emotional consistency."""
        # Group by speaker if available
        speakers = defaultdict(list)
        for emo in emotions:
            speaker = emo.get("speaker_id", 0)
            speakers[speaker].append(emo)
        
        # For each speaker, smooth their personal arc
        consistent = []
        for speaker_id, speaker_emotions in speakers.items():
            smoothed = self._smooth_single_arc(speaker_emotions)
            consistent.extend(smoothed)
        
        # Re-sort by position
        consistent.sort(key=lambda x: x["start"])
        
        return consistent
    
    def _smooth_single_arc(self, emotions: list[dict]) -> list[dict]:
        """Smooth a single speaker's emotional arc."""
        if len(emotions) <= 2:
            return emotions
        
        smoothed = []
        for i, emo in enumerate(emotions):
            smoothed_emo = dict(emo)
            
            if 0 < i < len(emotions) - 1:
                prev_emotion = emotions[i - 1]["emotion"]
                next_emotion = emotions[i + 1]["emotion"]
                curr_emotion = emo["emotion"]
                
                # If isolated emotion (different from neighbors), moderate it
                if curr_emotion != prev_emotion and curr_emotion != next_emotion:
                    if self._are_compatible(prev_emotion, next_emotion):
                        # Use the compatible emotion instead
                        smoothed_emo["emotion"] = prev_emotion
                        smoothed_emo["was_moderated"] = True
            
            smoothed.append(smoothed_emo)
        
        return smoothed
    
    def _build_timeline(self, emotions: list[dict], total_duration: float) -> list[dict]:
        """Build a clean timeline for the pipeline."""
        if not emotions:
            return []
        
        timeline = []
        for emo in emotions:
            pos = emo.get("position", 0)
            energy = emo.get("energy", 0.5)
            
            # Determine tempo from emotion
            tempo = "normal"
            if emo["emotion"] in ("excited", "angry"):
                tempo = "fast"
            elif emo["emotion"] in ("sad", "calm", "whisper"):
                tempo = "slow"
            elif emo["emotion"] == "serious":
                tempo = "measured"
            
            timeline.append({
                "start_pos": pos,
                "end_pos": min(pos + 0.05, 1.0),
                "emotion": emo["emotion"],
                "energy": energy,
                "tempo": tempo,
                "segment_index": emo.get("segment_index", 0),
            })
        
        return timeline
    
    def _are_compatible(self, emotion_a: str, emotion_b: str) -> bool:
        """Check if two emotions can naturally coexist or transition."""
        compatible_groups = [
            {"happy", "excited", "tender"},
            {"sad", "calm", "whisper", "tender"},
            {"angry", "fearful", "surprised"},
            {"serious", "calm", "neutral"},
        ]
        
        for group in compatible_groups:
            if emotion_a in group and emotion_b in group:
                return True
        return False
    
    def _dominant_mood(self, emotions: list[dict]) -> str:
        """Get the dominant mood."""
        return self._most_common([e["emotion"] for e in emotions]) or "neutral"
    
    def _emotional_range(self, emotions: list[dict]) -> list[str]:
        """Get unique emotions present."""
        return list(set(e["emotion"] for e in emotions))
    
    def _most_common(self, items: list[str]) -> str:
        """Get most common item."""
        from collections import Counter
        if not items:
            return ""
        return Counter(items).most_common(1)[0][0]
