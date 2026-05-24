"""
AutoGen Coordinator – optional multi-agent orchestration layer.

If `autogen` (pyautogen) is installed, the coordinator creates a group of
specialised agents that collaborate on complex multi-step tasks.  When the
library is absent, it transparently falls back to a single-agent mode using
the OpenManus executor.

Agent roles
-----------
* **Planner** – breaks the task into subtasks and assigns them.
* **Coder**    – writes / edits code.
* **Critic**   – reviews output, catches errors, requests revisions.
* **Executor** – runs code and reports results back.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_autogen = None  # type: ignore[assignment]
_HAS_AUTOGEN = False
try:
    import autogen as _autogen  # type: ignore[import-untyped, no-redef]
    _HAS_AUTOGEN = True
    logger.info("autogen library detected – multi-agent mode available")
except ImportError:
    logger.info("autogen not installed – using single-agent fallback")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class AgentRole:
    """Describes a coordinator agent."""
    name: str
    system_prompt: str
    model: str = ""
    tools: list[str] = field(default_factory=list)


@dataclass
class Subtask:
    """A unit of work assigned to one agent."""
    id: str
    description: str
    assigned_to: str
    status: str = "pending"  # pending | running | completed | failed
    result: str = ""


@dataclass
class CoordinationPlan:
    """The output of the planner – an ordered list of subtasks."""
    original_task: str
    subtasks: list[Subtask] = field(default_factory=list)


@dataclass
class CoordinationResult:
    """Final result returned by the coordinator."""
    task_id: str
    original_task: str
    plan: CoordinationPlan | None = None
    final_output: str = ""
    success: bool = True
    total_duration_ms: float = 0.0
    agent_logs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "original_task": self.original_task,
            "final_output": self.final_output,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
            "subtask_count": len(self.plan.subtasks) if self.plan else 0,
        }


# ---------------------------------------------------------------------------
# Default agent roles
# ---------------------------------------------------------------------------

DEFAULT_ROLES: list[AgentRole] = [
    AgentRole(
        name="planner",
        system_prompt=(
            "You are a task planner. Given a complex task, break it into "
            "clear, ordered subtasks. Each subtask should be self-contained "
            "and assigned to one of: coder, critic, or executor. "
            "Respond with a JSON array: "
            '[{"id": "1", "description": "...", "assigned_to": "coder|critic|executor"}]'
        ),
    ),
    AgentRole(
        name="coder",
        system_prompt=(
            "You are a skilled software engineer. Write clean, well-documented "
            "code. Always explain your approach before the code."
        ),
    ),
    AgentRole(
        name="critic",
        system_prompt=(
            "You are a code reviewer and quality checker. Review code and "
            "outputs for bugs, security issues, and improvements. Be specific."
        ),
    ),
    AgentRole(
        name="executor",
        system_prompt=(
            "You are a system executor. Run commands, report outputs, and "
            "verify results. Always show command output."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class AutoGenCoordinator:
    """
    Orchestrates multi-agent task execution.

    Falls back to single-agent mode if ``autogen`` is not installed or if
    the task is simple enough not to warrant multi-agent collaboration.
    """

    def __init__(
        self,
        *,
        llm_fn: Optional[Callable[[str, str], str]] = None,
        model_name: str = "mimo-v2.5",
        roles: list[AgentRole] | None = None,
        max_rounds: int = 10,
    ) -> None:
        self._llm_fn = llm_fn
        self._model_name = model_name
        self._roles = roles or DEFAULT_ROLES
        self._max_rounds = max_rounds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def coordinate(
        self,
        task_description: str,
        *,
        task_id: str = "",
        executor_fn: Optional[Callable[[str], str]] = None,
    ) -> CoordinationResult:
        """
        Coordinate a complex task across multiple agents.

        Parameters
        ----------
        task_description:
            The high-level task to accomplish.
        task_id:
            Optional identifier (auto-generated if empty).
        executor_fn:
            ``tool_command → output`` used by the executor agent.
        """
        if not task_id:
            task_id = f"coord_{int(time.time())}"

        result = CoordinationResult(task_id=task_id, original_task=task_description)
        start = time.time()

        if _HAS_AUTOGEN:
            result = self._run_autogen(task_description, result, executor_fn)
        else:
            result = self._run_single_agent(task_description, result, executor_fn)

        result.total_duration_ms = (time.time() - start) * 1000
        return result

    # ------------------------------------------------------------------
    # AutoGen mode
    # ------------------------------------------------------------------

    def _run_autogen(
        self,
        task: str,
        result: CoordinationResult,
        executor_fn: Optional[Callable[[str], str]],
    ) -> CoordinationResult:
        """Run the full multi-agent conversation via autogen."""
        try:
            config_list = [
                {
                    "model": self._model_name,
                    "api_key": "not-needed",
                    "base_url": "http://localhost:11434/v1",  # local Ollama / compatible
                }
            ]

            # Create agents
            planner = _autogen.AssistantAgent(
                name="planner",
                system_message=self._roles[0].system_prompt,
                llm_config={"config_list": config_list},
            )
            coder = _autogen.AssistantAgent(
                name="coder",
                system_message=self._roles[1].system_prompt,
                llm_config={"config_list": config_list},
            )
            critic = _autogen.AssistantAgent(
                name="critic",
                system_message=self._roles[2].system_prompt,
                llm_config={"config_list": config_list},
            )
            executor = _autogen.AssistantAgent(
                name="executor",
                system_message=self._roles[3].system_prompt,
                llm_config={"config_list": config_list},
            )

            user_proxy = _autogen.UserProxyAgent(
                name="user_proxy",
                human_input_mode="NEVER",
                max_consecutive_auto_reply=self._max_rounds,
                is_termination_msg=lambda x: x.get("content", "").rstrip().endswith("DONE"),
            )

            # Start the conversation
            groupchat = _autogen.GroupChat(
                agents=[user_proxy, planner, coder, critic, executor],
                messages=[],
                max_round=self._max_rounds,
                speaker_selection_method="round_robin",
            )
            manager = _autogen.GroupChatManager(groupchat=groupchat, llm_config={"config_list": config_list})

            user_proxy.initiate_chat(manager, message=task)

            # Extract conversation
            messages = groupchat.messages
            final = messages[-1].get("content", "") if messages else ""
            result.final_output = final
            result.agent_logs = [
                {"agent": m.get("name", "?"), "content": m.get("content", "")[:500]}
                for m in messages
            ]

        except Exception as exc:
            logger.error("AutoGen execution failed: %s – falling back", exc)
            result = self._run_single_agent(task, result, executor_fn)

        return result

    # ------------------------------------------------------------------
    # Single-agent fallback
    # ------------------------------------------------------------------

    def _run_single_agent(
        self,
        task: str,
        result: CoordinationResult,
        executor_fn: Optional[Callable[[str], str]],
    ) -> CoordinationResult:
        """Run the task with a single LLM call (no multi-agent)."""
        logger.info("Running in single-agent mode for: %s", task[:80])

        if self._llm_fn is not None:
            system = (
                "You are a helpful AI assistant. Complete the following task "
                "thoroughly. If you need to use tools, describe the commands "
                "you would run and their expected output."
            )
            try:
                output = self._llm_fn(system, task)
                result.final_output = output
                result.agent_logs = [{"agent": "single_agent", "content": output[:1000]}]
            except Exception as exc:
                logger.error("Single-agent LLM call failed: %s", exc)
                result.final_output = f"Error: {exc}"
                result.success = False
        elif executor_fn is not None:
            try:
                output = executor_fn(task)
                result.final_output = output
            except Exception as exc:
                logger.error("Single-agent executor call failed: %s", exc)
                result.final_output = f"Error: {exc}"
                result.success = False
        else:
            result.final_output = "No LLM or executor configured for single-agent mode"
            result.success = False

        return result

    # ------------------------------------------------------------------
    # Planning helpers
    # ------------------------------------------------------------------

    def plan_task(self, task_description: str) -> CoordinationPlan:
        """Use the planner role to decompose a task into subtasks."""
        plan = CoordinationPlan(original_task=task_description)

        if self._llm_fn is None:
            # Default: single subtask
            plan.subtasks = [
                Subtask(
                    id="1",
                    description=task_description,
                    assigned_to="executor",
                )
            ]
            return plan

        planner_role = self._roles[0]
        try:
            raw = self._llm_fn(planner_role.system_prompt, task_description)
            # Parse the JSON array
            import re
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                items = json.loads(match.group())
                for item in items:
                    plan.subtasks.append(Subtask(
                        id=str(item.get("id", len(plan.subtasks) + 1)),
                        description=item.get("description", ""),
                        assigned_to=item.get("assigned_to", "executor"),
                    ))
        except Exception as exc:
            logger.warning("Planning failed: %s – using single subtask", exc)
            plan.subtasks = [
                Subtask(
                    id="1",
                    description=task_description,
                    assigned_to="executor",
                )
            ]

        return plan
