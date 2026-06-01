#!/bin/bash
# OpenClaw MiMo Telegram Agent
set -e

export BOT_TOKEN="${BO...?Set BOT_TOKEN}"
export ALLOWED_CHATS="${ALLOWED_CHATS:-7563947218}"
export MIMO_API_KEY="${MI...port MIMO_API_BASE="${MIMO_API_BASE:-https://api.xiaomimimo.com/v1}"
export MIMO_MODEL="${MIMO_MODEL:-mimo-v2.5-pro}"
export OMNIVOICE_API_URL="${OMNIVOICE_API_URL:-}"
export OMNIVOICE_API_KEY="${OM...port DATA_DIR="${DATA_DIR:-/tmp/openclaw-mimo}"

echo "🎬 OpenClaw MiMo Telegram Agent"
echo "  Bot: ${BOT_TOKEN:0:10}..."
echo "  Allowed: $ALLOWED_CHATS"
echo "  OmniVoice: ${OMNIVOICE_API_URL:-NOT SET}"

exec python3 telegram_agent.py
