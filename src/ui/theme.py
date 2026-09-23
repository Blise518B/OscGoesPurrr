"""OscGoesPurrr's look: the 518 design system, built from `ui/theme_tokens.py`.

Two modes, one green. `theme_tokens.py` is a verbatim copy of
`_hub\\design\\theme_tokens.py` and is the only place a colour is spelled
out; nothing in this module retypes a hex. The semantic roles OGP needs on
top of the shared tokens (what "live signal" is, which hue each chain type
and trace wears) are declared here once, as *names* of tokens.

Import-safe: no Qt at module level, because `constants.py` resolves the
mode and the `COLOR_*` aliases from here before any widget exists (every
module copies those at import, so a mode switch applies on restart -- the
same contract the old colour profiles had). `install_fonts()` is the one
Qt touch and runs from the UI bootstrap.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, Tuple

import theme_tokens as T          # the verbatim hub copy, at the project root
from constants import UI_MODE      # resolved once, Qt-free, in constants.py

# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

SETTING_KEY = "ui_mode"
DEFAULT_MODE = T.DEFAULT_MODE
MODE_ORDER = list(T.MODE_ORDER)
MODE_LABELS = dict(T.MODE_LABELS)


def normalize_mode(raw) -> str:
    """Resolve a stored mode name, tolerating the legacy `broker` alias and
    anything unknown (-> the default)."""
    key = T.LEGACY_MODE_ALIASES.get(str(raw), str(raw))
    return key if key in T.MODES else DEFAULT_MODE


def other_mode(mode_name: str) -> str:
    """The mode the header toggle switches TO."""
    return "midnight" if normalize_mode(mode_name) == "neon" else "neon"


MODE = UI_MODE
CHROME: Dict[str, str] = dict(T.mode(MODE))
PALETTE: Dict[str, Tuple[str, str, str]] = T.PALETTE
RADIUS = T.RADIUS

# ---------------------------------------------------------------------------
# OGP's semantic roles -- names of tokens, never values.
#
#   live   the haptic signal itself: meters, charged chain borders, connector
#          arrows, the OSC-inspector value ramp. PINK, because that is what
#          the data is about (the R18 hue) and it keeps the app's "live =
#          pink" language readable at a glance. Not cyan: that is the
#          generic "something is running" state.
#   run    a job in flight: simulator playing, session recording, replay.
#   warn   waiting, stale, disconnected, paused -- NOT errors.
#   err    actual failures and destructive buttons, nothing else.
# ---------------------------------------------------------------------------

LIVE = PALETTE["pink"]
RUN = PALETTE["cyan"]
WARN = PALETTE["amber"]
ERR = PALETTE["red"]
OK = (CHROME["accent"], PALETTE["green"][1], PALETTE["green"][2])

# Identity hues, assigned by what a box IS (design-518 rule 8: in palette
# order, to a category, never per item):
#   toys   -- the top-level group frames -- cycle through the three cool
#             hues after the chrome green, so three toys stacked read as
#             three; a fourth starts over.
#   chains -- the cards inside a toy -- one hue per TYPE from the hues no
#             toy can wear, so a chain frame is never mistaken for a toy
#             frame: penetration pink (the act), touch amber, custom grey
#             (the neutral).
# Structure carries the rest: a toy is a group frame with a filled header
# bar in its hue; a chain is a card with a thin hue border and a stripe.
TOY_HUES = ("cyan", "blue", "purple")
CHAIN_TYPE_HUES = {"penetration": "pink", "touch": "amber", "custom": "grey"}


def toy_hue(index: int) -> str:
    """The hue for the toy at display position `index` (0-based)."""
    return TOY_HUES[int(index) % len(TOY_HUES)]

# One hue per stage trace, by what the signal IS. Depth is the blue family,
# speed amber, punch pink (it is the live accent's spike), the outward
# halves take the cool complement of their stage, combined is purple, the
# wake meter yellow, the post-wake / envelope signals cyan, and the chain's
# final output is the accent itself.
TRACE_HUES = {
    "d_raw": "blue", "d_shaped": "blue",
    "s_raw": "amber", "s_shaped": "amber", "s_in_shaped": "amber",
    "s_out_shaped": "cyan",
    "punch": "pink", "punch_in": "pink", "punch_out": "purple",
    "mixed": "purple",
    "wake_meter": "yellow", "wake_out": "cyan",
    "smoothed": "cyan", "textured": "grey",
}

# Neon's filled header bars, one per hue: (bar fill, frame border). Not in
# the shared token file yet -- these are VRCDollySync's / FFMPEG Studio's
# `_NEON_CAT_BARS`, copied from the reference apps rather than derived;
# Midnight uses the hue's tint as the fill and its mid tone as the frame.
NEON_CAT_BARS = {
    "green":  ("#1c8a3d", "#36a35c"),
    "blue":   ("#1e5fa0", "#3b6ea3"),
    "cyan":   ("#15808f", "#2e93a3"),
    "yellow": ("#a06a14", "#b3813a"),
    "red":    ("#9c2531", "#b04552"),
    "purple": ("#7a3fa8", "#9159ba"),
}
NEON_CAT_BAR = NEON_CAT_BARS["green"][0]


def hue(name: str) -> str:
    """Vibrant tone of an identity hue by name."""
    return PALETTE[name][0]


def tri(name: str) -> Tuple[str, str, str]:
    return PALETTE[name]


def qss_vars(mode_name: str = MODE) -> Dict[str, str]:
    """Flat name -> value mapping for the stylesheet template: the mode's
    chrome, every identity tone (`pink`, `pink_mid`, `pink_tint`, ...),
    the semantic roles above, radii, and the section-bar fill."""
    v: Dict[str, str] = dict(T.mode(mode_name))
    for key, (vib, mid, tint) in PALETTE.items():
        v[key] = vib
        v[f"{key}_mid"] = mid
        v[f"{key}_tint"] = tint
    for key, (vib, mid, tint) in (("live", LIVE), ("run", RUN),
                                  ("warn", WARN), ("err", ERR)):
        v[key] = vib
        v[f"{key}_mid"] = mid
        v[f"{key}_tint"] = tint
    v["ok"] = v["accent"]
    v["ok_mid"] = PALETTE["green"][1]
    v["ok_tint"] = PALETTE["green"][2]
    for key, px in RADIUS.items():
        v[f"r_{key}"] = str(px)
    if mode_name == "neon":
        v["catbar"] = NEON_CAT_BAR
        v["catbar_text"] = v["txt"]
    else:
        v["catbar"] = v["tint"]
        v["catbar_text"] = v["accent"]
    return v


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

def asset_dir() -> str:
    """The bundled `Images/` directory, in dev and in the PyInstaller exe."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "Images")  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "Images")


def bundle_path(name: str) -> str:
    """A file shipped at the repository root (LICENSE,
    THIRD_PARTY_NOTICES.md): next to src/ in dev, in the PyInstaller exe's
    bundle when frozen."""
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, name)  # type: ignore[attr-defined]
    src = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(os.path.dirname(src), name)


def image_url(name: str) -> str:
    """Absolute url() path for an `Images/` asset, for use inside QSS
    (forward slashes, even on Windows)."""
    return os.path.join(asset_dir(), name).replace("\\", "/")


def install_fonts() -> None:
    """Register the bundled title face (Aldrich, OFL) with Qt. Idempotent;
    silently a no-op when the file is missing so a stripped build still
    runs -- the stylesheet falls back to Segoe UI."""
    try:
        from PySide6.QtGui import QFontDatabase
    except Exception:
        return
    path = os.path.join(asset_dir(), "fonts", "Aldrich-Regular.ttf")
    if os.path.exists(path):
        try:
            QFontDatabase.addApplicationFont(path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Identity tags
# ---------------------------------------------------------------------------

def title_tag(version: str, build) -> str:
    """`v1.2.51 · b51` -- sits right of the app title, dim, never bold."""
    return T.title_tag(version, build)


def status_tag_html(app_name: str, version: str, accent: str = "") -> str:
    """The bottom-right identity tag as rich text: only `Blise518B` is
    accent-coloured and bold, everything else stays dim."""
    accent = accent or CHROME["accent"]
    return (f"{app_name} v{version} · made by "
            f'<b style="color:{accent}">Blise518B</b>')


# ---------------------------------------------------------------------------
# The stylesheet
# ---------------------------------------------------------------------------

_QSS = """
* {
    color: %(txt)s;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog, QWidget#root { background-color: %(bg)s; }
QToolTip {
    background-color: %(card)s; color: %(txt)s;
    border: 1px solid %(line)s; padding: 4px 6px;
}

/* ---- sidebar / shell ------------------------------------------------ */
QFrame#sidebar {
    background-color: %(panel)s;
    border: none; border-right: 1px solid %(line)s;
}
QLabel#sidebarTitle {
    font-family: "Aldrich", "Segoe UI";
    font-size: 19px; font-weight: 600; letter-spacing: 1px;
    color: %(accent)s;
}
QLabel#buildTag { color: %(dim)s; font-size: 11px; }
QPushButton#modeToggle {
    padding: 2px 6px; font-size: 12px; border-radius: 6px;
    color: %(muted)s;
}
QPushButton#modeToggle:hover { color: %(accent)s; }
QStatusBar {
    background-color: %(panel)s; border-top: 1px solid %(line)s;
    color: %(dim)s; font-size: 11px; min-height: 24px;
}
QStatusBar::item { border: none; }
QLabel#statusTag { color: %(dim)s; font-size: 11px; padding-right: 10px; }
QLabel#statusMessage { color: %(muted)s; font-size: 11px; padding-left: 6px; }

/* ---- surfaces -------------------------------------------------------- */
QFrame#card {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: %(r_card)spx;
}
QFrame#cardDark {
    background-color: %(panel)s;
    border: 1px solid %(line)s; border-radius: %(r_card)spx;
}
QFrame#chip {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: 10px;
}
/* A toy is a GROUP FRAME: panel ground, radius 14, its identity hue as
   the border and a filled header bar (the per-hue variants are appended
   by build_qss). A chain block inside it is a card-level frame in the
   chain's own hue -- no chrome-green outline on either. */
QFrame#toyFrame {
    background-color: %(panel)s;
    border: 1px solid %(line)s; border-radius: %(r_group)spx;
}
QWidget#toyBar { border-radius: %(r_gh)spx; }
QWidget#toyBar QLabel { background: transparent; }
QWidget#toyBar QPushButton {
    background-color: rgba(0, 0, 0, 0.28); border-color: rgba(255, 255, 255, 0.35);
    color: %(txt)s;
}
QWidget#toyBar QPushButton:hover { background-color: rgba(255, 255, 255, 0.12); border-color: %(txt)s; color: %(txt)s; }
QFrame#motorBlock {
    background-color: %(panel)s;
    border: 1px solid %(green_mid)s; border-radius: %(r_group)spx;
}
QFrame#tuneStageCard {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: 10px;
    padding: 4px;
}
QFrame#tuneStageCard[active="true"] { border-color: %(accent)s; }
QFrame#tuneStageCard:hover { background-color: %(hover)s; }
QFrame#stageQuick, QFrame#stageEditorRegion { background: transparent; border: none; }
QLabel#stageOutNum {
    color: %(live)s; font-weight: 600;
    font-family: "Cascadia Mono", Consolas, monospace;
}
QLabel#gainValue { color: %(txt)s; font-weight: 600; }
QLabel#expandCaret { color: %(muted)s; font-size: 15px; }
QFrame#chainFoldBar {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: 10px;
}
QFrame#chainFoldBar:hover { background-color: %(hover)s; border-color: %(accent)s; }
QPushButton#stageCycleButton { padding: 1px 6px; border-radius: 5px; }
QFrame#overviewTile {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: %(r_card)spx;
    padding: 4px;
}
QFrame#overviewTile:hover { background-color: %(hover)s; border-color: %(accent)s; }
QFrame#overviewTile:focus { border-color: %(accent)s; }
QFrame#speedCard, QFrame#zonePanel {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: %(r_btn)spx;
}
QFrame#separator {
    background-color: %(line)s;
    max-height: 1px; min-height: 1px; border: none;
}
QLabel { background: transparent; }

/* ---- type ------------------------------------------------------------ */
QLabel#viewTitle {
    font-family: "Aldrich", "Segoe UI";
    font-size: 19px; font-weight: 600; letter-spacing: 1px;
    color: %(accent)s;
}
/* Section title = the filled header bar (FFMPEG Studio / DollySync's
   category header): the bar is what makes a Neon screen read vibrant. */
QLabel#sectionTitle {
    background-color: %(catbar)s; color: %(catbar_text)s;
    font-size: 14px; font-weight: 700;
    padding: 4px 10px; border-radius: %(r_gh)spx;
}
QLabel#cardHeader {
    font-size: 13px; font-weight: 600; letter-spacing: 0.3px;
    color: %(accent)s;
}
QLabel#deviceName { font-size: 14px; font-weight: 600; color: %(txt)s; }
QLabel#motorLabel { font-size: 14px; font-weight: 600; color: %(txt)s; }
QLabel[accent="live"]    { color: %(live)s; }
QLabel[accent="warn"]    { color: %(warn)s; }
QLabel[accent="ok"]      { color: %(ok)s; }
QLabel[accent="primary"] { color: %(accent)s; }
QLabel[muted="true"]     { color: %(muted)s; font-size: 12px; }
QLabel[hint="true"]      { color: %(dim)s; font-size: 11px; }
QLabel[role="success"]   { color: %(ok)s; }
QLabel[role="alert"]     { color: %(err)s; }
QLabel[role="warning"]   { color: %(warn)s; }
QLabel[role="live"]      { color: %(live)s; }

/* ---- pills / chips --------------------------------------------------- */
QLabel[role="pill"] {
    padding: 2px 9px; border-radius: 10px;
    font-size: 11px; font-weight: 600;
    background-color: %(card)s; color: %(muted)s;
    border: 1px solid %(line)s;
}
QLabel[role="pill"][tone="ok"]   { background-color: %(ok_tint)s;   color: %(ok)s;   border-color: %(ok_mid)s; }
QLabel[role="pill"][tone="off"]  { background-color: %(warn_tint)s; color: %(warn)s; border-color: %(warn_mid)s; }
QLabel[role="pill"][tone="warn"] { background-color: %(warn_tint)s; color: %(warn)s; border-color: %(warn_mid)s; }
QLabel[role="pill"][tone="err"]  { background-color: %(err_tint)s;  color: %(err)s;  border-color: %(err_mid)s; }
QLabel[role="pill"][tone="live"] { background-color: %(live_tint)s; color: %(live)s; border-color: %(live_mid)s; }
QLabel[role="pill"][tone="info"] { background-color: %(run_tint)s;  color: %(run)s;  border-color: %(run_mid)s; }
QLabel[role="pill"][tone="run"]  { background-color: %(run_tint)s;  color: %(run)s;  border-color: %(run_mid)s; }

/* ---- buttons: outlined by default, ONE filled primary per screen ---- */
QPushButton {
    background-color: transparent; color: %(txt)s;
    border: 1px solid %(line)s; border-radius: %(r_btn)spx;
    padding: 6px 12px;
}
QPushButton:hover { background-color: %(hover)s; border-color: %(accent)s; color: %(accent)s; }
QPushButton:pressed { background-color: %(hover)s; }
QPushButton:disabled { color: %(dim)s; border-color: %(green_mid)s; background-color: transparent; }
QPushButton[role="primary"], QPushButton[role="confirm"], QPushButton[role="profileActive"] {
    background-color: %(accent)s; border-color: %(accent)s;
    color: %(ink)s; font-weight: 650;
}
QPushButton[role="primary"]:hover, QPushButton[role="confirm"]:hover,
QPushButton[role="profileActive"]:hover {
    background-color: %(accent2)s; border-color: %(accent2)s; color: %(ink)s;
}
QPushButton[role="secondary"], QPushButton[role="profileIdle"] { color: %(txt)s; }
QPushButton[role="danger"], QPushButton[role="cancel"], QPushButton[role="alert"] {
    background-color: transparent; color: %(err)s;
    border-color: %(err_mid)s; font-weight: 700;
}
QPushButton[role="danger"]:hover, QPushButton[role="cancel"]:hover,
QPushButton[role="alert"]:hover {
    background-color: %(err_tint)s; border-color: %(err)s; color: %(err)s;
}
QPushButton[role="ghost"] {
    background-color: transparent; border-color: transparent;
    color: %(muted)s; text-align: left; padding: 6px 12px;
}
QPushButton[role="ghost"]:hover { border-color: %(line)s; background-color: %(hover)s; color: %(txt)s; }
QPushButton[role="nav"] {
    background-color: transparent; border: 1px solid transparent;
    color: %(muted)s; text-align: left;
    padding: 5px 12px; border-radius: %(r_btn)spx; font-size: 13px;
}
QPushButton[role="nav"]:hover { background-color: %(hover)s; color: %(txt)s; border-color: transparent; }
QPushButton[role="nav"][active="true"] {
    background-color: %(tint)s; color: %(accent)s; font-weight: 600;
}
QPushButton[role="modeBtn"] {
    font-size: 12px; padding: 3px; color: %(muted)s;
}
QPushButton[role="modeBtn"]:hover { color: %(accent)s; }
QPushButton[role="modeBtn"][active="true"], QPushButton[role="modeBtn"]:checked {
    background-color: %(tint)s; border-color: %(accent)s;
    color: %(accent)s; font-weight: 600;
}
/* Off is a panic switch, not a mode: while it silences everything it
   reads as a warning, never as one more green "active". */
QPushButton#sidebarOff:checked {
    background-color: %(warn_tint)s; border-color: %(warn)s; color: %(warn)s;
}
QPushButton[role="chipClose"] {
    background-color: transparent; border-color: transparent;
    color: %(err)s; font-weight: 700; padding: 0px 6px;
}
QPushButton[role="chipClose"]:hover { background-color: %(err_tint)s; border-color: %(err_mid)s; }
QPushButton[role="segActive"] {
    background-color: %(tint)s; border-color: %(accent)s;
    color: %(accent)s; font-weight: 600;
}
QPushButton[role="segIdle"] { color: %(muted)s; }
QPushButton[role="segIdle"]:hover { color: %(accent)s; }
QPushButton[role="switch"]:checked {
    background-color: %(accent)s; border-color: %(accent)s; color: %(ink)s;
}

/* ---- inputs ---------------------------------------------------------- */
QLineEdit, QTextEdit, QPlainTextEdit,
QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox {
    background-color: %(well)s; color: %(txt)s;
    border: 1px solid %(line)s; border-radius: %(r_input)spx;
    padding: 4px 8px;
    selection-background-color: %(accent)s; selection-color: %(ink)s;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QAbstractSpinBox:focus,
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QAbstractSpinBox:hover {
    border-color: %(accent)s;
}
/* One control height (30px) for every single-line input: the native
   style's stacked-arrow allowance made spinboxes 46px and line edits
   42px; spinboxes get 4px less content because their buttons add it. */
QLineEdit, QComboBox { min-height: 20px; max-height: 20px; }
QAbstractSpinBox { min-height: 20px; max-height: 20px; }
QTextEdit, QPlainTextEdit { font-family: "Cascadia Mono", Consolas, "Courier New", monospace; }
/* Spinbox up/down buttons, owned by the stylesheet on purpose: the Qt 6.7+
   "windows11" base style paints the two arrows side by side and (with an
   app stylesheet active) its hit-testing does not match the painted
   arrows -- the up arrow goes dead. Defining the subcontrols here makes
   QStyleSheetStyle compute layout, painting AND hit-testing from these
   same boxes. The arrows are bundled SVGs. */
QAbstractSpinBox { padding-right: 20px; }
QAbstractSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border-left: 1px solid %(line)s;
    border-top-right-radius: 6px; background: transparent;
}
QAbstractSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border-left: 1px solid %(line)s;
    border-bottom-right-radius: 6px; background: transparent;
}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background: %(hover)s; }
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed { background: %(tint)s; }
QAbstractSpinBox::up-arrow   { image: url("%(arrow_up)s");   width: 8px; height: 5px; }
QAbstractSpinBox::down-arrow { image: url("%(arrow_down)s"); width: 8px; height: 5px; }
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off     { image: url("%(arrow_up_dim)s"); }
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off { image: url("%(arrow_down_dim)s"); }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: top right;
    width: 22px; border: none; border-left: 1px solid %(line)s;
}
QComboBox::down-arrow { image: url("%(arrow_down)s"); width: 8px; height: 5px; }
QComboBox::down-arrow:disabled { image: url("%(arrow_down_dim)s"); }
QComboBox QAbstractItemView {
    background-color: %(card)s; color: %(txt)s;
    border: 1px solid %(line)s;
    selection-background-color: %(tint)s; selection-color: %(accent)s;
    outline: 0;
}

QCheckBox { background: transparent; spacing: 6px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid %(line)s; border-radius: 4px;
    background-color: %(well)s;
}
QCheckBox::indicator:checked { background-color: %(accent)s; border-color: %(accent)s; }
QCheckBox::indicator:hover { border-color: %(accent)s; }
QCheckBox[role="switch"]::indicator { width: 32px; height: 16px; border-radius: 8px; }

/* ---- sliders / meters ------------------------------------------------ */
QSlider { background: transparent; border: none; }
QSlider::groove:horizontal {
    height: 6px; background: %(well)s;
    border: 1px solid %(line)s; border-radius: 4px;
}
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 3px; margin: 1px; }
QSlider::add-page:horizontal { background: transparent; }
QSlider::handle:horizontal {
    background: %(accent)s; width: 14px; height: 14px;
    margin: -4px 0; border-radius: 7px; border: none;   /* 8px groove -> 14px circle */
}
QSlider::handle:horizontal:hover { background: %(accent2)s; }
QSlider::sub-page:horizontal:disabled { background: %(green_mid)s; }
QSlider::handle:horizontal:disabled { background: %(green_mid)s; }

/* the sidebar's total output strength: a bar you can grab without aiming */
QSlider#strengthSlider::groove:horizontal { height: 12px; border-radius: 7px; }
QSlider#strengthSlider::sub-page:horizontal { border-radius: 6px; }
QSlider#strengthSlider::handle:horizontal {
    width: 26px; height: 26px; margin: -8px 0; border-radius: 13px;
    border: 3px solid %(panel)s;
}
QLabel#strengthTitle { color: %(muted)s; font-size: 12px; }
QLabel#strengthValue { color: %(accent)s; font-size: 17px; font-weight: 700; }

QProgressBar {
    background: %(well)s; border: 1px solid %(line)s; border-radius: 4px;
    text-align: center; color: transparent;
    max-height: 8px; min-height: 8px;
}
QProgressBar::chunk { border-radius: 3px; background-color: %(accent)s; }
QProgressBar[tone="ok"]::chunk   { background-color: %(ok)s; }
QProgressBar[tone="warn"]::chunk { background-color: %(warn)s; }
QProgressBar[tone="live"]::chunk { background-color: %(live)s; }
QProgressBar[tone="rainbow"]::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 %(accent)s, stop:1 %(live)s);
}

QScrollArea { border: none; background-color: transparent; }
QScrollArea > QWidget > QWidget { background-color: transparent; }
/* Painted by RainbowScrollBar -- only sizing here. */
QScrollBar { background: transparent; border: none; }
QScrollBar:vertical { width: 10px; }
QScrollBar:horizontal { height: 10px; }

/* ---- tables / trees / tabs / menus ---------------------------------- */
QTreeWidget, QTableWidget, QListWidget {
    background-color: %(panel)s; alternate-background-color: %(card)s;
    color: %(txt)s; border: 1px solid %(line)s; border-radius: %(r_btn)spx;
    gridline-color: transparent;
}
QTreeWidget { font-family: "Cascadia Mono", Consolas, "Courier New", monospace; }
QTreeWidget::item { height: 22px; }
QTreeWidget::item:selected, QTableWidget::item:selected, QListWidget::item:selected {
    background-color: %(tint)s; color: %(accent)s;
}
QTableWidget::item { padding: 0px 6px; }
QHeaderView::section {
    background-color: %(panel)s; color: %(dim)s;
    padding: 5px 8px; border: none; border-bottom: 1px solid %(line)s;
    font-size: 10px; font-weight: 700; letter-spacing: 1px;
}
QHeaderView::section:horizontal:!last { border-right: 1px solid %(green_mid)s; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab {
    background-color: %(card)s; color: %(muted)s;
    border: 1px solid %(line)s; border-radius: %(r_btn)spx;
    padding: 5px 12px; margin-right: 4px; margin-bottom: 4px;
}
QTabBar::tab:hover { color: %(txt)s; background-color: %(hover)s; }
QTabBar::tab:selected { background-color: %(tint)s; color: %(accent)s; border-color: %(accent)s; }
QMenu { background-color: %(card)s; border: 1px solid %(line)s; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 5px; }
QMenu::item:selected { background-color: %(tint)s; color: %(accent)s; }
QGroupBox {
    border: 1px solid %(line)s; border-radius: 10px;
    margin-top: 12px; padding: 14px 12px 8px;
    font-weight: 700; color: %(accent)s;
}
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px; }
QSplitter::handle { background: %(line)s; }
QSplitter::handle:hover { background: %(accent)s; }
"""


def _hue_variants(mode_name: str, v: Dict[str, str]) -> str:
    """Per-hue rules: a toy frame + header bar for every toy hue, a chain
    frame + fold bar for every chain-type hue."""
    neon = normalize_mode(mode_name) == "neon"
    out = []
    for hue in TOY_HUES:
        vib, mid, tint = PALETTE[hue]
        fill, border = NEON_CAT_BARS[hue] if neon else (tint, mid)
        text = v["txt"] if neon else vib
        out.append(
            f'QFrame#toyFrame[hue="{hue}"] {{ border-color: {border}; }}\n'
            f'QWidget#toyBar[hue="{hue}"] {{ background-color: {fill}; }}\n'
            f'QWidget#toyBar[hue="{hue}"] QLabel {{ color: {text}; }}\n'
            f'QWidget#toyBar[hue="{hue}"] QLabel#deviceName {{ color: {text}; }}\n'
        )
    for hue in sorted(set(CHAIN_TYPE_HUES.values())):
        vib, mid, tint = PALETTE[hue]
        out.append(
            f'QFrame#chainFoldBar[hue="{hue}"] {{ border-color: {mid}; }}\n'
            f'QFrame#chainFoldBar[hue="{hue}"]:hover {{ border-color: {vib}; }}\n'
            f'QFrame#motorBlock[hue="{hue}"] {{ border-color: {mid}; }}\n'
        )
    return "".join(out)


def build_qss(mode_name: str = MODE) -> str:
    """The whole application stylesheet for a mode, from the tokens."""
    v = qss_vars(mode_name)
    v["arrow_up"] = image_url("spin_arrow_up.svg")
    v["arrow_down"] = image_url("spin_arrow_down.svg")
    v["arrow_up_dim"] = image_url("spin_arrow_up_dim.svg")
    v["arrow_down_dim"] = image_url("spin_arrow_down_dim.svg")
    return (_QSS % v) + _hue_variants(mode_name, v)


_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def hexes_in(text: str) -> set:
    """Every 6-digit hex in a stylesheet -- for the test that pins the
    sheet to the token set."""
    return {h.lower() for h in _HEX.findall(text)}
