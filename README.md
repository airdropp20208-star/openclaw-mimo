# Phantom Node

> Free AI environment via GitHub Actions + Telegram control

## What is this?

A free Windows/Ubuntu VPS powered by GitHub Actions with:
- **Hermes Agent** - AI assistant with tools
- **Xiaomi Mimo 2.5** - Free AI model
- **Telegram Bot** - Control from your phone
- **SSH Access** - Via Cloudflare tunnel

## How it works

```
GitHub Actions Runner (Ubuntu)
├── Python 3.11 + Node.js 20
├── Hermes Agent + Gateway
├── Xiaomi Mimo 2.5 API
├── Telegram Bot Connection
└── Cloudflare Tunnel (SSH)
```

## Setup (2 minutes)

### 1. Fork this repo

### 2. Add Secrets

Go to **Settings → Secrets and variables → Actions**:

| Secret | Description | Required |
|--------|-------------|----------|
| `BOT_TOKEN` | Telegram bot token from @BotFather | Yes |
| `XIAOMI_API_KEY` | Your Mimo API key | Yes |

### 3. Run Workflow

Go to **Actions → Deploy → Run workflow**

Optionally provide an `api_key` to override the secret.

### 4. Connect

**SSH Access:**
```bash
ssh runner@<tunnel-url>
Password: phantom123
```

**Telegram Bot:**
Just message your bot on Telegram!

## Architecture

```
┌─────────────────────────────────────────────┐
│           GitHub Actions Runner             │
│  ┌─────────────────────────────────────┐    │
│  │        Hermes Agent Gateway         │    │
│  │  ┌──────────┐  ┌────────────────┐  │    │
│  │  │ Telegram │  │   CLI Tools    │  │    │
│  │  │   Bot    │  │  (terminal,    │  │    │
│  │  └──────────┘  │   file, web)   │  │    │
│  │                 └────────────────┘  │    │
│  └─────────────────────────────────────┘    │
│  ┌─────────────────────────────────────┐    │
│  │        Cloudflare Tunnel           │    │
│  │        (SSH Access)                │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
           │
           ▼
    ┌──────────────┐
    │   Your Phone │
    │  (Telegram)  │
    └──────────────┘
```

## Features

- **Free** - GitHub Actions provides 2,000 minutes/month free
- **Full Linux environment** - Python, Node.js, Docker, Git
- **Hermes Agent** - 15+ toolsets (terminal, web, vision, etc.)
- **Telegram control** - Message your bot from anywhere
- **SSH access** - Cloudflare tunnel for direct access
- **Auto-recovery** - Gateway restarts if it crashes
- **6-hour sessions** - Maximum GitHub Actions timeout

## Usage Examples

**Via Telegram:**
```
/help - Show commands
/run python script.py - Execute code
/search something - Web search
/read file.txt - Read files
```

**Via SSH:**
```bash
ssh runner@<tunnel-url>
# Password: phantom123

# Run commands
hermes "install docker"

# Check status
hermes status
```

## Limitations

- **6-hour max** - GitHub Actions jobs timeout at 6 hours
- **No persistence** - Data lost when job ends
- **Public repo** - Code is visible (use private for secrets)
- **Rate limits** - GitHub API limits apply

## File Structure

```
phantom-node/
├── .github/workflows/
│   └── deploy.yml      # Main workflow
├── scripts/
│   └── setup.ps1       # Windows setup (legacy)
├── CONNECTION.md        # Auto-updated SSH info
├── README.md           # This file
└── .gitignore
```

## Troubleshooting

**Bot not responding:**
1. Check secrets are set correctly
2. Go to Actions → see if workflow is running
3. Check logs in workflow output

**SSH not working:**
1. Wait 1-2 minutes for tunnel to start
2. Check CONNECTION.md for updated URL
3. Password is always: `phantom123`

**Gateway crashed:**
- It auto-restarts within 5 minutes
- Check logs: `cat ~/.hermes/gateway.log`

## Credits

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) - AI assistant framework
- [Xiaomi Mimo](https://mimo.xiaomi.com/) - Free AI model
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) - Secure access

## License

MIT
