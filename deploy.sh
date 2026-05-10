#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# deploy.sh  —  One-shot setup + deploy of the AI Influencer bot to a VPS
#
# Usage:
#   bash deploy.sh <server-ip>
#
# What it does:
#   1. Installs system packages (ffmpeg, Python, libGL for OpenCV, etc.)
#   2. Syncs all project files to the server via rsync
#   3. Creates a Python venv + installs all pip packages
#   4. Transfers Higgsfield CLI credentials
#   5. Creates a systemd service so the bot runs 24/7 and auto-restarts
#
# Re-run any time you change code — rsync only pushes diffs, service restarts.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SERVER_IP="${1:-}"
if [[ -z "$SERVER_IP" ]]; then
  echo "Usage: bash deploy.sh <server-ip>"
  echo "Example: bash deploy.sh 65.21.100.42"
  exit 1
fi

SSH="ssh -o StrictHostKeyChecking=accept-new root@$SERVER_IP"
REMOTE_DIR="/opt/ai_influencer"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

step() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  $*"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── 1. System packages ────────────────────────────────────────────────────────

step "1/6  Installing system packages on server..."
$SSH bash << 'ENDSSH'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y \
  python3 python3-pip python3-venv \
  ffmpeg \
  libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
  rsync curl wget 2>/dev/null
echo "  System packages OK"
ENDSSH

# ── 2. Create remote directory structure ──────────────────────────────────────

step "2/6  Creating remote directory structure..."
$SSH bash << ENDSSH
mkdir -p "$REMOTE_DIR"
mkdir -p "$REMOTE_DIR/outputs/higgsfield"
mkdir -p "$REMOTE_DIR/outputs/wavespeed"
mkdir -p "$REMOTE_DIR/raw material"
mkdir -p "$REMOTE_DIR/extracted frames"
echo "  Directories OK"
ENDSSH

# ── 3. Sync project files ─────────────────────────────────────────────────────

step "3/6  Syncing project files to server..."
rsync -avz --progress \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.git' \
  --exclude 'outputs/' \
  --exclude 'watcher.log' \
  --exclude 'extracted frames/' \
  --exclude 'raw material/' \
  --exclude '.DS_Store' \
  "$PROJECT_DIR/" "root@$SERVER_IP:$REMOTE_DIR/"
echo "  Files synced"

# ── 4. Python venv + packages ─────────────────────────────────────────────────

step "4/6  Setting up Python virtual environment..."
$SSH bash << ENDSSH
cd "$REMOTE_DIR"
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt
echo "  Python packages OK"
ENDSSH

# ── 4b. Node.js + real Higgsfield CLI ────────────────────────────────────────

step "4b/6  Installing Node.js + Higgsfield CLI..."
$SSH bash << 'ENDSSH'
if ! command -v node &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null 2>&1
  apt-get install -y nodejs >/dev/null 2>&1
fi
npm install -g @higgsfield/cli >/dev/null 2>&1
echo "  Higgsfield $(higgsfield --version 2>&1 | head -1)"
ENDSSH

# ── 5. Transfer Higgsfield credentials ───────────────────────────────────────

step "5/6  Transferring Higgsfield credentials..."
TRANSFERRED=false
for HF_DIR in "$HOME/.config/higgsfield" "$HOME/.higgsfield"; do
  if [[ -d "$HF_DIR" ]]; then
    REMOTE_HF="$(basename "$HF_DIR")"
    $SSH "mkdir -p ~/.config/$REMOTE_HF"
    rsync -avz "$HF_DIR/" "root@$SERVER_IP:~/.config/$REMOTE_HF/" 2>/dev/null || true
    echo "  Transferred: $HF_DIR → ~/.config/$REMOTE_HF/"
    TRANSFERRED=true
    break
  fi
done

if [[ "$TRANSFERRED" == "false" ]]; then
  echo ""
  echo "  ⚠️  No Higgsfield config found at ~/.config/higgsfield or ~/.higgsfield"
  echo "  You may need to run on the server:"
  echo "    ssh root@$SERVER_IP"
  echo "    /opt/ai_influencer/venv/bin/higgsfield auth"
  echo ""
fi

# ── 6. systemd service ────────────────────────────────────────────────────────

step "6/6  Creating systemd service..."
$SSH bash << ENDSSH
cat > /etc/systemd/system/ai-influencer.service << 'SERVICE'
[Unit]
Description=AI Influencer Pipeline Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai_influencer
ExecStart=/opt/ai_influencer/venv/bin/python3 watcher.py
Restart=always
RestartSec=15
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1
Environment=PATH=/opt/ai_influencer/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable ai-influencer
systemctl restart ai-influencer
sleep 3
echo ""
systemctl status ai-influencer --no-pager || true
ENDSSH

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅  Bot deployed and running on $SERVER_IP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Useful commands:"
echo ""
echo "  Live logs:"
echo "    ssh root@$SERVER_IP 'journalctl -u ai-influencer -f'"
echo ""
echo "  Check status:"
echo "    ssh root@$SERVER_IP 'systemctl status ai-influencer'"
echo ""
echo "  Restart bot:"
echo "    ssh root@$SERVER_IP 'systemctl restart ai-influencer'"
echo ""
echo "  Push code changes later:"
echo "    bash deploy.sh $SERVER_IP"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Next: Stop the Mac daemon if still running:"
echo "    launchctl unload ~/Library/LaunchAgents/com.aiinfluencer.watcher.plist"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
