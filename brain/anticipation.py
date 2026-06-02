#!/usr/bin/env python3
"""
Anticipation Network — Prediction + Narrative Intelligence
==========================================================
The brain PREDICTS what comes next:
- Anticipates emotional peaks before they happen
- Builds tension toward climactic moments
- Prepares transitions before they arrive
- Predicts speaker turns and topic shifts
- Understands narrative structure (setup → conflict → resolution)

Humans don't just REACT — they ANTICIPATE.
A dubbing director knows the climax is coming and prepares the voice.
"""

import requests


class AnticipationNetwork:
    """Predictive intelligence for narrative-driven dubbing."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
    
    def analyze_narrative(self, segments: list[dict], context: dict = None) -> dict:
        """
        Analyze the full narrative structure of the video.
        Identifies key moments, turning points, and emotional peaks.
        """
        if not segments:
            return {"turning_points": [], "peaks": [], "structure": "unknown"}
        
        total = len(segments)
        total_duration = max(s.get("end", 0) for s in segments)
        
        # Map emotional intensity across time
        intensity_map = self._map_intensity(segments)
        
        # Find peaks (local maxima in emotional intensity)
        peaks = self._find_peaks(intensity_map)
        
        # Find turning points (where the story shifts)
        turning_points = self._find_turning_points(segments, context)
        
        # Classify narrative structure
        structure = self._classify_structure(intensity_map, peaks, turning_points)
        
        # Build anticipation map — what to PREPARE for
        anticipation_map = self._build_anticipation_map(
            segments, peaks, turning_points, structure, total_duration
        )
        
        return {
            "intensity_map": intensity_map,
            "peaks": peaks,
            "turning_points": turning_points,
            "structure": structure,
            "anticipation_map": anticipation_map,
            "total_duration": total_duration,
        }
    
    def get_preparation(self, current_index: int, narrative: dict, lookahead: int = 3) -> dict:
        """
        What should the voice actor PREPARE for in the next few segments?
        Returns preparation guidance for natural emotional transitions.
        """
        peaks = narrative.get("peaks", [])
        turning_points = narrative.get("turning_points", [])
        anticipation_map = narrative.get("anticipation_map", [])
        
        # Check if a peak is approaching
        approaching_peak = None
        for peak in peaks:
            peak_index = peak.get("segment_index", -1)
            distance = peak_index - current_index
            if 0 < distance <= lookahead:
                approaching_peak = peak
                break
        
        # Check if a turning point is approaching
        approaching_turn = None
        for tp in turning_points:
            tp_index = tp.get("segment_index", -1)
            distance = tp_index - current_index
            if 0 < distance <= lookahead:
                approaching_turn = tp
                break
        
        # Get anticipation entry
        anticipation = None
        for entry in anticipation_map:
            if entry.get("prepare_from_index", 0) <= current_index <= entry.get("prepare_until_index", 0):
                anticipation = entry
                break
        
        preparation = {
            "approaching_peak": approaching_peak,
            "approaching_turn": approaching_turn,
            "anticipation": anticipation,
            "should_build_tension": bool(approaching_peak),
            "tension_level": self._calculate_tension_level(current_index, peaks, narrative),
        }
        
        if approaching_peak:
            distance = approaching_peak.get("segment_index", current_index) - current_index
            preparation["build_instruction"] = (
                f"Peak approaching in {distance} segments. "
                f"Start building energy: {approaching_peak.get('type', 'emotional')} peak. "
                f"Gradually increase intensity."
            )
        
        if approaching_turn:
            preparation["turn_instruction"] = (
                f"Story turning point ahead. Prepare for emotional shift: "
                f"{approaching_turn.get('from_mood', '?')} → {approaching_turn.get('to_mood', '?')}"
            )
        
        return preparation
    
    def _map_intensity(self, segments: list[dict]) -> list[dict]:
        """Map emotional intensity across time."""
        emotion_energy = {
            "neutral": 3, "calm": 2, "happy": 6, "sad": 4,
            "angry": 8, "excited": 9, "fearful": 7, "surprised": 7,
            "serious": 5, "whisper": 2, "tender": 4, "disgusted": 6,
        }
        
        intensity_map = []
        for seg in segments:
            emotion = seg.get("emotion", "neutral")
            intensity_map.append({
                "index": seg.get("index", 0),
                "time": seg.get("start", 0),
                "emotion": emotion,
                "intensity": emotion_energy.get(emotion, 3),
                "text_preview": seg.get("text", "")[:30],
            })
        
        return intensity_map
    
    def _find_peaks(self, intensity_map: list[dict]) -> list[dict]:
        """Find local maxima in emotional intensity."""
        if len(intensity_map) < 3:
            return []
        
        peaks = []
        for i in range(1, len(intensity_map) - 1):
            prev = intensity_map[i - 1]["intensity"]
            curr = intensity_map[i]["intensity"]
            next_val = intensity_map[i + 1]["intensity"]
            
            if curr > prev and curr > next_val and curr >= 6:
                peaks.append({
                    "segment_index": intensity_map[i]["index"],
                    "time": intensity_map[i]["time"],
                    "intensity": curr,
                    "emotion": intensity_map[i]["emotion"],
                    "type": "emotional",
                })
        
        return peaks
    
    def _find_turning_points(self, segments: list[dict], context: dict = None) -> list[dict]:
        """Find narrative turning points."""
        turning_points = []
        
        for i in range(1, len(segments)):
            prev_emo = segments[i - 1].get("emotion", "neutral")
            curr_emo = segments[i].get("emotion", "neutral")
            
            # Significant emotion change = potential turning point
            if prev_emo != curr_emo:
                if self._is_significant_shift(prev_emo, curr_emo):
                    turning_points.append({
                        "segment_index": segments[i].get("index", i),
                        "time": segments[i].get("start", 0),
                        "from_mood": prev_emo,
                        "to_mood": curr_emo,
                        "significance": "high" if self._is_dramatic_shift(prev_emo, curr_emo) else "medium",
                    })
        
        return turning_points
    
    def _classify_structure(self, intensity_map: list, peaks: list, turning_points: list) -> dict:
        """Classify the narrative structure."""
        if not intensity_map:
            return "flat"
        
        n = len(intensity_map)
        first_half = sum(d["intensity"] for d in intensity_map[:n//2]) / max(n//2, 1)
        second_half = sum(d["intensity"] for d in intensity_map[n//2:]) / max(n - n//2, 1)
        
        if second_half > first_half * 1.3:
            structure = "building"  # Gets more intense toward end
        elif first_half > second_half * 1.3:
            structure = "falling"  # Intense start, calms down
        elif len(peaks) >= 2:
            structure = "oscillating"  # Multiple peaks and valleys
        elif max(d["intensity"] for d in intensity_map) > 7:
            structure = "climactic"  # One major peak
        else:
            structure = "steady"
        
        return {
            "type": structure,
            "first_half_avg": round(first_half, 1),
            "second_half_avg": round(second_half, 1),
            "peak_count": len(peaks),
            "turn_count": len(turning_points),
        }
    
    def _build_anticipation_map(self, segments, peaks, turning_points, structure, total_duration) -> list:
        """Build a map of when to start preparing for key moments."""
        anticipation_map = []
        
        for peak in peaks:
            peak_idx = peak.get("segment_index", 0)
            # Start preparing 3-5 segments before a peak
            prepare_start = max(0, peak_idx - 4)
            anticipation_map.append({
                "prepare_from_index": prepare_start,
                "prepare_until_index": peak_idx,
                "target_event": "peak",
                "target_index": peak_idx,
                "build_duration": peak_idx - prepare_start,
            })
        
        for tp in turning_points:
            tp_idx = tp.get("segment_index", 0)
            prepare_start = max(0, tp_idx - 2)
            anticipation_map.append({
                "prepare_from_index": prepare_start,
                "prepare_until_index": tp_idx,
                "target_event": "turning_point",
                "target_index": tp_idx,
                "from_mood": tp.get("from_mood"),
                "to_mood": tp.get("to_mood"),
            })
        
        return anticipation_map
    
    def _calculate_tension_level(self, current_index: int, peaks: list, narrative: dict) -> float:
        """Calculate current tension level (0.0 - 1.0)."""
        if not peaks:
            return 0.3
        
        # Find nearest upcoming peak
        min_distance = float("inf")
        nearest_intensity = 0
        
        for peak in peaks:
            distance = peak.get("segment_index", 0) - current_index
            if 0 < distance < min_distance:
                min_distance = distance
                nearest_intensity = peak.get("intensity", 5)
        
        if min_distance == float("inf"):
            return 0.3
        
        # Closer to peak = higher tension
        proximity = max(0, 1 - min_distance / 10)
        return round(proximity * (nearest_intensity / 10), 2)
    
    def _is_significant_shift(self, from_emotion: str, to_emotion: str) -> bool:
        """Check if emotion shift is significant."""
        compatible = [
            {"calm", "neutral"},
            {"happy", "excited", "tender"},
            {"sad", "calm", "whisper"},
            {"angry", "fearful", "surprised"},
        ]
        
        for group in compatible:
            if from_emotion in group and to_emotion in group:
                return False
        return from_emotion != to_emotion
    
    def _is_dramatic_shift(self, from_emotion: str, to_emotion: str) -> bool:
        """Check if this is a dramatic emotional shift."""
        dramatic_pairs = [
            ("happy", "sad"), ("sad", "angry"), ("calm", "excited"),
            ("excited", "fearful"), ("neutral", "angry"),
        ]
        return (from_emotion, to_emotion) in dramatic_pairs or (to_emotion, from_emotion) in dramatic_pairs
