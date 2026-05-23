#!/bin/bash
# Start/restart the Mia AI Influencer bot.
cd "$(dirname "$0")"

SCRIPT_DIR="$(pwd)"
PID_FILE=".watcher.pid"

# Kill any existing instance of THIS bot (by exact path, so Scar is untouched)
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

# Also catch any stray instance not tracked by the pid file
pkill -f "$SCRIPT_DIR/watcher.py" 2>/dev/null || true

echo "Waiting for Telegram to release old connection..."
sleep 8

# Add venv binaries (including yt-dlp) to PATH so subprocess calls find them
export PATH="$SCRIPT_DIR/venv/bin:$PATH"

# Use venv Python if available, otherwise fall back to system python3
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python"
else
    PYTHON="python3"
fi

nohup "$PYTHON" "$SCRIPT_DIR/watcher.py" >> "$SCRIPT_DIR/watcher.log" 2>&1 &
echo $! > "$PID_FILE"
echo "Bot started (PID $(cat $PID_FILE))"
