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
        "natural skin pores visible, realistic skin micro-texture, "
        "candid photography skin detail, human skin depth, no retouching, "
        "natural healthy skin glow"
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
    "use soul character reference strictly — match exact face and facial identity, "
    "fair light skin tone, warm peachy-beige complexion, do not darken or alter skin colour, "
    f"natural skin texture, {_SKIN}, "
    "soft glam makeup, subtle eyeliner, light blush, soft nude lips, "
    "smooth clean unmarked skin — zero tattoos, zero ink, zero body art, zero skin markings of any kind, "
    "photorealistic, shot on camera, not CGI, not illustrated, not AI-generated looking, "
    "realistic human proportions and natural asymmetry, avoid plastic or waxy skin"
)

_EXTRA_SINGLE_PORTRAIT = (
    "SINGLE FULL-FRAME PORTRAIT PHOTOGRAPH — one person, one scene, full bleed, "
    "NOT a grid, NOT a collage, NOT a catalog page, NOT a lookbook, NOT a mood board, "
    "NOT multiple images side by side, NOT a social media screenshot, "
    "NO tiled panels, NO borders between images, NO caption text, NO watermarks, NO labels, "
    "one uninterrupted photograph filling the entire frame, "
    + _EXTRA
)

SYSTEM_PROMPT = f"""You write image generation prompts for Higgsfield AI.
The output character is a specific AI model — her face, hair, and skin are fixed by a soul reference. Your job is to describe the SCENE only: what the person is doing, where they are, what they are wearing, and how the camera is framed. Do NOT describe who the person looks like.

Given a scene image, describe it using EXACTLY this structure — nothing else:

Pose:
[exact body position, posture, gesture, expression and eye direction — end with: smooth clean unmarked skin, no tattoos]

Environment:
[exact location, background details, lighting quality, time of day, color mood, atmosphere]

Clothing:
[every garment the person is wearing — exact colors, garment names, style — clothing only, no hair], {_HAIR}

Camera:
[shot type, angle, lens feel, depth of field], shot on iPhone, candid natural light, photorealistic, slight telephoto compression, soft background bokeh

Extra:
{_EXTRA}

Rules:
- Pose describes body and movement ONLY — never mention hair color, skin color, face, or ethnicity of the person in the image — always end the Pose line with: smooth clean unmarked skin, no tattoos
- Clothing describes garments ONLY — never mention hair in the clothing description, the hair line at the end handles it
- Never reference the appearance of the person in the source image — only their pose, outfit, and scene
- Be specific about every garment — exact colors, names, style
- Never add extra sections or commentary
- Always end the Clothing line with the hair description exactly as given
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


def frame_to_prompt(frame_path: str, _attempt: int = 1) -> str:
    img_bytes, media_type = _compress_for_api(frame_path)
    img_b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
    log.info(f"[claude] Sending frame ({len(img_bytes)//1024} KB) to Claude Vision (attempt {_attempt})")

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
                        "text": "Describe this scene using the required format.",
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
    low = prompt.lower()
    refused = (
        ("i can't" in low or "i cannot" in low or "unable to" in low or "not able to" in low)
        and "Pose:" not in prompt
    )
    if refused:
        if _attempt < 3:
            log.warning(f"[claude] Soft refusal on attempt {_attempt} — retrying...")
            return frame_to_prompt(frame_path, _attempt=_attempt + 1)
        raise RuntimeError(f"CLAUDE_REFUSED: {prompt[:120]}")
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
    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)

    log.info(f"[hf job {index+1}] Saved: {out_path}")
    return out_path


AI_SYSTEM_PROMPT = f"""You are a creative director generating photoshoot scene prompts for a lifestyle AI model.

The character's face, hair, and skin are locked by a soul reference — describe ONLY the scene, pose, clothing, and environment. Never describe the person's appearance.

Generate ONE unique scene using EXACTLY this structure — nothing else:

Pose:
[natural body position, posture, gesture, expression, eye direction — specific and candid, not editorial]

Environment:
[specific location with vivid details — lighting, time of day, atmosphere, background elements]

Clothing:
[exact garments — specific colors, garment names, fit], {_HAIR}

Camera:
[shot type, angle, framing], shot on iPhone, candid natural light, photorealistic, slight telephoto compression, soft background bokeh

Extra:
{_EXTRA}

Rotate randomly through these scene categories each call:
Locations: rooftop pool, beach shoreline, yacht deck, tropical resort pool, ocean shallows, city rooftop terrace, café exterior, hotel balcony, private garden, pier or dock, beachside bar, luxury villa
Outfits: string bikini, triangle bikini, bandeau bikini, tie-side bikini, cutout one-piece swimsuit, strapless one-piece, crop top with mini shorts, fitted sundress, linen co-ord set, going-out mini dress, cami top with high-waisted jeans — always specific colors
Poses: leaning against pool edge, standing in shallow water, lying on sun lounger, standing on yacht, sitting on shoreline sand, walking along beach, leaning on railing, sitting at outdoor table, lying on towel, standing in doorway

Rules:
- Always end the Clothing line with the hair description exactly as given
- Always keep the Extra section exactly as given
- Never mention face, skin colour, ethnicity, or hair in Pose or Environment
- Camera line always ends with the full camera description exactly as given
- Poses must be natural and relaxed — never stiff, never editorial, never overly posed
- Be specific: exact colors, exact garment names, exact environment details
- Every call must produce a different scene — vary location, outfit, and pose each time"""


DAILY_BATCH_SYSTEM_PROMPT = f"""You are a creative director generating photoshoot scene prompts for a lifestyle AI model.

The character's face, hair, and skin are locked by a soul reference — describe ONLY the scene, pose, clothing, and environment. Never describe the person's appearance.

Generate ONE unique scene using EXACTLY this structure — nothing else:

Pose:
[natural body position, posture, gesture, expression, eye direction — specific and candid, not editorial — end with: smooth clean unmarked skin, no tattoos, no ink]

Environment:
[specific location with vivid details — lighting, time of day, atmosphere, background elements]

Clothing:
[exact garments — specific colors, garment names, fit], {_HAIR}

Camera:
[shot type, angle, framing], shot on iPhone, candid natural light, photorealistic, slight telephoto compression, soft background bokeh

Extra:
{_EXTRA}

Rotate randomly through these scene categories each call:
Locations: coffee shop interior, city street sidewalk, rooftop terrace, park bench, restaurant patio, hotel lobby, gym interior, shopping district, home kitchen, beach boardwalk, outdoor café, bookshop interior
Outfits: tight bodycon mini dress, strappy going-out mini dress, satin slip dress, cut-out club dress, fitted crop top + micro mini skirt, backless party dress, strapless bandeau mini dress, ruched mini dress, plunging neckline party dress, sequin mini dress, lace-up corset top + mini skirt — always short, fitted, and sexy, always a SPECIFIC color from this list: red, black, white, cobalt blue, forest green, burgundy, terracotta, cream, gold, coral, sage, navy
Poses: sitting at table with coffee, standing on street looking away, leaning on railing, walking and looking back, perched on bench, standing by window, resting elbows on counter, arms crossed leaning on wall, candid laugh, looking over shoulder

Rules:
- Always end the Clothing line with the hair description exactly as given
- Always keep the Extra section exactly as given
- Never mention face, skin colour, ethnicity, or hair in Pose or Environment
- Camera line always ends with the full camera description exactly as given
- Poses must be natural and relaxed — never stiff, never editorial
- Be specific: exact colors, exact garment names, exact environment details
- Every call must produce a different scene — vary location, outfit COLOR, and pose each time"""


FANVUE_BATCH_SYSTEM_PROMPT = f"""You are a creative director generating photoshoot scene prompts for an AI model's content platform.

The character's face, hair, and skin are locked by a soul reference — describe ONLY the scene, pose, clothing, and environment. Never describe the person's appearance.

Generate ONE unique scene using EXACTLY this structure — nothing else:

Pose:
[natural body position, posture, gesture, expression, eye direction — specific and candid, not editorial — end with: smooth clean unmarked skin, no tattoos, no ink]

Environment:
[specific indoor location — bedroom, bathroom, living room, or dressing room — specific details, natural window light, time of day]

Clothing:
[exact garment — specific colors, garment names, fit], {_HAIR}

Camera:
[shot type, angle, framing], shot on iPhone, candid natural light, photorealistic, slight telephoto compression, soft background bokeh

Extra:
{_EXTRA}

Rotate randomly through these scene categories each call:
Locations: sunlit apartment bedroom with white bedding, bathroom counter with natural morning light, bedroom doorway with warm afternoon light, dressing room with full-length mirror, living room window seat, hotel room with soft lamplight, reading chair by window, walk-in closet
Outfits: lace bralette + high-waist panties, triangle bikini top + thong, mesh teddy, satin slip chemise, cotton crop bralette + boyshorts, strapless bra + silk boxers, lace bodysuit, bandeau bra + seamless briefs — always a SPECIFIC color from this list: black, ivory, red, burgundy, sage green, navy, gold, cream, cobalt blue, forest green, white, coral
Poses: lying on bed looking at camera, sitting on bed edge leaning forward, standing by window looking over shoulder, leaning against wall, perched on vanity stool, lying on side with hand under chin, kneeling on bed, standing facing mirror

Rules:
- Always end the Clothing line with the hair description exactly as given
- Always keep the Extra section exactly as given
- Never mention face, skin colour, ethnicity, or hair in Pose or Environment
- Camera line always ends with the full camera description exactly as given
- Poses must be natural and candid — never stiff, never editorial, never overly posed
- Be specific: exact colors, exact garment names, exact environment details
- Every call must produce a different scene — vary location, outfit COLOR, and pose each time
- Environment must always be indoor — never outdoors"""


def generate_ai_prompt() -> str:
    """Call Claude text-only to invent a random lifestyle scene prompt for Mia."""
    log.info("[claude] Generating AI prompt (no reference image)")
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    for attempt in range(1, 4):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=600,
                system=AI_SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": "Generate a new random scene prompt.",
                }],
            )
        except Exception as e:
            err = str(e).lower()
            if "credit" in err or "billing" in err or "quota" in err or "insufficient" in err or "overloaded" in err or "rate" in err:
                raise RuntimeError("OUT_OF_CREDITS:Claude")
            raise

        prompt = response.content[0].text.strip()
        low = prompt.lower()
        refused = (
            ("i can't" in low or "i cannot" in low or "unable to" in low or "not able to" in low)
            and "Pose:" not in prompt
        )
        if refused:
            log.warning(f"[claude] AI prompt soft refusal on attempt {attempt} — retrying...")
            continue

        log.info(f"[claude] AI prompt generated:\n{prompt}")
        return prompt

    raise RuntimeError("CLAUDE_REFUSED: AI prompt generation refused after 3 attempts")


def generate_ai_for_video(name: str, output_dir: str, on_progress=None):
    """Generate 4 images using a Claude-invented scene — no reference frame needed."""
    existing = glob.glob(os.path.join(output_dir, "output_*.png"))
    if existing:
        log.info(f"[SKIP] {name}: {len(existing)} image(s) already generated.")
        return sorted(existing)

    os.makedirs(output_dir, exist_ok=True)

    prompt = generate_ai_prompt()
    log.info(f"[hf] Submitting {NUM_OUTPUTS} AI prompt jobs — soul={MIA_SOUL_ID} model={MODEL}")

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
        raise RuntimeError("All 4 Higgsfield AI jobs failed — check terminal for the actual error")
    return sorted(saved)


def generate_batch_prompts(style: str, num_prompts: int) -> list:
    """Generate num_prompts unique scene prompts via individual Claude calls."""
    system = DAILY_BATCH_SYSTEM_PROMPT if style == "daily" else FANVUE_BATCH_SYSTEM_PROMPT
    log.info(f"[claude] Generating {num_prompts} prompts individually — style={style}")
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)

    prompts = []
    previous = []
    for i in range(num_prompts):
        avoid = "; ".join(previous[-3:]) if previous else "none"
        for attempt in range(1, 4):
            try:
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=700,
                    system=system,
                    messages=[{
                        "role": "user",
                        "content": (
                            "Generate 1 unique scene prompt. "
                            f"Do NOT repeat any of these outfits or locations: {avoid}"
                        ),
                    }],
                )
                break
            except Exception as e:
                err = str(e).lower()
                if "credit" in err or "billing" in err or "quota" in err or "insufficient" in err:
                    raise RuntimeError("OUT_OF_CREDITS:Claude")
                if attempt == 3:
                    raise
        p = response.content[0].text.strip()
        prompts.append(p)
        previous.append(p[:120])
        log.info(f"[claude] Prompt {i + 1}/{num_prompts} ready")

    return prompts


def generate_ai_batch(name: str, output_dir: str, style: str, num_sets: int, on_progress=None) -> list:
    """Generate num_sets*2 images using unique Claude-invented scenes (2 images per scene)."""
    total = num_sets * 2
    existing = glob.glob(os.path.join(output_dir, "output_*.png"))
    if len(existing) == total:
        log.info(f"[SKIP] {name}: {len(existing)} batch images already generated.")
        return sorted(existing)

    os.makedirs(output_dir, exist_ok=True)

    prompts = generate_batch_prompts(style, num_sets)
    log.info(f"[hf] Submitting {total} batch jobs ({num_sets} scenes × 2 sequentially) — soul={MIA_SOUL_ID}")

    saved = []
    for set_idx, prompt in enumerate(prompts):
        base_idx = set_idx * 2
        final_prompt = prompt
        log.info(f"[hf batch] Scene {set_idx + 1}/{num_sets} — submitting 2 jobs")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            futures = {
                ex.submit(run_generation, final_prompt, output_dir, base_idx + img_idx): img_idx
                for img_idx in range(2)
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

    log.info(f"[hf batch] Done: {len(saved)}/{total} saved to {output_dir}")
    if not saved:
        raise RuntimeError(f"All {total} Higgsfield batch jobs failed — check terminal for the actual error")
    return sorted(saved)


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


NBP_PROMPT = (
    "Use reference image 1 for the face structure, skin color, skin tone, hair, and identity. "
    "Use Reference image 2 as the complete reference for clothing, pose, action scene composition, "
    "background environment, lighting setup and overall atmosphere. "
    "Do not use face structure, skin tone, hair, and identity from image 2."
)

_FACE_REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "character sheet mia", "mia-face.png")


def run_nbp_generation(face_path: str, frame_path: str, output_dir: str, index: int):
    log.info(f"[nbp job {index+1}/{NUM_OUTPUTS}] Submitting")
    out_path = os.path.join(output_dir, f"output_{index + 1}.png")

    result = subprocess.run(
        [
            "higgsfield", "generate", "create", "nano_banana_2",
            "--image", face_path,
            "--image", frame_path,
            "--prompt", NBP_PROMPT,
            "--aspect_ratio", ASPECT,
            "--resolution", "2k",
            "--wait",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    if result.returncode != 0:
        err = (result.stderr.strip() or result.stdout.strip())[:400]
        log.error(f"[nbp job {index+1}] CLI error (exit {result.returncode}): {err}")
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
            log.error(f"[nbp job {index+1}] No URL — status={data.get('status','unknown')}")
            return None
    except json.JSONDecodeError:
        for line in result.stdout.splitlines():
            if line.strip().startswith("http"):
                url = line.strip()
                break
        else:
            log.error(f"[nbp job {index+1}] JSON parse failed: {result.stdout[:200]}")
            return None

    log.info(f"[nbp job {index+1}] Downloading → {os.path.basename(out_path)}")
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(r.content)

    log.info(f"[nbp job {index+1}] Saved: {out_path}")
    return out_path


def generate_nbp_for_video(frame_path: str, on_progress=None):
    video_name = os.path.basename(frame_path).replace("_frame.png", "")
    output_dir = os.path.join(OUTPUTS_DIR, "higgsfield", video_name)

    existing = glob.glob(os.path.join(output_dir, "output_*.png"))
    if existing:
        log.info(f"[SKIP] {video_name}: {len(existing)} image(s) already generated.")
        return sorted(existing)

    os.makedirs(output_dir, exist_ok=True)

    if not os.path.exists(_FACE_REF):
        raise RuntimeError(f"Face reference not found: {_FACE_REF}")

    log.info(f"[nbp] Submitting {NUM_OUTPUTS} jobs — model=nano_banana_pro")

    saved = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_OUTPUTS) as ex:
        futures = {
            ex.submit(run_nbp_generation, _FACE_REF, frame_path, output_dir, i): i
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

    log.info(f"[nbp] Done: {len(saved)}/{NUM_OUTPUTS} saved to {output_dir}")
    if not saved:
        raise RuntimeError("All 4 NBP jobs failed — check terminal for the actual error")
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
