"""
Shell Tool
==========
Execute shell commands with timeout, safety checks, and structured output.
Self-contained — no BaseTool dependency.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

# Commands that are never allowed in untrusted contexts
BLOCKED_COMMANDS: list[str] = [
    "rm -rf /",
    "mkfs",
    ":(){ :|:& };:",  # fork bomb
    "dd if=/dev/zero of=/dev/sda",
    "chmod -R 777 /",
    "wget -O- | sh",
    "curl | bash",
]

# Destructive commands that require explicit acknowledgement
DESTRUCTIVE_PATTERNS: list[str] = [
    "rm -rf",
    "rm -fr",
    "shutdown",
    "reboot",
    "halt",
    "init 0",
    "init 6",
    "fdisk",
    "mkfs",
    "> /dev/sd",
]


def _is_blocked(command: str) -> tuple[bool, str]:
    """Check if a command contains blocked patterns."""
    normalized = command.lower().strip()
    for pattern in BLOCKED_COMMANDS:
        if pattern.lower() in normalized:
            return True, f"Blocked dangerous command pattern: {pattern}"
    for pattern in DESTRUCTIVE_PATTERNS:
        if pattern.lower() in normalized:
            return True, f"Potentially destructive command detected: {pattern}"
    return False, ""


def execute(
    command: str,
    timeout: int = 120,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    shell: bool = True,
) -> dict[str, Any]:
    """Execute a shell command.

    Args:
        command: The command string to run.
        timeout: Max execution time in seconds.
        cwd: Working directory.
        env: Extra environment variables.
        shell: Whether to use shell=True.

    Returns:
        Dict with success, output, stdout, stderr, exit_code, timed_out.
    """
    # Safety check
    is_blocked, reason = _is_blocked(command)
    if is_blocked:
        return {
            "success": False,
            "output": f"Command blocked: {reason}",
            "stdout": "",
            "stderr": reason,
            "exit_code": -1,
            "timed_out": False,
            "error": "safety_check_failed",
        }

    # Build environment
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)

    # Validate cwd
    if cwd and not os.path.isdir(cwd):
        return {
            "success": False,
            "output": f"Working directory does not exist: {cwd}",
            "stdout": "",
            "stderr": f"No such directory: {cwd}",
            "exit_code": -1,
            "timed_out": False,
            "error": "invalid_cwd",
        }

    timed_out = False
    stdout = ""
    stderr = ""
    exit_code = -1

    try:
        logger.info("Executing: %s (timeout=%ds)", command[:200], timeout)
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=proc_env,
            shell=shell,
            text=True,
            close_fds=True,
        )

        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            exit_code = proc.returncode or 0
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            stdout, stderr = proc.communicate()
            exit_code = -1
            logger.warning("Command timed out after %ds: %s", timeout, command[:100])

    except FileNotFoundError as exc:
        stderr = f"Command not found: {exc}"
        exit_code = -1
    except PermissionError as exc:
        stderr = f"Permission denied: {exc}"
        exit_code = -1
    except Exception as exc:
        stderr = f"Unexpected error: {exc}"
        exit_code = -1

    # Truncate very long output
    max_output = 100_000
    if len(stdout) > max_output:
        stdout = stdout[:max_output] + f"\n... [truncated, {len(stdout)} total chars]"
    if len(stderr) > max_output:
        stderr = stderr[:max_output] + f"\n... [truncated, {len(stderr)} total chars]"

    success = exit_code == 0 and not timed_out
    output = (
        stdout.strip()
        if stdout.strip()
        else (stderr.strip() if stderr.strip() else "(no output)")
    )

    return {
        "success": success,
        "output": output,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
