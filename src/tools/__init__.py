"""
Hermes-OpenManus Tools Layer
============================
Provides a BaseTool abstract class and ToolRegistry for managing all tools
used by the OpenManus executor. Each tool is a class with name, description,
parameters schema, and an execute(**kwargs) -> dict method.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class BaseTool(ABC):
    """Abstract base class for all Hermes-OpenManus tools."""

    name: str = "base"
    description: str = "Base tool"
    parameters: Dict[str, Any] = {}

    def __init__(self) -> None:
        logger.debug("Initialized tool: %s", self.name)

    @abstractmethod
    def execute(self, **_kwargs: Any) -> Dict[str, Any]:
        """Execute the tool with given parameters.

        Returns:
            A dict with at minimum:
              - "success": bool
              - "output": str (human-readable result)
              Additional keys may include "data", "error", etc.

        Subclasses should accept tool-specific keyword arguments.
        """
        ...

    def validate_params(self, **kwargs: Any) -> List[str]:
        """Validate required parameters are present.

        Returns:
            List of missing parameter names (empty if all present).
        """
        missing: List[str] = []
        for param_name, param_def in self.parameters.items():
            if isinstance(param_def, dict) and param_def.get("required", False):
                if param_name not in kwargs or kwargs[param_name] is None:
                    missing.append(param_name)
        return missing

    def safe_execute(self, **kwargs: Any) -> Dict[str, Any]:
        """Execute with validation and top-level error handling."""
        missing = self.validate_params(**kwargs)
        if missing:
            return {
                "success": False,
                "output": f"Missing required parameters: {', '.join(missing)}",
                "error": "validation_error",
            }
        try:
            result = self.execute(**kwargs)
            if not isinstance(result, dict):
                result = {"success": True, "output": str(result)}
            return result
        except Exception as exc:
            logger.exception("Tool '%s' execution failed", self.name)
            return {
                "success": False,
                "output": f"Tool execution failed: {exc}",
                "error": str(exc),
            }

    def to_schema(self) -> Dict[str, Any]:
        """Return tool metadata as a schema dict for LLM consumption."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"


class ToolRegistry:
    """Manages registration and lookup of all tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if tool.name in self._tools:
            logger.warning("Overwriting existing tool: %s", tool.name)
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if removed."""
        if name in self._tools:
            del self._tools[name]
            logger.info("Unregistered tool: %s", name)
            return True
        return False

    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Return schemas for all registered tools."""
        return [tool.to_schema() for tool in self._tools.values()]

    def execute(self, tool_name: str, **kwargs: Any) -> Dict[str, Any]:
        """Execute a tool by name with parameters."""
        tool = self.get(tool_name)
        if tool is None:
            return {
                "success": False,
                "output": f"Unknown tool: {tool_name}",
                "error": "tool_not_found",
            }
        return tool.safe_execute(**kwargs)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={self.list_tools()}>"


def register_default_tools(registry: ToolRegistry) -> ToolRegistry:
    """Import and register all default tools into the given registry.

    Returns:
        The populated registry.
    """
    from .browser import BrowserTool
    from .file_ops import FileOpsTool
    from .media import MediaTool
    from .search import SearchTool
    from .shell import ShellTool

    for tool_cls in [ShellTool, BrowserTool, FileOpsTool, SearchTool, MediaTool]:
        registry.register(tool_cls())

    logger.info("Registered %d default tools", len(registry))
    return registry
