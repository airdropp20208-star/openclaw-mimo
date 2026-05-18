<p align="center">
  <img src="https://img.shields.io/badge/PHANTOM%20NODE-v7.0-purple?style=for-the-badge&labelColor=black" />
  <img src="https://img.shields.io/badge/DEEPSEEK%20V4-PRO-brightgreen?style=for-the-badge&labelColor=black" />
  <img src="https://img.shields.io/badge/STATUS-FREE-yellow?style=for-the-badge&labelColor=black" />
</p>

<h1 align="center"> phantom-node </h1>

<p align="center">
  <b>⚡ Telegram → Hermes → DeepSeek V4 Pro → Code Execution ⚡</b><br>
  <sub>Your free VPS for 6 hours — DeepSeek V4 Pro via ds2api (FREE!)</sub>
</p>

---

## 🔥 What is this?

**Phantom Node** turns GitHub Actions into a **free DeepSeek V4 Pro environment** with:

- **ds2api** — DeepSeek Web → OpenAI API gateway
- **Claude Code** — AI coding assistant (uses DeepSeek as backend)
- **Hermes** — Telegram bot + agent
- **Self-healing** — Auto-restarts crashed services
- **Zero cost** — Runs on GitHub Actions free tier

## ⚡ Architecture

```
┌─────────────────────────────────────────────────┐
│                    Telegram                      │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              Hermes Gateway                      │
│     (Routes messages to Claude Code)             │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              Claude Code CLI                     │
│         (AI coding assistant)                    │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              ds2api (5001)                       │
│       (DeepSeek Web → OpenAI API)                │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│              DeepSeek V4 Pro (FREE!)             │
└─────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Fork this repo

### 2. Add GitHub Secrets

- `BOT_TOKEN` — Telegram bot token
- `DS_EMAIL` — DeepSeek email (optional, has defaults)
- `DS_PASSWORD` — DeepSeek password (optional, has defaults)

### 3. Trigger workflow

Go to Actions → Deploy Phantom Node → Run workflow

### 4. Chat on Telegram

Message your bot on Telegram. It uses DeepSeek V4 Pro for FREE!

## 📊 Services

| Service | Port | Purpose |
|---------|------|---------|
| ds2api | `:5001` | DeepSeek → OpenAI API |
| Hermes | - | Telegram gateway |
| Claude Code | - | AI coding agent |

## 🛡️ Features

| Feature | Status |
|---------|--------|
| DeepSeek V4 Pro (FREE) | ✅ |
| OpenAI API compat | ✅ |
| Telegram bot | ✅ |
| Claude Code integration | ✅ |
| Self-healing | ✅ |
| SSH tunnel | ✅ |
| Auto-recovery | ✅ |

## 📜 License

MIT License
