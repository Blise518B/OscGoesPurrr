"""Write the app's own sidebar icons as SVG for the site's demo window.

The demo (docs/assets/demo.js) draws the app's sidebar, so it needs the
app's icons: the identity ones (toys, shockers, Avatar Remote, friends, the
web remote) and the line-art page ones (Statistics, the tools, Settings,
Help). Rather than redrawing them by hand, this runs the app's own drawing
code (src/ui/icons.py) into Qt's SVG generator and writes them, in
currentColor, to docs/assets/demo-icons.js -- the demo colours each one with
the token the app uses for it.

Run from the project root after changing an icon in ui/icons.py:
    venv\\Scripts\\python.exe tools\\make_demo_icons.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, QSize  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgGenerator  # noqa: E402

from ui import icons  # noqa: E402

OUT = REPO / "docs" / "assets" / "demo-icons.js"
MARK = "#123456"        # the colour drawn with, swapped for currentColor after
NAMES = ("toys", "shock", "params", "friends", "web", "stats", "sps", "inspector",
         "diagnostics", "log", "settings", "help")


def svg(name: str) -> str:
    draw = icons._IDENTITY_DRAW.get(name) or icons._PAGE_DRAW[name]
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    gen = QSvgGenerator()
    gen.setOutputDevice(buf)
    gen.setSize(QSize(20, 20))
    gen.setViewBox(QRectF(0, 0, 20, 20))
    p = QPainter(gen)
    p.setRenderHint(QPainter.Antialiasing)
    draw(p, QColor(MARK))
    p.end()
    buf.close()
    text = bytes(data).decode("utf-8")
    body = text[text.index("<svg"):]
    body = re.sub(r"<title>.*?</title>|<desc>.*?</desc>|<defs>\s*</defs>", "", body, flags=re.S)
    body = body.replace(MARK, "currentColor")
    # just the drawing: our own <svg>, sized by the page
    inner = body[body.index(">") + 1:body.rindex("</svg>")]
    inner = re.sub(r">\s+<", "><", inner).strip()
    return f'<svg viewBox="0 0 20 20" aria-hidden="true">{inner}</svg>'


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    out = {name: svg(name) for name in NAMES}
    OUT.write_text(
        "// The app's own icons (src/ui/icons.py) as SVG, in currentColor, for the\n"
        "// demo window. Written by tools/make_demo_icons.py -- never edit by hand.\n"
        "window.OGPDemoIcons = " + json.dumps(out, indent=1) + ";\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(out)} icons to {OUT}")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
