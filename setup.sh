#!/bin/bash
set -e

echo "=== Hermes-OpenManus Multi-Agent System Setup ==="

# System deps
sudo apt-get update -qq
sudo apt-get install -y -qq xvfb scrot imagemagick poppler-utils ffmpeg curl jq openssh-server

# Python packages
pip install -q -r requirements.txt

# Optional: AutoGen for multi-agent coordination
pip install -q pyautogen 2>/dev/null || echo "AutoGen not installed (optional)"

# Browser automation
pip install -q playwright 2>/dev/null || true
playwright install chromium --with-deps 2>/dev/null || true

# Node.js MCP tools
npm install -g \
  @modelcontextprotocol/server-filesystem \
  @modelcontextprotocol/server-github \
  @supabase/mcp-server-supabase \
  @upstash/context7-mcp \
  @colbymchenry/codegraph \
  @anthropic-ai/mcp-sequential-thinking 2>/dev/null || true

# CodeGraph init
codegraph init -i --yes 2>/dev/null || true

# SSH tunnel
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared
sudo systemctl start ssh 2>/dev/null || sudo service ssh start 2>/dev/null || true
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
echo "runner:phantom123" | sudo chpasswd
sudo systemctl restart ssh 2>/dev/null || sudo service ssh restart 2>/dev/null || true
nohup cloudflared tunnel --url ssh://localhost:22 > tunnel.log 2>&1 &
echo $! > tunnel.pid

echo "=== Setup Complete ==="
echo "Bot: python main.py"
echo "Architecture: Hermes Brain + OpenManus Executor + AutoGen Coordinator"
