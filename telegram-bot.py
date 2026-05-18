#!/usr/bin/env python3
"""
Phantom Node v7 - Self-healing bot
Auto-detect errors, find solutions, fix and retry
"""
import os, json, logging, time, subprocess, urllib.request, urllib.error

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_KEY = os.environ.get("API_KEY", "")
API_BASE = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED_CHATS = os.environ.get("ALLOWED_CHATS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("phantom")

SYSTEM_PROMPT = """You are PhantomBot. When something fails:
1. Analyze the error message
2. Identify what is missing (package, file, permission)
3. Fix it automatically
4. Retry the task
Reply 1-2 sentences. No markdown."""

last_response = {}
RATE_LIMIT = 2


def run(cmd, timeout=60):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = r.stdout + r.stderr
        return out.strip()[:3000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Timeout"
    except Exception as e:
        return str(e)[:200]


def ai_plan(prompt):
    """Ask AI for a JSON plan"""
    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "Reply only with valid JSON, no extra text."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 250,
        "temperature": 0.1,
    }).encode()
    req = urllib.request.Request(
        f"{API_BASE}/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"].strip()
    for sep in ["```json", "```"]:
        if sep in content:
            content = content.split(sep)[1].split("```")[0].strip()
    return json.loads(content)


def smart_execute(task):
    """Execute task with auto-repair: detect errors, fix, retry"""
    # Step 1: Get command from AI
    try:
        plan = ai_plan(
            f'User wants: {task}\n'
            'Reply JSON: {{"cmd":"shell command","needs":["pkg"],"fix_cmd":"apt-get install -y pkg"}}\n'
            'If no packages needed, needs=[], fix_cmd="".'
        )
    except Exception as e:
        log.error(f"AI plan failed: {e}")
        return run(task)

    cmd = plan.get("cmd", task)
    needs = plan.get("needs", [])
    fix_cmd = plan.get("fix_cmd", "")

    parts = []

    # Step 2: Install missing
    if needs and fix_cmd:
        parts.append(f"Installing: {', '.join(needs)}")
        inst = run(fix_cmd, timeout=120)
        parts.append(inst[:200])

    # Step 3: Execute
    parts.append(f"$ {cmd}")
    output = run(cmd)

    # Step 4: Check errors and auto-fix
    errors = ["not found", "No such file", "Permission denied", "command not found",
              "ModuleNotFoundError", "ImportError", "Unable to locate", "error:"]
    has_err = any(e.lower() in output.lower() for e in errors)

    if has_err:
        parts.append("Error detected, auto-fixing...")
        try:
            fix = ai_plan(
                f"Command failed:\n$ {cmd}\nError: {output[:500]}\n"
                'Reply JSON: {{"diagnosis":"what went wrong","fix_cmd":"fix command","retry_cmd":"retry command"}}'
            )
            diag = fix.get("diagnosis", "")
            fc = fix.get("fix_cmd", "")
            rc = fix.get("retry_cmd", cmd)
            if diag:
                parts.append(f"Diagnosis: {diag}")
            if fc:
                parts.append(f"Fixing: {fc}")
                run(fc, timeout=120)
            parts.append(f"Retrying: {rc}")
            retry_out = run(rc)
            parts.append(retry_out)
        except Exception as e:
            parts.append(f"Auto-fix failed: {str(e)[:100]}")
    else:
        parts.append(output)

    return "\n".join(parts)


def api_chat(message, history=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-6:])
    messages.append({"role": "user", "content": message})
    payload = json.dumps({"model": MODEL, "messages": messages, "max_tokens": 300, "temperature": 0.2}).encode()
    req = urllib.request.Request(f"{API_BASE}/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        c = data["choices"][0]["message"]["content"]
        return c.strip()[:800] if c else "No response"
    except Exception as e:
        log.error(f"API error: {e}")
        return "API error"


def tg(method, data=None, timeout=10):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def tg_upload(file_path, chat_id, caption=""):
    import mimetypes
    boundary = "----PhantomBoundary7MA4"
    fname = os.path.basename(file_path)
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    with open(file_path, "rb") as f:
        fdata = f.read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{fname}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + fdata + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", data=body)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def send(chat_id, text):
    if len(text) <= 4096:
        try:
            tg("sendMessage", {"chat_id": chat_id, "text": text})
        except Exception as e:
            log.error(f"Send failed: {e}")
    else:
        for i in range(0, len(text), 4096):
            try:
                tg("sendMessage", {"chat_id": chat_id, "text": text[i:i+4096]})
            except:
                pass


def handle_doc(chat_id, doc):
    fid = doc.get("file_id")
    fname = doc.get("file_name", "unknown")
    fsize = doc.get("file_size", 0)
    if fsize > 50 * 1024 * 1024:
        send(chat_id, "File qua lon (max 50MB)")
        return
    try:
        info = tg("getFile", {"file_id": fid})
        fp = info["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}"
        local = f"/tmp/{fname}"
        urllib.request.urlretrieve(url, local)
        send(chat_id, f"Nhan: {fname} ({fsize} bytes)\n{local}")
    except Exception as e:
        send(chat_id, f"Loi: {str(e)[:100]}")


def main():
    if not BOT_TOKEN or not API_KEY:
        log.error("Missing BOT_TOKEN or API_KEY!")
        return

    allowed = set(int(c.strip()) for c in ALLOWED_CHATS.split(",") if c.strip())
    log.info(f"Bot v7 started! Model: {MODEL}")

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
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")

                if msg.get("document"):
                    if allowed and chat_id not in allowed:
                        continue
                    handle_doc(chat_id, msg["document"])
                    continue

                if not text or msg.get("from", {}).get("is_bot"):
                    continue
                if allowed and chat_id not in allowed:
                    continue

                now = time.time()
                if chat_id in last_response and now - last_response[chat_id] < RATE_LIMIT:
                    continue
                last_response[chat_id] = now

                log.info(f"[{chat_id}] {text[:80]}")

                try:
                    tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})
                except:
                    pass

                lower = text.lower().strip()

                if lower in ("/clear", "/reset"):
                    history.pop(chat_id, None)
                    send(chat_id, "Reset")
                    continue

                if lower == "/start":
                    send(chat_id, "PhantomBot v7 - Tu dong cai va su dung cong cu\n\n"
                         "Vi du: chuyen anh sang PNG, nen file, tao PDF, convert video...\n"
                         "!cmd <lenh> - chay truc tiep\n"
                         "!upload <path> - gui file\n"
                         "Gui file de luu vao /tmp/")
                    continue

                if lower.startswith("!cmd "):
                    send(chat_id, run(text[5:].strip()))
                    continue

                if lower.startswith("!upload "):
                    fp = text[8:].strip()
                    if not fp.startswith("/"):
                        fp = f"/tmp/{fp}"
                    if not os.path.exists(fp):
                        send(chat_id, f"Khong tim thay: {fp}")
                        continue
                    try:
                        tg_upload(fp, chat_id, os.path.basename(fp))
                    except Exception as e:
                        send(chat_id, f"Loi: {str(e)[:100]}")
                    continue

                if lower == "!scan":
                    send(chat_id, run("uname -a && whoami && pwd && df -h / && free -h"))
                    continue

                if lower == "!ps":
                    send(chat_id, run("ps aux --sort=-%mem | head -15"))
                    continue

                # Smart execution
                task_kw = ["convert", "chuyen", "nen", "compress", "extract", "resize",
                           "crop", "rotate", "merge", "split", "create", "generate", "make",
                           "build", "compile", "download", "tai", "fetch", "parse", "analyze",
                           "process", "edit", "modify", "video", "audio", "image", "anh",
                           "file", "pdf", "mp3", "mp4", "png", "jpg", "cài", "install"]

                if any(kw in lower for kw in task_kw):
                    send(chat_id, "Dang phan tich...")
                    result = smart_execute(text)
                    send(chat_id, result)
                    continue

                # AI chat
                if chat_id not in history:
                    history[chat_id] = []
                history[chat_id].append({"role": "user", "content": text})
                resp = api_chat(text, history[chat_id])
                history[chat_id].append({"role": "assistant", "content": resp})
                if len(history[chat_id]) > 12:
                    history[chat_id] = history[chat_id][-12:]
                send(chat_id, resp)

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error(f"Poll error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
