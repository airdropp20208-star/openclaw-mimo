#!/usr/bin/env python3
"""
AGI Brain v3 — Single Integrated Intelligence
===============================================
ONE brain, tightly interconnected. No redundancy.

Modules (all connected through IntelligenceCore):
- world_model: Causal reasoning + cultural commonsense
- meta_cognition: Self-awareness + verification + doubt
- anticipation: Prediction + tension building
- context_engine: Deep semantic understanding
- emotion_detector: Multi-modal emotion analysis
- emotional_continuity: Consistent emotional arcs
- adaptive_engine: Self-modifying based on results
- proactive_recovery: Smart error diagnosis
- human_thinker: Chain-of-thought reasoning
- quality_assessor: Output quality evaluation
- scene_understander: Multi-modal video analysis

Central Hub:
- IntelligenceCore: Orchestrates all modules in 5 phases
  1. UNDERSTAND → 2. THINK → 3. REFINE → 4. ASSESS → 5. LEARN
"""

from .core import IntelligenceCore

# Legacy aliases for backward compatibility
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
from .world_model import WorldModel
from .meta_cognition import MetaCognition
from .anticipation import AnticipationNetwork


class AGIBrain:
    """
    Legacy wrapper — delegates to IntelligenceCore.
    Use IntelligenceCore directly for new code.
    """
    
    def __init__(self, mimo_api_key: str = "", mimo_api_base: str = "", mimo_model: str = "mimo-v2.5-pro"):
        self.core = IntelligenceCore(mimo_api_key, mimo_api_base, mimo_model)
        
        # Expose modules for backward compat
        self.context = self.core.get("context")
        self.emotion = self.core.get("emotion")
        self.strategy = StrategySelector(self.context, self.emotion)
        self.quality = self.core.get("quality")
        self.learner = SelfLearner()
        self.thinker = self.core.get("thinker")
        self.scene = self.core.get("scene")
        self.adaptive = self.core.get("adaptive")
        self.recovery = self.core.get("recovery")
        self.emotional = self.core.get("continuity")
        self.world = self.core.get("world")
        self.meta = self.core.get("meta")
        self.anticipation = self.core.get("anticipation")
    
    def analyze(self, segments, source_lang, target_lang):
        """Legacy: basic analysis."""
        return self.core.understand(segments, source_lang, target_lang)
    
    def post_translate(self, segments, context):
        """Legacy: post-translation refinement."""
        return self.core.refine_translations(segments, context)
    
    def assess_and_retry(self, segments, output_dir, context):
        """Legacy: quality assessment."""
        return self.core.assess(segments, output_dir, context)
    
    def record_job(self, job_result, user_feedback=None):
        """Legacy: record job."""
        self.learner.record_job(job_result, user_feedback)
    
    def think(self, question, context=None):
        return self.thinker.think(question, context)
    
    def think_translation(self, text, source_lang, target_lang, context=None):
        return self.thinker.think_translation(text, source_lang, target_lang, context)
    
    def think_emotion(self, text, context=None):
        return self.thinker.think_emotion(text, context)
    
    def think_cultural_bridge(self, text, source_lang, target_lang):
        return self.thinker.think_cultural_bridge(text, source_lang, target_lang)
    
    def brainstorm(self, text, source_lang, target_lang, n=3):
        return self.thinker.brainstorm_translations(text, source_lang, target_lang, n)
    
    def self_reflect(self, translation, original, context=None):
        return self.thinker.self_reflect(translation, original, context)
    
    def create_plan(self, task):
        return self.core.understand(task.get("segments", []), task.get("source_lang", ""), task.get("target_lang", ""))
    
    def understand_scene(self, video_path, segments=None):
        return self.scene.analyze_video(video_path, segments)
    
    def build_emotional_arc(self, segments, context=None):
        return self.emotional.build_arc(segments, context)
    
    def apply_emotional_arc(self, segments, arc):
        return self.emotional.apply_arc(segments, arc)
    
    def get_adaptive_strategy(self, genre, source_lang, target_lang):
        return self.adaptive.get_optimized_strategy(genre, source_lang, target_lang)
    
    def record_job_result(self, job_result, strategy):
        self.adaptive.record_result(job_result, strategy)
    
    def diagnose_error(self, error, step, context=None):
        return self.recovery.diagnose(error, step, context)
    
    def get_adaptive_summary(self):
        return self.adaptive.get_learning_summary()


__all__ = [
    "IntelligenceCore", "AGIBrain",
    "ContextEngine", "EmotionDetector", "StrategySelector",
    "QualityAssessor", "SelfLearner", "HumanThinker",
    "SceneUnderstander", "AdaptiveEngine", "ProactiveRecovery",
    "EmotionalContinuity", "WorldModel", "MetaCognition",
    "AnticipationNetwork",
]
