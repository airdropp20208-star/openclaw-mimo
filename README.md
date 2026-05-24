# Hermes Agent + OpenManus Tools

Telegram AI bot powered by Hermes Agent (Xiaomi MiMo) with OpenManus tool chain.

## Architecture

```
bot.py      → Telegram bot (polling, commands, file handling)
agent.py    → Agent loop (LLM + tool calling)
tools.py    → OpenManus tools (shell, file, browser, search, convert, ppt)
```

## How it works

1. User sends message to Telegram
2. `bot.py` receives and forwards to `agent.py`
3. Agent sends to LLM (Xiaomi MiMo API)
4. If LLM wants to use a tool → execute tool → send result back to LLM
5. Repeat until LLM gives final response
6. Response sent back to Telegram

## Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands |
| `file_read` | Read files |
| `file_write` | Write files |
| `file_list` | List directory |
| `browse` | Fetch webpage content |
| `search` | DuckDuckGo web search |
| `convert` | Convert file formats (pdf→md, mp4→mp3, etc.) |
| `ppt` | Generate PowerPoint presentations |

## Deploy

1. Set GitHub secrets: `BOT_TOKEN`, `ALLOWED_CHATS`
2. Run workflow with `api_key` input

```bash
BOT_TOKEN=xxx API_KEY=xxx python bot.py
```

## Commands

- `/start` — Help
- `/clear` — Clear history
- `/remember <text>` — Save memory
- `/recall` — View memory
- `/health` — System health
- Or just chat — agent auto-detects tool needs
