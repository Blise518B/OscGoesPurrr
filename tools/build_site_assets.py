"""Generate web assets for the GitHub Pages site (docs/).

The source logo (Images/OGP_Logo_Original.png) is a black mark on an opaque
white background, which is unusable on the site's dark theme. This script
derives transparent, theme-tinted variants from it:

    docs/assets/ogp-mark.png        gradient-tinted mark, transparent (hero/nav)
    docs/assets/ogp-mark-white.png  white mark, transparent (mono uses)
    docs/assets/favicon.png         128px gradient mark (browser tab)
    docs/assets/og-cover.png        1200x630 social-share card

Re-run after changing the source logo or the brand gradient:

    python tools/build_site_assets.py

Pure-Pillow; uses numpy only if available (faster gradient fill).
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "Images", "OGP_Logo_Original.png")
OUT = os.path.join(ROOT, "docs", "assets")

# Brand gradient stops (pink -> violet -> cyan), sampled along the diagonal.
C0 = (255, 61, 154)
C1 = (168, 85, 247)
C2 = (34, 211, 238)
BG = (8, 7, 13)


def _lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _grad_color(t):
    if t < 0.5:
        return _lerp(C0, C1, t / 0.5)
    return _lerp(C1, C2, (t - 0.5) / 0.5)


def make_gradient(size):
    """Diagonal pink->violet->cyan gradient as an RGB image."""
    w, h = size
    try:
        import numpy as np

        yy, xx = np.mgrid[0:h, 0:w]
        d = (xx + yy) / float((w - 1) + (h - 1))
        t1 = np.clip(d / 0.5, 0.0, 1.0)
        t2 = np.clip((d - 0.5) / 0.5, 0.0, 1.0)

        def chan(i):
            first = C0[i] + (C1[i] - C0[i]) * t1
            second = C1[i] + (C2[i] - C1[i]) * t2
            return np.where(d < 0.5, first, second)

        rgb = np.stack([chan(0), chan(1), chan(2)], axis=-1).astype("uint8")
        return Image.fromarray(rgb, "RGB")
    except Exception:
        img = Image.new("RGB", size)
        px = img.load()
        denom = float((w - 1) + (h - 1)) or 1.0
        cache = {}
        for x in range(w):
            for y in range(h):
                d = x + y
                c = cache.get(d)
                if c is None:
                    c = _grad_color(d / denom)
                    cache[d] = c
                px[x, y] = c
        return img


def _load_font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf", "arial.ttf"):
        path = os.path.join(r"C:\Windows\Fonts", name)
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main():
    os.makedirs(OUT, exist_ok=True)

    lum = Image.open(SRC).convert("L")
    # Ink (black) -> opaque; paper (white) -> transparent. Anti-aliased edges
    # survive because alpha is a smooth function of luminance.
    alpha = lum.point(lambda p: 255 - p)

    grad = make_gradient(lum.size)
    mark = grad.convert("RGBA")
    mark.putalpha(alpha)
    mark.resize((640, 640), Image.LANCZOS).save(os.path.join(OUT, "ogp-mark.png"))

    white = Image.new("RGBA", lum.size, (240, 240, 255, 255))
    white.putalpha(alpha)
    white.resize((640, 640), Image.LANCZOS).save(
        os.path.join(OUT, "ogp-mark-white.png")
    )

    mark.resize((128, 128), Image.LANCZOS).save(os.path.join(OUT, "favicon.png"))

    # Social-share card: dark field, soft brand glow, logo + wordmark.
    cover = Image.new("RGBA", (1200, 630), BG + (255,))
    glow = make_gradient((1200, 630)).convert("RGBA")
    glow.putalpha(38)
    cover.alpha_composite(glow)
    logo = mark.resize((360, 360), Image.LANCZOS)
    cover.alpha_composite(logo, (84, 135))
    draw = ImageDraw.Draw(cover)
    draw.text((486, 214), "OscGoesPurrr", font=_load_font(92), fill=(245, 240, 255, 255))
    draw.text((490, 332), "Feel VRChat. Everywhere.", font=_load_font(42), fill=(176, 168, 208, 255))
    draw.text((490, 400), "OSC -> Bluetooth toys - SteamVR - bHaptics", font=_load_font(28), fill=(122, 116, 150, 255))
    cover.convert("RGB").save(os.path.join(OUT, "og-cover.png"))

    print("Wrote assets to", OUT)
    for f in ("ogp-mark.png", "ogp-mark-white.png", "favicon.png", "og-cover.png"):
        p = os.path.join(OUT, f)
        print(f"  {f:22} {os.path.getsize(p):>8} bytes")


if __name__ == "__main__":
    main()
