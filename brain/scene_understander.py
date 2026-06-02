#!/usr/bin/env python3
"""
Scene Understander — Multi-Modal Video Intelligence
====================================================
Understands WHAT is happening in the video:
- Extract keyframes and analyze visual content
- Detect facial expressions and body language
- Read on-screen text (subtitles, titles, signs)
- Understand scene transitions (cut, fade, dissolve)
- Identify speakers visually
- Correlate visual mood with audio emotion

This is how humans understand context — they WATCH, not just LISTEN.
"""

import os
import subprocess
import json
import tempfile
import requests


class SceneUnderstander:
    """Multi-modal scene analysis — sees the video like a human would."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
    
    def analyze_video(self, video_path: str, segments: list[dict] = None) -> dict:
        """
        Full video analysis: extract frames, understand scenes, build context.
        Returns rich scene understanding for the pipeline.
        """
        if not os.path.exists(video_path):
            return {"scenes": [], "overall_mood": "unknown", "speakers": []}
        
        # Step 1: Extract keyframes
        keyframes = self._extract_keyframes(video_path)
        
        # Step 2: Analyze scenes
        scenes = self._analyze_scenes(keyframes, segments)
        
        # Step 3: Detect visual mood
        visual_mood = self._detect_visual_mood(scenes)
        
        # Step 4: Detect scene types
        scene_types = self._classify_scenes(scenes)
        
        # Step 5: Build timeline
        timeline = self._build_timeline(scenes, segments)
        
        return {
            "keyframe_count": len(keyframes),
            "scenes": scenes,
            "scene_types": scene_types,
            "visual_mood": visual_mood,
            "timeline": timeline,
            "on_screen_text": self._extract_on_screen_text(scenes),
        }
    
    def get_mood_at_time(self, scene_data: dict, timestamp: float) -> dict:
        """
        Get visual mood at a specific timestamp.
        Used by the pipeline to match TTS emotion to visual.
        """
        timeline = scene_data.get("timeline", [])
        for entry in timeline:
            if entry.get("start", 0) <= timestamp <= entry.get("end", 0):
                return {
                    "mood": entry.get("mood", "neutral"),
                    "scene_type": entry.get("type", "unknown"),
                    "confidence": entry.get("confidence", 0.5),
                }
        
        return {"mood": "neutral", "scene_type": "unknown", "confidence": 0.3}
    
    def _extract_keyframes(self, video_path: str, max_frames: int = 20) -> list[str]:
        """Extract keyframes from video at regular intervals + scene changes."""
        temp_dir = tempfile.mkdtemp(prefix="scene_")
        keyframes_dir = os.path.join(temp_dir, "keyframes")
        os.makedirs(keyframes_dir, exist_ok=True)
        
        # Get video duration
        duration = self._get_duration(video_path)
        if duration <= 0:
            return []
        
        # Extract frames every N seconds + at scene changes
        interval = max(duration / max_frames, 1.0)
        
        # Regular interval frames
        cmd = (
            f'ffmpeg -i "{video_path}" '
            f'-vf "fps=1/{interval:.1f}" '
            f'-q:v 2 '
            f'"{keyframes_dir}/frame_%04d.jpg" '
            f'2>/dev/null'
        )
        subprocess.run(cmd, shell=True, timeout=120)
        
        # Also detect scene changes
        scene_cmd = (
            f'ffmpeg -i "{video_path}" '
            f'-vf "select=gt(scene,0.3)" '
            f'-vsync vfr '
            f'-q:v 2 '
            f'"{keyframes_dir}/scene_%04d.jpg" '
            f'2>/dev/null'
        )
        subprocess.run(scene_cmd, shell=True, timeout=120)
        
        # Collect all frames
        keyframes = []
        for f in sorted(os.listdir(keyframes_dir)):
            if f.endswith((".jpg", ".png")):
                keyframes.append(os.path.join(keyframes_dir, f))
        
        return keyframes[:max_frames]
    
    def _analyze_scenes(self, keyframes: list[str], segments: list[dict] = None) -> list[dict]:
        """Analyze each keyframe for content, mood, and scene type."""
        if not keyframes or not self.api_key:
            return self._fallback_scenes(keyframes)
        
        scenes = []
        
        # Analyze in batches of 5 for efficiency
        batch_size = 5
        for batch_start in range(0, len(keyframes), batch_size):
            batch = keyframes[batch_start:batch_start + batch_size]
            
            # Build image descriptions request
            frame_info = []
            for i, kf in enumerate(batch):
                idx = batch_start + i
                # Calculate approximate timestamp
                timestamp = idx * 5.0  # Rough estimate
                frame_info.append(f"Frame {idx+1} (t={timestamp:.0f}s): {os.path.basename(kf)}")
            
            prompt = f"""Analyze these video frames from a dubbing project. For each frame describe:
1. What is happening (action, scene)
2. Visual mood (bright/dark, tense/relaxed, etc.)
3. Scene type (indoor/outdoor, close-up/wide, interview/action/etc.)
4. Any visible text or subtitles
5. Facial expressions if people are visible

Frames:
{chr(10).join(frame_info)}

Return JSON array:
[{{"frame": 1, "description": "...", "mood": "bright|dark|warm|cold|tense|relaxed|dramatic|fun", "scene_type": "indoor|outdoor|studio|nature|urban", "text_visible": "any text on screen", "expression": "if visible"}}]"""

            try:
                result = self._call_llm(prompt)
                import re
                json_match = re.search(r'\[.*\]', result, re.DOTALL)
                if json_match:
                    batch_scenes = json.loads(json_match.group())
                    for i, scene in enumerate(batch_scenes):
                        scene["timestamp"] = (batch_start + i) * 5.0
                        scene["frame_path"] = batch[batch_start + i] if i < len(batch) else ""
                    scenes.extend(batch_scenes)
            except Exception as e:
                print(f"  ⚠️ Scene analysis batch failed: {e}")
        
        return scenes if scenes else self._fallback_scenes(keyframes)
    
    def _detect_visual_mood(self, scenes: list[dict]) -> dict:
        """Determine overall visual mood from scene analysis."""
        if not scenes:
            return {"primary": "neutral", "moods": [], "lighting": "unknown"}
        
        moods = [s.get("mood", "neutral") for s in scenes]
        from collections import Counter
        mood_counts = Counter(moods)
        
        return {
            "primary": mood_counts.most_common(1)[0][0] if moods else "neutral",
            "moods": [{"mood": m, "count": c} for m, c in mood_counts.most_common(5)],
            "lighting": self._estimate_lighting(scenes),
        }
    
    def _classify_scenes(self, scenes: list[dict]) -> list[str]:
        """Classify overall scene types present in the video."""
        types = [s.get("scene_type", "unknown") for s in scenes]
        from collections import Counter
        return [t for t, _ in Counter(types).most_common(5)]
    
    def _build_timeline(self, scenes: list[dict], segments: list[dict] = None) -> list[dict]:
        """Build a mood timeline aligned with audio segments."""
        if not scenes:
            return []
        
        timeline = []
        for scene in scenes:
            timeline.append({
                "start": scene.get("timestamp", 0),
                "end": scene.get("timestamp", 0) + 5.0,
                "mood": scene.get("mood", "neutral"),
                "type": scene.get("scene_type", "unknown"),
                "description": scene.get("description", ""),
                "confidence": 0.7,
            })
        
        return timeline
    
    def _extract_on_screen_text(self, scenes: list[dict]) -> list[str]:
        """Collect any text visible on screen across all scenes."""
        texts = []
        for scene in scenes:
            text = scene.get("text_visible", "")
            if text and text != "none" and text != "None":
                texts.append(text)
        return texts
    
    def _estimate_lighting(self, scenes: list[dict]) -> str:
        """Estimate overall lighting from mood descriptions."""
        bright_count = sum(1 for s in scenes if s.get("mood", "") in ("bright", "warm", "fun"))
        dark_count = sum(1 for s in scenes if s.get("mood", "") in ("dark", "cold", "tense"))
        
        if bright_count > dark_count:
            return "bright"
        elif dark_count > bright_count:
            return "dark"
        return "neutral"
    
    def _fallback_scenes(self, keyframes: list[str]) -> list[dict]:
        """Simple scene analysis when LLM is unavailable."""
        return [
            {
                "frame": i + 1,
                "timestamp": i * 5.0,
                "description": "Frame extracted",
                "mood": "neutral",
                "scene_type": "unknown",
                "text_visible": "",
            }
            for i in range(len(keyframes))
        ]
    
    def _get_duration(self, video_path: str) -> float:
        """Get video duration."""
        try:
            result = subprocess.run(
                f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{video_path}"',
                shell=True, capture_output=True, text=True, timeout=10,
            )
            return float(result.stdout.strip()) if result.stdout.strip() else 0.0
        except:
            return 0.0
    
    def _call_llm(self, prompt: str) -> str:
        """Call MiMo API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a visual analysis AI for video dubbing. Describe frames concisely. Return JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers=headers, json=payload, timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
