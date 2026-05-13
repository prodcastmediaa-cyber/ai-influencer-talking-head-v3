"""
Generates Mia's clone video using Wavespeed Kling 2.6 Pro Motion Control.

For each video in raw_material/:
  - Reads outputs/higgsfield/{video_name}/selected.png  (your picked Higgsfield output)
  - Pairs it with the original raw video
  - Uploads both to Wavespeed, submits the job, polls, downloads result
  - Saves to outputs/wavespeed/{video_name}/output.mp4
"""
import os
import glob
import time
import subprocess
import tempfile
import requests
from config import (
    RAW_MATERIAL_DIR,
    OUTPUTS_DIR,
    WAVESPEED_API_KEY,
    COL_STATUS,
)
try:
    from sheets import get_sheet, update_row
    SHEETS_ENABLED = True
except Exception:
    SHEETS_ENABLED = False

MAX_VIDEO_SECONDS = 10

BASE_URL   = "https://api.wavespeed.ai/api/v3"
ENDPOINT   = f"{BASE_URL}/kwaivgi/kling-v2.6-pro/motion-control"
UPLOAD_URL = f"{BASE_URL}/media/upload/binary"
HEADERS    = {"Authorization": f"Bearer {WAVESPEED_API_KEY}"}


# ── Trim ─────────────────────────────────────────────────────────────────────

def get_duration(video_path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    )
    return float(r.stdout.strip())


def trim_if_needed(video_path):
    """Return original path if <= 10s, else a trimmed temp file path."""
    duration = get_duration(video_path)
    if duration <= MAX_VIDEO_SECONDS:
        return video_path, None

    print(f"  Video is {duration:.1f}s — trimming to {MAX_VIDEO_SECONDS}s")
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.close()
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-t", str(MAX_VIDEO_SECONDS),
        "-c", "copy", tmp.name
    ], capture_output=True)
    return tmp.name, tmp.name   # (path_to_use, path_to_cleanup)


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_file(local_path):
    """Upload a local file to Wavespeed and return its CDN URL."""
    print(f"  Uploading: {os.path.basename(local_path)}")
    with open(local_path, "rb") as f:
        r = requests.post(
            UPLOAD_URL,
            headers=HEADERS,
            files={"file": (os.path.basename(local_path), f)},
            timeout=120,
        )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 200:
        raise RuntimeError(f"Upload failed: {data}")
    url = data["data"]["download_url"]
    print(f"  Uploaded  → {url}")
    return url


# ── Submit ────────────────────────────────────────────────────────────────────

def submit_job(image_url, video_url):
    payload = {
        "character_orientation": "image",
        "image": image_url,
        "video": video_url,
        "keep_original_sound": True,
    }
    r = requests.post(ENDPOINT, headers={**HEADERS, "Content-Type": "application/json"},
                      json=payload, timeout=30)
    if not r.ok:
        try:
            msg = r.json().get("message") or r.text
        except Exception:
            msg = r.text
        if "credit" in msg.lower() or "top up" in msg.lower() or "insufficient" in msg.lower() or "balance" in msg.lower():
            raise RuntimeError("OUT_OF_CREDITS:Wavespeed")
        raise RuntimeError(f"Wavespeed {r.status_code}: {msg}")
    r.raise_for_status()
    resp = r.json()
    data = resp.get("data", resp)
    job_id   = data.get("id")
    poll_url = data.get("urls", {}).get("get")
    if not job_id:
        raise RuntimeError(f"No job ID in response: {resp}")
    if not poll_url:
        # Fallback: construct from known pattern
        poll_url = f"{BASE_URL}/predictions/{job_id}/result"
    print(f"  Job submitted → {job_id}")
    return job_id, poll_url


# ── Poll ──────────────────────────────────────────────────────────────────────

def poll_job(job_id, poll_url, poll_interval=5, timeout=600):
    """Poll until completed or failed. Returns output URL."""
    print(f"  Polling (up to {timeout}s)...", end="", flush=True)
    elapsed = 0
    while elapsed < timeout:
        r = requests.get(poll_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        resp = r.json()
        data = resp.get("data", resp)

        status = data.get("status")
        print(f" {status}", end="", flush=True)

        if status == "completed":
            print()
            outputs = data.get("outputs", [])
            if not outputs:
                raise RuntimeError("Job completed but no outputs found")
            return outputs[0]

        if status == "failed":
            print()
            raise RuntimeError(f"Job failed: {data.get('error')}")

        time.sleep(poll_interval)
        elapsed += poll_interval

    raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")


# ── Download ──────────────────────────────────────────────────────────────────

def download_file(url, out_path):
    print(f"  Downloading output...")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)
    size_mb = os.path.getsize(out_path) / 1_000_000
    print(f"  Saved → {out_path} ({size_mb:.1f} MB)")


# ── Main ──────────────────────────────────────────────────────────────────────

def mark_sheet_done(video_name):
    """Update sheet Status to Done ✓ for the row matching this video name."""
    if not SHEETS_ENABLED:
        return
    try:
        sheet = get_sheet()
        rows = sheet.get_all_records()
        for i, row in enumerate(rows):
            name_col = str(row.get("Influencer Name", "")).strip().lower()
            if video_name.lower() in name_col or name_col in video_name.lower():
                update_row(i + 2, COL_STATUS, "Done ✓")
                print(f"  Sheet updated → row {i+2} marked Done ✓")
                return
        print(f"  Sheet: no matching row found for '{video_name}' — skipping sheet update")
    except Exception as e:
        print(f"  Sheet update failed (non-fatal): {e}")


def process_video(video_path):
    name = os.path.splitext(os.path.basename(video_path))[0]

    out_dir  = os.path.join(OUTPUTS_DIR, "wavespeed", name)
    out_path = os.path.join(out_dir, "output.mp4")

    # Skip if already completed
    if os.path.exists(out_path):
        print(f"\n[SKIP] {name}: output.mp4 already exists.")
        return out_path

    # Find the user-selected Higgsfield image
    selected = os.path.join(OUTPUTS_DIR, "higgsfield", name, "selected.png")
    if not os.path.exists(selected):
        print(f"\n[SKIP] {name}: no selected.png found.")
        print(f"  → Copy your favourite Higgsfield output to:")
        print(f"    outputs/higgsfield/{name}/selected.png")
        return

    os.makedirs(out_dir, exist_ok=True)

    print(f"\nProcessing: {name}")
    print(f"  Image : {selected}")
    print(f"  Video : {video_path}")

    image_url             = upload_file(selected)
    trimmed_path, cleanup = trim_if_needed(video_path)
    video_url             = upload_file(trimmed_path)
    if cleanup:
        os.unlink(cleanup)
    job_id, poll_url = submit_job(image_url, video_url)
    result           = poll_job(job_id, poll_url)
    download_file(result, out_path)
    mark_sheet_done(name)

    return out_path


def run_all():
    videos = sorted(glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")))
    if not videos:
        print("No .mp4 files found in raw material/")
        return

    done = []
    for v in videos:
        result = process_video(v)
        if result:
            done.append(result)

    print(f"\nDone. {len(done)} video(s) saved to outputs/wavespeed/")


if __name__ == "__main__":
    run_all()
