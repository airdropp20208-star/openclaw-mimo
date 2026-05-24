"""
OpenManus Tools — shell, file, browser, search, convert, ppt.
Each tool returns {"success": bool, "output": str}.
"""

import os
import re
import shlex
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

# Max sizes to prevent OOM
MAX_FILE_READ = 100_000       # 100KB
MAX_HTTP_READ = 500_000       # 500KB
MAX_SHELL_OUTPUT = 5000       # 5KB

# Blocked shell commands (dangerous)
_BLOCKED_CMDS = [
    "rm -rf /", "rm -rf /*", "mkfs", ":(){ :|:& };:",
    "dd if=/dev/zero", "dd if=/dev/random",
    "> /dev/sda", "chmod -R 777 /", "chown -R",
]
# Regex patterns for pipe injection
_BLOCKED_PATTERNS = [
    r"wget\s+.*\|\s*(ba)?sh",
    r"curl\s+.*\|\s*(ba)?sh",
]

# Private/internal IPs for SSRF protection
_PRIVATE_HOSTS = {
    "localhost", "127.0.0.1", "0.0.0.0", "::1",
    "169.254.169.254",  # cloud metadata
    "[::1]", "[::ffff:127.0.0.1]",
}


def _is_private_ip(hostname: str) -> bool:
    """Check if hostname resolves to a private/internal IP."""
    if not hostname:
        return True
    h = hostname.lower().strip("[]")
    if h in _PRIVATE_HOSTS:
        return True
    # RFC 1918 ranges
    parts = h.split(".")
    if len(parts) == 4:
        try:
            nums = [int(p) for p in parts]
            if (nums[0] == 10 or
                nums[0] == 172 and 16 <= nums[1] <= 31 or
                nums[0] == 192 and nums[1] == 168 or
                nums[0] == 0):
                return True
        except ValueError:
            pass
    return False


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------

def shell_exec(command: str, timeout: int = 60) -> dict[str, Any]:
    """Execute a shell command with sandboxing."""
    if not command or not command.strip():
        return {"success": False, "output": "Empty command"}

    # Block dangerous commands
    cmd_lower = command.lower().strip()
    for blocked in _BLOCKED_CMDS:
        if blocked in cmd_lower:
            return {"success": False, "output": f"Blocked: dangerous command detected"}
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower):
            return {"success": False, "output": f"Blocked: dangerous command detected"}

    timeout = max(5, min(timeout, 300))

    # Use process group so we can kill on timeout
    try:
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            output = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
            truncated = False
            if len(output) > MAX_SHELL_OUTPUT:
                output = output[:MAX_SHELL_OUTPUT]
                truncated = True
            if truncated:
                output += "\n... (truncated)"
            return {"success": proc.returncode == 0, "output": output or "(no output)"}
        except subprocess.TimeoutExpired:
            # Kill the entire process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.wait()
            return {"success": False, "output": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "output": f"Error: {str(e)[:500]}"}


# ---------------------------------------------------------------------------
# File operations (sandboxed to /tmp)
# ---------------------------------------------------------------------------

def file_read(path: str) -> dict[str, Any]:
    """Read a file (with size limit, restricted to safe paths)."""
    if not path:
        return {"success": False, "output": "No path provided"}
    # Block sensitive files
    sensitive = ["/etc/shadow", "/etc/passwd", ".ssh/", ".env", "id_rsa"]
    for s in sensitive:
        if s in path:
            return {"success": False, "output": f"Access denied: sensitive file"}
    try:
        size = os.path.getsize(path)
        if size > 1_000_000:
            return {"success": False, "output": f"File too large ({size} bytes, max 1MB)"}
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_FILE_READ)
        return {"success": True, "output": content}
    except FileNotFoundError:
        return {"success": False, "output": f"Not found: {path}"}
    except PermissionError:
        return {"success": False, "output": f"Permission denied: {path}"}
    except Exception as e:
        return {"success": False, "output": str(e)[:500]}


def file_write(path: str, content: str) -> dict[str, Any]:
    """Write content to a file (restricted to /tmp)."""
    if not path:
        return {"success": False, "output": "No path provided"}
    # Sandbox: only allow /tmp
    if not path.startswith("/tmp/"):
        path = f"/tmp/{os.path.basename(path)}"
    try:
        os.makedirs(os.path.dirname(path) or "/tmp", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content[:500_000])
        return {"success": True, "output": f"Wrote {len(content)} chars to {path}"}
    except Exception as e:
        return {"success": False, "output": str(e)[:500]}


def file_list(path: str = "/tmp") -> dict[str, Any]:
    """List files in a directory (restricted to /tmp)."""
    if not path:
        path = "/tmp"
    real = os.path.realpath(path)
    if not real.startswith("/tmp/"):
        return {"success": False, "output": "Access denied: can only list /tmp"}
    try:
        entries = sorted(os.listdir(path))[:200]
        return {"success": True, "output": "\n".join(entries) or "(empty)"}
    except Exception as e:
        return {"success": False, "output": str(e)[:500]}


# ---------------------------------------------------------------------------
# Browser / Web
# ---------------------------------------------------------------------------

def browse_url(url: str) -> dict[str, Any]:
    """Fetch a webpage and return text content."""
    if not url:
        return {"success": False, "output": "No URL provided"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    # Block internal/private URLs
    parsed = urllib.parse.urlparse(url)
    if _is_private_ip(parsed.hostname or ""):
        return {"success": False, "output": "Access denied: internal/private URL blocked"}
    if parsed.scheme == "file":
        return {"success": False, "output": "Access denied: file:// URLs blocked"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(MAX_HTTP_READ)
            html = raw.decode("utf-8", errors="ignore")
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()[:5000]
        return {"success": True, "output": text}
    except Exception as e:
        return {"success": False, "output": f"Error: {str(e)[:300]}"}


def web_search(query: str) -> dict[str, Any]:
    """Search the web via DuckDuckGo."""
    if not query:
        return {"success": False, "output": "No query provided"}
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(MAX_HTTP_READ)
            html = raw.decode("utf-8", errors="ignore")
        results = re.findall(
            r'class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>', html
        )
        if results:
            out = f"Results for: {query}\n\n"
            for i, (link, title) in enumerate(results[:5], 1):
                out += f"{i}. {title.strip()}\n{link}\n\n"
            return {"success": True, "output": out}
        return {"success": True, "output": "No results found."}
    except Exception as e:
        return {"success": False, "output": f"Search error: {str(e)[:300]}"}


# ---------------------------------------------------------------------------
# File conversion
# ---------------------------------------------------------------------------

def file_convert(file_path: str, target_fmt: str) -> dict[str, Any]:
    """Convert a file to another format."""
    if not file_path:
        return {"success": False, "output": "No file path provided"}
    if not target_fmt:
        return {"success": False, "output": "No target format"}
    if not target_fmt.startswith(".") or len(target_fmt) > 10:
        target_fmt = f".{target_fmt.lstrip('.')}"
    if not re.match(r"^\.\w{1,6}$", target_fmt):
        return {"success": False, "output": f"Invalid format: {target_fmt}"}

    ext = os.path.splitext(file_path)[1].lower()
    # Use UUID to avoid collision
    uid = tempfile.mktemp(suffix=target_fmt, prefix="converted_")
    out = f"/tmp/{uid}"

    converters = {
        (".pdf", ".md"): f'markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}',
        (".docx", ".md"): f'markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}',
        (".pptx", ".md"): f'markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}',
        (".xlsx", ".md"): f'markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}',
        (".mp4", ".mp3"): f'ffmpeg -i {shlex.quote(file_path)} -q:a 0 -map a {shlex.quote(out)} -y',
        (".mp4", ".gif"): f'ffmpeg -i {shlex.quote(file_path)} -vf fps=10,scale=480:-1 {shlex.quote(out)} -y',
        (".png", ".jpg"): f'convert {shlex.quote(file_path)} {shlex.quote(out)}',
        (".jpg", ".png"): f'convert {shlex.quote(file_path)} {shlex.quote(out)}',
    }
    cmd = converters.get((ext, target_fmt))
    if not cmd:
        return {"success": False, "output": f"Unsupported conversion: {ext} → {target_fmt}"}

    result = shell_exec(cmd, timeout=120)
    if os.path.exists(out):
        size = os.path.getsize(out)
        result["output"] = f"Converted → {out} ({size} bytes)"
        result["file"] = out
    else:
        result["success"] = False
        if not result.get("output") or result["output"] == "(no output)":
            result["output"] = "Conversion failed: output file not created"
    return result


# ---------------------------------------------------------------------------
# PPT generation
# ---------------------------------------------------------------------------

def generate_ppt(content: str, llm_fn=None) -> dict[str, Any]:
    """Generate a PowerPoint from text content."""
    if llm_fn is None:
        return {"success": False, "output": "No LLM configured for PPT generation"}
    if not content:
        return {"success": False, "output": "No content provided"}

    prompt = f"""Create a professional PowerPoint presentation from this content.
Return ONLY the python-pptx code to generate the PPT.
Content: {content[:3000]}

Requirements:
- Title slide
- Content slides with bullet points
- Professional styling
- Save to /tmp/presentation.pptx"""

    code = llm_fn(
        [{"role": "system", "content": "Return only executable python-pptx code, no explanation."},
         {"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    for fence in ("```python", "```"):
        if fence in code:
            code = code.split(fence, 1)[1].split("```")[0].strip()
            break

    code_lines = [l.strip() for l in code.split("\n") if l.strip()]
    if not code_lines:
        return {"success": False, "output": "Empty code from LLM"}

    # Use UUID to avoid race condition
    script_path = tempfile.mktemp(suffix=".py", prefix="ppt_gen_")
    ppt_path = tempfile.mktemp(suffix=".pptx", prefix="presentation_")

    # Patch the save path in the code
    code = code.replace("/tmp/presentation.pptx", ppt_path)

    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)

    result = shell_exec(f"python3 {shlex.quote(script_path)}", timeout=60)

    try:
        os.unlink(script_path)
    except Exception:
        pass

    if os.path.exists(ppt_path):
        size = os.path.getsize(ppt_path)
        result["output"] = f"PPT created ({size} bytes)"
        result["file"] = ppt_path
    else:
        result["success"] = False
        if not result.get("output") or result["output"] == "(no output)":
            result["output"] = "PPT generation failed"
    return result


# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS: dict[str, dict[str, Any]] = {
    "shell": {
        "fn": shell_exec,
        "description": "Execute a shell command. Args: {command: str, timeout?: int}",
    },
    "file_read": {
        "fn": file_read,
        "description": "Read a file (max 1MB). Args: {path: str}",
    },
    "file_write": {
        "fn": file_write,
        "description": "Write to /tmp. Args: {path: str, content: str}",
    },
    "file_list": {
        "fn": file_list,
        "description": "List /tmp. Args: {path?: str}",
    },
    "browse": {
        "fn": browse_url,
        "description": "Fetch webpage. Args: {url: str}",
    },
    "search": {
        "fn": web_search,
        "description": "Web search. Args: {query: str}",
    },
    "convert": {
        "fn": file_convert,
        "description": "Convert file format. Args: {file_path: str, target_fmt: str}",
    },
    "ppt": {
        "fn": generate_ppt,
        "description": "Generate PowerPoint. Args: {content: str}",
        "needs_llm": True,
    },
}


def execute_tool(name: str, args: dict[str, Any], llm_fn=None) -> dict[str, Any]:
    """Execute a tool by name with given args."""
    tool = TOOLS.get(name)
    if not tool:
        return {"success": False, "output": f"Unknown tool: {name}. Available: {', '.join(TOOLS)}"}

    if not isinstance(args, dict):
        return {"success": False, "output": f"Args must be a dict, got {type(args).__name__}"}

    fn = tool["fn"]
    try:
        if tool.get("needs_llm"):
            return fn(llm_fn=llm_fn, **args)
        return fn(**args)
    except TypeError as e:
        return {"success": False, "output": f"Invalid args for {name}: {e}"}
    except Exception as e:
        return {"success": False, "output": f"Tool {name} error: {str(e)[:300]}"}
