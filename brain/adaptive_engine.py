#!/usr/bin/env python3
"""
Adaptive Engine — Self-Modifying Intelligence
==============================================
Learns from past results and AUTO-ADJUSTS parameters:
- Tracks quality scores per genre/language/strategy
- Auto-tunes temperature, speed ranges, processing params
- A/B tests strategies on similar content
- Builds "playbook" of what works for different scenarios
- Modifies its OWN behavior over time (meta-learning)

This is what makes it GO from "follows instructions" to "improves itself".
"""

import json
import os
import time
from collections import defaultdict


class AdaptiveEngine:
    """Self-modifying engine that learns from results."""
    
    def __init__(self, data_dir: str = ""):
        self.data_dir = data_dir or os.getenv("BRAIN_DATA_DIR", "/tmp/openclaw-brain")
        self.playbook_file = os.path.join(self.data_dir, "adaptive_playbook.json")
        self.playbook = self._load_playbook()
    
    def _load_playbook(self) -> dict:
        """Load adaptive playbook from disk."""
        try:
            if os.path.exists(self.playbook_file):
                with open(self.playbook_file, "r") as f:
                    return json.load(f)
        except:
            pass
        
        return {
            "genre_strategies": {},  # genre -> best strategy found
            "language_pairs": {},    # lang_pair -> best settings
            "quality_history": [],   # Track quality over time
            "param_optimization": {},  # Track which params give best results
            "ab_tests": {},          # A/B test results
            "version": 1,
            "created_at": time.time(),
        }
    
    def _save_playbook(self):
        """Save playbook to disk."""
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.playbook_file, "w") as f:
            json.dump(self.playbook, f, ensure_ascii=False, indent=2)
    
    def get_optimized_strategy(self, genre: str, source_lang: str, target_lang: str) -> dict:
        """
        Get the BEST known strategy for this specific content type.
        Returns optimized parameters based on past learning.
        """
        strategy = {
            "translation_temperature": 0.3,
            "translation_method": "adaptive",
            "audio_target_lufs": -16.0,
            "speed_range": [0.7, 1.3],
            "eq_profile": "speech",
            "confidence": 0.5,  # How confident we are in these params
        }
        
        # Check genre-specific strategy
        genre_key = genre.lower()
        if genre_key in self.playbook["genre_strategies"]:
            learned = self.playbook["genre_strategies"][genre_key]
            strategy.update(learned.get("params", {}))
            strategy["confidence"] = learned.get("success_rate", 0.5)
        
        # Check language pair strategy
        lang_pair = f"{source_lang}_{target_lang}"
        if lang_pair in self.playbook["language_pairs"]:
            learned = self.playbook["language_pairs"][lang_pair]
            # Merge (language-specific overrides genre-specific)
            for k, v in learned.get("params", {}).items():
                strategy[k] = v
            strategy["confidence"] = max(strategy["confidence"], learned.get("success_rate", 0.5))
        
        # Check param optimization
        for param_key, optimization in self.playbook["param_optimization"].items():
            if optimization.get("best_value") is not None:
                strategy[param_key] = optimization["best_value"]
        
        return strategy
    
    def record_result(self, job_result: dict, strategy_used: dict):
        """
        Record results to learn what works.
        Updates playbook based on quality scores.
        """
        quality = job_result.get("quality_score", 0)
        genre = strategy_used.get("genre", "unknown")
        source_lang = job_result.get("source_lang", "")
        target_lang = job_result.get("target_lang", "")
        
        # Record in quality history
        self.playbook["quality_history"].append({
            "timestamp": time.time(),
            "quality": quality,
            "genre": genre,
            "strategy": strategy_used,
        })
        
        # Keep last 200 entries
        if len(self.playbook["quality_history"]) > 200:
            self.playbook["quality_history"] = self.playbook["quality_history"][-200:]
        
        # Update genre strategy
        genre_key = genre.lower()
        if genre_key not in self.playbook["genre_strategies"]:
            self.playbook["genre_strategies"][genre_key] = {
                "params": {},
                "total_jobs": 0,
                "total_quality": 0,
                "success_rate": 0,
            }
        
        gs = self.playbook["genre_strategies"][genre_key]
        gs["total_jobs"] += 1
        gs["total_quality"] += quality
        gs["success_rate"] = gs["total_quality"] / gs["total_jobs"]
        
        # If this was a good result, reinforce the params
        if quality >= 75:
            for key in ["translation_temperature", "translation_method", "audio_target_lufs",
                        "speed_range", "eq_profile"]:
                if key in strategy_used:
                    gs["params"][key] = strategy_used[key]
        
        # Update language pair strategy
        lang_pair = f"{source_lang}_{target_lang}"
        if lang_pair not in self.playbook["language_pairs"]:
            self.playbook["language_pairs"][lang_pair] = {
                "params": {},
                "total_jobs": 0,
                "total_quality": 0,
                "success_rate": 0,
            }
        
        lp = self.playbook["language_pairs"][lang_pair]
        lp["total_jobs"] += 1
        lp["total_quality"] += quality
        lp["success_rate"] = lp["total_quality"] / lp["total_jobs"]
        
        if quality >= 75:
            for key in strategy_used:
                if key in ("translation_temperature", "speed_range", "eq_profile"):
                    lp["params"][key] = strategy_used[key]
        
        # Update param optimization
        for key, value in strategy_used.items():
            if key in ("translation_temperature", "audio_target_lufs"):
                if key not in self.playbook["param_optimization"]:
                    self.playbook["param_optimization"][key] = {
                        "best_value": value,
                        "best_quality": quality,
                        "trials": 0,
                    }
                
                opt = self.playbook["param_optimization"][key]
                opt["trials"] += 1
                
                if quality > opt.get("best_quality", 0):
                    opt["best_value"] = value
                    opt["best_quality"] = quality
        
        self._save_playbook()
    
    def suggest_ab_test(self, genre: str) -> dict:
        """
        Suggest A/B test parameters to try.
        Systematically explores parameter space.
        """
        gs = self.playbook["genre_strategies"].get(genre.lower(), {})
        current_temp = gs.get("params", {}).get("translation_temperature", 0.3)
        
        # Suggest trying slightly different temperature
        return {
            "test_name": f"temp_test_{genre}",
            "parameter": "translation_temperature",
            "current_value": current_temp,
            "test_values": [max(0.1, current_temp - 0.1), min(0.8, current_temp + 0.1)],
            "metric": "quality_score",
        }
    
    def get_learning_summary(self) -> dict:
        """Summary of what the engine has learned."""
        return {
            "genres_learned": len(self.playbook["genre_strategies"]),
            "lang_pairs_learned": len(self.playbook["language_pairs"]),
            "total_experiments": len(self.playbook["quality_history"]),
            "avg_quality": self._avg_quality(),
            "best_genre": self._best_genre(),
            "worst_genre": self._worst_genre(),
        }
    
    def _avg_quality(self) -> float:
        history = self.playbook.get("quality_history", [])
        if not history:
            return 0
        scores = [h["quality"] for h in history]
        return round(sum(scores) / len(scores), 1)
    
    def _best_genre(self) -> str:
        genres = self.playbook.get("genre_strategies", {})
        if not genres:
            return "none"
        return max(genres, key=lambda g: genres[g].get("success_rate", 0))
    
    def _worst_genre(self) -> str:
        genres = self.playbook.get("genre_strategies", {})
        if not genres:
            return "none"
        return min(genres, key=lambda g: genres[g].get("success_rate", 0))
