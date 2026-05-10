# Installation Guide

> Complete setup from scratch. Follow every step in order — nothing is skipped. This works even if you have never run a Python project before.

---

## What You Will Need

Before starting, make sure you have accounts at:
- [Higgsfield](https://higgsfield.ai) — for AI character image generation
- [Wavespeed](https://wavespeed.ai) — for video generation
- [Telegram](https://telegram.org) — for the bot (optional but recommended)
- [Google Cloud](https://console.cloud.google.com) — for Sheets + Drive tracking (optional)

---

## Mac Setup (Recommended)

### Step 1 — Install Homebrew

Homebrew is the package manager for Mac. If you already have it, skip this.

Open **Terminal** (press `Cmd + Space`, type `Terminal`, press Enter) and run:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the prompts. When it asks for your password, type it (you won't see it — that's normal).

After it finishes, run this to check it works:
```bash
brew --version
```

You should see something like `Homebrew 4.x.x`.

---

### Step 2 — Install Python

```bash
brew install python@3.11
```

Verify it installed:
```bash
python3 --version
```

Should say `Python 3.11.x` (or higher).

---

### Step 3 — Install ffmpeg

ffmpeg handles video frame extraction and trimming. Required.

```bash
brew install ffmpeg
```

Verify:
```bash
ffmpeg -version
```

---

### Step 4 — Install Git

Git is usually already on Mac. Check first:
```bash
git --version
```

If not found:
```bash
brew install git
```

---

### Step 5 — Install VS Code (Recommended)

VS Code with the Claude Code extension lets Claude guide you through the entire setup automatically.

1. Go to [https://code.visualstudio.com](https://code.visualstudio.com) and download VS Code for Mac
2. Open the downloaded `.dmg` file and drag VS Code to your Applications folder
3. Open VS Code

**Install the Claude Code extension:**
1. In VS Code, press `Cmd + Shift + X` to open Extensions
2. Search for **Claude Code**
3. Click Install
4. Sign in to your Anthropic / Claude account when prompted

---

### Step 6 — Clone the Repository

In Terminal:

```bash
# Go to your preferred folder (Downloads is fine)
cd ~/Downloads

# Clone the repo
git clone https://github.com/YOUR_USERNAME/ai-influencer-automation.git

# Enter the folder
cd ai-influencer-automation
```

Replace `YOUR_USERNAME` with the actual GitHub username.

**Open in VS Code:**
```bash
code .
```

This opens the entire project in VS Code. Claude Code (in the sidebar) can now read all the files and help you.

---

### Step 7 — Run the Setup Script

This creates all required folders, installs Python dependencies, and copies the config template.

```bash
bash setup.sh
```

You should see:
```
✓ Folders created
✓ Python dependencies installed
✓ config.py created from template
Next: open config.py and fill in your API keys
```

If you see a permission error on `setup.sh`:
```bash
chmod +x setup.sh
bash setup.sh
```

---

### Step 8 — Get Your API Keys

#### Higgsfield API Key + CLI

1. Create an account at [higgsfield.ai](https://higgsfield.ai)
2. Go to **Settings → API** → copy your API key
3. Install the Higgsfield CLI:
   ```bash
   pip3 install higgsfield
   ```
4. Log in:
   ```bash
   higgsfield auth login
   ```
   Follow the browser prompt to authenticate.

#### Wavespeed API Key

1. Create an account at [wavespeed.ai](https://wavespeed.ai)
2. Go to **Dashboard → API Keys** → create a new key → copy it

---

### Step 9 — Configure Your Keys

Open `config.py` (created by setup.sh) and fill in the values:

```bash
# Open in VS Code:
code config.py

# Or open in any text editor:
open -e config.py
```

Fill in:
```python
HIGGSFIELD_API_KEY = "paste-your-higgsfield-key-here"
WAVESPEED_API_KEY  = "paste-your-wavespeed-key-here"
```

Save the file.

---

### Step 10 — Add Your AI Character Reference Image

1. Create your AI character in Higgsfield (follow their guide for training a Soul ID or use a reference photo)
2. Export or save the best reference image of your character (good face visibility, clean background preferred)
3. Place it at:
   ```
   character sheet/character-main.png
   ```
   The `character sheet/` folder was created by `setup.sh`.

This is the identity source — every generated image will use this face, skin tone, and hair.

---

### Step 11 — Test the Pipeline

Drop any `.mp4` video into `raw material/` and run:

```bash
python3 run_pipeline.py
```

It will:
1. Extract the best frame (takes ~30 seconds)
2. Generate 4 images via Higgsfield (takes 2–4 minutes)
3. Pause and ask you to pick the best image

Open `outputs/higgsfield/{video_name}/` in Finder, pick the best one, copy it and name it `selected.png` in the same folder.

Then run again:
```bash
python3 run_pipeline.py
```

Your final video will be at `outputs/wavespeed/{video_name}/output.mp4`.

---

## Optional — Telegram Bot Setup

The Telegram bot lets you control everything from your phone and run 24/7.

### Step 1 — Create a Telegram Bot

1. Open Telegram → search for **@BotFather**
2. Send `/newbot`
3. Follow the prompts to name your bot
4. BotFather will give you a **token** that looks like: `1234567890:AAFxxx...`
5. Copy it

### Step 2 — Get Your Chat ID

1. Start your new bot (tap **Start** or send `/start` in the chat)
2. The bot will print your chat ID — copy it
   - If it doesn't, send `/start` — the terminal running the bot will print the chat ID in the logs

### Step 3 — Add to config.py

```python
TELEGRAM_BOT_TOKEN = "1234567890:AAFxxx..."
TELEGRAM_CHAT_ID   = "123456789"
```

### Step 4 — Start the Bot

```bash
bash start_bot.sh
```

Check it's running:
```bash
tail -f watcher.log
```

You should see `[bot] Telegram polling started`. Send a message to your bot in Telegram — it should reply.

To stop:
```bash
bash stop_bot.sh
```

---

## Optional — Google Sheets + Drive Setup

Tracks pipeline status in a spreadsheet and auto-uploads finished videos to Drive.

### Step 1 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (any name)
3. Enable these two APIs:
   - **Google Sheets API**
   - **Google Drive API**

### Step 2 — Create OAuth Credentials

1. In Google Cloud Console → **APIs & Services → Credentials**
2. Click **Create Credentials → OAuth client ID**
3. Application type: **Desktop app**
4. Name it anything → click Create
5. Click **Download JSON** → save as `credentials.json` in the project folder

### Step 3 — Create Your Tracking Sheet

1. Create a new Google Sheet at [sheets.google.com](https://sheets.google.com)
2. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_PART_HERE/edit
   ```
3. Add to `config.py`:
   ```python
   SHEET_ID   = "your-sheet-id-here"
   SHEET_NAME = "May 2026"   # name of your tab
   ```

### Step 4 — Authenticate

```bash
python3 setup_sheet.py
```

A browser window opens → log in with your Google account → grant access. A `token.pickle` file is saved — this auto-refreshes and you won't need to do this again.

---

## Windows Setup

> Windows works but requires a few extra steps. If possible, use Mac or Linux for the smoothest experience.

### Option A — Use WSL (Windows Subsystem for Linux) — Recommended

WSL lets you run Linux inside Windows. Once set up, follow the Mac/Linux steps above.

1. Open PowerShell as Administrator
2. Run: `wsl --install`
3. Restart your computer
4. Open **Ubuntu** from the Start menu
5. Follow the **Mac Setup** steps above (use `apt` instead of `brew` for system packages)

### Option B — Native Windows

1. **Python**: Download from [python.org](https://python.org/downloads) — check "Add Python to PATH" during install
2. **ffmpeg**: Download from [ffmpeg.org/download.html](https://ffmpeg.org/download.html) → add to PATH
3. **Git**: Download from [git-scm.com](https://git-scm.com/downloads)
4. **VS Code**: [code.visualstudio.com](https://code.visualstudio.com)
5. Clone the repo using Git Bash or PowerShell
6. Instead of `bash setup.sh`, run the setup steps manually:
   ```powershell
   # In PowerShell or Command Prompt:
   mkdir "raw material" "extracted frames" "outputs\higgsfield" "outputs\wavespeed" "character sheet"
   pip install -r requirements.txt
   copy config.example.py config.py
   ```

---

## Verifying Everything Works

Run this quick check:

```bash
python3 -c "import cv2, mediapipe, requests, telegram; print('All imports OK')"
```

```bash
ffmpeg -version | head -1
```

```bash
higgsfield --version
```

If all three pass, you're ready to run the pipeline.

---

## Troubleshooting

**`python3: command not found`**
On Mac: `brew install python@3.11`
On Windows: download from python.org and check "Add to PATH"

**`ffmpeg: command not found`**
On Mac: `brew install ffmpeg`
On Windows: download from ffmpeg.org and add the bin folder to your PATH environment variable

**`higgsfield: command not found`**
Run: `pip3 install higgsfield`

**`No selected.png found`**
You need to manually pick one of the 4 Higgsfield images and copy it as `selected.png` in the same folder before running Wavespeed.

**`ModuleNotFoundError: No module named 'X'`**
Run: `pip3 install -r requirements.txt`

**`Google Sheets auth error`**
Delete `token.pickle` and run `python3 setup_sheet.py` again to re-authenticate.

**The Telegram bot isn't responding**
Check `watcher.log` with `tail -f watcher.log`. The most common causes are a wrong bot token or chat ID in `config.py`.

**Higgsfield generates blank / rejected images**
The model may have flagged the content. Try a different source video frame with less skin exposure or a more neutral pose.
