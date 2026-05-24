"""Telegram bot handlers — one function per command type.

Each handler receives the shared :class:`BotContext` and the relevant
message data.  This keeps the main bot loop clean and testable.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .telegram import TelegramBot

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Utility helpers
# ------------------------------------------------------------------


def safe_path(user_input: str) -> Optional[str]:
    """Sanitise a file path to prevent shell injection."""
    p = user_input.strip().strip("'\"")
    if not p.startswith("/"):
        p = f"/tmp/{p}"
    if any(c in p for c in [";", "|", "&", "$", "`", "(", ")", "{", "}"]):
        return None
    return p


def run_cmd(cmd: str, timeout: int = 60) -> str:
    """Execute a shell command and return combined stdout+stderr (truncated)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return (r.stdout + r.stderr).strip()[:3000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Timeout"
    except Exception as exc:
        return str(exc)[:200]


# ------------------------------------------------------------------
# /start
# ------------------------------------------------------------------


def handle_start(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Show the help/welcome message."""
    help_text = (
        "🤖 **PhantomBot v8** — AI Agent + MCP Tools\n\n"
        "/search <query> — Search the web\n"
        "/convert <file> <fmt> — Convert file (pdf→md, mp4→mp3…)\n"
        "/browse <url> — Fetch & summarise a webpage\n"
        "/analyze <file> — Analyse a file\n"
        "/ppt <text/file> — Create a PPT\n"
        "/mcp — List MCP tools\n"
        "/remember <text> — Save to memory\n"
        "/recall — View memory\n"
        "/skills — List saved skills\n"
        "!cmd <command> — Run a shell command\n"
        "!upload <path> — Send a file\n"
        "!scan — System info\n"
        "Send a file to save it to /tmp/\n"
        "Or just chat with the AI!"
    )
    bot.send_message(chat_id, help_text)


# ------------------------------------------------------------------
# /clear
# ------------------------------------------------------------------


def handle_clear(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Clear conversation history for this chat."""
    bot.context.clear(chat_id)
    bot.send_message(chat_id, "✅ History cleared.")


# ------------------------------------------------------------------
# /search
# ------------------------------------------------------------------


def handle_search(bot: TelegramBot, chat_id: int, text: str) -> None:
    """DuckDuckGo web search."""
    query = text.replace("/search", "").strip()
    if not query:
        bot.send_message(chat_id, "Usage: /search <query>")
        return

    bot.send_chat_action(chat_id, "typing")
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        results = re.findall(
            r'class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>', html
        )
        if results:
            out = f"🔍 {query}:\n\n"
            for i, (link, title) in enumerate(results[:5], 1):
                out += f"{i}. {title.strip()}\n{link}\n\n"
            bot.send_message(chat_id, out)
        else:
            bot.send_message(chat_id, "No results found.")
    except Exception as exc:
        logger.exception("Search failed")
        bot.send_message(chat_id, f"Search error: {exc}")


# ------------------------------------------------------------------
# /convert
# ------------------------------------------------------------------


def handle_convert(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Convert a file from one format to another."""
    parts = text.split()
    if len(parts) < 3:
        bot.send_message(
            chat_id, "Usage: /convert <file> <format>\nExample: /convert /tmp/doc.pdf .md"
        )
        return

    fpath = safe_path(parts[1])
    fmt = parts[2]
    if not fpath:
        bot.send_message(chat_id, "Invalid path")
        return
    if not os.path.exists(fpath):
        bot.send_message(chat_id, f"Not found: {fpath}")
        return

    bot.send_message(chat_id, "Converting...")
    converters = {
        (".pdf", ".md"): f'markitdown "{fpath}" -o /tmp/converted{fmt}',
        (".docx", ".md"): f'markitdown "{fpath}" -o /tmp/converted{fmt}',
        (".pptx", ".md"): f'markitdown "{fpath}" -o /tmp/converted{fmt}',
        (".xlsx", ".md"): f'markitdown "{fpath}" -o /tmp/converted{fmt}',
        (".mp4", ".mp3"): f'ffmpeg -i "{fpath}" -q:a 0 -map a /tmp/converted{fmt} -y',
        (".mp4", ".gif"): f'ffmpeg -i "{fpath}" -vf fps=10,scale=480:-1 /tmp/converted{fmt} -y',
        (".png", ".jpg"): f'convert "{fpath}" /tmp/converted{fmt}',
        (".jpg", ".png"): f'convert "{fpath}" /tmp/converted{fmt}',
    }
    ext = os.path.splitext(fpath)[1].lower()
    cmd = converters.get((ext, fmt))
    out_path = f"/tmp/converted_{int(time.time())}{fmt}"
    if cmd:
        cmd = cmd.replace("/tmp/converted" + fmt, out_path)

    if not cmd:
        bot.send_message(chat_id, f"Unsupported conversion: {ext} → {fmt}")
        return

    run_cmd(cmd, timeout=120)
    if os.path.exists(out_path):
        bot.send_document(chat_id, out_path, caption=f"Converted: {os.path.basename(out_path)}")
    else:
        bot.send_message(chat_id, "Conversion failed")


# ------------------------------------------------------------------
# /browse
# ------------------------------------------------------------------


def handle_browse(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Fetch a webpage and return an AI summarised version."""
    parts = text.split()
    if len(parts) < 2:
        bot.send_message(chat_id, "Usage: /browse <url>")
        return

    url = parts[1] if parts[1].startswith("http") else "https://" + parts[1]
    bot.send_message(chat_id, f"Fetching {url}...")
    bot.send_chat_action(chat_id, "typing")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        # Strip HTML tags for a text preview
        text_content = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
        text_content = re.sub(r"<[^>]+>", " ", text_content)
        text_content = re.sub(r"\s+", " ", text_content).strip()[:4000]

        summary = bot.llm.chat(
            [
                {"role": "system", "content": "Summarise this webpage concisely."},
                {"role": "user", "content": text_content},
            ],
            max_tokens=500,
        )
        bot.send_message(chat_id, summary)
    except Exception as exc:
        logger.exception("Browse failed")
        bot.send_message(chat_id, f"Browse error: {exc}")


# ------------------------------------------------------------------
# /analyze
# ------------------------------------------------------------------


def handle_analyze(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Analyse a file using the LLM."""
    parts = text.split()
    if len(parts) < 2:
        bot.send_message(chat_id, "Usage: /analyze <file_path>")
        return

    fpath = safe_path(parts[1])
    if not fpath:
        bot.send_message(chat_id, "Invalid path")
        return
    if not os.path.exists(fpath):
        bot.send_message(chat_id, f"Not found: {fpath}")
        return

    bot.send_message(chat_id, "Analysing...")
    bot.send_chat_action(chat_id, "typing")

    ext = os.path.splitext(fpath)[1].lower()
    if ext in (".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"):
        if ext == ".pdf":
            content = run_cmd(f'markitdown "{fpath}" 2>/dev/null | head -200')
        else:
            content = run_cmd(f'head -200 "{fpath}" 2>/dev/null')
    elif ext in (".png", ".jpg", ".jpeg", ".gif"):
        content = f"Image file: {ext}, size: {os.path.getsize(fpath)} bytes"
    else:
        content = run_cmd(f'file "{fpath}" && head -100 "{fpath}"')

    summary = bot.llm.chat(
        [
            {"role": "system", "content": "Analyse this file content concisely."},
            {"role": "user", "content": content},
        ],
        max_tokens=600,
    )
    bot.send_message(chat_id, summary)


# ------------------------------------------------------------------
# /ppt
# ------------------------------------------------------------------


def handle_ppt(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Generate a PowerPoint presentation from text or a file."""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(chat_id, "Usage: /ppt <text or file_path>\nExample: /ppt /tmp/doc.pdf")
        return

    arg = parts[1].strip()
    fpath = safe_path(arg)
    if fpath and os.path.exists(fpath):
        bot.send_message(chat_id, "Creating PPT from file...")
        if fpath.endswith(".pdf"):
            content = run_cmd(f'markitdown "{fpath}" 2>/dev/null | head -300')
        else:
            content = run_cmd(f'head -300 "{fpath}" 2>/dev/null')
    else:
        bot.send_message(chat_id, "Creating PPT...")
        content = arg

    prompt = (
        f"Create a professional PowerPoint presentation from this content.\n"
        f"Return ONLY the python-pptx code to generate the PPT.\n"
        f"Content: {content[:3000]}\n\n"
        f"Requirements:\n"
        f"- Title slide\n- Content slides with bullet points\n"
        f"- Professional styling\n- Save to /tmp/presentation.pptx"
    )
    code = bot.llm.chat(
        [
            {"role": "system", "content": "Return only executable python-pptx code, no explanation."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2000,
    )
    # Extract code block
    for fence in ("```python", "```"):
        if fence in code:
            code = code.split(fence, 1)[1].split("```")[0].strip()
            break

    with open("/tmp/gen_ppt.py", "w", encoding="utf-8") as f:
        f.write(code)

    output = run_cmd("python3 /tmp/gen_ppt.py", timeout=60)
    if os.path.exists("/tmp/presentation.pptx"):
        bot.send_document(chat_id, "/tmp/presentation.pptx", caption="PPT created!")
    else:
        bot.send_message(chat_id, f"PPT error:\n{output[:500]}")


# ------------------------------------------------------------------
# /mcp
# ------------------------------------------------------------------


def handle_mcp(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Check which MCP tools are available."""
    checks = {
        "CodeGraph": "which codegraph",
        "MarkItDown": "which markitdown",
        "Playwright": "python3 -c 'import playwright'",
        "Context7": "npm list -g @upstash/context7-mcp",
        "Filesystem MCP": "npm list -g @modelcontextprotocol/server-filesystem",
        "GitHub MCP": "npm list -g @modelcontextprotocol/server-github",
        "Supabase MCP": "npm list -g @supabase/mcp-server-supabase",
        "Sequential Thinking": "npm list -g @modelcontextprotocol/server-sequential-thinking",
    }
    tools: list[str] = []
    for name, cmd in checks.items():
        result = run_cmd(cmd)
        status = "✅" if "empty" not in result.lower() and "ERR" not in result else "❌"
        tools.append(f"{status} {name}")

    bot.send_message(
        chat_id,
        "🛠 MCP Tools:\n\n" + "\n".join(tools) +
        "\n\n📊 CodeGraph: semantic code graph (94% fewer calls)\n"
        "🌐 Playwright: headless browser automation\n"
        "🧠 Computer Use: Anthropic built-in\n"
        "📑 PPT Master: AI creates PPTX from documents",
    )


# ------------------------------------------------------------------
# /remember
# ------------------------------------------------------------------


def handle_remember(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Save a memory entry."""
    import hashlib
    from datetime import datetime

    content = text.replace("/remember", "").strip()
    if not content:
        bot.send_message(chat_id, "Usage: /remember <what>")
        return

    memory = bot.load_memory()
    key = hashlib.md5(content.encode()).hexdigest()[:8]
    memory[key] = {"text": content, "time": datetime.now().isoformat()}
    bot.save_memory(memory)
    bot.send_message(chat_id, f"✅ Remembered: {content}")


# ------------------------------------------------------------------
# /recall
# ------------------------------------------------------------------


def handle_recall(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Recall all stored memories."""
    memory = bot.load_memory()
    if not memory:
        bot.send_message(chat_id, "No memories stored.")
        return
    out = "🧠 Memory:\n\n" + "\n".join(
        f"• {v['text']}" for v in memory.values()
    )
    bot.send_message(chat_id, out[:4000])


# ------------------------------------------------------------------
# /skills
# ------------------------------------------------------------------


def handle_skills(bot: TelegramBot, chat_id: int, text: str) -> None:
    """List saved skills or search for a matching skill."""
    query = text.replace("/skills", "").strip()
    if query:
        skill = bot.skills.find_skill(query)
        if skill:
            lines = [
                f"🎯 Skill: {skill.name}",
                f"Keywords: {', '.join(skill.trigger_keywords)}",
                f"Successes: {skill.success_count}",
                f"\nSteps:",
            ]
            for i, step in enumerate(skill.steps, 1):
                lines.append(f"  {i}. {step}")
            if skill.result_template:
                lines.append(f"\nResult template: {skill.result_template}")
            bot.send_message(chat_id, "\n".join(lines))
        else:
            bot.send_message(chat_id, f"No skill matching: {query}")
        return

    skills = bot.skills.list_skills()
    if not skills:
        bot.send_message(chat_id, "No skills stored yet.\nUse /remember to save tasks as skills.")
        return
    out = f"📚 Skills ({len(skills)}):\n\n"
    for s in skills:
        out += f"• {s.name} (successes: {s.success_count})\n"
    bot.send_message(chat_id, out[:4000])


# ------------------------------------------------------------------
# Document handling
# ------------------------------------------------------------------


def handle_document(bot: TelegramBot, chat_id: int, doc: dict[str, Any]) -> None:
    """Receive and save a file sent to the bot."""
    fid = doc.get("file_id", "")
    fname = doc.get("file_name", "unknown")
    fsize = doc.get("file_size", 0)
    if fsize > 50 * 1024 * 1024:
        bot.send_message(chat_id, "File too large (max 50MB)")
        return
    try:
        info = bot.tg_api("getFile", {"file_id": fid})
        dl_url = f"https://api.telegram.org/file/bot{bot.bot_token}/{info['result']['file_path']}"
        local = f"/tmp/{fname}"
        urllib.request.urlretrieve(dl_url, local)
        bot.send_message(chat_id, f"📄 Received: {fname} ({fsize} bytes)\nSaved: {local}")
    except Exception as exc:
        bot.send_message(chat_id, f"Error: {str(exc)[:100]}")


# ------------------------------------------------------------------
# Shell execution (!cmd)
# ------------------------------------------------------------------


def handle_cmd(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Execute a shell command."""
    cmd = text[5:].strip()
    if not cmd:
        bot.send_message(chat_id, "Usage: !cmd <command>")
        return
    output = run_cmd(cmd)
    bot.send_message(chat_id, output)


# ------------------------------------------------------------------
# File upload (!upload)
# ------------------------------------------------------------------


def handle_upload(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Upload a file to the chat."""
    fp = text[8:].strip()
    if not fp.startswith("/"):
        fp = f"/tmp/{fp}"
    if not os.path.exists(fp):
        bot.send_message(chat_id, f"Not found: {fp}")
        return
    try:
        bot.send_document(chat_id, fp, caption=os.path.basename(fp))
    except Exception as exc:
        bot.send_message(chat_id, f"Error: {str(exc)[:100]}")


# ------------------------------------------------------------------
# System scan (!scan)
# ------------------------------------------------------------------


def handle_scan(bot: TelegramBot, chat_id: int, text: str) -> None:
    """Show system information."""
    output = run_cmd("uname -a && whoami && pwd && df -h / && free -h")
    bot.send_message(chat_id, output)
