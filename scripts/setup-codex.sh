#!/bin/bash
# Codex + 9router + ds2api Setup Script
# For Ubuntu/Debian VPS

set -e

echo "============================================"
echo "  CODEX + 9ROUTER + DS2API SETUP"
echo "============================================"
echo ""

# ==================== CHECK ROOT ====================
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root: sudo bash setup-codex.sh"
  exit 1
fi

# ==================== INSTALL DEPENDENCIES ====================
echo "[1/6] Installing dependencies..."
apt-get update -qq
apt-get install -y -qq curl git build-essential

# ==================== INSTALL NODE.JS ====================
echo "[2/6] Installing Node.js 20..."
if ! command -v node &> /dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -qq nodejs
fi
echo "Node: $(node --version)"
echo "npm: $(npm --version)"

# ==================== INSTALL CODEX ====================
echo "[3/6] Installing Codex..."
npm install -g @openai/codex
echo "Codex: $(codex --version 2>/dev/null || echo 'installed')"

# ==================== INSTALL 9ROUTER ====================
echo "[4/6] Installing 9router..."
npm install -g 9router
mkdir -p ~/.9router
echo "9router installed"

# ==================== INSTALL DS2API ====================
echo "[5/6] Installing ds2api..."
DS2API_VERSION="v4.6.1"
ARCH=$(uname -m)
if [ "$ARCH" = "x86_64" ]; then
  DS2API_ARCH="amd64"
elif [ "$ARCH" = "aarch64" ]; then
  DS2API_ARCH="arm64"
else
  echo "Unsupported architecture: $ARCH"
  exit 1
fi

cd /opt
curl -L -o ds2api.tar.gz "https://github.com/CJackHwang/ds2api/releases/download/${DS2API_VERSION}/ds2api_${DS2API_VERSION}_linux_${DS2API_ARCH}.tar.gz"
tar -xzf ds2api.tar.gz
mv ds2api_${DS2API_VERSION}_linux_${DS2API_ARCH} ds2api
chmod +x ds2api/ds2api
rm ds2api.tar.gz
echo "ds2api installed at /opt/ds2api"

# ==================== CONFIGURE DS2API ====================
echo "[6/6] Configuring services..."

read -p "DeepSeek Email: " DS_EMAIL
read -p "DeepSeek Password: " DS_PASS
read -p "API Key (default: sk-mykey): " API_KEY
API_KEY=${API_KEY:-sk-mykey}

cat > /opt/ds2api/config.json << EOF
{
  "keys": ["$API_KEY"],
  "accounts": [{"email": "$DS_EMAIL", "password": "$DS_PASS"}],
  "model_aliases": {
    "gpt-4o": "deepseek-v4-flash",
    "gpt-5": "deepseek-v4-pro",
    "codex-mini": "deepseek-v4-flash"
  },
  "runtime": {"account_max_inflight": 2, "token_refresh_interval_hours": 6}
}
EOF

# ==================== CREATE START SCRIPT ====================
cat > /usr/local/bin/start-ai-stack << 'STARTEOF'
#!/bin/bash
echo "Starting AI Stack..."

# Start ds2api
cd /opt/ds2api
nohup ./ds2api > /tmp/ds2api.log 2>&1 &
echo $! > /tmp/ds2api.pid
echo "ds2api: port 5001"

# Start 9router
nohup 9router > /tmp/9router.log 2>&1 &
echo $! > /tmp/9router.pid
echo "9router: port 20128"

sleep 5
echo ""
echo "Services started!"
echo "  ds2api:  http://localhost:5001"
echo "  9router: http://localhost:20128"
echo ""
echo "Use Codex:"
echo "  export OPENAI_BASE_URL=http://localhost:20128"
echo "  export OPENAI_API_KEY=sk-mykey"
echo "  codex \"your prompt here\""
STARTEOF
chmod +x /usr/local/bin/start-ai-stack

# ==================== CREATE STOP SCRIPT ====================
cat > /usr/local/bin/stop-ai-stack << 'STOPEOF'
#!/bin/bash
echo "Stopping AI Stack..."
kill $(cat /tmp/ds2api.pid 2>/dev/null) 2>/dev/null && echo "ds2api stopped"
kill $(cat /tmp/9router.pid 2>/dev/null) 2>/dev/null && echo "9router stopped"
rm -f /tmp/ds2api.pid /tmp/9router.pid
echo "Done!"
STOPEOF
chmod +x /usr/local/bin/stop-ai-stack

# ==================== CREATE CODEX ALIAS ====================
cat > /usr/local/bin/ai-codex << 'CODEXEOF'
#!/bin/bash
export OPENAI_BASE_URL=http://localhost:20128
export OPENAI_API_KEY=sk-mykey
codex "$@"
CODEXEOF
chmod +x /usr/local/bin/ai-codex

# ==================== DONE ====================
echo ""
echo "============================================"
echo "  SETUP COMPLETE!"
echo "============================================"
echo ""
echo "Start services:"
echo "  start-ai-stack"
echo ""
echo "Use Codex:"
echo "  ai-codex \"write a Python script\""
echo ""
echo "Or manually:"
echo "  export OPENAI_BASE_URL=http://localhost:20128"
echo "  export OPENAI_API_KEY=sk-mykey"
echo "  codex \"your prompt\""
echo ""
echo "Stop services:"
echo "  stop-ai-stack"
echo ""
echo "Dashboard:"
echo "  http://localhost:20128/dashboard"
echo ""
