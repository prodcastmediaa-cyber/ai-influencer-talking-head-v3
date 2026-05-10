"""
Generates 4 images using Higgsfield Nano Banana Pro.
Image 1: Mia reference (character appearance)
Image 2: Extracted scene frame (pose, outfit, background)
"""
import subprocess
import os
import json
import glob
import requests
import concurrent.futures
from config import (
    MIA_REFERENCE_IMAGE,
    EXTRACTED_FRAMES_DIR,
    OUTPUTS_DIR,
)

PROMPT = (
    "The character from image 1 placed into the exact scene from image 2. "
    "Use image 2 for all scene details: background, location, clothing, body pose, lighting, and composition. "
    "Use image 1 only for the face and identity. "
    "Photorealistic, sharp focus, high detail, 9:16 vertical."
)

MODEL       = "nano_banana_2"
ASPECT      = "9:16"
RESOLUTION  = "2k"
NUM_OUTPUTS = 4


def run_generation(frame_path, output_dir, index):
    print(f"  [Job {index+1}/{NUM_OUTPUTS}] Submitting...")

    result = subprocess.run(
        [
            "higgsfield", "generate", "create", MODEL,
            "--image", MIA_REFERENCE_IMAGE,
            "--image", frame_path,
            "--prompt", PROMPT,
            "--aspect_ratio", ASPECT,
            "--resolution", RESOLUTION,
            "--wait",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    if result.returncode != 0:
        err = (result.stderr.strip() or result.stdout.strip())[:300]
        print(f"  [Job {index+1}] CLI error (exit {result.returncode}): {err}")
        return None

    try:
        data = json.loads(result.stdout)
        if isinstance(data, list):
            data = data[0] if data else {}
        url = (
            data.get("result_url")
            or data.get("result", {}).get("url")
            or data.get("output")
            or data.get("url")
        )
        if not url:
            print(f"  [Job {index+1}] No URL — status: {data.get('status', 'unknown')}")
            return None
    except json.JSONDecodeError:
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("http"):
                url = line
                break
        else:
            print(f"  [Job {index+1}] Could not parse output: {result.stdout[:300]}")
            return None

    out_path = os.path.join(output_dir, f"output_{index+1}.png")
    print(f"  [Job {index+1}] Downloading → {os.path.basename(out_path)}")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)

    print(f"  [Job {index+1}] Saved: {out_path}")
    return out_path


def generate_for_video(frame_path, on_progress=None):
    video_name = os.path.basename(frame_path).replace("_frame.png", "")
    output_dir = os.path.join(OUTPUTS_DIR, "higgsfield", video_name)

    existing = glob.glob(os.path.join(output_dir, "output_*.png"))
    if existing:
        print(f"\n[SKIP] {video_name}: {len(existing)} image(s) already generated.")
        return sorted(existing)

    os.makedirs(output_dir, exist_ok=True)

    print(f"\nGenerating {NUM_OUTPUTS} outputs for: {video_name}")
    print(f"  Character ref: {MIA_REFERENCE_IMAGE}")
    print(f"  Scene frame:   {frame_path}")
    print(f"  Output dir:    {output_dir}")

    saved = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_OUTPUTS) as ex:
        futures = {
            ex.submit(run_generation, frame_path, output_dir, i): i
            for i in range(NUM_OUTPUTS)
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                saved.append(result)
            if on_progress:
                try:
                    on_progress(len(saved))
                except Exception:
                    pass

    print(f"\nDone: {len(saved)}/{NUM_OUTPUTS} images saved to {output_dir}")
    if not saved:
        raise RuntimeError(f"All {NUM_OUTPUTS} Higgsfield jobs failed — check terminal for the actual error")
    return sorted(saved)


def generate_all():
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    frames = sorted(glob.glob(os.path.join(EXTRACTED_FRAMES_DIR, "*_frame.png")))
    if not frames:
        print("No extracted frames found. Run extract_frame.py first.")
        return
    for frame_path in frames:
        generate_for_video(frame_path)
    print("\nAll done. Open outputs/higgsfield/ to review.")


if __name__ == "__main__":
    generate_all()
