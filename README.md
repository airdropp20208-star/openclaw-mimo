# 🧠⚡ Hermes-OpenManus

**Multi-Agent AI System** — Kết hợp 3 lớp thông minh: Brain + Executor + Coordinator

## 🏗️ Kiến trúc

```
┌─────────────────────────────────────────────────┐
│                  Telegram User                   │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│              🎯 Intent Router                    │
│   Simple Chat → LLM | Task → Executor |         │
│   Multi-step → Coordinator                      │
└──────┬───────────────┬──────────────────┬───────┘
       │               │                  │
┌──────▼──────┐ ┌──────▼──────┐ ┌────────▼────────┐
│ 🧠 Hermes   │ │ ⚡ OpenManus │ │ 🎼 AutoGen      │
│ Brain       │ │ Executor    │ │ Coordinator     │
│             │ │             │ │ (optional)      │
│ • Skills    │ │ • Shell     │ │ • Planner       │
│ • Memory    │ │ • Browser   │ │ • Coder         │
│ • Context   │ │ • File Ops  │ │ • Critic        │
│ • Learning  │ │ • Search    │ │ • Executor      │
│             │ │ • Media     │ │                 │
└─────────────┘ └─────────────┘ └─────────────────┘
```

## 📁 Cấu trúc

```
src/
├── core/
│   ├── router.py        # 🎯 Intent Router — phân loại yêu cầu
│   ├── brain.py         # 🧠 Hermes Brain — bộ nhớ + skills
│   ├── executor.py      # ⚡ OpenManus Executor — thực thi tác vụ
│   └── coordinator.py   # 🎼 AutoGen Coordinator (tùy chọn)
├── tools/
│   ├── shell.py         # Shell execution
│   ├── browser.py       # Web browsing
│   ├── file_ops.py      # File operations
│   ├── search.py        # Web search
│   └── media.py         # Media conversion
├── memory/
│   ├── skills.py        # Skill storage & retrieval
│   └── context.py       # Conversation context
├── llm/
│   └── client.py        # LLM API client (Xiaomi MiMo)
└── bot/
    ├── telegram.py      # Telegram bot interface
    └── handlers.py      # Command handlers
main.py                  # Entry point
```

## 🚀 Cài đặt

```bash
# Clone
git clone https://github.com/airdropp20208-star/hermes-mimo-by-son.git
cd hermes-mimo-by-son

# Setup
chmod +x setup.sh
./setup.sh

# Run
export BOT_TOKEN="your-telegram-bot-token"
export API_KEY="your-xiaomi-mimo-api-key"
python main.py
```

## 🔧 Commands

| Command | Mô tả |
|---------|-------|
| `/start` | Hiển thị hướng dẫn |
| `/search <query>` | Tìm kiếm web |
| `/convert <file> <fmt>` | Chuyển đổi file |
| `/browse <url>` | Đọc & tóm tắt trang web |
| `/analyze <file>` | Phân tích file |
| `/ppt <text/file>` | Tạo PowerPoint |
| `/skills` | Xem danh sách skills đã học |
| `/remember <text>` | Lưu memory |
| `/recall` | Xem memory |
| `/mcp` | Danh sách MCP tools |
| `!cmd <command>` | Chạy shell command |
| `!upload <path>` | Gửi file |
| `!scan` | Thông tin hệ thống |

## 🧠 3 Lớp Thông Minh

### 1. 🧠 Hermes Brain — "Bộ não ghi nhớ"
- Lưu trữ **skills** từ mỗi nhiệm vụ thành công
- Tìm kiếm skills tương tự cho nhiệm vụ mới
- Theo dõi **context** hội thoại (sliding window)
- Tự động **học hỏi** từ kết quả

### 2. ⚡ OpenManus Executor — "Cánh tay thực thi"
- Nhận yêu cầu phức tạp, chia nhỏ thành bước
- Sử dụng **tools**: Shell, Browser, File, Search, Media
- Tự động **fix lỗi** và retry
- Trả kết quả có cấu trúc

### 3. 🎼 AutoGen Coordinator — "Nhạc trưởng" (tùy chọn)
- Phân phối công việc giữa nhiều agent
- Planner → Coder → Critic → Executor
- Fallback về single-agent nếu không có autogen

## 🔑 Environment Variables

| Variable | Required | Mô tả |
|----------|----------|-------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token |
| `API_KEY` | ✅ | Xiaomi MiMo API Key |
| `API_KEYS` | ❌ | Additional keys (comma-separated, for rotation) |
| `API_BASE` | ❌ | API Base URL (default: https://api.xiaomimimo.com/v1) |
| `MODEL` | ❌ | Model name (default: mimo-v2.5) |
| `ALLOWED_CHATS` | ❌ | Allowed chat IDs (comma-separated) |

## 📊 Tech Stack

- **LLM**: Xiaomi MiMo v2.5 (OpenAI-compatible API)
- **Language**: Python 3.12
- **Bot**: Telegram Bot API (polling)
- **Tools**: Shell, Playwright, ffmpeg, ImageMagick, markitdown
- **Memory**: JSON file storage
- **Optional**: AutoGen (multi-agent), Hermes Agent (skills)

## 📄 License

MIT
