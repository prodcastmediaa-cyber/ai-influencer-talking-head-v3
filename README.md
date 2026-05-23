# AI Influencer Automation — V3

> **This is Version 3.** Install after [V1](https://github.com/prodcastmediaa-cyber/ai-influencer-automation) and [V2](https://github.com/prodcastmediaa-cyber/ai-influencer-talking-head-v2).

A fully automated AI influencer content pipeline. Drop a link or video into Telegram — get a finished AI character video back. Or tap **Let AI Create** to generate entire photoshoots with zero source material.

[![Python](https://img.shields.io/badge/Python-3.10+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## What's New in V3 — Batch AI Generation

V3 adds a **"Let AI Create"** system that generates fully original photoshoots with no source video needed. You pick a style and a scene count — Claude invents unique scenes, Higgsfield renders them.

### The Flow

```
Tap "Let AI Create"
        ↓
  🌸 Daily Stuff    🔥 Fanvue Stuff
        ↓
  2  4  6  8  (scenes)
        ↓
  2 images per scene = up to 16 total images
```

**Daily Stuff** — lifestyle & going-out content. City streets, rooftops, cafés, restaurants. Sexy mini dresses, club outfits, party dresses. Any environment.

**Fanvue Stuff** — intimate content. Indoor only (bedroom, bathroom, living room, dressing room). Lingerie, lace, satin. Natural window light.

**Every scene is unique** — different outfit, different color, different pose, different location. Claude Haiku generates each scene individually with an explicit variety constraint, so you never get the same pink outfit twice.

---

## How It Works (Full Pipeline)

1. **Drop a link or video** — paste a TikTok / Instagram / YouTube URL in Telegram, or upload an .mp4 directly
2. **Smart frame extraction** — MediaPipe scans every frame to find the best shot (eyes open, face unobstructed, sharpest detail), then upscales 2x with EDSR AI super-resolution
3. **AI character generation** — Higgsfield Soul Character 2.0 generates 4 portrait images locked to your trained character's identity, placed in the same scene as the source
4. **You pick one** — the bot sends all 4 to Telegram; you tap a button
5. **Video generation** — Wavespeed Kling 2.6 Pro animates your chosen image using the original video as a motion reference
6. **Delivery** — finished video sent to Telegram + uploaded to Google Drive

Or skip all of that and just tap **Let AI Create** to generate a full photoshoot from scratch.

---

## Prerequisites — Install V1 and V2 First

This repo is Version 3 of a multi-part series. You should have already set up:

| Repo | What it adds |
|------|-------------|
| [V1 — ai-influencer-automation](https://github.com/prodcastmediaa-cyber/ai-influencer-automation) | Core clone pipeline: frame extraction, Higgsfield image gen, Wavespeed video gen, Telegram bot |
| [V2 — ai-influencer-talking-head-v2](https://github.com/prodcastmediaa-cyber/ai-influencer-talking-head-v2) | Talking head + UGC video generation |
| **V3 (this repo)** | Batch AI photoshoot generation — Daily Stuff & Fanvue Stuff |

If you haven't set up V1 yet, start there. V3 builds on the same config, Soul Character, and Telegram bot.

---

## Quick Start

```bash
git clone https://github.com/prodcastmediaa-cyber/ai-influencer-talking-head-v3.git
cd ai-influencer-talking-head-v3
bash setup.sh
```

Then copy your `config.py` from your V1/V2 setup — all the same keys are used.

```bash
bash start_bot.sh
```

Open Telegram → tap **▶️ Start** → **🖼 Make Images** → **✨ Let AI Create**.

> See [INSTALLATION.md](INSTALLATION.md) for the full step-by-step including Soul Character setup and VPS deployment.

---

## Tech Stack

| Tool | Purpose |
|------|---------|
| [Higgsfield](https://higgsfield.ai) | AI character image generation (Soul Character 2.0) |
| [Wavespeed Kling 2.6 Pro](https://wavespeed.ai) | Motion control video generation |
| [Claude Haiku](https://anthropic.com) | Scene prompt generation for batch photoshoots |
| [MediaPipe](https://mediapipe.dev) | Face landmark + blink detection, hand tracking |
| [OpenCV + EDSR](https://github.com/Saafke/EDSR_Tensorflow) | Frame extraction + 2x AI super-resolution |
| [python-telegram-bot](https://python-telegram-bot.org) | Async Telegram automation with inline buttons |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | TikTok / Instagram / YouTube download |
| [Google Drive API](https://developers.google.com/drive) | Auto-upload finished videos |
| [ffmpeg](https://ffmpeg.org) | Video trimming, frame extraction, codec conversion |

---

## Folder Structure

```
ai-influencer-v3/
├── raw material/              ← Drop .mp4 files here (or send via Telegram)
├── extracted frames/          ← Auto-generated best frames
├── outputs/
│   ├── higgsfield/            ← Generated images (4 per clone, up to 16 per batch)
│   └── wavespeed/             ← Final output videos
│
├── config.example.py          ← Template — copy to config.py and fill in keys
├── config.py                  ← Your API keys (git-ignored, never committed)
├── higgsfield_generate.py     ← Image generation + batch prompt system
├── wavespeed_generate.py      ← Video generation via Kling
├── extract_frame.py           ← Smart frame extraction + upscaling
├── watcher.py                 ← 24/7 Telegram bot + filesystem daemon
├── run_pipeline.py            ← One-command CLI pipeline runner
├── setup.sh                   ← First-time setup (folders, deps, config template)
├── start_bot.sh               ← Start the 24/7 daemon in background
├── stop_bot.sh                ← Stop the daemon
└── requirements.txt           ← Python dependencies
```

---

## API Keys

| Service | Where to get it | Required? |
|---------|----------------|-----------|
| **Higgsfield API key** | [higgsfield.ai](https://higgsfield.ai) → Settings → API | Yes |
| **Higgsfield Soul Character ID** | higgsfield.ai → Soul Characters → your character → copy UUID | Yes |
| **Claude API key** | [console.anthropic.com](https://console.anthropic.com) | Yes (for Let AI Create) |
| **Wavespeed API key** | [wavespeed.ai](https://wavespeed.ai) → Dashboard → API Keys | Yes |
| **Telegram Bot Token** | [@BotFather](https://t.me/BotFather) → /newbot | For bot mode |
| **Google credentials.json** | Google Cloud Console → OAuth2 → Download | Optional (Drive upload) |

---

## Running 24/7 on a VPS

The bot runs on your laptop by default — it stops when your computer sleeps.

To keep it running 24/7, deploy to a cloud VPS. We use [Vultr](https://www.vultr.com/) — a $6/month server handles everything since Higgsfield and Wavespeed do the heavy lifting on their own servers.

See the full guide: **[DEPLOY_VPS.md](DEPLOY_VPS.md)**

---

## Notes

- **Batch scenes run sequentially** — 2 Higgsfield jobs at a time, one scene at a time. This prevents Higgsfield from defaulting to catalog/grid layouts.
- **No repeated outfits** — Claude generates each scene individually with an avoid list from previous scenes in the same run.
- **No tattoos** — enforced at both the prompt and Extra level.
- **Model files download automatically** on first run (`face_landmarker.task`, `hand_landmarker.task`, `EDSR_x2.pb`)
- **Videos over 10 seconds** are auto-trimmed before Wavespeed upload
- **Instagram downloads** require cookies if the account is private — send `cookies.txt` to the bot via Telegram

---

## License

MIT — use it, modify it, build with it.
