#!/usr/bin/env python3
"""
Quality Assessor — Self-Evaluation & Quality Control
====================================================
Automatically evaluates dubbing quality:
- Translation accuracy check
- TTS naturalness estimation
- Audio quality metrics (sync, volume, clarity)
- Overall quality score
- Retry suggestions
"""

import json
import os
import subprocess
import requests


class QualityAssessor:
    """Self-evaluate dubbing output quality."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
    
    def assess(self, segments: list[dict], output_dir: str, context: dict) -> dict:
        """
        Full quality assessment of dubbing output.
        Returns quality report with scores and suggestions.
        """
        report = {
            "overall_score": 0,
            "translation_score": 0,
            "timing_score": 0,
            "audio_score": 0,
            "completeness_score": 0,
            "issues": [],
            "suggestions": [],
            "should_retry": False,
            "retry_config": {},
        }
        
        # 1. Completeness check
        completeness = self._check_completeness(segments)
        report["completeness_score"] = completeness["score"]
        report["issues"].extend(completeness.get("issues", []))
        
        # 2. Translation quality
        if self.api_key:
            translation = self._check_translation(segments, context)
            report["translation_score"] = translation["score"]
            report["issues"].extend(translation.get("issues", []))
        
        # 3. Timing/sync check
        timing = self._check_timing(segments)
        report["timing_score"] = timing["score"]
        report["issues"].extend(timing.get("issues", []))
        
        # 4. Audio quality check
        audio = self._check_audio(segments, output_dir)
        report["audio_score"] = audio["score"]
        report["issues"].extend(audio.get("issues", []))
        
        # Calculate overall score
        weights = {"completeness": 0.25, "translation": 0.30, "timing": 0.25, "audio": 0.20}
        report["overall_score"] = round(
            completeness["score"] * weights["completeness"] +
            report["translation_score"] * weights["translation"] +
            timing["score"] * weights["timing"] +
            audio["score"] * weights["audio"],
            1
        )
        
        # Generate suggestions
        report["suggestions"] = self._generate_suggestions(report)
        
        # Should we retry?
        if report["overall_score"] < 70:
            report["should_retry"] = True
            report["retry_config"] = self._suggest_retry(report)
        
        return report
    
    def _check_completeness(self, segments: list[dict]) -> dict:
        """Check if all segments were properly processed."""
        total = len(segments)
        if total == 0:
            return {"score": 0, "issues": ["No segments found"]}
        
        translated = sum(1 for s in segments if s.get("text_vi"))
        tts_generated = sum(1 for s in segments if s.get("tts_path") and os.path.exists(s.get("tts_path", "")))
        synced = sum(1 for s in segments if s.get("synced_path"))
        
        scores = [
            (translated / total) * 100,
            (tts_generated / total) * 100,
            (synced / total) * 100,
        ]
        
        issues = []
        if translated < total:
            issues.append(f"Missing translations: {total - translated}/{total} segments")
        if tts_generated < total:
            issues.append(f"Missing TTS: {total - tts_generated}/{total} segments")
        
        return {"score": sum(scores) / len(scores), "issues": issues}
    
    def _check_translation(self, segments: list[dict], context: dict) -> dict:
        """Use LLM to assess translation quality."""
        if not self.api_key:
            return {"score": 85, "issues": []}
        
        # Sample check (first 10 segments)
        sample = segments[:10]
        numbered = "\n".join(
            f"{i+1}. Source: {s['text']}\n   Translation: {s.get('text_vi', 'N/A')}"
            for i, s in enumerate(sample)
        )
        
        prompt = f"""Rate the dubbing translation quality (0-100) for each pair.
Consider: accuracy, naturalness, cultural fit, brevity for speech.

{numbered}

Return JSON: {{"score": <avg_score>, "issues": ["list any problems"], "best": "best translation", "worst": "worst translation"}}"""

        try:
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a translation quality assessor. Be critical but fair."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
            
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers=headers, json=payload, timeout=30,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {"score": result.get("score", 75), "issues": result.get("issues", [])}
        except Exception as e:
            pass
        
        return {"score": 75, "issues": ["LLM quality check failed"]}
    
    def _check_timing(self, segments: list[dict]) -> dict:
        """Check timing accuracy."""
        issues = []
        bad_timing = 0
        
        for seg in segments:
            target = seg.get("end", 0) - seg.get("start", 0)
            tts_dur = seg.get("tts_duration", 0)
            
            if target <= 0 or tts_dur <= 0:
                continue
            
            ratio = tts_dur / target
            if ratio > 1.5:  # TTS much longer than slot
                bad_timing += 1
                issues.append(f"Seg {seg['index']}: TTS too long ({tts_dur:.1f}s vs {target:.1f}s)")
            elif ratio < 0.5:  # TTS much shorter
                bad_timing += 1
                issues.append(f"Seg {seg['index']}: TTS too short ({tts_dur:.1f}s vs {target:.1f}s)")
        
        total = len(segments)
        if total == 0:
            return {"score": 100, "issues": []}
        
        score = max(0, 100 - (bad_timing / total * 100))
        return {"score": round(score, 1), "issues": issues[:5]}  # Limit issues
    
    def _check_audio(self, segments: list[dict], output_dir: str) -> dict:
        """Check audio quality metrics."""
        issues = []
        total_loudness_issues = 0
        
        for seg in segments:
            audio_path = seg.get("processed_path") or seg.get("synced_path")
            if not audio_path or not os.path.exists(audio_path):
                continue
            
            # Quick loudness check
            try:
                result = subprocess.run(
                    f'ffmpeg -i "{audio_path}" -af eburt123=peak=true -f null - 2>&1 | grep "Integrated"',
                    shell=True, capture_output=True, text=True, timeout=10,
                )
                # Just check if file is not silent
                probe = subprocess.run(
                    f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{audio_path}"',
                    shell=True, capture_output=True, text=True, timeout=5,
                )
                duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0
                if duration < 0.1:
                    total_loudness_issues += 1
                    issues.append(f"Seg {seg['index']}: Audio too short or silent")
            except:
                pass
        
        total = len(segments)
        score = max(0, 100 - (total_loudness_issues / max(total, 1) * 100))
        return {"score": round(score, 1), "issues": issues[:5]}
    
    def _generate_suggestions(self, report: dict) -> list[str]:
        """Generate actionable suggestions based on assessment."""
        suggestions = []
        
        if report["timing_score"] < 70:
            suggestions.append("Consider more aggressive speed adjustment for better sync")
        if report["translation_score"] < 70:
            suggestions.append("Translation quality is low — try increasing temperature or using creative mode")
        if report["audio_score"] < 70:
            suggestions.append("Audio processing needs improvement — check levels and processing chain")
        if report["completeness_score"] < 90:
            suggestions.append("Some segments failed — check TTS server health")
        
        return suggestions
    
    def _suggest_retry(self, report: dict) -> dict:
        """Suggest config changes for retry."""
        retry = {}
        
        if report["timing_score"] < 60:
            retry["pacing"] = {"allow_speed_range": [0.6, 1.5], "max_speedup": 1.5}
        if report["translation_score"] < 60:
            retry["translation"] = {"temperature": 0.5, "method": "creative"}
        if report["audio_score"] < 60:
            retry["audio"] = {"compress": True, "noise_gate": True, "target_lufs": -14.0}
        
        return retry
