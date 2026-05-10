#!/bin/bash
# Stop the AI Influencer bot cleanly.
cd "$(dirname "$0")"

SERVICE="com.aiinfluencer.watcher"
PLIST="$HOME/Library/LaunchAgents/${SERVICE}.plist"

if [ -f "$PLIST" ]; then
    echo "Unloading launchctl service..."
    launchctl unload "$PLIST" 2>/dev/null || true
    pkill -f "python3.*watcher\.py" 2>/dev/null || true
    rm -f .watcher.pid
    echo "Bot stopped."
    exit 0
fi

# ── Fallback: direct kill ────────────────────────────────────────────────────

PID_FILE=".watcher.pid"

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping bot (PID $PID)..."
        kill "$PID"
        sleep 2
        kill -9 "$PID" 2>/dev/null || true
        echo "Bot stopped."
    else
        echo "Bot is not running (stale PID file)."
    fi
    rm -f "$PID_FILE"
else
    if pkill -f "python3.*watcher\.py" 2>/dev/null; then
        echo "Bot stopped."
    else
        echo "Bot is not running."
    fi
fi
