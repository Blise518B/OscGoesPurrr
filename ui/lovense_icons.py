"""Lovense product icon catalog with auto-detection from buttplug device names.

The icon PNGs live in `Images/lovense_icons/` (downloaded from cdn.lovense.com
at dev time). Auto-detection runs the device name through a longest-match-wins
substring check so "Lovense Solace Pro" picks `solace_pro` rather than `solace`,
and so a user-renamed device like "My Gush 2" still matches `gush_2`.

Manual override is stored per-device under the profile key `icon_override`:
    - missing / None: auto-detect from the device name
    - "" (empty string): user explicitly disabled the icon
    - any other key: force that icon, regardless of name
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QLabel, QPushButton, QScrollArea, QToolButton,
    QVBoxLayout, QWidget,
)


ICONS_DIR = Path(__file__).resolve().parent.parent / "Images" / "lovense_icons"


# (key, display_name, [match_patterns]) — patterns are normalized (lowercase, alphanumerics
# and single spaces). Patterns are sorted by length descending at match time so the most
# specific variant wins (e.g. "solace pro" before "solace", "lush 4" before "lush").
# Despite the module name the catalog isn't Lovense-only: non-Lovense devices with a
# procedurally drawn icon (see tools/generate_handy_icon.py) live here too.
TOYS: List[Tuple[str, str, List[str]]] = [
    ("the_handy",        "The Handy",        ["the handy", "thehandy", "handy"]),
    ("velvo",            "Velvo",            ["velvo"]),
    ("lush_4",           "Lush 4",           ["lush 4", "lush4"]),
    ("lush_mini",        "Lush Mini",        ["lush mini", "lushmini"]),
    ("lush_3",           "Lush 3",           ["lush 3", "lush3"]),
    ("lush_anal",        "Lush Anal",        ["lush anal"]),
    ("ferri",            "Ferri",            ["ferri"]),
    ("nora",             "Nora",             ["nora"]),
    ("spinel",           "Spinel",           ["spinel"]),
    ("tenera_2",         "Tenera 2",         ["tenera 2", "tenera2"]),
    ("tenera",           "Tenera",           ["tenera"]),
    ("osci_3",           "Osci 3",           ["osci 3", "osci3", "osci"]),
    ("mission_2",        "Mission 2",        ["mission 2", "mission2", "mission"]),
    ("flexer",           "Flexer",           ["flexer"]),
    ("gravity",          "Gravity",          ["gravity"]),
    ("dolce",            "Dolce",            ["dolce", "quake"]),
    ("vulse",            "Vulse",            ["vulse"]),
    ("lapis",            "Lapis",            ["lapis"]),
    ("ambi",             "Ambi",             ["ambi"]),
    ("hyphy",            "Hyphy",            ["hyphy"]),
    ("exomoon",          "Exomoon",          ["exomoon"]),
    ("gush_2",           "Gush 2",           ["gush 2", "gush2", "gush"]),
    ("edge_2",           "Edge 2",           ["edge 2", "edge2", "edge"]),
    ("solace_pro",       "Solace Pro",       ["solace pro"]),
    ("solace",           "Solace",           ["solace"]),
    ("max_2",            "Max 2",            ["max 2", "max2", "max"]),
    ("diamo",            "Diamo",            ["diamo"]),
    ("calor",            "Calor",            ["calor"]),
    ("kraken",           "Kraken",           ["kraken"]),
    ("mini_sex_machine", "Mini Sex Machine", ["mini sex machine"]),
    ("sex_machine",      "Sex Machine",      ["sex machine"]),
    ("ridge",            "Ridge",            ["ridge"]),
    ("hush_2",           "Hush 2",           ["hush 2", "hush2", "hush"]),
    ("domi_2",           "Domi 2",           ["domi 2", "domi2", "domi"]),
    ("gemini",           "Gemini",           ["gemini"]),
]


_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(name: str) -> str:
    return _NORMALIZE_RE.sub(" ", name.lower()).strip()


# Pre-flatten patterns into (pattern, key) sorted longest-first so the first
# substring hit is the most specific match.
_MATCH_TABLE: List[Tuple[str, str]] = sorted(
    [(p, key) for key, _disp, pats in TOYS for p in pats],
    key=lambda kv: -len(kv[0]),
)


def detect_toy_key(device_name: str) -> Optional[str]:
    """Return the canonical toy key matching this device name, or None."""
    if not device_name:
        return None
    norm = _normalize(device_name)
    if not norm:
        return None
    padded = f" {norm} "
    for pattern, key in _MATCH_TABLE:
        # Use word-boundary-ish check: surround with spaces so "max" doesn't
        # match inside "maximum", but "lovense max 2" still hits.
        if f" {pattern} " in padded:
            return key
    return None


def icon_path(key: Optional[str]) -> Optional[Path]:
    if not key:
        return None
    p = ICONS_DIR / f"{key}.png"
    return p if p.is_file() else None


def display_name(key: str) -> str:
    for k, disp, _pats in TOYS:
        if k == key:
            return disp
    return key


def all_toys() -> List[Tuple[str, str]]:
    """Return [(key, display_name), ...] for every catalog entry that has a file on disk."""
    out = []
    for key, disp, _pats in TOYS:
        if (ICONS_DIR / f"{key}.png").is_file():
            out.append((key, disp))
    return out


def resolve_key(device_name: str, override: Optional[str]) -> Optional[str]:
    """Apply override semantics (see module docstring) and fall back to auto-detect."""
    if override is None:
        return detect_toy_key(device_name)
    if override == "":
        return None  # user disabled the icon
    return override


def load_pixmap(key: Optional[str], size: int = 36, circular: bool = True) -> Optional[QPixmap]:
    """Load and scale the icon for `key`. Returns None if no icon is available."""
    path = icon_path(key)
    if path is None:
        return None
    src = QPixmap(str(path))
    if src.isNull():
        return None
    scaled = src.scaled(
        size, size,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )
    if not circular:
        return scaled

    # Composite onto a transparent square, clipped to a circle. Preserves the
    # source's own transparency (these PNGs already ship with alpha) while
    # giving the row a tidy round badge.
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    path_clip = QPainterPath()
    path_clip.addEllipse(QRectF(0, 0, size, size))
    painter.setClipPath(path_clip)
    # Center the scaled pixmap inside the square.
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return out


# ---------------------------------------------------------------------------
# Picker dialog
# ---------------------------------------------------------------------------

# Sentinels returned by pick_icon().
PICK_CANCELLED = object()  # user dismissed the dialog — caller should not save
PICK_AUTO = None           # restore auto-detection (clear override)
PICK_NONE = ""             # explicitly hide the icon


def pick_icon(parent, device_name: str, current_override):
    """Show a modal grid of every Lovense icon. Returns one of:
        PICK_CANCELLED  — leave the existing override unchanged
        PICK_AUTO       — clear override (use auto-detect)
        PICK_NONE       — hide the icon
        "<key>"         — force the given toy icon

    `current_override` follows the same semantics as the stored value
    (None = auto, "" = hidden, str = forced).
    """

    dlg = QDialog(parent)
    dlg.setWindowTitle(f"Pick icon — {device_name}")
    dlg.setModal(True)
    dlg.resize(560, 560)

    outer = QVBoxLayout(dlg)
    outer.setContentsMargins(12, 12, 12, 12)
    outer.setSpacing(8)

    header = QLabel(f"Pick an icon for <b>{device_name}</b>")
    header.setAlignment(Qt.AlignHCenter)
    outer.addWidget(header)

    detected = detect_toy_key(device_name)
    sub_parts = []
    if detected:
        sub_parts.append(f"Auto-detected: <b>{display_name(detected)}</b>")
    else:
        sub_parts.append("No icon was auto-detected from the device name.")
    sub = QLabel(" · ".join(sub_parts))
    sub.setAlignment(Qt.AlignHCenter)
    sub.setProperty("muted", "true")
    outer.addWidget(sub)

    # Top action row: Auto / Hide
    top_row = QWidget()
    top_lay = QGridLayout(top_row)
    top_lay.setContentsMargins(0, 0, 0, 0)
    auto_btn = QPushButton("Use auto-detect")
    hide_btn = QPushButton("Hide icon")
    hide_btn.setProperty("role", "secondary")
    top_lay.addWidget(auto_btn, 0, 0)
    top_lay.addWidget(hide_btn, 0, 1)
    outer.addWidget(top_row)

    # Scrollable grid
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    container = QWidget()
    grid = QGridLayout(container)
    grid.setContentsMargins(4, 4, 4, 4)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(6)

    icon_size = 56
    cols = 5
    for idx, (key, disp) in enumerate(all_toys()):
        btn = QToolButton()
        pm = load_pixmap(key, icon_size, circular=True)
        if pm is not None:
            btn.setIcon(QIcon(pm))
            btn.setIconSize(QSize(icon_size, icon_size))
        btn.setText(disp)
        btn.setToolTip(disp)
        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setMinimumSize(QSize(icon_size + 24, icon_size + 32))
        if isinstance(current_override, str) and current_override == key:
            btn.setChecked(True)

        def _on_click(_=False, k=key):
            state["chosen"] = k
            dlg.accept()

        btn.clicked.connect(_on_click)
        grid.addWidget(btn, idx // cols, idx % cols)

    scroll.setWidget(container)
    outer.addWidget(scroll, 1)

    cancel_btn = QPushButton("Cancel")
    cancel_btn.setProperty("role", "secondary")
    outer.addWidget(cancel_btn, alignment=Qt.AlignRight)

    state = {"chosen": PICK_CANCELLED}

    def _on_auto():
        state["chosen"] = PICK_AUTO
        dlg.accept()

    def _on_hide():
        state["chosen"] = PICK_NONE
        dlg.accept()

    auto_btn.clicked.connect(_on_auto)
    hide_btn.clicked.connect(_on_hide)
    cancel_btn.clicked.connect(dlg.reject)

    if dlg.exec() == QDialog.Accepted:
        return state["chosen"]
    return PICK_CANCELLED
