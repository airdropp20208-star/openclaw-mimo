# 🧠⚡ Hermes-OpenManus

**Hybrid Multi-Agent AI System** — Go Core + Python AI

## 🏗️ Kiến trúc

```
┌─────────────────────────────────────────┐
│              🐹 Go Core                  │
│  • Telegram polling (goroutines)        │
│  • HTTP API server (:8080)              │
│  • Message routing + caching            │
│  • Health checks                        │
│  • Process watchdog                     │
│  • Graceful shutdown                    │
│  • Skills/Memory storage                │
└──────────────┬──────────────────────────┘
               │ HTTP localhost
┌──────────────▼──────────────────────────┐
│              🐍 Python AI                │
│  • LLM reasoning (MiMo API)             │
│  • Task decomposition                   │
│  • Skills learning                      │
│  • AutoGen coordination                 │
│  • Media processing (ffmpeg)            │
│  • Browser/File/Search tools            │
└─────────────────────────────────────────┘
```

## 📁 Cấu trúc

```
hermes-mimo-by-son/
├── go-core/                    # 🐹 Go Core
│   ├── main.go                 # Entry point
│   ├── config/config.go        # Configuration
│   ├── bot/telegram.go         # Telegram API
│   ├── api/server.go           # HTTP server
│   ├── core/router.go          # Intent routing
│   ├── core/health.go          # Health checks
│   ├── core/watchdog.go        # Process monitor
│   ├── core/graceful.go        # Shutdown handler
│   ├── storage/skills.go       # Skills storage
│   ├── storage/memory.go       # Conversation memory
│   └── client/python.go        # Python AI client
├── ai-server/                  # 🐍 Python AI
│   ├── server.py               # Flask HTTP server
│   ├── llm/client.py           # LLM API client
│   ├── ai/reasoner.py          # Task reasoning
│   ├── ai/executor.py          # Task execution
│   ├── ai/skills_learner.py    # Skills learning
│   └── tools/                  # Tool implementations
│       ├── shell.py
│       ├── browser.py
│       ├── file_ops.py
│       ├── search.py
│       └── media.py
├── src/                        # Legacy Python (optional)
├── start.sh                    # Start both services
└── README.md
```

## 🚀 Cài đặt

```bash
# Clone
git clone https://github.com/airdropp20208-star/hermes-mimo-by-son.git
cd hermes-mimo-by-son

# Run
chmod +x start.sh
BOT_TOKEN="your-token" API_KEY="your-key" ./start.sh
```

## 🔧 Tại sao Go + Python?

| Part | Language | Lý do |
|------|----------|-------|
| Telegram polling | 🐹 Go | Goroutines = 10k concurrent connections |
| HTTP routing | 🐹 Go | Compiled, ~0.1ms latency |
| Health checks | 🐹 Go | Concurrent, non-blocking |
| Process watch | 🐹 Go | Goroutine monitoring |
| LLM reasoning | 🐍 Python | Rich AI ecosystem |
| Skills learning | 🐍 Python | JSON + pattern matching |
| Media processing | 🐍 Python | ffmpeg/ImageMagick wrappers |
| Browser tools | 🐍 Python | Playwright/requests |

## 📊 Performance

| Metric | Python Only | Go + Python |
|--------|-------------|-------------|
| Memory | ~100MB | ~30MB |
| Startup | ~3s | ~0.5s |
| Concurrent chats | ~100 | ~10,000 |
| API latency | ~50ms | ~5ms |
| Binary size | N/A | ~15MB |

## 🔑 Environment Variables

| Variable | Required | Mô tả |
|----------|----------|-------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `API_KEY` | ✅ | Xiaomi MiMo API Key |
| `API_KEYS` | ❌ | Additional keys (comma-separated) |
| `API_BASE` | ❌ | API Base URL |
| `MODEL` | ❌ | Model name (default: mimo-v2.5) |
| `ALLOWED_CHATS` | ❌ | Allowed chat IDs |

## 📄 License

MIT
