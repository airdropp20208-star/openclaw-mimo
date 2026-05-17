# Phantom Node

> Free AI environment: Claude Code + DeepSeek via GitHub Actions

## What is this?

A free AI coding environment powered by GitHub Actions:

```
Claude Code → 9router → ds2api → DeepSeek (FREE!)
```

- **Claude Code** - AI coding assistant
- **DeepSeek** - Free AI model (V4 Flash/Pro)
- **9router** - Smart AI router with token savings
- **ds2api** - DeepSeek to API converter
- **Hermes Agent** - Telegram bot control
- **SSH Access** - Via Cloudflare tunnel

## Quick Start (3 minutes)

### 1. Fork this repo

### 2. Add Secrets

Go to **Settings → Secrets and variables → Actions**:

| Secret | Description | Required |
|--------|-------------|----------|
| `BOT_TOKEN` | Telegram bot token from @BotFather | Yes |
| `XIAOMI_API_KEY` | Your Mimo API key | Optional |

### 3. Run Workflow

Go to **Actions → Deploy → Run workflow**

Optional inputs:
- `api_key` - Override Mimo API key
- `deepseek_email` - DeepSeek account email
- `deepseek_password` - DeepSeek account password

### 4. Connect

**SSH Access:**
```bash
ssh runner@<tunnel-url>
Password: phantom123
```

**Use Claude Code:**
```bash
# SSH into the runner
ssh runner@<tunnel-url>

# Use Claude Code (routed through DeepSeek)
claude "write a Python script to scrape websites"
```

**Telegram Bot:**
Just message your bot on Telegram!

## Architecture

```
┌─────────────────────────────────────────────────┐
│           GitHub Actions Runner (Ubuntu)         │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │         Claude Code CLI                  │   │
│  │    (AI coding assistant)                 │   │
│  └───────────────┬──────────────────────────┘   │
│                  │                              │
│                  ▼                              │
│  ┌──────────────────────────────────────────┐   │
│  │         9router (port 20128)             │   │
│  │    Smart AI router + RTK token saver     │   │
│  └───────────────┬──────────────────────────┘   │
│                  │                              │
│                  ▼                              │
│  ┌──────────────────────────────────────────┐   │
│  │         ds2api (port 5001)               │   │
│  │    DeepSeek Web → OpenAI API             │   │
│  └───────────────┬──────────────────────────┘   │
│                  │                              │
│                  ▼                              │
│  ┌──────────────────────────────────────────┐   │
│  │         DeepSeek API                     │   │
│  │    (Free V4 Flash/Pro models)            │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │         Hermes Gateway                   │   │
│  │    Telegram bot + CLI tools              │   │
│  └──────────────────────────────────────────┘   │
│                                                  │
│  ┌──────────────────────────────────────────┐   │
│  │         Cloudflare Tunnel                │   │
│  │    SSH access from anywhere              │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

## Services Running

| Service | Port | Description |
|---------|------|-------------|
| ds2api | 5001 | DeepSeek API converter |
| 9router | 20128 | AI router + dashboard |
| Claude Code | - | Via 9router |
| Hermes | - | Telegram bot |
| SSH | 22 | Via Cloudflare tunnel |

## Usage Examples

**Claude Code (via SSH):**
```bash
ssh runner@<tunnel-url>
# Password: phantom123

# Use Claude Code
claude "create a REST API with FastAPI"
claude "debug this Python code"
claude "write tests for my project"
```

**Telegram Bot:**
```
/help - Show commands
/run python script.py - Execute code
/search something - Web search
/read file.txt - Read files
```

**9router Dashboard:**
- Open http://localhost:20128/dashboard
- View token usage
- Configure providers
- Monitor requests

## Features

- **Free** - GitHub Actions provides 2,000 minutes/month
- **Full environment** - Python, Node.js, Docker, Git
- **Claude Code** - AI coding with DeepSeek backend
- **Token savings** - RTK saves 20-40% tokens
- **Auto-recovery** - Services restart if they crash
- **6-hour sessions** - Maximum GitHub Actions timeout

## DeepSeek Models

| Model | Alias | Thinking |
|-------|-------|----------|
| deepseek-v4-flash | claude-sonnet-4-6 | ✅ |
| deepseek-v4-pro | claude-opus-4-6 | ✅ |
| deepseek-v4-flash-nothinking | - | ❌ |
| deepseek-v4-pro-nothinking | - | ❌ |

## Limitations

- **6-hour max** - GitHub Actions jobs timeout
- **No persistence** - Data lost when job ends
- **Rate limits** - GitHub API limits apply

## Troubleshooting

**Claude Code not working:**
```bash
# Check services
curl http://localhost:5001/healthz  # ds2api
curl http://localhost:20128          # 9router

# Check config
cat ~/.claude/config.json
echo $ANTHROPIC_BASE_URL
```

**Services crashed:**
- They auto-restart within 5 minutes
- Check logs: `cat ds2api.log 9router.log hermes-gateway.log`

**SSH not working:**
- Wait 1-2 minutes for tunnel
- Check CONNECTION.md for updated URL

## Credits

- [ds2api](https://github.com/CJackHwang/ds2api) - DeepSeek to API
- [9router](https://github.com/decolua/9router) - AI router
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - AI coding
- [Hermes Agent](https://github.com/NousResearch/hermes-agent) - Agent framework

## License

MIT
