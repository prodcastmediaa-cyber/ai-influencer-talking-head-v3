"""
Generates 4 images using Higgsfield Soul Character 2.0.
Step 1: Analyze extracted frame with GPT-4o → structured prompt
Step 2: Generate with Soul V2 using character reference + LLM prompt
"""
import subprocess
import os
import json
import glob
import base64
import requests
import concurrent.futures
from openai import OpenAI
from config import (
    MIA_REFERENCE_IMAGE,
    EXTRACTED_FRAMES_DIR,
    OUTPUTS_DIR,
    OPENAI_API_KEY,
)

MODEL       = "text2image_soul_v2"
NUM_OUTPUTS = 4

HAIR_DESCRIPTION = (
    "long natural jet-black hair with soft cool undertones, rich deep black tone, "
    "subtle espresso sheen under light, smooth realistic texture, soft dimensional shine, "
    "healthy silky finish, natural dark brunette-black blend with effortless depth"
)

_FRAME_ANALYSIS_PROMPT = (
    "Analyze this video frame and write a structured image generation prompt in EXACTLY this format. "
    "Output only the prompt text, nothing else — no preamble, no explanation.\n\n"
    "Pose:\n"
    "[body position, stance, angle, movement, gesture]\n\n"
    "Environment:\n"
    "[location, setting, time of day, lighting, atmosphere]\n\n"
    "Clothing:\n"
    "[outfit and accessories], " + HAIR_DESCRIPTION + "\n\n"
    "Camera:\n"
    "[camera angle, shot type, distance, lens feel, style]\n\n"
    "Extra:\n"
    "use reference soul character strictly, preserve exact face and identity, "
    "natural skin texture, subtle eyeliner, light blush, soft nude lips, "
    "realistic human details, no tattoos, avoid overly shiny skin"
)


def analyze_frame(frame_path: str) -> str:
    client = OpenAI(api_key=OPENAI_API_KEY)
    with open(frame_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{image_data}",
                        "detail": "high",
                    },
                },
                {"type": "text", "text": _FRAME_ANALYSIS_PROMPT},
            ],
        }],
    )
    prompt = response.choices[0].message.content.strip()
    print(f"  [GPT-4o] Generated prompt:\n{prompt}\n")
    return prompt


def run_generation(output_dir, index, prompt):
    print(f"  [Job {index+1}/{NUM_OUTPUTS}] Submitting...")

    result = subprocess.run(
        [
            "higgsfield", "generate", "create", MODEL,
            "--image", MIA_REFERENCE_IMAGE,
            "--prompt", prompt,
            "--wait",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    if result.returncode != 0:
        err = (result.stderr.strip() or result.stdout.strip())[:400]
        print(f"  [Job {index+1}] CLI error (exit {result.returncode}): {err}")
        if "not authenticated" in err.lower() or "auth login" in err.lower():
            raise RuntimeError(
                f"Higgsfield CLI not authenticated — run: higgsfield auth login\n{err}"
            )
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

    print(f"\nAnalyzing frame with GPT-4o: {video_name}")
    prompt = analyze_frame(frame_path)

    print(f"Generating {NUM_OUTPUTS} outputs for: {video_name}")
    print(f"  Character ref: {MIA_REFERENCE_IMAGE}")
    print(f"  Model:         {MODEL}")
    print(f"  Output dir:    {output_dir}")

    saved = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_OUTPUTS) as ex:
        futures = {
            ex.submit(run_generation, output_dir, i, prompt): i
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
