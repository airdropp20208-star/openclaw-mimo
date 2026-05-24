"""
File Operations Tool
====================
Read, write, list, search, and manage files with safe path handling.
Self-contained — no BaseTool dependency.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Maximum file size for read operations (10 MB)
MAX_READ_SIZE = 10 * 1024 * 1024

# Default base directory (project root)
DEFAULT_BASE_DIR = os.environ.get("HERMES_WORKDIR", os.getcwd())


def _safe_path(path: str, base_dir: str = DEFAULT_BASE_DIR) -> Path:
    """Resolve a path safely, ensuring it stays within base_dir."""
    base = Path(base_dir).resolve()
    target = (base / path).resolve()

    try:
        target.relative_to(base)
    except ValueError:
        if not str(target).startswith(str(base)):
            raise PermissionError(
                f"Path '{path}' is outside the allowed directory: {base}"
            )

    return target


def execute(
    operation: str,
    path: str | None = None,
    content: str | None = None,
    pattern: str | None = None,
    recursive: bool = False,
    max_results: int = 100,
    **kwargs: Any,
) -> dict[str, Any]:
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
        "read": _read,
        "write": _write,
        "append": _append,
        "list": _list,
        "search": _search,
        "delete": _delete,
        "mkdir": _mkdir,
        "stat": _stat,
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


def _read(path: str | None = None, **_: Any) -> dict[str, Any]:
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


def _write(path: str | None = None, content: str | None = None, **_: Any) -> dict[str, Any]:
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


def _append(path: str | None = None, content: str | None = None, **_: Any) -> dict[str, Any]:
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


def _list(
    path: str | None = None,
    pattern: str | None = None,
    recursive: bool = False,
    max_results: int = 100,
    **_: Any,
) -> dict[str, Any]:
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

    items: list[dict[str, str]] = []
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
    }


def _search(
    path: str | None = None,
    pattern: str | None = None,
    recursive: bool = True,
    max_results: int = 100,
    **_: Any,
) -> dict[str, Any]:
    if not pattern:
        return {"success": False, "output": "pattern (regex) is required for search", "error": "missing_param"}

    search_dir = _safe_path(path or ".")
    if not search_dir.exists():
        return {"success": False, "output": f"Directory not found: {path}", "error": "directory_not_found"}

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return {"success": False, "output": f"Invalid regex: {exc}", "error": "invalid_regex"}

    results: list[dict[str, Any]] = []

    try:
        file_pattern = "**/*" if recursive else "*"
        for file_path in search_dir.glob(file_pattern):
            if not file_path.is_file():
                continue
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


def _delete(path: str | None = None, **_: Any) -> dict[str, Any]:
    if not path:
        return {"success": False, "output": "path is required for delete", "error": "missing_param"}

    target = _safe_path(path)
    if not target.exists():
        return {"success": False, "output": f"File not found: {path}", "error": "file_not_found"}

    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

    return {
        "success": True,
        "output": f"Deleted: {path}",
        "path": str(target),
    }


def _mkdir(path: str | None = None, **_: Any) -> dict[str, Any]:
    if not path:
        return {"success": False, "output": "path is required for mkdir", "error": "missing_param"}

    target = _safe_path(path)
    target.mkdir(parents=True, exist_ok=True)

    return {
        "success": True,
        "output": f"Created directory: {path}",
        "path": str(target),
    }


def _stat(path: str | None = None, **_: Any) -> dict[str, Any]:
    if not path:
        return {"success": False, "output": "path is required for stat", "error": "missing_param"}

    target = _safe_path(path)
    if not target.exists():
        return {"success": False, "output": f"Not found: {path}", "error": "file_not_found"}

    st = target.stat()
    return {
        "success": True,
        "output": f"Path: {path}",
        "path": str(target),
        "type": "dir" if target.is_dir() else "file",
        "size": st.st_size,
        "mode": oct(st.st_mode),
        "modified": st.st_mtime,
    }
