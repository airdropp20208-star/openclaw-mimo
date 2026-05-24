"""
File Operations Tool
====================
Read, write, list, search, and manage files with safe path handling.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from . import BaseTool

logger = logging.getLogger(__name__)

# Maximum file size for read operations (10 MB)
MAX_READ_SIZE = 10 * 1024 * 1024

# Default base directory (project root)
DEFAULT_BASE_DIR = os.environ.get("HERMES_WORKDIR", os.getcwd())


def _safe_path(path: str, base_dir: str = DEFAULT_BASE_DIR) -> Path:
    """Resolve a path safely, ensuring it stays within base_dir.

    Prevents path traversal attacks.
    """
    base = Path(base_dir).resolve()
    target = (base / path).resolve()

    # Allow if the target is within the base directory or is a symlink that resolves there
    try:
        target.relative_to(base)
    except ValueError:
        # Also allow absolute paths that are under the base
        if not str(target).startswith(str(base)):
            raise PermissionError(
                f"Path '{path}' is outside the allowed directory: {base}"
            )

    return target


class FileOpsTool(BaseTool):
    """Read, write, list, and search files with safe path handling."""

    name = "file_ops"
    description = (
        "Perform file operations: read, write, append, list, search, "
        "delete, mkdir, or stat. All paths are resolved safely within "
        "the working directory."
    )
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation to perform: read, write, append, list, search, delete, mkdir, stat.",
            "required": True,
        },
        "path": {
            "type": "string",
            "description": "File or directory path (relative to working directory).",
            "required": False,
        },
        "content": {
            "type": "string",
            "description": "Content to write (for write/append operations).",
            "required": False,
        },
        "pattern": {
            "type": "string",
            "description": "Glob pattern for list or regex pattern for search.",
            "required": False,
        },
        "recursive": {
            "type": "boolean",
            "description": "Whether to recurse into subdirectories (default: false).",
            "required": False,
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum results for list/search (default: 100).",
            "required": False,
        },
    }

    def execute(
        self,
        operation: str,
        path: str | None = None,
        content: str | None = None,
        pattern: str | None = None,
        recursive: bool = False,
        max_results: int = 100,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute a file operation.

        Args:
            operation: One of read, write, append, list, search, delete, mkdir, stat.
            path: File/directory path.
            content: Content for write/append.
            pattern: Glob or regex pattern.
            recursive: Whether to recurse.
            max_results: Max results to return.

        Returns:
            Dict with success, output, and operation-specific data.
        """
        operations = {
            "read": self._read,
            "write": self._write,
            "append": self._append,
            "list": self._list,
            "search": self._search,
            "delete": self._delete,
            "mkdir": self._mkdir,
            "stat": self._stat,
        }

        handler = operations.get(operation)
        if handler is None:
            return {
                "success": False,
                "output": f"Unknown operation: {operation}. Supported: {', '.join(operations.keys())}",
                "error": "invalid_operation",
            }

        try:
            return handler(
                path=path,
                content=content,
                pattern=pattern,
                recursive=recursive,
                max_results=max_results,
            )
        except PermissionError as exc:
            return {"success": False, "output": str(exc), "error": "permission_error"}
        except FileNotFoundError as exc:
            return {"success": False, "output": str(exc), "error": "file_not_found"}
        except Exception as exc:
            logger.exception("File operation '%s' failed", operation)
            return {"success": False, "output": f"Operation failed: {exc}", "error": str(exc)}

    # ── Individual operations ──────────────────────────────────────────

    def _read(self, path: str | None = None, **_: Any) -> Dict[str, Any]:
        if not path:
            return {"success": False, "output": "path is required for read", "error": "missing_param"}

        target = _safe_path(path)

        if not target.exists():
            return {"success": False, "output": f"File not found: {path}", "error": "file_not_found"}

        if not target.is_file():
            return {"success": False, "output": f"Not a file: {path}", "error": "not_a_file"}

        file_size = target.stat().st_size
        if file_size > MAX_READ_SIZE:
            return {
                "success": False,
                "output": f"File too large: {file_size} bytes (max: {MAX_READ_SIZE})",
                "error": "file_too_large",
            }

        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except UnicodeDecodeError:
            return {
                "success": False,
                "output": "File is binary and cannot be read as text",
                "error": "binary_file",
            }

        return {
            "success": True,
            "output": text,
            "path": str(target),
            "size": file_size,
        }

    def _write(self, path: str | None = None, content: str | None = None, **_: Any) -> Dict[str, Any]:
        if not path:
            return {"success": False, "output": "path is required for write", "error": "missing_param"}
        if content is None:
            return {"success": False, "output": "content is required for write", "error": "missing_param"}

        target = _safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(content, encoding="utf-8")
        file_size = target.stat().st_size

        return {
            "success": True,
            "output": f"Written {file_size} bytes to {path}",
            "path": str(target),
            "size": file_size,
        }

    def _append(self, path: str | None = None, content: str | None = None, **_: Any) -> Dict[str, Any]:
        if not path:
            return {"success": False, "output": "path is required for append", "error": "missing_param"}
        if content is None:
            return {"success": False, "output": "content is required for append", "error": "missing_param"}

        target = _safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)

        with open(target, "a", encoding="utf-8") as f:
            f.write(content)

        file_size = target.stat().st_size

        return {
            "success": True,
            "output": f"Appended to {path} (total size: {file_size})",
            "path": str(target),
            "size": file_size,
        }

    def _list(self, path: str | None = None, pattern: str | None = None,
              recursive: bool = False, max_results: int = 100, **_: Any) -> Dict[str, Any]:
        directory = _safe_path(path or ".")
        if not directory.exists():
            return {"success": False, "output": f"Directory not found: {path}", "error": "directory_not_found"}
        if not directory.is_dir():
            return {"success": False, "output": f"Not a directory: {path}", "error": "not_a_directory"}

        glob_pattern = pattern or "*"

        try:
            if recursive and not glob_pattern.startswith("**"):
                glob_pattern = f"**/{glob_pattern}"
            matches = sorted(directory.glob(glob_pattern), key=lambda p: (not p.is_dir(), p.name))
        except Exception as exc:
            return {"success": False, "output": f"Glob error: {exc}", "error": "glob_error"}

        items: List[Dict[str, str]] = []
        for match in matches[:max_results]:
            try:
                rel = match.relative_to(directory)
                items.append({
                    "name": str(rel),
                    "type": "dir" if match.is_dir() else "file",
                    "size": str(match.stat().st_size) if match.is_file() else "-",
                })
            except (PermissionError, OSError):
                continue

        return {
            "success": True,
            "output": f"Found {len(items)} items in {path or '.'}",
            "items": items,
            "count": len(items),
            "truncated": len(list(directory.glob(glob_pattern))) > max_results,
        }

    def _search(self, path: str | None = None, pattern: str | None = None,
                recursive: bool = True, max_results: int = 100, **_: Any) -> Dict[str, Any]:
        if not pattern:
            return {"success": False, "output": "pattern (regex) is required for search", "error": "missing_param"}

        search_dir = _safe_path(path or ".")
        if not search_dir.exists():
            return {"success": False, "output": f"Directory not found: {path}", "error": "directory_not_found"}

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return {"success": False, "output": f"Invalid regex: {exc}", "error": "invalid_regex"}

        results: List[Dict[str, Any]] = []

        try:
            file_pattern = "**/*" if recursive else "*"
            for file_path in search_dir.glob(file_pattern):
                if not file_path.is_file():
                    continue
                # Skip binary and huge files
                try:
                    file_size = file_path.stat().st_size
                    if file_size > MAX_READ_SIZE or file_size == 0:
                        continue
                    text = file_path.read_text(encoding="utf-8", errors="ignore")
                except (PermissionError, OSError):
                    continue

                for line_no, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel = file_path.relative_to(search_dir)
                        results.append({
                            "file": str(rel),
                            "line": line_no,
                            "text": line.strip()[:200],
                        })
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break
        except Exception as exc:
            return {"success": False, "output": f"Search error: {exc}", "error": "search_error"}

        return {
            "success": True,
            "output": f"Found {len(results)} matches for pattern '{pattern}'",
            "matches": results,
            "count": len(results),
        }

    def _delete(self, path: str | None = None, **_: Any) -> Dict[str, Any]:
        if not path:
            return {"success": False, "output": "path is required for delete", "error": "missing_param"}

        target = _safe_path(path)
        if not target.exists():
            return {"success": False, "output": f"File not found: {path}", "error": "file_not_found"}

        # Safety: only delete files, not directories (to prevent accidental rm -rf)
        if target.is_dir():
            import shutil
            shutil.rmtree(target)
        else:
            target.unlink()

        return {
            "success": True,
            "output": f"Deleted: {path}",
            "path": str(target),
        }

    def _mkdir(self, path: str | None = None, **_: Any) -> Dict[str, Any]:
        if not path:
            return {"success": False, "output": "path is required for mkdir", "error": "missing_param"}

        target = _safe_path(path)
        target.mkdir(parents=True, exist_ok=True)

        return {
            "success": True,
            "output": f"Created directory: {path}",
            "path": str(target),
        }

    def _stat(self, path: str | None = None, **_: Any) -> Dict[str, Any]:
        if not path:
            return {"success": False, "output": "path is required for stat", "error": "missing_param"}

        target = _safe_path(path)
        if not target.exists():
            return {"success": False, "output": f"Not found: {path}", "error": "file_not_found"}

        stat = target.stat()
        return {
            "success": True,
            "output": f"Path: {path}",
            "path": str(target),
            "type": "dir" if target.is_dir() else "file",
            "size": stat.st_size,
            "mode": oct(stat.st_mode),
            "modified": stat.st_mtime,
        }
