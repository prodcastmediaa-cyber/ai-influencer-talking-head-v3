"""
24/7 AI Influencer pipeline daemon — cloud edition.

Input via Telegram:
  • Paste a TikTok / Instagram / YouTube URL → downloaded automatically
  • Send a video file (up to 20 MB) → saved automatically

Pipeline:
  Step 1 — Extract best face frame
  Step 2 — You approve the frame (or retry for a different one)
  Step 3 — Higgsfield generates 4 images  (live progress bar)
  Step 4 — You pick the best image
  Step 5 — Wavespeed generates the final video
  Step 6 — Video sent to Telegram + uploaded to Google Drive

Commands:
  /start   — confirm the bot is live
  /status  — see every video and its current stage
  /help    — list all commands and buttons
"""
import asyncio
import atexit
import functools
import glob
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)
from telegram.request import HTTPXRequest

# Persistent bottom menu — always visible in the chat input area
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        ["▶️ Start / Scan Queue", "📊 Status"],
        ["🔄 Hard Restart",       "🗑 Clean All"],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="Paste a TikTok / Instagram / YouTube link...",
)
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from config import (
    EXTRACTED_FRAMES_DIR,
    OUTPUTS_DIR,
    RAW_MATERIAL_DIR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

try:
    import drive_upload as _drive
    _DRIVE_ENABLED = True
except Exception:
    _DRIVE_ENABLED = False

# ── Logging ───────────────────────────────────────────────────────────────────

_log_handlers = [logging.FileHandler("watcher.log")]
if sys.stderr.isatty():
    # Only add console output when running interactively (not as a daemon)
    _log_handlers.append(logging.StreamHandler())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_log_handlers,
)
log = logging.getLogger(__name__)

# Suppress httpx/telegram network logs — they log the full API URL which
# contains the bot token in plaintext on every request.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)

# ── Single-instance lock ──────────────────────────────────────────────────────

_PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".watcher.pid")


def _acquire_pid_lock() -> None:
    """Kill any running instance, then write our PID. Runs before anything else."""
    if os.path.exists(_PID_FILE):
        try:
            with open(_PID_FILE) as f:
                old_pid = int(f.read().strip())
            if old_pid != os.getpid():
                log.info(f"[pid] Found old instance (PID {old_pid}) — stopping it...")
                try:
                    os.kill(old_pid, signal.SIGTERM)
                except ProcessLookupError:
                    old_pid = None
                if old_pid:
                    # Poll until the process is actually gone (up to 5s graceful)
                    for _ in range(10):
                        try:
                            os.kill(old_pid, 0)
                            time.sleep(0.5)
                        except ProcessLookupError:
                            old_pid = None
                            break
                    # Force-kill if still alive after graceful window
                    if old_pid:
                        try:
                            os.kill(old_pid, signal.SIGKILL)
                            time.sleep(1)
                        except ProcessLookupError:
                            pass
                log.info("[pid] Old instance stopped.")
        except (ValueError, OSError):
            pass

    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    def _remove_pid():
        try:
            os.remove(_PID_FILE)
        except FileNotFoundError:
            pass

    atexit.register(_remove_pid)

# ── Globals ───────────────────────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=2)
_processing: set = set()      # names currently running through the pipeline
_cancelled: set = set()       # names marked for cancellation
_retry_counts: dict = {}
_stage: dict = {}             # name → human-readable current stage string
_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop = None
_app: Application = None

_pending_mode: set = set()    # names waiting for Clone / Talking Head selection
_awaiting_script: dict = {}   # chat_id → name  (waiting for script text from user)
_selected_mode: str = None    # "clone" or "ugc" — pre-selected before video arrives
_awaiting_ref_image: dict = {}    # chat_id → name  (waiting for reference image upload)
_make_images_names: set = set()   # names from Make Images flow — skip Wavespeed on pick
_ai_prompt_names: set = set()     # names using AI Prompting mode (no frame file)
_ai_create_style_pending: dict = {}   # chat_id → name (waiting for Daily/Fanvue choice)
_ai_create_count_pending: dict = {}   # chat_id → (name, style) (waiting for 2/4/6/8 choice)
_batch_config: dict = {}              # name → {"style": str, "num_sets": int}


# ── State helpers ─────────────────────────────────────────────────────────────

def _vname(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]

def _has_output(name: str) -> bool:
    return os.path.exists(os.path.join(OUTPUTS_DIR, "wavespeed", name, "output.mp4"))

def _has_selected(name: str) -> bool:
    return os.path.exists(os.path.join(OUTPUTS_DIR, "higgsfield", name, "selected.png"))

def _has_higgsfield(name: str) -> bool:
    return bool(glob.glob(os.path.join(OUTPUTS_DIR, "higgsfield", name, "output_*.png")))

def _has_frame(name: str) -> bool:
    return os.path.exists(os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png"))

def _has_ugc_output(name: str) -> bool:
    return os.path.exists(os.path.join(OUTPUTS_DIR, "ugc", name, "output.mp4"))

def _higgsfield_images(name: str) -> list:
    return sorted(glob.glob(os.path.join(OUTPUTS_DIR, "higgsfield", name, "output_*.png")))


# ── Mode selection ────────────────────────────────────────────────────────────

def _next_ugc_name() -> str:
    existing = glob.glob(os.path.join(OUTPUTS_DIR, "ugc", "ugc*"))
    nums = []
    for d in existing:
        stem = os.path.basename(d)
        if stem.startswith("ugc") and stem[3:].isdigit():
            nums.append(int(stem[3:]))
    return f"ugc{max(nums) + 1}" if nums else "ugc1"


def _next_make_images_name() -> str:
    existing = glob.glob(os.path.join(OUTPUTS_DIR, "higgsfield", "img*"))
    nums = []
    for d in existing:
        stem = os.path.basename(d)
        if stem.startswith("img") and stem[3:].isdigit():
            nums.append(int(stem[3:]))
    return f"img{max(nums) + 1}" if nums else "img1"


async def _send_mode_selection(reply_fn) -> None:
    """Show Clone / Talking Head / Make Images choice."""
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎭 Clone Video",  callback_data="preselect_clone"),
            InlineKeyboardButton("🎤 Talking Head", callback_data="preselect_ugc"),
        ],
        [
            InlineKeyboardButton("🖼 Make Images",  callback_data="preselect_make_images"),
        ],
    ])
    await reply_fn(
        "What do you want to make?\n\n"
        "🎭 *Clone Video* — Send a dance/reel link → swap identity with Mia\n"
        "🎤 *Talking Head* — Type a script → Mia delivers it direct to camera\n"
        "🖼 *Make Images* — Upload a reference image → generate 4 images with Mia",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _on_preselect_clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🧠 NBP",   callback_data="preselect_engine_nbp"),
        InlineKeyboardButton("🎭 SC2.0", callback_data="preselect_engine_sc2"),
    ]])
    await _safe_edit(
        query,
        "🎭 *Clone Video* — Choose generation engine:\n\n"
        "🧠 *NBP* — Nano Banana Pro (great for dancing / moving scenes)\n"
        "🎭 *SC2.0* — Soul Character 2.0 (bypasses NSFW, consistent identity)",
        keyboard=keyboard,
    )


async def _on_preselect_engine_sc2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _selected_mode
    query = update.callback_query
    await query.answer()
    _selected_mode = "clone_sc2"
    await _safe_edit(
        query,
        "🎭 *SC2.0 Clone* selected.\n\nNow paste a TikTok / Instagram / YouTube link, or send a video file.",
        keyboard=None,
    )


async def _on_preselect_engine_nbp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _selected_mode
    query = update.callback_query
    await query.answer()
    _selected_mode = "clone_nbp"
    await _safe_edit(
        query,
        "🧠 *NBP Clone* selected.\n\nNow paste a TikTok / Instagram / YouTube link, or send a video file.",
        keyboard=None,
    )


async def _on_preselect_ugc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    name = _next_ugc_name()
    _awaiting_script[TELEGRAM_CHAT_ID] = name
    await _safe_edit(
        query,
        "🎤 *Talking Head* — Send me the script and Mia will deliver it.\n\n"
        "_Just type or paste it in the chat._",
        keyboard=None,
    )


async def _on_preselect_make_images(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📸 Upload Image",  callback_data="make_img_upload"),
        InlineKeyboardButton("✨ Let AI Create", callback_data="make_img_ai_prompt"),
    ]])
    await _safe_edit(
        query,
        "🖼 *Make Images* — How do you want to create?\n\n"
        "📸 *Upload Image* — Send a reference photo → Mia replicates the scene\n"
        "✨ *Let AI Create* — AI invents a random scene for Mia",
        keyboard=keyboard,
    )


async def _on_make_img_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    name = _next_make_images_name()
    _awaiting_ref_image[TELEGRAM_CHAT_ID] = name
    _make_images_names.add(name)
    await _safe_edit(
        query,
        f"📸 *Upload Image* — *{name}* ready!\n\n"
        "Send a reference image (JPG, PNG, screenshot from Instagram/Pinterest) and Mia will be placed in the same scene.\n\n"
        "_Just send the photo here — no links needed._",
        keyboard=None,
    )


async def _on_make_img_ai_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    name = _next_make_images_name()
    _ai_create_style_pending[TELEGRAM_CHAT_ID] = name
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🌸 Daily Stuff",  callback_data="ai_create_style:daily"),
        InlineKeyboardButton("🔥 Fanvue Stuff", callback_data="ai_create_style:fanvue"),
    ]])
    await _safe_edit(
        query,
        "✨ *Let AI Create* — Pick a style:\n\n"
        "🌸 *Daily Stuff* — lifestyle scenes, cute/casual/party outfits, any environment\n"
        "🔥 *Fanvue Stuff* — teasing, intimate scenes, indoor only",
        keyboard=keyboard,
    )


async def _on_ai_create_style(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, style = query.data.split(":", 1)
    name = _ai_create_style_pending.pop(TELEGRAM_CHAT_ID, None)
    if not name:
        await _safe_edit(query, "⚠️ Session expired — tap *▶️ Start / Scan Queue* to begin again.", keyboard=None)
        return
    _ai_create_count_pending[TELEGRAM_CHAT_ID] = (name, style)
    style_label = "🌸 Daily Stuff" if style == "daily" else "🔥 Fanvue Stuff"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("2 scenes · 4 imgs",  callback_data="ai_create_count:2"),
            InlineKeyboardButton("4 scenes · 8 imgs",  callback_data="ai_create_count:4"),
        ],
        [
            InlineKeyboardButton("6 scenes · 12 imgs", callback_data="ai_create_count:6"),
            InlineKeyboardButton("8 scenes · 16 imgs", callback_data="ai_create_count:8"),
        ],
    ])
    await _safe_edit(
        query,
        f"✨ *{style_label}* — How many unique scenes?\n\nEach scene = 2 images with the same outfit. Every scene has a different look.",
        keyboard=keyboard,
    )


async def _on_ai_create_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, count_str = query.data.split(":", 1)
    count = int(count_str)
    pending = _ai_create_count_pending.pop(TELEGRAM_CHAT_ID, None)
    if not pending:
        await _safe_edit(query, "⚠️ Session expired — tap *▶️ Start / Scan Queue* to begin again.", keyboard=None)
        return
    name, style = pending
    num_sets = count
    total_imgs = num_sets * 2
    _make_images_names.add(name)
    _batch_config[name] = {"style": style, "num_sets": num_sets}
    style_label = "Daily Stuff" if style == "daily" else "Fanvue Stuff"
    await _safe_edit(
        query,
        f"✨ *{name}* — {count} scenes · {total_imgs} images total, generating now...",
        keyboard=None,
    )
    asyncio.create_task(_pipeline_make_images_ai_batch(name, style, num_sets))


async def _show_mode_popup(name: str) -> None:
    """After a video is received, ask: Clone Video or Talking Head?"""
    _pending_mode.add(name)
    _stage[name] = "⏸ Waiting for mode selection"
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎭 Clone Video",   callback_data=f"mode_clone:{name}"),
            InlineKeyboardButton("🎤 Talking Head",  callback_data=f"mode_ugc:{name}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{name}")],
    ])
    await _app.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=(
            f"📥 *{name}* — Video ready! What do you want to do?\n\n"
            f"🎭 *Clone Video* — Swap identity with Mia (existing pipeline)\n"
            f"🎤 *Talking Head* — Mia delivers a custom script in your words"
        ),
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _route_new_video(name: str) -> None:
    """Route a newly received video based on pre-selected mode (or show popup as fallback)."""
    global _selected_mode
    mode = _selected_mode
    _selected_mode = None

    if mode in ("clone", "clone_sc2"):
        await _notify(f"🎭 *{name}* — Starting SC2.0 clone pipeline...")
        asyncio.create_task(_pipeline(name, stable=True))
    elif mode == "clone_nbp":
        await _notify(f"🧠 *{name}* — Starting NBP clone pipeline...")
        asyncio.create_task(_pipeline_nbp(name, stable=True))
    elif mode == "ugc":
        _awaiting_script[TELEGRAM_CHAT_ID] = name
        _stage[name] = "⏸ Waiting for script"
        await _notify(
            f"🎤 *{name}* — Video received!\n\nSend me the script and Mia will deliver it."
        )
    else:
        await _show_mode_popup(name)


async def _on_new_video(name: str) -> None:
    """Watchdog handler: wait for file stability then route based on pre-selected mode."""
    global _selected_mode
    video_path = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")
    if not await _wait_until_stable(video_path):
        await _notify(f"❌ *{name}* — File not readable after waiting.")
        return

    # URL/upload handler already routed this video while we were waiting for stability
    if name in _pending_mode or name in _processing:
        return

    mode = _selected_mode
    _selected_mode = None  # consume it

    if mode in ("clone", "clone_sc2"):
        await _notify(f"🎭 *{name}* — Starting SC2.0 clone pipeline...")
        asyncio.create_task(_pipeline(name, stable=True))
    elif mode == "clone_nbp":
        await _notify(f"🧠 *{name}* — Starting NBP clone pipeline...")
        asyncio.create_task(_pipeline_nbp(name, stable=True))
    elif mode == "ugc":
        _awaiting_script[TELEGRAM_CHAT_ID] = name
        _stage[name] = "⏸ Waiting for script"
        await _notify(
            f"🎤 *{name}* — Video received!\n\nSend me the script and Mia will deliver it."
        )
    else:
        # No mode pre-selected — fall back to popup
        await _show_mode_popup(name)


# ── Telegram helpers ──────────────────────────────────────────────────────────

async def _notify(text: str) -> None:
    try:
        await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="Markdown"
        )
    except Exception as e:
        log.error(f"Telegram notify failed: {e}")


async def _safe_edit(query, text: str, keyboard=None) -> None:
    """Edit text or caption correctly depending on whether the message is a photo."""
    try:
        if query.message.photo:
            await query.edit_message_caption(
                caption=text, parse_mode="Markdown", reply_markup=keyboard
            )
        else:
            await query.edit_message_text(
                text=text, parse_mode="Markdown", reply_markup=keyboard
            )
    except Exception as e:
        log.warning(f"_safe_edit failed: {e}")


async def _send_failure_actions(name: str, reason: str) -> None:
    retries = _retry_counts.get(name, 0)
    if retries == 0:
        keyboard = [[InlineKeyboardButton("🔄 Retry", callback_data=f"retry:{name}")]]
        footer = "Tap *Retry* to try again."
    else:
        keyboard = [[InlineKeyboardButton("🗑 Delete Video", callback_data=f"delete_video:{name}")]]
        footer = "Retry failed again. Tap *Delete Video* to remove all files for this video."
    await _app.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=f"❌ *{name}* — {reason}\n\n{footer}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def _send_frame_approval(name: str) -> None:
    """Show the extracted frame and ask user to approve before spending Higgsfield credits."""
    frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Generate Images", callback_data=f"frame_approve:{name}"),
            InlineKeyboardButton("🔄 New Frame", callback_data=f"frame_retry:{name}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{name}")],
    ])
    with open(frame_path, "rb") as f:
        await _app.bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=f,
            caption=(
                f"🖼 *{name}* — Frame extracted!\n\n"
                "Does this look good?\n"
                "• *Generate Images* → start AI generation\n"
                "• *New Frame* → try a different frame\n"
                "• *Cancel* → stop processing"
            ),
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    _stage[name] = "⏸ Waiting for frame approval"


async def _send_selection_prompt(name: str) -> None:
    images = _higgsfield_images(name)
    if not images:
        return

    for i, path in enumerate(images, 1):
        with open(path, "rb") as f:
            await _app.bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=f,
                caption=f"`{name}` — Option {i}",
                parse_mode="Markdown",
            )

    keyboard = [
        [
            InlineKeyboardButton(f"✅ Pick {i}", callback_data=f"sel:{i}:{name}")
            for i in range(1, len(images) + 1)
        ],
        [
            InlineKeyboardButton("🔄 Restart Gen", callback_data=f"hf_restart:{name}"),
            InlineKeyboardButton("🖼 See Frame", callback_data=f"see_frame:{name}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{name}")],
    ]
    await _app.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=f"👆 *{name}* — Tap to pick the best one:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    _stage[name] = "👆 Waiting for image pick"


# ── Blocking pipeline steps (run in thread executor) ─────────────────────────

def _step1_extract(name: str) -> None:
    import cv2
    from extract_frame import (
        build_face_landmarker, build_hand_landmarker,
        ensure_hand_model, ensure_sr_model,
        extract_candidates, pick_best_frame, upscale_frame,
    )
    video_path = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")
    out = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    tmp_dir = os.path.join(EXTRACTED_FRAMES_DIR, f"_tmp_{name}")

    ensure_hand_model()
    ensure_sr_model()
    os.makedirs(EXTRACTED_FRAMES_DIR, exist_ok=True)

    face_lmk = build_face_landmarker()
    hand_lmk = build_hand_landmarker()
    extract_candidates(video_path, tmp_dir)
    best, _ = pick_best_frame(tmp_dir, face_lmk, hand_lmk)
    if best:
        img = cv2.imread(best)
        cv2.imwrite(out, upscale_frame(img))
    shutil.rmtree(tmp_dir, ignore_errors=True)


def _step2_higgsfield(name: str, on_progress=None) -> None:
    from higgsfield_generate import generate_for_video
    frame = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    generate_for_video(frame, on_progress=on_progress)


def _step2_higgsfield_ai(name: str, on_progress=None) -> None:
    from higgsfield_generate import generate_ai_for_video
    output_dir = os.path.join(OUTPUTS_DIR, "higgsfield", name)
    generate_ai_for_video(name, output_dir, on_progress=on_progress)


def _step2_nbp(name: str, on_progress=None) -> None:
    from higgsfield_generate import generate_nbp_for_video
    frame = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    generate_nbp_for_video(frame, on_progress=on_progress)


def _step4_wavespeed(name: str) -> str:
    from wavespeed_generate import process_video
    video_path = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")
    out_path = process_video(video_path)
    if out_path and os.path.exists(out_path):
        _reencode_for_telegram(out_path)
    return out_path


def _reencode_for_telegram(path: str) -> None:
    """Re-encode to CRF 23 so Telegram can stream it (Wavespeed outputs ~32 Mbps)."""
    tmp = path + ".tmp.mp4"
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", path,
         "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
         "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart",
         tmp],
        capture_output=True,
    )
    if result.returncode == 0:
        os.replace(tmp, path)
    else:
        try:
            os.remove(tmp)
        except OSError:
            pass
        log.warning(f"Re-encode failed (sending original): {result.stderr.decode()[-200:]}")


def _video_dimensions(path: str) -> tuple:
    import json
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration", "-of", "json", path],
        capture_output=True, text=True,
    )
    streams = json.loads(r.stdout).get("streams", [{}])
    s = streams[0] if streams else {}
    width    = s.get("width", 1080)
    height   = s.get("height", 1920)
    duration = max(1, int(float(s.get("duration", 1))))
    return width, height, duration


# ── File stability check ──────────────────────────────────────────────────────

async def _wait_until_stable(path: str) -> bool:
    prev = -1
    for _ in range(15):
        await asyncio.sleep(2)
        if not os.path.exists(path):
            continue
        size = os.path.getsize(path)
        if size == prev and size > 0:
            return True
        prev = size
    return os.path.exists(path) and os.path.getsize(path) > 0


# ── Sub-pipeline: frame extract (used by retry too) ──────────────────────────

async def _do_frame_extract(name: str) -> None:
    """Extract frame then auto-start Higgsfield generation."""
    loop = asyncio.get_running_loop()
    with _lock:
        _processing.add(name)
    _stage[name] = "📥 Extracting frame"
    await loop.run_in_executor(_executor, _step1_extract, name)

    if name in _cancelled:
        with _lock:
            _processing.discard(name)
        return

    if not _has_frame(name):
        await _notify(f"❌ *{name}* — Frame extraction failed. Check logs.")
        with _lock:
            _processing.discard(name)
        return

    asyncio.create_task(_do_higgsfield(name))


# ── Sub-pipeline: Higgsfield with live progress bar ──────────────────────────

async def _do_higgsfield(name: str) -> None:
    loop = asyncio.get_running_loop()

    if name in _cancelled:
        return

    cancel_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{name}")
    ]])

    try:
        progress_msg = await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"🎨 *{name}* — Generating images... [░░░░] 0/4",
            parse_mode="Markdown",
            reply_markup=cancel_kb,
        )
    except Exception as e:
        log.error(f"[{name}] Could not send Higgsfield progress message: {e}")
        with _lock:
            _processing.discard(name)
        return
    _stage[name] = "🎨 Generating images (0/4)"

    def _on_progress(count: int):
        if name in _cancelled:
            return
        bar = "▓" * count + "░" * (4 - count)
        _stage[name] = f"🎨 Generating images ({count}/4)"
        try:
            asyncio.run_coroutine_threadsafe(
                progress_msg.edit_text(
                    f"🎨 *{name}* — Generating images... [{bar}] {count}/4",
                    parse_mode="Markdown",
                    reply_markup=cancel_kb,
                ),
                _loop,
            ).result(timeout=10)
        except Exception:
            pass

    hf_error: str = ""
    try:
        step_fn = _step2_higgsfield_ai if name in _ai_prompt_names else _step2_higgsfield
        await loop.run_in_executor(_executor, step_fn, name, _on_progress)
    except Exception as e:
        hf_error = str(e)
        log.exception(f"[{name}] Higgsfield error")

    if name in _cancelled:
        return

    if not _has_higgsfield(name):
        # Surface the real error — auth failures were previously shown as "NSFW"
        if "OUT_OF_CREDITS:Higgsfield" in hf_error:
            reason = "💳 Out of Higgsfield credits. Please top it up → higgsfield.ai/billing"
        elif "OUT_OF_CREDITS:Claude" in hf_error:
            reason = "💳 Out of Claude credits. Please top it up → console.anthropic.com/billing"
        elif "CLAUDE_REFUSED" in hf_error:
            reason = "⚠️ Claude Vision refused this frame (content policy). Try a different video or skip to a cleaner scene."
        elif "not authenticated" in hf_error.lower() or "auth login" in hf_error.lower():
            reason = "Higgsfield CLI not authenticated. SSH into the VPS and run: `higgsfield auth login`"
        elif hf_error:
            reason = f"Higgsfield error: `{hf_error[:200]}`"
        else:
            reason = "All 4 Higgsfield jobs failed — check VPS journal: `journalctl -u ai-influencer -n 50`"
        try:
            await progress_msg.edit_text(
                f"❌ *{name}* — Image generation failed.",
                parse_mode="Markdown",
                reply_markup=None,
            )
        except Exception:
            pass
        await _send_failure_actions(name, reason)
        with _lock:
            _processing.discard(name)
        return

    try:
        await progress_msg.edit_text(
            f"✅ *{name}* — 4 images ready!",
            parse_mode="Markdown",
            reply_markup=None,
        )
    except Exception:
        pass

    try:
        if name in _make_images_names:
            await _send_make_images_result(name)
        else:
            await _send_selection_prompt(name)
    except Exception as e:
        log.exception(f"[{name}] Failed to send results to Telegram")
        await _notify(f"❌ *{name}* — Images ready but failed to send: `{str(e)[:200]}`")
        with _lock:
            _processing.discard(name)


async def _do_nbp(name: str) -> None:
    loop = asyncio.get_running_loop()

    if name in _cancelled:
        return

    cancel_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{name}")
    ]])

    try:
        progress_msg = await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"🧠 *{name}* — NBP generating images... [░░░░] 0/4",
            parse_mode="Markdown",
            reply_markup=cancel_kb,
        )
    except Exception as e:
        log.error(f"[{name}] Could not send NBP progress message: {e}")
        with _lock:
            _processing.discard(name)
        return
    _stage[name] = "🧠 NBP generating images (0/4)"

    def _on_progress(count: int):
        if name in _cancelled:
            return
        bar = "▓" * count + "░" * (4 - count)
        _stage[name] = f"🧠 NBP generating images ({count}/4)"
        try:
            asyncio.run_coroutine_threadsafe(
                progress_msg.edit_text(
                    f"🧠 *{name}* — NBP generating images... [{bar}] {count}/4",
                    parse_mode="Markdown",
                    reply_markup=cancel_kb,
                ),
                _loop,
            ).result(timeout=10)
        except Exception:
            pass

    nbp_error: str = ""
    try:
        await loop.run_in_executor(_executor, _step2_nbp, name, _on_progress)
    except Exception as e:
        nbp_error = str(e)
        log.exception(f"[{name}] NBP error")

    if name in _cancelled:
        return

    if not _has_higgsfield(name):
        if "OUT_OF_CREDITS:Higgsfield" in nbp_error:
            reason = "💳 Out of Higgsfield credits. Please top it up → higgsfield.ai/billing"
        elif "not authenticated" in nbp_error.lower() or "auth login" in nbp_error.lower():
            reason = "Higgsfield CLI not authenticated. SSH into the VPS and run: `higgsfield auth login`"
        elif nbp_error:
            reason = f"NBP error: `{nbp_error[:200]}`"
        else:
            reason = "All 4 NBP jobs failed — check VPS logs."
        try:
            await progress_msg.edit_text(
                f"❌ *{name}* — NBP image generation failed.",
                parse_mode="Markdown",
                reply_markup=None,
            )
        except Exception:
            pass
        await _send_failure_actions(name, reason)
        with _lock:
            _processing.discard(name)
        return

    try:
        await progress_msg.edit_text(
            f"✅ *{name}* — 4 NBP images ready! Choose the best one below.",
            parse_mode="Markdown",
            reply_markup=None,
        )
    except Exception:
        pass

    await _send_selection_prompt(name)


# ── Sub-pipeline: Wavespeed + Drive upload ────────────────────────────────────

async def _do_wavespeed(name: str, loop: asyncio.AbstractEventLoop = None) -> None:
    if loop is None:
        loop = asyncio.get_running_loop()
    _stage[name] = "⚡ Wavespeed running"
    try:
        await _notify(f"⚡ *{name}* — Running Wavespeed Kling...")
        out_path = await loop.run_in_executor(_executor, _step4_wavespeed, name)

        if out_path and os.path.exists(out_path):
            _retry_counts.pop(name, None)
            size_mb = os.path.getsize(out_path) / 1_000_000
            width, height, duration = _video_dimensions(out_path)
            await _notify(f"✅ *{name}* — Done! Uploading video ({size_mb:.1f} MB)...")
            voice_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🎙 Replace with Mia's Voice", callback_data=f"voice_replace:{name}")
            ]])
            with open(out_path, "rb") as f:
                await _app.bot.send_video(
                    chat_id=TELEGRAM_CHAT_ID,
                    video=f,
                    caption=f"🎬 *{name}*\n\nTap below to replace the audio with Mia's cloned voice.",
                    parse_mode="Markdown",
                    supports_streaming=True,
                    width=width,
                    height=height,
                    duration=duration,
                    reply_markup=voice_kb,
                )
            if _DRIVE_ENABLED:
                try:
                    drive_link = await loop.run_in_executor(
                        _executor, _drive.upload_video, out_path, name
                    )
                    await _notify(f"📁 *{name}* — [Open in Google Drive]({drive_link})")
                except Exception as drive_err:
                    log.warning(f"[{name}] Drive upload failed (non-fatal): {drive_err}")
            _stage[name] = "✅ Done"
        else:
            await _notify(f"⚠️ *{name}* — Wavespeed finished but no output found.")
    except Exception as e:
        log.exception(f"[{name}] Wavespeed error")
        err_str = str(e)
        if "OUT_OF_CREDITS:Wavespeed" in err_str:
            await _notify(f"💳 *{name}* — Out of Wavespeed credits. Please top it up → wavespeed.ai/billing")
        else:
            await _notify(f"❌ *{name}* — Wavespeed failed: `{e}`")
    finally:
        with _lock:
            _processing.discard(name)


# ── Core pipeline coroutine ───────────────────────────────────────────────────

async def _pipeline(name: str, stable: bool = False) -> None:
    with _lock:
        if name in _processing:
            log.info(f"[{name}] Already in progress — skipping duplicate.")
            return
        _processing.add(name)

    loop = asyncio.get_running_loop()
    try:
        video_path = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")

        if not stable and not await _wait_until_stable(video_path):
            await _notify(f"❌ *{name}* — File not readable after waiting.")
            with _lock:
                _processing.discard(name)
            return

        if name in _cancelled:
            with _lock:
                _processing.discard(name)
            return

        # Step 1 — extract best frame
        if not _has_frame(name):
            _stage[name] = "📥 Extracting frame"
            await _notify(f"📥 *{name}* — New video! Extracting best frame...")
            await loop.run_in_executor(_executor, _step1_extract, name)

            if name in _cancelled:
                with _lock:
                    _processing.discard(name)
                return
            if not _has_frame(name):
                await _notify(f"❌ *{name}* — Frame extraction failed. Check logs.")
                with _lock:
                    _processing.discard(name)
                return

        # Step 2 — auto-start Higgsfield (no frame approval gate)
        if not _has_higgsfield(name):
            if name in _cancelled:
                with _lock:
                    _processing.discard(name)
                return
            asyncio.create_task(_do_higgsfield(name))
            return

        # Step 3 — (startup resume: Higgsfield images exist but not picked yet)
        if not _has_selected(name):
            if name in _cancelled:
                with _lock:
                    _processing.discard(name)
                return
            await _send_selection_prompt(name)
            return

        # Step 4 — (startup resume: selected.png exists, run Wavespeed)
        await _do_wavespeed(name, loop)

    except Exception as e:
        log.exception(f"[{name}] Unexpected pipeline error")
        await _send_failure_actions(name, f"Pipeline error: `{e}`")
        with _lock:
            _processing.discard(name)


async def _pipeline_nbp(name: str, stable: bool = False) -> None:
    with _lock:
        if name in _processing:
            log.info(f"[{name}] Already in progress — skipping duplicate.")
            return
        _processing.add(name)

    loop = asyncio.get_running_loop()
    try:
        video_path = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")

        if not stable and not await _wait_until_stable(video_path):
            await _notify(f"❌ *{name}* — File not readable after waiting.")
            with _lock:
                _processing.discard(name)
            return

        if name in _cancelled:
            with _lock:
                _processing.discard(name)
            return

        # Step 1 — extract best frame
        if not _has_frame(name):
            _stage[name] = "📥 Extracting frame"
            await _notify(f"📥 *{name}* — Extracting best frame...")
            await loop.run_in_executor(_executor, _step1_extract, name)

            if name in _cancelled:
                with _lock:
                    _processing.discard(name)
                return
            if not _has_frame(name):
                await _notify(f"❌ *{name}* — Frame extraction failed. Check logs.")
                with _lock:
                    _processing.discard(name)
                return

        # Step 2 — NBP image generation
        if not _has_higgsfield(name):
            if name in _cancelled:
                with _lock:
                    _processing.discard(name)
                return
            asyncio.create_task(_do_nbp(name))
            return

        # Step 3 — images exist, show selection (startup resume)
        if not _has_selected(name):
            if name in _cancelled:
                with _lock:
                    _processing.discard(name)
                return
            await _send_selection_prompt(name)
            return

        # Step 4 — selected.png exists, run Wavespeed
        await _do_wavespeed(name, loop)

    except Exception as e:
        log.exception(f"[{name}] Unexpected NBP pipeline error")
        await _send_failure_actions(name, f"NBP pipeline error: `{e}`")
        with _lock:
            _processing.discard(name)


async def _pipeline_make_images(name: str) -> None:
    """Make Images flow: reference frame already saved, skip extraction, go straight to SC2.0."""
    with _lock:
        if name in _processing:
            log.info(f"[{name}] Already in progress — skipping duplicate.")
            return
        _processing.add(name)

    try:
        if not _has_frame(name):
            await _notify(f"❌ *{name}* — Reference frame not found. Please try again.")
            with _lock:
                _processing.discard(name)
            return
        asyncio.create_task(_do_higgsfield(name))
        # _processing stays active until user picks (released in _on_pick for make_images)
    except Exception as e:
        log.exception(f"[{name}] Make Images pipeline error")
        await _notify(f"❌ *{name}* — Make Images failed: `{e}`")
        with _lock:
            _processing.discard(name)


async def _pipeline_make_images_ai(name: str) -> None:
    """AI Prompting flow: no frame needed — Claude invents the scene."""
    with _lock:
        if name in _processing:
            log.info(f"[{name}] Already in progress — skipping duplicate.")
            return
        _processing.add(name)

    try:
        asyncio.create_task(_do_higgsfield(name))
    except Exception as e:
        log.exception(f"[{name}] AI prompt pipeline error")
        await _notify(f"❌ *{name}* — AI Prompting failed: `{e}`")
        with _lock:
            _processing.discard(name)


def _step2_higgsfield_batch(name: str, style: str, num_sets: int, on_progress=None) -> None:
    from higgsfield_generate import generate_ai_batch
    output_dir = os.path.join(OUTPUTS_DIR, "higgsfield", name)
    generate_ai_batch(name, output_dir, style, num_sets, on_progress=on_progress)


async def _pipeline_make_images_ai_batch(name: str, style: str, num_sets: int) -> None:
    """Batch AI flow: generates num_sets*2 images across num_sets unique scenes."""
    with _lock:
        if name in _processing:
            log.info(f"[{name}] Already in progress — skipping duplicate.")
            return
        _processing.add(name)

    try:
        asyncio.create_task(_do_higgsfield_batch(name, style, num_sets))
    except Exception as e:
        log.exception(f"[{name}] Batch pipeline error")
        await _notify(f"❌ *{name}* — Batch generation failed: `{e}`")
        with _lock:
            _processing.discard(name)


async def _do_higgsfield_batch(name: str, style: str, num_sets: int) -> None:
    import functools
    loop = asyncio.get_running_loop()
    total = num_sets * 2

    if name in _cancelled:
        return

    cancel_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{name}")
    ]])

    bar_empty = "░" * total
    try:
        progress_msg = await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=f"🎨 *{name}* — Generating {total} images... [{bar_empty}] 0/{total}",
            parse_mode="Markdown",
            reply_markup=cancel_kb,
        )
    except Exception as e:
        log.error(f"[{name}] Could not send batch progress message: {e}")
        with _lock:
            _processing.discard(name)
        return
    _stage[name] = f"🎨 Generating images (0/{total})"

    def _on_progress(count: int):
        if name in _cancelled:
            return
        bar = "▓" * count + "░" * (total - count)
        _stage[name] = f"🎨 Generating images ({count}/{total})"
        try:
            asyncio.run_coroutine_threadsafe(
                progress_msg.edit_text(
                    f"🎨 *{name}* — Generating {total} images... [{bar}] {count}/{total}",
                    parse_mode="Markdown",
                    reply_markup=cancel_kb,
                ),
                _loop,
            ).result(timeout=10)
        except Exception:
            pass

    hf_error: str = ""
    try:
        step_fn = functools.partial(_step2_higgsfield_batch, name, style, num_sets)
        await loop.run_in_executor(_executor, step_fn, _on_progress)
    except Exception as e:
        hf_error = str(e)
        log.exception(f"[{name}] Higgsfield batch error")

    if name in _cancelled:
        return

    if not _has_higgsfield(name):
        if "OUT_OF_CREDITS:Higgsfield" in hf_error:
            reason = "💳 Out of Higgsfield credits. Please top it up → higgsfield.ai/billing"
        elif "OUT_OF_CREDITS:Claude" in hf_error:
            reason = "💳 Out of Claude credits. Please top it up → console.anthropic.com/billing"
        elif "CLAUDE_REFUSED" in hf_error:
            reason = "⚠️ Claude refused the batch prompt request. Try again."
        elif "not authenticated" in hf_error.lower() or "auth login" in hf_error.lower():
            reason = "Higgsfield CLI not authenticated. Run: `higgsfield auth login`"
        elif hf_error:
            reason = f"Higgsfield batch error: `{hf_error[:200]}`"
        else:
            reason = f"All {total} Higgsfield batch jobs failed — check logs."
        try:
            await progress_msg.edit_text(
                f"❌ *{name}* — Batch generation failed.",
                parse_mode="Markdown",
                reply_markup=None,
            )
        except Exception:
            pass
        await _send_failure_actions(name, reason)
        with _lock:
            _processing.discard(name)
        return

    try:
        await progress_msg.edit_text(
            f"✅ *{name}* — {total} images ready!",
            parse_mode="Markdown",
            reply_markup=None,
        )
    except Exception:
        pass

    try:
        await _send_make_images_result(name)
    except Exception as e:
        log.exception(f"[{name}] Failed to send batch results to Telegram")
        await _notify(f"❌ *{name}* — Images ready but failed to send: `{str(e)[:200]}`")
        with _lock:
            _processing.discard(name)


# ── Reference image upload handler ────────────────────────────────────────────

async def _on_ref_image_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo / image document uploads for the Make Images flow."""
    msg = update.message
    chat_id = str(update.effective_chat.id)

    waiting_key = chat_id if chat_id in _awaiting_ref_image else (
        TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID in _awaiting_ref_image else None
    )
    if not waiting_key:
        return

    name = _awaiting_ref_image.pop(waiting_key)

    if msg.document and msg.document.mime_type and msg.document.mime_type.startswith("image/"):
        tg_file = await msg.document.get_file()
    elif msg.photo:
        tg_file = await msg.photo[-1].get_file()
    else:
        _awaiting_ref_image[waiting_key] = name
        return

    reply = await msg.reply_text(f"📥 *{name}* — Saving reference image...", parse_mode="Markdown")

    try:
        import tempfile
        os.makedirs(EXTRACTED_FRAMES_DIR, exist_ok=True)
        frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.close()
        await tg_file.download_to_drive(tmp.name)

        from PIL import Image as _PILImage
        img = _PILImage.open(tmp.name).convert("RGB")
        img.save(frame_path, format="PNG")
        os.unlink(tmp.name)

        await reply.delete()
        log.info(f"[make_images] {name}: reference image saved → {frame_path}")

        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, generate!", callback_data=f"make_img_yes:{name}"),
            InlineKeyboardButton("❌ No",             callback_data=f"make_img_no:{name}"),
        ]])
        with open(frame_path, "rb") as img_f:
            await _app.bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=img_f,
                caption="Do you want to replicate this image with Mia?",
                reply_markup=confirm_kb,
            )

    except Exception as e:
        log.error(f"[make_images] Failed to save reference image: {e}")
        _make_images_names.discard(name)
        await reply.edit_text(f"❌ Failed to save image: `{e}`", parse_mode="Markdown")


# ── Make Images result / confirm handlers ────────────────────────────────────

async def _send_make_images_result(name: str) -> None:
    """Send all 4 generated images + Restart Gen / Cancel buttons. No picking needed."""
    images = _higgsfield_images(name)
    if not images:
        return

    for i, path in enumerate(images, 1):
        with open(path, "rb") as f:
            await _app.bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=f,
                caption=f"`{name}` — Image {i}",
                parse_mode="Markdown",
            )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Restart Gen", callback_data=f"make_img_restart:{name}"),
        InlineKeyboardButton("❌ Cancel",       callback_data=f"cancel:{name}"),
    ]])
    await _app.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=f"🖼 *{name}* — Here are your {len(images)} images! Save whichever you like.",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    _stage[name] = "✅ Done"
    with _lock:
        _processing.discard(name)


async def _on_make_img_yes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)
    await _safe_edit(query, f"✅ *{name}* — Generating with Mia...", keyboard=None)
    asyncio.create_task(_pipeline_make_images(name))


async def _on_make_img_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)
    _make_images_names.discard(name)
    frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    if os.path.exists(frame_path):
        os.remove(frame_path)
    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)
    await _safe_edit(
        query,
        "👍 No problem! Tap *▶️ Start / Scan Queue* for more options.",
        keyboard=None,
    )


async def _on_make_img_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    is_ai = name in _ai_prompt_names
    is_batch = name in _batch_config
    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)
    _cancelled.discard(name)
    with _lock:
        _processing.discard(name)
    _make_images_names.add(name)

    await query.edit_message_text(
        f"🔄 *{name}* — Deleted old images. Regenerating...", parse_mode="Markdown"
    )

    if is_batch:
        cfg = _batch_config[name]
        with _lock:
            _processing.add(name)
        asyncio.create_task(_do_higgsfield_batch(name, cfg["style"], cfg["num_sets"]))
    elif is_ai:
        _ai_prompt_names.add(name)
        asyncio.create_task(_do_higgsfield(name))
    else:
        asyncio.create_task(_do_higgsfield(name))


# ── Telegram handlers ─────────────────────────────────────────────────────────

async def _on_frame_approve(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User approved the extracted frame — start Higgsfield."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    if name in _cancelled:
        await _safe_edit(query, f"❌ *{name}* — Already cancelled.")
        return

    await _safe_edit(query, f"✅ *{name}* — Frame approved! Starting image generation...")
    asyncio.create_task(_do_higgsfield(name))


async def _on_frame_retry_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User wants a different frame — delete current and re-extract."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    if os.path.exists(frame_path):
        os.remove(frame_path)
    with _lock:
        _processing.discard(name)
    _cancelled.discard(name)

    await _safe_edit(query, f"🔄 *{name}* — Trying a different frame...")
    asyncio.create_task(_do_frame_extract(name))


async def _on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel processing for a video at any stage."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    _cancelled.add(name)
    with _lock:
        _processing.discard(name)
    _stage.pop(name, None)
    _make_images_names.discard(name)
    _ai_prompt_names.discard(name)

    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)
    frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    if os.path.exists(frame_path):
        os.remove(frame_path)

    await _safe_edit(query, f"❌ *{name}* — Cancelled and cleaned up.", keyboard=None)
    log.info(f"[{name}] Cancelled by user.")


async def _on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    _, num_str, name = query.data.split(":", 2)
    num = int(num_str)

    if _has_output(name):
        await query.edit_message_text(f"✅ *{name}* already completed.", parse_mode="Markdown")
        return

    src = os.path.join(OUTPUTS_DIR, "higgsfield", name, f"output_{num}.png")
    dst = os.path.join(OUTPUTS_DIR, "higgsfield", name, "selected.png")

    if not os.path.exists(src):
        await query.edit_message_text(f"❌ `output_{num}.png` not found for `{name}`.")
        return

    shutil.copy2(src, dst)
    log.info(f"[{name}] User picked output_{num}.png → selected.png")

    if name in _make_images_names:
        await query.edit_message_text(
            f"✅ *{name}* — Picked option {num}! Sending your image...",
            parse_mode="Markdown",
        )
        with open(src, "rb") as f:
            await _app.bot.send_photo(
                chat_id=TELEGRAM_CHAT_ID,
                photo=f,
                caption=f"🖼 *{name}* — Done!",
                parse_mode="Markdown",
            )
        _make_images_names.discard(name)
        _stage[name] = "✅ Done"
        with _lock:
            _processing.discard(name)
        return

    await query.edit_message_text(
        f"✅ *{name}* — Picked option {num}! Starting Wavespeed...",
        parse_mode="Markdown",
    )
    asyncio.create_task(_do_wavespeed(name))


def _next_video_name() -> str:
    existing = glob.glob(os.path.join(RAW_MATERIAL_DIR, "video*.mp4"))
    nums = []
    for f in existing:
        stem = _vname(f)
        if stem.startswith("video") and stem[5:].isdigit():
            nums.append(int(stem[5:]))
    return f"video{max(nums) + 1}" if nums else "video1"


def _download_url(url: str, name: str) -> str:
    import tempfile
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, f"{name}.mp4")
    try:
        cmd = [
            "yt-dlp",
            "--no-playlist",
            "-f", "bestvideo+bestaudio/best",
            "--merge-output-format", "mp4",
            "--socket-timeout", "30",
            "--retries", "5",
            "--fragment-retries", "10",
            "--extractor-retries", "5",
            "--retry-sleep", "3",
            "-o", tmp_path,
        ]
        if os.path.exists(COOKIES_FILE):
            cmd += ["--cookies", COOKIES_FILE]
        cmd.append(url)

        last_err = ""
        for attempt in range(1, 4):
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            if result.returncode == 0:
                break
            last_err = result.stderr.strip() or result.stdout.strip()
            is_timeout = "timed out" in last_err.lower() or "timeout" in last_err.lower()
            if not is_timeout or attempt == 3:
                raise RuntimeError(last_err)
            log.warning(f"[download] Attempt {attempt} timed out — retrying in 5s...")
            time.sleep(5)
        else:
            raise RuntimeError(last_err)

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", tmp_path],
            capture_output=True, text=True,
        )
        codec = probe.stdout.strip()
        if codec != "h264":
            log.info(f"[download] Re-encoding {codec} → H.264...")
            h264_path = tmp_path.replace(".mp4", "_h264.mp4")
            enc = subprocess.run(
                ["ffmpeg", "-y", "-i", tmp_path,
                 "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
                 "-c:a", "aac", "-movflags", "+faststart", h264_path],
                capture_output=True,
            )
            if enc.returncode != 0:
                raise RuntimeError("ffmpeg re-encode failed: " + enc.stderr.decode()[-300:])
            os.replace(h264_path, tmp_path)

        final = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")
        shutil.move(tmp_path, final)
        return final
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def _on_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()

    # Check if we're waiting for a script from the user
    chat_id = str(update.effective_chat.id)
    waiting_key = chat_id if chat_id in _awaiting_script else (
        TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID in _awaiting_script else None
    )
    if waiting_key and not re.match(r"https?://", text):
        name = _awaiting_script.pop(waiting_key)
        await update.message.reply_text(
            f"🎤 *{name}* — Got it! Generating with Mia's voice...",
            parse_mode="Markdown",
        )
        asyncio.create_task(_do_ugc_pipeline(name, text))
        return

    if not re.match(r"https?://", text):
        return

    name = _next_video_name()
    msg = await update.message.reply_text(
        f"⬇️ Downloading as *{name}*...", parse_mode="Markdown"
    )
    loop = asyncio.get_running_loop()
    try:
        final = await loop.run_in_executor(_executor, _download_url, text, name)
        await msg.edit_text(f"✅ *{name}* — Downloaded!", parse_mode="Markdown")
        log.info(f"[download] {text} → {final}")
        await _route_new_video(name)
    except Exception as e:
        err = str(e)
        log.error(f"[download] Failed: {err}")
        is_instagram = "instagram.com" in text.lower()
        is_timeout = "timed out" in err.lower() or "timeout" in err.lower()
        is_bad_url = "unsupported url" in err.lower() or "falling back on generic" in err.lower()
        needs_login = any(x in err.lower() for x in ["login", "empty media", "not granting", "cookies", "auth"])
        if is_bad_url:
            await msg.edit_text(
                "⚠️ *That link isn't a video.*\n\n"
                "Make sure you're sharing an actual video, not a profile page, homepage, or search result.\n\n"
                "*How to get the right link:*\n"
                "• TikTok — open a video → tap Share → Copy link\n"
                "• Instagram — open a Reel → tap ··· → Copy link\n"
                "• YouTube — open a video → tap Share → Copy link",
                parse_mode="Markdown",
            )
        elif is_timeout:
            await msg.edit_text(
                "⏱ *Download timed out* (tried 3×)\n\n"
                "TikTok/Instagram servers were slow. Options:\n\n"
                "• *Try again* — paste the same link again\n"
                "• *Send the file directly* — download on your phone and send here (up to 20 MB)",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔁 Retry same link", callback_data=f"retry_url:{text}"),
                ]]),
            )
        elif is_instagram and needs_login:
            await msg.edit_text(
                "⚠️ *Instagram login required*\n\n"
                "Instagram blocked the download because the bot isn't logged in.\n\n"
                "*Option 1 — Quick fix:*\n"
                "Download the reel to your phone → send the video file directly here (up to 20 MB)\n\n"
                "*Option 2 — Permanent fix:*\n"
                "Export your Instagram cookies and send the `cookies.txt` file to this bot. "
                "It will work for all future Instagram links automatically.\n\n"
                "See /help for cookie export instructions.",
                parse_mode="Markdown",
            )
        else:
            await msg.edit_text(f"❌ Download failed: `{err[:300]}`", parse_mode="Markdown")


async def _on_retry_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retry a timed-out URL download from the inline button."""
    query = update.callback_query
    await query.answer()
    _, url = query.data.split(":", 1)

    name = _next_video_name()
    await _safe_edit(query, f"⬇️ Retrying download as *{name}*...", keyboard=None)
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(_executor, _download_url, url, name)
        await _notify(f"✅ *{name}* — Downloaded! Pipeline starting...")
        log.info(f"[download] retry succeeded: {url}")
    except Exception as e:
        err = str(e)
        log.error(f"[download] retry failed: {err}")
        is_timeout = "timed out" in err.lower() or "timeout" in err.lower()
        if is_timeout:
            await _notify(
                f"⏱ *Still timing out.* TikTok servers may be slow right now.\n"
                f"Download the video on your phone and send the file here instead."
            )
        else:
            await _notify(f"❌ Download failed again: `{err[:200]}`")


async def _on_video_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    tg_file = None
    original_name = None

    # Handle cookies.txt upload — saves it for yt-dlp Instagram auth
    if msg.document and (msg.document.file_name or "").lower() == "cookies.txt":
        reply = await msg.reply_text("🍪 Saving cookies...", parse_mode="Markdown")
        try:
            tg_cookies = await msg.document.get_file()
            await tg_cookies.download_to_drive(COOKIES_FILE)
            await reply.edit_text(
                "✅ *Cookies saved!*\n\n"
                "Instagram links will now download automatically. "
                "Cookies stay on the server — just paste links as normal.",
                parse_mode="Markdown",
            )
            log.info("Cookies file updated.")
        except Exception as e:
            await reply.edit_text(f"❌ Failed to save cookies: `{e}`", parse_mode="Markdown")
        return

    if msg.video:
        tg_file = await msg.video.get_file()
        original_name = msg.video.file_name or "upload.mp4"
        file_size = msg.video.file_size or 0
    elif msg.document and msg.document.mime_type and msg.document.mime_type.startswith("video/"):
        tg_file = await msg.document.get_file()
        original_name = msg.document.file_name or "upload.mp4"
        file_size = msg.document.file_size or 0
    else:
        return

    if file_size > 20 * 1024 * 1024:
        await msg.reply_text(
            f"⚠️ File is {file_size / 1_000_000:.0f} MB — Telegram bots can only receive files up to 20 MB.\n"
            "Send a URL (TikTok / Instagram / YouTube) instead.",
            parse_mode="Markdown",
        )
        return

    name = _next_video_name()
    reply = await msg.reply_text(f"⬇️ Receiving *{name}*...", parse_mode="Markdown")

    import tempfile
    tmp_dir = tempfile.mkdtemp()
    ext = os.path.splitext(original_name)[1].lower() or ".mp4"
    tmp_path = os.path.join(tmp_dir, f"{name}{ext}")

    try:
        await tg_file.download_to_drive(tmp_path)

        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1:nokey=1", tmp_path],
            capture_output=True, text=True,
        )
        codec = probe.stdout.strip()
        final_tmp = os.path.join(tmp_dir, f"{name}.mp4")

        if codec != "h264" or ext != ".mp4":
            await reply.edit_text(f"🔄 *{name}* — Converting to H.264...", parse_mode="Markdown")
            loop = asyncio.get_running_loop()
            enc_result = await loop.run_in_executor(
                _executor,
                lambda: subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_path,
                     "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast",
                     "-c:a", "aac", "-movflags", "+faststart", final_tmp],
                    capture_output=True,
                ),
            )
            if enc_result.returncode != 0:
                raise RuntimeError("ffmpeg re-encode failed: " + enc_result.stderr.decode()[-300:])
        else:
            os.rename(tmp_path, final_tmp)

        dest = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")
        shutil.move(final_tmp, dest)
        await reply.edit_text(f"✅ *{name}* — Saved!", parse_mode="Markdown")
        log.info(f"[upload] Telegram video ({ext}, {codec}) → {dest}")
        await _route_new_video(name)

    except Exception as e:
        log.error(f"[upload] Failed: {e}")
        await reply.edit_text(f"❌ Upload failed: `{e}`", parse_mode="Markdown")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Mode selection callbacks ──────────────────────────────────────────────────

async def _on_mode_clone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User chose Clone Video — show engine sub-menu (NBP or SC2.0)."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)
    _pending_mode.discard(name)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🧠 NBP",   callback_data=f"engine_nbp:{name}"),
        InlineKeyboardButton("🎭 SC2.0", callback_data=f"engine_sc2:{name}"),
    ]])
    await _safe_edit(
        query,
        f"🎭 *{name}* — Choose generation engine:\n\n"
        "🧠 *NBP* — Nano Banana Pro (great for dancing / moving scenes)\n"
        "🎭 *SC2.0* — Soul Character 2.0 (bypasses NSFW, consistent identity)",
        keyboard=keyboard,
    )


async def _on_engine_sc2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)
    await _safe_edit(query, f"🎭 *{name}* — Starting SC2.0 clone pipeline...")
    asyncio.create_task(_pipeline(name, stable=True))


async def _on_engine_nbp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)
    await _safe_edit(query, f"🧠 *{name}* — Starting NBP clone pipeline...")
    asyncio.create_task(_pipeline_nbp(name, stable=True))


async def _on_mode_ugc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User chose Talking Head — ask for the script."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)
    _pending_mode.discard(name)
    _awaiting_script[TELEGRAM_CHAT_ID] = name
    _stage[name] = "⏸ Waiting for script"
    await _safe_edit(
        query,
        f"🎤 *{name}* — Send me the script and Mia will deliver it.\n\n"
        f"_Just type or paste it in the chat._",
        keyboard=None,
    )


# ── Talking Head pipeline ─────────────────────────────────────────────────────

def _step_ugc(name: str, script: str) -> str:
    from ugc_generate import generate_and_swap
    out_dir = os.path.join(OUTPUTS_DIR, "ugc", name)
    os.makedirs(out_dir, exist_ok=True)
    return generate_and_swap(script, out_dir)


async def _do_ugc_pipeline(name: str, script: str) -> None:
    loop = asyncio.get_running_loop()
    with _lock:
        _processing.add(name)
    _stage[name] = "🎤 Generating talking head"

    try:
        await _notify(f"🎤 *{name}* — Generating talking head (Higgsfield + Mia's voice)...")
        out_path = await loop.run_in_executor(_executor, _step_ugc, name, script)

        if out_path and os.path.exists(out_path):
            size_mb = os.path.getsize(out_path) / 1_000_000
            width, height, duration = _video_dimensions(out_path)
            with open(out_path, "rb") as f:
                await _app.bot.send_video(
                    chat_id=TELEGRAM_CHAT_ID,
                    video=f,
                    caption=f"🎤 *{name}* — Talking head done! ({size_mb:.1f} MB)",
                    parse_mode="Markdown",
                    supports_streaming=True,
                    width=width,
                    height=height,
                    duration=duration,
                )
            _stage[name] = "✅ Done"
        else:
            await _notify(f"❌ *{name}* — Talking head generation failed. Check VPS logs.")
    except Exception as e:
        log.exception(f"[{name}] UGC pipeline error")
        err = str(e)
        if "OUT_OF_CREDITS:Higgsfield" in err:
            await _notify(f"💳 *{name}* — Out of Higgsfield credits → higgsfield.ai/billing")
        elif "OUT_OF_CREDITS:ElevenLabs" in err:
            await _notify(f"💳 *{name}* — Out of ElevenLabs credits → elevenlabs.io/billing")
        else:
            await _notify(f"❌ *{name}* — Talking head failed: `{err[:200]}`")
    finally:
        with _lock:
            _processing.discard(name)


# ── Voice replace callback (Clone Video flow) ─────────────────────────────────

def _step_voice_replace(name: str) -> str:
    from voice_swap import process as voice_process
    video_path = os.path.join(OUTPUTS_DIR, "wavespeed", name, "output.mp4")
    out_path   = os.path.join(OUTPUTS_DIR, "wavespeed", name, "output_mia_voice.mp4")
    return voice_process(video_path, output_path=out_path)


async def _on_voice_replace(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    await _safe_edit(query, f"🎙 *{name}* — Replacing audio with Mia's voice...", keyboard=None)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(_executor, _step_voice_replace, name)
        if result and os.path.exists(result):
            size_mb = os.path.getsize(result) / 1_000_000
            width, height, duration = _video_dimensions(result)
            with open(result, "rb") as f:
                await _app.bot.send_video(
                    chat_id=TELEGRAM_CHAT_ID,
                    video=f,
                    caption=f"🎙 *{name}* — Mia's voice applied! ({size_mb:.1f} MB)",
                    parse_mode="Markdown",
                    supports_streaming=True,
                    width=width,
                    height=height,
                    duration=duration,
                )
        else:
            await _notify(f"❌ *{name}* — Voice replace failed — output not found.")
    except Exception as e:
        log.exception(f"[{name}] Voice replace error")
        err = str(e)
        if "OUT_OF_CREDITS:ElevenLabs" in err:
            await _notify(f"💳 *{name}* — Out of ElevenLabs credits → elevenlabs.io/billing")
        else:
            await _notify(f"❌ *{name}* — Voice replace failed: `{err[:200]}`")


async def _on_hf_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)
    _cancelled.discard(name)
    with _lock:
        _processing.discard(name)

    await query.edit_message_text(
        f"🔄 *{name}* — Deleted old images. Regenerating...", parse_mode="Markdown"
    )
    asyncio.create_task(_do_higgsfield(name))


async def _on_see_frame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    if not os.path.exists(frame_path):
        await query.answer("⚠️ Frame not found.", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Try Different Frame", callback_data=f"frame_retry_full:{name}"),
        InlineKeyboardButton("✅ Pick 1/2/3/4", callback_data=f"frame_pick:{name}"),
    ]])
    with open(frame_path, "rb") as f:
        await _app.bot.send_photo(
            chat_id=TELEGRAM_CHAT_ID,
            photo=f,
            caption=f"🖼 *{name}* — Extracted frame",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )


async def _on_frame_ok(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)
    _cancelled.discard(name)
    with _lock:
        _processing.discard(name)

    await query.edit_message_caption(
        f"✅ *{name}* — Frame confirmed! Regenerating images...", parse_mode="Markdown"
    )
    asyncio.create_task(_do_higgsfield(name))


async def _on_frame_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    await query.edit_message_caption(
        f"✅ *{name}* — Frame confirmed! Choose your image:", parse_mode="Markdown"
    )
    await _send_selection_prompt(name)


async def _on_frame_retry_full(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete frame + all Higgsfield images, re-extract a different frame, regenerate."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")
    if os.path.exists(frame_path):
        os.remove(frame_path)
    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)

    _cancelled.discard(name)
    with _lock:
        _processing.discard(name)

    try:
        await query.edit_message_caption(
            f"🔄 *{name}* — Trying a different frame and regenerating all images...",
            parse_mode="Markdown",
            reply_markup=None,
        )
    except Exception:
        pass

    asyncio.create_task(_do_frame_extract(name))


def _build_cancel_keyboard() -> tuple:
    """Return (text, InlineKeyboardMarkup|None) for the cancel-video list."""
    videos = sorted(glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")))
    if not videos:
        return "📭 No videos in the pipeline to cancel.", None

    buttons = []
    for v in videos:
        name = _vname(v)
        if _has_output(name):
            status = "✅ Done"
        elif name in _processing:
            status = _stage.get(name, "⚙️ Processing")
        elif _has_selected(name):
            status = "⏳ Wavespeed queued"
        elif _has_higgsfield(name):
            status = "👆 Awaiting pick"
        elif _has_frame(name):
            status = "⏸ Awaiting approval"
        else:
            status = _stage.get(name, "📥 Queued")
        buttons.append([InlineKeyboardButton(
            f"❌ {name} — {status}", callback_data=f"cancel_pick:{name}"
        )])

    buttons.append([InlineKeyboardButton("✖️ Never mind", callback_data="cancel_list_dismiss")])
    return (
        "*Which video do you want to cancel?*\n\nTap a video — you'll confirm before anything is deleted.",
        InlineKeyboardMarkup(buttons),
    )


async def _on_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cancel command — show list of videos to cancel."""
    text, keyboard = _build_cancel_keyboard()
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def _on_cancel_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """cancel_list button — edit current message to show the video list."""
    query = update.callback_query
    await query.answer()
    text, keyboard = _build_cancel_keyboard()
    await _safe_edit(query, text, keyboard=keyboard)


async def _on_cancel_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """User tapped a specific video — show confirmation before deleting."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    stage = _stage.get(name, "in pipeline")
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes, cancel & delete it", callback_data=f"cancel_do:{name}"),
            InlineKeyboardButton("No, keep it", callback_data="cancel_list_dismiss"),
        ]
    ])
    await _safe_edit(
        query,
        f"*Cancel {name}?*\n\nCurrent stage: {stage}\n\nThis stops processing and deletes the raw video, frame, and all generated images. It won't come back on restart.",
        keyboard=keyboard,
    )


async def _on_cancel_do(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirmed — fully cancel and delete everything for this video."""
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    _cancelled.add(name)
    with _lock:
        _processing.discard(name)
    _make_images_names.discard(name)
    _ai_prompt_names.discard(name)

    for p in [
        os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4"),
        os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png"),
    ]:
        if os.path.exists(p):
            os.remove(p)
    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)
    shutil.rmtree(os.path.join(OUTPUTS_DIR, "wavespeed", name), ignore_errors=True)

    _retry_counts.pop(name, None)
    _stage.pop(name, None)

    log.info(f"[{name}] Cancelled and deleted via cancel menu.")
    await _safe_edit(
        query,
        f"🗑 *{name}* — Cancelled and deleted. All files removed, won't reappear on restart.",
        keyboard=None,
    )


async def _on_cancel_list_dismiss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _safe_edit(query, "👍 No changes made.", keyboard=None)


async def _on_action_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await _safe_edit(query, "🔍 Scanning queue...", keyboard=None)
    asyncio.create_task(_startup_scan())


async def _on_retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    _retry_counts[name] = _retry_counts.get(name, 0) + 1
    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)
    _cancelled.discard(name)
    with _lock:
        _processing.discard(name)

    await query.edit_message_text(f"🔄 *{name}* — Retrying...", parse_mode="Markdown")
    if name in _make_images_names:
        asyncio.create_task(_pipeline_make_images(name))
    else:
        asyncio.create_task(_pipeline(name))


async def _on_delete_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, name = query.data.split(":", 1)

    raw_path = os.path.join(RAW_MATERIAL_DIR, f"{name}.mp4")
    frame_path = os.path.join(EXTRACTED_FRAMES_DIR, f"{name}_frame.png")

    for p in [raw_path, frame_path]:
        if os.path.exists(p):
            os.remove(p)
    shutil.rmtree(os.path.join(OUTPUTS_DIR, "higgsfield", name), ignore_errors=True)

    _retry_counts.pop(name, None)
    _cancelled.discard(name)
    _stage.pop(name, None)
    with _lock:
        _processing.discard(name)

    log.info(f"[{name}] Deleted by user via bot.")
    await query.edit_message_text(
        f"🗑 *{name}* — Deleted. Raw video, frame, and generated images removed.",
        parse_mode="Markdown",
    )


async def _on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cid = update.effective_chat.id
    await update.message.reply_text(
        f"👋 *Pipeline bot is live!*\n\n"
        f"Your chat ID: `{cid}`\n\n"
        f"*How to add a video:*\n"
        f"• Paste a TikTok / Instagram / YouTube link\n"
        f"• Or send a video file (up to 20 MB)\n\n"
        f"Use the buttons below or type /help for all commands.",
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


async def _on_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cookies_status = "✅ Saved" if os.path.exists(COOKIES_FILE) else "❌ Not set"
    await update.message.reply_text(
        "🤖 *AI Influencer Bot — Help*\n\n"
        "*How to add a video:*\n"
        "• Paste a TikTok / Instagram / YouTube link\n"
        "• Or send a video file directly (up to 20 MB)\n\n"
        "*Pipeline steps:*\n"
        "1️⃣ Frame extracted automatically\n"
        "2️⃣ 4 AI images generated with live progress\n"
        "3️⃣ You pick the best image (tap 1/2/3/4)\n"
        "4️⃣ Final video → Telegram + Google Drive link\n\n"
        "*Commands:*\n"
        "/status — See all videos, stages, clean + restart buttons\n"
        "/clean — Wipe everything and start fresh\n"
        "/cancel — Cancel & delete one video\n"
        "/help — Show this message\n\n"
        "*Buttons:*\n"
        "✅ Pick 1/2/3/4 — choose the best AI image\n"
        "🖼 See Frame — view the extracted source frame\n"
        "🔄 Try Different Frame — re-extract frame & regenerate all 4 images\n"
        "🔄 Restart Gen — regenerate all 4 images (keep same frame)\n"
        "🔄 Retry — retry after a failure\n"
        "❌ Cancel — stop processing and clean up\n\n"
        f"*Instagram cookies:* {cookies_status}\n"
        "To fix Instagram download errors:\n"
        "1. Open Chrome → instagram.com (logged in)\n"
        "2. Install extension: *Get cookies.txt LOCALLY*\n"
        "3. Click extension → Export → save as `cookies.txt`\n"
        "4. Send that file to this bot\n"
        "Done — all Instagram links work from then on.",
        parse_mode="Markdown",
    )


async def _on_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    videos = sorted(glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")))
    active = len(_processing)

    if not videos:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 Clean All", callback_data="clean_confirm_direct"),
        ]])
        await update.message.reply_text(
            "📭 *Queue is empty.*\n\nSend a URL or video file to get started!",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    lines = [f"*Pipeline Status* — {active} job(s) active\n"]
    for v in videos:
        name = _vname(v)
        if _has_output(name):
            s = "✅ Done"
        elif _has_selected(name):
            s = _stage.get(name, "⚡ Wavespeed running")
        elif _has_higgsfield(name):
            s = _stage.get(name, "👆 Waiting for image pick")
        elif _has_frame(name):
            s = _stage.get(name, "🎨 Generating images...")
        else:
            s = _stage.get(name, "📥 Extracting frame")
        active_tag = " ⚙️" if name in _processing else ""
        lines.append(f"• `{name}`: {s}{active_tag}")

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("❌ Cancel a Video", callback_data="cancel_list"),
            InlineKeyboardButton("🔄 Hard Restart", callback_data="hard_restart"),
        ],
        [InlineKeyboardButton("🗑 Clean All", callback_data="clean_prompt")],
    ])
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=keyboard
    )


# ── /clean and hard-restart ───────────────────────────────────────────────────

async def _on_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the persistent bottom keyboard."""
    text = update.message.text

    if text == "📊 Status":
        await _on_status(update, context)

    elif text == "▶️ Start / Scan Queue":
        await _send_mode_selection(update.message.reply_text)

    elif text == "🔄 Hard Restart":
        await update.message.reply_text(
            "🔄 *Hard restarting...* cancelling all jobs and rescanning.",
            parse_mode="Markdown",
        )
        with _lock:
            for name in list(_processing):
                _cancelled.add(name)
            _processing.clear()
        _stage.clear()
        _retry_counts.clear()
        _cancelled.clear()
        await asyncio.sleep(1)
        await _startup_scan()

    elif text == "🗑 Clean All":
        await _on_clean_cmd(update, context)


async def _on_clean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clean — show what will be wiped and ask for confirmation."""
    await _show_clean_prompt(update.message.reply_text)


async def _show_clean_prompt(reply_fn) -> None:
    videos  = glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4"))
    frames  = glob.glob(os.path.join(EXTRACTED_FRAMES_DIR, "*_frame.png"))
    hf_dirs = [d for d in glob.glob(os.path.join(OUTPUTS_DIR, "higgsfield", "*")) if os.path.isdir(d)]
    ws_dirs = [d for d in glob.glob(os.path.join(OUTPUTS_DIR, "wavespeed", "*")) if os.path.isdir(d)]

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑 Yes, wipe everything", callback_data="clean_confirm_direct")],
        [InlineKeyboardButton("✖️ Cancel", callback_data="clean_cancel")],
    ])
    await reply_fn(
        f"⚠️ *Clean All — this cannot be undone:*\n\n"
        f"• {len(videos)} raw video(s)\n"
        f"• {len(frames)} extracted frame(s)\n"
        f"• {len(hf_dirs)} Higgsfield folder(s)\n"
        f"• {len(ws_dirs)} Wavespeed output(s)\n\n"
        f"All in-progress jobs will be cancelled.\n\n"
        f"Continue?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _on_clean_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clean All button from /status — show the confirmation dialog."""
    query = update.callback_query
    await query.answer()
    await _show_clean_prompt(query.message.reply_text)


async def _do_clean() -> dict:
    """Wipe all pipeline files and cancel all in-progress jobs. Returns counts."""
    with _lock:
        for name in list(_processing):
            _cancelled.add(name)
        _processing.clear()
    _stage.clear()
    _retry_counts.clear()
    _cancelled.clear()

    deleted = {"videos": 0, "frames": 0, "hf": 0, "ws": 0}

    for f in glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")):
        try:
            os.remove(f)
            deleted["videos"] += 1
        except OSError:
            pass

    for f in glob.glob(os.path.join(EXTRACTED_FRAMES_DIR, "*_frame.png")):
        try:
            os.remove(f)
            deleted["frames"] += 1
        except OSError:
            pass

    # Clean up temp dirs left behind by interrupted frame extractions
    for d in glob.glob(os.path.join(EXTRACTED_FRAMES_DIR, "_tmp_*")):
        shutil.rmtree(d, ignore_errors=True)

    for d in glob.glob(os.path.join(OUTPUTS_DIR, "higgsfield", "*")):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            deleted["hf"] += 1

    for d in glob.glob(os.path.join(OUTPUTS_DIR, "wavespeed", "*")):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            deleted["ws"] += 1

    return deleted


async def _on_clean_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Confirmed — wipe everything."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🗑 Cleaning...", parse_mode="Markdown")

    deleted = await _do_clean()

    await query.edit_message_text(
        f"✅ *All clear!*\n\n"
        f"• {deleted['videos']} video(s) deleted\n"
        f"• {deleted['frames']} frame(s) deleted\n"
        f"• {deleted['hf']} Higgsfield folder(s) deleted\n"
        f"• {deleted['ws']} Wavespeed output(s) deleted\n\n"
        f"Queue is empty. Send a link or video to start fresh.",
        parse_mode="Markdown",
    )


async def _on_clean_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👍 Clean cancelled — nothing deleted.")


async def _on_hard_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel all in-progress jobs, clear state, re-scan disk and resume."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔄 *Hard restarting...* cancelling all jobs and rescanning.", parse_mode="Markdown")

    with _lock:
        for name in list(_processing):
            _cancelled.add(name)
        _processing.clear()
    _stage.clear()
    _retry_counts.clear()
    _cancelled.clear()

    await asyncio.sleep(1)
    await _startup_scan()


# ── Watchdog ──────────────────────────────────────────────────────────────────

class _VideoWatcher(FileSystemEventHandler):
    def _enqueue(self, path: str) -> None:
        if not path.lower().endswith(".mp4"):
            return
        name = _vname(path)
        if name in _pending_mode or name in _processing:
            return  # already handled by URL/upload handler
        log.info(f"[watchdog] Detected: {os.path.basename(path)}")
        asyncio.run_coroutine_threadsafe(_on_new_video(name), _loop)

    def on_created(self, event):
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._enqueue(event.dest_path)


# ── Startup scan ──────────────────────────────────────────────────────────────

async def _startup_scan() -> None:
    videos = sorted(glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")))

    if not videos:
        await _notify(
            "📭 *Queue is empty.*\n\n"
            "Send a TikTok / Instagram link, or upload a video file directly here."
        )
        return

    # Build an instant summary so the user gets a response immediately
    lines = [f"📋 Found *{len(videos)}* video(s):\n"]
    pending = []

    for v in videos:
        name = _vname(v)
        if _has_output(name):
            lines.append(f"• `{name}` — ✅ Already done")
        elif _has_ugc_output(name):
            lines.append(f"• `{name}` — ✅ Talking head done")
        elif _has_selected(name):
            lines.append(f"• `{name}` — ⚡ Resuming Wavespeed")
            pending.append(("wavespeed", name))
        elif _has_higgsfield(name):
            lines.append(f"• `{name}` — 👆 Needs image pick")
            pending.append(("pick", name))
        elif _has_frame(name):
            lines.append(f"• `{name}` — 🎨 Generating images...")
            pending.append(("higgsfield_auto", name))
        else:
            lines.append(f"• `{name}` — 📥 Queued for processing")
            pending.append(("pipeline", name))

    await _notify("\n".join(lines))

    # Now kick off background work — files are already on disk so skip stability wait
    for kind, name in pending:
        if kind == "wavespeed":
            asyncio.create_task(_do_wavespeed(name))
        elif kind == "pick":
            with _lock:
                _processing.add(name)
            await _send_selection_prompt(name)
        elif kind == "higgsfield_auto":
            with _lock:
                _processing.add(name)
            asyncio.create_task(_do_higgsfield(name))
        else:
            asyncio.create_task(_pipeline(name, stable=True))


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    global _loop, _app

    _acquire_pid_lock()

    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be set in config.py")

    if not TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_CHAT_ID not set — send /start to your bot to get it.")

    _loop = asyncio.get_running_loop()

    _request = HTTPXRequest(connection_pool_size=1, http_version="1.1")
    _get_updates_request = HTTPXRequest(connection_pool_size=1, http_version="1.1")
    _app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .request(_request)
        .get_updates_request(_get_updates_request)
        .build()
    )

    # Commands
    _app.add_handler(CommandHandler("start",  _on_start))
    _app.add_handler(CommandHandler("status", _on_status))
    _app.add_handler(CommandHandler("help",   _on_help))
    _app.add_handler(CommandHandler("cancel", _on_cancel_cmd))
    _app.add_handler(CommandHandler("clean",  _on_clean_cmd))

    # Callback buttons — order matters: more specific patterns first
    _app.add_handler(CallbackQueryHandler(_on_preselect_clone,         pattern=r"^preselect_clone$"))
    _app.add_handler(CallbackQueryHandler(_on_preselect_engine_sc2,   pattern=r"^preselect_engine_sc2$"))
    _app.add_handler(CallbackQueryHandler(_on_preselect_engine_nbp,   pattern=r"^preselect_engine_nbp$"))
    _app.add_handler(CallbackQueryHandler(_on_preselect_ugc,          pattern=r"^preselect_ugc$"))
    _app.add_handler(CallbackQueryHandler(_on_preselect_make_images,  pattern=r"^preselect_make_images$"))
    _app.add_handler(CallbackQueryHandler(_on_make_img_upload,        pattern=r"^make_img_upload$"))
    _app.add_handler(CallbackQueryHandler(_on_make_img_ai_prompt,     pattern=r"^make_img_ai_prompt$"))
    _app.add_handler(CallbackQueryHandler(_on_ai_create_style,        pattern=r"^ai_create_style:"))
    _app.add_handler(CallbackQueryHandler(_on_ai_create_count,        pattern=r"^ai_create_count:"))
    _app.add_handler(CallbackQueryHandler(_on_make_img_yes,           pattern=r"^make_img_yes:"))
    _app.add_handler(CallbackQueryHandler(_on_make_img_no,            pattern=r"^make_img_no:"))
    _app.add_handler(CallbackQueryHandler(_on_make_img_restart,       pattern=r"^make_img_restart:"))
    _app.add_handler(CallbackQueryHandler(_on_mode_clone,            pattern=r"^mode_clone:"))
    _app.add_handler(CallbackQueryHandler(_on_engine_sc2,            pattern=r"^engine_sc2:"))
    _app.add_handler(CallbackQueryHandler(_on_engine_nbp,            pattern=r"^engine_nbp:"))
    _app.add_handler(CallbackQueryHandler(_on_mode_ugc,              pattern=r"^mode_ugc:"))
    _app.add_handler(CallbackQueryHandler(_on_voice_replace,       pattern=r"^voice_replace:"))
    _app.add_handler(CallbackQueryHandler(_on_frame_approve,       pattern=r"^frame_approve:"))
    _app.add_handler(CallbackQueryHandler(_on_frame_retry_new,    pattern=r"^frame_retry:"))
    _app.add_handler(CallbackQueryHandler(_on_cancel,             pattern=r"^cancel:"))
    _app.add_handler(CallbackQueryHandler(_on_cancel_list,        pattern=r"^cancel_list$"))
    _app.add_handler(CallbackQueryHandler(_on_cancel_pick,        pattern=r"^cancel_pick:"))
    _app.add_handler(CallbackQueryHandler(_on_cancel_do,          pattern=r"^cancel_do:"))
    _app.add_handler(CallbackQueryHandler(_on_cancel_list_dismiss, pattern=r"^cancel_list_dismiss$"))
    _app.add_handler(CallbackQueryHandler(_on_pick,               pattern=r"^sel:"))
    _app.add_handler(CallbackQueryHandler(_on_retry,              pattern=r"^retry:"))
    _app.add_handler(CallbackQueryHandler(_on_delete_video,       pattern=r"^delete_video:"))
    _app.add_handler(CallbackQueryHandler(_on_hf_restart,         pattern=r"^hf_restart:"))
    _app.add_handler(CallbackQueryHandler(_on_see_frame,          pattern=r"^see_frame:"))
    _app.add_handler(CallbackQueryHandler(_on_frame_ok,           pattern=r"^frame_ok:"))
    _app.add_handler(CallbackQueryHandler(_on_frame_pick,         pattern=r"^frame_pick:"))
    _app.add_handler(CallbackQueryHandler(_on_frame_retry_full,   pattern=r"^frame_retry_full:"))
    _app.add_handler(CallbackQueryHandler(_on_action_start,       pattern=r"^action:start$"))
    _app.add_handler(CallbackQueryHandler(_on_retry_url,          pattern=r"^retry_url:"))
    _app.add_handler(CallbackQueryHandler(_on_clean_prompt,       pattern=r"^clean_prompt$"))
    _app.add_handler(CallbackQueryHandler(_on_clean_confirm,      pattern=r"^clean_confirm_direct$"))
    _app.add_handler(CallbackQueryHandler(_on_clean_cancel,       pattern=r"^clean_cancel$"))
    _app.add_handler(CallbackQueryHandler(_on_hard_restart,       pattern=r"^hard_restart$"))

    # Persistent keyboard buttons (must be registered before the URL handler)
    _kb_filter = filters.Text([
        "▶️ Start / Scan Queue",
        "📊 Status",
        "🔄 Hard Restart",
        "🗑 Clean All",
    ])
    _app.add_handler(MessageHandler(_kb_filter, _on_keyboard_button))

    # Messages — image handler first so PHOTO / Document.IMAGE goes to Make Images flow
    _app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, _on_ref_image_upload))
    _app.add_handler(MessageHandler(filters.VIDEO | filters.Document.ALL, _on_video_upload))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_url))

    observer = Observer()
    observer.schedule(_VideoWatcher(), RAW_MATERIAL_DIR, recursive=False)
    observer.start()
    log.info(f"[watchdog] Watching: {RAW_MATERIAL_DIR}")

    await _app.initialize()
    await _app.start()
    # Brief pause so Telegram releases the previous instance's long-poll connection
    # before we start polling (avoids "Conflict: terminated by other getUpdates" errors)
    await asyncio.sleep(3)
    await _app.updater.start_polling(drop_pending_updates=True)
    log.info("[bot] Telegram polling started")

    if TELEGRAM_CHAT_ID:
        await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=(
                "🚀 *Pipeline bot is live!*\n\n"
                "Paste a TikTok / Instagram / YouTube link\n"
                "or send a video file directly.\n\n"
                "Use the *buttons below* to control the pipeline:\n"
                "▶️ *Start / Scan Queue* — resume any pending jobs\n"
                "📊 *Status* — see what's processing\n"
                "🔄 *Hard Restart* — cancel all and rescan\n"
                "🗑 *Clean All* — wipe everything and start fresh"
            ),
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD,
        )
    else:
        log.info("[bot] Waiting for chat ID — send /start to your bot in Telegram.")

    try:
        await asyncio.Event().wait()
    finally:
        observer.stop()
        observer.join()
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
