import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Google Sheet ──────────────────────────────────────────────────────────────
# The ID is the long string in your Google Sheet URL:
# https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
SHEET_ID   = "YOUR_GOOGLE_SHEET_ID_HERE"
SHEET_NAME = "May 2026"   # Change to match your tab name

# Column positions (1-indexed — do not change unless you reorder the sheet columns)
COL_SR_NO           = 1
COL_INFLUENCER_NAME = 2
COL_DRIVE_LINK      = 3
COL_FRAME_IMAGE     = 4
COL_STATUS          = 5

# ─── Local folders ────────────────────────────────────────────────────────────
RAW_MATERIAL_DIR     = os.path.join(BASE_DIR, "raw material")
CHARACTER_REF_DIR    = os.path.join(BASE_DIR, "character sheet")
EXTRACTED_FRAMES_DIR = os.path.join(BASE_DIR, "extracted frames")
OUTPUTS_DIR          = os.path.join(BASE_DIR, "outputs")

# ─── Your AI Character reference image ────────────────────────────────────────
# Place your character's reference photo here.
# This is the identity source: face, skin tone, hair, and overall look.
MIA_REFERENCE_IMAGE = os.path.join(CHARACTER_REF_DIR, "character-main.png")

# ─── Higgsfield ───────────────────────────────────────────────────────────────
# Get your key from: https://higgsfield.ai → Settings → API
# Also install the CLI: pip install higgsfield
# And log in:          higgsfield auth login
HIGGSFIELD_API_KEY = "YOUR_HIGGSFIELD_API_KEY_HERE"

# ─── Wavespeed (Kling Motion Control) ─────────────────────────────────────────
# Get your key from: https://wavespeed.ai → Dashboard → API Keys
WAVESPEED_API_KEY = "YOUR_WAVESPEED_API_KEY_HERE"

# ─── Telegram Bot (optional — for 24/7 bot mode) ──────────────────────────────
# Step 1: Message @BotFather on Telegram → /newbot → copy the token below
# Step 2: Start your bot in Telegram, send /start → copy the chat ID shown
TELEGRAM_BOT_TOKEN = ""   # e.g. "7123456789:AAFxxx..."
TELEGRAM_CHAT_ID   = ""   # e.g. "123456789"
