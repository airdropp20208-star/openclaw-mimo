#!/usr/bin/env python3
"""
Intelligence Core — Central Neural Hub
=======================================
Connects ALL brain modules into ONE tightly coupled system.
Every module feeds into and receives from every other module.

Flow:
  World Model → Causal Understanding → Deep Reasoning
       ↓                                       ↓
  Anticipation ← Narrative Analysis ← Emotion System
       ↓                                       ↓
  Strategy Engine ← Meta-Cognition ← Quality Intelligence
       ↓                                       ↓
  Output: Human-like dubbing decisions

This is the BRAIN. Everything else is a neuron.
"""

import json
import time


class IntelligenceCore:
    """
    Central hub that connects all intelligence modules.
    NOT a collection of tools — ONE integrated mind.
    """
    
    def __init__(self, mimo_api_key: str = "", mimo_api_base: str = "", mimo_model: str = "mimo-v2.5-pro"):
        self.api_key = mimo_api_key
        self.api_base = mimo_api_base
        self.model = mimo_model
        
        # Lazy-import to avoid circular deps
        self._modules = {}
        self._initialized = False
    
    def _init_modules(self):
        """Initialize all modules (lazy to avoid import cycles)."""
        if self._initialized:
            return
        
        from .world_model import WorldModel
        from .meta_cognition import MetaCognition
        from .anticipation import AnticipationNetwork
        from .context_engine import ContextEngine
        from .emotion_detector import EmotionDetector
        from .emotional_continuity import EmotionalContinuity
        from .adaptive_engine import AdaptiveEngine
        from .proactive_recovery import ProactiveRecovery
        from .human_thinker import HumanThinker
        from .quality_assessor import QualityAssessor
        from .scene_understander import SceneUnderstander
        
        self._modules = {
            "world": WorldModel(self.api_key, self.api_base, self.model),
            "meta": MetaCognition(self.api_key, self.api_base, self.model),
            "anticipation": AnticipationNetwork(self.api_key, self.api_base, self.model),
            "context": ContextEngine(self.api_key, self.api_base, self.model),
            "emotion": EmotionDetector(self.api_key, self.api_base, self.model),
            "continuity": EmotionalContinuity(),
            "adaptive": AdaptiveEngine(),
            "recovery": ProactiveRecovery(self.api_key, self.api_base, self.model),
            "thinker": HumanThinker(self.api_key, self.api_base, self.model),
            "quality": QualityAssessor(self.api_key, self.api_base, self.model),
            "scene": SceneUnderstander(self.api_key, self.api_base, self.model),
        }
        self._initialized = True
    
    def get(self, name: str):
        """Access a module by name."""
        self._init_modules()
        return self._modules.get(name)
    
    # ═════════════════════════════════════════════════════════════════
    # PHASE 1: UNDERSTAND — Analyze everything before acting
    # ═════════════════════════════════════════════════════════════════
    
    def understand(self, segments: list[dict], source_lang: str, target_lang: str, 
                   video_path: str = None) -> dict:
        """
        FULL understanding pass. Analyzes EVERYTHING before any action.
        
        Returns a unified understanding object that all downstream
        modules consume.
        """
        self._init_modules()
        start = time.time()
        
        understanding = {
            "segments": segments,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "timestamp": time.time(),
        }
        
        # 1. Deep context analysis (what is this content?)
        ctx = self._modules["context"].analyze(
            "\n".join(s["text"] for s in segments), source_lang, target_lang
        )
        understanding["context"] = ctx
        
        # 2. Causal understanding (WHY do speakers say this?)
        for seg in segments:
            cause = self._modules["world"].understand_cause(seg["text"], source_lang, ctx)
            seg["cause"] = cause
            seg["speaker_intent"] = cause.get("speaker_intent", "")
        
        # 3. Emotion detection with causality
        for seg in segments:
            emotion = self._modules["emotion"].detect_from_text(seg["text"], ctx, source_lang)
            seg["emotion"] = emotion
            
            # Enhance with causal context
            if seg.get("cause", {}).get("emotion"):
                cause_emotion = seg["cause"]["emotion"]
                if cause_emotion != "neutral" and emotion == "neutral":
                    seg["emotion"] = cause_emotion  # Causality overrides surface
        
        # 4. Emotional continuity (smooth the arc)
        arc = self._modules["continuity"].build_arc(segments, ctx)
        understanding["emotional_arc"] = arc
        segments = self._modules["continuity"].apply_arc(segments, arc)
        understanding["segments"] = segments
        
        # 5. Narrative anticipation (what's coming next?)
        narrative = self._modules["anticipation"].analyze_narrative(segments, ctx)
        understanding["narrative"] = narrative
        
        # 6. Scene understanding (if video available)
        if video_path:
            try:
                scenes = self._modules["scene"].analyze_video(video_path, segments)
                understanding["scenes"] = scenes
            except:
                understanding["scenes"] = {}
        
        # 7. Cultural bridging
        cultural = self._modules["world"].bridge_culture(
            "\n".join(s["text"] for s in segments[:20]), source_lang, target_lang, ctx
        )
        understanding["cultural"] = cultural
        
        # 8. Adaptive strategy (what worked before for this type?)
        adaptive = self._modules["adaptive"].get_optimized_strategy(
            ctx.get("genre", "unknown"), source_lang, target_lang
        )
        understanding["adaptive_strategy"] = adaptive
        
        # 9. Meta-cognition: check understanding consistency
        meta_check = self._modules["meta"].self_audit({"segments": segments})
        understanding["meta_audit"] = meta_check
        
        understanding["understand_time"] = time.time() - start
        return understanding
    
    # ═════════════════════════════════════════════════════════════════
    # PHASE 2: THINK — Reason about translation decisions
    # ═════════════════════════════════════════════════════════════════
    
    def think_translation(self, segments: list[dict], understanding: dict) -> list[dict]:
        """
        Think about HOW to translate each segment.
        Uses understanding to make human-like decisions.
        """
        self._init_modules()
        
        ctx = understanding.get("context", {})
        narrative = understanding.get("narrative", {})
        cultural = understanding.get("cultural", {})
        adaptive = understanding.get("adaptive_strategy", {})
        
        # Determine translation temperature from strategy
        temp = adaptive.get("translation_temperature", 0.3)
        method = adaptive.get("translation_method", "adaptive")
        
        # Build enhanced system prompt
        genre = ctx.get("genre", "unknown")
        humor = ctx.get("humor_type", "none")
        
        system = self._build_translation_system(ctx, cultural, method)
        
        # Prepare numbered text
        numbered = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(segments))
        
        # Context enrichment
        context_lines = []
        if cultural.get("gaps"):
            context_lines.append(f"Cultural refs to bridge: {json.dumps(cultural['gaps'][:3], ensure_ascii=False)}")
        if narrative.get("structure"):
            context_lines.append(f"Narrative structure: {narrative['structure'].get('type', '?')}")
        if humor != "none":
            context_lines.append(f"Humor type: {humor} — recreate the joke in Vietnamese!")
        
        context_str = "\n".join(context_lines)
        
        prompt = f"""Translate this {understanding['source_lang']}→{understanding['target_lang']} dialogue for VIDEO DUBBING.
These translations will be SPOKEN by a voice actor — they must sound NATURAL.

{context_str}

RULES:
1. Translate MEANING + FEELING, not just words
2. Match the emotion of each line
3. Keep sentences short enough to speak in the time slot
4. For humor: recreate the joke, don't translate literally
5. For cultural refs: bridge the gap for Vietnamese audience
6. The speaker's INTENT matters more than literal meaning

{numbered}

Return ONLY the numbered translations:"""
        
        return {
            "system_prompt": system,
            "user_prompt": prompt,
            "temperature": temp,
            "method": method,
        }
    
    def _build_translation_system(self, ctx: dict, cultural: dict, method: str) -> str:
        """Build the system prompt for translation."""
        genre = ctx.get("genre", "casual")
        formality = ctx.get("formality", "casual")
        audience = ctx.get("target_audience", "general")
        
        parts = [
            f"You are a world-class translator for {genre} video dubbing.",
            f"Formality level: {formality}. Audience: {audience}.",
            "You think like a HUMAN — understanding context, emotion, humor, and culture.",
            "You translate MEANING, not just words.",
        ]
        
        if method == "creative":
            parts.append("Approach: CREATIVE — prioritize naturalness and entertainment value.")
        elif method == "adaptive":
            parts.append("Approach: ADAPTIVE — balance accuracy with naturalness.")
        else:
            parts.append("Approach: PRECISE — prioritize accuracy while keeping it speakable.")
        
        prefs = cultural.get("target_preferences", {})
        if prefs.get("translate_proverbs") == "find Vietnamese equivalent":
            parts.append("For proverbs/idioms: find the Vietnamese equivalent, not a literal translation.")
        if prefs.get("humor") == "recreate the joke in Vietnamese style":
            parts.append("For humor: recreate the joke in Vietnamese style, not literal translation.")
        
        return " ".join(parts)
    
    # ═════════════════════════════════════════════════════════════════
    # PHASE 3: REFINE — Review and improve
    # ═════════════════════════════════════════════════════════════════
    
    def refine_translations(self, segments: list[dict], understanding: dict) -> list[dict]:
        """
        Post-translation refinement using all brain modules.
        Reviews translations through multiple lenses.
        """
        self._init_modules()
        
        narrative = understanding.get("narrative", {})
        meta = self._modules["meta"]
        
        # 1. Verify each translation
        for seg in segments:
            if seg.get("text") and seg.get("text_vi"):
                verification = meta.verify_translation(seg["text"], seg["text_vi"], understanding.get("context"))
                seg["translation_score"] = verification.get("score", 50)
                seg["translation_issues"] = verification.get("issues", [])
                
                # 2. Check confidence
                confidence = meta.estimate_confidence(
                    {"translation": seg["text_vi"], "emotion_detected": seg.get("emotion")},
                    seg["text"],
                    understanding.get("context"),
                )
                seg["confidence"] = confidence.get("confidence", 0.5)
                
                # 3. If low confidence, use HumanThinker to improve
                if confidence.get("needs_verification") and self.api_key:
                    thinking = self._modules["thinker"].think_translation(
                        seg["text"], understanding["source_lang"], understanding["target_lang"],
                        understanding.get("context")
                    )
                    if thinking.get("translation"):
                        better = thinking["translation"]
                        if len(better) > 0 and better != seg["text_vi"]:
                            seg["text_vi_original"] = seg["text_vi"]
                            seg["text_vi"] = better
                            seg["refined"] = True
                            seg["refinement_reason"] = "Low confidence — HumanThinker improved"
        
        # 4. Check narrative consistency
        for i, seg in enumerate(segments):
            if i > 0 and seg.get("emotion") and segments[i-1].get("emotion"):
                if seg["emotion"] != segments[i-1]["emotion"]:
                    # Check anticipation — is this shift expected?
                    prep = self._modules["anticipation"].get_preparation(i, narrative)
                    if not prep.get("approaching_turn") and not prep.get("approaching_peak"):
                        # Unexpected shift — might need moderation
                        seg["emotion_note"] = "Unexpected emotion shift"
        
        return segments
    
    # ═════════════════════════════════════════════════════════════════
    # PHASE 4: ASSESS — Final quality check
    # ═════════════════════════════════════════════════════════════════
    
    def assess(self, segments: list[dict], output_dir: str, understanding: dict) -> dict:
        """
        Final quality assessment using all brain modules together.
        """
        self._init_modules()
        
        # 1. Quality score
        quality = self._modules["quality"].assess(segments, output_dir, understanding)
        
        # 2. Meta-audit
        audit = self._modules["meta"].self_audit({"segments": segments})
        
        # 3. Emotional consistency check
        emotion_consistent = True
        for i in range(1, len(segments)):
            if segments[i].get("emotion") != segments[i-1].get("emotion"):
                # Check if shift is expected in the narrative
                narrative = understanding.get("narrative", {})
                peaks = narrative.get("peaks", [])
                tp = narrative.get("turning_points", [])
                
                expected = any(
                    abs(p.get("segment_index", 0) - i) <= 2
                    for p in peaks + tp
                )
                if not expected:
                    emotion_consistent = False
        
        # 4. Translation quality distribution
        scores = [s.get("translation_score", 50) for s in segments if s.get("translation_score")]
        avg_translation = sum(scores) / max(len(scores), 1)
        
        # Combine all assessments
        overall = (
            quality.get("overall_score", 50) * 0.4 +
            (100 if audit["health"] == "good" else 60 if audit["health"] == "warning" else 30) * 0.2 +
            (100 if emotion_consistent else 70) * 0.2 +
            avg_translation * 0.2
        )
        
        return {
            "overall_score": round(overall, 1),
            "quality_detail": quality,
            "meta_audit": audit,
            "emotion_consistent": emotion_consistent,
            "avg_translation_score": round(avg_translation, 1),
            "refined_count": sum(1 for s in segments if s.get("refined")),
            "should_retry": overall < 65,
        }
    
    # ═════════════════════════════════════════════════════════════════
    # PHASE 5: LEARN — Record and adapt
    # ═════════════════════════════════════════════════════════════════
    
    def learn(self, job_result: dict, understanding: dict, assessment: dict):
        """
        Record everything this job taught us.
        """
        self._init_modules()
        
        # Record in adaptive engine
        strategy = understanding.get("adaptive_strategy", {})
        strategy["genre"] = understanding.get("context", {}).get("genre", "unknown")
        self._modules["adaptive"].record_result(
            {
                "quality_score": assessment.get("overall_score", 0),
                "source_lang": understanding.get("source_lang", ""),
                "target_lang": understanding.get("target_lang", ""),
            },
            strategy,
        )
    
    # ═════════════════════════════════════════════════════════════════
    # ERROR RECOVERY
    # ═════════════════════════════════════════════════════════════════
    
    def diagnose_error(self, error: str, step: str, context: dict = None) -> dict:
        """Smart error diagnosis."""
        self._init_modules()
        return self._modules["recovery"].diagnose(error, step, context)
    
    def should_retry(self, step: str, error: str, attempt: int) -> dict:
        """Should we retry? And how?"""
        self._init_modules()
        return self._modules["meta"].should_retry(step, error, attempt)
