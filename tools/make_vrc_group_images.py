"""Draw the OGP VRChat group's banner, icon and gallery into docs/vrchat-group/.

  banner.png   2000 x 1125, the group's banner (vrchat.com -> the group ->
               Banner; VRC+ needed to change it)
  icon.png     1024 x 1024, the group's icon; VRChat shows it as a circle
  gallery-<n>-<page>.png
               1920 x 1080, for the group's gallery: the real app, rendered
               headless on demo data (tools/app_shots.py) -- first every page
               fanned out under the slogan, then a page a card with its
               steps (ui/page_steps.py) ringed and pointed at

VRChat shows the one 16:9 banner in many crops, and the new nameplates
(open beta 1878, July 2026) moved all of them. VRChat's own template is
still a draft ("NOT FINAL", attached to feedback post 1878 on 2026-08-06);
its zones are measured from that image below, next to the live client's,
measured in game by the community tool the VRChat wiki links
(tokage-lab.com's Group Banner Creator). The guides from 2023 are for the
old nameplates. On the 2000 x 1125 canvas:

  nameplate, menu closed   VRChat's "always shown" dome, x 466-1534,
                           y 323-551; a long name can crop its top to 405
  nameplate, menu open     x 311-1688, y 323-551
  nameplate, long name     "sometimes": the full width, y 322-790, but
                           never the arch behind the plate (x 496-1502,
                           y 553-790)
  group page in game       the full width, y 394-731, dimmed to 75 %
  compact card in game     the full width, y 158 down
  website                  the whole image (the group list at 256 x 144);
                           an event without a picture shows it cropped
                           to fit, the bottom third under its title bar

So the name sits where every nameplate shows it (inside the dome, below
405 and above the live client's 534), the tagline and the three things OGP
drives under it, where only the group pages show them, and the icon above,
which only the website and the compact card show. When VRChat publishes
the final template (or the nameplate-only upload it promised), change the
zones here and re-run.

Uploads must be under 10 MB and are scaled down above 2048 px.

Run from the project root:
    venv\\Scripts\\python.exe tools\\make_vrc_group_images.py [--sheet out.png]

--sheet also draws the banner with every zone outlined and each crop the
way VRChat shows it, to check a change against.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

# the stock 518 green in Neon, not whatever this PC's OGP is set to
os.environ["OGP_UI_ACCENT"] = "default"
os.environ["OGP_UI_MODE"] = "neon"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_app_icon as icon  # noqa: E402  (sets the offscreen platform)
import make_menu_icons as menu  # noqa: E402  (points offscreen Qt at the system fonts)
import make_site_images as site  # noqa: E402

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QImage,  # noqa: E402
                           QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QRadialGradient)

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import app_shots  # noqa: E402
from ui import icons as ui_icons  # noqa: E402
from ui import page_steps  # noqa: E402
from ui import theme as ui_theme  # noqa: E402
from version import VERSION  # noqa: E402

T = icon.T
OUT = icon.REPO / "docs" / "vrchat-group"
W, H = 2000, 1125
ICON = 1024
URL = "blise518b.github.io/OscGoesPurrr"
FACTS = "Free & open source  ·  Windows & Linux  ·  " + URL
# the three things OGP drives, each with its one icon (ui.icons)
CHIPS = (("toys", "Toys"), ("shock", "Shockers"), ("params", "Avatar Remote"))

# VRChat's draft template, measured from its image: (x0, y0, x1, y1, rx, ry),
# a box whose top corners are quarter ellipses.
DOME = (466, 323, 1534, 551, 320, 228)        # nameplate, menu closed
EXPANDED = (311, 323, 1688, 551, 48, 48)      # nameplate, menu open
LONG_NAME_Y = 405                             # a long name can crop the dome to here
BAND = (0, 322, W, 790)                       # nameplate, "sometimes shown"
ARCH = (496, 553, 1502, 790, 264, 237)        # behind the plate: never shown
# The live client, measured in game.
LIVE_SHORT = (324, 317, 1672, 534, 240, 240)  # nameplate, short name
LIVE_BOTTOM = 534                             # the plate covers everything below
GROUP_PAGE = (394, 731)                       # in-game group page, dimmed
GROUP_PAGE_DIM = 0.75
COMPACT_TOP = 158                             # in-game compact card
LIST_THUMB = (256, 144)                       # the website's group list

GW, GH = 1920, 1080
SHOT = (1240, 814)       # the app window as rendered (814 high: the sidebar fits
                         # without a scrollbar) ...
SHOT_SCALE = 0.84        # ... and how big a page's card shows it
BAR = 40                 # the title bar drawn over it
RADIUS = 14              # the window's corners
COLUMN_X = 110           # the text column's left edge, and the footer's
# The gallery after the overview, a card a page: (file, page, art, kicker,
# headline, what to do on the page first). The arrows are the page's steps
# in ui/page_steps.py.
SHOTS = (
    ("toys", "Home", "toys", "TOYS", "Your avatar's touches, on your toys.", "open a toy"),
    ("friends", "Friends", "friends", "FRIENDS", "Hand your friends the remote.", None),
    ("shockers", "Shockers", "shock", "SHOCKERS", "PiShock and OpenShock, straight over USB.", None),
    ("suits", "Suits", "suits", "SUITS", "bHaptics and OWO feel the same touch.", None),
    ("avatar-remote", "Avatar Remote", "params", "AVATAR REMOTE",
     "Your avatar's toggles, on one board.", None),
)
# The overview's fan of windows, drawn back to front: (page, degrees, scale,
# centre x as a share of the width, centre y)
FAN = (
    ("Suits", -7.0, 0.46, 0.17, 640),
    ("Avatar Remote", 7.0, 0.46, 0.83, 640),
    ("Friends", -3.5, 0.57, 0.31, 625),
    ("Shockers", 3.5, 0.57, 0.69, 625),
    ("Home", 0.0, 0.70, 0.50, 615),
)
# The overview's chips: everything OGP drives, each in its one icon
FAN_CHIPS = (("toys", "Toys"), ("shock", "Shockers"), ("suits", "Suits"),
             ("friends", "Friends"), ("params", "Avatar Remote"))


def top_rounded(x0, y0, x1, y1, rx, ry) -> QPainterPath:
    """A box whose top corners are quarter ellipses -- every nameplate
    zone's shape. A corner taller than the box is cut off at its bottom."""
    bottom = max(y1, y0 + ry)
    p = QPainterPath(QPointF(x0, bottom))
    p.lineTo(x0, y0 + ry)
    p.arcTo(QRectF(x0, y0, 2 * rx, 2 * ry), 180, -90)
    p.lineTo(x1 - rx, y0)
    p.arcTo(QRectF(x1 - 2 * rx, y0, 2 * rx, 2 * ry), 90, -90)
    p.lineTo(x1, bottom)
    p.closeSubpath()
    box = QPainterPath()
    box.addRect(QRectF(x0, y0, x1 - x0, y1 - y0))
    return p.intersected(box)


def name_zone() -> QPainterPath:
    """Where every nameplate shows the banner: the draft's dome below the
    long-name line, inside the live client's short-name strip."""
    rows = QPainterPath()
    rows.addRect(QRectF(0, LONG_NAME_Y, W, LIVE_BOTTOM - LONG_NAME_Y))
    return top_rounded(*DOME).intersected(top_rounded(*LIVE_SHORT)).intersected(rows)


def under_zone() -> QPainterPath:
    """Under the name, where only the group pages show the banner: behind
    the plate (so no long name's nameplate peeks at it) and above the
    group page's bottom edge."""
    rows = QPainterPath()
    rows.addRect(QRectF(0, 0, W, GROUP_PAGE[1]))
    return top_rounded(*ARCH).intersected(rows)


def _text(family: str, px: int, text: str, spacing: float = 0) -> QPainterPath:
    f = QFont(family)
    f.setPixelSize(px)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    p = QPainterPath()
    p.addText(0, 0, f, text)
    return p


def _wordmark(family: str, px: int) -> QPainterPath:
    return _text(family, px, "OscGoesPurrr", px * 2 / 76)  # the og-card's spacing


def _fits(path: QPainterPath, zone: QPainterPath, margin: float) -> bool:
    return zone.contains(path.boundingRect().adjusted(-margin, -margin, margin, margin))


def fitted_wordmark(family: str, zone: QPainterPath, margin: float = 22) -> QPainterPath:
    """The largest "OscGoesPurrr" that fits inside `zone` with `margin` to
    spare, centred across it and as near its middle row as it fits."""
    zr = zone.boundingRect()
    best = None
    for px in range(60, 240, 2):
        p = _wordmark(family, px)
        br = p.boundingRect()
        fits = []
        for dy in range(-60, 61, 2):
            q = p.translated(zr.center().x() - br.center().x(),
                             zr.center().y() + dy - br.center().y())
            if _fits(q, zone, margin):
                fits.append((abs(dy), q))
        if not fits:
            break
        best = min(fits, key=lambda f: f[0])[1]
    if best is None:
        raise SystemExit("the name does not fit the nameplate zone at any size")
    return best


def fitted_line(family: str, text: str, top: float, zone: QPainterPath, largest: int,
                margin: float = 16) -> QPainterPath:
    """`text` centred with its top at `top`, at the largest size up to
    `largest` px that keeps it inside `zone`."""
    for px in range(largest, 19, -1):
        p = _text(family, px, text)
        br = p.boundingRect()
        p = p.translated(W / 2 - br.center().x(), top - br.top())
        if _fits(p, zone, margin):
            return p
    raise SystemExit(f"{text!r} does not fit under the name at any size")


def _qimage(width: int, height: int, fill=Qt.transparent) -> QImage:
    img = QImage(width, height, QImage.Format_ARGB32)
    img.fill(fill)
    return img


def _pil(img: QImage) -> Image.Image:
    raw = bytes(img.constBits())
    # Format_ARGB32 is BGRA in memory on little-endian machines.
    return Image.frombuffer("RGBA", (img.width(), img.height()), raw,
                            "raw", "BGRA", 0, 1).copy()


def _painter(img: QImage) -> QPainter:
    g = QPainter(img)
    g.setRenderHint(QPainter.Antialiasing, True)
    g.setRenderHint(QPainter.TextAntialiasing, True)
    return g


def _glow(g: QPainter, cx: float, cy: float, rx: float, ry: float, alpha: int) -> None:
    """A soft ellipse of the dark green tint, fading out to its edge."""
    g.save()
    g.translate(cx, cy)
    g.scale(1.0, ry / rx)
    grad = QRadialGradient(QPointF(0, 0), rx)
    tint = QColor(T.NEON["tint"])
    tint.setAlpha(alpha)
    clear = QColor(tint)
    clear.setAlpha(0)
    grad.setColorAt(0.0, tint)
    grad.setColorAt(1.0, clear)
    g.setPen(Qt.NoPen)
    g.setBrush(grad)
    g.drawEllipse(QPointF(0, 0), rx, rx)
    g.restore()


def _blurred(img: Image.Image, radius: float, alpha: float) -> Image.Image:
    out = img.filter(ImageFilter.GaussianBlur(radius))
    a = out.getchannel("A").point(lambda v: int(v * alpha))
    out.putalpha(a)
    return out


def _chip_width(label: str, font: QFont, height: float) -> float:
    return height * (0.42 + 0.56 + 0.2 + 0.42) + QFontMetricsF(font).horizontalAdvance(label)


def _chip(g: QPainter, x: float, y: float, what: str, label: str, font: QFont,
          height: float) -> None:
    """One chip, the header-chip pattern: --card pill, --line border, the
    thing's icon in its colour."""
    g.setFont(font)
    size = height * 0.56
    pad, gap = height * 0.42, height * 0.2
    width = _chip_width(label, font, height)
    g.setPen(QPen(QColor(T.NEON["line"]), 2))
    g.setBrush(QColor(T.NEON["card"]))
    g.drawRoundedRect(QRectF(x, y, width, height), height / 2, height / 2)
    g.save()
    g.translate(x + pad, y + (height - size) / 2)
    g.scale(size / 20.0, size / 20.0)
    draw, colour = _feature_art(what)
    draw(g, QColor(colour))
    g.restore()
    g.setPen(QColor(T.NEON["txt"]))
    g.drawText(QRectF(x + pad + size + gap, y, width, height), Qt.AlignLeft | Qt.AlignVCenter, label)


def _ground(width: int, height: int, cx: float, cy: float, rx: float, ry: float) -> QImage:
    """Every image's ground: Neon bg, a faint dot grid, the tint glowing
    around (cx, cy)."""
    base = _qimage(width, height, QColor(T.NEON["bg"]))
    g = _painter(base)
    dot = QColor(T.NEON["line"])
    dot.setAlpha(34)
    g.setPen(Qt.NoPen)
    g.setBrush(dot)
    for y in range(20, height, 40):
        for x in range(20, width, 40):
            g.drawEllipse(QPointF(x, y), 1.6, 1.6)
    _glow(g, cx, cy, rx, ry, 235)
    g.end()
    return base


def draw_banner(title: str, body: str) -> Image.Image:
    base = _ground(W, H, W / 2, 470, 1150, 330)   # glowing behind the name
    name = fitted_wordmark(title, name_zone())
    lit = _qimage(W, H)
    g = _painter(lit)
    g.fillPath(name, QColor(T.NEON["accent"]))
    g.end()
    glow = _blurred(_pil(lit), 22, 0.45)

    top = _qimage(W, H)
    g = _painter(top)
    g.fillPath(name, QColor(T.NEON["accent"]))

    under = under_zone()
    g.fillPath(fitted_line(body, site.TAGLINE, 584, under, 50), QColor(T.NEON["txt"]))

    f = QFont(body)
    f.setPixelSize(32)
    chip_h, chip_gap, chip_y = 62, 26, 652
    widths = [_chip_width(label, f, chip_h) for _, label in CHIPS]
    row = sum(widths) + chip_gap * (len(widths) - 1)
    if not under.contains(QRectF((W - row) / 2 - 12, chip_y - 12, row + 24, chip_h + 24)):
        raise SystemExit("the chips do not fit under the name")
    x = (W - row) / 2
    for (what, label), width in zip(CHIPS, widths):
        _chip(g, x, chip_y, what, label, f, chip_h)
        x += width + chip_gap

    f.setPixelSize(30)
    g.setFont(f)
    g.setPen(QColor(T.NEON["muted"]))
    g.drawText(QRectF(0, 812, W, 50), Qt.AlignCenter, FACTS)
    g.end()

    out = _pil(base)
    out.alpha_composite(glow)
    out.alpha_composite(_pil(top))
    # above every nameplate (the highest starts at 314), clear of the card's top
    mark = icon.render(130, title)
    out.alpha_composite(mark, ((W - mark.width) // 2, 174))
    return out.convert("RGB")


def _reach(size: int) -> float:
    """How far the app icon drawn at `size` reaches from its centre,
    its stroke included."""
    w = icon._stroke_width(size)
    box, radius, ears = icon._geometry(size, w)
    s = QPainterPathStroker()
    s.setWidth(w)
    s.setJoinStyle(Qt.RoundJoin)
    s.setCapStyle(Qt.RoundCap)
    shape = s.createStroke(icon._outline(box, radius, ears))
    c = size / 2
    return max(math.hypot(p.x() - c, p.y() - c) for p in shape.toFillPolygon())


def draw_icon(title: str) -> Image.Image:
    """The app icon on the Neon ground, as large as fits VRChat's circle
    with its ear tips well inside the edge."""
    limit = 0.84 * ICON / 2
    size = int(ICON * limit / _reach(ICON))
    while _reach(size) > limit:
        size -= 2
    ground = _qimage(ICON, ICON, QColor(T.NEON["bg"]))
    g = _painter(ground)
    _glow(g, ICON / 2, ICON / 2, ICON * 0.5, ICON * 0.5, 200)
    g.end()
    out = _pil(ground)
    out.alpha_composite(icon.render(size, title), ((ICON - size) // 2, (ICON - size) // 2))
    return out.convert("RGB")


# ---------------------------------------------------------------------------
# The gallery: the real app, a page a card
# ---------------------------------------------------------------------------

def _draw_friends(p: QPainter, c: QColor) -> None:
    """Friends: the two people of the VRChat menu's Friends icon
    (tools/make_menu_icons.py), in the app icons' line width -- the app
    has no icon of its own for them."""
    k = 20.0 / menu.SIZE
    p.save()
    p.scale(k, k)
    for cx, cy, s, colour in ((330, 250, 0.8, c), (210, 290, 0.95, QColor(T.NEON["txt"]))):
        p.setPen(QPen(colour, 1.5 / k, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy - 70 * s), 62 * s, 62 * s)
        path = QPainterPath(QPointF(cx - 130 * s, cy + 150 * s))
        path.cubicTo(QPointF(cx - 130 * s, cy + 20 * s), QPointF(cx + 130 * s, cy + 20 * s),
                     QPointF(cx + 130 * s, cy + 150 * s))
        p.drawPath(path)
    p.restore()


def _draw_suit(p: QPainter, c: QColor) -> None:
    """A haptic vest with its motors, on the app icons' 20-unit grid --
    only the gallery draws one; the app has no suit icon."""
    ui_icons._stroke(p, c)
    vest = QPainterPath(QPointF(5.5, 2.0))
    vest.quadTo(QPointF(6.4, 5.6), QPointF(4.3, 7.4))
    vest.lineTo(QPointF(4.3, 16.8))
    vest.quadTo(QPointF(4.3, 18.0), QPointF(5.5, 18.0))
    vest.lineTo(QPointF(14.5, 18.0))
    vest.quadTo(QPointF(15.7, 18.0), QPointF(15.7, 16.8))
    vest.lineTo(QPointF(15.7, 7.4))
    vest.quadTo(QPointF(13.6, 5.6), QPointF(14.5, 2.0))
    vest.lineTo(QPointF(12.6, 2.0))
    vest.lineTo(QPointF(10.0, 7.6))
    vest.lineTo(QPointF(7.4, 2.0))
    vest.closeSubpath()
    p.drawPath(vest)
    p.drawLine(QPointF(10.0, 7.6), QPointF(10.0, 18.0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(c))
    for x, y in ((7.2, 10.8), (12.8, 10.8), (7.2, 14.4), (12.8, 14.4)):
        p.drawEllipse(QPointF(x, y), 1.05, 1.05)


def _feature_art(key: str):
    """(draw, colour) for a gallery card's icon: the app's own where it has
    one, in the same colour as everywhere else."""
    if key in ui_icons._IDENTITY_DRAW:
        return ui_icons._IDENTITY_DRAW[key], ui_icons.identity_color(key)
    if key == "friends":
        return _draw_friends, ui_theme.hue("cyan")      # the menu's friends hue
    return _draw_suit, ui_theme.hue(ui_theme.SUITS_HUE)


_WRAP = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop


def _wrapped(g: QPainter, x: float, y: float, width: float, text: str, paint: bool) -> float:
    """`text` word-wrapped at most `width` wide, its lines balanced (the
    narrowest width that needs no more lines, so no word is left on a line
    of its own); draws it when `paint`, returns its height either way."""
    def height(w):
        return g.boundingRect(QRectF(x, y, w, 2000), _WRAP, text).height()

    full = height(width)
    lo, hi = width * 0.4, width
    while hi - lo > 2:
        if height((lo + hi) / 2) > full:
            lo = (lo + hi) / 2
        else:
            hi = (lo + hi) / 2
    if paint:
        g.drawText(QRectF(x, y, hi, full), _WRAP, text)
    return full


def _window(shot: Image.Image, title: str, body: str) -> Image.Image:
    """The app window as it sits on the desktop: OGP's title bar over the
    page, rounded corners, the line colour round it."""
    w, h = shot.size
    img = _qimage(w, h + BAR, QColor(T.NEON["panel"]))
    g = _painter(img)
    g.drawImage(QPointF(14, (BAR - 22) / 2), site._qimage(icon.render(22, title)))
    f = QFont(body)
    f.setPixelSize(15)
    g.setFont(f)
    g.setPen(QColor(T.NEON["muted"]))
    g.drawText(QRectF(46, 0, w, BAR), Qt.AlignLeft | Qt.AlignVCenter, f"OscGoesPurrr v{VERSION}")
    g.setPen(QPen(QColor(T.NEON["muted"]), 1.4))
    cy = BAR / 2
    g.drawLine(QPointF(w - 134, cy), QPointF(w - 122, cy))                 # minimise
    g.drawRect(QRectF(w - 88.5, cy - 5.5, 11, 11))                         # maximise
    g.drawLine(QPointF(w - 42, cy - 6), QPointF(w - 30, cy + 6))           # close
    g.drawLine(QPointF(w - 42, cy + 6), QPointF(w - 30, cy - 6))
    g.drawImage(QPointF(0, BAR), site._qimage(shot))
    g.setPen(QPen(QColor(T.NEON["line"]), 2))
    g.setBrush(Qt.NoBrush)
    g.drawRoundedRect(QRectF(1, 1, w - 2, h + BAR - 2), RADIUS, RADIUS)
    g.end()
    out = _pil(img)
    mask = Image.new("L", (out.width * 2, out.height * 2), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1),
                                           RADIUS * 2, fill=255)
    out.putalpha(mask.resize(out.size, Image.LANCZOS))
    return out


def _lifted(canvas: Image.Image, win: Image.Image, x: int, y: int, glow: str,
            glow_alpha: float = 0.3) -> None:
    """`win` onto `canvas` at (x, y), lifted off the ground: a soft shadow
    under it and a glow of `glow` round it."""
    alpha = win.getchannel("A")
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shade.paste(Image.new("RGBA", win.size, (0, 0, 0, 255)), (x, y + 28), alpha)
    lit = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    lit.paste(Image.new("RGBA", win.size, QColor(glow).getRgb()), (x, y), alpha)
    canvas.alpha_composite(_blurred(shade, 34, 0.8))
    canvas.alpha_composite(_blurred(lit, 46, glow_alpha))
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(win, (x, y), win)
    canvas.alpha_composite(layer)


def _footer(canvas: Image.Image, title: str, body: str, slogan: bool = True) -> None:
    """OGP's name and the slogan along the bottom, the site on the right --
    the same on every card (the slogan left out where it is the headline)."""
    top = _qimage(GW, GH)
    g = _painter(top)
    f = QFont(title)
    f.setPixelSize(38)
    f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
    g.setFont(f)
    g.setPen(QColor(T.NEON["accent"]))
    x = COLUMN_X + 72
    g.drawText(QRectF(x, GH - 122, 600, 60), Qt.AlignLeft | Qt.AlignVCenter, "OscGoesPurrr")
    after = x + QFontMetricsF(f).horizontalAdvance("OscGoesPurrr") + 30
    f = QFont(body)
    f.setPixelSize(28)
    g.setFont(f)
    g.setPen(QColor(T.NEON["txt"]))
    if slogan:
        g.drawText(QRectF(after, GH - 122, 700, 60), Qt.AlignLeft | Qt.AlignVCenter, site.TAGLINE)
    g.setPen(QColor(T.NEON["muted"]))
    g.drawText(QRectF(GW - COLUMN_X - 800, GH - 122, 800, 60),
               Qt.AlignRight | Qt.AlignVCenter, URL)
    g.end()
    canvas.alpha_composite(_pil(top))
    canvas.alpha_composite(icon.render(58, title), (COLUMN_X, GH - 122))


def _arrow(g: QPainter, start: QPointF, end: QPointF, colour: QColor) -> None:
    """A curved arrow from a step's words to its control, on a dark edge so
    it reads over the screenshot."""
    dx = end.x() - start.x()
    c1 = QPointF(start.x() + dx * 0.5, start.y())
    c2 = QPointF(end.x() - dx * 0.5, end.y())
    shaft = QPainterPath(start)
    shaft.cubicTo(c1, c2, end)
    edge = QColor(T.NEON["bg"])
    edge.setAlpha(230)
    head = QPainterPath(end)
    angle = math.atan2(end.y() - c2.y(), end.x() - c2.x())
    for side in (-0.42, 0.42):
        head.lineTo(end.x() - 20 * math.cos(angle + side), end.y() - 20 * math.sin(angle + side))
    head.closeSubpath()
    for pen_colour, width in ((edge, 7.5), (colour, 3.5)):
        g.setPen(QPen(pen_colour, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        g.setBrush(Qt.NoBrush)
        g.drawPath(shaft)
        g.setBrush(pen_colour)
        g.drawPath(head)


def _badge(g: QPainter, centre: QPointF, radius: float, n: int, colour: QColor) -> None:
    g.setPen(QPen(QColor(T.NEON["bg"]), 3))
    g.setBrush(colour)
    g.drawEllipse(centre, radius, radius)
    f = QFont(g.font())
    f.setPixelSize(round(radius * 1.15))
    f.setBold(True)
    g.setFont(f)
    g.setPen(QColor(T.NEON["bg"]))
    g.drawText(QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius),
               Qt.AlignCenter, str(n))


def draw_shot(spec, shots, title: str, body: str) -> Image.Image:
    """One page's card: the real page in its window in the middle, the
    headline over it, and each step beside the window at the height of the
    control it is about -- on the nearer side -- pointing at it, which glows."""
    _, page, art, kicker, headline, first = spec
    colour = QColor(_feature_art(art)[1])
    page = shots.show(page)
    steps = next(s for name, s in page_steps.STEPS.items() if shots.resolve(name) == page)
    if first == "open a toy":
        # one of app_shots' demo toys opened: its signal chain, how a toy is tuned
        QTest.mouseClick(shots.ui.device_ui_frames["Lovense Lush 3"]["status_label"],
                         Qt.LeftButton)
        shots.pump(400)
    shot = _pil(shots.ui.window.grab().toImage())
    rects = []
    for step in steps:
        targets = (step.target,) if isinstance(step.target, str) else step.target
        found = [shots.anchor(page, t) for t in targets]
        if None in found:
            raise SystemExit(f"{page}: nothing on it is {targets[found.index(None)]!r} "
                             "-- bring ui/page_steps.py up to date")
        r = found[0]
        for more in found[1:]:
            r = r.united(more)
        rects.append(r)

    k = SHOT_SCALE
    win = _window(shot, title, body)
    win = win.resize((round(win.width * k), round(win.height * k)), Image.LANCZOS)
    wx, wy = (GW - win.width) // 2, 186
    out = _pil(_ground(GW, GH, GW / 2, wy + win.height / 2, 1100, 620))
    _lifted(out, win, wx, wy, colour.name())
    rings = [QRectF(wx + r.x() * k, wy + (BAR + r.y()) * k, r.width() * k,
                    r.height() * k).adjusted(-6, -6, 6, 6) for r in rects]
    # the window dimmed a little, the steps' controls left lit
    dim = _qimage(GW, GH)
    g = _painter(dim)
    g.setPen(Qt.NoPen)
    g.setBrush(QColor(0, 0, 0, 105))
    g.setClipRect(QRectF(wx, wy + BAR * k, win.width, win.height - BAR * k))   # not the title bar
    g.drawRoundedRect(QRectF(wx, wy, win.width, win.height), RADIUS * k, RADIUS * k)
    g.setClipping(False)
    g.setCompositionMode(QPainter.CompositionMode_Clear)
    for ring in rings:
        g.drawRoundedRect(ring, 10, 10)
    g.end()
    out.alpha_composite(_pil(dim))
    halo = _qimage(GW, GH)
    g = _painter(halo)
    g.setBrush(Qt.NoBrush)
    g.setPen(QPen(colour, 12))
    for ring in rings:
        g.drawRoundedRect(ring, 10, 10)
    g.end()
    out.alpha_composite(_blurred(_pil(halo), 10, 0.9))

    top = _qimage(GW, GH)
    g = _painter(top)
    f_kick, f_head, f_label, f_hint = QFont(body), QFont(body), QFont(body), QFont(body)
    f_kick.setPixelSize(26)
    f_kick.setBold(True)
    f_kick.setLetterSpacing(QFont.AbsoluteSpacing, 6)
    f_head.setPixelSize(56)
    f_head.setWeight(QFont.DemiBold)
    f_label.setPixelSize(30)
    f_label.setWeight(QFont.DemiBold)
    f_hint.setPixelSize(23)
    g.setFont(f_kick)
    g.setPen(colour)
    g.drawText(QRectF(0, 38, GW, 34), Qt.AlignCenter, kicker)
    g.setFont(f_head)
    g.setPen(QColor(T.NEON["txt"]))
    g.drawText(QRectF(0, 74, GW, 76), Qt.AlignCenter, headline)

    # the steps: beside the window on the side nearer their control, at its
    # height, pushed apart where two would overlap
    radius, gap = 20, 14
    width = wx - 64 - 2 * radius - gap - 40
    blocks = {"L": [], "R": []}
    for n, (step, ring) in enumerate(zip(steps, rings), 1):
        g.setFont(f_label)
        lh = _wrapped(g, 0, 0, width, step.label, False)
        g.setFont(f_hint)
        hh = _wrapped(g, 0, 0, width, step.hint, False)
        side = "L" if ring.center().x() < GW / 2 else "R"
        blocks[side].append([ring.center().y() - 20, n, step, ring, lh, hh])
    for side, items in blocks.items():
        items.sort(key=lambda b: b[0])
        floor = wy
        for b in items:
            b[0] = max(b[0], floor)
            floor = b[0] + b[4] + b[5] + 30
        ceiling = wy + win.height
        for b in reversed(items):
            b[0] = min(b[0], ceiling - b[4] - b[5])
            ceiling = b[0] - 30
        for y, n, step, ring, lh, hh in items:
            if side == "L":
                bx = 64 + radius
                tx = bx + radius + gap
            else:
                bx = wx + win.width + 40 + radius
                tx = bx + radius + gap
            _badge(g, QPointF(bx, y + 20), radius, n, colour)
            g.setFont(f_label)
            g.setPen(QColor(T.NEON["txt"]))
            _wrapped(g, tx, y, width, step.label, True)
            g.setFont(f_hint)
            g.setPen(QColor(T.NEON["muted"]))
            _wrapped(g, tx, y + lh + 2, width, step.hint, True)
            g.setBrush(Qt.NoBrush)
            g.setPen(QPen(colour, 3))
            g.drawRoundedRect(ring, 10, 10)
            if side == "L":
                line = QFontMetricsF(f_label).boundingRect(
                    QRectF(0, 0, width, 2000), _WRAP, step.label)
                start = QPointF(min(tx + line.width() + 16, wx - 12), y + 20)
                _arrow(g, start, QPointF(ring.left() - 3, ring.center().y()), colour)
            else:
                start = QPointF(bx - radius - 12, y + 20)
                _arrow(g, start, QPointF(ring.right() + 3, ring.center().y()), colour)
    g.end()
    out.alpha_composite(_pil(top))
    _footer(out, title, body)
    return out.convert("RGB")


def draw_overview(shots, title: str, body: str) -> Image.Image:
    """The gallery's first card: every page fanned out under the slogan,
    with everything OGP drives in a row of chips."""
    out = _pil(_ground(GW, GH, GW / 2, 640, 1150, 560))
    for page, degrees, scale, cx, cy in FAN:
        win = _window(_pil(shots.page(page)), title, body)
        win = win.resize((round(win.width * scale), round(win.height * scale)), Image.LANCZOS)
        win = win.rotate(-degrees, resample=Image.BICUBIC, expand=True)
        _lifted(out, win, round(GW * cx - win.width / 2), round(cy - win.height / 2),
                T.NEON["accent"], 0.18)

    top = _qimage(GW, GH)
    g = _painter(top)
    f = QFont(body)
    f.setPixelSize(70)
    f.setWeight(QFont.DemiBold)
    g.setFont(f)
    g.setPen(QColor(T.NEON["txt"]))
    g.drawText(QRectF(0, 70, GW, 90), Qt.AlignCenter, site.TAGLINE)
    f = QFont(body)
    f.setPixelSize(30)
    chip_h, chip_gap = 58, 22
    widths = [_chip_width(label, f, chip_h) for _, label in FAN_CHIPS]
    x = (GW - sum(widths) - chip_gap * (len(widths) - 1)) / 2
    for (what, label), width in zip(FAN_CHIPS, widths):
        _chip(g, x, 180, what, label, f, chip_h)
        x += width + chip_gap
    g.end()
    out.alpha_composite(_pil(top))
    _footer(out, title, body, slogan=False)
    return out.convert("RGB")


# ---------------------------------------------------------------------------
# The check sheet: every zone on the banner, then each crop as VRChat shows it
# ---------------------------------------------------------------------------

def _clip(img: Image.Image, path: QPainterPath, ground: str) -> Image.Image:
    """`img` inside `path` on `ground`, cut to the path's bounds."""
    mask = _qimage(img.width, img.height)
    g = _painter(mask)
    g.fillPath(path, QColor("white"))
    g.end()
    out = Image.new("RGB", img.size, ground)
    out.paste(img, (0, 0), _pil(mask).getchannel("A"))
    r = path.boundingRect().toAlignedRect()
    return out.crop((r.left(), r.top(), r.right() + 1, r.bottom() + 1))


def _framed(img: Image.Image) -> Image.Image:
    out = img.copy()
    ImageDraw.Draw(out).rectangle((0, 0, out.width - 1, out.height - 1), outline=T.NEON["line"])
    return out


def _circle(img: Image.Image, size: int, ground: str) -> Image.Image:
    small = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    out = Image.new("RGB", (size, size), ground)
    out.paste(small, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


def _zone_overlay(banner: Image.Image, body: str) -> Image.Image:
    pal = T.PALETTE
    over = _qimage(W, H)
    g = _painter(over)
    f = QFont(body)
    f.setPixelSize(26)
    f.setBold(True)

    def outline(path, colour, dash=None, label=None, at=None, width=4):
        pen = QPen(QColor(colour), width)
        if dash:
            pen.setDashPattern(dash)
        g.setPen(pen)
        g.setBrush(Qt.NoBrush)
        g.drawPath(path)
        if label:
            g.setFont(f)
            r = QRectF(at[0], at[1], g.fontMetrics().horizontalAdvance(label) + 20, 36)
            g.setPen(Qt.NoPen)
            g.setBrush(QColor(0, 0, 0, 190))
            g.drawRoundedRect(r, 8, 8)
            g.setPen(QColor(colour))
            g.drawText(r, Qt.AlignCenter, label)

    def hline(y, x0=0, x1=W):
        p = QPainterPath(QPointF(x0, y))
        p.lineTo(x1, y)
        return p

    band = QPainterPath()
    band.addRect(QRectF(BAND[0], BAND[1], BAND[2] - BAND[0], BAND[3] - BAND[1]))
    outline(band, pal["grey"][0], [3, 3], "nameplate, long name: sometimes", (12, BAND[3] - 44), 3)
    outline(top_rounded(*ARCH), pal["red"][0], [3, 3], "behind the plate: never", (ARCH[0] + 260, ARCH[3] - 44), 3)
    outline(hline(GROUP_PAGE[0]), pal["purple"][0], [6, 4], "group page in game", (12, GROUP_PAGE[0] + 6), 3)
    outline(hline(GROUP_PAGE[1]), pal["purple"][0], [6, 4], width=3)
    outline(hline(COMPACT_TOP), pal["blue"][0], [6, 4], "compact card in game: from here down", (12, COMPACT_TOP + 6), 3)
    outline(top_rounded(*EXPANDED), pal["amber"][0], label="nameplate, menu open", at=(EXPANDED[0] + 8, EXPANDED[1] - 44))
    outline(top_rounded(*DOME), pal["cyan"][0], label="nameplate, menu closed", at=(DOME[0] + 740, DOME[1] - 44))
    outline(hline(LONG_NAME_Y, DOME[0] + 60, DOME[2] - 60), pal["cyan"][0], [4, 4], width=2)
    outline(name_zone(), "#ffffff", [2, 2], width=2)
    g.end()
    out = banner.convert("RGBA")
    out.alpha_composite(_pil(over))
    return out.convert("RGB")


def draw_sheet(banner: Image.Image, group_icon: Image.Image, body: str) -> Image.Image:
    M, ground = 40, T.NEON["panel"]
    plate = "#1b1a20"                       # VRChat's nameplate grey, for the crops
    closed = _clip(banner, top_rounded(*DOME), plate)
    opened = _clip(banner, top_rounded(*EXPANDED), plate)
    page = banner.crop((0, GROUP_PAGE[0], W, GROUP_PAGE[1]))
    page = Image.blend(Image.new("RGB", page.size, "black"), page, GROUP_PAGE_DIM)
    card = _clip(banner, top_rounded(0, COMPACT_TOP, W, H, 87, 87), plate)
    thumb = banner.resize(LIST_THUMB, Image.LANCZOS)

    k = 0.62
    closed = closed.resize((round(closed.width * k), round(closed.height * k)), Image.LANCZOS)
    opened = opened.resize((round(opened.width * k), round(opened.height * k)), Image.LANCZOS)
    page = page.resize((W // 2, round(page.height / 2)), Image.LANCZOS)
    card = card.resize((round(card.width * 0.3), round(card.height * 0.3)), Image.LANCZOS)

    rows = [
        [("Nameplate, menu closed", closed), ("Nameplate, menu open", opened)],
        [("Group page in game (dimmed)", page), ("Compact card in game", card)],
        [("Website group list, 256 x 144", thumb), ("Icon, 256", _circle(group_icon, 256, ground)),
         ("Icon, 96", _circle(group_icon, 96, ground)), ("Icon, 48", _circle(group_icon, 48, ground))],
    ]
    label_h, gap = 48, 36
    height = M + 60 + H + gap
    for row in rows:
        height += label_h + max(img.height for _, img in row) + gap
    sheet = Image.new("RGB", (W + 2 * M, height + M), ground)

    canvas = _qimage(*sheet.size)
    g = _painter(canvas)
    f = QFont(body)
    f.setPixelSize(30)
    f.setBold(True)
    g.setFont(f)
    g.setPen(QColor(T.NEON["txt"]))
    g.drawText(QRectF(M, M, W, 44), Qt.AlignLeft | Qt.AlignVCenter,
               "OGP group banner — where VRChat shows what (2000 x 1125)")
    f.setBold(False)
    f.setPixelSize(22)
    g.setFont(f)
    g.setPen(QColor(T.NEON["muted"]))
    g.drawText(QRectF(M, M + 44, W, 30), Qt.AlignLeft | Qt.AlignVCenter,
               "Zones: VRChat's draft template (not final, 2026-08-06) and the live client "
               "(tokage-lab.com). Dotted white: where the name has to fit.")
    sheet.paste(_zone_overlay(banner, body), (M, M + 80))
    y = M + 80 + H + gap
    f.setPixelSize(24)
    g.setFont(f)
    for row in rows:
        x = M
        tallest = max(img.height for _, img in row)
        for label, img in row:
            g.drawText(QRectF(x, y, img.width + 200, label_h - 8), Qt.AlignLeft | Qt.AlignBottom, label)
            sheet.paste(_framed(img) if not label.startswith("Icon") else img, (x, y + label_h))
            x += img.width + 2 * gap
        y += label_h + tallest + gap
    g.end()
    sheet = sheet.convert("RGBA")
    sheet.alpha_composite(_pil(canvas))
    return sheet.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sheet", type=Path, help="also write a check sheet of every crop here")
    args = ap.parse_args()
    app = QApplication.instance() or QApplication(sys.argv[:1])   # widgets: the real app
    title = site._load_font(icon.FONT)
    if not title:
        print(f"Could not load {icon.FONT}", file=sys.stderr)
        return 1
    body = site._load_font(site.SEGOE) or title
    OUT.mkdir(parents=True, exist_ok=True)
    banner = draw_banner(title, body)
    group_icon = draw_icon(title)
    banner.save(OUT / "banner.png", optimize=True)
    group_icon.save(OUT / "icon.png", optimize=True)
    shots = app_shots.open_app(*SHOT)
    cards = ["gallery-1-overview.png"]
    for n, spec in enumerate(SHOTS, 2):
        cards.append(f"gallery-{n}-{spec[0]}.png")
        draw_shot(spec, shots, title, body).save(OUT / cards[-1], optimize=True)
    # last, so its pages are as the cards left them (Home with a toy open)
    draw_overview(shots, title, body).save(OUT / cards[0], optimize=True)
    for old in OUT.glob("gallery-*.png"):          # cards this run no longer draws
        if old.name not in cards:
            old.unlink()
    print(f"wrote banner.png, icon.png, {', '.join(cards)} to {OUT}")
    if args.sheet:
        draw_sheet(banner, group_icon, body).save(args.sheet)
        print(f"wrote {args.sheet}")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
