"""Generate the procedural icon for The Handy stroker.

The Handy has no scrapeable transparent product-photo set (the official
site sits behind bot protection), so like the bHaptics pieces the icon is
drawn from primitives: the upright rounded body, the sliding stroker band
with its strap, and the teal power ring near the base — the three features
that make the device read as "The Handy" at a glance.

Outputs (mirroring what flatten_lovense_icons.py derives for the photo set,
so this tool is self-contained and never wipes the other icons):

  Images/lovense_icons/the_handy.png           (400x400 catalog icon, RGBA)
  Images/flat_lovense_icons/the_handy.png      (white + alpha, full size)
  steamvr_toy_driver/icon_assets_64/the_handy.png (32x32 hardened silhouette)

Run from the project root:
    venv\\Scripts\\python.exe tools\\generate_handy_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw
import numpy as np


REPO = Path(__file__).resolve().parent.parent
CATALOG_DST = REPO / "Images" / "lovense_icons" / "the_handy.png"
FLAT_DST = REPO / "Images" / "flat_lovense_icons" / "the_handy.png"
STEAMVR_DST = REPO / "steamvr_toy_driver" / "icon_assets_64" / "the_handy.png"

# Draw at high resolution, downsample with Lanczos for smooth edges.
SOURCE_SIZE = 800
CATALOG_SIZE = 400
STEAMVR_ICON_SIZE = 32

# Same hardening constants as flatten_lovense_icons.py so the 32x32 thumb
# matches the rest of the SteamVR strip.
HARDEN_LOW_CUTOFF = 24
SILHOUETTE_HARDNESS = 1.0

# Palette — the retail device: white/light-grey body, dark stroker sleeve
# band, teal accent ring around the power button.
BODY = (236, 237, 240, 255)
BODY_EDGE = (196, 199, 206, 255)
BAND = (72, 76, 84, 255)
BAND_HIGHLIGHT = (104, 109, 118, 255)
STRAP = (52, 55, 61, 255)
TEAL = (0, 191, 179, 255)
BUTTON = (218, 221, 226, 255)


def draw_handy() -> Image.Image:
    img = Image.new("RGBA", (SOURCE_SIZE, SOURCE_SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = SOURCE_SIZE // 2

    # Body: upright slab with fully rounded ends, slightly narrower than the
    # band so the slider clearly wraps around it.
    body_half = 110
    body_top = 60
    body_bot = SOURCE_SIZE - 60
    d.rounded_rectangle(
        (cx - body_half, body_top, cx + body_half, body_bot),
        radius=body_half, fill=BODY, outline=BODY_EDGE, width=10)

    # Subtle left-edge shade line so the body doesn't read as a flat blob in
    # the colored catalog icon (the flatten pass keeps it as alpha detail).
    d.rounded_rectangle(
        (cx - body_half + 18, body_top + 18, cx - body_half + 44, body_bot - 18),
        radius=14, fill=(222, 224, 229, 255))

    # Stroker band: wide horizontal capsule across the upper body — the
    # moving part. Sits proud of the body on both sides.
    band_half_w = 190
    band_top = 250
    band_bot = 392
    d.rounded_rectangle(
        (cx - band_half_w, band_top, cx + band_half_w, band_bot),
        radius=(band_bot - band_top) // 2, fill=BAND)
    # Strap buckle blocks at the band's outer ends.
    for sx in (cx - band_half_w, cx + band_half_w):
        d.rounded_rectangle(
            (sx - 34, band_top + 16, sx + 34, band_bot - 16),
            radius=24, fill=STRAP)
    # Highlight ridge along the band top — keeps the band from merging with
    # the body in the binary silhouette.
    d.rounded_rectangle(
        (cx - band_half_w + 50, band_top + 18, cx + band_half_w - 50, band_top + 44),
        radius=13, fill=BAND_HIGHLIGHT)

    # Power button: teal ring + grey center near the base, the device's
    # signature accent.
    btn_cy = body_bot - 130
    ring_r = 52
    d.ellipse((cx - ring_r, btn_cy - ring_r, cx + ring_r, btn_cy + ring_r), fill=TEAL)
    inner_r = 32
    d.ellipse((cx - inner_r, btn_cy - inner_r, cx + inner_r, btn_cy + inner_r), fill=BUTTON)

    return img


def save_catalog(img: Image.Image) -> None:
    out = img.copy()
    out.thumbnail((CATALOG_SIZE, CATALOG_SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (CATALOG_SIZE, CATALOG_SIZE), (0, 0, 0, 0))
    canvas.paste(out, ((CATALOG_SIZE - out.width) // 2, (CATALOG_SIZE - out.height) // 2), out)
    CATALOG_DST.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(CATALOG_DST, optimize=True)


def flatten_white(img: Image.Image) -> Image.Image:
    """White RGB + luminance-modulated alpha, like flatten_lovense_icons."""
    arr = np.asarray(img, dtype=np.float32)
    rgb, alpha = arr[:, :, :3], arr[:, :, 3]
    luminance = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]
    body = alpha >= 32
    median = max(1.0, float(np.median(luminance[body])))
    detail = np.clip(luminance * (210.0 / median), 0.0, 255.0) / 255.0
    envelope = 0.3 + 0.7 * detail  # DETAIL_STRENGTH = 0.7
    out = np.zeros_like(arr, dtype=np.uint8)
    out[:, :, :3] = 255
    out[:, :, 3] = np.clip(alpha * envelope, 0.0, 255.0).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def save_steamvr_thumb(img: Image.Image) -> None:
    img = img.copy()
    img.thumbnail((STEAMVR_ICON_SIZE, STEAMVR_ICON_SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (STEAMVR_ICON_SIZE, STEAMVR_ICON_SIZE), (0, 0, 0, 0))
    canvas.paste(img, ((STEAMVR_ICON_SIZE - img.width) // 2,
                       (STEAMVR_ICON_SIZE - img.height) // 2), img)
    arr = np.asarray(canvas, dtype=np.uint8).copy()
    alpha = arr[:, :, 3].astype(np.float32)
    alpha = np.where(alpha < HARDEN_LOW_CUTOFF, 0.0, alpha)
    binary = np.where(alpha > 0.0, 255.0, 0.0)
    hardened = (1.0 - SILHOUETTE_HARDNESS) * alpha + SILHOUETTE_HARDNESS * binary
    arr[:, :, 3] = np.clip(hardened, 0.0, 255.0).astype(np.uint8)
    STEAMVR_DST.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr, "RGBA").save(STEAMVR_DST, optimize=True)


def main() -> int:
    big = draw_handy()
    save_catalog(big)
    flat = flatten_white(big)
    FLAT_DST.parent.mkdir(parents=True, exist_ok=True)
    flat.save(FLAT_DST, optimize=True)
    save_steamvr_thumb(flat)
    print(f"  {CATALOG_DST.relative_to(REPO)}")
    print(f"  {FLAT_DST.relative_to(REPO)}")
    print(f"  {STEAMVR_DST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
