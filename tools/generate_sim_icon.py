"""Generate Images/OGP_Sim_Icon.ico — a tinted variant of OGP_Icon.ico with
a corner play-badge so the simulator is unmistakable in the taskbar, Alt-Tab,
and Explorer.

The source icon is a black silhouette on transparent, so a hue rotation
would be a no-op. Instead we recolour the silhouette to a saturated tint
(luminance preserved → existing shading still reads) and overlay a play-arrow
badge for redundancy at small sizes where colour alone may not be enough.

Run from the project root:
    venv\\Scripts\\python.exe tools\\generate_sim_icon.py

The output is committed to the repo so the build scripts do not depend on
Pillow / numpy at build time. Re-run only when the source icon or styling
changes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "Images" / "OGP_Icon.ico"
DST = REPO / "Images" / "OGP_Sim_Icon.ico"

# Strong teal — clearly distinct from the main app's black-on-white identity
# at any size, and survives the taskbar's small icon footprint well.
TINT_RGB = (0, 178, 196)

# Sizes baked into the .ico. Windows picks the best match per surface
# (16/32 for taskbar + tray, 48 for Alt-Tab, 256 for Explorer thumbnails).
ICO_SIZES = [256, 128, 64, 48, 32, 16]


def colorize_silhouette(rgba: np.ndarray, tint: tuple[int, int, int]) -> np.ndarray:
    """Re-render the icon as a transparent-background tinted silhouette.

    The source is a black drawing on a white background (not a transparent
    PNG), so the "shape" lives in luminance, not the alpha channel. We
    derive a new alpha from inverse luminance — dark ink pixels become
    opaque tint, the white background drops to fully transparent — and
    multiply by the source alpha so any genuine transparency is honoured.
    """
    rgb = rgba[..., :3].astype(np.float32)
    src_alpha = rgba[..., 3].astype(np.float32)
    # ITU-R BT.601 luma — same weighting the lovense-icon flattener uses.
    lum = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    ink = 1.0 - (lum / 255.0)
    new_alpha = np.clip(ink * (src_alpha / 255.0) * 255.0, 0.0, 255.0)
    out = np.empty_like(rgba)
    out[..., 0] = tint[0]
    out[..., 1] = tint[1]
    out[..., 2] = tint[2]
    out[..., 3] = new_alpha.astype(np.uint8)
    return out


def add_play_badge(img: Image.Image) -> Image.Image:
    """Bottom-right play-arrow badge — preserves distinguishability even when
    the image is greyscaled or shown next to the main icon at small sizes."""
    img = img.convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    pad = max(1, w // 20)
    badge = max(8, w * 7 // 20)
    x0 = w - badge - pad
    y0 = h - badge - pad
    x1 = x0 + badge
    y1 = y0 + badge

    outline = max(1, w // 64)
    draw.ellipse(
        (x0, y0, x1, y1),
        fill=(255, 255, 255, 235),
        outline=(20, 20, 20, 235),
        width=outline,
    )

    inset = badge // 4
    # Visually centre the triangle: a right-pointing triangle's optical
    # centre sits a bit left of its geometric centre.
    nudge = badge // 16
    tri = [
        (x0 + inset - nudge,         y0 + inset),
        (x0 + inset - nudge,         y1 - inset),
        (x1 - inset - nudge // 2,    (y0 + y1) // 2),
    ]
    draw.polygon(tri, fill=(20, 20, 20, 255))
    return Image.alpha_composite(img, overlay)


def main() -> int:
    if not SRC.exists():
        print(f"Source icon missing: {SRC}")
        return 1

    base = Image.open(SRC).convert("RGBA")
    # Operate at the highest resolution available — downscaling preserves
    # quality better than upscaling later.
    if base.size != (256, 256):
        base = base.resize((256, 256), Image.LANCZOS)

    arr = np.asarray(base)
    tinted = Image.fromarray(colorize_silhouette(arr, TINT_RGB), "RGBA")
    badged = add_play_badge(tinted)

    # Pillow auto-generates the requested sizes from the source. Provide the
    # 256x256 master so each downsize starts from the cleanest possible image.
    badged.save(DST, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"Wrote {DST} ({', '.join(f'{s}x{s}' for s in ICO_SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
