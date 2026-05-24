"""
OpenManus Executor – task execution engine with a tool-registry pattern.

The Executor receives a task from the router, decomposes it into an ordered
list of *steps*, and executes each step using the appropriate registered tool.
All tool invocations are recorded so the Brain can extract reusable patterns
after the task completes.

Supported built-in tools
------------------------
* **shell**    – run shell commands
* **file**     – read / write / list files
* **browser**  – open URLs, take screenshots (stub; plug in real impl)
* **search**   – web search (stub; plug in real impl)

Custom tools can be registered via :py:meth:`ToolRegistry.register`.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool abstraction
# ---------------------------------------------------------------------------

class Tool(ABC):
    """Base class for all executor tools."""

    name: str
    description: str

    @abstractmethod
    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        Run the tool with *args* and return a structured result.

        Returns
        -------
        ``{"success": bool, "output": str, "error": str | None, ...}``
        """

    def to_schema(self) -> dict[str, Any]:
        """Return a JSON-schema-like dict describing the tool for LLM prompts."""
        return {"name": self.name, "description": self.description}


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------

class ShellTool(Tool):
    """Execute shell commands."""

    name = "shell"
    description = "Run a shell command and return its output."

    def __init__(self, *, timeout: int = 120, cwd: str | None = None) -> None:
        self._timeout = timeout
        self._cwd = cwd

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        command = args.get("command", "")
        if not command:
            return {"success": False, "output": "", "error": "No command provided"}

        cwd = args.get("cwd", self._cwd)
        timeout = args.get("timeout", self._timeout)

        logger.info("Shell: %s (cwd=%s)", command, cwd)
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr or None,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"Command timed out after {timeout}s",
            }
        except Exception as exc:
            return {"success": False, "output": "", "error": str(exc)}


class FileTool(Tool):
    """Read, write, and list files."""

    name = "file"
    description = "Read, write, or list files on disk."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args.get("action", "read")
        path = args.get("path", "")

        if not path:
            return {"success": False, "output": "", "error": "No path provided"}

        try:
            if action == "read":
                content = Path(path).read_text(encoding="utf-8")
                return {"success": True, "output": content}
            elif action == "write":
                content = args.get("content", "")
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(content, encoding="utf-8")
                return {"success": True, "output": f"Wrote {len(content)} chars to {path}"}
            elif action == "list":
                entries = sorted(
                    str(p) for p in Path(path).iterdir()
                ) if Path(path).is_dir() else [str(path)]
                return {"success": True, "output": "\n".join(entries)}
            else:
                return {"success": False, "output": "", "error": f"Unknown action: {action}"}
        except Exception as exc:
            return {"success": False, "output": "", "error": str(exc)}


class BrowserTool(Tool):
    """Stub browser tool – real implementation requires playwright / selenium."""

    name = "browser"
    description = "Open a URL, take a screenshot, or interact with a webpage."

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args.get("action", "open")
        url = args.get("url", "")
        logger.info("Browser [%s]: %s", action, url)

        # Attempt to use playwright if available
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-untyped]
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=30_000)
                if action == "screenshot":
                    out_path = args.get("output_path", "/tmp/screenshot.png")
                    page.screenshot(path=out_path)
                    browser.close()
                    return {"success": True, "output": f"Screenshot saved to {out_path}"}
                title = page.title()
                content = page.content()[:5000]
                browser.close()
                return {"success": True, "output": f"Title: {title}\n\n{content[:2000]}"}
        except ImportError:
            return {
                "success": False,
                "output": "",
                "error": "playwright not installed – install with: pip install playwright",
            }
        except Exception as exc:
            return {"success": False, "output": "", "error": str(exc)}


class SearchTool(Tool):
    """Stub search tool – plugs into any search API."""

    name = "search"
    description = "Search the web for information."

    def __init__(self, *, api_fn: Optional[Callable[[str], str]] = None) -> None:
        self._api_fn = api_fn

    def execute(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "")
        if not query:
            return {"success": False, "output": "", "error": "No query provided"}

        if self._api_fn is not None:
            try:
                result = self._api_fn(query)
                return {"success": True, "output": result}
            except Exception as exc:
                return {"success": False, "output": "", "error": str(exc)}

        return {
            "success": False,
            "output": "",
            "error": "No search API configured – set api_fn in SearchTool",
        }


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool
        logger.info("Tool registered: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def list_schemas(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self._tools.values()]


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    """Result of executing a single step."""
    step_index: int
    tool_name: str
    args: dict[str, Any]
    output: str
    success: bool
    error: str | None = None
    duration_ms: float = 0.0


@dataclass
class TaskResult:
    """Aggregated result of a full task execution."""
    task_id: str
    task_description: str
    steps: list[StepResult] = field(default_factory=list)
    final_output: str = ""
    success: bool = True
    total_duration_ms: float = 0.0
    tool_sequence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_description": self.task_description,
            "steps": [
                {
                    "step_index": s.step_index,
                    "tool": s.tool_name,
                    "args": s.args,
                    "output": s.output[:500],
                    "success": s.success,
                    "error": s.error,
                    "duration_ms": s.duration_ms,
                }
                for s in self.steps
            ],
            "final_output": self.final_output,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
        }


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class OpenManusExecutor:
    """
    Decomposes tasks into steps and executes them via registered tools.

    Optionally uses an LLM to break complex descriptions into an ordered
    plan of tool invocations.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry | None = None,
        llm_fn: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self._registry = registry or self._default_registry()
        self._llm_fn = llm_fn

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_task(
        self,
        task_description: str,
        *,
        task_id: str = "",
        max_steps: int = 20,
    ) -> TaskResult:
        """Execute a full task end-to-end."""
        if not task_id:
            task_id = f"task_{int(time.time())}"

        result = TaskResult(task_id=task_id, task_description=task_description)
        start = time.time()

        # 1. Decompose into steps
        steps = self._decompose(task_description)
        logger.info("Task %s decomposed into %d steps", task_id, len(steps))

        # 2. Execute each step sequentially
        for idx, step in enumerate(steps[:max_steps]):
            step_result = self._execute_step(idx, step)
            result.steps.append(step_result)
            result.tool_sequence.append({
                "tool": step_result.tool_name,
                "args": step_result.args,
            })

            if not step_result.success:
                result.success = False
                result.final_output = f"Failed at step {idx}: {step_result.error}"
                break
        else:
            # All steps completed
            last = result.steps[-1] if result.steps else None
            result.final_output = last.output if last else ""

        result.total_duration_ms = (time.time() - start) * 1000
        return result

    # ------------------------------------------------------------------
    # Step decomposition
    # ------------------------------------------------------------------

    def _decompose(self, task_description: str) -> list[dict[str, Any]]:
        """Convert a natural-language task into a list of step dicts."""
        if self._llm_fn is not None:
            return self._llm_decompose(task_description)

        # Simple heuristic decomposition – treat the whole task as one step
        # Try to detect shell commands
        if any(
            kw in task_description.lower()
            for kw in ("run ", "execute ", "install ", "pip ", "npm ", "git ", "docker ")
        ):
            return [{"tool": "shell", "args": {"command": task_description}}]
        if any(
            kw in task_description.lower()
            for kw in ("read ", "write ", "create file", "save ")
        ):
            return [{"tool": "file", "args": {"action": "read", "path": task_description}}]

        return [{"tool": "shell", "args": {"command": task_description}}]

    def _llm_decompose(self, task_description: str) -> list[dict[str, Any]]:
        """Ask the LLM to produce a structured step plan."""
        assert self._llm_fn is not None

        tool_schemas = json.dumps(self._registry.list_schemas(), indent=2)
        system = (
            f"You are a task planner. Given a user task, produce a JSON array of steps.\n"
            f"Available tools:\n{tool_schemas}\n\n"
            "Return ONLY a JSON array:\n"
            '[{"tool": "<tool_name>", "args": {<arguments>}}, ...]\n'
            "Keep steps minimal and ordered. If only one step is needed, return a single-element array."
        )

        try:
            raw = self._llm_fn(system, task_description)
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as exc:
            logger.warning("LLM decomposition failed, using heuristic: %s", exc)
        # Fallback
        return [{"tool": "shell", "args": {"command": task_description}}]

    # ------------------------------------------------------------------
    # Single step execution
    # ------------------------------------------------------------------

    def _execute_step(self, index: int, step: dict[str, Any]) -> StepResult:
        """Execute a single step and return a StepResult."""
        tool_name = step.get("tool", "shell")
        args = step.get("args", {})

        tool = self._registry.get(tool_name)
        if tool is None:
            return StepResult(
                step_index=index,
                tool_name=tool_name,
                args=args,
                output="",
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        start = time.time()
        try:
            result = tool.execute(args)
            duration = (time.time() - start) * 1000
            return StepResult(
                step_index=index,
                tool_name=tool_name,
                args=args,
                output=result.get("output", ""),
                success=result.get("success", False),
                error=result.get("error"),
                duration_ms=duration,
            )
        except Exception as exc:
            duration = (time.time() - start) * 1000
            return StepResult(
                step_index=index,
                tool_name=tool_name,
                args=args,
                output="",
                success=False,
                error=str(exc),
                duration_ms=duration,
            )

    # ------------------------------------------------------------------
    # Default setup
    # ------------------------------------------------------------------

    @staticmethod
    def _default_registry() -> ToolRegistry:
        """Create a registry pre-loaded with the built-in tools."""
        registry = ToolRegistry()
        registry.register(ShellTool())
        registry.register(FileTool())
        registry.register(BrowserTool())
        registry.register(SearchTool())
        return registry
