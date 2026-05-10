# AI Influencer Video Generator — Claude Code Guide

## What This Project Does

Automated pipeline that takes any video, swaps the face/identity with a custom AI character, and outputs a clone video. Two-stage AI pipeline: **Higgsfield** (image generation) → **Wavespeed Kling** (video generation). Controlled via Telegram bot 24/7.

---

## For Claude: First-Time Setup Flow

When a user says "set up this project", "help me get started", or similar, guide them through these steps in order:

### 1. Run the setup script
```bash
bash setup.sh
```
This creates all required folders, installs Python dependencies, and copies `config.example.py → config.py`. If the user gets a permission error, run `chmod +x setup.sh` first.

### 2. Check for missing tools
- **Python 3.10+**: `python3 --version` — if missing, `brew install python@3.11`
- **ffmpeg**: `ffmpeg -version` — if missing, `brew install ffmpeg`
- **Higgsfield CLI**: `higgsfield --version` — if missing, `pip3 install higgsfield`

### 3. Collect API keys from the user
Ask the user for:
- **Higgsfield API key** — from higgsfield.ai → Settings → API
- **Wavespeed API key** — from wavespeed.ai → Dashboard → API Keys
- **Telegram Bot Token** (optional) — from @BotFather on Telegram → /newbot
- **Telegram Chat ID** (optional) — shown when they send /start to their bot

Then open `config.py` and fill in the values. Never commit this file.

### 4. Higgsfield CLI login
Ask the user to run:
```bash
higgsfield auth login
```
A browser window will open for authentication.

### 5. Character reference image
Tell the user to:
1. Choose a high-quality photo of their AI character (or create one in Higgsfield)
2. Save it as: `character sheet/character-main.png`

This is the identity source for all generated images — face, skin tone, hair, overall look.

### 6. Test the pipeline
```bash
python3 run_pipeline.py
```
If `raw material/` is empty, ask the user to drop any `.mp4` file in there first.

---

## Folder Structure

```
ai-influencer-automation/
├── character sheet/           ← AI character reference images
│   └── character-main.png    ← Primary reference (face identity)
├── raw material/              ← Input .mp4 videos
├── extracted frames/          ← Auto-generated best frames
├── outputs/
│   ├── higgsfield/            ← 4 generated images per video
│   └── wavespeed/             ← Final output videos
├── config.py                  ← API keys (git-ignored)
├── config.example.py          ← Template
├── extract_frame.py           ← Step 1: Smart frame extraction
├── higgsfield_generate.py     ← Step 2: AI character image generation
├── wavespeed_generate.py      ← Step 4: Final video generation
├── run_pipeline.py            ← One-command pipeline runner
├── watcher.py                 ← 24/7 Telegram bot + daemon
├── setup.sh                   ← First-time setup
├── start_bot.sh               ← Start daemon in background
└── stop_bot.sh                ← Stop daemon
```

---

## Full Pipeline (Step by Step)

### Step 1 — Extract best frame
```bash
python3 extract_frame.py
```
Output: `extracted frames/{video_name}_frame.png`

### Step 2 — Generate AI character images (Higgsfield)
```bash
python3 higgsfield_generate.py
```
Output: `outputs/higgsfield/{video_name}/output_1.png` through `output_4.png`

### Step 3 — Pick best image (MANUAL)
Open `outputs/higgsfield/{video_name}/` in Finder.
Pick the best image → copy it → rename the copy to `selected.png` in the same folder.

### Step 4 — Generate final video (Wavespeed)
```bash
python3 wavespeed_generate.py
```
Output: `outputs/wavespeed/{video_name}/output.mp4`

### Run everything at once
```bash
python3 run_pipeline.py
```
Skips already-completed steps automatically. Pauses at Step 3 for manual image selection, then resumes on next run.

---

## 24/7 Telegram Bot

```bash
bash start_bot.sh   # start in background
bash stop_bot.sh    # stop
tail -f watcher.log # view logs
```

In Telegram: paste a TikTok / Instagram / YouTube link, or send a video file. The bot handles everything else with interactive buttons.

---

## API Keys (in config.py)

| Variable | Service | Where to get |
|----------|---------|-------------|
| `HIGGSFIELD_API_KEY` | Higgsfield | higgsfield.ai → Settings → API |
| `WAVESPEED_API_KEY` | Wavespeed | wavespeed.ai → Dashboard → API Keys |
| `TELEGRAM_BOT_TOKEN` | Telegram | @BotFather → /newbot |
| `TELEGRAM_CHAT_ID` | Telegram | Send /start to your bot |
| `SHEET_ID` | Google Sheets | From sheet URL |

---

## Notes

- **Model files auto-download** on first run (`face_landmarker.task`, `hand_landmarker.task`, `EDSR_x2.pb`)
- **Videos over 10s** are auto-trimmed before Wavespeed (Kling's limit)
- **4 images run in parallel** — 4x faster but uses 4 Higgsfield credits per video
- **The pipeline is idempotent** — safe to run `run_pipeline.py` repeatedly
- **Never commit** `config.py`, `credentials.json`, `token.pickle`, or anything in `character sheet/`
- **Google Sheets/Drive** are optional — the pipeline works without them; just skip those config keys

---

## Common Commands

```bash
# First-time setup
bash setup.sh

# Run full pipeline (CLI mode)
python3 run_pipeline.py

# Run individual steps
python3 extract_frame.py
python3 higgsfield_generate.py
python3 wavespeed_generate.py

# Start/stop 24/7 bot
bash start_bot.sh
bash stop_bot.sh

# View bot logs
tail -f watcher.log

# Set up Google Sheets headers (one-time)
python3 setup_sheet.py

# Higgsfield CLI login
higgsfield auth login
```
