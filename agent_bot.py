#!/usr/bin/env python3
"""
MiMo Agent - Autonomous AI Agent

Think, plan, use tools, execute tasks.
Not a chatbot. An autonomous agent.
"""

import json, logging, mimetypes, os, re, signal, subprocess, sys, time
import urllib.error, urllib.request
from datetime import datetime
from pathlib import Path

# Config
BOT_TOKEN=os.environ.get("BOT_TOKEN", "")
API_KEY=os.environ.get("API_KEY", "")
API_BASE = os.environ.get("API_BASE", "https://api.xiaomimimo.com/v1")
MODEL = os.environ.get("MODEL", "mimo-v2.5")
ALLOWED = set()
_raw = os.environ.get("ALLOWED_CHATS", "")
if _raw:
    try:
        ALLOWED = {int(c.strip()) for c in _raw.split(",") if c.strip()}
    except ValueError:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("agent")
_shutdown = False

def _sig(s, f):
    global _shutdown
    _shutdown = True

TG = "https://api.telegram.org/bot{}".format(BOT_TOKEN) if BOT_TOKEN else ""


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def tg(method, data=None, timeout=10):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request("{}/{}".format(TG, method), data=body)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def send(cid, text):
    try:
        if len(text) <= 4096:
            tg("sendMessage", {"chat_id": cid, "text": text})
        else:
            for i in range(0, len(text), 4096):
                tg("sendMessage", {"chat_id": cid, "text": text[i:i+4096]})
                time.sleep(0.1)
    except Exception as e:
        logger.error("Send: %s", e)


def send_file(cid, path, method="sendVideo", caption=""):
    try:
        mime = mimetypes.guess_type(path)[0] or "video/mp4"
        bnd = "----X{}".format(int(time.time() * 1000))
        with open(path, "rb") as f:
            data = f.read()
        fname = os.path.basename(path)
        key = "video" if "Video" in method else "audio"
        header = (
            "--{}\r\n"
            'Content-Disposition: form-data; name="chat_id"\r\n\r\n{}\r\n'
            "--{}\r\n"
            'Content-Disposition: form-data; name="caption"\r\n\r\n{}\r\n'
            "--{}\r\n"
            'Content-Disposition: form-data; name="{}"; filename="{}"\r\n'
            "Content-Type: {}\r\n\r\n"
        ).format(bnd, cid, bnd, caption[:1024], bnd, key, fname, mime)
        body = header.encode() + data + ("\r\n--{}--\r\n".format(bnd)).encode()
        req = urllib.request.Request("{}/{}".format(TG, method), data=body)
        req.add_header("Content-Type", "multipart/form-data; boundary={}".format(bnd))
        urllib.request.urlopen(req, timeout=120)
    except Exception as e:
        logger.error("Send file: %s", e)


def typing(cid):
    try:
        tg("sendChatAction", {"chat_id": cid, "action": "typing"}, timeout=5)
    except Exception:
        pass


def dl_file(fid, name):
    try:
        info = tg("getFile", {"file_id": fid}, timeout=15)
        if not info.get("ok"):
            return None
        fp = info["result"]["file_path"]
        url = "https://api.telegram.org/file/bot{}/{}".format(BOT_TOKEN, fp)
        local = "/tmp/{}".format(os.path.basename(name).replace("..", "_"))
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=120) as r:
            with open(local, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        return local
    except Exception as e:
        logger.error("Download: %s", e)
        return None


# ---------------------------------------------------------------------------
# Brain (MiMo LLM)
# ---------------------------------------------------------------------------

class Brain:
    def __init__(self):
        self.hist = {}

    def system_prompt(self):
        return (
            "You are MiMo Agent -- an autonomous AI that thinks step-by-step and uses tools.\n\n"
            "TOOLS:\n"
            "- shell: Execute shell command. Args: {command: str}\n"
            "- video_edit: Edit video (trim, concat, overlay_text, extract_audio, remove_audio, speed, resize, gif, rotate). "
            "Args: {video_path: str, action: str, start?: float, end?: float, text?: str, position?: str}\n"
            "- video_info: Get video metadata. Args: {video_path: str}\n"
            "- video_dub: Dub video (transcribe+translate+TTS). Args: {video_path: str, source_lang: str, target_lang: str}\n"
            "- video_download: Download from YouTube/Bilibili/etc. Args: {url: str, quality?: str}\n"
            "- tts_generate: Vietnamese speech. Args: {text: str, engine?: str, voice?: str}\n"
            "- web_search: Search web. Args: {query: str}\n\n"
            "RESPONSE FORMAT:\n"
            "THOUGHT: <your reasoning>\n"
            'ACTION: {"tool": "tool_name", "args": {...}}\n\n'
            "If no tool needed, respond directly in the user's language.\n"
            "Chain multiple tool calls for complex tasks.\n"
            "When a tool returns a file path, mention it so the bot can send it.\n"
            "Be concise. Respond in the same language as the user."
        )

    def think(self, cid, msg):
        if cid not in self.hist:
            self.hist[cid] = []

        msgs = [{"role": "system", "content": self.system_prompt()}]
        msgs.extend(self.hist[cid][-20:])
        msgs.append({"role": "user", "content": msg})

        try:
            r = tg(
                "chat/completions",
                {"model": MODEL, "messages": msgs, "max_tokens": 1000, "temperature": 0.3},
                timeout=60,
            )
            content = r["choices"][0]["message"]["content"]
            self.hist[cid].append({"role": "user", "content": msg})
            self.hist[cid].append({"role": "assistant", "content": content})
            if len(self.hist[cid]) > 40:
                self.hist[cid] = self.hist[cid][-40:]
            return self._parse(content)
        except Exception as e:
            logger.error("LLM error: %s", e)
            return {"type": "resp", "content": "Error: {}".format(str(e)[:200])}

    def _parse(self, content):
        if "ACTION:" in content:
            for part in content.split("ACTION:")[1:]:
                try:
                    m = re.search(r"\{.*\}", part, re.DOTALL)
                    if m:
                        a = json.loads(m.group())
                        if "tool" in a:
                            thought = ""
                            if "THOUGHT:" in content:
                                thought = content.split("THOUGHT:")[1].split("ACTION:")[0].strip()
                            return {"type": "tool", "tool": a["tool"], "args": a.get("args", {}), "thought": thought}
                except (json.JSONDecodeError, ValueError):
                    continue
        # Clean THOUGHT prefix
        c = content
        if "THOUGHT:" in c:
            c = c.split("THOUGHT:")[-1]
            if "ACTION:" in c:
                c = c.split("ACTION:")[0]
            c = c.strip()
        return {"type": "resp", "content": (c or content).replace("**", "").replace("*", "")}


# ---------------------------------------------------------------------------
# Tool Executor
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).parent))


def exec_tool(name, args):
    try:
        if name == "shell":
            cmd = args.get("command", "")
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            out = r.stdout + r.stderr
            return out[:2000] if out else "(no output)"

        if name == "video_edit":
            from tools_video import video_edit
            return video_edit(**args).get("output", "Done")

        if name == "video_info":
            from tools_video import video_info
            return video_info(**args).get("output", "")

        if name == "video_dub":
            from studio import DubStudio
            s = DubStudio(api_key=API_KEY, api_base=API_BASE, model=MODEL)
            result = s.dub(**args)
            if result.get("file"):
                return "{}\nFile: {}".format(result["output"], result["file"])
            return result.get("output", "Done")

        if name == "video_download":
            from tools_video import video_download
            return video_download(**args).get("output", "")

        if name == "tts_generate":
            from tools_video import tts_generate
            result = tts_generate(**args)
            if result.get("file"):
                return "{}\nFile: {}".format(result["output"], result["file"])
            return result.get("output", "Done")

        if name == "web_search":
            import urllib.parse
            q = urllib.parse.quote(args.get("query", ""))
            url = "https://html.duckduckgo.com/html/?q={}".format(q)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode("utf-8", errors="ignore")
            results = re.findall(r'class="result__a" href="([^"]+)"[^>]*>([^<]+)</a>', html)
            if results:
                lines = []
                for i, (link, title) in enumerate(results[:5], 1):
                    lines.append("{}. {}\n{}".format(i, title.strip(), link))
                return "\n\n".join(lines)
            return "No results"

        return "Unknown tool: {}".format(name)

    except Exception as e:
        return "Error: {}".format(str(e)[:300])


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    def __init__(self):
        self.brain = Brain()

    def process(self, cid, msg, media=None):
        typing(cid)
        if media:
            msg = "File: {}\n\nRequest: {}".format(media, msg)

        for iteration in range(5):
            r = self.brain.think(cid, msg)
            if r["type"] == "resp":
                return r["content"]
            if r["type"] == "tool":
                tool_name = r["tool"]
                tool_args = r["args"]
                logger.info("Tool[%d]: %s(%s)", iteration, tool_name, json.dumps(tool_args, default=str)[:200])
                result = exec_tool(tool_name, tool_args)
                msg = "Tool result ({}):\n{}\n\nContinue the task.".format(tool_name, result)

        return "Max iterations reached."


# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

def main():
    global _shutdown

    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set")
        sys.exit(1)
    if not API_KEY:
        print("ERROR: API_KEY not set")
        sys.exit(1)

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    agent = Agent()

    logger.info("=" * 50)
    logger.info("MiMo Agent v2 | Model: %s", MODEL)
    logger.info("Tools: shell, video_edit, video_dub, video_download, tts, web_search")
    logger.info("Allowed chats: %s", ALLOWED or "all")
    logger.info("=" * 50)

    # Get offset
    try:
        r = tg("getUpdates", {"offset": -1, "timeout": 1}, timeout=5)
        offset = r["result"][-1]["update_id"] + 1 if r.get("result") else 0
    except Exception:
        offset = 0

    while not _shutdown:
        try:
            result = tg("getUpdates", {"offset": offset, "timeout": 30}, timeout=60)
            for u in result.get("result", []):
                if _shutdown:
                    break
                offset = u["update_id"] + 1
                msg = u.get("message")
                if not msg:
                    continue

                cid = msg.get("chat", {}).get("id")
                if cid is None:
                    continue
                if ALLOWED and cid not in ALLOWED:
                    continue
                if msg.get("from", {}).get("is_bot"):
                    continue

                text = msg.get("text", "")
                media = None

                # Handle video/document
                if msg.get("video") or (
                    msg.get("document")
                    and msg["document"].get("file_name", "").endswith(
                        (".mp4", ".avi", ".mov", ".mkv", ".webm")
                    )
                ):
                    fo = msg.get("video") or msg.get("document")
                    fid = fo.get("file_id", "")
                    fname = fo.get("file_name", "video_{}.mp4".format(int(time.time())))
                    typing(cid)
                    send(cid, "Downloading...")
                    media = dl_file(fid, fname)
                    if not media:
                        send(cid, "Download failed")
                        continue
                    if not text:
                        text = "Process this video: {}".format(media)

                # Handle voice
                elif msg.get("voice"):
                    typing(cid)
                    media = dl_file(msg["voice"]["file_id"], "voice_{}.ogg".format(int(time.time())))
                    if media:
                        text = "Transcribe: {}".format(media)
                    else:
                        send(cid, "Download failed")
                        continue

                if not text:
                    continue

                logger.info("[%d] %s", cid, text[:100])

                try:
                    response = agent.process(cid, text, media)
                    if not response:
                        response = "No response."
                    send(cid, response)

                    # Auto-send result files
                    fm = re.search(r"File: (/tmp/[^\s\"']+)", response)
                    if fm and os.path.exists(fm.group(1)):
                        fp = fm.group(1)
                        ext = os.path.splitext(fp)[1].lower()
                        if ext in (".mp4", ".avi", ".mov", ".mkv", ".gif"):
                            send_file(cid, fp, "sendVideo", "Result")
                        elif ext in (".mp3", ".wav", ".ogg", ".m4a"):
                            send_file(cid, fp, "sendAudio", "Audio")

                except Exception as e:
                    logger.exception("Agent error")
                    send(cid, "Error: {}".format(str(e)[:200]))

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("Poll error: %s", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
