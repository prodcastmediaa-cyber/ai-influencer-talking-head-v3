import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── Google Sheet ──────────────────────────────────────────────────────────────
# The ID is the long string in your Google Sheet URL:
# https://docs.google.com/spreadsheets/d/<THIS_PART>/edit
SHEET_ID   = "YOUR_GOOGLE_SHEET_ID_HERE"
SHEET_NAME = "May 2026"   # Change to your tab name

# Column positions (1-indexed, do not change unless you reorder columns)
COL_SR_NO           = 1
COL_INFLUENCER_NAME = 2
COL_DRIVE_LINK      = 3
COL_FRAME_IMAGE     = 4
COL_STATUS          = 5

# ─── Local folders ────────────────────────────────────────────────────────────
RAW_MATERIAL_DIR    = os.path.join(BASE_DIR, "raw material")
CHARACTER_REF_DIR   = os.path.join(BASE_DIR, "character sheet mia")
MIA_REFERENCE_IMAGE = os.path.join(CHARACTER_REF_DIR, "mia-main.png")
EXTRACTED_FRAMES_DIR = os.path.join(BASE_DIR, "extracted frames")
OUTPUTS_DIR         = os.path.join(BASE_DIR, "outputs")

# ─── Higgsfield ───────────────────────────────────────────────────────────────
# Get your key from: https://higgsfield.ai → Settings → API
HIGGSFIELD_API_KEY = "YOUR_HIGGSFIELD_API_KEY_HERE"

# ─── Wavespeed (Kling Motion Control) ─────────────────────────────────────────
# Get your key from: https://wavespeed.ai → Dashboard → API Keys
WAVESPEED_API_KEY = "YOUR_WAVESPEED_API_KEY_HERE"
