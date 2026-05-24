"""
OpenManus Tools — shell, file, browser, search, convert, ppt.
Each tool returns {"success": bool, "output": str}.
"""

import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------

def shell_exec(command: str, timeout: int = 120) -> dict[str, Any]:
    """Execute a shell command."""
    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=timeout
        )
        output = (r.stdout + r.stderr).strip()[:5000]
        return {"success": r.returncode == 0, "output": output or "(no output)"}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "output": str(e)[:500]}


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def file_read(path: str) -> dict[str, Any]:
    """Read a file."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()[:10000]
        return {"success": True, "output": content}
    except Exception as e:
        return {"success": False, "output": str(e)}


def file_write(path: str, content: str) -> dict[str, Any]:
    """Write content to a file."""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "output": f"Wrote {len(content)} chars to {path}"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def file_list(path: str = "/tmp") -> dict[str, Any]:
    """List files in a directory."""
    try:
        entries = sorted(os.listdir(path))
        return {"success": True, "output": "\n".join(entries) or "(empty)"}
    except Exception as e:
        return {"success": False, "output": str(e)}


# ---------------------------------------------------------------------------
# Browser / Web
# ---------------------------------------------------------------------------

def browse_url(url: str) -> dict[str, Any]:
    """Fetch a webpage and return text content."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Strip HTML
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()[:5000]
        return {"success": True, "output": text}
    except Exception as e:
        return {"success": False, "output": str(e)}


def web_search(query: str) -> dict[str, Any]:
    """Search the web via DuckDuckGo."""
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
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
        return {"success": False, "output": f"Search error: {e}"}


# ---------------------------------------------------------------------------
# File conversion
# ---------------------------------------------------------------------------

def file_convert(file_path: str, target_fmt: str) -> dict[str, Any]:
    """Convert a file to another format."""
    ext = os.path.splitext(file_path)[1].lower()
    out = f"/tmp/converted_{int(time.time())}{target_fmt}"
    converters = {
        (".pdf", ".md"): f'markitdown "{file_path}" -o "{out}"',
        (".docx", ".md"): f'markitdown "{file_path}" -o "{out}"',
        (".pptx", ".md"): f'markitdown "{file_path}" -o "{out}"',
        (".xlsx", ".md"): f'markitdown "{file_path}" -o "{out}"',
        (".mp4", ".mp3"): f'ffmpeg -i "{file_path}" -q:a 0 -map a "{out}" -y',
        (".mp4", ".gif"): f'ffmpeg -i "{file_path}" -vf fps=10,scale=480:-1 "{out}" -y',
        (".png", ".jpg"): f'convert "{file_path}" "{out}"',
        (".jpg", ".png"): f'convert "{file_path}" "{out}"',
    }
    cmd = converters.get((ext, target_fmt))
    if not cmd:
        return {"success": False, "output": f"Unsupported: {ext} → {target_fmt}"}
    result = shell_exec(cmd, timeout=120)
    if os.path.exists(out):
        result["output"] = f"Converted: {out}"
        result["file"] = out
    return result


# ---------------------------------------------------------------------------
# PPT generation
# ---------------------------------------------------------------------------

def generate_ppt(content: str, llm_fn=None) -> dict[str, Any]:
    """Generate a PowerPoint from text content using python-pptx."""
    if llm_fn is None:
        return {"success": False, "output": "No LLM configured for PPT generation"}

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
    # Extract code block
    for fence in ("```python", "```"):
        if fence in code:
            code = code.split(fence, 1)[1].split("```")[0].strip()
            break

    with open("/tmp/gen_ppt.py", "w", encoding="utf-8") as f:
        f.write(code)

    result = shell_exec("python3 /tmp/gen_ppt.py", timeout=60)
    if os.path.exists("/tmp/presentation.pptx"):
        result["output"] = "PPT created: /tmp/presentation.pptx"
        result["file"] = "/tmp/presentation.pptx"
    return result


# ---------------------------------------------------------------------------
# Tool registry — maps tool names to functions
# ---------------------------------------------------------------------------

TOOLS: dict[str, dict[str, Any]] = {
    "shell": {
        "fn": shell_exec,
        "description": "Execute a shell command. Args: {command: str, timeout?: int}",
    },
    "file_read": {
        "fn": file_read,
        "description": "Read a file. Args: {path: str}",
    },
    "file_write": {
        "fn": file_write,
        "description": "Write content to a file. Args: {path: str, content: str}",
    },
    "file_list": {
        "fn": file_list,
        "description": "List files in a directory. Args: {path?: str}",
    },
    "browse": {
        "fn": browse_url,
        "description": "Fetch a webpage and get text content. Args: {url: str}",
    },
    "search": {
        "fn": web_search,
        "description": "Search the web via DuckDuckGo. Args: {query: str}",
    },
    "convert": {
        "fn": file_convert,
        "description": "Convert file format. Args: {file_path: str, target_fmt: str}",
    },
    "ppt": {
        "fn": generate_ppt,
        "description": "Generate PowerPoint from text. Args: {content: str} (uses LLM)",
        "needs_llm": True,
    },
}


def execute_tool(name: str, args: dict[str, Any], llm_fn=None) -> dict[str, Any]:
    """Execute a tool by name with given args."""
    tool = TOOLS.get(name)
    if not tool:
        return {"success": False, "output": f"Unknown tool: {name}"}

    fn = tool["fn"]
    if tool.get("needs_llm"):
        return fn(llm_fn=llm_fn, **args)
    return fn(**args)
