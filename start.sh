#!/bin/bash
# OpenClaw MiMo - Startup Script

echo "🎬 OpenClaw MiMo - Starting..."

# Check .env
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Create .env with:"
    echo "  BOT_TOKEN=your_telegram_bot_token"
    echo "  API_KEY=your_mimo_api_key"
    exit 1
fi

# Load env
source .env

# Check required vars
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ BOT_TOKEN not set in .env"
    exit 1
fi

if [ -z "$API_KEY" ]; then
    echo "❌ API_KEY not set in .env"
    exit 1
fi

echo "✅ Config loaded"
echo "   BOT_TOKEN: ${BOT_TOKEN:0:10}..."
echo "   API_KEY: ${API_KEY:0:10}..."

# Install deps if needed
echo "📦 Checking dependencies..."
pip install -q yt-dlp faster-whisper edge-tts 2>/dev/null

# Start bot
echo "🚀 Starting bot..."
export BOT_TOKEN API_KEY
python3 bot.py
