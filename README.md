# 🎬 OpenClaw Dubbing Studio

**Professional Video Dubbing Service** — Not a chatbot. A dedicated dubbing studio.

## 🎯 What It Does

Send a video → Get a dubbed version in Vietnamese. That's it.

## 🚀 Quick Start

```bash
# Set environment
export BOT_TOKEN="your_telegram_bot_token"
export API_KEY="your_mimo_api_key"
export ALLOWED_CHATS="your_telegram_id"

# Run
python3 dubbing_bot.py
```

## 📹 How to Use

### Option 1: Send Video
1. Send a video file to the bot
2. Add caption: `dịch sang tiếng việt`
3. Wait 2-3 minutes
4. Receive dubbed video

### Option 2: Send Link
```
https://youtu.be/xxxxx dịch sang tiếng việt
https://www.bilibili.com/video/xxxxx dịch trung → vi
```

## 🌐 Supported Languages

| Source | Target | Code |
|--------|--------|------|
| 🇨🇳 Chinese | 🇻🇳 Vietnamese | zh→vi |
| 🇬🇧 English | 🇻🇳 Vietnamese | en→vi |
| 🇯🇵 Japanese | 🇻🇳 Vietnamese | ja→vi |
| 🇰🇷 Korean | 🇻🇳 Vietnamese | ko→vi |

## ⚡ Performance

| Video Length | Processing Time |
|--------------|-----------------|
| 5 minutes | 2-3 minutes |
| 30 minutes | 10-15 minutes |
| 60 minutes | 20-30 minutes |

## 🛠 Tech Stack

- **Transcription**: Whisper large-v3
- **Translation**: MiMo-V2.5 (Xiaomi)
- **TTS**: Edge TTS / OmniVoice
- **Download**: yt-dlp (1000+ platforms)
- **Bot**: Python Telegram Bot API

## 📝 Commands

| Command | Description |
|---------|-------------|
| `/start` | Help |
| `/status` | Queue status |

## 🔧 Configuration

```bash
# Required
BOT_TOKEN=xxx        # Telegram bot token
API_KEY=xxx          # MiMo API key

# Optional
API_BASE=https://api.xiaomimimo.com/v1
MODEL=mimo-v2.5
ALLOWED_CHATS=123,456  # Comma-separated Telegram user IDs
```

## 🎬 Professional Features

- **Batch Processing**: Queue multiple videos
- **Subtitle Generation**: SRT, ASS, VTT formats
- **Voice Cloning**: Clone voices from reference audio
- **Audio Normalization**: Professional audio post-processing
- **Quality Presets**: Draft, Standard, Premium

## 📦 Installation

```bash
git clone https://github.com/airdropp20208-star/openclaw-mimo.git
cd openclaw-mimo
pip install -r requirements.txt
```

## 🚨 Important Notes

1. **GPU Recommended**: For faster transcription (Whisper)
2. **API Key Required**: MiMo API key for translation
3. **Storage**: Videos are processed in /tmp, auto-cleaned
4. **Size Limit**: 100MB per video

## 📄 License

MIT
