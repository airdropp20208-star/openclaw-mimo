"""
AI Executor
===========
Runs planned steps using the appropriate tools and returns structured results.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _import_tool(tool_name: str):
    """Import a tool module by name."""
    if tool_name == "shell":
        from tools import shell
        return shell
    elif tool_name == "browser":
        from tools import browser
        return browser
    elif tool_name == "file_ops":
        from tools import file_ops
        return file_ops
    elif tool_name == "search":
        from tools import search
        return search
    elif tool_name == "media":
        from tools import media
        return media
    else:
        raise ValueError(f"Unknown tool: {tool_name}")


def execute_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Execute a complete plan with all its steps.

    Args:
        plan: A plan dict with 'steps' list (from reasoner).

    Returns:
        Structured result with step outputs, success status, and final output.
    """
    steps = plan.get("steps", [])
    if not steps:
        return {
            "success": False,
            "output": "No steps to execute",
            "error": "empty_plan",
        }

    logger.info("Executing plan with %d steps", len(steps))

    step_results: list[dict[str, Any]] = []
    step_outputs: dict[int, Any] = {}
    all_success = True
    start_time = time.time()

    for step in steps:
        step_num = step.get("step_number", 0)
        tool_name = step.get("tool")
        tool_params = step.get("tool_params", {})
        description = step.get("description", f"Step {step_num}")

        logger.info("Step %d: %s (tool=%s)", step_num, description, tool_name)

        # Check dependencies
        deps = step.get("depends_on", [])
        for dep in deps:
            if dep not in step_outputs:
                logger.warning("Step %d depends on step %d which hasn't run", step_num, dep)
                step_result = {
                    "step_number": step_num,
                    "success": False,
                    "output": f"Dependency step {dep} not available",
                    "error": "dependency_not_met",
                }
                all_success = False
                step_results.append(step_result)
                continue

        # Inject outputs from dependent steps into params
        for dep in deps:
            dep_output = step_outputs.get(dep, {})
            if isinstance(dep_output, dict):
                for key, value in dep_output.items():
                    if key not in tool_params:
                        tool_params[f"dep_{dep}_{key}"] = value

        # Execute the tool
        if tool_name:
            step_result = execute_tool(tool_name, tool_params)
        else:
            # No tool needed — return a pass-through
            step_result = {
                "success": True,
                "output": description,
                "no_tool_needed": True,
            }

        step_result["step_number"] = step_num
        step_result["description"] = description
        step_results.append(step_result)
        step_outputs[step_num] = step_result

        if not step_result.get("success", False):
            all_success = False
            logger.warning("Step %d failed: %s", step_num, step_result.get("output", "unknown"))
            # Stop on failure (could be configurable)
            break

    elapsed = time.time() - start_time

    # Build final output
    last_result = step_results[-1] if step_results else {}
    final_output = last_result.get("output", "")

    return {
        "success": all_success,
        "output": final_output,
        "steps_executed": len(step_results),
        "step_results": step_results,
        "elapsed_seconds": round(elapsed, 2),
        "plan": plan,
    }


def execute_tool(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a single tool with given parameters.

    Args:
        tool_name: Name of the tool (shell, browser, file_ops, search, media).
        params: Tool parameters.

    Returns:
        Tool execution result dict.
    """
    try:
        logger.info("Executing tool '%s' with params: %s", tool_name, {k: str(v)[:100] for k, v in params.items()})
        tool_module = _import_tool(tool_name)
        result = tool_module.execute(**params)

        if not isinstance(result, dict):
            result = {"success": True, "output": str(result)}

        logger.info("Tool '%s' result: success=%s", tool_name, result.get("success", False))
        return result

    except Exception as exc:
        logger.exception("Tool '%s' execution failed", tool_name)
        return {
            "success": False,
            "output": f"Tool execution failed: {exc}",
            "error": str(exc),
        }


def execute_single(task: str) -> dict[str, Any]:
    """Quick execution: classify task, plan, and execute in one call.

    Args:
        task: The user's task description.

    Returns:
        Combined reason + execute result.
    """
    from ai.reasoner import reason

    logger.info("Quick execution for: %s", task[:100])

    # Reason
    plan = reason(task)

    # Execute
    result = execute_plan(plan)

    # Attach reasoning info
    result["task"] = task
    result["reasoning"] = {
        "intent": plan.get("intent", ""),
        "complexity": plan.get("complexity", "unknown"),
        "steps_planned": len(plan.get("steps", [])),
    }

    return result
