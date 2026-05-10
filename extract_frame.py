"""
Extracts the best frame from each video in raw_material/.

Scoring priority (best to worst):
  1. Face fully visible (no hand obstruction) + eyes open + sharp
  2. Face fully visible + eyes open (any sharpness)
  3. Face fully visible + sharpest face (any eye state)
  4. Eyes open + sharp  (hand may be present — fallback)
  5. Absolute last resort: any frame with a detected face

After picking the best frame, applies 2x AI super-resolution (EDSR via
OpenCV dnn_superres) to sharpen the face before passing to Higgsfield.
Falls back to Lanczos 2x if the SR model is unavailable.

Uses MediaPipe Face Landmarker (eye blink + sharpness) and
Hand Landmarker (hand-on-face detection).
"""
import subprocess
import os
import glob
import shutil
import requests
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
from config import RAW_MATERIAL_DIR, EXTRACTED_FRAMES_DIR

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
FACE_MODEL_PATH = os.path.join(BASE_DIR, "face_landmarker.task")
HAND_MODEL_PATH = os.path.join(BASE_DIR, "hand_landmarker.task")
SR_MODEL_PATH   = os.path.join(BASE_DIR, "EDSR_x2.pb")

HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
SR_MODEL_URL = (
    "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x2.pb"
)

EYE_OPEN_THRESHOLD  = 0.35   # blendshape score: 0 = open, 1 = closed
MIN_FACE_SHARP      = 15.0
# How far outside the face bbox a hand landmark still counts as "on face"
HAND_FACE_MARGIN    = 0.08   # fraction of image size


# ── Model setup ───────────────────────────────────────────────────────────────

def _download(url, dest, label):
    print(f"  Downloading {label}...")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)
    size_mb = os.path.getsize(dest) / 1_000_000
    print(f"  Saved: {os.path.basename(dest)} ({size_mb:.1f} MB)")


def ensure_hand_model():
    if not os.path.exists(HAND_MODEL_PATH):
        _download(HAND_MODEL_URL, HAND_MODEL_PATH, "hand landmarker model (~25 MB)")


def ensure_sr_model():
    if not os.path.exists(SR_MODEL_PATH):
        _download(SR_MODEL_URL, SR_MODEL_PATH, "EDSR super-resolution model (~14 MB)")


def build_face_landmarker():
    options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=FACE_MODEL_PATH),
        output_face_blendshapes=True,
        num_faces=1,
        min_face_detection_confidence=0.4,
        min_face_presence_confidence=0.4,
        min_tracking_confidence=0.4,
    )
    return mp_vision.FaceLandmarker.create_from_options(options)


def build_hand_landmarker():
    options = mp_vision.HandLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=HAND_MODEL_PATH),
        num_hands=2,
        min_hand_detection_confidence=0.3,
        min_hand_presence_confidence=0.3,
        min_tracking_confidence=0.3,
    )
    return mp_vision.HandLandmarker.create_from_options(options)


# ── Per-frame analysis ────────────────────────────────────────────────────────

def face_sharpness(img, landmarks, w, h):
    if not landmarks:
        return 0.0
    xs = [int(l.x * w) for l in landmarks]
    ys = [int(l.y * h) for l in landmarks]
    x1 = max(min(xs) - 10, 0);  x2 = min(max(xs) + 10, w)
    y1 = max(min(ys) - 10, 0);  y2 = min(max(ys) + 10, h)
    crop = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(crop, cv2.CV_64F).var()


def hand_covers_face(face_result, hand_result):
    """
    Returns True if any detected hand landmark falls inside (or close to)
    the face bounding box.
    """
    if not hand_result.hand_landmarks:
        return False
    if not face_result.face_landmarks:
        return False

    face_lms = face_result.face_landmarks[0]
    xs = [l.x for l in face_lms]
    ys = [l.y for l in face_lms]
    fx1 = min(xs) - HAND_FACE_MARGIN
    fx2 = max(xs) + HAND_FACE_MARGIN
    fy1 = min(ys) - HAND_FACE_MARGIN
    fy2 = max(ys) + HAND_FACE_MARGIN

    for hand_lms in hand_result.hand_landmarks:
        for lm in hand_lms:
            if fx1 <= lm.x <= fx2 and fy1 <= lm.y <= fy2:
                return True
    return False


def analyze_frame(img, face_lmk, hand_lmk):
    """
    Returns (eyes_open, blink_score, sharpness, hand_on_face).
    """
    h, w = img.shape[:2]
    rgb    = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

    face_result = face_lmk.detect(mp_img)
    hand_result = hand_lmk.detect(mp_img)

    if not face_result.face_landmarks or not face_result.face_blendshapes:
        return False, 1.0, 0.0, False

    blendshapes = {b.category_name: b.score for b in face_result.face_blendshapes[0]}
    blink_left  = blendshapes.get("eyeBlinkLeft",  1.0)
    blink_right = blendshapes.get("eyeBlinkRight", 1.0)
    avg_blink   = (blink_left + blink_right) / 2.0
    eyes_open   = avg_blink < EYE_OPEN_THRESHOLD

    sharp      = face_sharpness(img, face_result.face_landmarks[0], w, h)
    obstructed = hand_covers_face(face_result, hand_result)

    return eyes_open, avg_blink, sharp, obstructed


# ── Super-resolution upscale ─────────────────────────────────────────────────

def upscale_frame(img):
    """
    Apply 2x AI super-resolution using EDSR.
    Falls back to Lanczos 2x if the SR model fails for any reason.
    """
    try:
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(SR_MODEL_PATH)
        sr.setModel("edsr", 2)
        upscaled = sr.upsample(img)
        h, w = upscaled.shape[:2]
        print(f"  Upscaled: {img.shape[1]}x{img.shape[0]} → {w}x{h} (EDSR 2x)")
        return upscaled
    except Exception as e:
        print(f"  EDSR failed ({e}) — falling back to Lanczos 2x")
        h, w = img.shape[:2]
        return cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_LANCZOS4)


# ── Frame extraction ──────────────────────────────────────────────────────────

def extract_candidates(video_path, tmp_dir, n=120):
    os.makedirs(tmp_dir, exist_ok=True)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", video_path],
        capture_output=True, text=True
    )
    duration = float(result.stdout.strip())
    start  = duration * 0.05
    length = duration * 0.90

    subprocess.run([
        "ffmpeg", "-y",
        "-ss", str(start), "-t", str(length),
        "-i", video_path,
        "-vf", f"fps={n}/{length},scale=1080:-1",
        "-frames:v", str(n),
        os.path.join(tmp_dir, "frame_%04d.png")
    ], capture_output=True)


def pick_best_frame(tmp_dir, face_lmk, hand_lmk):
    candidates = sorted(glob.glob(os.path.join(tmp_dir, "*.png")))
    if not candidates:
        return None, "no frames"

    scored = []
    for path in candidates:
        img = cv2.imread(path)
        if img is None:
            continue
        eyes_open, blink, sharp, obstructed = analyze_frame(img, face_lmk, hand_lmk)
        scored.append((path, eyes_open, blink, sharp, obstructed))

    clean   = [(p, o, b, s) for p, o, b, s, obs in scored if not obs]
    all_frm = [(p, o, b, s) for p, o, b, s, obs in scored]

    def best_open_sharp(pool):
        frames = [(p, b, s) for p, o, b, s in pool if o and s >= MIN_FACE_SHARP]
        return min(frames, key=lambda x: x[1]) if frames else None

    def best_open(pool):
        frames = [(p, b, s) for p, o, b, s in pool if o]
        return min(frames, key=lambda x: x[1]) if frames else None

    def sharpest(pool):
        frames = [(p, b, s) for p, o, b, s in pool if s > 0]
        return max(frames, key=lambda x: x[2]) if frames else None

    tiers = [
        (best_open_sharp(clean),   "clean face + eyes open + sharp"),
        (best_open(clean),         "clean face + eyes open"),
        (sharpest(clean),          "clean face + sharpest"),
        (best_open_sharp(all_frm), "eyes open + sharp (hand may be present)"),
        (best_open(all_frm),       "eyes open (hand may be present)"),
        (sharpest(all_frm),        "last resort: sharpest face"),
    ]

    for result, label in tiers:
        if result:
            p, b, s = result
            obs_tag = " [WARNING: hand detected on face]" if label.endswith("hand may be present)") else ""
            print(f"  Best frame: {os.path.basename(p)} | {label}{obs_tag}")
            print(f"  blink={b:.3f}  sharpness={s:.1f}  clean_frames={len(clean)}/{len(scored)}")
            return p, label

    return candidates[0], "absolute last resort"


# ── Main ──────────────────────────────────────────────────────────────────────

def extract_all():
    ensure_hand_model()
    ensure_sr_model()
    os.makedirs(EXTRACTED_FRAMES_DIR, exist_ok=True)

    videos = sorted(glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")))
    if not videos:
        print("No .mp4 files found in raw material/")
        return

    face_lmk = build_face_landmarker()
    hand_lmk = build_hand_landmarker()

    for video_path in videos:
        name    = os.path.splitext(os.path.basename(video_path))[0]
        out     = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
        tmp_dir = os.path.join(EXTRACTED_FRAMES_DIR, f"_tmp_{name}")

        if os.path.exists(out):
            print(f"[SKIP] {name}: frame already extracted.")
            continue

        print(f"\nProcessing: {os.path.basename(video_path)}")
        extract_candidates(video_path, tmp_dir)
        best_path, label = pick_best_frame(tmp_dir, face_lmk, hand_lmk)

        if best_path:
            img = cv2.imread(best_path)
            upscaled = upscale_frame(img)
            cv2.imwrite(out, upscaled)
            print(f"  Saved → extracted frames/{name}_frame.png")
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\nDone. {len(videos)} video(s) processed.")


if __name__ == "__main__":
    extract_all()
