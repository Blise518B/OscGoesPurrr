"""Normalize the colour-variability across the Lovense product photos.

Some product photos are pink/red, some are matte black, some are translucent
white — so a uniform "alpha threshold" silhouette pass makes the dark toys
disappear into the strip's tinted gradient while the light ones look fine.

This script normalises each photo so the toy body lands at a consistent
brightness, then outputs:

    Images/flat_lovense_icons/<key>.png

The output PNG has:
  * RGB = pure white (so the app UI can tint freely)
  * Alpha = mask shaped like the original, modulated by the photo's
    *normalised* luminance, so contour highlights / shadows survive as
    relative alpha variations rather than the raw colour differences.

Run from the project root:
    venv\\Scripts\\python.exe tools\\flatten_lovense_icons.py

The output folder gets recreated on each run.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PIL import Image
import numpy as np


REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "Images" / "lovense_icons"
DST = REPO / "src" / "Images" / "flat_lovense_icons"

# Body pixels are anything with at least this much alpha in the source. Tight
# enough to ignore soft anti-aliased fringe pixels, loose enough not to crop
# the silhouette.
ALPHA_BODY_THRESHOLD = 32

# Target median luminance for the normalised body, on the 0..255 scale. We
# pick something close to "bright cream" so light toys aren't crushed up to
# full white and dark toys still leave room above the median for highlight
# detail.
TARGET_BODY_LUMINANCE = 210.0

# Detail-preservation strength. 1.0 = full luminance variation kept in the
# output alpha. 0.0 = flat opaque silhouette (no interior detail). Values
# between 0.5 and 0.8 give visible contour detail without making the icon
# look "smoky" when a gradient blends through it.
DETAIL_STRENGTH = 0.7

# Hardness applied AFTER the icon is resized to its strip size. Standable
# / SlimeVR icons are essentially binary — fully opaque body or fully
# transparent background, no soft anti-aliased fringe — which is why they
# render crisply through a gradient.
#
#   0.0  = leave the soft alpha alone (gradient bleed at edges)
#   1.0  = fully binary (any alpha > LOW threshold becomes 255, rest is 0)
#   0.x  = quantise into a few alpha levels — keeps subtle interior detail
#          while still giving a crisp outer outline.
#
# 1.0 produces the cleanest look; lower
# values keep more contour detail at the cost of slightly fuzzier edges.
SILHOUETTE_HARDNESS = 1.0

# Alpha threshold for the hardening pass. Pixels below this become fully
# transparent; pixels above become fully opaque (at hardness=1) or get
# quantised to one of a few opacity steps (at hardness<1).
HARDEN_LOW_CUTOFF = 24


def normalise_one(src_path: Path, dst_path: Path) -> str:
    img = Image.open(src_path).convert("RGBA")
    arr = np.asarray(img, dtype=np.float32)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]

    # ITU-R BT.601 luma — perceptual brightness with the standard weights.
    luminance = 0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]

    body_mask = alpha >= ALPHA_BODY_THRESHOLD
    if not body_mask.any():
        return f"{src_path.name}: empty (no opaque pixels)"

    # Median is robust to highlights and shadows that would skew the mean.
    body_median = float(np.median(luminance[body_mask]))
    if body_median < 1.0:
        body_median = 1.0
    scale = TARGET_BODY_LUMINANCE / body_median
    normalised = np.clip(luminance * scale, 0.0, 255.0)

    # Convert normalised luminance to a per-pixel detail factor in [0,1].
    # detail_factor=1 means "fully opaque part of the toy body"; values
    # below 1 are darker interior crevices that should show as relatively
    # thinner / more transparent regions.
    detail_factor = normalised / 255.0
    # Mix detail_factor with full opacity according to DETAIL_STRENGTH so
    # we can dial how much contour detail survives vs how flat the icon
    # looks. At strength=0 every body pixel is fully opaque; at strength=1
    # the detail is purely the normalised luminance map.
    alpha_envelope = (1.0 - DETAIL_STRENGTH) + DETAIL_STRENGTH * detail_factor

    new_alpha = alpha * alpha_envelope
    new_alpha = np.clip(new_alpha, 0.0, 255.0).astype(np.uint8)

    # Output: white RGB, modulated alpha. Pre-multiplied alpha isn't
    # required — PySide6 handles straight-alpha PNGs fine.
    out = np.zeros_like(arr, dtype=np.uint8)
    out[:, :, 0] = 255
    out[:, :, 1] = 255
    out[:, :, 2] = 255
    out[:, :, 3] = new_alpha

    final = Image.fromarray(out, "RGBA")
    final.save(dst_path, optimize=True)
    return final, f"{src_path.name}: body_median={body_median:5.1f} scale={scale:.2f}"


def main() -> int:
    if not SRC.is_dir():
        print(f"Source folder missing: {SRC}", file=sys.stderr)
        return 1

    # Clear + recreate the destinations so runs are reproducible. We delete
    # contents file-by-file rather than rmtree-ing the directory itself —
    # Windows occasionally locks an empty directory (Explorer thumbnail
    # service, file watcher, etc.) which would otherwise fail the rmtree
    # but is happy with file-level deletes.
    DST.mkdir(parents=True, exist_ok=True)
    for f in DST.iterdir():
        try:
            if f.is_file():
                f.unlink()
        except OSError:
            pass

    pngs = sorted(p for p in SRC.iterdir() if p.suffix.lower() == ".png")
    if not pngs:
        print(f"No PNGs in {SRC}", file=sys.stderr)
        return 1

    print(f"Normalising {len(pngs)} icons")
    print(f"  flat preview  -> {DST}")
    for src in pngs:
        try:
            _img, note = normalise_one(src, DST / src.name)
            print(f"  {note}")
        except Exception as e:
            print(f"  {src.name}: FAILED ({e})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
