# AI Influencer Video Generator — Claude Code Guide

## What This Project Does

Automated pipeline that takes any video, swaps the face/identity with a custom AI character, and outputs a clone video. Two-stage AI pipeline: **Higgsfield** (image generation) → **Wavespeed Kling** (video generation). Controlled via Telegram bot 24/7.

---

## For Claude: First-Time Setup Flow

When a user says "set up this project", "help me get started", or similar, guide them through these steps in order. **Always explain what you are doing and why at each step — new users do not know the system yet.**

---

### Step 1 — Run the setup script

Explain first: "This script creates all the folders the pipeline needs, installs Python packages, and creates your `config.py` from the template."

```bash
bash setup.sh
```

If the user gets a permission error, run `chmod +x setup.sh` first.

---

### Step 2 — Check for missing tools

Run these checks and explain each one:

- **Python 3.10+**: `python3 --version` — if missing, `brew install python@3.11`
- **ffmpeg**: `ffmpeg -version` — if missing, `brew install ffmpeg`
- **Higgsfield CLI**: `higgsfield --version` — if missing, `pip3 install higgsfield`

---

### Step 3 — Collect API keys

Explain: "The pipeline needs API keys to talk to Higgsfield (image generation) and Wavespeed (video generation). These go in your `config.py` — that file is git-ignored and never committed."

Ask the user for:
- **Higgsfield API key** — from higgsfield.ai → Settings → API
- **Wavespeed API key** — from wavespeed.ai → Dashboard → API Keys
- **Telegram Bot Token** (optional) — from @BotFather on Telegram → /newbot
- **Telegram Chat ID** (optional) — shown when they send /start to their bot

Then open `config.py` and fill in the values.

---

### Step 4 — Higgsfield CLI login

Explain: "The pipeline calls Higgsfield through its CLI. You need to log in once so the CLI is authenticated."

```bash
higgsfield auth login
```

A browser window will open. After logging in, come back to the terminal.

---

### Step 5 — Create your AI Character (IMPORTANT — ask the user this)

**This is the most important setup step. Ask the user directly:**

> "This pipeline uses Higgsfield Soul Character 2.0 to lock your AI character's face, skin, and identity into every generated image. Do you already have a trained Soul Character on Higgsfield, or do you need to create one?"

**If the user says they need to create one (or does not know what a Soul Character is):**

Tell them:

> "Great — head to this URL to create your Soul Character:
> **https://higgsfield.ai/character**
>
> Here's what to do there:
> 1. Click **Create New Character**
> 2. Upload 10–20 reference photos of your AI character (or your real face if you're the character) — variety of angles and lighting works best
> 3. Give the character a name
> 4. Click **Train** — training takes around 10 minutes
> 5. Once the status shows **Ready**, open the character and copy its **Soul ID** — it looks like a UUID, for example: `dc1b8265-abe1-41d4-9cf4-518c52bf2c82`
> 6. Come back here and give me that Soul ID"

Once the user gives you the Soul ID, open `config.py` and set:
```python
MIA_SOUL_ID = "paste-their-soul-id-here"
```

**If the user already has a Soul Character:**

Ask them to copy the Soul ID from higgsfield.ai → Soul Characters → open their character → copy the UUID. Then set it in `config.py` as above.

**Then ask the user about hair colour — show them the options and wait for their answer:**

> "What hair colour does your AI character have? Pick the closest match:
>
> 1. **jet_black** — Long jet-black hair, cool undertones, silky finish
> 2. **dark_espresso** — Dark warm brown/black, chestnut hints, sun-kissed ends
> 3. **red_head** — Copper red, ginger undertones, warm golden highlights"

Wait for the user to reply (1, 2, 3, or the key name), then write their choice to `config.py`:
```python
CHARACTER_HAIR = "jet_black"   # or "dark_espresso" or "red_head"
```

**Then ask about skin style — show the options and wait for their answer:**

> "How should the skin look in generated images? Pick one:
>
> 1. **soft** — Smooth, polished, even-toned (most AI-looking)
> 2. **realistic** — Natural pores and skin texture, candid feel (recommended)
> 3. **imperfect** — Visible pores, raw unretouched skin, most human-looking"

Wait for the user to reply, then write their choice to `config.py`:
```python
SKIN_STYLE = "realistic"   # or "soft" or "imperfect"
```

After both answers are set, confirm to the user: "Got it — I've updated `config.py` with your hair and skin choices. These are built into every image prompt automatically, so you never have to think about them again."

> **Note for Claude:** The old method of placing an image in `character sheet/` is no longer used. The pipeline now requires a Soul Character ID. Do NOT tell users to put an image in the character sheet folder as a substitute — it will not work.

---

### Step 6 — Test the pipeline

Explain: "Drop any `.mp4` file into the `raw material/` folder. The pipeline will extract the best frame, generate 4 images of your AI character in the same scene, and you'll pick one before the final video is made."

```bash
python3 run_pipeline.py
```

If `raw material/` is empty, ask the user to drop any `.mp4` file in there first.

---

### Step 7 — After a successful test: Tell the user about limitations and VPS

Once the pipeline runs successfully, **always tell the user this:**

> "Great — the pipeline is working! One important thing to know: right now this only runs while your computer is on and the terminal is open. The moment you close your laptop or shut down, the bot stops.
>
> If you want this running 24/7 without your computer — so you can send Telegram links from anywhere and get videos back — you need to deploy it to a cloud server (VPS).
>
> The service we use for this is **Vultr**: https://www.vultr.com/
>
> It costs as little as $6/month and keeps your bot alive around the clock. Want me to walk you through deploying to Vultr?"

If the user says yes, follow the **VPS Deployment Guide** section below.

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

---

## VPS Deployment Guide (24/7 on Vultr)

When the user asks about running the bot 24/7 on a server, guide them through this. Reference: **https://www.vultr.com/**

> Tell the user: "We're going to rent a small cloud server that stays on all the time. You'll pay around $6/month, and your bot will run 24/7 even when your laptop is off."

### Step 1 — Create a Vultr account

1. Go to **https://www.vultr.com/** and sign up
2. Add a payment method

### Step 2 — Deploy a server

1. Click **Deploy** → **Cloud Compute — Shared CPU**
2. Choose a location closest to you (or closest to your audience)
3. Select **Ubuntu 22.04 LTS** as the operating system
4. Choose the **$6/month plan** (1 CPU, 1GB RAM, 25GB SSD) — enough for this pipeline
5. Under **Server Hostname**, give it a name like `ai-influencer-bot`
6. Click **Deploy Now** — wait ~2 minutes for it to boot

### Step 3 — Connect via SSH

In your terminal (on your Mac):
```bash
ssh root@YOUR_SERVER_IP
```
The IP address is shown on your Vultr dashboard. Accept the fingerprint prompt. The initial password is shown in the Vultr dashboard under **Server Details → Password**.

### Step 4 — Install dependencies on the server

Run these commands on the server:
```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip ffmpeg git curl libgl1
pip3 install higgsfield
```

### Step 5 — Clone the repo and set up config

```bash
git clone https://github.com/YOUR_USERNAME/ai-influencer-automation.git
cd ai-influencer-automation
bash setup.sh
```

Then open `config.py` and fill in your API keys:
```bash
nano config.py
```

Fill in:
- `HIGGSFIELD_API_KEY`
- `MIA_SOUL_ID`
- `WAVESPEED_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Save with `Ctrl+O`, then `Ctrl+X`.

### Step 6 — Log in to Higgsfield CLI

```bash
higgsfield auth login
```

This opens a URL — copy it, open it in your local browser, authenticate, and the CLI on the server will be logged in.

### Step 7 — Start the bot

```bash
bash start_bot.sh
```

Check it's running:
```bash
tail -f watcher.log
```

You should see the bot starting up. Send a Telegram message to your bot to confirm it responds.

### Step 8 — Keep the bot running after SSH disconnect

The `start_bot.sh` script already uses `nohup` to keep the process alive after you close the SSH session. You can safely disconnect:
```bash
exit
```

The bot keeps running. To stop it later, SSH back in and run:
```bash
bash stop_bot.sh
```

### Useful server commands

```bash
# Check if bot process is running
ps aux | grep watcher.py

# View live logs
tail -f watcher.log

# Restart the bot
bash stop_bot.sh && bash start_bot.sh

# Check disk usage
df -h

# Check memory
free -h
```

### Notes for Claude on VPS setup

- If the user is on Windows and hasn't used SSH before, tell them to use **PowerShell** or install **PuTTY** — `ssh root@IP` works in both
- The `$6/month` Vultr plan has enough memory for this pipeline since Higgsfield and Wavespeed do the heavy lifting on their own servers — this server is just running the orchestration scripts
- If the user wants the bot to auto-start on server reboot, tell them they can set up a systemd service — but `start_bot.sh` + `nohup` is sufficient for most users
- Remind the user their `config.py` contains secret keys — never commit it or paste it publicly
