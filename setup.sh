#!/bin/bash
# First-time setup for AI Influencer Video Generator
# Run this once after cloning the repo: bash setup.sh

set -e
cd "$(dirname "$0")"

echo ""
echo "======================================"
echo "  AI Influencer Video Generator Setup"
echo "======================================"
echo ""

# ── Step 1: Create required folders ─────────────────────────────────────────

echo "Creating folders..."
mkdir -p "raw material"
mkdir -p "extracted frames"
mkdir -p "outputs/higgsfield"
mkdir -p "outputs/wavespeed"
mkdir -p "character sheet"

# Keep folders in git with a .gitkeep
touch "raw material/.gitkeep"
touch "extracted frames/.gitkeep"
touch "outputs/higgsfield/.gitkeep"
touch "outputs/wavespeed/.gitkeep"
touch "character sheet/.gitkeep"

echo "  ✓ Folders created"

# ── Step 2: Check Python ─────────────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
    echo ""
    echo "  ✗ python3 not found."
    echo "    Mac:     brew install python@3.11"
    echo "    Ubuntu:  sudo apt install python3 python3-pip"
    echo "    Windows: https://python.org/downloads"
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  ✓ Python $PY_VERSION found"

# ── Step 3: Check ffmpeg ─────────────────────────────────────────────────────

if ! command -v ffmpeg &>/dev/null; then
    echo ""
    echo "  ✗ ffmpeg not found."
    echo "    Mac:     brew install ffmpeg"
    echo "    Ubuntu:  sudo apt install ffmpeg"
    echo "    Windows: https://ffmpeg.org/download.html"
    echo ""
    echo "  Install ffmpeg and run setup.sh again."
    exit 1
fi

echo "  ✓ ffmpeg found"

# ── Step 4: Install Python dependencies ──────────────────────────────────────

echo ""
echo "Installing Python dependencies..."
pip3 install -r requirements.txt --quiet

echo "  ✓ Python dependencies installed"

# ── Step 5: Check / install Higgsfield CLI ───────────────────────────────────

echo ""
if command -v higgsfield &>/dev/null; then
    echo "  ✓ Higgsfield CLI found"
else
    echo "  Installing Higgsfield CLI..."
    pip3 install higgsfield --quiet
    echo "  ✓ Higgsfield CLI installed"
    echo ""
    echo "  ⚠  You still need to log in:"
    echo "     higgsfield auth login"
fi

# ── Step 6: Create config.py from example ───────────────────────────────────

echo ""
if [ -f "config.py" ]; then
    echo "  ✓ config.py already exists — skipping (not overwriting your keys)"
else
    cp config.example.py config.py
    echo "  ✓ config.py created from template"
    echo "  ⚠  Open config.py and fill in your API keys before running the pipeline"
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo "======================================"
echo "  Setup complete!"
echo "======================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Open config.py and fill in:"
echo "       HIGGSFIELD_API_KEY        — from higgsfield.ai → Settings → API"
echo "       MIA_SOUL_ID               — from higgsfield.ai → Soul Characters → your character → Soul ID"
echo "       CHARACTER_HAIR             — pick hair colour: jet_black | dark_espresso | red_head"
echo "       WAVESPEED_API_KEY         — from wavespeed.ai → Dashboard → API Keys"
echo "       TELEGRAM_BOT_TOKEN        — from @BotFather on Telegram (optional)"
echo "       TELEGRAM_CHAT_ID          — your Telegram chat ID (optional)"
echo ""
echo "  2. Log in to Higgsfield CLI:"
echo "       higgsfield auth login"
echo ""
echo "  3. Train your Soul Character (if you haven't yet):"
echo "       higgsfield.ai → Soul Characters → New Character → upload 5–20 photos → Train"
echo "       Once 'Ready', copy the Soul ID into config.py as MIA_SOUL_ID"
echo ""
echo "  4. Run the pipeline:"
echo "       python3 run_pipeline.py"
echo ""
echo "  5. (Optional) Start the 24/7 Telegram bot:"
echo "       bash start_bot.sh"
echo ""
echo "  See INSTALLATION.md for the full step-by-step guide."
echo ""
