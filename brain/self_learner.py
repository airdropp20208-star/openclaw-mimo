#!/usr/bin/env python3
"""
Self-Learner — Learning from Feedback
======================================
Stores and learns from user interactions:
- User corrections and preferences
- Quality feedback patterns
- Language/vocabulary preferences
- Voice preference trends
- Strategy effectiveness

Stores data locally as JSON for portability.
"""

import json
import os
import time
from collections import defaultdict


DATA_DIR = os.getenv("BRAIN_DATA_DIR", "/tmp/openclaw-brain")


class SelfLearner:
    """Learn and adapt from user feedback over time."""
    
    def __init__(self, data_dir: str = ""):
        self.data_dir = data_dir or DATA_DIR
        self.memory_file = os.path.join(self.data_dir, "learning_memory.json")
        self.memory = self._load_memory()
    
    def _load_memory(self) -> dict:
        """Load learning memory from disk."""
        try:
            if os.path.exists(self.memory_file):
                with open(self.memory_file, "r") as f:
                    return json.load(f)
        except:
            pass
        
        return {
            "users": {},  # user_id -> preferences
            "jobs": [],  # Recent job results (keep last 100)
            "corrections": [],  # User corrections
            "vocabulary": {},  # Learned vocabulary mappings
            "strategy_stats": {},  # Strategy effectiveness stats
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    
    def _save_memory(self):
        """Save memory to disk."""
        self.memory["updated_at"] = time.time()
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.memory_file, "w") as f:
            json.dump(self.memory, f, ensure_ascii=False, indent=2)
    
    def record_job(self, job_result: dict, user_feedback: dict = None):
        """Record a completed job and optional feedback."""
        entry = {
            "timestamp": time.time(),
            "success": job_result.get("success", False),
            "segments": job_result.get("segments", 0),
            "processing_time": job_result.get("processing_time", 0),
            "source_lang": job_result.get("source_lang", ""),
            "target_lang": job_result.get("target_lang", ""),
            "strategy": job_result.get("strategy_used", {}),
            "quality_score": job_result.get("quality_score", 0),
            "feedback": user_feedback,
        }
        
        # Add to jobs list (keep last 100)
        self.memory["jobs"].append(entry)
        if len(self.memory["jobs"]) > 100:
            self.memory["jobs"] = self.memory["jobs"][-100:]
        
        # Process feedback
        if user_feedback:
            self._process_feedback(user_feedback, entry)
        
        # Update strategy stats
        self._update_strategy_stats(entry)
        
        self._save_memory()
    
    def record_correction(self, original: str, corrected: str, context: str = ""):
        """Record a user correction (original vs corrected translation)."""
        correction = {
            "timestamp": time.time(),
            "original": original,
            "corrected": corrected,
            "context": context,
        }
        
        self.memory["corrections"].append(correction)
        if len(self.memory["corrections"]) > 200:
            self.memory["corrections"] = self.memory["corrections"][-200:]
        
        # Learn vocabulary mapping
        self._learn_vocabulary(original, corrected)
        
        self._save_memory()
    
    def record_preference(self, user_id: str, key: str, value):
        """Record a user preference."""
        user_id = str(user_id)
        if user_id not in self.memory["users"]:
            self.memory["users"][user_id] = {"preferences": {}, "job_count": 0}
        
        self.memory["users"][user_id]["preferences"][key] = value
        self._save_memory()
    
    def get_preferences(self, user_id: str = "default") -> dict:
        """Get learned preferences for a user."""
        user_id = str(user_id)
        user_data = self.memory["users"].get(user_id, {})
        return user_data.get("preferences", {})
    
    def get_vocabulary_hints(self, source_text: str) -> str:
        """Check if we have learned mappings for this text."""
        # Exact match
        if source_text in self.memory["vocabulary"]:
            return self.memory["vocabulary"][source_text]
        
        # Partial match
        for orig, learned in self.memory["vocabulary"].items():
            if source_text in orig or orig in source_text:
                return learned
        
        return ""
    
    def get_corrections_context(self) -> list[dict]:
        """Get recent corrections for context-aware translation."""
        return self.memory.get("corrections", [])[-20:]  # Last 20
    
    def get_strategy_effectiveness(self) -> dict:
        """Get strategy effectiveness statistics."""
        return self.memory.get("strategy_stats", {})
    
    def get_stats(self) -> dict:
        """Get overall learning statistics."""
        return {
            "total_jobs": len(self.memory.get("jobs", [])),
            "total_corrections": len(self.memory.get("corrections", [])),
            "total_vocabulary": len(self.memory.get("vocabulary", {})),
            "known_users": len(self.memory.get("users", {})),
            "avg_quality": self._avg_quality(),
            "created_at": self.memory.get("created_at", 0),
            "updated_at": self.memory.get("updated_at", 0),
        }
    
    def _process_feedback(self, feedback: dict, job_entry: dict):
        """Process user feedback."""
        user_id = str(feedback.get("user_id", "default"))
        
        if user_id not in self.memory["users"]:
            self.memory["users"][user_id] = {"preferences": {}, "job_count": 0}
        
        user = self.memory["users"][user_id]
        user["job_count"] = user.get("job_count", 0) + 1
        
        # Learn from rating
        if "rating" in feedback:
            rating = feedback["rating"]
            if rating >= 4:  # Good feedback
                # Reinforce current strategy
                strategy = job_entry.get("strategy", {})
                if strategy:
                    for key, val in strategy.items():
                        user["preferences"][f"strategy_{key}"] = val
        
        # Learn from specific corrections
        if "corrections" in feedback:
            for corr in feedback["corrections"]:
                self.record_correction(
                    corr.get("original", ""),
                    corr.get("corrected", ""),
                    context=corr.get("context", ""),
                )
    
    def _learn_vocabulary(self, original: str, corrected: str):
        """Learn vocabulary mappings from corrections."""
        if original and corrected:
            self.memory["vocabulary"][original] = corrected
    
    def _update_strategy_stats(self, job_entry: dict):
        """Update strategy effectiveness statistics."""
        strategy = job_entry.get("strategy", {})
        quality = job_entry.get("quality_score", 0)
        
        if not strategy:
            return
        
        key = json.dumps(strategy, sort_keys=True)
        if key not in self.memory["strategy_stats"]:
            self.memory["strategy_stats"][key] = {
                "count": 0,
                "total_quality": 0,
                "avg_quality": 0,
            }
        
        stats = self.memory["strategy_stats"][key]
        stats["count"] += 1
        stats["total_quality"] += quality
        stats["avg_quality"] = stats["total_quality"] / stats["count"]
    
    def _avg_quality(self) -> float:
        """Calculate average quality score."""
        jobs = self.memory.get("jobs", [])
        scores = [j["quality_score"] for j in jobs if j.get("quality_score", 0) > 0]
        if not scores:
            return 0
        return round(sum(scores) / len(scores), 1)
