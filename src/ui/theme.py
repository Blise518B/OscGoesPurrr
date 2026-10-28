"""OscGoesPurrr's look: the 518 design system, built from `ui/theme_tokens.py`.

Two modes, one green. `theme_tokens.py` is a verbatim copy of
`_hub\\design\\theme_tokens.py` and is the only place a colour is spelled
out; nothing in this module retypes a hex. The semantic roles OGP needs on
top of the shared tokens (what "live signal" is, which hue each chain type
and trace wears) are declared here once, as *names* of tokens.

Import-safe: no Qt at module level, because `constants.py` resolves the
mode and the `COLOR_*` aliases from here before any widget exists. Every
module copies those at import; `set_mode` and `set_accent_hue` change
them while the app runs (see retint.py and ui/live_theme.py).
`install_fonts()` is the one Qt touch and runs from the UI bootstrap.
"""
from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

import theme_tokens as T          # the verbatim hub copy, at the project root
import accent_shift as _accent
import retint as _retint
import constants as _constants
# Resolved once, Qt-free, in constants.py: the mode, and how far the user
# turned the green (0.0 = the house green, tokens untouched).
from constants import UI_MODE, UI_ACCENT_DELTA, UI_ACCENT_HUE, UI_IDENTITY_HUES
from constants import PALETTE as _PALETTE
from constants import GREEN_ROLES as _GREEN_ROLES

# Names retint.modules() must leave alone: these are SOURCES a turned
# colour is computed from, not copies of the current colour.
__retint_skip__ = frozenset({"_GREEN_BAR", "_OTHER_BARS"})

# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

SETTING_KEY = "ui_mode"
DEFAULT_MODE = T.DEFAULT_MODE
MODE_ORDER = list(T.MODE_ORDER)
# What the user reads: "Vibrant" / "Darker" (the tokens' own names for the
# two, Neon / Midnight, stay the internal ones).
MODE_LABELS = dict(_constants.UI_MODE_LABELS)


def normalize_mode(raw) -> str:
    """Resolve a stored mode name, tolerating the legacy `broker` alias and
    anything unknown (-> the default)."""
    key = T.LEGACY_MODE_ALIASES.get(str(raw), str(raw))
    return key if key in T.MODES else DEFAULT_MODE


# The mode in use right now; set_mode() changes it while the app runs.
MODE = UI_MODE

# Neon's filled header bars, one per hue: (bar fill, frame border). Not in
# the shared token file yet -- these are VRCDollySync's / FFMPEG Studio's
# `_NEON_CAT_BARS`, copied from the reference apps rather than derived;
# Midnight uses the hue's tint as the fill and its mid tone as the frame.
# The green pair turns with the accent; the others never do.
_GREEN_BAR = ("#1c8a3d", "#36a35c")
_BAR_ROLES = ("bar.0", "bar.1")
_OTHER_BARS = {
    "blue":   ("#1e5fa0", "#3b6ea3"),
    "cyan":   ("#15808f", "#2e93a3"),
    "yellow": ("#a06a14", "#b3813a"),
    "red":    ("#9c2531", "#b04552"),
    "purple": ("#7a3fa8", "#9159ba"),
}

# How far the green is turned RIGHT NOW, in degrees. Starts at what the
# user had saved; set_accent_hue() moves it while the app runs.
_delta: float = UI_ACCENT_DELTA
# The identity colours the user set by hand, ((name, hue), ...);
# set_identity_hues() changes them while the app runs.
_chosen: tuple = UI_IDENTITY_HUES


def _table(delta: float, mode_name: str = "", chosen=None) -> Dict[str, str]:
    """`{role: its colour at this turn}` for every colour that can change:
    constants' table (the chrome, by token name; the palette's green; each
    identity colour, "pink.0".."pink.2" -- its own tones, or turned where
    it had to move or was set by hand) plus the section bars (the green's
    `bar.0` / `bar.1`, and "bar.blue.0" ... for the other hues). Every role
    has a value of its own and none lands on a colour that must not
    change -- in either mode -- which is the guarantee that lets the
    running app be recoloured by value (see retint.py), whether the hue,
    the mode or an identity colour changed. Read-only: the result is
    shared (cached)."""
    return _table_cached(float(delta), normalize_mode(mode_name or MODE),
                         _chosen if chosen is None else tuple(chosen))


@lru_cache(maxsize=1024)
def _table_cached(delta: float, mode_name: str, chosen: tuple) -> Dict[str, str]:
    base = _constants.accent_table(delta, mode_name, chosen)
    fixed = [tone for name, tri in T.PALETTE.items() if name != "green"
             for tone in tri]
    fixed += [tone for pair in _OTHER_BARS.values() for tone in pair]
    # Like the palette's green, the bar is the same in every mode: it
    # steps clear of what ANY mode's chrome uses (Neon's `line` is the
    # bar's frame tone).
    for other in T.MODES:
        fixed += list(_constants.accent_table(delta, other, chosen).values())
    bar = _accent.unique_table(dict(zip(_BAR_ROLES, _GREEN_BAR)), delta, fixed)
    # The other hues' bars follow their colour when it moved.
    moves = _constants.identity_moves(delta, chosen)
    taken = fixed + list(bar.values())
    bars = {}
    for name, pair in _OTHER_BARS.items():
        roles = {f"bar.{name}.{i}": tone for i, tone in enumerate(pair)}
        if name in moves:
            roles = _accent.unique_table(
                roles, _constants.identity_delta(name, moves[name]), taken)
            taken += list(roles.values())
        bars.update(roles)
    return {**base, **bar, **bars}


def current_table() -> Dict[str, str]:
    """The table for the colours in use now."""
    return _table(_delta)


def chrome(mode_name: str = "", delta=None) -> Dict[str, str]:
    """A mode's chrome tokens with the green turned by `delta` degrees --
    by default the turn in use, which is none unless the user chose one."""
    mode_name = mode_name or MODE
    table = _table(_delta if delta is None else delta, mode_name)
    return {k: table[k] for k in T.mode(mode_name)}


CHROME: Dict[str, str] = chrome()
# The identity palette, with its green following the chosen hue too.
PALETTE: Dict[str, Tuple[str, str, str]] = _PALETTE
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
# A toy that is remembered but not connected wears no identity hue: its
# frame is a solid outline in the chrome's `dim` -- the disabled tone --
# and its bar is unfilled. Not red (switched off is not an error) and not the
# identity grey (that one is the custom chain's).
OFFLINE_HUE = "offline"


def toy_hue(index: int) -> str:
    """The hue for the toy at display position `index` (0-based)."""
    return TOY_HUES[int(index) % len(TOY_HUES)]


# The Friends page: each friend wears one of the toys' three cool hues (its
# avatar, its row when picked, the control panel's frame and bar), and the
# two kinds of control wear the hue of what they drive -- everything about
# toys the live pink, everything about shocks yellow -- so the toys / shocks
# boxes in the list match the panel's sections. Strength keeps the accent.
FRIEND_HUES = TOY_HUES
FRIEND_TOYS_HUE = "pink"
FRIEND_SHOCK_HUE = "yellow"
# Friends itself, wherever it is named (its icon, ui/icons.identity_icon):
# cyan, like the friends icons of the VRChat menu (tools/make_menu_icons.py).
FRIENDS_HUE = "cyan"

# Home's rows under the toys, for what isn't an Intiface toy, wear the hue of
# what they are (Appearance -> Other colours): the shocker hub yellow, the
# haptic suits orange.
SHOCKERS_HUE = FRIEND_SHOCK_HUE
SUITS_HUE = "orange"
DEVICE_ROW_HUES = (SHOCKERS_HUE, SUITS_HUE)
# The Suits page tells its two suits apart (2026-10-28): bHaptics wears the
# suits' orange, OWO purple -- the one identity hue nothing on that page
# means already (it is the third toy's, and no toy is there).
BHAPTICS_HUE = SUITS_HUE
OWO_HUE = "purple"
# ... and Vive trackers blue (the second toy's; no toy there either).
TRACKERS_HUE = "blue"


def friend_hue(index: int) -> str:
    """The hue for the friend at list position `index` (0-based)."""
    return FRIEND_HUES[int(index) % len(FRIEND_HUES)]


def toy_frame_colors(hue_name: str, mode_name: str = ""):
    """`(outline, ground)` for a toy's frame; ground is None for no fill.

    A connected toy: its identity hue as the outline -- Neon in the
    reference apps' brighter frame tone, Midnight in the hue's mid -- on
    the panel ground. An offline one: a quiet solid outline on no ground,
    in the chrome's `dim` (Neon) or grey's mid (Midnight, where `dim` would
    outshine the mid-tone frames of the toys that ARE connected). Read at
    paint time, so it follows the colour picker and a mode switch."""
    mode_name = mode_name or MODE
    neon = normalize_mode(mode_name) == "neon"
    ground = CHROME["panel"] if mode_name == MODE else chrome(mode_name)["panel"]
    if hue_name in TOY_HUES or hue_name in DEVICE_ROW_HUES:
        bars = NEON_CAT_BARS.get(hue_name)
        return (bars[1] if neon and bars else PALETTE[hue_name][1], ground)
    if hue_name == OFFLINE_HUE:
        dim = CHROME["dim"] if mode_name == MODE else chrome(mode_name)["dim"]
        return (dim if neon else PALETTE["grey"][1]), None
    line = CHROME["line"] if mode_name == MODE else chrome(mode_name)["line"]
    return line, ground

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

# The section bars in use: the green pair at the current turn, the rest
# as the reference apps have them (see _GREEN_BAR / _OTHER_BARS above).
NEON_CAT_BARS = dict(
    {name: tuple(current_table()[f"bar.{name}.{i}"] for i in (0, 1)) for name in _OTHER_BARS},
    green=tuple(current_table()[r] for r in _BAR_ROLES))
NEON_CAT_BAR = NEON_CAT_BARS["green"][0]


# ---------------------------------------------------------------------------
# The colour picker (Settings -> Appearance)
# ---------------------------------------------------------------------------

#: Where the house green sits on the hue slider.
DEFAULT_ACCENT_HUE = _accent.hue_of(T.NEON["accent"])
#: The hue in use right now, or None for the house green.
ACCENT_HUE = UI_ACCENT_HUE
#: One-click choices: the green, then the identity palette's own hues (red
#: and amber are left to the slider -- they are what errors and warnings
#: wear). Picking one moves that identity colour out of the way.
ACCENT_PRESETS = (("Green (default)", None),) + tuple(
    (name.capitalize(), _accent.hue_of(T.PALETTE[name][0]))
    for name in ("cyan", "blue", "purple", "pink", "orange", "yellow"))


def accent_preview(hue_deg, mode_name: str = "") -> Dict[str, str]:
    """What the chrome would be with the green turned to `hue_deg` (None =
    the house green): the mode's tokens plus the section-bar fill, for
    the picker's swatches. Nothing is applied."""
    mode_name = mode_name or MODE
    delta = _accent.delta_for(hue_deg, T.NEON["accent"])
    v = chrome(mode_name, delta)
    if normalize_mode(mode_name) == "neon":
        v["catbar"] = _table(delta, mode_name)[_BAR_ROLES[0]]
        v["catbar_text"] = v["txt"]
    else:
        v["catbar"] = v["tint"]
        v["catbar_text"] = v["accent"]
    return v


def set_accent_hue(hue_deg) -> Dict[str, str]:
    """Turn the app's green to `hue_deg` (None = the house green) while it
    runs -- and every identity colour that has to move with it -- and
    return `{old hex: new hex}` for every colour that changed.

    Everything that is module state follows at once: this module's and
    `constants`' tokens, every `COLOR_*` copy in every colour module,
    class-level colours, default arguments (retint.modules). What is
    already ON SCREEN -- the stylesheet each widget was polished with and
    the colours widgets copied into themselves -- is the caller's to
    update with the returned mapping; ui/live_theme.py does it in slices."""
    global ACCENT_HUE
    mapping = _retable(_accent.delta_for(hue_deg, T.NEON["accent"]), _chosen)
    ACCENT_HUE = hue_deg
    _constants.UI_ACCENT_HUE = hue_deg
    return mapping


def set_identity_hues(chosen) -> Dict[str, str]:
    """Set the identity colours the user picked by hand -- `{name: hue}`;
    a name left out is automatic again -- while the app runs, and return
    `{old hex: new hex}` like set_accent_hue (the same follow-up)."""
    return _retable(_delta, _constants.clean_identity_hues(chosen))


def _retable(new_delta: float, new_chosen: tuple) -> Dict[str, str]:
    global _delta, _chosen
    old, new = _table(_delta), _table(new_delta, chosen=new_chosen)
    mapping = {old[role]: new[role] for role in old if old[role] != new[role]}
    _delta, _chosen = new_delta, tuple(new_chosen)
    _constants.UI_ACCENT_DELTA = new_delta
    _constants.UI_IDENTITY_HUES = _chosen
    _retint.modules(mapping)
    return mapping


#: The identity colours Appearance -> Other colours offers, and what each
#: one marks in the app.
IDENTITY_ROLES = (
    ("pink", "Pink", "the live signal, penetration, friends' toys"),
    ("red", "Red", "errors and Stop"),
    ("amber", "Amber", "touch contact and warnings"),
    ("yellow", "Yellow", "shockers"),
    ("cyan", "Cyan", "your first toy, friends, things running"),
    ("blue", "Blue", "your second toy"),
    ("purple", "Purple", "your third toy"),
    ("orange", "Orange", "the haptic suits"),
)


def identity_chosen() -> Dict[str, float]:
    """The identity colours set by hand now, {name: hue}."""
    return dict(_chosen)


def identity_state() -> Dict[str, Dict[str, object]]:
    """For Other colours: each identity colour's hue now, its own hue,
    whether the user set it by hand, and whether it moved for the accent."""
    chosen = dict(_chosen)
    moves = _constants.identity_moves(_delta, _chosen)
    out = {}
    for name in _constants.IDENTITY_HUES:
        own = _accent.hue_of(T.PALETTE[name][0])
        out[name] = {"hue": moves.get(name, own), "own": own,
                     "chosen": name in chosen,
                     "moved": name in moves and name not in chosen}
    return out


def identity_preview(name: str, hue_deg: float) -> str:
    """Identity colour `name` turned to `hue_deg` (its vibrant tone), for
    the Other colours sliders. Nothing is applied."""
    return _accent.shift_hex(T.PALETTE[name][0], _constants.identity_delta(name, hue_deg))


def set_mode(mode_name) -> Dict[str, str]:
    """Switch the app to the other mode while it runs, and return `{old
    hex: new hex}` for every colour that changed -- the same contract as
    set_accent_hue, and the same follow-up: what is already on screen is
    the caller's (ui/live_theme.py).

    Only the chrome differs between the modes; the palette's green and
    the section bar are the same in both. What a mode decides beyond its
    tokens -- the filled section bar or the tinted one, the frame tone of
    a toy -- is looked up by name when a stylesheet is built or a frame
    painted, never copied, so it follows MODE."""
    global MODE
    new_mode = normalize_mode(mode_name)
    old, new = _table(_delta, MODE), _table(_delta, new_mode)  # same identity colours
    mapping = {old[role]: new[role] for role in old if old[role] != new[role]}
    MODE = new_mode
    _constants.UI_MODE = new_mode
    _retint.modules(mapping)
    return mapping


def same_accent(a, b) -> bool:
    """Whether two picker choices are the same colour (None = the green)."""
    if a is None or b is None:
        return a is None and b is None
    return abs((float(a) - float(b) + 180.0) % 360.0 - 180.0) < 0.5


def hue(name: str) -> str:
    """Vibrant tone of an identity hue by name."""
    return PALETTE[name][0]


def tri(name: str) -> Tuple[str, str, str]:
    return PALETTE[name]


def qss_vars(mode_name: str = "") -> Dict[str, str]:
    """Flat name -> value mapping for the stylesheet template: the mode's
    chrome (by default the mode in use), every identity tone (`pink`,
    `pink_mid`, `pink_tint`, ...), the semantic roles above, radii, and
    the section-bar fill."""
    mode_name = normalize_mode(mode_name or MODE)
    v: Dict[str, str] = chrome(mode_name)
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
        v["home_edge"] = v["line"]
    else:
        v["catbar"] = v["tint"]
        v["catbar_text"] = v["accent"]
        # Midnight's `line` is a near-invisible hairline, which would
        # un-frame the Home entry: step it to the tone that keeps the
        # rank `line` has in Neon.
        v["home_edge"] = v["green_mid"]
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
/* A card "Take me there" just led to: lit for a moment (whats_new.py). */
QFrame#card[spot="true"] { background-color: %(hover)s; border-color: %(accent)s; }
QFrame#cardDark {
    background-color: %(panel)s;
    border: 1px solid %(line)s; border-radius: %(r_card)spx;
}
QFrame#chip {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: 10px;
}
/* Statistics: a clickable session row, and the number tiles. */
QFrame#statsSessionRow {
    background-color: transparent;
    border: 1px solid transparent; border-radius: %(r_btn)spx;
}
QFrame#statsSessionRow:hover {
    background-color: %(hover)s; border-color: %(line)s;
}
QFrame#statsTile {
    background-color: %(panel)s;
    border: 1px solid %(green_mid)s; border-radius: %(r_btn)spx;
}
QFrame#statsTile QLabel { background: transparent; }
/* A toy is ONE thin-outlined frame: panel ground, its identity hue as the
   border and as the colour of its name, nothing filled. The frame paints
   itself (ui.widgets.ToyFrame, colours from toy_frame_colors below) --
   it CONTAINS the toy's sections, and a container that sections sit in
   must not take its look from a stylesheet (see ui/live_theme.py). Its
   bar and the chain blocks inside are styled here; a chain block is a
   card-level frame in the chain's own hue -- no chrome-green outline. */
QWidget#toyBar { background-color: transparent; border-radius: %(r_gh)spx; }
QWidget#toyBar:hover { background-color: %(hover)s; }
QWidget#toyBar QLabel { background: transparent; }
QWidget#toyBar QPushButton { padding: 3px 12px; }
QWidget#toyBar QLabel#toyZones { color: %(muted)s; font-size: 11px; }
QFrame#listDividerLine { background-color: %(line)s; border: none; }
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
QFrame#chainFoldBar, QFrame#toolsFoldBar {
    background-color: %(card)s;
    border: 1px solid %(line)s; border-radius: 10px;
}
QFrame#chainFoldBar:hover, QFrame#toolsFoldBar:hover { background-color: %(hover)s; border-color: %(accent)s; }
QFrame#toolsFoldBar:focus { border-color: %(accent)s; }
QPushButton#stageCycleButton { padding: 1px 6px; border-radius: 5px; }
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
/* Home's one heading: the page title and the list's title in one line. */
QLabel#homeTitle {
    font-family: "Aldrich", "Segoe UI";
    font-size: 17px; font-weight: 600; letter-spacing: 1px;
    color: %(accent)s;
}
QLabel#sidebarLinkTitle { font-size: 12px; font-weight: 600; color: %(txt)s; }
QLabel#setupStepTitle, QLabel#newsTitle, QCheckBox#interestChoice {
    font-size: 13px; font-weight: 600;
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
QLabel[role="pill"][tone="idle"] { background-color: transparent;  color: %(dim)s;  border-color: %(dim)s; }

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
/* ...which outranks the plain :disabled rule above, so say it again. */
QPushButton[role="secondary"]:disabled, QPushButton[role="profileIdle"]:disabled { color: %(dim)s; }
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
/* Home is where the app opens and where everything else leads back to:
   the one nav entry that is framed and larger. */
QPushButton[role="navHome"] {
    background-color: transparent; border: 1px solid %(home_edge)s;
    color: %(txt)s; text-align: left;
    padding: 8px 12px; border-radius: %(r_btn)spx;
    font-size: 15px; font-weight: 600;
}
QPushButton[role="navHome"]:hover { background-color: %(hover)s; border-color: %(accent)s; color: %(accent)s; }
QPushButton[role="navHome"][active="true"] {
    background-color: %(tint)s; border-color: %(accent)s; color: %(accent)s;
}
/* The sidebar's connect / refresh buttons: there when needed, quiet
   otherwise. */
QPushButton[role="sideSmall"] {
    padding: 2px 6px; font-size: 12px; color: %(muted)s;
    border-color: %(green_mid)s;
}
QPushButton[role="sideSmall"]:hover { color: %(accent)s; border-color: %(accent)s; }
QPushButton[role="sideSmall"]:disabled { color: %(dim)s; }
/* the sidebar's group captions, and the toy list's small dividers on Home */
QLabel#navGroup, QLabel#listDivider {
    color: %(dim)s; font-size: 10px; font-weight: 700; letter-spacing: 1px;
}
QLabel#navGroup { padding: 0px 10px 2px 10px; }
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
/* ticked: the frame in the hue with a smaller square inside, not one solid
   fill -- the gap keeps it reading as a box that is ticked (Blise's pick,
   2026-10-27). Same outer size as the empty box: 10 + 2 x 3 padding. */
QCheckBox::indicator:checked {
    background-color: %(accent)s; border-color: %(accent)s;
    width: 10px; height: 10px; padding: 3px; background-clip: content;
}
QCheckBox::indicator:hover { border-color: %(accent)s; }
QCheckBox[role="switch"]::indicator { width: 32px; height: 16px; border-radius: 8px; }
QCheckBox[role="switch"]::indicator:checked { padding: 0px; background-clip: border; }

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
    width: 26px; height: 26px; margin: -8px -3px; border-radius: 13px;
    border: 3px solid %(panel)s;   /* the ring hangs past the ends: the green reaches them */
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
QSplitter#paramsSplit::handle { background: transparent; border: none;
    border-left: 2px solid %(line)s; margin: 40px 3px; }
QSplitter#paramsSplit::handle:hover { border-left-color: %(accent)s; }
"""


def _hue_variants(mode_name: str, v: Dict[str, str]) -> str:
    """Per-hue rules: a toy's bar for every toy hue, a chain frame + fold
    bar for every chain-type hue, and the Friends page's (theme_friends).
    (The toy's FRAME is painted, not styled: toy_frame_colors.)"""
    out = []
    for hue in TOY_HUES + DEVICE_ROW_HUES:
        vib, _mid, _tint = PALETTE[hue]
        # The name wears the hue's vibrant in both modes.
        out.append(
            f'QWidget#toyBar[hue="{hue}"] QLabel#deviceName {{ color: {vib}; }}\n'
        )
    # Offline: quiet text on a bar with the colour taken out.
    off = OFFLINE_HUE
    out.append(
        f'QWidget#toyBar[hue="{off}"] QLabel {{ color: {v["dim"]}; }}\n'
        f'QWidget#toyBar[hue="{off}"] QLabel#deviceName {{ color: {v["muted"]}; }}\n'
    )
    for hue in sorted(set(CHAIN_TYPE_HUES.values())):
        vib, mid, tint = PALETTE[hue]
        out.append(
            f'QFrame#chainFoldBar[hue="{hue}"] {{ border-color: {mid}; }}\n'
            f'QFrame#chainFoldBar[hue="{hue}"]:hover {{ border-color: {vib}; }}\n'
            f'QFrame#motorBlock[hue="{hue}"] {{ border-color: {mid}; }}\n'
        )
    from ui.theme_friends import friends_qss      # imports this module
    out.append(friends_qss(mode_name, v))
    from ui.theme_params import params_qss        # imports this module
    out.append(params_qss(mode_name, v))
    from ui.theme_suits import suits_qss          # imports this module
    out.append(suits_qss(mode_name, v))
    # OGP open twice: a banner nobody can miss
    out.append(
        f'QLabel#secondWindowBanner {{ background-color: {v["err_tint"]}; color: {v["err"]};'
        f' border: 2px solid {v["err"]}; border-radius: {v["r_btn"]}px; padding: 10px;'
        ' font-size: 15px; font-weight: 700; }\n')
    return "".join(out)


def build_qss(mode_name: str = "") -> str:
    """The whole application stylesheet for a mode (by default the one in
    use), from the tokens."""
    mode_name = normalize_mode(mode_name or MODE)
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
