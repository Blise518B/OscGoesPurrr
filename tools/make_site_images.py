"""Generate the website's images in docs/assets/ from the app icon.

  ogp-icon.svg          the icon as vectors, letters as outlines, so the page
                        shows it crisp at any size without needing Aldrich
  favicon.ico           the app's own .ico (its 16 px frame drops the letters)
  apple-touch-icon.png  180 px, for phone home screens
  og-card.png           1200 x 630 link preview (Discord, X, ...)
  download-badge.svg    the README's big "Download for Windows" button,
                        the same button every 518 app's README carries

Everything is drawn from tools/make_app_icon.py's geometry and coloured from
theme_tokens.py, so the site and the app can't drift apart. The images are
committed; re-run this only when the icon or the tagline changes.

Run from the project root:
    venv\\Scripts\\python.exe tools\\make_site_images.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_app_icon as icon  # noqa: E402  (sets the offscreen platform)

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication,  # noqa: E402
                           QImage, QPainter, QPainterPath, QPen)

T = icon.T
OUT = icon.REPO / "docs" / "assets"
TAGLINE = "Every touch in VRChat, felt for real."
SUBLINE = "VRChat OSC \u2192 Bluetooth toys via Intiface \u00b7 free for Windows"
SEGOE = Path(r"C:\Windows\Fonts\segoeui.ttf")
# The release asset's stable name: the README button links to
# releases/latest/download/<this>, so it must never carry a version.
STABLE_ASSET = "OscGoesPurrr-Windows.exe"


def _load_font(path: Path) -> str | None:
    if not path.exists():
        return None
    families = QFontDatabase.applicationFontFamilies(
        QFontDatabase.addApplicationFont(str(path)))
    return families[0] if families else None


def _svg_path(p: QPainterPath) -> str:
    """A QPainterPath as SVG path data. Qt stores every curve as a cubic:
    a CurveTo element (first control point) plus two data elements."""
    out, i, n = [], 0, p.elementCount()
    while i < n:
        e = p.elementAt(i)
        if e.type == QPainterPath.MoveToElement:
            out.append(f"M{e.x:.2f} {e.y:.2f}")
        elif e.type == QPainterPath.LineToElement:
            out.append(f"L{e.x:.2f} {e.y:.2f}")
        elif e.type == QPainterPath.CurveToElement:
            c2, end = p.elementAt(i + 1), p.elementAt(i + 2)
            out.append(f"C{e.x:.2f} {e.y:.2f} {c2.x:.2f} {c2.y:.2f} "
                       f"{end.x:.2f} {end.y:.2f}")
            i += 2
        i += 1
    return "".join(out) + "Z"


def write_svg(family: str) -> None:
    size = 256
    w = icon._stroke_width(size)
    box, radius, ears = icon._geometry(size, w)
    outline = icon._outline(box, radius, ears)
    green, surface = T.NEON["accent"], T.NEON["bg"]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'role="img" aria-label="OscGoesPurrr">'
        f'<path fill="{surface}" d="{_svg_path(outline)}"/>'
        f'<path fill="{green}" d="{_svg_path(icon._ears(ears))}"/>'
        f'<path fill="none" stroke="{green}" stroke-width="{w:.2f}" '
        f'stroke-linejoin="round" stroke-linecap="round" d="{_svg_path(outline)}"/>'
        f'<path fill="{green}" d="{_svg_path(icon._letters(box, family))}"/>'
        f'</svg>\n')
    (OUT / "ogp-icon.svg").write_text(svg, encoding="utf-8")


def write_download_badge() -> None:
    """The README button, laid out like FFmpegStudio518's and
    VRCParameterRelay's: a dark pill framed in the green, the call to
    action on top and the file it fetches underneath. GitHub shows an SVG
    through an <img>, so the text uses system fonts, not Aldrich."""
    bg, green, muted = T.NEON["bg"], T.NEON["accent"], T.NEON["muted"]
    font = "Segoe UI, Arial, sans-serif"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="56" role="img" '
        'aria-label="Download for Windows">\n'
        f'  <rect x="1.5" y="1.5" width="317" height="53" rx="12" fill="{bg}" '
        f'stroke="{green}" stroke-width="3"/>\n'
        f'  <text x="160" y="26" text-anchor="middle" font-family="{font}" font-size="17" '
        f'font-weight="700" fill="{green}">⬇&#160;&#160;DOWNLOAD FOR WINDOWS</text>\n'
        f'  <text x="160" y="44" text-anchor="middle" font-family="{font}" font-size="11" '
        f'fill="{muted}">{STABLE_ASSET} · latest release</text>\n'
        '</svg>\n')
    (OUT / "download-badge.svg").write_text(svg, encoding="utf-8")


def _qimage(pil_img) -> QImage:
    data = pil_img.tobytes("raw", "BGRA")
    return QImage(data, pil_img.width, pil_img.height,
                  QImage.Format_ARGB32).copy()


def write_og_card(title_family: str, body_family: str) -> None:
    W, H = 1200, 630
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor(T.NEON["bg"]))
    g = QPainter(img)
    g.setRenderHint(QPainter.Antialiasing, True)
    g.setRenderHint(QPainter.TextAntialiasing, True)

    # the card the whole thing sits on: --card ground, the --line frame
    g.setPen(QPen(QColor(T.NEON["line"]), 2))
    g.setBrush(QColor(T.NEON["card"]))
    g.drawRoundedRect(QRectF(40, 40, W - 80, H - 80), 24, 24)

    g.drawImage(96, 165, _qimage(icon.render(300, title_family)))

    x = 450
    f = QFont(title_family)
    f.setPixelSize(76)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 2)
    g.setFont(f)
    g.setPen(QColor(T.NEON["accent"]))
    g.drawText(x, 270, "OscGoesPurrr")

    f = QFont(body_family)
    f.setPixelSize(38)
    g.setFont(f)
    g.setPen(QColor(T.NEON["txt"]))
    g.drawText(x, 345, TAGLINE)

    f.setPixelSize(25)
    g.setFont(f)
    g.setPen(QColor(T.NEON["muted"]))
    g.drawText(x, 395, SUBLINE)

    # three chips, the header-chip pattern: --card pill, --line border
    f.setPixelSize(22)
    g.setFont(f)
    cx = x
    for text in ("One file", "Updates itself", "Open source"):
        tw = g.fontMetrics().horizontalAdvance(text)
        r = QRectF(cx, 432, tw + 36, 44)
        g.setPen(QPen(QColor(T.NEON["line"]), 2))
        g.setBrush(QColor(T.NEON["panel"]))
        g.drawRoundedRect(r, 22, 22)
        g.setPen(QColor(T.NEON["accent"]))
        g.drawText(r, Qt.AlignCenter, text)
        cx += tw + 52
    g.end()
    img.save(str(OUT / "og-card.png"))


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    title = _load_font(icon.FONT)
    if not title:
        print(f"Could not load {icon.FONT}", file=sys.stderr)
        return 1
    body = _load_font(SEGOE) or title
    OUT.mkdir(parents=True, exist_ok=True)
    write_svg(title)
    shutil.copyfile(icon.DST, OUT / "favicon.ico")
    icon.render(180, title).save(OUT / "apple-touch-icon.png")
    write_og_card(title, body)
    write_download_badge()
    print(f"wrote ogp-icon.svg, favicon.ico, apple-touch-icon.png, og-card.png, "
          f"download-badge.svg to {OUT}")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
