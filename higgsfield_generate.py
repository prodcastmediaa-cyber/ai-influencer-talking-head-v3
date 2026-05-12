"""
v5 — Soul V2 + Mia soul_id + OpenCV frame analysis (no external APIs)
soul_id locks identity to trained Mia character; OpenCV describes scene via prompt.
"""
import subprocess
import os
import json
import glob
import requests
import concurrent.futures
import cv2
import numpy as np
from config import (
    MIA_SOUL_ID,
    CHARACTER_HAIR,
    SKIN_STYLE,
    EXTRACTED_FRAMES_DIR,
    OUTPUTS_DIR,
)

MODEL       = "text2image_soul_v2"
NUM_OUTPUTS = 4

HAIR_PRESETS = {
    "jet_black": (
        "long natural jet-black hair with soft cool undertones, rich deep black tone, "
        "subtle espresso sheen under light, smooth realistic texture, soft dimensional shine, "
        "healthy silky finish, natural dark brunette-black blend with effortless depth"
    ),
    "dark_espresso": (
        "long dark espresso-brown hair with soft warm chestnut undertones, subtle caramel-brown "
        "fade toward the ends, natural dimensional shine, realistic texture, soft brunette tone "
        "with slightly sun-kissed warmth, effortless natural finish"
    ),
    "red_head": (
        "long natural copper-red hair with rich ginger undertones, warm golden highlights, "
        "soft dimensional shine, realistic texture, slightly sunlit auburn glow, "
        "natural ginger red tone"
    ),
}

_HAIR = HAIR_PRESETS.get(CHARACTER_HAIR, HAIR_PRESETS["jet_black"])

SKIN_PRESETS = {
    "soft": (
        "smooth refined skin, soft-focus complexion, subtle skin detail, "
        "gentle porcelain finish, even skin tone"
    ),
    "realistic": (
        "natural skin pores visible, realistic skin micro-texture, subtle skin tone variations, "
        "candid photography skin detail, human skin depth, no retouching, "
        "natural uneven skin undertones"
    ),
    "imperfect": (
        "authentic human skin, clearly visible pores, natural skin imperfections, "
        "slight texture irregularities, raw unretouched skin detail, "
        "documentary-style skin realism, lived-in natural complexion"
    ),
}

_SKIN = SKIN_PRESETS.get(SKIN_STYLE, SKIN_PRESETS["realistic"])

_EXTRA = (
    "use reference soul character strictly, preserve exact face and identity, "
    f"{_SKIN}, subtle eyeliner, light blush, soft nude lips, "
    "realistic human details, no tattoos"
)


def analyze_frame(frame_path: str) -> str:
    img = cv2.imread(frame_path)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    brightness = float(gray.mean())
    if brightness > 170:
        lighting = "bright natural daylight, high-key lighting, airy atmosphere"
    elif brightness > 110:
        lighting = "soft diffused daylight, balanced natural exposure"
    elif brightness > 70:
        lighting = "warm indoor lighting, golden hour feel, cozy ambiance"
    else:
        lighting = "moody low-key lighting, dramatic shadows, cinematic feel"

    b_ch, g_ch, r_ch = cv2.split(img)
    tone = "warm golden tones" if float(r_ch.mean()) > float(b_ch.mean()) else "cool blue-toned palette"

    edges = cv2.Canny(gray, 100, 200)
    complex_bg = float(edges.mean()) > 12
    environment = (
        "dynamic urban environment with architectural details in background"
        if complex_bg else
        "clean minimal background, uncluttered modern setting"
    )

    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4)
    if len(faces) > 0:
        fx, fy, fw, fh = faces[0]
        face_y = (fy + fh / 2) / h
    else:
        face_y = 0.35

    if face_y < 0.35:
        pose = "close-up portrait, face and upper chest visible, slight angle to camera, natural expression"
        camera = "tight portrait shot, eye-level, 85mm lens feel, shallow bokeh"
    elif face_y < 0.55:
        pose = "medium shot, upper body fully visible, relaxed confident posture, natural stance"
        camera = "medium portrait, eye-level angle, 50mm lens feel, soft background blur"
    else:
        pose = "full body shot, confident standing pose, slight three-quarter angle, dynamic presence"
        camera = "full body portrait, slight low angle, 35mm lens feel, cinematic framing"

    prompt = (
        f"Pose:\n{pose}\n\n"
        f"Environment:\n{environment}, {lighting}, {tone}\n\n"
        f"Clothing:\nstylish contemporary outfit suited to the scene, {_HAIR}\n\n"
        f"Camera:\n{camera}, 9:16 vertical, sharp focus on subject, professional quality\n\n"
        f"Extra:\n{_EXTRA}"
    )
    print(f"  [OpenCV] brightness={brightness:.0f}, complex_bg={complex_bg}, face_y={face_y:.2f}")
    print(f"  [OpenCV] Prompt:\n{prompt}\n")
    return prompt


def run_generation(output_dir, index, prompt):
    print(f"  [Job {index+1}/{NUM_OUTPUTS}] Submitting...")

    result = subprocess.run(
        [
            "higgsfield", "generate", "create", MODEL,
            "--soul_id", MIA_SOUL_ID,
            "--prompt", prompt,
            "--aspect_ratio", "9:16",
            "--quality", "2k",
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

    print(f"\nAnalyzing frame (OpenCV): {video_name}")
    prompt = analyze_frame(frame_path)

    print(f"Generating {NUM_OUTPUTS} outputs for: {video_name}")
    print(f"  Soul ID (Mia): {MIA_SOUL_ID}")
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
