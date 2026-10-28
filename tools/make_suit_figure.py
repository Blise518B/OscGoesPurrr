"""Turn the two cat girl drawings into the Suits page's figure images.

  src/Images/suits/front.png   her front, the box FIG_BOX of the drawing
  src/Images/suits/back.png    her back, the same box

The drawings (1024 x 1536, green line art on transparency, made with
ChatGPT's image generator from Blise's brief, 2026-10-28) keep only their
lines: every pixel turns white with the drawing's alpha, so the page can
tint her in the accent at paint time and she follows the colour picker.
They are cropped to the box every dot of ui/views/body_view.py is placed
in and scaled to SCALE, which is still sharper than the page ever shows
her. The images are committed; re-run this only for new drawings, and
check the dots still land (body_view.py's coordinates are the drawing's).

Run from the project root:
    venv\\Scripts\\python.exe tools\\make_suit_figure.py <front.png> <back.png>
"""

import sys
from pathlib import Path

from PIL import Image

FIG_BOX = (255, 20, 790, 1500)        # x0, y0, x1, y1 in the drawing's pixels
SCALE = 0.75
OUT = Path(__file__).resolve().parent.parent / "src" / "Images" / "suits"


def convert(src: str, dst: Path) -> None:
    im = Image.open(src).convert("RGBA")
    if im.size != (1024, 1536):
        sys.exit(f"{src}: expected 1024 x 1536, got {im.size[0]} x {im.size[1]}")
    alpha = im.getchannel("A").crop(FIG_BOX)
    w, h = alpha.size
    alpha = alpha.resize((round(w * SCALE), round(h * SCALE)), Image.LANCZOS)
    lines = Image.new("LA", alpha.size, 255)
    lines.putalpha(alpha)
    lines.save(dst, optimize=True)
    print(f"{dst.name}: {lines.size[0]} x {lines.size[1]}, {dst.stat().st_size // 1024} KB")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    OUT.mkdir(parents=True, exist_ok=True)
    convert(sys.argv[1], OUT / "front.png")
    convert(sys.argv[2], OUT / "back.png")


if __name__ == "__main__":
    main()
