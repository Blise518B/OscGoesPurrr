"""Generate src/Images/OGP_Icon.ico -- the app icon, in the 518 green style.

A frame of THE GREEN (Neon accent) around the dark Neon surface, rising
into two solid cat ears, with "OGP" in Aldrich -- the lettering of the
app's own title. Drawn as vectors with Qt and rendered separately at every
size the .ico carries, so each size is crisp rather than a shrunken 256.

Below 24 px the letters would be a four-pixel smudge, so the tiny sizes
(tray, title bar) show the eared frame alone: at that size the silhouette
is what identifies the app.

Run from the project root:
    venv\\Scripts\\python.exe tools\\make_app_icon.py

The .ico is committed, so a build never depends on this script. Re-run it
only when the design changes; colours come from theme_tokens.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication,
                           QImage, QPainter, QPainterPath, QPen)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
import theme_tokens as T  # noqa: E402

DST = REPO / "src" / "Images" / "OGP_Icon.ico"
FONT = REPO / "src" / "Images" / "fonts" / "Aldrich-Regular.ttf"

# Every size Windows asks an .ico for, from the tray (16) to Explorer (256).
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
TEXT_MIN_SIZE = 24          # below this, the eared frame alone

GREEN = QColor(T.NEON["accent"])    # THE GREEN
SURFACE = QColor(T.NEON["bg"])      # the dark Neon surface inside the frame


def _stroke_width(size: int) -> float:
    # ~7.5 % of the icon, but never thinner than a crisp line at 16 px.
    return max(0.075 * size, 1.6)


def _geometry(size: int, w: float):
    """Frame box and ear points in pixels. The outline is inset by half a
    stroke so the line never clips at the canvas edge."""
    u = size / 100.0
    m = w / 2 + 0.6
    left, right, bottom = m, size - m, size - m
    top = 36 * u                     # where the head's top edge sits
    radius = 15 * u                  # bottom corners
    peak_y = m + 0.5 * u
    ears = (
        # outer base, peak, inner base
        ((left, top), (left + 5 * u, peak_y), (left + 34 * u, top)),
        ((right, top), (right - 5 * u, peak_y), (right - 34 * u, top)),
    )
    return (left, top, right, bottom), radius, ears


def _outline(box, radius, ears) -> QPainterPath:
    """One continuous frame whose top edge rises into the two ears."""
    left, top, right, bottom = box
    (l_out, l_peak, l_in), (r_out, r_peak, r_in) = ears
    p = QPainterPath()
    p.moveTo(left, bottom - radius)
    p.lineTo(*l_out)
    p.lineTo(*l_peak)
    p.lineTo(*l_in)
    p.lineTo(*r_in)
    p.lineTo(*r_peak)
    p.lineTo(*r_out)
    p.lineTo(right, bottom - radius)
    p.quadTo(right, bottom, right - radius, bottom)
    p.lineTo(left + radius, bottom)
    p.quadTo(left, bottom, left, bottom - radius)
    p.closeSubpath()
    return p


def _ears(ears) -> QPainterPath:
    p = QPainterPath()
    for out, peak, inner in ears:
        p.moveTo(*out)
        p.lineTo(*peak)
        p.lineTo(*inner)
        p.closeSubpath()
    return p


def _letters(box, family: str) -> QPainterPath:
    left, top, right, bottom = box
    font = QFont(family)
    font.setPixelSize(max(4, int(round((bottom - top) * 0.52))))
    font.setLetterSpacing(QFont.PercentageSpacing, 104)
    p = QPainterPath()
    p.addText(0, 0, font, "OGP")
    br = p.boundingRect()
    cx = (left + right) / 2
    cy = (top + bottom) / 2 + (bottom - top) * 0.02
    return p.translated(cx - br.center().x(), cy - br.center().y())


def render(size: int, family: str) -> Image.Image:
    """The icon at exactly `size` px, as an RGBA Pillow image."""
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    g = QPainter(img)
    g.setRenderHint(QPainter.Antialiasing, True)
    w = _stroke_width(size)
    box, radius, ears = _geometry(size, w)
    outline = _outline(box, radius, ears)
    g.fillPath(outline, SURFACE)
    g.fillPath(_ears(ears), GREEN)
    g.strokePath(outline, QPen(GREEN, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if size >= TEXT_MIN_SIZE:
        g.fillPath(_letters(box, family), GREEN)
    g.end()
    raw = bytes(img.constBits())
    # Format_ARGB32 is BGRA in memory on little-endian machines.
    return Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1).copy()


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    fid = QFontDatabase.addApplicationFont(str(FONT))
    families = QFontDatabase.applicationFontFamilies(fid)
    if not families:
        print(f"Could not load {FONT}", file=sys.stderr)
        return 1
    frames = [render(s, families[0]) for s in SIZES]
    largest = frames[-1]
    # Pillow takes the per-size renders as-is when their size matches one
    # requested; without append_images it would shrink the 256 for all.
    largest.save(DST, format="ICO", sizes=[(s, s) for s in SIZES],
                 append_images=frames[:-1])
    print(f"wrote {DST} ({', '.join(str(s) for s in SIZES)} px)")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
