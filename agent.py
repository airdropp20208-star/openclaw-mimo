"""
Hermes Agent — autonomous agent with planning, tool calling, and learning.

3 capabilities:
1. Tool-using — execute tools (shell, file, browser, search, etc.)
2. Autonomous — self-plan, auto-chain steps, progress reporting
3. Learning — extract skills from successful tasks
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from tools import TOOLS, execute_tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are Hermes — an autonomous AI agent with a full VPS toolchain.

## Your capabilities:
- Execute shell commands, browse the web, convert files, generate PPTs, manage files
- Plan complex tasks into steps and execute them automatically
- Learn from successful tasks to improve future performance

## How you work:
When the user asks you to DO something, you have TWO modes:

### Mode 1: Quick task (single action)
If the task needs only 1-2 tool calls, respond with:
{"action": "tool", "tool": "tool_name", "args": {"arg1": "value1"}}

### Mode 2: Complex task (multi-step plan)
If the task needs multiple steps, respond with a plan:
{"action": "plan", "steps": [
  {"tool": "shell", "args": {"command": "..."}, "desc": "what this step does"},
  {"tool": "file_write", "args": {"path": "...", "content": "..."}, "desc": "..."},
  {"tool": "browse", "args": {"url": "..."}, "desc": "..."}
], "goal": "brief description of the final goal"}

After executing each step, you'll get the result. Then respond with:
{"action": "next"} — to continue to next step
{"action": "fix", "tool": "tool_name", "args": {...}} — if a step failed, try a fix
{"action": "done", "summary": "what was accomplished"} — when all steps complete

### For simple chat (no tools needed):
Just respond with text. No JSON needed.

## Available tools:
- shell: Run shell commands. Args: {command: str}
- file_read: Read files. Args: {path: str}
- file_write: Write to /tmp. Args: {path: str, content: str}
- file_list: List /tmp. Args: {path?: str}
- browse: Fetch webpage. Args: {url: str}
- search: Web search. Args: {query: str}
- convert: Convert files. Args: {file_path: str, target_fmt: str}
- ppt: Generate PPT. Args: {content: str}

## Rules:
- Reply in the user's language. Be concise.
- When planning, always start with information gathering if needed.
- If a step fails, try to fix it before giving up.
- Report progress after every 2-3 steps.
- Always explain what you're doing and why."""


LEARN_PROMPT = """You are a skill extractor. Analyze this completed task and determine if it created a reusable skill.

Task: {task}
Steps executed:
{steps}
Result: {result}

If this task can be reused for similar future requests, respond with JSON:
{{"skill_name": "short_descriptive_name", "description": "what this skill does", "keywords": ["word1", "word2", ...], "steps": [{{"tool": "...", "args": {{...}}, "desc": "..."}}], "category": "coding|fileops|web|system|data"}}

If not reusable, respond with: {{"skill_name": null}}"""


# ---------------------------------------------------------------------------
# HermesAgent
# ---------------------------------------------------------------------------

class HermesAgent:
    """
    Autonomous agent with 3 capabilities:
    1. Tool-using — execute tools
    2. Autonomous — plan, auto-chain, progress tracking
    3. Learning — extract and store skills
    """

    def __init__(
        self,
        api_keys: list[str],
        api_base: str = "https://api.xiaomimimo.com/v1",
        model: str = "mimo-v2.5",
        max_tool_rounds: int = 15,
        timeout: int = 120,
    ):
        self.api_keys = api_keys
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_tool_rounds = max(1, min(max_tool_rounds, 15))
        self.timeout = timeout
        self._key_idx = 0

        # Per-chat history
        self._history: dict[int, list[dict]] = {}
        self._max_history = 30

        # Per-chat active plan
        self._plans: dict[int, dict] = {}

        # Skills store
        self._skills_file = "/tmp/hermes_skills.json"
        self._skills: dict[str, dict] = self._load_skills()

        # Max chars for tool output
        self._max_tool_output = 3000

        logger.info(
            "HermesAgent v2: model=%s, keys=%d, skills=%d",
            model, len(api_keys), len(self._skills),
        )

    # ------------------------------------------------------------------
    # LLM
    # ------------------------------------------------------------------

    def _next_key(self) -> str:
        key = self.api_keys[self._key_idx % len(self.api_keys)]
        self._key_idx += 1
        return key

    def _chat(self, messages: list[dict], max_tokens: int = 800, temperature: float = 0.3) -> str:
        """Chat completion with key rotation."""
        last_error = None
        for _ in range(len(self.api_keys)):
            key = self._next_key()
            payload = json.dumps({
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }).encode()
            req = urllib.request.Request(
                f"{self.api_base}/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {key}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    result = json.loads(resp.read())
                    choices = result.get("choices")
                    if not choices or not isinstance(choices, list):
                        last_error = "Empty choices"
                        continue
                    content = choices[0].get("message", {}).get("content", "")
                    if not content:
                        last_error = "Empty content"
                        continue
                    return content.strip()
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    last_error = "HTTP 401"
                    continue
                last_error = f"HTTP {e.code}"
                break
            except Exception as e:
                last_error = str(e)[:200]
                break

        logger.error("LLM error: %s", last_error)
        return f"⚠️ LLM error: {last_error}"

    def _llm_fn(self, messages: list[dict], max_tokens: int = 800) -> str:
        return self._chat(messages, max_tokens=max_tokens)

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    def _parse_json(self, text: str) -> Optional[dict]:
        """Extract JSON from LLM response."""
        text = text.strip()
        if not text.startswith("{"):
            # Try to find JSON in text
            start = text.find("{")
            if start == -1:
                return None
            text = text[start:]

        depth = 0
        in_string = False
        escape = False
        for i, c in enumerate(text):
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[:i + 1])
                    except json.JSONDecodeError:
                        break
        return None

    # ------------------------------------------------------------------
    # Core: process message
    # ------------------------------------------------------------------

    def process(self, chat_id: int, user_message: str, progress_fn=None) -> str:
        """
        Process user message — supports 3 modes:
        1. Simple chat (no tools)
        2. Quick task (1-2 tool calls)
        3. Autonomous multi-step plan

        progress_fn: optional callback(step_num, total, desc) for progress updates
        """
        if chat_id not in self._history:
            self._history[chat_id] = []

        # Check if there's an active plan to continue
        if chat_id in self._plans:
            return self._continue_plan(chat_id, user_message, progress_fn)

        # Check for skill match
        skill = self._find_skill(user_message)
        if skill:
            logger.info("Skill matched: %s", skill.get("name"))

        # Add user message to history
        self._history[chat_id].append({"role": "user", "content": user_message})
        self._trim_history(chat_id)

        # Build context with skill hint if found
        system = SYSTEM_PROMPT
        if skill:
            system += f"\n\n## Known skill: {skill['name']}\n{skill.get('description', '')}\nSteps: {json.dumps(skill.get('steps', []), indent=2)}"

        messages = [{"role": "system", "content": system}]
        messages.extend(self._history[chat_id])

        # Agent loop
        response = ""
        for round_num in range(self.max_tool_rounds):
            response = self._chat(messages, max_tokens=1000)
            if response.startswith("⚠️"):
                break

            parsed = self._parse_json(response)
            if not parsed:
                # Plain text response — done
                break

            action = parsed.get("action", "")

            # --- Quick tool call ---
            if action == "tool":
                tool_name = parsed.get("tool", "")
                tool_args = parsed.get("args", {})
                if not isinstance(tool_args, dict):
                    tool_args = {}

                result = execute_tool(tool_name, tool_args, llm_fn=self._llm_fn)
                output = result.get("output", "")[:self._max_tool_output]

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": f"Tool result ({tool_name}):\n{output}\n\nGive final response to user.",
                })
                continue

            # --- Autonomous plan ---
            if action == "plan":
                steps = parsed.get("steps", [])
                goal = parsed.get("goal", user_message)
                if steps:
                    return self._start_plan(chat_id, goal, steps, messages, progress_fn)
                break

            # --- Plan step responses ---
            if action in ("next", "fix"):
                # Continue plan (handled by _continue_plan)
                break

            if action == "done":
                summary = parsed.get("summary", "Task completed.")
                # Learn from this task
                self._learn_from_task(chat_id, user_message, summary)
                break

            # Unknown action — treat as text response
            break

        # Save to history
        if not response.startswith("⚠️"):
            self._history[chat_id].append({"role": "assistant", "content": response})

        return response or "⚠️ No response from AI."

    # ------------------------------------------------------------------
    # Autonomous: plan management
    # ------------------------------------------------------------------

    def _start_plan(self, chat_id: int, goal: str, steps: list, messages: list, progress_fn=None) -> str:
        """Start executing an autonomous plan."""
        plan = {
            "goal": goal,
            "steps": steps,
            "current": 0,
            "results": [],
            "messages": messages,  # conversation context
        }
        self._plans[chat_id] = plan

        # Execute first step
        return self._execute_plan_step(chat_id, progress_fn)

    def _continue_plan(self, chat_id: int, user_message: str, progress_fn=None) -> str:
        """Continue executing the current plan."""
        plan = self._plans.get(chat_id)
        if not plan:
            return "No active plan."

        # Add user context to plan messages
        plan["messages"].append({"role": "user", "content": user_message})

        # Ask LLM what to do next
        response = self._chat(plan["messages"], max_tokens=1000)
        parsed = self._parse_json(response)

        if parsed:
            action = parsed.get("action", "")

            if action == "next":
                # Move to next step
                plan["current"] += 1
                return self._execute_plan_step(chat_id, progress_fn)

            if action == "fix":
                # Retry with fix
                tool_name = parsed.get("tool", "")
                tool_args = parsed.get("args", {})
                if tool_name:
                    result = execute_tool(tool_name, tool_args, llm_fn=self._llm_fn)
                    output = result.get("output", "")[:self._max_tool_output]
                    plan["results"][-1] = {"step": plan["current"], "output": output, "fixed": True}

                    plan["messages"].append({"role": "assistant", "content": response})
                    plan["messages"].append({
                        "role": "user",
                        "content": f"Fix result ({tool_name}):\n{output}\n\nContinue or done?",
                    })
                    return f"🔧 Fixing step {plan['current'] + 1}..."

            if action == "done":
                summary = parsed.get("summary", "Plan completed.")
                goal = plan["goal"]
                self._end_plan(chat_id)
                self._learn_from_task(chat_id, goal, summary)
                return f"✅ *Plan complete:* {goal}\n\n{summary}"

        # Default: try to continue
        plan["current"] += 1
        if plan["current"] >= len(plan["steps"]):
            self._end_plan(chat_id)
            return f"✅ *Plan complete:* {plan['goal']}\n\nAll {len(plan['steps'])} steps executed."

        return self._execute_plan_step(chat_id, progress_fn)

    def _execute_plan_step(self, chat_id: int, progress_fn=None) -> str:
        """Execute the current step of a plan."""
        plan = self._plans.get(chat_id)
        if not plan:
            return "No active plan."

        current = plan["current"]
        steps = plan["steps"]

        if current >= len(steps):
            self._end_plan(chat_id)
            return f"✅ *Plan complete:* {plan['goal']}"

        step = steps[current]
        tool_name = step.get("tool", "")
        tool_args = step.get("args", {})
        desc = step.get("desc", f"Step {current + 1}")

        # Report progress
        if progress_fn:
            progress_fn(current + 1, len(steps), desc)

        # Execute tool
        result = execute_tool(tool_name, tool_args, llm_fn=self._llm_fn)
        output = result.get("output", "")[:self._max_tool_output]
        success = result.get("success", False)

        plan["results"].append({"step": current, "output": output, "success": success})

        # Add to plan messages
        plan["messages"].append({
            "role": "user",
            "content": (
                f"Step {current + 1}/{len(steps)} [{tool_name}]: {desc}\n"
                f"Result: {'✅' if success else '❌'}\n{output}\n\n"
                f"{'Next step or done?' if success else 'This step failed. Try fix or skip?'}\n"
                'Respond with: {"action": "next"} or {"action": "fix", "tool": "...", "args": {...}} or {"action": "done", "summary": "..."}'
            ),
        })

        # Auto-continue if successful
        if success:
            plan["current"] += 1
            if plan["current"] >= len(steps):
                goal = plan["goal"]
                summary = f"All {len(steps)} steps completed successfully."
                self._end_plan(chat_id)
                self._learn_from_task(chat_id, goal, summary)
                return f"✅ *Plan complete:* {goal}\n\n{summary}"
            return f"⏳ Step {current + 1}/{len(steps)} ✅ — continuing..."
        else:
            return f"⚠️ Step {current + 1} failed. Waiting for fix..."

    def _end_plan(self, chat_id: int) -> None:
        """Clean up plan state."""
        plan = self._plans.pop(chat_id, None)
        if plan:
            # Save final context to history
            goal = plan.get("goal", "")
            results_count = len(plan.get("results", []))
            self._history[chat_id].append({
                "role": "assistant",
                "content": f"[Completed plan: {goal} — {results_count} steps]",
            })

    # ------------------------------------------------------------------
    # Learning: skill extraction and storage
    # ------------------------------------------------------------------

    def _learn_from_task(self, chat_id: int, task: str, result: str) -> None:
        """After a successful task, try to extract a reusable skill."""
        try:
            steps_text = ""
            history = self._history.get(chat_id, [])
            for msg in history[-10:]:
                if msg["role"] == "assistant":
                    steps_text += f"  {msg['content'][:200]}\n"

            prompt = LEARN_PROMPT.format(
                task=task,
                steps=steps_text or "(tool calls)",
                result=result[:500],
            )
            response = self._chat(
                [{"role": "system", "content": "Reply ONLY with valid JSON."},
                 {"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.1,
            )
            parsed = self._parse_json(response)
            if parsed and parsed.get("skill_name"):
                self._save_skill(parsed)
                logger.info("Learned skill: %s", parsed["skill_name"])
        except Exception as e:
            logger.debug("Skill extraction failed: %s", e)

    def _save_skill(self, skill: dict) -> None:
        """Save a skill to disk."""
        import hashlib
        name = skill.get("name", skill.get("skill_name", "unknown"))
        skill_id = hashlib.sha256(name.encode()).hexdigest()[:12]
        skill["id"] = skill_id
        skill["name"] = name
        skill["success_count"] = 1
        skill["created_at"] = time.time()

        self._skills[skill_id] = skill
        self._persist_skills()

    def _load_skills(self) -> dict:
        """Load skills from disk."""
        try:
            with open(self._skills_file, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _persist_skills(self) -> None:
        """Save all skills to disk atomically."""
        try:
            tmp = self._skills_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._skills, f, indent=2, ensure_ascii=False, default=str)
            os.replace(tmp, self._skills_file)
        except Exception as e:
            logger.error("Failed to persist skills: %s", e)

    def _find_skill(self, query: str) -> Optional[dict]:
        """Find a matching skill for a user query."""
        if not self._skills:
            return None
        query_lower = query.lower()
        tokens = set(query_lower.split())
        best, best_score = None, 0

        for skill in self._skills.values():
            score = 0
            keywords = skill.get("keywords", [])
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in query_lower:
                    score += 3
                elif any(t in kw_lower for t in tokens):
                    score += 1
            if query_lower in skill.get("description", "").lower():
                score += 2
            if score > best_score:
                best_score = score
                best = skill

        return best if best_score >= 2 else None

    def list_skills(self) -> list[dict]:
        """Return all stored skills."""
        return sorted(self._skills.values(), key=lambda s: s.get("name", ""))

    def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill."""
        if skill_id in self._skills:
            del self._skills[skill_id]
            self._persist_skills()
            return True
        return False

    # ------------------------------------------------------------------
    # History management
    # ------------------------------------------------------------------

    def clear_history(self, chat_id: int) -> None:
        self._history.pop(chat_id, None)
        self._plans.pop(chat_id, None)

    def _trim_history(self, chat_id: int) -> None:
        if len(self._history[chat_id]) > self._max_history:
            trim_to = self._max_history - (self._max_history % 2)
            self._history[chat_id] = self._history[chat_id][-trim_to:]

    def cleanup_old_chats(self, max_chats: int = 100) -> int:
        if len(self._history) <= max_chats:
            return 0
        to_remove = len(self._history) - max_chats
        sorted_ids = sorted(self._history.keys())
        for cid in sorted_ids[:to_remove]:
            self._history.pop(cid, None)
            self._plans.pop(cid, None)
        return to_remove
