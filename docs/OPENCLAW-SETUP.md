# OpenClaw + Claude Code + 9router + ds2api Setup

## Flow

```
Telegram → OpenClaw → Claude Code → 9router (20128) → ds2api (5001) → DeepSeek
```

## Quick Start

### 1. Install OpenClaw

```bash
# On VPS (Ubuntu/Debian)
curl -fsSL https://raw.githubusercontent.com/openclaw/openclaw/main/install.sh | bash
```

Or via npm:
```bash
npm install -g openclaw
```

### 2. Install 9router + ds2api

```bash
# Install 9router
npm install -g 9router

# Download ds2api
curl -L -o ds2api.tar.gz "https://github.com/CJackHwang/ds2api/releases/download/v4.6.1/ds2api_v4.6.1_linux_amd64.tar.gz"
tar -xzf ds2api.tar.gz
mv ds2api_v4.6.1_linux_amd64 ds2api
chmod +x ds2api/ds2api
```

### 3. Configure OpenClaw

Edit `~/.openclaw/openclaw.json`:

```json
{
  "model": "claude-sonnet-4-6",
  "provider": {
    "type": "openai",
    "baseURL": "http://localhost:20128/v1",
    "apiKey": "sk-mykey"
  },
  "telegram": {
    "enabled": true,
    "botToken": "YOUR_BOT_TOKEN"
  }
}
```

### 4. Configure ds2api

Edit `ds2api/config.json`:

```json
{
  "keys": ["sk-mykey"],
  "accounts": [
    {
      "email": "your-deepseek-email",
      "password": "your-deepseek-password"
    }
  ],
  "model_aliases": {
    "claude-sonnet-4-6": "deepseek-v4-flash",
    "claude-opus-4-6": "deepseek-v4-pro"
  }
}
```

### 5. Start Services

```bash
# Terminal 1: ds2api
cd ds2api && ./ds2api

# Terminal 2: 9router
9router

# Terminal 3: OpenClaw
openclaw
```

### 6. Connect Telegram

1. Talk to [@BotFather](https://t.me/BotFather)
2. Create new bot → copy token
3. Add token to `~/.openclaw/openclaw.json`
4. Restart OpenClaw
5. Message your bot on Telegram!

## Usage

**From Telegram:**
```
/help - Show commands
/code write a Python script - Use Claude Code
/search something - Web search
```

**From terminal:**
```bash
openclaw "your prompt here"
```

## Services

| Service | Port | Description |
|---------|------|-------------|
| ds2api | 5001 | DeepSeek → OpenAI API |
| 9router | 20128 | AI router + dashboard |
| OpenClaw | - | Telegram gateway |

## Flow Diagram

```
┌─────────────────────────────────────────────────┐
│                    Telegram                      │
│              (Send commands)                     │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│                  OpenClaw                        │
│         (Telegram gateway + AI agent)            │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│               Claude Code CLI                    │
│          (AI coding assistant)                   │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              9router (port 20128)                │
│        (Smart AI router + token saver)           │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              ds2api (port 5001)                  │
│       (DeepSeek Web → OpenAI API)                │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              DeepSeek API                        │
│          (Free V4 Flash/Pro)                     │
└─────────────────────────────────────────────────┘
```

## Troubleshooting

**Bot not responding:**
1. Check bot token in config
2. Check OpenClaw logs
3. Verify 9router is running

**Claude Code errors:**
1. Check 9router: `curl http://localhost:20128/v1/models`
2. Check ds2api: `curl http://localhost:5001/healthz`
3. Check config in `~/.openclaw/openclaw.json`

## Links

- OpenClaw: https://github.com/openclaw/openclaw
- 9router: https://github.com/decolua/9router
- ds2api: https://github.com/CJackHwang/ds2api
