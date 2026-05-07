"""
Extracts the best frame from each video in raw_material/.
Uses MediaPipe Face Landmarker blendshapes (eyeBlinkLeft/Right) for accurate
open-eye detection. Saves results to extracted_frames/.
"""
import subprocess
import os
import glob
import shutil
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from config import RAW_MATERIAL_DIR, EXTRACTED_FRAMES_DIR

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH      = os.path.join(BASE_DIR, "face_landmarker.task")

# Eye blink blendshape score: 0.0 = fully open, 1.0 = fully closed
EYE_OPEN_THRESHOLD = 0.35   # below this = eyes open
MIN_FACE_SHARP     = 15.0


def build_landmarker():
    options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
        output_face_blendshapes=True,
        num_faces=1,
        min_face_detection_confidence=0.4,
        min_face_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    return mp_vision.FaceLandmarker.create_from_options(options)


def face_sharpness(img, landmarks, w, h):
    """Laplacian variance on the face bounding box."""
    if not landmarks:
        return 0.0
    xs = [int(l.x * w) for l in landmarks]
    ys = [int(l.y * h) for l in landmarks]
    x1 = max(min(xs) - 10, 0);  x2 = min(max(xs) + 10, w)
    y1 = max(min(ys) - 10, 0);  y2 = min(max(ys) + 10, h)
    crop = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(crop, cv2.CV_64F).var()


def analyze_frame(img, landmarker):
    h, w = img.shape[:2]
    rgb     = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mp_img  = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result  = landmarker.detect(mp_img)

    if not result.face_landmarks or not result.face_blendshapes:
        return False, 1.0, 0.0

    blendshapes = {b.category_name: b.score for b in result.face_blendshapes[0]}
    blink_left  = blendshapes.get("eyeBlinkLeft",  1.0)
    blink_right = blendshapes.get("eyeBlinkRight", 1.0)
    avg_blink   = (blink_left + blink_right) / 2.0
    eyes_open   = avg_blink < EYE_OPEN_THRESHOLD

    sharp = face_sharpness(img, result.face_landmarks[0], w, h)
    return eyes_open, avg_blink, sharp


def extract_candidates(video_path, tmp_dir, n=100):
    os.makedirs(tmp_dir, exist_ok=True)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())
    start  = duration * 0.10
    length = duration * 0.80

    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(start), "-t", str(length),
        "-i", video_path,
        "-vf", f"fps={n}/{length},scale=1080:-1",
        "-frames:v", str(n),
        os.path.join(tmp_dir, "frame_%04d.png")
    ], capture_output=True)


def pick_best_frame(tmp_dir, landmarker):
    candidates = sorted(glob.glob(os.path.join(tmp_dir, "*.png")))
    if not candidates:
        return None, "no frames"

    scored = []
    for path in candidates:
        img = cv2.imread(path)
        if img is None:
            continue
        eyes_open, blink_score, sharp = analyze_frame(img, landmarker)
        scored.append((path, eyes_open, blink_score, sharp))

    open_frames = [(p, b, s) for p, o, b, s in scored if o]

    # Tier 1: eyes open + sharp face
    tier1 = [(p, b, s) for p, b, s in open_frames if s >= MIN_FACE_SHARP]
    # Tier 2: eyes open any sharpness
    tier2 = open_frames
    # Tier 3: sharpest face regardless of eye state
    tier3 = [(p, b, s) for p, o, b, s in scored if s > 0]

    for tier, label in [
        (tier1, "eyes open + sharp"),
        (tier2, "eyes open (soft — fast motion)"),
        (tier3, "fallback: sharpest face"),
    ]:
        if tier:
            best = min(tier, key=lambda x: x[1])   # lowest blink score = most open
            print(f"  Best: {os.path.basename(best[0])} | {label} | blink={best[1]:.3f} | sharpness={best[2]:.1f}")
            return best[0], label

    return candidates[0], "last resort"


def extract_all():
    os.makedirs(EXTRACTED_FRAMES_DIR, exist_ok=True)
    videos = sorted(glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")))
    if not videos:
        print("No .mp4 files found in raw material/")
        return

    landmarker = build_landmarker()

    for video_path in videos:
        name    = os.path.splitext(os.path.basename(video_path))[0]
        out     = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
        tmp_dir = os.path.join(EXTRACTED_FRAMES_DIR, f"_tmp_{name}")

        if os.path.exists(out):
            print(f"[SKIP] {name}: frame already extracted.")
            continue

        print(f"Processing: {os.path.basename(video_path)}")
        extract_candidates(video_path, tmp_dir)
        best_path, label = pick_best_frame(tmp_dir, landmarker)

        if best_path:
            shutil.copy2(best_path, out)
            print(f"  Saved → extracted frames/{name}_frame.png")
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\nDone. {len(videos)} frame(s) extracted.")


if __name__ == "__main__":
    extract_all()
