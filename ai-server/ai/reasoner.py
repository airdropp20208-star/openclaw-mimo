"""
AI Reasoner
===========
Analyzes user intent, breaks tasks into steps, and selects appropriate tools.
Uses the LLM client for intelligent task decomposition.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Available tools and their descriptions for the LLM
TOOL_CATALOG = {
    "shell": {
        "name": "shell",
        "description": "Execute shell commands on the system",
        "best_for": ["system administration", "code compilation", "package management", "file manipulation via CLI"],
    },
    "browser": {
        "name": "browser",
        "description": "Fetch web pages and extract text content",
        "best_for": ["web research", "URL fetching", "web scraping", "content extraction"],
    },
    "file_ops": {
        "name": "file_ops",
        "description": "Read, write, search, and manage files",
        "best_for": ["file management", "code editing", "document creation", "directory operations"],
    },
    "search": {
        "name": "search",
        "description": "Search the web via DuckDuckGo",
        "best_for": ["information retrieval", "web search", "fact finding", "research"],
    },
    "media": {
        "name": "media",
        "description": "Convert and transform media files (audio, video, images, documents)",
        "best_for": ["file conversion", "media processing", "image resizing", "document conversion"],
    },
}


def _build_reasoning_prompt(task: str, context: dict[str, Any] | None = None) -> str:
    """Build a system prompt for task reasoning."""
    tools_desc = "\n".join(
        f"- {t['name']}: {t['description']} (best for: {', '.join(t['best_for'])})"
        for t in TOOL_CATALOG.values()
    )
    context_str = ""
    if context:
        context_str = f"\nAdditional context: {context}"

    return f"""You are an AI task planner. Analyze the user's task and create an execution plan.

Available tools:
{tools_desc}{context_str}

Respond with a JSON object:
{{
  "intent": "<one-line description of what the user wants>",
  "complexity": "simple|moderate|complex",
  "steps": [
    {{
      "step_number": 1,
      "description": "<what this step does>",
      "tool": "<tool_name or null if no tool needed>",
      "tool_params": {{}},
      "depends_on": [],
      "expected_output": "<what this step produces>"
    }}
  ],
  "final_output_description": "<description of the final result>",
  "estimated_tools_used": ["<list of tool names>"]
}}

Rules:
- Use the minimum number of steps needed
- Each step should be atomic (do one thing well)
- If no tool is needed, set tool to null
- tool_params should match the tool's parameter schema
- Steps can depend on previous steps via step numbers
- Be specific about what each step does
"""


def reason(task: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Analyze user intent and create an execution plan.

    Args:
        task: The user's task description.
        context: Optional additional context.

    Returns:
        A structured plan with intent, steps, and tool selections.
    """
    from llm.client import get_llm_client

    logger.info("Reasoning about task: %s", task[:100])

    system_prompt = _build_reasoning_prompt(task, context)
    user_prompt = f"Task: {task}"

    try:
        client = get_llm_client()
        result = client.structured_output(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=1000,
            temperature=0.1,
        )

        if not result or "steps" not in result:
            logger.warning("LLM returned invalid plan, falling back to simple plan")
            return _simple_fallback_plan(task)

        # Validate and clean the plan
        plan = _validate_plan(result)
        logger.info("Generated plan with %d steps", len(plan.get("steps", [])))
        return plan

    except Exception as exc:
        logger.error("Reasoning failed: %s", exc)
        return _simple_fallback_plan(task)


def _simple_fallback_plan(task: str) -> dict[str, Any]:
    """Generate a simple fallback plan when LLM reasoning fails."""
    return {
        "intent": task,
        "complexity": "simple",
        "steps": [
            {
                "step_number": 1,
                "description": f"Execute task: {task}",
                "tool": "shell",
                "tool_params": {"command": task},
                "depends_on": [],
                "expected_output": "Result of executing the task",
            }
        ],
        "final_output_description": "Result of the task",
        "estimated_tools_used": ["shell"],
    }


def _validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Validate and clean an LLM-generated plan."""
    steps = plan.get("steps", [])
    if not steps:
        return _simple_fallback_plan(plan.get("intent", "unknown task"))

    valid_steps = []
    valid_tool_names = set(TOOL_CATALOG.keys())

    for i, step in enumerate(steps):
        step_num = step.get("step_number", i + 1)
        tool = step.get("tool")
        tool_params = step.get("tool_params", {})

        # Validate tool name
        if tool and tool not in valid_tool_names:
            logger.warning("Invalid tool '%s' in step %d, setting to null", tool, step_num)
            tool = None
            tool_params = {}

        valid_steps.append({
            "step_number": step_num,
            "description": step.get("description", f"Step {step_num}"),
            "tool": tool,
            "tool_params": tool_params,
            "depends_on": step.get("depends_on", []),
            "expected_output": step.get("expected_output", ""),
        })

    plan["steps"] = valid_steps
    return plan


def quick_classify(task: str) -> str:
    """Quick classification of task type for routing.

    Returns one of: 'reasoning', 'execution', 'research', 'media'.
    """
    task_lower = task.lower()

    media_keywords = ["convert", "resize", "compress", "thumbnail", "ffmpeg", "video", "audio", "image", "pdf", "document"]
    research_keywords = ["search", "find", "look up", "research", "google", "browse", "web"]
    execution_keywords = ["run", "execute", "install", "compile", "build", "deploy", "create file", "write file"]

    media_score = sum(1 for kw in media_keywords if kw in task_lower)
    research_score = sum(1 for kw in research_keywords if kw in task_lower)
    execution_score = sum(1 for kw in execution_keywords if kw in task_lower)

    scores = {
        "media": media_score,
        "research": research_score,
        "execution": execution_score,
    }

    max_score = max(scores.values())
    if max_score == 0:
        return "reasoning"

    return max(scores, key=scores.get)  # type: ignore[arg-type]
