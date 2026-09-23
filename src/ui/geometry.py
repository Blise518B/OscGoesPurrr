"""Tk-style geometry string helpers used by the main window's save/restore."""

import re

_TK_GEOM_RE = re.compile(r"^\s*(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?\s*$")


def parse_tk_geometry(geom: str):
    """Parse a Tkinter-style geometry string into (w, h, x, y).
    Returns None on failure. x/y may be None when not present."""
    if not geom:
        return None
    m = _TK_GEOM_RE.match(geom)
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    x = int(m.group(3)) if m.group(3) is not None else None
    y = int(m.group(4)) if m.group(4) is not None else None
    return (w, h, x, y)


def format_tk_geometry(w: int, h: int, x: int, y: int) -> str:
    return f"{w}x{h}+{x}+{y}"
