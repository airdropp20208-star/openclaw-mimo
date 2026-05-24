#!/bin/bash
set -e

echo "=== Hermes-OpenManus Hybrid System ==="
echo "🐹 Go Core (port 8080) + 🐍 Python AI (port 8081)"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check dependencies
echo "Checking dependencies..."

# Go
if ! command -v go &> /dev/null; then
    echo -e "${YELLOW}Installing Go...${NC}"
    wget -q https://go.dev/dl/go1.22.0.linux-amd64.tar.gz -O /tmp/go.tar.gz
    sudo tar -C /usr/local -xzf /tmp/go.tar.gz
    export PATH=$PATH:/usr/local/go/bin
    rm /tmp/go.tar.gz
fi
echo -e "${GREEN}✓ Go: $(go version)${NC}"

# Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python3 not found!${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python: $(python3 --version)${NC}"

# Build Go core
echo ""
echo "Building Go core..."
cd go-core
go mod tidy 2>/dev/null || true
go build -o ../hermes-core . 2>/dev/null || {
    echo -e "${YELLOW}Go build failed, using 'go run' instead${NC}"
    cd ..
    GO_BUILD_OK=false
}
cd ..
if [ -f hermes-core ]; then
    echo -e "${GREEN}✓ Go binary built: hermes-core${NC}"
    GO_BUILD_OK=true
fi

# Install Python deps
echo ""
echo "Installing Python dependencies..."
cd ai-server
pip install -q -r requirements.txt 2>/dev/null || pip install -q flask requests duckduckgo-search 2>/dev/null
cd ..
echo -e "${GREEN}✓ Python dependencies ready${NC}"

# Environment
export BOT_TOKEN="${BOT_TOKEN:-}"
export API_KEY="${API_KEY:-}"
export API_KEYS="${API_KEYS:-}"
export API_BASE="${API_BASE:-https://api.xiaomimimo.com/v1}"
export MODEL="${MODEL:-mimo-v2.5}"
export PYTHON_AI_URL="http://localhost:8081"
export GO_API_PORT="8080"

# Validate
if [ -z "$BOT_TOKEN" ]; then
    echo -e "${RED}Error: BOT_TOKEN not set${NC}"
    echo "Usage: BOT_TOKEN=xxx API_KEY=xxx ./start.sh"
    exit 1
fi

if [ -z "$API_KEY" ] && [ -z "$API_KEYS" ]; then
    echo -e "${RED}Error: API_KEY or API_KEYS not set${NC}"
    exit 1
fi

# Cleanup function
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down...${NC}"
    [ -n "$PYTHON_PID" ] && kill $PYTHON_PID 2>/dev/null
    [ -n "$GO_PID" ] && kill $GO_PID 2>/dev/null
    wait $PYTHON_PID 2>/dev/null
    wait $GO_PID 2>/dev/null
    echo -e "${GREEN}Shutdown complete${NC}"
    exit 0
}

trap cleanup SIGTERM SIGINT SIGHUP

# Start Python AI server
echo ""
echo "Starting Python AI server (port 8081)..."
cd ai-server
python3 server.py &
PYTHON_PID=$!
cd ..
echo -e "${GREEN}✓ Python AI server started (PID: $PYTHON_PID)${NC}"

# Wait for Python to be ready
sleep 2

# Start Go core
echo ""
echo "Starting Go core (port 8080)..."
if [ "$GO_BUILD_OK" = true ]; then
    ./hermes-core &
else
    cd go-core && go run . &
fi
GO_PID=$!
cd ..
echo -e "${GREEN}✓ Go core started (PID: $GO_PID)${NC}"

# Health check
sleep 3
echo ""
echo "Running health checks..."
HEALTH_GO=$(curl -s http://localhost:8080/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unreachable")
HEALTH_PY=$(curl -s http://localhost:8081/health 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unreachable")

echo -e "  🐹 Go Core:   ${GREEN}$HEALTH_GO${NC}"
echo -e "  🐍 Python AI: ${GREEN}$HEALTH_PY${NC}"

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  🚀 System running!${NC}"
echo -e "${GREEN}  🐹 Go:   http://localhost:8080${NC}"
echo -e "${GREEN}  🐍 AI:   http://localhost:8081${NC}"
echo -e "${GREEN}  📱 Bot:  Telegram${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Press Ctrl+C to stop"

# Wait for either to exit
wait $PYTHON_PID $GO_PID 2>/dev/null
cleanup
