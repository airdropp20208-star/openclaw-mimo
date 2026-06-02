#!/usr/bin/env python3
"""
Meta-Cognition — Self-Awareness + Verification
===============================================
The brain questions ITSELF:
- "Am I sure about this translation?"
- "My confidence is low — should I verify?"
- "I detected anger but the context says comedy — check again"
- "This segment failed 3 times — I need a different approach"
- Monitors its OWN reasoning for contradictions

This is the difference between a tool and an intelligence:
A tool outputs and moves on. An intelligence DOUBTS itself.
"""

import json
import re
import requests


class MetaCognition:
    """Self-monitoring, confidence estimation, and verification."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.doubt_log = []  # Track when the brain doubted itself
        self.verification_results = []  # Track verification outcomes
    
    def estimate_confidence(self, result: dict, source: str, context: dict = None) -> dict:
        """
        Estimate how confident we should be in a result.
        Returns confidence score + whether verification is needed.
        """
        confidence = 0.5  # Base confidence
        needs_verification = False
        reasons = []
        
        # Factor 1: Source quality — was this from LLM or rule-based?
        if result.get("from_llm"):
            confidence += 0.15
        elif result.get("from_rules"):
            confidence -= 0.1
        
        # Factor 2: Consistency — does this match what we know?
        if context:
            ctx_genre = context.get("genre", "")
            detected_emotion = result.get("emotion", result.get("emotion_detected", ""))
            
            # Genre-emotion consistency check
            if ctx_genre == "news" and detected_emotion in ("excited", "happy"):
                confidence -= 0.2
                reasons.append(f"Emotion '{detected_emotion}' unusual for news")
                needs_verification = True
            elif ctx_genre == "comedy" and detected_emotion == "sad":
                confidence -= 0.15
                reasons.append(f"Sadness unusual for comedy")
                needs_verification = True
        
        # Factor 3: Translation length — too long or too short?
        if "translation" in result:
            trans = result["translation"]
            source_text = source
            if len(trans) > len(source_text) * 2:
                confidence -= 0.15
                reasons.append("Translation much longer than source")
                needs_verification = True
            elif len(trans) < len(source_text) * 0.3:
                confidence -= 0.1
                reasons.append("Translation much shorter than source")
        
        # Factor 4: Multiple alternatives available
        if result.get("alternatives") and len(result.get("alternatives", [])) > 1:
            confidence += 0.05  # Having options increases confidence
        
        # Factor 5: Previous failures on this segment
        if context and context.get("previous_failures", 0) > 0:
            confidence -= 0.1 * context["previous_failures"]
            reasons.append(f"Failed {context['previous_failures']} times before")
            needs_verification = True
        
        confidence = max(0.0, min(1.0, confidence))
        
        # Always verify if confidence < 0.5
        if confidence < 0.5:
            needs_verification = True
            reasons.append("Overall confidence too low")
        
        return {
            "confidence": round(confidence, 2),
            "needs_verification": needs_verification,
            "reasons": reasons,
            "recommendation": "verify" if needs_verification else "proceed",
        }
    
    def verify_translation(self, source: str, translation: str, context: dict = None) -> dict:
        """
        Cross-check a translation against multiple criteria.
        Like a human translator double-checking their work.
        """
        issues = []
        score = 100
        
        # Check 1: Length ratio
        ratio = len(translation) / max(len(source), 1)
        if ratio > 2.5:
            issues.append("Too long — will be hard to speak in the time slot")
            score -= 20
        elif ratio < 0.2:
            issues.append("Too short — meaning might be lost")
            score -= 15
        elif ratio < 0.4 or ratio > 1.8:
            issues.append(f"Unusual length ratio ({ratio:.1f}x)")
            score -= 5
        
        # Check 2: Repeated words
        words = translation.split()
        if len(words) > 3:
            from collections import Counter
            repeats = Counter(words).most_common(1)
            if repeats[0][1] > len(words) * 0.3:
                issues.append("Too many repeated words — sounds unnatural")
                score -= 15
        
        # Check 3: Sentence structure
        if translation.count("?") > 2 and source.count("?") < 2:
            issues.append("More questions than source — might be wrong tone")
            score -= 10
        
        # Check 4: Untranslated content
        # Check if source has non-ASCII but translation doesn't (possible missed translation)
        has_source_chars = any(0x4e00 <= ord(c) <= 0x9fff for c in source)
        has_trans_chars = any(0x4e00 <= ord(c) <= 0x9fff for c in translation)
        if has_source_chars and not has_trans_chars:
            pass  # Good — translated to non-Chinese
        elif has_source_chars and has_trans_chars:
            issues.append("Translation still contains Chinese characters")
            score -= 25
        
        # Check 5: LLM verification (if available and needed)
        llm_check = {}
        if self.api_key and score < 80:
            llm_check = self._llm_verify(source, translation, context)
            if llm_check.get("issues"):
                issues.extend(llm_check["issues"])
                score -= 10
        
        self.verification_results.append({
            "source": source[:50],
            "translation": translation[:50],
            "score": max(0, score),
            "issues": issues,
        })
        
        return {
            "score": max(0, score),
            "issues": issues,
            "pass": score >= 70,
            "llm_feedback": llm_check.get("feedback", ""),
        }
    
    def detect_contradiction(self, statement_a: str, statement_b: str) -> dict:
        """
        Detect if two statements contradict each other.
        Important for maintaining consistent translations.
        """
        if not self.api_key:
            return {"contradicts": False, "confidence": 0.3}
        
        try:
            prompt = f"""Do these two statements contradict each other?

A: "{statement_a}"
B: "{statement_b}"

Return JSON: {{"contradicts": true/false, "explanation": "...", "confidence": 0.0-1.0}}"""
            
            result = self._call_llm(prompt, 0.1)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {"contradicts": False, "confidence": 0.3}
    
    def doubt(self, situation: str, confidence: float, context: dict = None):
        """
        Express doubt about a result.
        The brain recognizes when it might be wrong.
        """
        self.doubt_log.append({
            "situation": situation,
            "confidence": confidence,
            "context": context,
        })
    
    def should_retry(self, step: str, error: str, attempt: int) -> dict:
        """
        Decide if we should retry and HOW.
        Not just "retry same thing" — but "retry differently."
        """
        max_attempts = 3
        
        if attempt >= max_attempts:
            return {
                "retry": False,
                "reason": f"Failed {attempt} times — need different approach or give up",
                "strategy": "give_up_or_fallback",
            }
        
        # Analyze the error to determine retry strategy
        error_lower = error.lower()
        
        if "parse" in error_lower or "format" in error_lower:
            strategy = "simplify_prompt"  # The LLM didn't follow format
        elif "timeout" in error_lower:
            strategy = "increase_timeout"
        elif "empty" in error_lower or "no output" in error_lower:
            strategy = "rephrase_prompt"
        elif "rate" in error_lower:
            strategy = "wait_and_retry"
        else:
            strategy = "retry_with_context"  # Add more context to help
        
        return {
            "retry": True,
            "strategy": strategy,
            "attempt": attempt + 1,
            "max_attempts": max_attempts,
            "adjustments": self._get_retry_adjustments(strategy, attempt),
        }
    
    def _get_retry_adjustments(self, strategy: str, attempt: int) -> dict:
        """Get specific adjustments for retry."""
        adjustments = {}
        
        if strategy == "simplify_prompt":
            adjustments["temperature"] = 0.1  # More precise
            adjustments["simplify"] = True
        elif strategy == "increase_timeout":
            adjustments["timeout_multiplier"] = 2
        elif strategy == "rephrase_prompt":
            adjustments["add_examples"] = True
            adjustments["temperature"] = 0.2
        elif strategy == "wait_and_retry":
            adjustments["wait_seconds"] = 30 * (attempt + 1)
        elif strategy == "retry_with_context":
            adjustments["add_context"] = True
            adjustments["temperature"] = 0.4
        
        return adjustments
    
    def self_audit(self, pipeline_state: dict) -> dict:
        """
        Full self-audit of the current pipeline state.
        Check for inconsistencies, missing data, potential issues.
        """
        issues = []
        warnings = []
        
        segments = pipeline_state.get("segments", [])
        for i, seg in enumerate(segments):
            # Check: translation exists?
            if not seg.get("text_vi"):
                issues.append(f"Segment {i}: Missing translation")
            
            # Check: TTS generated?
            if seg.get("text_vi") and not seg.get("tts_path"):
                issues.append(f"Segment {i}: Has translation but no TTS")
            
            # Check: Timing consistency
            if seg.get("tts_duration", 0) > 0 and seg.get("end", 0) > 0:
                target = seg["end"] - seg.get("start", 0)
                if seg["tts_duration"] > target * 2:
                    warnings.append(f"Segment {i}: TTS much longer than slot ({seg['tts_duration']:.1f}s vs {target:.1f}s)")
            
            # Check: Emotion consistency
            if i > 0:
                prev_emo = segments[i-1].get("emotion", "neutral")
                curr_emo = seg.get("emotion", "neutral")
                if prev_emo != curr_emo and seg.get("emotion") == "neutral":
                    warnings.append(f"Segment {i}: Emotion reset to neutral after {prev_emo}")
        
        return {
            "issues": issues,
            "warnings": warnings,
            "health": "good" if not issues else ("warning" if not warnings else "critical"),
            "completeness": sum(1 for s in segments if s.get("text_vi")) / max(len(segments), 1),
        }
    
    def _llm_verify(self, source: str, translation: str, context: dict) -> dict:
        """LLM verification of translation quality."""
        try:
            prompt = f"""Quick quality check on this translation:
Source: "{source}"
Translation: "{translation}"

Is this a good translation for video dubbing? Any problems?
Return JSON: {{"score": 0-100, "issues": ["list"], "feedback": "brief comment"}}"""
            
            result = self._call_llm(prompt, 0.2)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        return {}
    
    def _call_llm(self, prompt: str, temperature: float = 0.2) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a quality assurance expert. Be precise and critical. Return JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        resp = requests.post(f"{self.api_base}/chat/completions", headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
