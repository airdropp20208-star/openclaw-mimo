"""
Autonomous Planner — goal decomposition, task tracking, self-initiation.

The planner enables Hermes to:
1. Set long-term goals and break them into actionable subtasks
2. Track progress on each goal
3. Suggest next actions proactively
4. Maintain a goal queue with priorities and deadlines
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
GOALS_FILE = os.path.join(_DATA_DIR, "hermes_goals.json")


class Goal:
    """Represents a goal with subtasks."""

    def __init__(
        self,
        goal_id: str,
        description: str,
        priority: int = 5,  # 1=highest, 10=lowest
        deadline: Optional[str] = None,
        subtasks: Optional[list[dict]] = None,
        status: str = "active",  # active, paused, completed, failed
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ):
        self.goal_id = goal_id
        self.description = description
        self.priority = priority
        self.deadline = deadline
        self.subtasks = subtasks or []
        self.status = status
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or self.created_at
        self.tags = tags or []

    def to_dict(self) -> dict:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "priority": self.priority,
            "deadline": self.deadline,
            "subtasks": self.subtasks,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Goal":
        valid = {k for k in cls.__init__.__code__.co_varnames if k != "self"}
        return cls(**{k: v for k, v in data.items() if k in valid})

    @property
    def progress(self) -> float:
        if not self.subtasks:
            return 100.0 if self.status == "completed" else 0.0
        done = sum(1 for s in self.subtasks if s.get("status") == "completed")
        return round(done / len(self.subtasks) * 100, 1)

    @property
    def next_subtask(self) -> Optional[dict]:
        for s in self.subtasks:
            if s.get("status") == "pending":
                return s
        return None

    @property
    def is_overdue(self) -> bool:
        if not self.deadline or self.status != "active":
            return False
        try:
            dl = datetime.fromisoformat(self.deadline)
            return datetime.now() > dl
        except ValueError:
            return False


class Planner:
    """
    Autonomous planning engine.

    Manages goals, decomposes them into subtasks, and provides
    recommendations for next actions.
    """

    def __init__(self, chat_id: int):
        self.chat_id = chat_id
        self._goals: list[Goal] = []
        self._goal_counter = 0
        self._load()

    # --- Persistence ---

    def _load(self) -> None:
        try:
            with open(GOALS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            chat_data = data.get(str(self.chat_id), {})
            self._goals = [Goal.from_dict(g) for g in chat_data.get("goals", [])]
            self._goal_counter = chat_data.get("counter", 0)
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            self._goals = []
            self._goal_counter = 0

    def _save(self) -> None:
        try:
            os.makedirs(_DATA_DIR, exist_ok=True)
            data = {}
            try:
                with open(GOALS_FILE, encoding="utf-8") as f:
                    data = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            data[str(self.chat_id)] = {
                "goals": [g.to_dict() for g in self._goals],
                "counter": self._goal_counter,
            }
            tmp = GOALS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, GOALS_FILE)
        except Exception as e:
            logger.error("Failed to save goals: %s", e)

    # --- Goal Management ---

    def add_goal(
        self,
        description: str,
        priority: int = 5,
        deadline: Optional[str] = None,
        subtasks: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
    ) -> Goal:
        """Add a new goal with optional subtasks."""
        self._goal_counter += 1
        goal_id = f"g{self._goal_counter}"
        subtask_list = []
        for i, st in enumerate(subtasks or []):
            subtask_list.append({
                "id": f"{goal_id}.s{i+1}",
                "description": st,
                "status": "pending",
                "result": None,
            })
        goal = Goal(
            goal_id=goal_id,
            description=description,
            priority=priority,
            deadline=deadline,
            subtasks=subtask_list,
            tags=tags or [],
        )
        self._goals.append(goal)
        self._save()
        logger.info("Added goal %s: %s", goal_id, description)
        return goal

    def complete_subtask(self, subtask_id: str, result: str = "", llm_fn=None) -> Optional[Goal]:
        """Mark a subtask as completed and optionally re-evaluate the plan."""
        for goal in self._goals:
            if goal.status != "active":
                continue
            for st in goal.subtasks:
                if st["id"] == subtask_id:
                    st["status"] = "completed"
                    st["result"] = result
                    goal.updated_at = datetime.now().isoformat()
                    
                    # Adaptive Planning: If it's a major step, re-evaluate remaining tasks
                    if llm_fn and len(goal.subtasks) > 1:
                        self._adapt_plan(goal, subtask_id, result, llm_fn)

                    # Only complete goal if it has subtasks AND all are done
                    if goal.subtasks and all(s["status"] in ["completed", "skipped"] for s in goal.subtasks):
                        goal.status = "completed"
                        logger.info("Goal %s completed!", goal.goal_id)
                    self._save()
                    return goal
        return None

    def fail_subtask(self, subtask_id: str, reason: str = "", llm_fn=None) -> Optional[Goal]:
        """Mark a subtask as failed and trigger plan adaptation."""
        for goal in self._goals:
            if goal.status != "active":
                continue
            for st in goal.subtasks:
                if st["id"] == subtask_id:
                    st["status"] = "failed"
                    st["result"] = reason
                    goal.updated_at = datetime.now().isoformat()
                    
                    # Trigger plan adaptation on failure
                    if llm_fn:
                        logger.info("Subtask failed. Triggering plan adaptation for goal %s", goal.goal_id)
                        self._adapt_plan(goal, subtask_id, reason, llm_fn, is_failure=True)
                    
                    self._save()
                    return goal
        return None

    def _adapt_plan(self, goal: Goal, subtask_id: str, result: str, llm_fn, is_failure: bool = False):
        """Internal helper to adapt the remaining plan based on new information."""
        remaining_tasks = [st for st in goal.subtasks if st["status"] == "pending"]
        if not remaining_tasks and not is_failure:
            return

        prompt = f"""Goal: {goal.description}
Completed/Failed Task: {subtask_id}
Result/Reason: {result}
Current Remaining Plan: {json.dumps([st['description'] for st in remaining_tasks])}

{'The last task FAILED.' if is_failure else 'The last task was successful.'}
Based on this, should the remaining plan be adjusted? 
- You can add new subtasks.
- You can skip/remove unnecessary ones.
- You can modify existing ones.

Return a JSON object: {{"action": "update", "new_plan": ["task 1", "task 2", ...]}} or {{"action": "keep"}}
ONLY return the JSON."""

        try:
            resp = llm_fn([{"role": "user", "content": prompt}])
            import re
            match = re.search(r"\{.*\}", resp, re.DOTALL)
            if match:
                data = json.loads(match.group())
                if data.get("action") == "update" and isinstance(data.get("new_plan"), list):
                    logger.info("Adapting plan for goal %s", goal.goal_id)
                    # Keep completed tasks, replace pending ones
                    new_subtasks = [st for st in goal.subtasks if st["status"] != "pending"]
                    for i, desc in enumerate(data["new_plan"]):
                        new_subtasks.append({
                            "id": f"{goal.goal_id}.a{len(new_subtasks)+1}",
                            "description": desc,
                            "status": "pending",
                            "result": None
                        })
                    goal.subtasks = new_subtasks
        except Exception as e:
            logger.warning("Plan adaptation failed: %s", e)

    def get_active_goals(self) -> list[Goal]:
        """Get all active goals, sorted by priority."""
        active = [g for g in self._goals if g.status == "active"]
        active.sort(key=lambda g: (g.priority, g.deadline or "9999"))
        return active

    def get_all_goals(self) -> list[Goal]:
        return self._goals.copy()

    def pause_goal(self, goal_id: str) -> bool:
        for g in self._goals:
            if g.goal_id == goal_id and g.status == "active":
                g.status = "paused"
                g.updated_at = datetime.now().isoformat()
                self._save()
                return True
        return False

    def resume_goal(self, goal_id: str) -> bool:
        for g in self._goals:
            if g.goal_id == goal_id and g.status == "paused":
                g.status = "active"
                g.updated_at = datetime.now().isoformat()
                self._save()
                return True
        return False

    def delete_goal(self, goal_id: str) -> bool:
        before = len(self._goals)
        self._goals = [g for g in self._goals if g.goal_id != goal_id]
        if len(self._goals) < before:
            self._save()
            return True
        return False

    # --- Autonomous Planning ---

    def decompose_goal(self, description: str, llm_fn=None) -> list[str]:
        """
        Use LLM to decompose a high-level goal into actionable subtasks.
        If no llm_fn, return a basic decomposition.
        """
        if not llm_fn:
            return [f"Work on: {description}"]

        prompt = f"""Break this goal into 3-7 concrete, actionable subtasks.
Each subtask should be a single clear action that can be done independently.

Goal: {description}

Return ONLY a JSON array of strings. Example:
["Step 1: ...", "Step 2: ...", "Step 3: ..."]"""

        try:
            response = llm_fn(
                [{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            # Extract JSON array
            text = response.strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                tasks = json.loads(text[start:end])
                if isinstance(tasks, list) and all(isinstance(t, str) for t in tasks):
                    return tasks[:7]
        except Exception as e:
            logger.warning("LLM decomposition failed: %s", e)

        return [f"Work on: {description}"]

    def get_next_actions(self, llm_fn=None) -> list[dict]:
        """
        Get recommended next actions based on current goals.
        Returns list of {goal_id, subtask_id, action, priority, reason}.
        """
        recommendations = []
        now = datetime.now()

        for goal in self.get_active_goals():
            next_st = goal.next_subtask
            if next_st:
                # Calculate urgency
                urgency = goal.priority
                if goal.deadline:
                    try:
                        dl = datetime.fromisoformat(goal.deadline)
                        days_left = (dl - now).days
                        if days_left <= 0:
                            urgency = 1  # overdue = highest
                        elif days_left <= 2:
                            urgency = min(urgency, 2)
                    except ValueError:
                        pass

                recommendations.append({
                    "goal_id": goal.goal_id,
                    "subtask_id": next_st["id"],
                    "action": next_st["description"],
                    "priority": urgency,
                    "goal": goal.description,
                    "reason": _urgency_reason(urgency, goal),
                })

        # Sort by priority (lower = more urgent)
        recommendations.sort(key=lambda r: r["priority"])
        return recommendations[:5]  # Top 5

    def get_summary(self) -> str:
        """Get a human-readable summary of all goals."""
        active = [g for g in self._goals if g.status == "active"]
        completed = [g for g in self._goals if g.status == "completed"]
        paused = [g for g in self._goals if g.status == "paused"]
        overdue = [g for g in active if g.is_overdue]

        lines = [f"📋 *Goal Summary* ({len(active)} active)"]

        if overdue:
            lines.append(f"\n🚨 *Overdue:* {len(overdue)}")
            for g in overdue:
                lines.append(f"  ⚠️ {g.goal_id}: {g.description[:60]}")

        for g in active:
            progress_bar = _progress_bar(g.progress)
            lines.append(
                f"\n🎯 {g.goal_id} [{g.description[:50]}]\n"
                f"   {progress_bar} {g.progress}%\n"
                f"   Priority: {g.priority} | Subtasks: {len(g.subtasks)}"
            )
            if g.deadline:
                lines.append(f"   Deadline: {g.deadline}")
            next_st = g.next_subtask
            if next_st:
                lines.append(f"   ▶ Next: {next_st['description'][:60]}")

        if completed:
            lines.append(f"\n✅ Completed: {len(completed)}")
            for g in completed[-3:]:  # Last 3
                lines.append(f"  ✓ {g.goal_id}: {g.description[:60]}")

        if paused:
            lines.append(f"\n⏸ Paused: {len(paused)}")

        return "\n".join(lines)

    def add_subtask(self, goal_id: str, description: str, after_id: Optional[str] = None) -> bool:
        """Dynamically add a subtask to an existing goal."""
        for goal in self._goals:
            if goal.goal_id == goal_id:
                new_id = f"{goal_id}.s{len(goal.subtasks) + 1}"
                new_st = {
                    "id": new_id,
                    "description": description,
                    "status": "pending",
                    "result": None,
                }
                if after_id:
                    for i, st in enumerate(goal.subtasks):
                        if st["id"] == after_id:
                            goal.subtasks.insert(i + 1, new_st)
                            break
                    else:
                        goal.subtasks.append(new_st)
                else:
                    goal.subtasks.append(new_st)
                
                goal.updated_at = datetime.now().isoformat()
                self._save()
                return True
        return False

    def export_for_prompt(self) -> str:
        """Export detailed goal context for injection into LLM prompt."""
        active = self.get_active_goals()
        if not active:
            return ""

        lines = ["[CURRENT GOALS & PROGRESS]"]
        lines.append("You are currently working on these goals. Use 'goal_manage' tool to update progress.")
        for g in active[:3]:
            lines.append(f"\n🎯 Goal {g.goal_id}: {g.description}")
            lines.append(f"   Status: {g.status} | Progress: {g.progress}%")
            for st in g.subtasks:
                status_icon = "✅" if st["status"] == "completed" else "❌" if st["status"] == "failed" else "⏳"
                lines.append(f"   {status_icon} {st['id']}: {st['description']}")
                if st.get("result"):
                    lines.append(f"      Result: {st['result'][:100]}...")
        
        return "\n".join(lines)


# --- Helpers ---

def _progress_bar(pct: float, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def _urgency_reason(priority: int, goal: Goal) -> str:
    if priority == 1:
        return "🔴 Overdue!"
    elif priority <= 3:
        return "🟡 High priority"
    else:
        return "🟢 Normal"
