"""Draw the VRChat menu's icons into docs/unity/icons/ (512 px PNGs).

The style follows Blise's "Flat" avatar icons: white line art with round
caps on a transparent ground, a few solid shapes, and colour only where it
means something -- the app's own identity hues (theme_tokens via
ui.theme.PALETTE): toys pink, shockers yellow, friends cyan, your own
things green, stop red. The wave icons are drawn from friend_patterns, so
they show exactly what the app plays. VRChat shows menu icons at 256 px at
most; the prefab builder scales them down.

The icons are committed; re-run this after changing one:
    venv\\Scripts\\python.exe tools\\make_menu_icons.py [--sheet out.png]
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# offscreen Qt only finds fonts it is pointed at; without them the numbers
# and STOP come out as empty boxes
if sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
# the stock 518 green, not whatever accent this PC's OGP is set to
os.environ["OGP_UI_ACCENT"] = "default"

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage,  # noqa: E402
                           QPainter, QPainterPath, QPainterPathStroker, QPen, QPolygonF)

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
import friend_patterns  # noqa: E402
from ui.theme import PALETTE  # noqa: E402

OUT = REPO / "docs" / "unity" / "icons"
SIZE = 512
W = 28                     # the line width, like the Flat set's
WHITE = "#ffffff"
PINK, YELLOW, CYAN, GREEN, RED = (PALETTE[h][0] for h in ("pink", "yellow", "cyan", "green", "red"))


def _pen(p: QPainter, color: str = WHITE, width: float = W) -> None:
    p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)


def _fill(p: QPainter, color: str) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(QColor(color)))


def _text(p: QPainter, rect: QRectF, text: str, color: str, size: int, weight=QFont.Black) -> None:
    f = QFont("Segoe UI", size)
    f.setWeight(weight)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(rect, Qt.AlignCenter, text)


def _curve(p: QPainter, fn, x0: float, x1: float, y_top: float, y_bot: float, n: int = 160) -> None:
    path = QPainterPath()
    for i in range(n + 1):
        x = i / n
        pt = QPointF(x0 + x * (x1 - x0), y_bot - fn(x) * (y_bot - y_top))
        path.lineTo(pt) if i else path.moveTo(pt)
    p.drawPath(path)


# ---------------------------------------------------------------------------
# shapes reused by several icons
# ---------------------------------------------------------------------------

def _person(p: QPainter, cx: float, cy: float, s: float, color: str) -> None:
    _pen(p, color)
    p.drawEllipse(QPointF(cx, cy - 70 * s), 62 * s, 62 * s)
    path = QPainterPath(QPointF(cx - 130 * s, cy + 150 * s))
    path.cubicTo(QPointF(cx - 130 * s, cy + 20 * s), QPointF(cx + 130 * s, cy + 20 * s),
                 QPointF(cx + 130 * s, cy + 150 * s))
    p.drawPath(path)


def _heart(p: QPainter, cx: float, cy: float, s: float, color: str) -> None:
    _fill(p, color)
    path = QPainterPath(QPointF(cx, cy + 40 * s))
    path.cubicTo(QPointF(cx - 70 * s, cy - 10 * s), QPointF(cx - 40 * s, cy - 70 * s), QPointF(cx, cy - 32 * s))
    path.cubicTo(QPointF(cx + 40 * s, cy - 70 * s), QPointF(cx + 70 * s, cy - 10 * s), QPointF(cx, cy + 40 * s))
    p.drawPath(path)


def _toy(p: QPainter, cx: float, cy: float, s: float, fill: str) -> None:
    """A vibrator standing up: pink body, white line, a band near the base
    (Blise's pick, "A")."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(cx - 60 * s, cy - 186 * s, 120 * s, 372 * s), 60 * s, 60 * s)
    _fill(p, fill)
    p.drawPath(body)
    _pen(p, WHITE, W * max(0.75, s))
    p.drawPath(body)
    p.drawLine(QPointF(cx - 60 * s, cy + 96 * s), QPointF(cx + 60 * s, cy + 96 * s))


def _zigzags(p: QPainter, x_left: float, x_right: float, y0: float, y1: float,
             amp: float = 26, step: float = 34) -> None:
    """The Flat set's vibration marks: a zigzag either side."""
    _pen(p)
    for x0, sgn in ((x_left, -1), (x_right, 1)):
        path = QPainterPath(QPointF(x0, y0))
        k, y = 0, y0
        while y < y1:
            y += step
            k += 1
            path.lineTo(QPointF(x0 + sgn * (amp if k % 2 else 0), min(y, y1)))
        p.drawPath(path)


def _bolt(p: QPainter, cx: float, cy: float, s: float, color: str, outline: bool = True) -> None:
    pts = [(30, -200), (-110, 30), (0, 30), (-40, 200), (110, -40), (0, -40)]
    poly = QPolygonF([QPointF(cx + x * s, cy + y * s) for x, y in pts])
    _fill(p, color)
    p.drawPolygon(poly)
    if outline:
        p.setPen(QPen(QColor(WHITE), W * 0.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(poly)


def _gauge(p: QPainter, needle: str, at: float = 0.72) -> None:
    c = QPointF(256, 312)
    r = 190
    _pen(p)
    p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 200 * 16, -220 * 16)
    for k in range(6):
        a = math.radians(200 - k * 44)
        p.drawLine(QPointF(c.x() + math.cos(a) * (r - 46), c.y() - math.sin(a) * (r - 46)),
                   QPointF(c.x() + math.cos(a) * (r - 18), c.y() - math.sin(a) * (r - 18)))
    a = math.radians(200 - at * 220)
    _pen(p, needle, W * 1.1)
    p.drawLine(c, QPointF(c.x() + math.cos(a) * (r - 40), c.y() - math.sin(a) * (r - 40)))
    _fill(p, needle)
    p.drawEllipse(c, 34, 34)


def _stop(p: QPainter) -> None:
    pts = [(256 + 200 * math.cos(math.radians(22.5 + 45 * k)),
            256 + 200 * math.sin(math.radians(22.5 + 45 * k))) for k in range(8)]
    poly = QPolygonF([QPointF(x, y) for x, y in pts])
    _fill(p, RED)
    p.drawPolygon(poly)
    _pen(p, WHITE, 16)
    inner = QPolygonF([QPointF(256 + (x - 256) * 0.86, 256 + (y - 256) * 0.86) for x, y in pts])
    p.drawPolygon(inner)
    _text(p, QRectF(0, 0, SIZE, SIZE), "STOP", WHITE, 70)


def _numbered(p: QPainter, n: int, color: str, glyph) -> None:
    glyph(p)
    _fill(p, color)
    p.drawEllipse(QPointF(380, 380), 104, 104)
    _text(p, QRectF(276, 276, 208, 208), str(n), "#000000", 120)


def _collar(p: QPainter, color: str) -> None:
    _pen(p)
    p.drawEllipse(QRectF(70, 120, 372, 230))
    p.drawEllipse(QRectF(118, 160, 276, 150))
    _fill(p, color)
    p.drawRoundedRect(QRectF(196, 300, 120, 120), 22, 22)
    _pen(p, WHITE, 18)
    p.drawRoundedRect(QRectF(196, 300, 120, 120), 22, 22)


def _check(p: QPainter, x: float, y: float, s: float, color: str) -> None:
    _pen(p, color, W * s)
    path = QPainterPath(QPointF(x - 40 * s, y))
    path.lineTo(QPointF(x - 10 * s, y + 30 * s))
    path.lineTo(QPointF(x + 44 * s, y - 34 * s))
    p.drawPath(path)


# ---------------------------------------------------------------------------
# the icons
# ---------------------------------------------------------------------------

def me(p):
    _person(p, 236, 270, 1.0, WHITE)
    _heart(p, 392, 150, 1.0, GREEN)


def friends(p):
    _person(p, 330, 250, 0.8, CYAN)
    _person(p, 210, 290, 0.95, WHITE)


def strength(p):
    _gauge(p, GREEN)


def their_strength(p):
    _gauge(p, CYAN)


def off(p):
    _pen(p)
    p.drawArc(QRectF(86, 96, 340, 340), 120 * 16, 300 * 16)
    p.drawLine(QPointF(256, 70), QPointF(256, 250))
    _pen(p, RED, W * 1.2)
    p.drawLine(QPointF(90, 430), QPointF(430, 90))


def sleep(p):
    outer = QPainterPath()
    outer.addEllipse(QRectF(70, 70, 372, 372))
    bite = QPainterPath()
    bite.addEllipse(QRectF(190, 20, 330, 330))
    _pen(p)
    p.drawPath(outer.subtracted(bite))


def test(p):
    _fill(p, GREEN)
    p.drawEllipse(QPointF(256, 256), 70, 70)
    _pen(p)
    for r in (130, 200):
        for start in (135, -45):
            p.drawArc(QRectF(256 - r, 256 - r, 2 * r, 2 * r), start * 16, 90 * 16)


def modes(p):
    _pen(p)
    for y, x in ((140, 330), (256, 190), (372, 300)):
        p.drawLine(QPointF(80, y), QPointF(432, y))
        _fill(p, GREEN)
        p.drawEllipse(QPointF(x, y), 40, 40)
        _pen(p)
        p.drawEllipse(QPointF(x, y), 40, 40)


def toys(p):
    _toy(p, 256, 256, 1.0, PINK)
    _zigzags(p, 130, 382, 110, 400)


def both(p):
    """You and your friend at once: you green, them cyan, a pink heart."""
    _person(p, 150, 300, 0.72, GREEN)
    _person(p, 362, 300, 0.72, CYAN)
    _heart(p, 256, 120, 1.0, PINK)


def shockers(p):
    _collar(p, YELLOW)
    _bolt(p, 256, 236, 0.42, YELLOW, outline=False)


def level(p):
    _pen(p)
    p.drawLine(QPointF(70, 256), QPointF(442, 256))
    _pen(p, PINK, W * 1.6)
    p.drawLine(QPointF(70, 256), QPointF(310, 256))
    _fill(p, PINK)
    p.drawEllipse(QPointF(310, 256), 66, 66)
    _pen(p)
    p.drawEllipse(QPointF(310, 256), 66, 66)


def _wave(fn, dashed_mid: bool = False):
    def draw(p):
        if dashed_mid:
            p.setPen(QPen(QColor(WHITE), 14, Qt.DashLine, Qt.RoundCap))
            p.drawLine(QPointF(60, 256), QPointF(452, 256))
        _pen(p, PINK, W * 1.25)
        _curve(p, fn, 60, 452, 130, 382)
    return draw


def _shape(wave: str, cycles: float, lo: float = 0.0, hi: float = 1.0):
    return lambda x: lo + (hi - lo) * friend_patterns.shape(wave, x * cycles, x * 3.0, 1.0)


auto = _wave(_shape("sine", 2.0))
wave_sine = _wave(_shape("sine", 2.0))
wave_square = _wave(_shape("square", 2.0))
wave_triangle = _wave(_shape("triangle", 2.0))
wave_saw = _wave(_shape("saw", 2.0))
wave_heart = _wave(_shape("heart", 1.6))
wave_build = _wave(_shape("build", 1.0))
wave_osc = _wave(_shape("osc", 2.0, 0.25, 0.75), dashed_mid=True)


def wave_random(p):
    _pen(p)
    p.drawRoundedRect(QRectF(86, 86, 340, 340), 64, 64)
    _fill(p, PINK)
    for x, y in ((170, 170), (256, 256), (342, 342), (342, 170), (170, 342)):
        p.drawEllipse(QPointF(x, y), 34, 34)


def speed(p):
    _pen(p, PINK, W * 1.4)
    for x in (230, 340):
        path = QPainterPath(QPointF(x - 70, 120))
        path.lineTo(QPointF(x + 60, 256))
        path.lineTo(QPointF(x - 70, 392))
        p.drawPath(path)
    _pen(p)
    for y, x0 in ((180, 40), (256, 20), (332, 40)):
        p.drawLine(QPointF(x0, y), QPointF(x0 + 80, y))


def range_(p):
    _pen(p)
    p.drawLine(QPointF(256, 120), QPointF(256, 392))
    for y, d in ((120, 1), (392, -1)):
        path = QPainterPath(QPointF(196, y + d * 60))
        path.lineTo(QPointF(256, y))
        path.lineTo(QPointF(316, y + d * 60))
        p.drawPath(path)
    _pen(p, PINK, W * 1.3)
    p.drawLine(QPointF(110, 70), QPointF(402, 70))
    p.drawLine(QPointF(110, 442), QPointF(402, 442))


def override(p):
    p.setPen(QPen(QColor(WHITE), 18, Qt.DashLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    _curve(p, _shape("sine", 1.5), 50, 462, 250, 440)
    _pen(p, PINK, W * 1.5)
    p.drawLine(QPointF(60, 170), QPointF(452, 170))
    _fill(p, PINK)
    p.drawPolygon(QPolygonF([QPointF(452, 170), QPointF(380, 120), QPointF(380, 220)]))


def _grid_of_four(p, color):
    _pen(p)
    for x, y in ((80, 80), (276, 80), (80, 276), (276, 276)):
        p.drawRoundedRect(QRectF(x, y, 156, 156), 34, 34)
        _check(p, x + 78, y + 78, 1.0, color)
        _pen(p)


def which_toys(p):
    _grid_of_four(p, PINK)


def which_shockers(p):
    _grid_of_four(p, YELLOW)


def _toy_small(p):
    _toy(p, 190, 230, 0.78, PINK)


def _collar_small(p):
    p.save()
    p.translate(30, 10)
    p.scale(0.78, 0.78)
    _collar(p, YELLOW)
    p.restore()


def stop_toys(p):
    _stop(p)


def stop(p):
    _stop(p)


def shock(p):
    _bolt(p, 256, 256, 1.0, YELLOW)


def vibrate(p):
    _pen(p)
    p.drawRoundedRect(QRectF(180, 80, 152, 352), 34, 34)
    _fill(p, PINK)
    p.drawRoundedRect(QRectF(214, 130, 84, 200), 16, 16)
    _pen(p)
    for x0, sgn in ((130, -1), (382, 1)):
        path = QPainterPath(QPointF(x0, 140))
        for k, y in enumerate(range(180, 400, 40)):
            path.lineTo(QPointF(x0 + sgn * (34 if k % 2 == 0 else 0), y))
        p.drawPath(path)


def beep(p):
    _pen(p)
    path = QPainterPath(QPointF(110, 360))
    path.cubicTo(QPointF(150, 320), QPointF(140, 120), QPointF(256, 110))
    path.cubicTo(QPointF(372, 120), QPointF(362, 320), QPointF(402, 360))
    path.closeSubpath()
    p.drawPath(path)
    p.drawLine(QPointF(210, 420), QPointF(302, 420))
    _pen(p, YELLOW)
    for r in (70, 120):
        p.drawArc(QRectF(420 - r, 120 - r, 2 * r, 2 * r), -10 * 16, 80 * 16)


def length(p):
    _pen(p)
    p.drawLine(QPointF(120, 70), QPointF(392, 70))
    p.drawLine(QPointF(120, 442), QPointF(392, 442))
    path = QPainterPath(QPointF(150, 70))
    path.cubicTo(QPointF(150, 200), QPointF(256, 220), QPointF(256, 256))
    path.cubicTo(QPointF(256, 292), QPointF(150, 312), QPointF(150, 442))
    p.drawPath(path)
    path = QPainterPath(QPointF(362, 70))
    path.cubicTo(QPointF(362, 200), QPointF(256, 220), QPointF(256, 256))
    path.cubicTo(QPointF(256, 292), QPointF(362, 312), QPointF(362, 442))
    p.drawPath(path)
    _fill(p, YELLOW)
    sand = QPainterPath(QPointF(180, 420))
    sand.cubicTo(QPointF(200, 360), QPointF(250, 330), QPointF(256, 320))
    sand.cubicTo(QPointF(262, 330), QPointF(312, 360), QPointF(332, 420))
    sand.closeSubpath()
    p.drawPath(sand)


def warning(p):
    tri = QPolygonF([QPointF(256, 70), QPointF(460, 420), QPointF(52, 420)])
    _pen(p, YELLOW, W * 1.1)
    p.drawPolygon(tri)
    _pen(p, WHITE, W * 1.2)
    p.drawLine(QPointF(256, 190), QPointF(256, 300))
    _fill(p, WHITE)
    p.drawEllipse(QPointF(256, 360), 20, 20)


ICONS = {
    # yours
    "me": me, "strength": strength, "off": off, "sleep": sleep, "test": test, "modes": modes,
    # friends
    "friends": friends, "their_strength": their_strength, "both": both,
    "toys": toys, "level": level, "auto": auto, "speed": speed, "range": range_,
    "override": override, "which_toys": which_toys, "stop_toys": stop_toys,
    "wave_sine": wave_sine, "wave_square": wave_square, "wave_triangle": wave_triangle,
    "wave_saw": wave_saw, "wave_random": wave_random, "wave_heart": wave_heart,
    "wave_build": wave_build, "wave_osc": wave_osc,
    "shockers": shockers, "shock": shock, "vibrate": vibrate, "beep": beep, "stop": stop,
    "shock_strength": lambda p: _gauge(p, YELLOW), "length": length, "warning": warning,
    "which_shockers": which_shockers,
}
for _n in range(1, 5):
    ICONS[f"toy{_n}"] = (lambda n: lambda p: _numbered(p, n, PINK, _toy_small))(_n)
    ICONS[f"shocker{_n}"] = (lambda n: lambda p: _numbered(p, n, YELLOW, _collar_small))(_n)


def render(name: str) -> QImage:
    img = QImage(SIZE, SIZE, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    ICONS[name](p)
    p.end()
    return img


def main() -> None:
    QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        render(name).save(str(OUT / f"{name}.png"))
    if "--sheet" in sys.argv:
        sheet_path = sys.argv[sys.argv.index("--sheet") + 1]
        cols, cell = 8, 150
        rows = (len(ICONS) + cols - 1) // cols
        sheet = QImage(cols * cell, rows * (cell + 22), QImage.Format_ARGB32)
        sheet.fill(QColor(40, 44, 52))
        p = QPainter(sheet)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        for i, name in enumerate(ICONS):
            x, y = (i % cols) * cell, (i // cols) * (cell + 22)
            p.drawImage(QRectF(x + 15, y + 8, 120, 120), render(name))
            _text(p, QRectF(x, y + cell - 12, cell, 22), name, "#c8c8c8", 9, QFont.Normal)
        p.end()
        sheet.save(sheet_path)
    print(f"{len(ICONS)} icons in {OUT}")


if __name__ == "__main__":
    main()
