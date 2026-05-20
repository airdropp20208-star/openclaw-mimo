#!/bin/bash
set -e

echo "=== PhantomBot v8 Full Setup ==="

# System deps
sudo apt-get update -qq
sudo apt-get install -y -qq xvfb scrot imagemagick poppler-utils ffmpeg curl jq openssh-server

# Python packages
pip install -q "markitdown[all]" python-pptx openpyxl python-docx pymupdf anthropic playwright cloakbrowser ui-tars
playwright install chromium --with-deps 2>/dev/null || true

# Node.js MCP tools
npm install -g \
  @modelcontextprotocol/server-filesystem \
  @modelcontextprotocol/server-github \
  @supabase/mcp-server-supabase \
  @upstash/context7-mcp \
  @colbymchenry/codegraph \
  @anthropic-ai/mcp-sequential-thinking

# CodeGraph init
codegraph init -i --yes 2>/dev/null || true

# Clone apps
git clone https://github.com/hugohe3/ppt-master.git /tmp/ppt-master 2>/dev/null || true
cd /tmp/ppt-master && pip install -r requirements.txt 2>/dev/null || true
git clone https://github.com/opencut-app/opencut.git /tmp/opencut 2>/dev/null || true

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
