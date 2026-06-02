#!/usr/bin/env python3
"""
AGI Brain — Intelligence Layer for OpenClaw MiMo
=================================================
Adds reasoning, emotion detection, strategy selection,
quality assessment, and self-learning to the dubbing pipeline.

Modules:
- ContextEngine: Deep semantic understanding of dialogue
- EmotionDetector: Multi-modal emotion analysis (audio + text)
- StrategySelector: Auto-select dubbing approach per scene
- QualityAssessor: Self-evaluate output quality
- SelfLearner: Learn from user feedback over time
"""

from .context_engine import ContextEngine
from .emotion_detector import EmotionDetector
from .strategy_selector import StrategySelector
from .quality_assessor import QualityAssessor
from .self_learner import SelfLearner
from .human_thinker import HumanThinker
from .scene_understander import SceneUnderstander
from .adaptive_engine import AdaptiveEngine
from .proactive_recovery import ProactiveRecovery
from .emotional_continuity import EmotionalContinuity
from .autonomous_planner import AutonomousPlanner

class AGIBrain:
    """
    Central brain that orchestrates all intelligence modules.
    Replaces the fixed pipeline with adaptive, reasoning-based processing.
    """
    
    def __init__(self, mimo_api_key: str = "", mimo_api_base: str = "", mimo_model: str = "mimo-v2.5-pro"):
        self.context = ContextEngine(mimo_api_key, mimo_api_base, mimo_model)
        self.emotion = EmotionDetector(mimo_api_key, mimo_api_base, mimo_model)
        self.strategy = StrategySelector(self.context, self.emotion)
        self.quality = QualityAssessor(mimo_api_key, mimo_api_base, mimo_model)
        self.learner = SelfLearner()
        self.thinker = HumanThinker(mimo_api_key, mimo_api_base, mimo_model)
        self.scene = SceneUnderstander(mimo_api_key, mimo_api_base, mimo_model)
        self.adaptive = AdaptiveEngine()
        self.recovery = ProactiveRecovery(mimo_api_key, mimo_api_base, mimo_model)
        self.emotional = EmotionalContinuity()
        self.planner = AutonomousPlanner(self)
    
    def analyze(self, segments: list[dict], source_lang: str, target_lang: str) -> dict:
        """
        Full brain analysis before translation.
        Returns enriched context for the pipeline.
        """
        # 1. Deep context analysis
        full_text = "\n".join(s["text"] for s in segments)
        context = self.context.analyze(full_text, source_lang, target_lang)
        
        # 2. Emotion analysis per segment
        for seg in segments:
            seg["emotion"] = self.emotion.detect_from_text(seg["text"], context)
        
        # 3. Global emotion arc
        emotion_arc = self.emotion.compute_arc(segments)
        context["emotion_arc"] = emotion_arc
        
        # 4. Select strategy
        strategy = self.strategy.select(segments, context)
        
        return {
            "context": context,
            "strategy": strategy,
            "emotion_arc": emotion_arc,
        }
    
    def post_translate(self, segments: list[dict], context: dict) -> list[dict]:
        """
        After translation: refine based on context understanding.
        Adjusts emotions, pacing, and cultural adaptation.
        """
        # Apply emotion arc to segments
        emotion_arc = context.get("emotion_arc", {})
        
        for seg in segments:
            # Match emotion to arc position
            pos = seg["start"] / max(emotion_arc.get("total_duration", 1), 0.01)
            dominant = self._get_emotion_at_pos(emotion_arc, pos)
            if dominant and seg.get("emotion") == "neutral":
                seg["emotion"] = dominant
            seg["emotion"] = seg.get("emotion", "neutral")
        
        # Cultural adaptation pass
        strategy = context.get("strategy", {})
        if strategy.get("cultural_adapt", True):
            segments = self.context.cultural_adapt(segments, target_lang="Vietnamese")
        
        return segments
    


    def create_plan(self, task: dict) -> dict:
        """Autonomously plan the entire dubbing approach."""
        return self.planner.create_plan(task)
    
    def understand_scene(self, video_path: str, segments: list[dict] = None) -> dict:
        """Multi-modal scene understanding — see the video like a human."""
        return self.scene.analyze_video(video_path, segments)
    
    def build_emotional_arc(self, segments: list[dict], context: dict = None) -> dict:
        """Build consistent emotional arc for the entire video."""
        return self.emotional.build_arc(segments, context)
    
    def apply_emotional_arc(self, segments: list[dict], arc: dict) -> list[dict]:
        """Apply emotional arc to segments for smooth flow."""
        return self.emotional.apply_arc(segments, arc)
    
    def get_adaptive_strategy(self, genre: str, source_lang: str, target_lang: str) -> dict:
        """Get self-optimized strategy based on past learning."""
        return self.adaptive.get_optimized_strategy(genre, source_lang, target_lang)
    
    def record_job_result(self, job_result: dict, strategy: dict):
        """Record results for adaptive learning."""
        self.adaptive.record_result(job_result, strategy)
    
    def diagnose_error(self, error: str, step: str, context: dict = None) -> dict:
        """Smart error diagnosis and recovery planning."""
        return self.recovery.diagnose(error, step, context)
    
    def get_adaptive_summary(self) -> dict:
        """Get summary of adaptive learning."""
        return self.adaptive.get_learning_summary()

    def think(self, question: str, context: dict = None) -> dict:
        """Chain-of-thought reasoning on any question."""
        return self.thinker.think(question, context)
    
    def think_translation(self, text: str, source_lang: str, target_lang: str, context: dict = None) -> dict:
        """Deep thinking about how to translate a line."""
        return self.thinker.think_translation(text, source_lang, target_lang, context)
    
    def think_emotion(self, text: str, context: dict = None) -> dict:
        """Deep emotion analysis with acting direction."""
        return self.thinker.think_emotion(text, context)
    
    def think_cultural_bridge(self, text: str, source_lang: str, target_lang: str) -> dict:
        """Think about cultural gaps and how to bridge them."""
        return self.thinker.think_cultural_bridge(text, source_lang, target_lang)
    
    def brainstorm(self, text: str, source_lang: str, target_lang: str, n: int = 3) -> list[str]:
        """Brainstorm multiple translation options."""
        return self.thinker.brainstorm_translations(text, source_lang, target_lang, n)
    
    def self_reflect(self, translation: str, original: str, context: dict = None) -> dict:
        """Self-reflect on a translation quality."""
        return self.thinker.self_reflect(translation, original, context)

    def assess_and_retry(self, segments: list[dict], output_dir: str, context: dict) -> dict:
        """
        After pipeline: assess quality, suggest retries if needed.
        """
        return self.quality.assess(segments, output_dir, context)
    
    def learn(self, job_result: dict, user_feedback: dict = None):
        """
        Learn from completed job + optional feedback.
        """
        self.learner.record_job(job_result, user_feedback)
    
    def get_learned_preferences(self, user_id: str = "default") -> dict:
        """Get learned preferences for a user."""
        return self.learner.get_preferences(user_id)
    
    def _get_emotion_at_pos(self, emotion_arc: dict, pos: float) -> str:
        """Get dominant emotion at position (0.0-1.0) in the arc."""
        segments = emotion_arc.get("segments", [])
        if not segments:
            return ""
        # Find the emotion segment that covers this position
        for emo_seg in segments:
            if emo_seg.get("start_pos", 0) <= pos <= emo_seg.get("end_pos", 1):
                return emo_seg.get("emotion", "")
        return ""

__all__ = ["AGIBrain", "ContextEngine", "EmotionDetector", "StrategySelector", "QualityAssessor", "SelfLearner"]
