#!/bin/bash
# Stop the Mia AI Influencer bot cleanly.
cd "$(dirname "$0")"

SCRIPT_DIR="$(pwd)"
PID_FILE=".watcher.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping Mia bot (PID $PID)..."
        kill "$PID"
        sleep 2
        kill -9 "$PID" 2>/dev/null || true
        echo "Bot stopped."
    else
        echo "Bot is not running (stale PID file)."
    fi
    rm -f "$PID_FILE"
else
    if pkill -f "$SCRIPT_DIR/watcher.py" 2>/dev/null; then
        echo "Bot stopped."
    else
        echo "Bot is not running."
    fi
fi
