"""The 518 design system — token source of truth for PySide/Qt apps.

Spec: ``_hub\\design-518.md``.  Web equivalent: ``_hub\\design\\tokens.css``.

Copy this file into a new program as-is and build the QSS from it.  Do not
retype hexes, do not invent a per-app accent — every 518 program is green.

Two modes, one difference: NEON draws every border in a true green so cards
read as *outlined*; MIDNIGHT uses a near-invisible hairline so they *float*.
Shapes, spacing, radii and type are identical.  **NEON is the default** —
it is the mode an app opens in.

The identity hues are mode-independent: only the chrome swaps.

Historical note: Midnight's internal name in older stylesheets (VRCDollySync,
VRCParameterRelay) is ``broker``.  Keep that key in saved settings — renaming
it would orphan every user's stored choice.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Chrome — the only thing that differs between the two modes.
#
# FOUR SURFACES, ONE RULE EACH:
#   bg    = the window
#   panel = bars and frames  (header, status bar, group frames, tables)
#   card  = things you look at  (cards, chips, tiles, menus) — THE GREY
#   well  = things you type into or read logs from
# If an element is not obviously one of the four, it is `card`.
# ---------------------------------------------------------------------------

NEON = {
    "bg":      "#0a0c0a",
    "panel":   "#0f120f",
    "card":    "#121712",
    "well":    "#070907",
    "hover":   "#142418",  # mouse over anything; pressed = hover + 1px nudge
    "line":    "#36a35c",  # THE FRAME — every 1px border, scrollbar, separators
    "tint":    "#143a22",  # dark green fill behind accent text
    "accent":  "#31f272",  # THE GREEN
    "accent2": "#62ff97",  # hover on a FILLED accent surface only
    "ink":     "#04150b",  # text ON a filled accent — never white
    "txt":     "#e6efe8",  # body text
    "muted":   "#94a698",  # secondary text, chip labels
    "dim":     "#5f6f63",  # hints, status bar, micro-labels, column headers
}

MIDNIGHT = {
    "bg":      "#07090c",
    "panel":   "#090d0a",
    "card":    "#0b0f0c",
    "well":    "#05070a",
    "hover":   "#0d1712",
    "line":    "#243029",  # near-invisible hairline — cards float
    "tint":    "#10291a",
    "accent":  "#4af58c",
    "accent2": "#7dffb0",
    "ink":     "#04120a",
    "txt":     "#c9d4cc",
    "muted":   "#7c8a80",
    "dim":     "#5f6f64",
}

MODES = {"neon": NEON, "midnight": MIDNIGHT}
MODE_LABELS = {"neon": "Neon (default)", "midnight": "Midnight"}
MODE_ORDER = ["neon", "midnight"]
DEFAULT_MODE = "neon"

# Older apps persist Midnight as "broker" — a saved setting from before
# 2026-09-07 still resolves.
LEGACY_MODE_ALIASES = {"broker": "midnight"}

# Older token names -> the current four surfaces, for reading an old sheet.
LEGACY_TOKEN_ALIASES = {
    "header": "panel", "group": "panel",
    "panel2": "card", "chip": "card",
    "field": "well",
    "press": "hover",
    "faint": "dim",
    # "edge" -> PALETTE["green"][1] (green-mid); see qss_vars()
}


def mode(name: str) -> dict:
    """Return the chrome dict for a mode name, tolerating the legacy alias."""
    key = LEGACY_MODE_ALIASES.get(name, name)
    return MODES.get(key, NEON)


# ---------------------------------------------------------------------------
# Identity palette — one colour per category/function, THE SAME IN BOTH MODES
#   vibrant = text / icons / the value   ·   mid = the 1px border
#   tint    = the dark fill behind it
# A value NEVER changes colour because it went bad — see RULES below.
# ---------------------------------------------------------------------------

PALETTE = {
    #            vibrant     mid         tint         used for
    "green":   ("#4af58c", "#2f5e3f", "#10291a"),  # house accent; done, OK, owned; NVIDIA/GPU
    "cyan":    ("#56d9f2", "#2f6b7a", "#0e2229"),  # running, live; clock in HUDs
    "blue":    ("#7aa7ff", "#3a5384", "#131c30"),  # links, sync, backup
    "purple":  ("#d78cff", "#5e3f78", "#221430"),  # AI, models, memory; batteries in HUDs
    "pink":    ("#ff5da2", "#66284a", "#2a0f1d"),  # R18/NSFW, chat, media, notifications
    "red":     ("#ff5561", "#5c2228", "#2a1014"),  # ERRORS ONLY — never an accent; AMD/CPU
    "orange":  ("#f97316", "#6b3a16", "#2a1707"),  # updaters, nags
    "amber":   ("#ffb454", "#6b5320", "#291f0c"),  # warnings, paused, remote, stale; FPS
    "yellow":  ("#ffd60a", "#6b5a0f", "#2a2205"),  # containers, VMs, scheduled tasks
    "grey":    ("#9aa5b3", "#454f5c", "#171b20"),  # protected, neutral, N/A, locked, services
}

PALETTE_LABELS = {
    "green": "Green", "cyan": "Cyan", "blue": "Blue", "purple": "Purple",
    "pink": "Pink", "red": "Red", "orange": "Orange", "amber": "Amber",
    "yellow": "Yellow", "grey": "Grey",
}

# Assignment order — a group of N items takes the first N of these, in order,
# so colour assignment is deterministic instead of arbitrary. More than ten
# doubles up on grey before inventing an eleventh hue.
PALETTE_ORDER = [
    "green", "cyan", "blue", "purple", "pink",
    "amber", "orange", "yellow", "red", "grey",
]

# Retired: a second hex under a name that already had one (2026-09-07), and
# three hues that sat on top of a neighbour (2026-09-10). Kept only so a
# migration can recognise and replace them.
RETIRED = {
    "#22d3ee": "cyan",    # -> #56d9f2
    "#a877ff": "purple",  # -> #d78cff
    "#4f7cff": "blue",    # -> #7aa7ff
    "#fbbf24": "amber",   # -> #ffb454
    "#d946ef": "pink",    # fuchsia -> pink
    "#12a88b": "green",   # teal    -> green (or grey for a neutral)
    "#a3e635": "green",   # lime    -> green
}

# ---------------------------------------------------------------------------
# Semantic states — always go through these, never the hue directly, so a
# state can be re-pointed in one edit.
# ---------------------------------------------------------------------------

# `ok` follows the ACCENT, so it brightens with Neon; the other three are
# identical in both modes. Known variance: DollySync's Qt NEON_QSS still uses
# ok #3af0a0 / bad #f87171 for chip states - converge when next touched.
STATES = {
    "ok":   PALETTE["green"],
    "run":  PALETTE["cyan"],
    "warn": PALETTE["amber"],
    "bad":  PALETTE["red"],
}

# ---------------------------------------------------------------------------
# Type · radius · shadow
# ---------------------------------------------------------------------------

DEFAULT_FONT = "Segoe UI"
BASE_SIZE_PX = 13
MONO_FONT = '"Cascadia Mono", Consolas, monospace'
TITLE_FONT = "Aldrich"          # bundled OFL; falls back to Segoe UI

FONT_GROUPS = [
    ("Clean & rounded", [
        ("Segoe UI", "clean modern sans — the default"),
        ("Century Gothic", "very round, geometric"),
    ]),
    ("Sci-fi & techno (bundled)", [
        ("Orbitron", "wide geometric, slashed zeros"),
        ("Aldrich", "square techno — the 518 title face"),
        ("Audiowide", "retro-futuristic, rounded"),
    ]),
]
FONT_CHOICES = [item for _, items in FONT_GROUPS for item in items]

# size_px, weight, role
TYPE_SCALE = [
    (19, 600, "app title (desktop), page heading — Aldrich, accent, +1px tracking"),
    (17, 600, "big numbers / tile values — mono, tabular-nums"),
    (14, 600, "group header"),
    (13, 600, "card heading — in the accent, +0.3px tracking"),
    (13, 400, "body, labels, controls"),
    (12, 400, "secondary text, table cells — muted"),
    (11, 400, "hint line under every setting, status bar — dim"),
    (10, 700, "column headers, micro-labels — UPPERCASE, +1px tracking, dim"),
]

# One value per role — NOT one radius stamped on everything.
RADIUS = {
    "group": 14,   # group frame
    "card": 12,    # card
    "gh": 9,       # group header bar
    "btn": 8,      # button, badge, tile, popup
    "input": 7,    # input, select
    "chip": 999,   # chip (pill)
}

# The only shadows in the system. Separation comes from the border, not depth.
GLOW = "0 0 6px"                       # live dots, at 50% of the hue
POPUP_SHADOW = "0 8px 30px rgba(0, 0, 0, 0.6)"

# ---------------------------------------------------------------------------
# The rules a stylesheet cannot enforce — see design-518.md §4
# ---------------------------------------------------------------------------

RULES = """
1. Red means broken. Warnings/pauses/down services are AMBER. The one
   exception: an identity palette where red simply names a group.
2. State belongs to the BACKGROUND, not the text. Tint the row background;
   leave the value's identity colour intact. A number never changes colour
   because it crossed a threshold. Until an app can do that, threshold
   recolouring stays OFF.
3. Group colours by WHAT THE DATA IS ABOUT, not by where it sits on screen.
   VRAM is GPU-coloured and RAM is CPU-coloured even when the rows are
   neighbours. Brand-code where it helps: NVIDIA/GPU green, AMD/CPU red.
4. Err loud - "rather too vibrant than too thin". HDR/in-world surfaces
   scale colours so the brightest channel hits 2.0 before emission.
5. When a data hue collides with the chrome hue, dim the STRUCTURE, not the
   data: internal dividers drop to green-mid, the outer frame stays full.
6. Exactly ONE filled accent surface (the primary button) per screen.
7. No per-app accent. Every 518 program is green.
8. Identity colour is assigned to a CATEGORY in PALETTE_ORDER, not picked
   per item.
9. Never white on green - text on a filled accent is `ink`.
10. Glow is the only shadow.
"""


# ---------------------------------------------------------------------------
# The Qt stylesheet. `qss("neon")` renders it; widgets opt in by object name.
#
#   #Header / #StatusBar        the two bars (QWidget / QStatusBar)
#   #AppTitle / #VersionTag     Aldrich title in the accent · dim 11px tag
#   QFrame#Card · QLabel#CardTitle
#   QFrame#Group[hue="purple"] · QWidget#GroupHeader · QLabel#GroupTitle
#   QLabel#Chip[state="ok|run|warn|bad"]     pill in the header / status bar
#   QLabel#Badge[state="ok|run|warn|bad"]    tri-tone badge stuck to a row
#   QPushButton#Primary · #Danger · #Ghost   the ONE filled button · stop · quiet
#   QLabel#Hint                              the dim line under every setting
# ---------------------------------------------------------------------------

QSS_TEMPLATE = """
* { font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QMainWindow, QDialog, QWidget#Body { background: %(bg)s; }
QWidget { color: %(txt)s; }

QWidget#Header { background: %(panel)s; border-bottom: 1px solid %(line)s; }
QLabel#AppTitle { font-family: 'Aldrich', 'Segoe UI'; font-size: 19px; font-weight: 600; color: %(accent)s; letter-spacing: 1px; }
QLabel#VersionTag { color: %(dim)s; font-size: 11px; }
QStatusBar, QWidget#StatusBar { background: %(panel)s; color: %(dim)s; font-size: 11px; border-top: 1px solid %(line)s; }
QStatusBar::item { border: none; }

QFrame#Card { background: %(card)s; border: 1px solid %(line)s; border-radius: %(r_card)spx; }
QLabel#CardTitle { color: %(accent)s; font-weight: 600; letter-spacing: 0.3px; }
QFrame#Group { background: %(panel)s; border: 1px solid %(line)s; border-radius: %(r_group)spx; }
QWidget#GroupHeader { background: %(tint)s; border-radius: %(r_gh)spx; }
QLabel#GroupTitle { color: %(accent)s; font-weight: 700; font-size: 12px; }
QLabel#Hint { color: %(dim)s; font-size: 11px; }

QLabel#Chip { background: %(card)s; border: 1px solid %(line)s; border-radius: 10px; padding: 0 9px; color: %(muted)s; font-size: 11px; }
QLabel#Chip[state="ok"]   { color: %(ok)s;   border-color: %(ok_mid)s; }
QLabel#Chip[state="run"]  { color: %(run)s;  border-color: %(run_mid)s; }
QLabel#Chip[state="warn"] { color: %(warn)s; border-color: %(warn_mid)s; }
QLabel#Chip[state="bad"]  { color: %(bad)s;  border-color: %(bad_mid)s; }
QLabel#Badge { border: 1px solid %(line)s; border-radius: %(r_btn)spx; padding: 0 6px; font-size: 10px; font-weight: 700; color: %(dim)s; }
QLabel#Badge[state="ok"]   { color: %(ok)s;   border-color: %(ok_mid)s;   background: %(ok_tint)s; }
QLabel#Badge[state="run"]  { color: %(run)s;  border-color: %(run_mid)s;  background: %(run_tint)s; }
QLabel#Badge[state="warn"] { color: %(warn)s; border-color: %(warn_mid)s; background: %(warn_tint)s; }
QLabel#Badge[state="bad"]  { color: %(bad)s;  border-color: %(bad_mid)s;  background: %(bad_tint)s; }

QPushButton { background: transparent; border: 1px solid %(line)s; border-radius: %(r_btn)spx; padding: 7px 14px; color: %(txt)s; }
QPushButton:hover { background: %(hover)s; border-color: %(accent)s; color: %(accent)s; }
QPushButton:pressed { background: %(hover)s; padding-top: 8px; padding-bottom: 6px; }
QPushButton:disabled { color: %(dim)s; border-color: %(line)s; }
QPushButton:checked { background: %(tint)s; border-color: %(accent)s; color: %(accent)s; }
QPushButton#Primary { background: %(accent)s; border-color: %(accent)s; color: %(ink)s; font-weight: 650; }
QPushButton#Primary:hover { background: %(accent2)s; border-color: %(accent2)s; color: %(ink)s; }
QPushButton#Danger { color: %(bad)s; border-color: %(bad_mid)s; font-weight: 700; }
QPushButton#Danger:hover { background: %(bad_tint)s; border-color: %(bad)s; color: %(bad)s; }
QPushButton#Ghost { border-color: transparent; color: %(muted)s; }
QPushButton#Ghost:hover { border-color: %(line)s; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background: %(well)s; border: 1px solid %(line)s; border-radius: %(r_input)spx; padding: 5px 8px;
    selection-background-color: %(accent)s; selection-color: %(ink)s;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus { border-color: %(accent)s; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: %(card)s; border: 1px solid %(line)s; selection-background-color: %(tint)s; }
QSpinBox::up-button, QSpinBox::down-button { width: 20px; border: none; background: %(card)s; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(hover)s; }
QCheckBox::indicator, QRadioButton::indicator { width: 14px; height: 14px; border: 1px solid %(line)s; border-radius: 3px; background: %(well)s; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: %(accent)s; border-color: %(accent)s; }
QRadioButton::indicator { border-radius: 7px; }

QProgressBar { background: %(well)s; border: 1px solid %(line)s; border-radius: %(r_btn)spx; text-align: center; color: %(txt)s; }
QProgressBar::chunk { background: %(accent)s; border-radius: %(r_input)spx; }
QSlider::groove:horizontal { height: 5px; background: %(green_mid)s; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; background: %(accent)s; }

QTreeWidget, QTreeView, QTableView, QListView { background: %(panel)s; border: none; alternate-background-color: %(card)s; }
QTreeWidget::item, QTreeView::item, QTableView::item, QListView::item { height: 26px; padding-left: 6px; }
QTreeWidget::item:selected, QTreeView::item:selected, QTableView::item:selected, QListView::item:selected { background: %(tint)s; color: %(accent)s; }
QHeaderView::section { background: %(panel)s; border: none; border-bottom: 1px solid %(line)s; padding: 6px 8px; color: %(dim)s; font-size: 10px; font-weight: 600; letter-spacing: 1px; }

QGroupBox { border: 1px solid %(line)s; border-radius: 10px; margin-top: 12px; padding: 14px 12px 8px; font-weight: 700; color: %(accent)s; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px; }
QMenu { background: %(card)s; border: 1px solid %(line)s; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 5px; }
QMenu::item:selected { background: %(tint)s; color: %(accent)s; }
QToolTip { background: %(card)s; color: %(txt)s; border: 1px solid %(line)s; padding: 4px 8px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: %(line)s; border-radius: 5px; min-height: 30px; min-width: 30px; }
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QMainWindow::separator { width: 4px; height: 4px; background: %(line)s; }
QMainWindow::separator:hover { background: %(accent)s; }
"""


def _group_variants() -> str:
    """One `QFrame#Group[hue="<name>"]` block per palette hue.

    `>`-scoped so a group frame does not recolour the cards nested in it —
    the bug DollySync hit when its category frames nested.
    """
    out = []
    for key, (vib, mid, tint) in PALETTE.items():
        out.append(
            f'QFrame#Group[hue="{key}"] {{ border-color: {mid}; }}\n'
            f'QFrame#Group[hue="{key}"] > QWidget#GroupHeader {{ background: {tint}; }}\n'
            f'QFrame#Group[hue="{key}"] > QWidget#GroupHeader > QLabel#GroupTitle {{ color: {vib}; }}\n'
        )
    return "".join(out)


def qss(mode_name: str = DEFAULT_MODE) -> str:
    """The complete stylesheet for a mode: `app.setStyleSheet(qss("neon"))`."""
    return QSS_TEMPLATE % qss_vars(mode_name) + _group_variants()


def qss_vars(mode_name: str = DEFAULT_MODE) -> dict:
    """Flat name -> value mapping for `QSS_TEMPLATE % qss_vars("neon")`.

    Merges the mode's chrome with every identity tone (``green``,
    ``green_mid``, ``green_tint``, …), the four semantic states
    (``ok``/``run``/``warn``/``bad`` plus their ``_mid``/``_tint``), the
    legacy token names (so an older template keeps rendering), and
    ``r_group``/``r_card``/``r_gh``/``r_btn``/``r_input``/``r_chip`` as bare
    pixel numbers for `border-radius: %(r_card)spx`.

    ``ok`` follows the mode's accent, so it brightens in Neon along with
    everything else the accent drives.
    """
    out = dict(mode(mode_name))
    for key, (vib, mid, tint) in PALETTE.items():
        out[key] = vib
        out[f"{key}_mid"] = mid
        out[f"{key}_tint"] = tint
    for key, (vib, mid, tint) in STATES.items():
        out[key] = vib
        out[f"{key}_mid"] = mid
        out[f"{key}_tint"] = tint
    out["ok"] = out["accent"]
    for old, new in LEGACY_TOKEN_ALIASES.items():
        out[old] = out[new]
    out["edge"] = PALETTE["green"][1]
    for key, px in RADIUS.items():
        out[f"r_{key}"] = px
    return out


def build_tag(app_name: str, version: str, build: int | str) -> str:
    """The identity tag every 518 app puts at the bottom-right of its status bar.

    Only ``Blise518B`` is accent-coloured and weight 600 — the rest is `dim`.
    Rendered as rich text, that is:
        f'{app_name} v{version} · made by <b>Blise518B</b>'
    """
    return f"{app_name} v{version} · made by Blise518B"


def title_tag(version: str, build: int | str) -> str:
    """The version tag that sits right of the headline: `v1.2.3 · b318`."""
    return f"v{version} · b{build}"
