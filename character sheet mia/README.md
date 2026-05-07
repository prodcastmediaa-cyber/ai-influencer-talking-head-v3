# Character Sheet — Mia

Place your AI character's reference image in this folder.

## Required file

`mia-main.png` — This is the identity source for all generated images.

## What this image should look like

- Clear, front-facing photo of your character's face
- Good lighting, sharp focus
- Neutral or simple background works best
- High resolution (at least 1080x1080)

## How it is used

This image is passed as **Reference Image 1** to the Higgsfield `nano_banana_2` model.

The prompt instructs the model to copy:
- Face structure
- Skin color and tone
- Hair (style, color, texture)
- Overall identity and look

The scene, clothing, pose, and background always come from the original video — only the identity is replaced with this character.

## Tip

If you want to test with a different character, just swap `mia-main.png` for another image with the same filename.
