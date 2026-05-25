"""
Hermes Agent — core agent loop with tool calling.

Uses OpenAI-compatible API (Xiaomi MiMo) for LLM.
Tools are OpenManus-style (shell, file, browser, search, convert, ppt).

Features:
- Autonomous planning (goals, subtasks, self-initiation)
- Learning (pattern extraction, skill library)
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from tools import TOOLS, execute_tool
from planner import Planner
from learner import Learner

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Hermes — an autonomous general AI agent.
You are proficient in solving complex tasks using a wide range of tools in your VPS environment.

CORE PRINCIPLES:
1. AUTONOMY: You don't just answer questions; you solve problems. If a task requires multiple steps, plan them and execute them one by one.
2. TOOL-FIRST: For any task that involves external information, file manipulation, or computation, use your tools immediately.
3. SELF-RELIANCE: If a tool is missing or a package is not installed, use the 'shell' tool to install it (e.g., pip install, apt-get).
4. ERROR CORRECTION: If a tool call fails, analyze the error and try a different approach. Do not give up.
5. CHAINING: You can and should chain multiple tool calls to achieve a goal.

AVAILABLE TOOLS:
- shell: Execute ANY shell command. Use this to install dependencies, run scripts, or explore the system. Args: {command: str}
- file_read: Read file content. Args: {path: str}
- file_write: Create/overwrite files. Use this to write scripts or save data. Args: {path: str, content: str}
- file_list: List files in a directory. Args: {path: str}
- browse: Access a URL and extract content. Args: {url: str}
- search: Search the web for information. Args: {query: str}
- convert: Convert file formats (PDF to MD, MP4 to MP3, etc.). Args: {file_path: str, target_fmt: str}
- ppt: Generate a professional PowerPoint presentation. Args: {content: str}

THOUGHT PROCESS:
Before every action or response, you MUST perform an internal monologue. Analyze the current state, evaluate previous tool results, and plan your next move.
Format your thought process as:
THOUGHT: <your reasoning here>
ACTION: {"tool": "tool_name", "args": {...}}

If no action is needed, just provide the final response after your THOUGHT.

After each tool execution, you will receive the result. Continue the loop until the task is complete.
When finished, provide a comprehensive final response to the user in their language.
Use professional, academic style and markdown for clarity."""


class HermesAgent:
    """
    Agent loop with tool calling + autonomous planning + learning.

    Flow:
    1. User message → LLM (with tool definitions + skill/goal context)
    2. LLM returns tool call → execute tool → send result back to LLM
    3. Repeat until LLM gives final text response
    4. After completion: record task, extract pattern, learn skill
    """

    def __init__(
        self,
        api_keys: list[str],
        api_base: str = "https://api.xiaomimimo.com/v1",
        model: str = "mimo-v2.5",
        max_tool_rounds: int = 10,
        timeout: int = 120,
        autonomous_mode: bool = True,  # Enable autonomous planning
        learning_mode: bool = True,    # Enable learning
    ):
        self.api_keys = api_keys
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.max_tool_rounds = max(1, min(max_tool_rounds, 10))
        self.timeout = timeout
        self._key_idx = 0

        # Autonomous mode
        self.autonomous_mode = autonomous_mode
        # Learning mode
        self.learning_mode = learning_mode

        # Per-chat history
        self._history: dict[int, list[dict]] = {}
        self._max_history = 24

        # Per-chat planner + learner
        self._planners: dict[int, Planner] = {}
        self._learners: dict[int, Learner] = {}

        # Max chars for tool output injected into messages
        self._max_tool_output = 3000

        logger.info(
            "HermesAgent initialized: model=%s, keys=%d, base=%s, autonomous=%s, learning=%s",
            model, len(api_keys), api_base, autonomous_mode, learning_mode,
        )

    def _get_planner(self, chat_id: int) -> Planner:
        if chat_id not in self._planners:
            self._planners[chat_id] = Planner(chat_id)
        return self._planners[chat_id]

    def _get_learner(self, chat_id: int) -> Learner:
        if chat_id not in self._learners:
            self._learners[chat_id] = Learner(chat_id)
        return self._learners[chat_id]

    def _next_key(self) -> str:
        key = self.api_keys[self._key_idx % len(self.api_keys)]
        self._key_idx += 1
        return key

    def _chat(self, messages: list[dict], max_tokens: int = 800, temperature: float = 0.3) -> dict:
        """Send chat completion request to LLM with key rotation and retry. Returns message dict."""
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
                        last_error = "Empty choices in response"
                        continue
                    msg = choices[0].get("message", {})
                    return msg
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    logger.warning("Key invalid (401), rotating...")
                    last_error = f"HTTP 401"
                    continue
                last_error = f"HTTP {e.code}: {e.reason}"
                break
            except Exception as e:
                last_error = str(e)[:200]
                break

        logger.error("LLM error: %s", last_error)
        return f"⚠️ LLM error: {last_error}"

    def _llm_fn(self, messages: list[dict], max_tokens: int = 800) -> str:
        """LLM call wrapper for tools that need it (e.g. PPT)."""
        msg = self._chat(messages, max_tokens=max_tokens)
        if isinstance(msg, dict):
            return msg.get("content", "")
        return str(msg)

    def _parse_tool_call(self, msg: Any) -> Optional[dict]:
        """Extract a JSON tool call from LLM response message."""
        # 1. Handle OpenAI-style tool_calls
        if isinstance(msg, dict) and msg.get("tool_calls"):
            tc = msg["tool_calls"][0]
            if tc.get("function"):
                fn = tc["function"]
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                    return {"tool": fn.get("name"), "args": args}
                except json.JSONDecodeError:
                    pass

        # 2. Handle text-based JSON (legacy or non-standard)
        text = ""
        if isinstance(msg, dict):
            text = msg.get("content", "") or ""
        elif isinstance(msg, str):
            text = msg
        
        text = text.strip()
        if not text:
            return None

        # 3. Handle THOUGHT/ACTION format
        if "ACTION:" in text:
            action_part = text.split("ACTION:", 1)[1].strip()
            try:
                # Try to find JSON within the action part
                import re
                match = re.search(r"\{.*\}", action_part, re.DOTALL)
                if match:
                    obj = json.loads(match.group())
                    if isinstance(obj, dict) and "tool" in obj:
                        return obj
            except json.JSONDecodeError:
                pass

        # Look for JSON-like structures
        import re
        # Try to find anything that looks like {"tool": ...}
        matches = re.findall(r"\{.*\}", text, re.DOTALL)
        for potential_json in matches:
            try:
                # Clean up markdown code blocks if present
                clean_json = potential_json.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:].strip()
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3].strip()
                
                obj = json.loads(clean_json)
                if isinstance(obj, dict):
                    # Standard Hermes format: {"tool": "name", "args": {}}
                    if "tool" in obj:
                        return obj
                    # Some LLMs might return {"name": "tool_name", "arguments": {}}
                    if "name" in obj and ("arguments" in obj or "args" in obj):
                        return {"tool": obj["name"], "args": obj.get("arguments") or obj.get("args")}
            except json.JSONDecodeError:
                continue
        
        return None

    def _is_error_response(self, msg: Any) -> bool:
        if isinstance(msg, str):
            return msg.startswith("⚠️ LLM error:")
        return False

    def _truncate_tool_output(self, output: str) -> str:
        if len(output) > self._max_tool_output:
            return output[:self._max_tool_output] + "\n... (truncated)"
        return output

    def _build_system_prompt(self, chat_id: int) -> str:
        """Build system prompt with skill/goal context injection."""
        parts = [SYSTEM_PROMPT]

        # Inject learned skills
        if self.learning_mode:
            learner = self._get_learner(chat_id)
            skill_ctx = learner.export_for_prompt()
            if skill_ctx:
                parts.append(f"\n{skill_ctx}")

        # Inject autonomous goals
        if self.autonomous_mode:
            planner = self._get_planner(chat_id)
            goal_ctx = planner.export_for_prompt()
            if goal_ctx:
                parts.append(f"\n{goal_ctx}")

        return "\n".join(parts)

    def process(self, chat_id: int, user_message: str) -> str:
        """
        Process a user message through the agent loop.
        Returns the final text response.
        """
        # Initialize history for this chat
        if chat_id not in self._history:
            self._history[chat_id] = []

        # Add user message
        self._history[chat_id].append({"role": "user", "content": user_message})

        # Trim history (keep pairs intact)
        if len(self._history[chat_id]) > self._max_history:
            trim_to = self._max_history - (self._max_history % 2)
            self._history[chat_id] = self._history[chat_id][-trim_to:]

        # Build messages with dynamic system prompt (includes skills + goals)
        system_prompt = self._build_system_prompt(chat_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._history[chat_id])

        # Agent loop — track tool calls for learning
        response = ""
        tools_used = []
        tool_rounds = 0
        start_time = time.time()

        final_text = ""
        for round_num in range(self.max_tool_rounds):
            msg_obj = self._chat(messages)

            if self._is_error_response(msg_obj):
                final_text = msg_obj if isinstance(msg_obj, str) else "⚠️ LLM error"
                break

            tool_call = self._parse_tool_call(msg_obj)
            if tool_call:
                tool_name = str(tool_call.get("tool", ""))
                tool_args = tool_call.get("args", {})

                if not tool_name:
                    final_text = msg_obj.get("content", "") if isinstance(msg_obj, dict) else str(msg_obj)
                    break

                tool_rounds += 1
                logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_args, default=str)[:200])

                tools_used.append(tool_name)

                # Execute the tool
                # Inject chat_id into args if needed by goal_manage
                if tool_name == "goal_manage" and "args" not in tool_args:
                    tool_args["args"] = {"chat_id": chat_id}
                elif tool_name == "goal_manage" and isinstance(tool_args.get("args"), dict):
                    tool_args["args"]["chat_id"] = chat_id

                result = execute_tool(tool_name, tool_args, llm_fn=self._llm_fn, agent=self)
                tool_output = self._truncate_tool_output(result.get("output", ""))

                # --- ADVANCED REFLECTION ---
                # If tool failed or output looks suspicious, ask LLM to reflect
                if not result.get("success") or "error" in tool_output.lower() or "failed" in tool_output.lower():
                    logger.info("Triggering reflection for tool: %s", tool_name)
                    reflection_prompt = f"""The tool '{tool_name}' returned an error or suspicious output.
Tool Args: {json.dumps(tool_args)}
Output: {tool_output}

Analyze why this happened and suggest a fix or an alternative approach.
If it's a syntax error, provide the corrected command.
If a resource is missing, suggest how to get it.
Return your analysis and the next ACTION to take."""
                    
                    reflection_msg = self._chat([
                        {"role": "system", "content": "You are the Reflection Engine for Hermes. Analyze failures and provide fixes."},
                        {"role": "user", "content": reflection_prompt}
                    ])
                    
                    if isinstance(reflection_msg, dict) and reflection_msg.get("content"):
                        tool_output += f"\n\n[REFLECTION]: {reflection_msg['content']}"

                # Add tool call and result to messages
                assistant_content = msg_obj.get("content", "") or json.dumps(tool_call)
                messages.append({"role": "assistant", "content": assistant_content})
                
                result_text = f"Tool result ({tool_name}):\n{tool_output}"
                if result.get("file"):
                    result_text += f"\nFile: {result['file']}"
                messages.append({"role": "user", "content": result_text})

                continue

            # No tool call — this is the final response
            final_text = msg_obj.get("content", "") if isinstance(msg_obj, dict) else str(msg_obj)
            break

        # Save to history (only if no error)
        if not self._is_error_response(final_text):
            self._history[chat_id].append({"role": "assistant", "content": final_text})

        # --- Learning: record successful task execution ---
        if self.learning_mode and tools_used and not self._is_error_response(final_text):
            duration = time.time() - start_time
            try:
                learner = self._get_learner(chat_id)
                learner.learn_from_task(
                    user_request=user_message,
                    tools_used=tools_used,
                    success=True,
                    duration_sec=duration,
                    output_summary=final_text[:300],
                    llm_fn=self._llm_fn,
                )
            except Exception as e:
                logger.warning("Learning failed: %s", e)

        return final_text or "⚠️ No response from AI."

        # --- Learning: record successful task execution ---
        if self.learning_mode and tools_used and not self._is_error_response(response):
            duration = time.time() - start_time
            try:
                learner = self._get_learner(chat_id)
                learner.learn_from_task(
                    user_request=user_message,
                    tools_used=tools_used,
                    success=True,
                    duration_sec=duration,
                    output_summary=response[:300],
                    llm_fn=self._llm_fn,
                )
            except Exception as e:
                logger.warning("Learning failed: %s", e)

        return response or "⚠️ No response from AI."

    # --- Goal Management (for bot commands) ---

    def add_goal(
        self,
        chat_id: int,
        description: str,
        priority: int = 5,
        deadline: Optional[str] = None,
        subtasks: Optional[list[str]] = None,
    ) -> str:
        """Add a new goal. Returns confirmation message."""
        planner = self._get_planner(chat_id)
        if subtasks is None:
            # Use LLM to decompose
            if self.autonomous_mode:
                subtasks = planner.decompose_goal(description, llm_fn=self._llm_fn)
            else:
                subtasks = [description]

        goal = planner.add_goal(description, priority, deadline, subtasks)
        return (
            f"🎯 Goal added: {goal.goal_id}\n"
            f"📝 {description}\n"
            f"Priority: {priority} | Subtasks: {len(goal.subtasks)}\n"
            + "\n".join(f"  • {st['description']}" for st in goal.subtasks)
        )

    def complete_subtask(self, chat_id: int, subtask_id: str, result: str = "") -> str:
        planner = self._get_planner(chat_id)
        goal = planner.complete_subtask(subtask_id, result)
        if goal:
            if goal.status == "completed":
                return f"🎉 Goal {goal.goal_id} completed! ({goal.progress}%)"
            return f"✅ Subtask {subtask_id} done. Goal {goal.goal_id}: {goal.progress}%"
        return f"❌ Subtask {subtask_id} not found."

    def get_goals(self, chat_id: int) -> str:
        planner = self._get_planner(chat_id)
        return planner.get_summary()

    def delete_goal(self, chat_id: int, goal_id: str) -> str:
        planner = self._get_planner(chat_id)
        if planner.delete_goal(goal_id):
            return f"🗑 Goal {goal_id} deleted."
        return f"❌ Goal {goal_id} not found."

    def pause_goal(self, chat_id: int, goal_id: str) -> str:
        planner = self._get_planner(chat_id)
        if planner.pause_goal(goal_id):
            return f"⏸ Goal {goal_id} paused."
        return f"❌ Goal {goal_id} not found or not active."

    def resume_goal(self, chat_id: int, goal_id: str) -> str:
        planner = self._get_planner(chat_id)
        if planner.resume_goal(goal_id):
            return f"▶ Goal {goal_id} resumed."
        return f"❌ Goal {goal_id} not found or not paused."

    def get_next_actions(self, chat_id: int) -> str:
        """Get recommended next actions based on goals."""
        planner = self._get_planner(chat_id)
        actions = planner.get_next_actions(llm_fn=self._llm_fn)
        if not actions:
            return "📭 No pending actions. All goals clear!"

        lines = ["⚡ *Recommended Next Actions:*\n"]
        for i, a in enumerate(actions, 1):
            lines.append(
                f"{i}. [{a['goal_id']}] {a['action']}\n"
                f"   {a['reason']} | Priority: {a['priority']}"
            )
        return "\n".join(lines)

    # --- Skill/Learning Management (for bot commands) ---

    def get_skills(self, chat_id: int) -> str:
        learner = self._get_learner(chat_id)
        return learner.get_summary()

    def get_skill(self, chat_id: int, skill_id: str) -> str:
        learner = self._get_learner(chat_id)
        skill = learner.get_skill(skill_id)
        if not skill:
            return f"❌ Skill {skill_id} not found."

        return (
            f"📚 *{skill.name}*\n"
            f"ID: {skill.skill_id}\n"
            f"Category: {skill.category}\n"
            f"Description: {skill.description}\n"
            f"Tools: {' → '.join(skill.tool_sequence)}\n"
            f"Success rate: {skill.success_rate}% ({skill.success_count} uses)\n"
            f"Triggers: {', '.join(skill.triggers)}\n"
            f"Template: {skill.template or 'none'}"
        )

    def delete_skill(self, chat_id: int, skill_id: str) -> str:
        learner = self._get_learner(chat_id)
        if learner.delete_skill(skill_id):
            return f"🗑 Skill {skill_id} deleted."
        return f"❌ Skill {skill_id} not found."

    def get_learning_stats(self, chat_id: int) -> str:
        learner = self._get_learner(chat_id)
        stats = learner.get_stats()
        return (
            f"📊 *Learning Stats*\n"
            f"Tasks recorded: {stats['total_tasks']}\n"
            f"Success rate: {stats['success_rate']}%\n"
            f"Skills learned: {stats['total_skills']}\n"
            f"Categories: {', '.join(stats['categories']) or 'none'}"
        )

    # --- History Management ---

    def clear_history(self, chat_id: int) -> None:
        self._history.pop(chat_id, None)

    def cleanup_old_chats(self, max_chats: int = 100) -> int:
        all_ids = set(self._history) | set(self._planners) | set(self._learners)
        if len(all_ids) <= max_chats:
            return 0
        to_remove = len(all_ids) - max_chats
        sorted_ids = sorted(all_ids)
        for chat_id in sorted_ids[:to_remove]:
            self._history.pop(chat_id, None)
            self._planners.pop(chat_id, None)
            self._learners.pop(chat_id, None)
        return to_remove

    def chat_only(self, chat_id: int, user_message: str) -> str:
        """Simple chat without tool calling."""
        if chat_id not in self._history:
            self._history[chat_id] = []

        self._history[chat_id].append({"role": "user", "content": user_message})

        if len(self._history[chat_id]) > self._max_history:
            trim_to = self._max_history - (self._max_history % 2)
            self._history[chat_id] = self._history[chat_id][-trim_to:]

        messages = [
            {"role": "system", "content": "You are Hermes, a helpful AI assistant. Reply in the user's language. Be concise."},
        ]
        messages.extend(self._history[chat_id])

        response = self._chat(messages)

        if not self._is_error_response(response):
            self._history[chat_id].append({"role": "assistant", "content": response})

        return response or "⚠️ No response from AI."
