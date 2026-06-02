#!/usr/bin/env python3
"""
Proactive Recovery — Smart Error Handling
==========================================
When things go wrong, this module:
- Diagnoses WHY something failed
- Plans alternative approaches
- Retries with adjusted parameters
- Falls back gracefully
- Learns from failures

Unlike basic error handling, this THINKS about recovery strategies
before retrying — like a human troubleshooting a problem.
"""

import json
import os
import subprocess
import requests


class ProactiveRecovery:
    """Smart error recovery with reasoning."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.failure_log = []
    
    def diagnose(self, error: str, step: str, context: dict = None) -> dict:
        """
        Diagnose why something failed and plan recovery.
        
        Args:
            error: Error message
            step: Which pipeline step failed
            context: Additional context
        
        Returns:
            Diagnosis with recovery plan
        """
        diagnosis = {
            "error": error,
            "step": step,
            "root_cause": "unknown",
            "recovery_options": [],
            "recommended_action": "retry",
            "confidence": 0.5,
        }
        
        # Quick pattern matching for common errors
        error_lower = error.lower()
        
        if "timeout" in error_lower or "timed out" in error_lower:
            diagnosis["root_cause"] = "timeout"
            diagnosis["recovery_options"] = [
                {"action": "retry", "params": {"timeout_multiplier": 2}, "description": "Retry with longer timeout"},
                {"action": "skip_segment", "params": {}, "description": "Skip this segment and continue"},
                {"action": "reduce_batch", "params": {"batch_size": 5}, "description": "Process fewer items at once"},
            ]
            diagnosis["recommended_action"] = "retry"
        
        elif "connection" in error_lower or "refused" in error_lower:
            diagnosis["root_cause"] = "service_unavailable"
            diagnosis["recovery_options"] = [
                {"action": "wait_and_retry", "params": {"wait_seconds": 30}, "description": "Wait and retry"},
                {"action": "fallback_engine", "params": {"engine": "edge_tts"}, "description": "Use Edge TTS fallback"},
            ]
            diagnosis["recommended_action"] = "fallback_engine"
        
        elif "rate limit" in error_lower or "429" in error_lower:
            diagnosis["root_cause"] = "rate_limited"
            diagnosis["recovery_options"] = [
                {"action": "wait_and_retry", "params": {"wait_seconds": 60}, "description": "Wait for rate limit reset"},
                {"action": "reduce_frequency", "params": {"delay_between_requests": 2}, "description": "Slow down requests"},
            ]
            diagnosis["recommended_action"] = "wait_and_retry"
        
        elif "translat" in step.lower() and ("empty" in error_lower or "parse" in error_lower):
            diagnosis["root_cause"] = "translation_parse_error"
            diagnosis["recovery_options"] = [
                {"action": "retry", "params": {"temperature": 0.2}, "description": "Retry with lower temperature (more precise)"},
                {"action": "simplify_prompt", "params": {}, "description": "Use simpler translation prompt"},
                {"action": "segment_by_segment", "params": {}, "description": "Translate one segment at a time"},
            ]
            diagnosis["recommended_action"] = "segment_by_segment"
        
        elif "tts" in step.lower() and ("error" in error_lower or "fail" in error_lower):
            diagnosis["root_cause"] = "tts_failure"
            diagnosis["recovery_options"] = [
                {"action": "retry_segment", "params": {}, "description": "Retry this TTS segment"},
                {"action": "fallback_engine", "params": {"engine": "edge_tts"}, "description": "Use Edge TTS for this segment"},
                {"action": "split_text", "params": {}, "description": "Split long text into smaller chunks"},
            ]
            diagnosis["recommended_action"] = "retry_segment"
        
        elif "download" in step.lower() and ("fail" in error_lower or "error" in error_lower):
            diagnosis["root_cause"] = "download_failure"
            diagnosis["recovery_options"] = [
                {"action": "retry", "params": {"attempts": 3}, "description": "Retry download"},
                {"action": "try_alternative_url", "params": {}, "description": "Try alternative video source"},
            ]
            diagnosis["recommended_action"] = "retry"
        
        else:
            # Use LLM for complex diagnosis
            if self.api_key:
                llm_diagnosis = self._llm_diagnose(error, step, context)
                diagnosis.update(llm_diagnosis)
        
        # Log the failure
        self.failure_log.append({
            "error": error,
            "step": step,
            "root_cause": diagnosis["root_cause"],
            "action_taken": diagnosis["recommended_action"],
        })
        
        return diagnosis
    
    def execute_recovery(self, diagnosis: dict, pipeline_func, **kwargs) -> dict:
        """
        Execute the recommended recovery action.
        Returns recovery result.
        """
        action = diagnosis.get("recommended_action", "retry")
        options = diagnosis.get("recovery_options", [])
        
        # Find the matching recovery option
        target_option = None
        for opt in options:
            if opt["action"] == action:
                target_option = opt
                break
        
        if not target_option and options:
            target_option = options[0]  # Use first available
        
        if not target_option:
            return {"success": False, "error": "No recovery options available"}
        
        # Execute the recovery
        try:
            if target_option["action"] == "fallback_engine":
                kwargs["fallback"] = target_option["params"].get("engine", "edge_tts")
                return pipeline_func(**kwargs)
            
            elif target_option["action"] == "segment_by_segment":
                kwargs["batch_size"] = 1
                return pipeline_func(**kwargs)
            
            elif target_option["action"] == "retry":
                return pipeline_func(**kwargs)
            
            elif target_option["action"] == "wait_and_retry":
                import time
                wait = target_option["params"].get("wait_seconds", 30)
                print(f"  ⏳ Waiting {wait}s before retry...")
                time.sleep(wait)
                return pipeline_func(**kwargs)
            
            else:
                return pipeline_func(**kwargs)
        
        except Exception as e:
            return {"success": False, "error": f"Recovery failed: {e}"}
    
    def should_give_up(self, step: str) -> bool:
        """
        Decide if we should give up on a step after multiple failures.
        Like a human knowing when to cut losses.
        """
        recent_failures = [
            f for f in self.failure_log[-10:]
            if f["step"] == step
        ]
        
        # Give up after 3 failures on the same step
        if len(recent_failures) >= 3:
            # But check if they're different root causes
            causes = set(f["root_cause"] for f in recent_failures)
            if len(causes) == 1:
                return True  # Same cause 3 times = give up
        
        return False
    
    def get_failure_patterns(self) -> dict:
        """Analyze failure patterns to prevent future issues."""
        from collections import Counter
        
        step_failures = Counter(f["step"] for f in self.failure_log)
        cause_failures = Counter(f["root_cause"] for f in self.failure_log)
        
        return {
            "total_failures": len(self.failure_log),
            "by_step": dict(step_failures.most_common(5)),
            "by_cause": dict(cause_failures.most_common(5)),
            "most_problematic_step": step_failures.most_common(1)[0][0] if step_failures else "none",
        }
    
    def _llm_diagnose(self, error: str, step: str, context: dict = None) -> dict:
        """Use LLM for complex error diagnosis."""
        try:
            prompt = f"""Analyze this dubbing pipeline error and suggest recovery:

STEP: {step}
ERROR: {error}
CONTEXT: {json.dumps(context or {}, default=str)[:500]}

What went wrong? What should we try?
Return JSON: {{"root_cause": "...", "recovery_options": [...], "recommended_action": "..."}}"""

            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are a system reliability engineer diagnosing pipeline errors."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers=headers, json=payload, timeout=15,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {"root_cause": "unknown", "recovery_options": [], "recommended_action": "retry"}
