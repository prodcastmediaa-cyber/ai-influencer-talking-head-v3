"""
v7 — Soul V2 + Claude Vision (Scar architecture)
System prompt bakes in the full template. Claude fills in scene. Response used directly.
"""
import subprocess
import os
import json
import glob
import base64
import io
import logging
import requests
import concurrent.futures
import anthropic
from PIL import Image
from config import (
    MIA_SOUL_ID,
    CHARACTER_HAIR,
    SKIN_STYLE,
    CLAUDE_API_KEY,
    EXTRACTED_FRAMES_DIR,
    OUTPUTS_DIR,
)

log = logging.getLogger(__name__)

MODEL       = "text2image_soul_v2"
ASPECT      = "9:16"
RESOLUTION  = "2k"
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

_HAIR = HAIR_PRESETS.get(CHARACTER_HAIR, HAIR_PRESETS["jet_black"])
_SKIN = SKIN_PRESETS.get(SKIN_STYLE, SKIN_PRESETS["realistic"])

_EXTRA = (
    "use reference soul character strictly, preserve exact face, skin tone, facial proportions and identity, "
    f"natural skin texture, {_SKIN}, soft glam makeup, subtle eyeliner, light blush, soft nude lips, "
    "realistic human details, no tattoos, avoid plastic or overly shiny skin, natural asymmetry preserved"
)

SYSTEM_PROMPT = f"""You write image generation prompts for Higgsfield AI.
Given a scene image, describe it using EXACTLY this structure — nothing else:

Pose:
[person's exact body position, posture, expression and eye contact]

Environment:
[exact location, background details, lighting quality, time of day, color mood, atmosphere]

Clothing:
[describe exactly what the person is wearing — every garment, color, style], {_HAIR}

Camera:
[shot type, angle, lens feel, depth of field], smartphone camera feel, slight telephoto look

Extra:
{_EXTRA}

Rules:
- Be specific about every piece of clothing — exact colors, garment names, style
- Never add extra sections or commentary
- Always keep the Clothing line ending with the hair description exactly as given
- Always keep the Extra section exactly as given"""


def _compress_for_api(frame_path: str, max_bytes: int = 4 * 1024 * 1024) -> tuple:
    img = Image.open(frame_path).convert("RGB")
    for quality in (85, 70, 55, 40):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data, "image/jpeg"
    # Still too large — halve resolution and retry
    w, h = img.size
    img = img.resize((w // 2, h // 2), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue(), "image/jpeg"


def frame_to_prompt(frame_path: str) -> str:
    img_bytes, media_type = _compress_for_api(frame_path)
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
    log.info(f"[claude] Sending frame ({len(img_bytes)//1024} KB) to Claude Vision")

    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": img_b64},
                    },
                    {
                        "type": "text",
                        "text": "Write the Higgsfield prompt for this scene.",
                    },
                ],
            }],
        )
    except Exception as e:
        err = str(e).lower()
        if "credit" in err or "billing" in err or "quota" in err or "insufficient" in err or "overloaded" in err or "rate" in err:
            raise RuntimeError("OUT_OF_CREDITS:Claude")
        raise

    prompt = response.content[0].text.strip()
    log.info(f"[claude] Prompt:\n{prompt}")
    return prompt


def run_generation(prompt, output_dir, index):
    log.info(f"[hf job {index+1}/{NUM_OUTPUTS}] Submitting")

    result = subprocess.run(
        [
            "higgsfield", "generate", "create", MODEL,
            "--custom_reference_id", MIA_SOUL_ID,
            "--prompt", prompt,
            "--aspect_ratio", ASPECT,
            "--quality", RESOLUTION,
            "--wait",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    if result.returncode != 0:
        err = (result.stderr.strip() or result.stdout.strip())[:400]
        log.error(f"[hf job {index+1}] CLI error (exit {result.returncode}): {err}")
        if "not authenticated" in err.lower() or "auth login" in err.lower():
            raise RuntimeError(f"Higgsfield not authenticated — run: higgsfield auth login\n{err}")
        if "credit" in err.lower() or "insufficient" in err.lower() or "balance" in err.lower() or "out of credit" in err.lower():
            raise RuntimeError("OUT_OF_CREDITS:Higgsfield")
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
            log.error(f"[hf job {index+1}] No URL — status={data.get('status','unknown')}")
            return None
    except json.JSONDecodeError:
        for line in result.stdout.splitlines():
            if line.strip().startswith("http"):
                url = line.strip()
                break
        else:
            log.error(f"[hf job {index+1}] Could not parse output: {result.stdout[:300]}")
            return None

    out_path = os.path.join(output_dir, f"output_{index+1}.png")
    log.info(f"[hf job {index+1}] Downloading → {os.path.basename(out_path)}")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)

    log.info(f"[hf job {index+1}] Saved: {out_path}")
    return out_path


def generate_for_video(frame_path, on_progress=None):
    video_name = os.path.basename(frame_path).replace("_frame.png", "")
    output_dir = os.path.join(OUTPUTS_DIR, "higgsfield", video_name)

    existing = glob.glob(os.path.join(output_dir, "output_*.png"))
    if existing:
        log.info(f"[SKIP] {video_name}: {len(existing)} image(s) already generated.")
        return sorted(existing)

    os.makedirs(output_dir, exist_ok=True)

    log.info(f"[hf] Analyzing frame with Claude Vision: {video_name}")
    prompt = frame_to_prompt(frame_path)

    log.info(f"[hf] Submitting {NUM_OUTPUTS} jobs — soul={MIA_SOUL_ID} model={MODEL}")

    saved = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_OUTPUTS) as ex:
        futures = {
            ex.submit(run_generation, prompt, output_dir, i): i
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

    log.info(f"[hf] Done: {len(saved)}/{NUM_OUTPUTS} saved to {output_dir}")
    if not saved:
        raise RuntimeError("All 4 Higgsfield jobs failed — check terminal for the actual error")
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
