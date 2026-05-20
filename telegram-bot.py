#!/usr/bin/env python3
"""
PhantomBot v8 - AI Agent with full MCP toolchain
"""
import os, json, logging, time, subprocess, urllib.request, urllib.error, urllib.parse, hashlib, re
from datetime import datetime

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_KEY = os.environ.get("API_KEY", "")
API_BASE = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED_CHATS = os.environ.get("ALLOWED_CHATS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("phantom")

SYSTEM_PROMPT = """You are PhantomBot v8 — an AI assistant with a full VPS toolchain.
You can execute shell commands, browse the web, convert files, generate images, and use MCP tools.
Reply in the user's language. Be concise. Use markdown when helpful."""

MEMORY_FILE = "/tmp/phantom_memory.json"
last_response = {}
RATE_LIMIT = 2


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()[:3000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Timeout"
    except Exception as e:
        return str(e)[:200]


def ai_chat(messages, max_tokens=800, temperature=0.3):
    payload = json.dumps({"model": MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}).encode()
    req = urllib.request.Request(f"{API_BASE}/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"API error: {e}")
        return "API error"


def ai_plan(prompt):
    content = ai_chat([{"role": "system", "content": "Reply only with valid JSON."},
                       {"role": "user", "content": prompt}], max_tokens=250, temperature=0.1)
    for sep in ["```json", "```"]:
        if sep in content:
            content = content.split(sep)[1].split("```")[0].strip()
    return json.loads(content)


def smart_execute(task):
    try:
        plan = ai_plan(f'User wants: {task}\nReply JSON: {{"cmd":"shell command","needs":[],"fix_cmd":""}}')
    except:
        return run(task)
    cmd, needs, fix_cmd = plan.get("cmd", task), plan.get("needs", []), plan.get("fix_cmd", "")
    parts = []
    if needs and fix_cmd:
        parts.append(f"Installing: {', '.join(needs)}")
        parts.append(run(fix_cmd, timeout=120)[:200])
    parts.append(f"$ {cmd}")
    output = run(cmd)
    if any(e.lower() in output.lower() for e in ["not found", "No such file", "Permission denied", "command not found", "ModuleNotFoundError"]):
        parts.append("Auto-fixing...")
        try:
            fix = ai_plan("Failed: $ " + cmd + "\nError: " + output[:500] + '\nJSON: {"fix_cmd":"fix","retry_cmd":"retry"}')
            if fix.get("fix_cmd"): run(fix["fix_cmd"], timeout=120)
            output = run(fix.get("retry_cmd", cmd))
        except:
            pass
    parts.append(output)
    return "\n".join(parts)


def load_memory():
    try:
        with open(MEMORY_FILE) as f: return json.load(f)
    except: return {}


def save_memory(data):
    with open(MEMORY_FILE, "w") as f: json.dump(data, f, indent=2, ensure_ascii=False)


def browse_url(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()[:4000]
    except Exception as e:
        return f"Error: {e}"


def convert_file(file_path, target_fmt):
    ext = os.path.splitext(file_path)[1].lower()
    out = f"/tmp/converted_{int(time.time())}{target_fmt}"
    converters = {
        (".pdf", ".md"): f"markitdown {file_path} > {out}",
        (".docx", ".md"): f"markitdown {file_path} > {out}",
        (".pptx", ".md"): f"markitdown {file_path} > {out}",
        (".xlsx", ".md"): f"markitdown {file_path} > {out}",
        (".mp4", ".mp3"): f"ffmpeg -i {file_path} -q:a 0 -map a {out} -y",
        (".mp4", ".gif"): f"ffmpeg -i {file_path} -vf fps=10,scale=480:-1 {out} -y",
        (".png", ".jpg"): f"convert {file_path} {out}",
        (".jpg", ".png"): f"convert {file_path} {out}",
    }
    cmd = converters.get((ext, target_fmt))
    if not cmd: return None
    run(cmd, timeout=120)
    return out if os.path.exists(out) else f"Convert failed"


def tg(method, data=None, timeout=10):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body)
    if body: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def tg_upload(file_path, chat_id, caption=""):
    import mimetypes
    boundary = "----PhantomV8"
    fname = os.path.basename(file_path)
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    with open(file_path, "rb") as f: fdata = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{fname}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=60) as resp: return json.loads(resp.read())


def send(chat_id, text):
    try:
        if len(text) <= 4096:
            tg("sendMessage", {"chat_id": chat_id, "text": text})
        else:
            for i in range(0, len(text), 4096):
                tg("sendMessage", {"chat_id": chat_id, "text": text[i:i+4096]})
    except Exception as e:
        log.error(f"Send failed: {e}")


def handle_doc(chat_id, doc):
    fid, fname, fsize = doc.get("file_id"), doc.get("file_name", "unknown"), doc.get("file_size", 0)
    if fsize > 50 * 1024 * 1024:
        return send(chat_id, "File qua lon (max 50MB)")
    try:
        info = tg("getFile", {"file_id": fid})
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{info['result']['file_path']}"
        local = f"/tmp/{fname}"
        urllib.request.urlretrieve(url, local)
        send(chat_id, f"Da nhan: {fname} ({fsize} bytes)\nLuu: {local}")
    except Exception as e:
        send(chat_id, f"Loi: {str(e)[:100]}")


def handle_search(chat_id, text):
    query = text.replace("/search", "").strip()
    if not query: return send(chat_id, "Usage: /search <query>")
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        results = re.findall(r'class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>', html)
        if results:
            out = f"🔍 {query}:\n\n"
            for i, (link, title) in enumerate(results[:5], 1):
                out += f"{i}. {title.strip()}\n{link}\n\n"
            send(chat_id, out)
        else:
            send(chat_id, "Khong tim thay ket qua")
    except Exception as e:
        send(chat_id, f"Search error: {e}")


def handle_convert(chat_id, text):
    parts = text.split()
    if len(parts) < 3: return send(chat_id, "Usage: /convert <file> <format>\nExample: /convert /tmp/doc.pdf .md")
    fpath, fmt = parts[1], parts[2]
    if not os.path.exists(fpath): return send(chat_id, f"Khong tim thay: {fpath}")
    send(chat_id, "Dang convert...")
    result = convert_file(fpath, fmt)
    if result and os.path.exists(result):
        tg_upload(result, chat_id, f"Converted: {os.path.basename(result)}")
    else:
        send(chat_id, result or "Convert failed")


def handle_browse(chat_id, text):
    parts = text.split()
    if len(parts) < 2: return send(chat_id, "Usage: /browse <url>")
    url = parts[1] if parts[1].startswith("http") else "https://" + parts[1]
    send(chat_id, f"Dang truy cap {url}...")
    content = browse_url(url)
    summary = ai_chat([{"role": "system", "content": "Summarize this webpage concisely."},
                       {"role": "user", "content": content}], max_tokens=500)
    send(chat_id, summary)


def handle_mcp(chat_id):
    checks = {
        "CodeGraph": "which codegraph",
        "MarkItDown": "which markitdown",
        "Playwright": "which playwright",
        "Context7": "npm list -g @context7/mcp-server",
        "Filesystem MCP": "npm list -g @anthropic-ai/mcp-filesystem",
        "GitHub MCP": "npm list -g @anthropic-ai/mcp-github",
        "Sequential Thinking": "npm list -g @anthropic-ai/mcp-sequential-thinking",
        "Supabase MCP": "npm list -g @anthropic-ai/mcp-supabase",
        "Browserbase MCP": "npm list -g @anthropic-ai/mcp-browserbase",
        "Playwright MCP": "npm list -g @anthropic-ai/mcp-playwright",
    }
    tools = []
    for name, cmd in checks.items():
        result = run(cmd)
        status = "✅" if "empty" not in result.lower() and "ERR" not in result else "❌"
        tools.append(f"{status} {name}")
    send(chat_id, f"🛠 MCP Tools:\n\n" + "\n".join(tools) +
         "\n\n📊 CodeGraph: semantic code graph (94% fewer calls)\n"
         "🌐 Browserbase: cloud headless browser 24/7\n"
         "🎬 OpenCut: open source video editor\n"
         "🧠 Computer Use: Anthropic built-in")


def handle_memory(chat_id, text, action):
    memory = load_memory()
    if action == "remember":
        content = text.replace("/remember", "").strip()
        if not content: return send(chat_id, "Usage: /remember <what>")
        key = hashlib.md5(content.encode()).hexdigest()[:8]
        memory[key] = {"text": content, "time": datetime.now().isoformat()}
        save_memory(memory)
        send(chat_id, f"Da nho: {content}")
    else:
        if not memory: return send(chat_id, "Chua co memory nao.")
        out = "🧠 Memory:\n\n" + "\n".join(f"• {v['text']}" for v in memory.values())
        send(chat_id, out[:4000])


def handle_analyze(chat_id, text):
    parts = text.split()
    if len(parts) < 2: return send(chat_id, "Usage: /analyze <file_path>")
    fpath = parts[1]
    if not os.path.exists(fpath): return send(chat_id, f"Khong tim thay: {fpath}")
    send(chat_id, "Dang phan tich...")
    ext = os.path.splitext(fpath)[1].lower()
    if ext in [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"]:
        content = run(f"cat {fpath} 2>/dev/null | head -200")
        if ext == ".pdf": content = run(f"markitdown {fpath} 2>/dev/null | head -200")
    elif ext in [".png", ".jpg", ".jpeg", ".gif"]:
        content = f"Image file: {ext}, size: {os.path.getsize(fpath)} bytes"
    else:
        content = run(f"file {fpath} && head -100 {fpath}")
    summary = ai_chat([{"role": "system", "content": "Analyze this file content concisely."},
                       {"role": "user", "content": content}], max_tokens=600)
    send(chat_id, summary)


def main():
    if not BOT_TOKEN or not API_KEY:
        log.error("Missing BOT_TOKEN or API_KEY!")
        return

    allowed = set(int(c.strip()) for c in ALLOWED_CHATS.split(",") if c.strip())
    log.info(f"PhantomBot v8 started! Model: {MODEL}")

    try:
        r = tg("getUpdates", {"offset": -1, "timeout": 1}, timeout=5)
        offset = r["result"][-1]["update_id"] + 1 if r.get("result") else 0
    except:
        offset = 0

    history = {}

    while True:
        try:
            result = tg("getUpdates", {"offset": offset, "timeout": 30}, timeout=35)
            for update in result.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg: continue

                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")

                if msg.get("document"):
                    if allowed and chat_id not in allowed: continue
                    handle_doc(chat_id, msg["document"])
                    continue

                if not text or msg.get("from", {}).get("is_bot"): continue
                if allowed and chat_id not in allowed: continue

                now = time.time()
                if chat_id in last_response and now - last_response[chat_id] < RATE_LIMIT: continue
                last_response[chat_id] = now

                log.info(f"[{chat_id}] {text[:80]}")
                try: tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                except: pass

                lower = text.lower().strip()

                # === Commands ===
                if lower in ("/clear", "/reset"):
                    history.pop(chat_id, None)
                    send(chat_id, "Reset"); continue

                if lower == "/start":
                    send(chat_id, "PhantomBot v8 — AI Agent + MCP Tools\n\n"
                         "/search <query> — Tim kiem web\n"
                         "/convert <file> <fmt> — Convert file (pdf→md, mp4→mp3...)\n"
                         "/browse <url> — Doc va tong hop trang web\n"
                         "/analyze <file> — Phan tich file\n"
                         "/mcp — Danh sach MCP tools\n"
                         "/remember <text> — Luu memory\n"
                         "/recall — Xem memory\n"
                         "!cmd <command> — Chay lenh shell\n"
                         "!upload <path> — Gui file\n"
                         "!scan — Thong tin he thong\n"
                         "Gui file de luu vao /tmp/\n"
                         "Hoac chi can chat voi AI!"); continue

                if lower.startswith("!cmd "): send(chat_id, run(text[5:].strip())); continue
                if lower.startswith("!upload "):
                    fp = text[8:].strip()
                    if not fp.startswith("/"): fp = f"/tmp/{fp}"
                    if not os.path.exists(fp): send(chat_id, f"Khong tim thay: {fp}"); continue
                    try: tg_upload(fp, chat_id, os.path.basename(fp))
                    except Exception as e: send(chat_id, f"Loi: {str(e)[:100]}")
                    continue
                if lower == "!scan": send(chat_id, run("uname -a && whoami && pwd && df -h / && free -h")); continue
                if lower == "!ps": send(chat_id, run("ps aux --sort=-%mem | head -15")); continue
                if lower.startswith("/search"): handle_search(chat_id, text); continue
                if lower.startswith("/convert"): handle_convert(chat_id, text); continue
                if lower.startswith("/browse"): handle_browse(chat_id, text); continue
                if lower == "/mcp": handle_mcp(chat_id); continue
                if lower.startswith("/remember"): handle_memory(chat_id, text, "remember"); continue
                if lower == "/recall": handle_memory(chat_id, text, "recall"); continue
                if lower.startswith("/analyze"): handle_analyze(chat_id, text); continue

                # === Smart Execution ===
                task_kw = ["convert", "chuyen", "nen", "compress", "extract", "resize", "crop", "rotate",
                           "merge", "split", "create", "generate", "make", "build", "compile", "download",
                           "tai", "fetch", "parse", "analyze", "process", "edit", "modify", "video", "audio",
                           "image", "anh", "file", "pdf", "mp3", "mp4", "png", "jpg", "cai", "install"]
                if any(kw in lower for kw in task_kw):
                    send(chat_id, "Dang phan tich...")
                    send(chat_id, smart_execute(text)); continue

                # === AI Chat ===
                if chat_id not in history: history[chat_id] = []
                history[chat_id].append({"role": "user", "content": text})
                resp = ai_chat([{"role": "system", "content": SYSTEM_PROMPT}] + history[chat_id][-12:])
                history[chat_id].append({"role": "assistant", "content": resp})
                if len(history[chat_id]) > 12: history[chat_id] = history[chat_id][-12:]
                send(chat_id, resp)

        except KeyboardInterrupt: break
        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
