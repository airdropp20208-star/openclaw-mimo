#!/bin/bash
# OpenClaw Dubbing Studio — Start Script

echo "🎬 OpenClaw Dubbing Studio"
echo "=========================="

# Check env
if [ -z "$BOT_TOKEN" ] || [ -z "$API_KEY" ]; then
    echo "❌ Set environment variables:"
    echo "   export BOT_TOKEN='your...port export API_KEY='your...'
    echo "   export ALLOWED_CHATS='your_telegram_id'"
    exit 1
fi

echo "✅ Config loaded"
echo "   BOT_TOKEN: ${BOT_TOKEN:0:10}..."
echo "   API_KEY: ${API_KEY:0:10}..."

# Install deps
echo "📦 Installing dependencies..."
pip install -q yt-dlp edge-tts faster-whisper pydub numpy pillow requests 2>/dev/null

# Start bot
echo "🚀 Starting dubbing bot..."
python3 dubbing_bot.py
