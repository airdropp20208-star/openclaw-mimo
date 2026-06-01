#!/bin/bash
# OpenClaw Dubbing Studio — Quick Start

echo "🎬 OpenClaw Dubbing Studio"
echo "=========================="
echo ""

# Check .env
if [ -f .env ]; then
    source .env
    echo "✅ Loaded .env"
fi

# Check env vars
if [ -z "$BOT_TOKEN" ] || [ -z "$API_KEY" ]; then
    echo "❌ Set environment variables:"
    echo ""
    echo "  Option 1: Create .env file"
    echo "    echo 'BOT_TOKEN=*** export API_KEY=*** echo 'ALLOWED_CHATS=7563947218' > .env"
    echo "    source .env"
    echo ""
    echo "  Option 2: Export directly"
    echo "    export BOT_TOKEN=*** export API_KEY=*** export ALLOWED_CHATS=7563947218"
    echo ""
    exit 1
fi

echo "✅ Config OK"
echo "   BOT_TOKEN: ${BOT_TOKEN:0:10}..."
echo "   API_KEY: ${API_KEY:0:10}..."
echo ""

# Install deps
echo "📦 Checking dependencies..."
pip install -q yt-dlp edge-tts faster-whisper pydub numpy pillow requests 2>/dev/null
echo "✅ Dependencies OK"
echo ""

# Choose mode
echo "Chọn mode:"
echo "  1) Foreground (Ctrl+C to stop)"
echo "  2) Background (daemon)"
echo "  3) Just test"
echo ""
read -p "Choice [1]: " CHOICE
CHOICE=${CHOICE:-1}

case $CHOICE in
    1)
        echo "🚀 Starting in foreground..."
        python3 dubbing_bot.py
        ;;
    2)
        echo "🚀 Starting as daemon..."
        chmod +x daemon.sh
        ./daemon.sh start
        echo "📄 Log: tail -f dubbing_bot.log"
        echo "🛑 Stop: ./daemon.sh stop"
        ;;
    3)
        echo "🧪 Testing..."
        python3 -c "
import sys
sys.path.insert(0, '.')
from studio import DubStudio
from tools_video import video_edit, tts_generate, video_dub
print('✅ All imports OK')
print('✅ Studio ready')
print('✅ Tools ready')
"
        echo "✅ Test passed! Ready to run."
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
