"""Generate procedural bHaptics suit-piece silhouettes for the SteamVR strip.

bHaptics is a family of haptic peripherals (TactSuit, Tactosy etc.), not a
single retail product line we can scrape product photos for — so unlike the
Lovense flow there is no source-photo set to flatten. Instead we draw small
high-contrast silhouettes from primitives (ellipses, rounded rects) and feed
them through the same hardening pass that flatten_lovense_icons.py uses, so
the output matches the SlimeVR / Standable visual language of binary
silhouettes against SteamVR's tinted strip.

Produced files (white RGB + alpha-mask PNG, matching the lovense_icons set):

  Images/bhaptics_icons/<key>.png            (256x256 preview)
  steamvr_toy_driver/icon_assets_64/<key>.png (32x32 runtime asset)

Keys:
  bhaptics_head, bhaptics_vest, bhaptics_arm, bhaptics_hand, bhaptics_foot

The five icons cover the nine bHaptics device positions — left/right pairs
share a silhouette (the strip is too small for L/R differentiation to read).

Run from the project root:
    venv\\Scripts\\python.exe tools\\generate_bhaptics_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
import numpy as np


REPO = Path(__file__).resolve().parent.parent
PREVIEW_DST = REPO / "Images" / "bhaptics_icons"
STEAMVR_DST = REPO / "steamvr_toy_driver" / "icon_assets_64"

# High-res canvas size we draw on; downsampled to STEAMVR_ICON_SIZE with
# Lanczos. Larger source = smoother curves once shrunk.
SOURCE_SIZE = 256
STEAMVR_ICON_SIZE = 32  # matches the lovense flow + SlimeVR canonical size

# Hardening pass — identical defaults to flatten_lovense_icons.py so the
# bhaptics silhouettes render with the same crisp outline as the toy icons.
HARDEN_LOW_CUTOFF = 24
SILHOUETTE_HARDNESS = 1.0


def _new_canvas() -> Image.Image:
    return Image.new("RGBA", (SOURCE_SIZE, SOURCE_SIZE), (0, 0, 0, 0))


def _white_brush() -> tuple[int, int, int, int]:
    # All silhouettes paint pure white with full alpha so SteamVR's tinted
    # gradient can colour them in the same way it tints the lovense icons.
    return (255, 255, 255, 255)


def _rounded_rect(d: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int,
                  r: int, fill) -> None:
    d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=fill)


# ---- Individual silhouettes ----------------------------------------------
# Each draw_* function paints a centred, ~80% canvas-filling shape so once
# resized to 32x32 the silhouette has a clean 2-3px transparent margin.

def draw_head() -> Image.Image:
    img = _new_canvas()
    d = ImageDraw.Draw(img)
    w = _white_brush()
    cx = SOURCE_SIZE // 2
    # Head: oval slightly taller than wide.
    head_w, head_h = 140, 168
    head_top = 28
    d.ellipse((cx - head_w // 2, head_top,
               cx + head_w // 2, head_top + head_h), fill=w)
    # Neck: short trapezoid tucked into the head ellipse.
    neck_top = head_top + head_h - 12
    neck_bottom = neck_top + 36
    neck_half_top = 30
    neck_half_bot = 42
    d.polygon([
        (cx - neck_half_top, neck_top),
        (cx + neck_half_top, neck_top),
        (cx + neck_half_bot, neck_bottom),
        (cx - neck_half_bot, neck_bottom),
    ], fill=w)
    # Shoulder hint: thin bar across the bottom so the head reads as
    # "tactal headset" rather than a floating skull.
    bar_top = neck_bottom
    bar_bot = bar_top + 18
    _rounded_rect(d, cx - 100, bar_top, cx + 100, bar_bot, 8, fill=w)
    return img


def draw_vest() -> Image.Image:
    img = _new_canvas()
    d = ImageDraw.Draw(img)
    w = _white_brush()
    cx = SOURCE_SIZE // 2

    # Body: a single solid trapezoid with shoulder caps and a V-neck cut.
    # No arm-hole cut-outs — at 32x32 they fragment the body into separate
    # blobs that don't read as a vest. Shoulder caps are drawn as wide
    # ellipses on top of the trapezoid so the silhouette has a clear
    # "yoke" shape and the V-neck reads correctly.
    shoulder_y = 64
    waist_y = 220
    shoulder_half = 102
    waist_half = 84
    d.polygon([
        (cx - shoulder_half, shoulder_y),
        (cx + shoulder_half, shoulder_y),
        (cx + waist_half, waist_y),
        (cx - waist_half, waist_y),
    ], fill=w)
    # Rounded waist bottom — single wide ellipse at the bottom edge.
    d.ellipse((cx - waist_half, waist_y - 36, cx + waist_half, waist_y + 36), fill=w)
    # Rounded shoulder caps so the silhouette doesn't have hard square
    # corners at the top — same effect as flat-cap-vs-rounded-cap on a rect.
    cap_h = 36
    d.ellipse((cx - shoulder_half, shoulder_y - cap_h // 2,
               cx + shoulder_half, shoulder_y + cap_h // 2), fill=w)

    # V-neck cut-out — punched into the top centre after the body is drawn.
    # Drawn with ALPHA=0 fill, which directly writes transparent pixels
    # (PIL.ImageDraw does not alpha-composite — it writes raw RGBA).
    neck_w = 36
    neck_depth = 56
    d.polygon([
        (cx - neck_w, shoulder_y - 12),
        (cx + neck_w, shoulder_y - 12),
        (cx, shoulder_y + neck_depth),
    ], fill=(0, 0, 0, 0))
    return img


def draw_arm() -> Image.Image:
    img = _new_canvas()
    d = ImageDraw.Draw(img)
    w = _white_brush()
    cx = SOURCE_SIZE // 2

    # Forearm: slightly tapered rounded rectangle, with a small "hand bump"
    # at the bottom so it reads as an arm with a wrist rather than a
    # featureless capsule.
    top_half = 44
    bot_half = 34
    top_y = 40
    bot_y = 210
    arm_poly = [
        (cx - top_half, top_y),
        (cx + top_half, top_y),
        (cx + bot_half, bot_y),
        (cx - bot_half, bot_y),
    ]
    d.polygon(arm_poly, fill=w)
    # Cap the ends so the silhouette is rounded rather than flat-cut.
    d.ellipse((cx - top_half, top_y - top_half, cx + top_half, top_y + top_half), fill=w)
    d.ellipse((cx - bot_half, bot_y - bot_half, cx + bot_half, bot_y + bot_half), fill=w)
    return img


def draw_hand() -> Image.Image:
    img = _new_canvas()
    d = ImageDraw.Draw(img)
    w = _white_brush()
    cx = SOURCE_SIZE // 2

    # Mitten silhouette: palm + thumb. Avoid drawing five fingers because
    # at 32x32 they smear into a single blob; a mitten silhouette is the
    # most legible "hand" shape at that size.
    palm_top = 80
    palm_bot = 220
    palm_half_top = 60
    palm_half_bot = 50
    palm_poly = [
        (cx - palm_half_top, palm_top),
        (cx + palm_half_top, palm_top),
        (cx + palm_half_bot, palm_bot),
        (cx - palm_half_bot, palm_bot),
    ]
    d.polygon(palm_poly, fill=w)
    # Round palm top + bottom.
    d.ellipse((cx - palm_half_top, palm_top - palm_half_top,
               cx + palm_half_top, palm_top + palm_half_top), fill=w)
    d.ellipse((cx - palm_half_bot, palm_bot - palm_half_bot,
               cx + palm_half_bot, palm_bot + palm_half_bot), fill=w)
    # Thumb: oval offset to the side.
    thumb_cx = cx - 80
    thumb_cy = palm_top + 56
    thumb_w, thumb_h = 44, 80
    d.ellipse((thumb_cx - thumb_w // 2, thumb_cy - thumb_h // 2,
               thumb_cx + thumb_w // 2, thumb_cy + thumb_h // 2), fill=w)
    return img


def draw_foot() -> Image.Image:
    img = _new_canvas()
    d = ImageDraw.Draw(img)
    w = _white_brush()

    # Side-view shoe: heel + arch + toe. Drawn as a fat rounded rectangle
    # for the sole + an ellipse for the heel rise so the shape reads as
    # "footwear" rather than "loaf of bread".
    sole_top = 150
    sole_bot = 208
    sole_left = 28
    sole_right = SOURCE_SIZE - 28
    _rounded_rect(d, sole_left, sole_top, sole_right, sole_bot, 28, fill=w)

    # Heel rise — ellipse anchored at the back of the sole.
    heel_w, heel_h = 110, 130
    heel_cx = sole_left + heel_w // 2 + 6
    heel_cy = sole_top - heel_h // 2 + 40
    d.ellipse((heel_cx - heel_w // 2, heel_cy - heel_h // 2,
               heel_cx + heel_w // 2, heel_cy + heel_h // 2), fill=w)

    # Toe taper — ellipse anchored at the front.
    toe_w, toe_h = 90, 90
    toe_cx = sole_right - toe_w // 2 - 4
    toe_cy = sole_top + 6
    d.ellipse((toe_cx - toe_w // 2, toe_cy - toe_h // 2,
               toe_cx + toe_w // 2, toe_cy + toe_h // 2), fill=w)
    return img


# ---- Resize + harden pass (mirrors flatten_lovense_icons.save_steamvr_thumb)

def save_steamvr_thumb(img: Image.Image, dst_path: Path) -> None:
    img = img.copy()
    img.thumbnail((STEAMVR_ICON_SIZE, STEAMVR_ICON_SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (STEAMVR_ICON_SIZE, STEAMVR_ICON_SIZE), (0, 0, 0, 0))
    x = (STEAMVR_ICON_SIZE - img.width) // 2
    y = (STEAMVR_ICON_SIZE - img.height) // 2
    canvas.paste(img, (x, y), img)

    arr = np.asarray(canvas, dtype=np.uint8).copy()
    alpha = arr[:, :, 3].astype(np.float32)
    # 1) Knock background (very low alpha) to fully transparent.
    alpha_zeroed = np.where(alpha < HARDEN_LOW_CUTOFF, 0.0, alpha)
    # 2) At hardness=1.0 every remaining pixel snaps to fully opaque.
    binary = np.where(alpha_zeroed > 0.0, 255.0, 0.0)
    hardened = (1.0 - SILHOUETTE_HARDNESS) * alpha_zeroed + SILHOUETTE_HARDNESS * binary
    arr[:, :, 3] = np.clip(hardened, 0.0, 255.0).astype(np.uint8)
    Image.fromarray(arr, "RGBA").save(dst_path, optimize=True)


ICONS = [
    ("bhaptics_head", draw_head),
    ("bhaptics_vest", draw_vest),
    ("bhaptics_arm",  draw_arm),
    ("bhaptics_hand", draw_hand),
    ("bhaptics_foot", draw_foot),
]


def main() -> int:
    PREVIEW_DST.mkdir(parents=True, exist_ok=True)
    STEAMVR_DST.mkdir(parents=True, exist_ok=True)

    for key, draw in ICONS:
        big = draw()
        preview_path = PREVIEW_DST / f"{key}.png"
        small_path = STEAMVR_DST / f"{key}.png"
        big.save(preview_path, optimize=True)
        save_steamvr_thumb(big, small_path)
        print(f"  {key}: {preview_path.name} + {small_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
