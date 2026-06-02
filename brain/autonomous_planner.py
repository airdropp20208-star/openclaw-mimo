#!/usr/bin/env python3
"""
Autonomous Planner — Self-Directed Decision Making
===================================================
The brain PLANS its own approach before execution:
- Analyzes the task and decides the best pipeline
- Allocates resources (time, API calls, quality) intelligently
- Makes trade-off decisions (speed vs quality)
- Plans multi-step reasoning
- Adapts the plan mid-execution if needed

This is what separates a TOOL from an AGENT:
A tool waits for instructions. An AGENT makes its own plan.
"""

import json
import time


class AutonomousPlanner:
    """Self-directed planning engine."""
    
    def __init__(self, brain=None):
        self.brain = brain
        self.current_plan = None
        self.execution_log = []
    
    def create_plan(self, task: dict) -> dict:
        """
        Create an execution plan for a dubbing task.
        
        Task: {"url": "...", "source_lang": "...", "target_lang": "...", "user_prefs": {...}}
        
        Returns a detailed plan with steps, priorities, and contingencies.
        """
        plan = {
            "id": f"plan_{int(time.time())}",
            "created_at": time.time(),
            "status": "planning",
            "task": task,
            "steps": [],
            "estimated_time": 0,
            "quality_target": "high",
            "contingencies": [],
            "resource_allocation": {},
        }
        
        # Step 1: Analyze the task
        analysis = self._analyze_task(task)
        plan["analysis"] = analysis
        
        # Step 2: Determine approach
        approach = self._determine_approach(analysis, task)
        plan["approach"] = approach
        
        # Step 3: Build step sequence
        steps = self._build_steps(analysis, approach, task)
        plan["steps"] = steps
        
        # Step 4: Estimate time and resources
        plan["estimated_time"] = self._estimate_time(steps)
        plan["resource_allocation"] = self._allocate_resources(steps, approach)
        
        # Step 5: Plan contingencies
        plan["contingencies"] = self._plan_contingencies(steps)
        
        plan["status"] = "ready"
        self.current_plan = plan
        
        return plan
    
    def execute_plan(self, plan: dict, pipeline_func) -> dict:
        """
        Execute a plan step by step, monitoring progress.
        Can adapt the plan if issues arise.
        """
        results = []
        start_time = time.time()
        
        for i, step in enumerate(plan["steps"]):
            step_start = time.time()
            
            log_entry = {
                "step": step["name"],
                "started_at": time.time(),
                "status": "running",
            }
            
            try:
                # Execute the step
                result = self._execute_step(step, pipeline_func)
                log_entry["status"] = "completed"
                log_entry["result"] = result
                log_entry["duration"] = time.time() - step_start
                
                results.append(log_entry)
                
                # Check if we should adapt the plan
                if self._should_adapt(result, plan, i):
                    plan = self._adapt_plan(plan, result, i)
                    log_entry["plan_adapted"] = True
                
            except Exception as e:
                log_entry["status"] = "failed"
                log_entry["error"] = str(e)
                log_entry["duration"] = time.time() - step_start
                results.append(log_entry)
                
                # Handle failure
                if not self._handle_step_failure(step, e, plan, i):
                    break  # Give up
        
        total_time = time.time() - start_time
        
        return {
            "success": all(r["status"] == "completed" for r in results),
            "steps_completed": sum(1 for r in results if r["status"] == "completed"),
            "total_steps": len(plan["steps"]),
            "total_time": total_time,
            "results": results,
            "plan_adapted": any(r.get("plan_adapted") for r in results),
        }
    
    def _analyze_task(self, task: dict) -> dict:
        """Analyze what we're being asked to do."""
        url = task.get("url", "")
        source_lang = task.get("source_lang", "Chinese")
        target_lang = task.get("target_lang", "Vietnamese")
        
        # Determine complexity
        complexity = "standard"
        if not url:
            complexity = "simple"  # Local file
        elif "bilibili" in url or "long" in url.lower():
            complexity = "complex"  # Platform-specific or long video
        
        # Determine quality needs
        user_prefs = task.get("user_prefs", {})
        quality = user_prefs.get("quality", "high")
        
        return {
            "url": url,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "complexity": complexity,
            "quality_target": quality,
            "has_url": bool(url),
            "is_local": not bool(url),
        }
    
    def _determine_approach(self, analysis: dict, task: dict) -> dict:
        """Determine the best approach for this task."""
        approach = {
            "translation": "brain_enhanced",
            "tts": "omnivoice",
            "brain_level": "full",
            "quality_over_speed": True,
        }
        
        if analysis["complexity"] == "standard":
            approach["brain_level"] = "full"
        elif analysis["complexity"] == "simple":
            approach["brain_level"] = "basic"  # Don't overthink simple tasks
        
        # Adapt based on user preferences
        user_prefs = task.get("user_prefs", {})
        if user_prefs.get("fast_mode"):
            approach["brain_level"] = "minimal"
            approach["quality_over_speed"] = False
        
        return approach
    
    def _build_steps(self, analysis: dict, approach: dict, task: dict) -> list[dict]:
        """Build the execution step sequence."""
        steps = []
        
        # Always: Download (if URL)
        if analysis["has_url"]:
            steps.append({
                "name": "download",
                "description": "Download video",
                "priority": "critical",
                "estimated_time": 30,
                "retryable": True,
            })
        
        # Always: Extract audio
        steps.append({
            "name": "extract_audio",
            "description": "Extract audio track",
            "priority": "critical",
            "estimated_time": 10,
            "retryable": True,
        })
        
        # Brain: Scene analysis (if full brain)
        if approach["brain_level"] == "full":
            steps.append({
                "name": "scene_analysis",
                "description": "Analyze video scenes visually",
                "priority": "optional",
                "estimated_time": 20,
                "retryable": False,
            })
        
        # Always: Transcribe
        steps.append({
            "name": "transcribe",
            "description": "Transcribe audio with Whisper",
            "priority": "critical",
            "estimated_time": 60,
            "retryable": True,
        })
        
        # Brain: Deep analysis
        if approach["brain_level"] in ("full", "standard"):
            steps.append({
                "name": "brain_analyze",
                "description": "Deep context + emotion analysis",
                "priority": "high",
                "estimated_time": 15,
                "retryable": True,
            })
        
        # Always: Translate
        steps.append({
            "name": "translate",
            "description": f"Translate {analysis['source_lang']} -> {analysis['target_lang']}",
            "priority": "critical",
            "estimated_time": 30,
            "retryable": True,
        })
        
        # Brain: Emotional continuity
        if approach["brain_level"] == "full":
            steps.append({
                "name": "emotional_continuity",
                "description": "Build consistent emotional arc",
                "priority": "high",
                "estimated_time": 5,
                "retryable": False,
            })
        
        # Brain: Self-reflect translations
        if approach["brain_level"] == "full":
            steps.append({
                "name": "self_reflect",
                "description": "Review and improve translations",
                "priority": "medium",
                "estimated_time": 20,
                "retryable": False,
            })
        
        # Always: TTS
        steps.append({
            "name": "tts",
            "description": "Generate voice for all segments",
            "priority": "critical",
            "estimated_time": 120,
            "retryable": True,
        })
        
        # Always: Sync + Process + Combine
        steps.extend([
            {"name": "sync", "description": "Sync voice to video timing", "priority": "high", "estimated_time": 15, "retryable": True},
            {"name": "audio_process", "description": "Professional audio processing", "priority": "medium", "estimated_time": 10, "retryable": True},
            {"name": "combine", "description": "Combine final video", "priority": "critical", "estimated_time": 30, "retryable": True},
            {"name": "subtitles", "description": "Burn subtitles", "priority": "medium", "estimated_time": 20, "retryable": True},
        ])
        
        # Brain: Quality assessment
        if approach["brain_level"] in ("full", "standard"):
            steps.append({
                "name": "quality_assess",
                "description": "Auto-evaluate output quality",
                "priority": "high",
                "estimated_time": 10,
                "retryable": False,
            })
        
        return steps
    
    def _estimate_time(self, steps: list[dict]) -> float:
        """Estimate total execution time."""
        return sum(s.get("estimated_time", 0) for s in steps)
    
    def _allocate_resources(self, steps: list[dict], approach: dict) -> dict:
        """Allocate resources based on approach."""
        total_time = self._estimate_time(steps)
        
        return {
            "total_estimated_seconds": total_time,
            "brain_usage": approach.get("brain_level", "basic"),
            "quality_priority": "high" if approach.get("quality_over_speed") else "balanced",
            "max_api_calls": 50 if approach.get("brain_level") == "full" else 20,
        }
    
    def _plan_contingencies(self, steps: list[dict]) -> list[dict]:
        """Plan what to do if things fail."""
        contingencies = []
        
        for step in steps:
            if step.get("retryable"):
                contingencies.append({
                    "trigger": f"{step['name']}_failed",
                    "action": f"retry_{step['name']}",
                    "max_retries": 2,
                })
        
        # Overall contingencies
        contingencies.append({
            "trigger": "total_time_exceeded",
            "action": "reduce_brain_usage",
            "detail": "Switch to minimal brain mode to save time",
        })
        
        return contingencies
    
    def _execute_step(self, step: dict, pipeline_func) -> dict:
        """Execute a single plan step."""
        # In real implementation, this would call the actual pipeline functions
        return {"success": True, "step": step["name"]}
    
    def _should_adapt(self, result: dict, plan: dict, current_step: int) -> bool:
        """Decide if the plan should be adapted."""
        if not result.get("success"):
            return True
        return False
    
    def _adapt_plan(self, plan: dict, result: dict, current_step: int) -> dict:
        """Adapt the plan based on execution results."""
        # If a step failed, adjust remaining steps
        if not result.get("success"):
            # Reduce brain usage for remaining steps
            for i in range(current_step + 1, len(plan["steps"])):
                if plan["steps"][i].get("priority") == "optional":
                    plan["steps"][i]["skip"] = True
        
        return plan
    
    def _handle_step_failure(self, step: dict, error: Exception, plan: dict, step_index: int) -> bool:
        """Handle a step failure. Returns True if we should continue."""
        if step.get("retryable"):
            return True  # Allow retry
        if step.get("priority") == "optional":
            return True  # Skip optional steps
        return False  # Critical step failed, give up
