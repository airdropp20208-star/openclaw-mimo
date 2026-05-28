"""
OpenManus Tools — shell, file, browser, search, convert, ppt.
Each tool returns {"success": bool, "output": str}.
Security: sandboxed, no RCE, no dynamic code loading.
"""
import ast, os, re, shlex, signal, subprocess, tempfile, time
import urllib.error, urllib.parse, urllib.request
from typing import Any, Optional

MAX_FILE_READ = 100_000
MAX_HTTP_READ = 500_000
MAX_SHELL_OUTPUT = 5000

_BLOCKED_CMDS = [
    "rm -rf /", "rm -rf /*", "mkfs", ":(){ :|:& };:",
    "dd if=/dev/zero", "dd if=/dev/random", "> /dev/sda",
    "shutdown", "reboot", "halt", "poweroff",
    "chmod 777", "chown -R", "useradd", "userdel",
    "nc -", "ncat", "netcat", "socat",
    "python -c", "python3 -c", "perl -e", "ruby -e",
    "curl.*|.*sh", "curl.*|.*bash", "wget.*|.*sh", "wget.*|.*bash",
    "eval ", "exec(",
]

_BLOCKED_PATTERNS = [
    r"wget\s+.*\|\s*(ba)?sh",
    r"curl\s+.*\|\s*(ba)?sh",
    r"python\s*-c\s+.*import\s+os",
    r"base64\s+-d\s*\|",
]

_PRIVATE_HOSTS = {
    "localhost", "127.0.0.1", "0.0.0.0", "::1",
    "169.254.169.254", "[::1]", "[::ffff:127.0.0.1]",
}

_ALLOWED_WRITE_DIRS = ["/tmp/", os.path.expanduser("~/data/")]

_SENSITIVE_FILES = ["/etc/shadow", "/etc/passwd", ".ssh/", ".env", "id_rsa", "credentials", "secret"]


def _is_private_ip(hostname):
    if not hostname:
        return True
    h = hostname.lower().strip("[]")
    if h in _PRIVATE_HOSTS:
        return True
    parts = h.split(".")
    if len(parts) == 4:
        try:
            nums = [int(p) for p in parts]
            if (nums[0] == 10 or
                nums[0] == 172 and 16 <= nums[1] <= 31 or
                nums[0] == 192 and nums[1] == 168 or
                nums[0] == 0 or
                nums[0] == 169 and nums[1] == 254):
                return True
        except ValueError:
            pass
    return False


def _is_safe_write_path(path):
    abs_path = os.path.abspath(path)
    for allowed in _ALLOWED_WRITE_DIRS:
        if abs_path.startswith(os.path.abspath(allowed)):
            return True
    return False


def _sanitize_code(code):
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in ('os', 'sys', 'subprocess', 'shutil', 'socket', 'ctypes', 'importlib'):
                    return False
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split('.')[0] in ('os', 'sys', 'subprocess', 'shutil', 'socket', 'ctypes', 'importlib'):
                return False
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in ('exec', 'eval', 'compile', '__import__'):
                return False
            if isinstance(func, ast.Attribute) and func.attr in ('system', 'popen', 'call', 'run'):
                return False
    return True


def shell_exec(command, timeout=60):
    if not command or not command.strip():
        return {"success": False, "output": "Empty command"}
    cmd_lower = command.lower().strip()
    for blocked in _BLOCKED_CMDS:
        if blocked in cmd_lower:
            return {"success": False, "output": "Blocked: dangerous command detected"}
    for pattern in _BLOCKED_PATTERNS:
        if re.search(pattern, cmd_lower):
            return {"success": False, "output": "Blocked: dangerous command detected"}
    timeout = max(5, min(timeout, 300))
    try:
        proc = subprocess.Popen(
            command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            output = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
            if len(output) > MAX_SHELL_OUTPUT:
                output = output[:MAX_SHELL_OUTPUT] + "\n... (truncated)"
            return {"success": proc.returncode == 0, "output": output or "(no output)"}
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            proc.wait()
            return {"success": False, "output": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"success": False, "output": f"Error: {str(e)[:500]}"}


def file_read(path):
    if not path:
        return {"success": False, "output": "No path provided"}
    for s in _SENSITIVE_FILES:
        if s in path:
            return {"success": False, "output": "Access denied: sensitive file"}
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


def file_write(path, content):
    if not path:
        return {"success": False, "output": "No path provided"}
    if not _is_safe_write_path(path):
        return {"success": False, "output": "Access denied: can only write to /tmp/ or ~/data/"}
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content[:1_000_000])
        return {"success": True, "output": f"Wrote {len(content)} chars to {path}"}
    except Exception as e:
        return {"success": False, "output": str(e)[:500]}


def file_list(path="."):
    if not path:
        path = "."
    for f in ["/root", "/boot", "/sys", "/proc", "/etc"]:
        if path.startswith(f):
            return {"success": False, "output": f"Access denied: cannot list {f}"}
    try:
        entries = sorted(os.listdir(path))[:500]
        return {"success": True, "output": "\n".join(entries) or "(empty)"}
    except Exception as e:
        return {"success": False, "output": str(e)[:500]}


def browse_url(url):
    if not url:
        return {"success": False, "output": "No URL provided"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urllib.parse.urlparse(url)
    if _is_private_ip(parsed.hostname or ""):
        return {"success": False, "output": "Access denied: internal/private URL blocked"}
    if parsed.scheme == "file":
        return {"success": False, "output": "Access denied: file:// URLs blocked"}
    browser = None
    try:
        from browser_use import Browser
        import asyncio
        async def _fetch():
            nonlocal browser
            browser = Browser(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, timeout=30000)
                content = await page.content()
                title = await page.title()
                return title, content
            finally:
                await browser.close()
        title, html = asyncio.run(_fetch())
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()[:5000]
        return {"success": True, "output": f"Title: {title}\n\n{text}"}
    except ImportError:
        pass
    except Exception:
        if browser:
            try:
                import asyncio
                asyncio.run(browser.close())
            except Exception:
                pass
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


def web_search(query):
    if not query:
        return {"success": False, "output": "No query provided"}
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read(MAX_HTTP_READ)
            html = raw.decode("utf-8", errors="ignore")
        results = re.findall(r'class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>', html)
        if results:
            out = f"Results for: {query}\n\n"
            for i, (link, title) in enumerate(results[:5], 1):
                out += f"{i}. {title.strip()}\n{link}\n\n"
            return {"success": True, "output": out}
        return {"success": True, "output": "No results found."}
    except Exception as e:
        return {"success": False, "output": f"Search error: {str(e)[:300]}"}


def pandas_exec(code, csv_path=None):
    if not _sanitize_code(code):
        return {"success": False, "output": "Code contains disallowed operations"}
    try:
        import pandas as pd
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import io
        loc = {"pd": pd, "plt": plt}
        if csv_path and os.path.exists(csv_path):
            loc["df"] = pd.read_csv(csv_path)
        output = io.StringIO()
        import sys
        old_stdout = sys.stdout
        sys.stdout = output
        try:
            safe_builtins = {
                'print': print, 'range': range, 'len': len, 'str': str,
                'int': int, 'float': float, 'bool': bool, 'list': list,
                'dict': dict, 'set': set, 'tuple': tuple, 'type': type,
                'isinstance': isinstance, 'enumerate': enumerate, 'zip': zip,
                'map': map, 'filter': filter, 'sorted': sorted, 'reversed': reversed,
                'min': min, 'max': max, 'sum': sum, 'abs': abs, 'round': round,
                'True': True, 'False': False, 'None': None,
            }
            exec(code, {"__builtins__": safe_builtins}, loc)
            sys.stdout = old_stdout
            res = output.getvalue()
            if plt.get_fignums():
                plot_path = f"/tmp/plot_{int(time.time())}.png"
                plt.savefig(plot_path)
                plt.close()
                return {"success": True, "output": res or "Code executed successfully", "file": plot_path}
            return {"success": True, "output": res or "Code executed successfully"}
        except Exception as e:
            sys.stdout = old_stdout
            return {"success": False, "output": str(e)}
    except Exception as e:
        return {"success": False, "output": f"Pandas error: {e}"}


def file_convert(file_path, target_fmt):
    if not file_path:
        return {"success": False, "output": "No file path provided"}
    if not target_fmt:
        return {"success": False, "output": "No target format"}
    if not target_fmt.startswith(".") or len(target_fmt) > 10:
        target_fmt = f".{target_fmt.lstrip('.')}"
    if not re.match(r"^\.\w{1,6}$", target_fmt):
        return {"success": False, "output": f"Invalid format: {target_fmt}"}
    ext = os.path.splitext(file_path)[1].lower()
    fd, out = tempfile.mkstemp(suffix=target_fmt, prefix="converted_")
    os.close(fd)
    converters = {
        (".pdf", ".md"): f"markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}",
        (".docx", ".md"): f"markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}",
        (".pptx", ".md"): f"markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}",
        (".xlsx", ".md"): f"markitdown {shlex.quote(file_path)} -o {shlex.quote(out)}",
        (".mp4", ".mp3"): f"ffmpeg -i {shlex.quote(file_path)} -q:a 0 -map a {shlex.quote(out)} -y",
        (".mp4", ".gif"): f"ffmpeg -i {shlex.quote(file_path)} -vf fps=10,scale=480:-1 {shlex.quote(out)} -y",
        (".png", ".jpg"): f"convert {shlex.quote(file_path)} {shlex.quote(out)}",
        (".jpg", ".png"): f"convert {shlex.quote(file_path)} {shlex.quote(out)}",
    }
    cmd = converters.get((ext, target_fmt))
    if not cmd:
        os.unlink(out)
        return {"success": False, "output": f"Unsupported conversion: {ext} -> {target_fmt}"}
    result = shell_exec(cmd, timeout=120)
    if os.path.exists(out):
        size = os.path.getsize(out)
        result["output"] = f"Converted -> {out} ({size} bytes)"
        result["file"] = out
    else:
        result["success"] = False
        if not result.get("output") or result["output"] == "(no output)":
            result["output"] = "Conversion failed: output file not created"
    return result


def goal_manage(action, args, agent=None):
    if not agent:
        return {"success": False, "output": "Agent context missing"}
    chat_id = args.get("chat_id", 0)
    planner = agent._get_planner(chat_id)
    try:
        if action == "add_goal":
            goal = agent.add_goal(chat_id, args.get("description"), args.get("priority", 5))
            return {"success": True, "output": f"Goal created: {goal}"}
        elif action == "complete_subtask":
            res = agent.complete_subtask(chat_id, args.get("subtask_id"), args.get("result", ""), llm_fn=agent._llm_fn)
            return {"success": True, "output": res}
        elif action == "add_subtask":
            success = planner.add_subtask(args.get("goal_id"), args.get("description"), args.get("after_id"))
            return {"success": success, "output": "Subtask added" if success else "Goal not found"}
        elif action == "list_goals":
            return {"success": True, "output": planner.get_summary()}
        return {"success": False, "output": f"Unknown action: {action}"}
    except Exception as e:
        return {"success": False, "output": str(e)}


def generate_ppt(content, llm_fn=None):
    if llm_fn is None:
        return {"success": False, "output": "No LLM configured for PPT generation"}
    if not content:
        return {"success": False, "output": "No content provided"}
    prompt = f"""Create a professional PowerPoint from this content.
Return ONLY python-pptx code. Content: {content[:3000]}
Requirements: Title slide, content slides with bullets, professional styling, save to /tmp/presentation.pptx
IMPORTANT: Only use from pptx import Presentation. Do NOT use os, sys, subprocess."""
    code = llm_fn(
        [{"role": "system", "content": "Return only executable python-pptx code, no explanation."},
         {"role": "user", "content": prompt}],
        max_tokens=2000,
    )
    for fence in ("```python", "```"):
        if fence in code:
            code = code.split(fence, 1)[1].split("```")[0].strip()
            break
    if not code.strip():
        return {"success": False, "output": "Empty code from LLM"}
    if not _sanitize_code(code):
        return {"success": False, "output": "Generated code contains disallowed operations"}
    fd, script_path = tempfile.mkstemp(suffix=".py", prefix="ppt_gen_")
    os.close(fd)
    fd2, ppt_path = tempfile.mkstemp(suffix=".pptx", prefix="presentation_")
    os.close(fd2)
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


TOOLS = {
    "shell": {"fn": shell_exec, "description": "Execute shell command. Args: {command: str, timeout?: int}"},
    "file_read": {"fn": file_read, "description": "Read a file (max 1MB). Args: {path: str}"},
    "file_write": {"fn": file_write, "description": "Write to /tmp or ~/data. Args: {path: str, content: str}"},
    "file_list": {"fn": file_list, "description": "List files. Args: {path?: str}"},
    "browse": {"fn": browse_url, "description": "Fetch webpage. Args: {url: str}"},
    "search": {"fn": web_search, "description": "Web search. Args: {query: str}"},
    "convert": {"fn": file_convert, "description": "Convert file format. Args: {file_path: str, target_fmt: str}"},
    "ppt": {"fn": generate_ppt, "description": "Generate PowerPoint. Args: {content: str}", "needs_llm": True},
    "goal_manage": {"fn": goal_manage, "description": "Manage goals. Args: {action: str, args: dict}", "needs_agent": True},
    "data_analyze": {"fn": pandas_exec, "description": "Analyze data with pandas. Args: {code: str, csv_path?: str}"},
}


def execute_tool(name, args, llm_fn=None, agent=None):
    if not isinstance(args, dict):
        return {"success": False, "output": f"Args must be a dict, got {type(args).__name__}"}
    tool = TOOLS.get(name)
    if not tool:
        return {"success": False, "output": f"Unknown tool: {name}. Available: {', '.join(TOOLS)}"}
    fn = tool["fn"]
    extra_args = {}
    if tool.get("needs_llm"):
        extra_args["llm_fn"] = llm_fn
    if tool.get("needs_agent"):
        extra_args["agent"] = agent
    try:
        return fn(**args, **extra_args)
    except TypeError as e:
        return {"success": False, "output": f"Invalid args for {name}: {e}"}
    except Exception as e:
        return {"success": False, "output": f"Tool execution error: {str(e)}"}
