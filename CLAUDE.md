# AI Influencer Video Generator — Project Guide

## What This Project Does

Takes raw influencer videos, swaps the face/identity with "Mia" (a virtual character), and outputs final clone videos. Two-stage AI pipeline: Higgsfield (image generation) → Wavespeed Kling (video generation).

---

## Folder Structure

```
ai_inf_test/
├── raw material/           ← Put new input .mp4 videos here
├── character sheet mia/    ← Mia's reference images (mia-main.png is the key one)
├── extracted frames/       ← Auto-generated best frames from each video
├── outputs/
│   ├── higgsfield/         ← 4 generated images per video (output_1.png to output_4.png)
│   └── wavespeed/          ← Final output video per video (output.mp4)
├── config.py               ← API keys, paths, Google Sheet config
├── extract_frame.py        ← Step 1: Extract best face frame from videos
├── higgsfield_generate.py  ← Step 2: Generate 4 Mia-swapped images
├── wavespeed_generate.py   ← Step 4: Generate final video
├── sheets.py               ← Google Sheets integration (tracking)
├── setup_sheet.py          ← One-time sheet header setup
├── requirements.txt        ← Python dependencies
└── credentials.json        ← Google OAuth credentials (do not share)
```

---

## Full Pipeline (Step by Step)

### Step 1 — Extract best frame
```bash
cd ~/Downloads/ai_inf_test
python extract_frame.py
```
Output: `extracted frames/{video_name}_frame.png`

### Step 2 — Generate Mia-swapped images (Higgsfield)
```bash
python higgsfield_generate.py
```
Output: `outputs/higgsfield/{video_name}/output_1.png` through `output_4.png`

### Step 3 — Pick best image (MANUAL)
Open `outputs/higgsfield/{video_name}/` in Finder.  
Pick the best image → copy and rename it to **`selected.png`** in the same folder.

### Step 4 — Generate final video (Wavespeed Kling)
```bash
python wavespeed_generate.py
```
Output: `outputs/wavespeed/{video_name}/output.mp4`

---

## API Keys

| Service     | Location in config.py     | Status                  |
|-------------|---------------------------|-------------------------|
| Wavespeed   | `WAVESPEED_API_KEY`       | Already set             |
| Higgsfield  | `HIGGSFIELD_API_KEY`      | Fill in if blank        |

---

## Google Sheets Tracking

- Sheet ID: `1qm7kOQx4BVkXF_AHTmTZpshbLtX91XyerMkjwBLtNvg`
- Sheet Name: `May 2026`
- Auth token cached in `token.pickle` (auto-refreshes)

---

## Adding a New Video Sample (Recommended — Smart Pipeline)

1. Copy new `.mp4` file into `raw material/`
2. Run `python3 run_pipeline.py`
3. If it pauses asking for manual selection → open `outputs/higgsfield/{name}/` → pick best image → copy and rename to `selected.png`
4. Run `python3 run_pipeline.py` again — it picks up where it left off
5. Collect result from `outputs/wavespeed/{video_name}/output.mp4`

The pipeline **skips already-completed steps automatically** and **marks the Google Sheet row as "Done ✓"** when finished. Safe to run repeatedly.

---

## Notes

- Videos longer than 10 seconds are auto-trimmed to 10s before Wavespeed upload
- Higgsfield generates 4 images in parallel per video
- `mia-main.png` = identity/face reference. Do not replace without updating the character
- `face_landmarker.task` = MediaPipe model file, must stay in project root
