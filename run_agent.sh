#!/bin/bash
# Run OpenClaw MiMo Dubbing Agent
# Usage: BOT_TOKEN=xxx MIMO_API_KEY=xxx OMNIVOICE_API_URL=xxx ./run_agent.sh

set -e

# Check required env vars
if [ -z "$BOT_TOKEN" ]; then
    echo "❌ BOT_TOKEN not set!"
    echo "Usage: BOT_TOKEN=xxx MIMO_API_KEY=xxx OMNIVOICE_API_URL=xxx ./run_agent.sh"
    exit 1
fi

if [ -z "$MIMO_API_KEY" ]; then
    echo "❌ MIMO_API_KEY not set!"
    exit 1
fi

if [ -z "$OMNIVOICE_API_URL" ]; then
    echo "❌ OMNIVOICE_API_URL not set!"
    exit 1
fi

# Install deps if needed
pip install -q python-telegram-bot yt-dlp faster-whisper pydub requests 2>/dev/null || true

echo "🚀 Starting OpenClaw MiMo Dubbing Agent..."
echo "   Bot Token: ${BOT_TOKEN:0:10}..."
echo "   MiMo API: ${MIMO_API_BASE:-https://api.xiaomimimo.com/v1}"
echo "   OmniVoice: $OMNIVOICE_API_URL"

# Run the bot
python3 telegram_agent.py
