import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Google Sheet (optional) ──────────────────────────────────────────────────
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

# ─── Higgsfield ───────────────────────────────────────────────────────────────
# Get your key from: https://higgsfield.ai → Settings → API
# Also install the CLI:  pip install higgsfield
# And log in:            higgsfield auth login
HIGGSFIELD_API_KEY = "YOUR_HIGGSFIELD_API_KEY_HERE"

# ─── Your AI Character — Hair Description ─────────────────────────────────────
# Describe your character's hair in as much detail as possible.
# This is injected into every generated image prompt under "Clothing".
# Be specific: length, color, texture, shine, undertones, finish.
#
# Example (straight black hair):
#   "long natural jet-black hair with soft cool undertones, rich deep black tone,
#    subtle espresso sheen under light, smooth realistic texture, healthy silky finish"
#
# Example (curly auburn hair):
#   "shoulder-length curly auburn hair, warm copper highlights, defined ringlets,
#    natural volume, soft frizz-free texture, rich chestnut undertone"
CHARACTER_HAIR_DESCRIPTION = "YOUR HAIR DESCRIPTION HERE"

# ─── Your AI Character — Soul ID ──────────────────────────────────────────────
# This is the ID of the Soul Character you trained in Higgsfield.
# How to get it:
#   1. Go to higgsfield.ai → Soul Characters
#   2. Train a new character with 5–20 reference photos (takes ~10 min)
#   3. Once status shows "Ready", open the character → copy its Soul ID (a UUID)
#   4. Paste it below
#
# Example: "dc1b8265-abe1-41d4-9cf4-518c52bf2c82"
MIA_SOUL_ID = "YOUR_SOUL_ID_HERE"

# If you have multiple characters, add them here and swap MIA_SOUL_ID as needed:
# SCAR_SOUL_ID          = "YOUR_SECOND_SOUL_ID_HERE"
# SUNLIT_EMBRACE_SOUL_ID = "YOUR_THIRD_SOUL_ID_HERE"

# ─── Wavespeed (Kling Motion Control) ─────────────────────────────────────────
# Get your key from: https://wavespeed.ai → Dashboard → API Keys
WAVESPEED_API_KEY = "YOUR_WAVESPEED_API_KEY_HERE"

# ─── Telegram Bot (optional — for 24/7 bot mode) ──────────────────────────────
# Step 1: Message @BotFather on Telegram → /newbot → copy the token below
# Step 2: Start your bot in Telegram, send /start → copy the chat ID shown
TELEGRAM_BOT_TOKEN = ""   # e.g. "7123456789:AAFxxx..."
TELEGRAM_CHAT_ID   = ""   # e.g. "123456789"
