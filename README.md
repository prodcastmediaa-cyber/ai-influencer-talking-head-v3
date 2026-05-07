# AI Influencer Video Generator

Automatically swap any influencer's face and identity with your custom AI character using a two-stage AI pipeline — Higgsfield for image generation and Wavespeed Kling for video generation.

Drop in a raw video. Get back a video with your AI character's face, same motion, same background.

---

## What This Does

Takes a real influencer video and creates a "clone" version where the person's appearance is replaced by your custom AI character — preserving the exact motion, pose, clothing context, background, and lighting from the original.

### The Two-Stage Pipeline

```
Raw Video (.mp4)
     │
     ▼
[Stage 1 — Frame Extraction]
     Pick the sharpest frame where eyes are open
     Uses: MediaPipe Face Landmarker
     │
     ▼
[Stage 2 — Image Generation via Higgsfield]
     Swap identity: AI character's face + scene from original
     Generates 4 candidate images in parallel
     Model: nano_banana_2 (9:16, 2K resolution)
     │
     ▼  ← You manually pick the best of the 4 images
[Stage 3 — Video Generation via Wavespeed Kling]
     Apply selected image as face reference to original video
     Model: Kling v2.6 Pro Motion Control
     │
     ▼
Output Video (.mp4) — AI character's face, original motion
```

---

## What We Built (Iteration History)

### Iteration 1 — Manual proof of concept
- Ran Higgsfield manually from the browser
- Ran Wavespeed manually from the browser
- Confirmed the face swap worked well enough to automate

### Iteration 2 — Python scripts for each step
- `extract_frame.py` — automatically picks the best frame from a video (sharpest, eyes open)
- `higgsfield_generate.py` — calls the Higgsfield CLI to generate 4 candidate images in parallel
- `wavespeed_generate.py` — uploads image + video to Wavespeed API, polls, downloads result
- `sheets.py` — Google Sheets integration for tracking status per video

### Iteration 3 — Smart pipeline with skip logic
- Added skip logic to all scripts: already-completed steps are never re-run
- Created `run_pipeline.py` — single command that runs all steps in sequence, pauses when manual input is needed, and resumes where it left off
- Wavespeed script now auto-marks the corresponding Google Sheet row as "Done ✓" when complete
- Designed for future N8n / phone automation — fully idempotent (safe to run multiple times)

---

## Project Structure

```
ai_inf_test/
├── run_pipeline.py          ← Main entry point — runs everything
├── extract_frame.py         ← Step 1: Extract best frame from video
├── higgsfield_generate.py   ← Step 2: Generate 4 AI character-swapped images
├── wavespeed_generate.py    ← Step 4: Generate final output video
├── sheets.py                ← Google Sheets read/write helper
├── setup_sheet.py           ← One-time: creates sheet headers
├── config.example.py        ← Template — copy to config.py and fill in keys
├── config.py                ← Your actual config (not committed — has API keys)
├── requirements.txt         ← Python dependencies
├── face_landmarker.task     ← MediaPipe model for face/eye detection
├── character sheet mia/
│   └── mia-main.png         ← Your AI character's reference image (face, skin, hair, identity)
├── raw material/            ← Put your input .mp4 files here
├── extracted frames/        ← Auto-generated: best frame per video
└── outputs/
    ├── higgsfield/          ← 4 generated images per video
    │   └── {video_name}/
    │       ├── output_1.png
    │       ├── output_2.png
    │       ├── output_3.png
    │       ├── output_4.png
    │       └── selected.png ← You create this (copy of your chosen image)
    └── wavespeed/           ← Final output videos
        └── {video_name}/
            └── output.mp4
```

---

## Prerequisites

- Mac (tested on macOS)
- Python 3.10+
- [ffmpeg](https://ffmpeg.org/download.html) installed (`brew install ffmpeg`)
- [Higgsfield CLI](https://higgsfield.ai) installed and logged in
- A [Wavespeed](https://wavespeed.ai) account and API key
- A Google Cloud project with Sheets + Drive API enabled (for tracking)

---

## First-Time Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/ai-influencer-video-generator.git
cd ai-influencer-video-generator
```

### 2. Install Python dependencies

```bash
pip3 install -r requirements.txt
pip3 install opencv-python mediapipe
```

### 3. Set up config

```bash
cp config.example.py config.py
```

Open `config.py` and fill in:
- `SHEET_ID` — from your Google Sheet URL
- `SHEET_NAME` — name of the tab (e.g. "May 2026")
- `HIGGSFIELD_API_KEY` — from higgsfield.ai → Settings → API
- `WAVESPEED_API_KEY` — from wavespeed.ai → Dashboard → API Keys

### 4. Set up Google Sheets credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Google Sheets API** and **Google Drive API**
3. Create OAuth 2.0 credentials → Desktop App → Download as `credentials.json`
4. Place `credentials.json` in the project root
5. Run once to authenticate:
```bash
python3 setup_sheet.py
```
A browser window will open. Log in. A `token.pickle` file will be saved — this auto-refreshes from now on.

### 5. Create the required folders

```bash
mkdir -p "raw material" "extracted frames" "outputs/higgsfield" "outputs/wavespeed"
```

### 6. Add your AI character's reference image

Place your character's reference photo at:
```
character sheet mia/mia-main.png
```
This is the identity source — your AI character's face, skin tone, hair, and overall look will be used in every generated image.

---

## How to Generate a New Video (Every Time)

### Step 1 — Add your video
Drop the `.mp4` file into the `raw material/` folder.

### Step 2 — Run the pipeline
```bash
cd ~/Downloads/ai_inf_test
python3 run_pipeline.py
```

The script will:
- Extract the best frame automatically
- Generate 4 AI character-swapped images via Higgsfield
- **Pause** and tell you to pick the best image

### Step 3 — Pick the best image (manual)
1. Open Finder → `outputs/higgsfield/{your_video_name}/`
2. Look at `output_1.png` through `output_4.png`
3. Pick the best one → duplicate it → rename the copy to **`selected.png`**
4. It must be in the same folder

### Step 4 — Finish the pipeline
```bash
python3 run_pipeline.py
```
It skips everything already done and generates the final video.

### Result
Your video is at:
```
outputs/wavespeed/{video_name}/output.mp4
```

---

## How the Skip Logic Works

Every script checks if its output already exists before running:

| Script | Skip condition |
|--------|---------------|
| `extract_frame.py` | `extracted frames/{name}_frame.png` already exists |
| `higgsfield_generate.py` | `outputs/higgsfield/{name}/output_1.png` already exists |
| `wavespeed_generate.py` | `outputs/wavespeed/{name}/output.mp4` already exists |

This means you can add one new video to `raw material/`, run `python3 run_pipeline.py`, and it will only process the new one — all previously completed videos are skipped automatically.

---

## Google Sheet Tracking

The sheet has 5 columns:

| Sr No | Influencer Name | Google Drive Link | Frame Image Link | Status |
|-------|----------------|-------------------|------------------|--------|
| 1     | video3         | https://...       |                  | Done ✓ |

- After Wavespeed completes, the script automatically sets `Status = Done ✓`
- The sheet name and ID are set in `config.py`
- To re-run setup headers: `python3 setup_sheet.py`

---

## The Higgsfield Prompt

This prompt is used in `higgsfield_generate.py` when calling the `nano_banana_2` model:

```
Use reference image 1 for the face structure, skin color, skin tone, hair, and identity.
Use reference image 2 as the complete reference for clothing, pose, action scene composition,
background environment, lighting setup and overall atmosphere.
Do not use face structure, skin tone, hair, and identity from image 2.
```

**Reference image 1** = `character sheet mia/mia-main.png` (your AI character's identity)
**Reference image 2** = extracted frame from the original video (scene, pose, clothing)

Settings used:
- Model: `nano_banana_2`
- Aspect ratio: `9:16`
- Resolution: `2K`
- Outputs: 4 images per video (generated in parallel)

---

## Wavespeed Settings

API endpoint: `kwaivgi/kling-v2.6-pro/motion-control`

Payload:
```json
{
  "character_orientation": "image",
  "image": "<uploaded selected.png>",
  "video": "<uploaded original video>",
  "keep_original_sound": true
}
```

- Videos longer than 10 seconds are auto-trimmed before upload
- Polls every 5 seconds, times out after 600 seconds

---

## Frame Extraction Logic

`extract_frame.py` uses **MediaPipe Face Landmarker** to pick the best frame:

1. Samples 100 evenly-spaced frames from the middle 80% of the video
2. For each frame, measures eye blink score (0 = fully open, 1 = closed)
3. Picks the frame with the most open eyes and sharpest face (Laplacian variance)

Priority tiers:
1. Eyes open + sharp face
2. Eyes open (any sharpness)
3. Sharpest face regardless of eye state (fallback)

---

## Future Automation (Planned)

The pipeline is designed to be triggered remotely:

- **N8n workflow** → triggers `python3 run_pipeline.py` on new video upload
- **Telegram bot** → sends generated images for approval, receives `selected.png` selection
- **Google Drive** → watches for new raw video uploads, auto-downloads to `raw material/`

The `run_pipeline.py` script is fully idempotent — safe to call from any automation tool.

---

## Files Not in This Repo

These are excluded from git (see `.gitignore`) for security or size:

| File/Folder | Why excluded |
|-------------|-------------|
| `config.py` | Contains API keys |
| `credentials.json` | Google OAuth client secret |
| `token.pickle` | Google auth session token |
| `raw material/` | Large video files |
| `outputs/` | Large generated media |
| `extracted frames/` | Intermediate files |

---

## Troubleshooting

**`zsh: command not found: python`**
Use `python3` instead of `python`. Or run once: `echo 'alias python=python3' >> ~/.zshrc && source ~/.zshrc`

**`No selected.png found`**
You need to manually pick one of the 4 Higgsfield images and save it as `selected.png` in the same folder.

**Higgsfield CLI not found**
Install from [higgsfield.ai](https://higgsfield.ai) and make sure you're logged in via `higgsfield login`.

**Google Sheets auth error**
Delete `token.pickle` and run `python3 setup_sheet.py` again to re-authenticate.

---

## LLM Context Summary

If you are an LLM reading this repo: this project is a local Python automation pipeline running on macOS. It has no web server, no frontend, and no database. All state is stored in local folders and one Google Sheet. The entry point for running is `run_pipeline.py`. The two external AI APIs are Higgsfield (image generation via CLI) and Wavespeed (video generation via REST API). The `config.py` file (not committed) holds all keys and paths. The `face_landmarker.task` file is a pre-downloaded MediaPipe model binary. The character reference image inside `character sheet mia/` is the AI character identity source for all generated content.
