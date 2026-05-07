"""
Single command to run the full pipeline for all new videos.
Skips anything already completed. Safe to run repeatedly.

Usage:
    python3 run_pipeline.py
"""
import os
import glob
import sys
from config import RAW_MATERIAL_DIR, OUTPUTS_DIR, EXTRACTED_FRAMES_DIR

def has_output_video(video_name):
    return os.path.exists(os.path.join(OUTPUTS_DIR, "wavespeed", video_name, "output.mp4"))

def has_selected_image(video_name):
    return os.path.exists(os.path.join(OUTPUTS_DIR, "higgsfield", video_name, "selected.png"))

def has_higgsfield_images(video_name):
    return bool(glob.glob(os.path.join(OUTPUTS_DIR, "higgsfield", video_name, "output_*.png")))

def has_extracted_frame(video_name):
    return os.path.exists(os.path.join(EXTRACTED_FRAMES_DIR, f"{video_name}_frame.png"))


def run():
    videos = sorted(glob.glob(os.path.join(RAW_MATERIAL_DIR, "*.mp4")))
    if not videos:
        print("No .mp4 files found in raw material/ — nothing to do.")
        return

    names = [os.path.splitext(os.path.basename(v))[0] for v in videos]

    print(f"\n{'='*50}")
    print(f"Found {len(videos)} video(s): {', '.join(names)}")
    print(f"{'='*50}\n")

    # Classify each video
    need_frame      = [v for v in names if not has_extracted_frame(v)]
    need_higgsfield = [v for v in names if not has_higgsfield_images(v)]
    need_selection  = [v for v in names if has_higgsfield_images(v) and not has_selected_image(v) and not has_output_video(v)]
    need_wavespeed  = [v for v in names if has_selected_image(v) and not has_output_video(v)]
    already_done    = [v for v in names if has_output_video(v)]

    if already_done:
        print(f"[DONE]    Already complete: {', '.join(already_done)}")
    if need_selection:
        print(f"\n[ACTION NEEDED] These videos need you to pick a Higgsfield image first:")
        for name in need_selection:
            print(f"  → outputs/higgsfield/{name}/  (copy best one as selected.png)")
        print()

    # Step 1: Extract frames
    if need_frame:
        print(f"\n--- Step 1: Extracting frames for: {', '.join(need_frame)} ---")
        from extract_frame import extract_all
        extract_all()
    else:
        print("--- Step 1: All frames already extracted. Skipping. ---")

    # Step 2: Higgsfield
    if need_higgsfield:
        print(f"\n--- Step 2: Running Higgsfield for: {', '.join(need_higgsfield)} ---")
        from higgsfield_generate import generate_all
        generate_all()
    else:
        print("--- Step 2: All Higgsfield images already generated. Skipping. ---")

    # Recheck after higgsfield
    need_selection = [v for v in names if has_higgsfield_images(v) and not has_selected_image(v) and not has_output_video(v)]
    if need_selection:
        print(f"\n{'='*50}")
        print("PAUSING — manual selection required before Wavespeed can run.")
        print(f"{'='*50}")
        for name in need_selection:
            print(f"\n  {name}:")
            print(f"    Open: outputs/higgsfield/{name}/")
            print(f"    Pick the best image → copy & rename it to: selected.png")
        print("\nThen run this script again to complete the pipeline.")
        sys.exit(0)

    # Step 3: Wavespeed
    ready_for_wavespeed = [v for v in names if has_selected_image(v) and not has_output_video(v)]
    if ready_for_wavespeed:
        print(f"\n--- Step 3: Running Wavespeed for: {', '.join(ready_for_wavespeed)} ---")
        from wavespeed_generate import run_all
        run_all()
    else:
        print("--- Step 3: Nothing new to send to Wavespeed. ---")

    # Final summary
    done_now = [v for v in names if has_output_video(v)]
    print(f"\n{'='*50}")
    print(f"Pipeline complete. {len(done_now)}/{len(names)} video(s) done.")
    for name in names:
        status = "Done ✓" if has_output_video(name) else ("Waiting for selected.png" if has_higgsfield_images(name) else "Pending")
        print(f"  {name}: {status}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run()
