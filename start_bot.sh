#!/bin/bash
# Start/restart the AI Influencer bot.
# Uses launchctl when a plist is registered (prevents dual-instance Conflict).
cd "$(dirname "$0")"

SERVICE="com.aiinfluencer.watcher"
PLIST="$HOME/Library/LaunchAgents/${SERVICE}.plist"

if [ -f "$PLIST" ]; then
    echo "Restarting via launchctl (clean single-instance restart)..."
    # Unload completely — stops the process AND prevents launchd from restarting it
    launchctl unload "$PLIST" 2>/dev/null || true
    # Kill any stray watcher.py that escaped launchd's control
    pkill -9 -f "python3.*watcher\.py" 2>/dev/null || true
    rm -f .watcher.pid
    # Wait for Telegram to release the old long-poll connection
    echo "Waiting for Telegram to release old connection..."
    sleep 5
    # Load the service — launchd starts a single fresh instance
    launchctl load "$PLIST"
    echo "Bot started via launchctl."
    exit 0
fi

# ── Fallback: no launchd service — start directly ────────────────────────────

PID_FILE=".watcher.pid"

if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping existing bot (PID $OLD_PID)..."
        kill "$OLD_PID"
        for i in $(seq 1 10); do
            kill -0 "$OLD_PID" 2>/dev/null || break
            sleep 0.5
        done
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

pkill -9 -f "python3.*watcher\.py" 2>/dev/null || true
sleep 4

nohup python3 watcher.py > /dev/null 2>&1 &
echo "Bot started (PID $!)"
