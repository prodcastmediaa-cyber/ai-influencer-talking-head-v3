"""
Generates 4 character-swapped images using Higgsfield nano_banana_2.
Reference 1: mia-main.png (face, identity, skin, hair)
Reference 2: extracted frame (clothing, pose, scene, background, lighting)
Saves all 4 outputs to outputs/higgsfield/{video_name}/
"""
import subprocess
import os
import json
import glob
import requests
import concurrent.futures
from datetime import datetime
from config import (
    MIA_REFERENCE_IMAGE,
    EXTRACTED_FRAMES_DIR,
    OUTPUTS_DIR,
)

PROMPT = (
    "Use reference image 1 for the face structure, skin color, skin tone, hair, and identity. "
    "Use reference image 2 as the complete reference for clothing, pose, action scene composition, "
    "background environment, lighting setup and overall atmosphere. "
    "Do not use face structure, skin tone, hair, and identity from image 2."
)

MODEL        = "nano_banana_2"
ASPECT_RATIO = "9:16"
RESOLUTION   = "2k"
NUM_OUTPUTS  = 4


def run_generation(ref1, ref2, output_dir, index):
    """Run one Higgsfield generation job and download the result."""
    print(f"  [Job {index+1}/{NUM_OUTPUTS}] Submitting...")

    result = subprocess.run(
        [
            "higgsfield", "generate", "create", MODEL,
            "--image", ref1,
            "--image", ref2,
            "--prompt", PROMPT,
            "--aspect_ratio", ASPECT_RATIO,
            "--resolution", RESOLUTION,
            "--wait",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    if result.returncode != 0:
        print(f"  [Job {index+1}] Error: {result.stderr.strip()}")
        return None

    try:
        data = json.loads(result.stdout)
        # CLI returns a list of result objects
        if isinstance(data, list):
            data = data[0] if data else {}
        url = (
            data.get("result_url")
            or data.get("result", {}).get("url")
            or data.get("output")
            or data.get("url")
        )
        if not url:
            print(f"  [Job {index+1}] No URL in response: {result.stdout[:300]}")
            return None
    except json.JSONDecodeError:
        # Some CLI versions print the URL directly on a line
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("http"):
                url = line
                break
        else:
            print(f"  [Job {index+1}] Could not parse output: {result.stdout[:300]}")
            return None

    # Download the image
    out_path = os.path.join(output_dir, f"output_{index+1}.png")
    print(f"  [Job {index+1}] Downloading → {os.path.basename(out_path)}")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)

    print(f"  [Job {index+1}] Saved: {out_path}")
    return out_path


def generate_for_video(frame_path):
    """Generate NUM_OUTPUTS images for a given extracted frame."""
    video_name = os.path.basename(frame_path).replace("_frame.png", "")
    output_dir = os.path.join(OUTPUTS_DIR, "higgsfield", video_name)

    existing = glob.glob(os.path.join(output_dir, "output_*.png"))
    if existing:
        print(f"\n[SKIP] {video_name}: {len(existing)} image(s) already generated.")
        return sorted(existing)

    os.makedirs(output_dir, exist_ok=True)

    print(f"\nGenerating {NUM_OUTPUTS} outputs for: {video_name}")
    print(f"  Ref 1 (identity): {MIA_REFERENCE_IMAGE}")
    print(f"  Ref 2 (scene):    {frame_path}")
    print(f"  Output dir:       {output_dir}")

    # Run all 4 jobs in parallel
    saved = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_OUTPUTS) as ex:
        futures = {
            ex.submit(run_generation, MIA_REFERENCE_IMAGE, frame_path, output_dir, i): i
            for i in range(NUM_OUTPUTS)
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                saved.append(result)

    print(f"\nDone: {len(saved)}/{NUM_OUTPUTS} images saved to {output_dir}")
    return sorted(saved)


def generate_all():
    os.makedirs(OUTPUTS_DIR, exist_ok=True)
    frames = sorted(glob.glob(os.path.join(EXTRACTED_FRAMES_DIR, "*_frame.png")))
    if not frames:
        print("No extracted frames found. Run extract_frame.py first.")
        return

    for frame_path in frames:
        generate_for_video(frame_path)

    print("\nAll done. Open outputs/higgsfield/ to review and pick your 2 favourites.")


if __name__ == "__main__":
    generate_all()
