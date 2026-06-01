#!/bin/bash
# OpenClaw Dubbing Studio — Daemon Runner
# Keeps bot running 24/7 with auto-restart

BOT_SCRIPT="dubbing_bot.py"
PID_FILE="dubbing_bot.pid"
LOG_FILE="dubbing_bot.log"
MAX_RETRIES=10
RETRY_DELAY=5

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() {
    echo -e "[$(date '+%H:%M:%S')] $1"
}

check_env() {
    if [ -z "$BOT_TOKEN" ] || [ -z "$API_KEY" ]; then
        echo "❌ Set environment variables first:"
        echo ""
        echo "  export BOT_TOKEN=*** export API_KEY=*** export ALLOWED_CHATS=7563947218"
        echo ""
        echo "  Or create .env file:"
        echo "  BOT_TOKEN=*** export API_KEY=*** ALLOWED_CHATS=7563947218 > .env"
        echo "  source .env"
        exit 1
    fi
}

start_bot() {
    check_env
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log "${YELLOW}Bot already running (PID: $PID)${NC}"
            return 1
        fi
        rm -f "$PID_FILE"
    fi
    
    log "${GREEN}Starting OpenClaw Dubbing Studio...${NC}"
    
    # Start bot in background
    nohup python3 "$BOT_SCRIPT" >> "$LOG_FILE" 2>&1 &
    BOT_PID=$!
    echo "$BOT_PID" > "$PID_FILE"
    
    sleep 2
    
    if kill -0 "$BOT_PID" 2>/dev/null; then
        log "${GREEN}✅ Bot started (PID: $BOT_PID)${NC}"
        log "📄 Log: tail -f $LOG_FILE"
        return 0
    else
        log "${RED}❌ Bot failed to start${NC}"
        tail -20 "$LOG_FILE"
        return 1
    fi
}

stop_bot() {
    if [ ! -f "$PID_FILE" ]; then
        log "${YELLOW}No PID file found${NC}"
        return 1
    fi
    
    PID=$(cat "$PID_FILE")
    
    if kill -0 "$PID" 2>/dev/null; then
        log "${YELLOW}Stopping bot (PID: $PID)...${NC}"
        kill "$PID"
        sleep 2
        
        # Force kill if still running
        if kill -0 "$PID" 2>/dev/null; then
            log "${RED}Force killing...${NC}"
            kill -9 "$PID"
        fi
        
        rm -f "$PID_FILE"
        log "${GREEN}✅ Bot stopped${NC}"
    else
        log "${YELLOW}Bot not running${NC}"
        rm -f "$PID_FILE"
    fi
}

status_bot() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log "${GREEN}✅ Bot running (PID: $PID)${NC}"
            echo "📊 Stats:"
            echo "   Uptime: $(ps -o etime= -p $PID 2>/dev/null || echo 'unknown')"
            echo "   Memory: $(ps -o rss= -p $PID 2>/dev/null | awk '{printf "%.1f MB", $1/1024}' || echo 'unknown')"
            echo "   Log lines: $(wc -l < $LOG_FILE 2>/dev/null || echo 0)"
            return 0
        fi
    fi
    
    log "${RED}❌ Bot not running${NC}"
    return 1
}

run_daemon() {
    check_env
    
    log "${GREEN}🎬 OpenClaw Dubbing Studio — Daemon Mode${NC}"
    log "Press Ctrl+C to stop"
    log ""
    
    RETRIES=0
    
    while [ $RETRIES -lt $MAX_RETRIES ]; do
        log "${YELLOW}Starting bot (attempt $((RETRIES+1))/$MAX_RETRIES)...${NC}"
        
        # Start bot
        python3 "$BOT_SCRIPT" >> "$LOG_FILE" 2>&1 &
        BOT_PID=$!
        echo "$BOT_PID" > "$PID_FILE"
        
        log "${GREEN}Bot started (PID: $BOT_PID)${NC}"
        
        # Wait for bot to exit
        wait $BOT_PID
        EXIT_CODE=$?
        
        RETRIES=$((RETRIES + 1))
        
        if [ $EXIT_CODE -eq 0 ]; then
            log "${GREEN}Bot exited normally${NC}"
            break
        fi
        
        log "${YELLOW}Bot crashed (exit code: $EXIT_CODE). Restarting in ${RETRY_DELAY}s...${NC}"
        sleep $RETRY_DELAY
    done
    
    if [ $RETRIES -ge $MAX_RETRIES ]; then
        log "${RED}Max retries reached. Check logs: $LOG_FILE${NC}"
    fi
    
    rm -f "$PID_FILE"
}

tail_log() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "No log file found"
    fi
}

case "${1:-run}" in
    start)
        start_bot
        ;;
    stop)
        stop_bot
        ;;
    restart)
        stop_bot
        sleep 1
        start_bot
        ;;
    status)
        status_bot
        ;;
    run|daemon)
        run_daemon
        ;;
    log|logs)
        tail_log
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|run|log}"
        echo ""
        echo "  start    - Start bot (one-shot)"
        echo "  stop     - Stop bot"
        echo "  restart  - Restart bot"
        echo "  status   - Check bot status"
        echo "  run      - Run as daemon (auto-restart)"
        echo "  log      - Tail log file"
        exit 1
        ;;
esac
