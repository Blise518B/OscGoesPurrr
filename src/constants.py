# constants.py

import json as _json
from pathlib import Path as _Path

# --- Theme & Colors ---
# OscGoesPurrr wears the 518 design system: two modes (Neon, the default,
# and Midnight), one green, ten identity hues. The values live in
# `theme_tokens.py` -- a verbatim copy of `_hub\design\theme_tokens.py` --
# and NOTHING in this project retypes a hex; everything below is a name
# for a token. The stylesheet itself is built in `ui/theme.py`.
#
# The one thing a user can change is the hue of "the green": Settings ->
# Appearance turns every green token by one angle (see accent_shift.py).
# The tokens stay the source; a turned colour is computed from one,
# never typed.
#
# The mode and that hue are read straight from app_settings.json here
# (constants must stay import-safe: no Qt, nothing that imports the app),
# and every module copies these values at import. Both can change while
# the app runs: theme.set_mode / theme.set_accent_hue rebind every copy
# (retint.py) and ui/live_theme.py sweeps the change across what is on
# screen.
from functools import lru_cache as _lru_cache

import theme_tokens as _tokens


def _load_ui_mode() -> str:
    """Persisted `ui_mode`, tolerating the legacy `broker` alias; anything
    missing or unknown falls back to the default (Neon). `OGP_UI_MODE` in
    the environment wins over the file -- for screenshots and tests, so a
    render of the other mode never has to rewrite the user's settings."""
    import os as _os
    forced = _os.environ.get("OGP_UI_MODE")
    if forced:
        key = _tokens.LEGACY_MODE_ALIASES.get(forced, forced)
        if key in _tokens.MODES:
            return key
    try:
        p = (_Path.home() / "AppData" / "Roaming" / "OscGoesPurrr"
             / "app_settings.json")
        with open(p, "r", encoding="utf-8") as f:
            raw = _json.load(f).get("ui_mode", _tokens.DEFAULT_MODE)
    except Exception:
        return _tokens.DEFAULT_MODE
    key = _tokens.LEGACY_MODE_ALIASES.get(str(raw), str(raw))
    return key if key in _tokens.MODES else _tokens.DEFAULT_MODE


def _load_ui_accent_hue():
    """Persisted `ui_accent_hue`: the hue (OKLCH degrees, 0-360) the user
    turned the app's green to in Settings -> Appearance, or None for the
    house green. Read the same way and for the same reason as the mode
    above; `OGP_UI_ACCENT` in the environment wins over the file (a number,
    or `default`) so tests and screenshots never depend on -- or rewrite --
    the user's settings."""
    import os as _os
    forced = _os.environ.get("OGP_UI_ACCENT")
    if forced is None:
        try:
            p = (_Path.home() / "AppData" / "Roaming" / "OscGoesPurrr"
                 / "app_settings.json")
            with open(p, "r", encoding="utf-8") as f:
                forced = _json.load(f).get("ui_accent_hue")
        except Exception:
            return None
    try:
        return float(forced) % 360.0
    except (TypeError, ValueError):
        return None          # absent, null, "default" or junk: the green


UI_MODE = _load_ui_mode()
# What the two modes are called in THIS app. The design system's names
# (and the stored setting, and OGP_UI_MODE) stay `neon` / `midnight`.
UI_MODE_LABELS = {"neon": "Vibrant", "midnight": "Darker"}
UI_MODE_ORDER = list(_tokens.MODE_ORDER)
# The colour picker: every green token is turned by one angle, measured
# from the Neon accent so both modes turn alike. 0.0 leaves the tokens
# untouched, character for character. (accent_shift is pure maths -- as
# import-safe as the token file.)
import accent_shift as _accent


# The palette's green, as roles of the table below.
GREEN_ROLES = ("green.0", "green.1", "green.2")


def accent_table(delta: float, mode_name: str = "") -> dict:
    """`{role: its colour with the green turned by delta degrees}` for
    every green token of a mode: its chrome (the roles are the token
    names -- `bg`, `line`, `accent`, ...) and the palette's green
    (GREEN_ROLES). The one place that decides what "a green token" is;
    `ui/theme.py` extends it with the section-bar fill.

    Every role has a colour of its own, in every mode: no two roles share
    one and none lands on an identity hue (accent_shift.unique_table) --
    which is what lets the running app be recoloured by value, across a
    change of hue AND of mode. The chrome is the tokens, character for
    character, at no turn; the palette's green is the same in every mode
    and steps one blue level aside where a mode's chrome uses the same
    colour (Midnight's accent IS the palette's green)."""
    key = mode_name or UI_MODE
    key = _tokens.LEGACY_MODE_ALIASES.get(key, key)
    if key not in _tokens.MODES:
        key = _tokens.DEFAULT_MODE
    return dict(_accent_table(float(delta), key))


@_lru_cache(maxsize=1024)
def _accent_table(delta: float, mode_name: str) -> dict:
    protected = [tone for name, tri in _tokens.PALETTE.items()
                 if name != "green" for tone in tri]
    chromes = {name: _accent.unique_table(dict(tokens), delta, protected)
               for name, tokens in _tokens.MODES.items()}
    taken = protected + [c for chrome in chromes.values()
                         for c in chrome.values()]
    green = _accent.unique_table(
        dict(zip(GREEN_ROLES, _tokens.PALETTE["green"])), delta, taken)
    return {**chromes[mode_name], **green}


UI_ACCENT_HUE = _load_ui_accent_hue()
UI_ACCENT_DELTA = _accent.delta_for(UI_ACCENT_HUE, _tokens.NEON["accent"])
_startup_table = accent_table(UI_ACCENT_DELTA)
CHROME = {k: _startup_table[k] for k in _tokens.mode(UI_MODE)}
PALETTE = dict(_tokens.PALETTE)
PALETTE["green"] = tuple(_startup_table[r] for r in GREEN_ROLES)
del _startup_table

# The four surfaces + the frame, by their token names.
COLOR_BG = CHROME["bg"]            # the window
COLOR_PANEL = CHROME["panel"]      # bars and frames: sidebar, status bar, group frames, tables
COLOR_CARD = CHROME["card"]        # things you look at -- THE grey
COLOR_WELL = CHROME["well"]        # things you type into / read logs from
COLOR_HOVER = CHROME["hover"]
COLOR_LINE = CHROME["line"]        # every 1px border
COLOR_TINT = CHROME["tint"]        # fill behind accent text (active nav, selected tab)
COLOR_ACCENT = CHROME["accent"]    # THE green
COLOR_ACCENT2 = CHROME["accent2"]  # hover on a filled accent only
COLOR_INK = CHROME["ink"]          # text ON a filled accent -- never white
COLOR_TXT = CHROME["txt"]
COLOR_MUTED = CHROME["muted"]
COLOR_DIM = CHROME["dim"]

# Semantic roles OGP needs on top of the shared tokens, as tri-tones
# (vibrant, mid border, dark tint fill):
#   live  the haptic signal itself -- meters, charged chain borders,
#         connector arrows, the value ramp. PINK: it is what the data is
#         about (the R18 hue), and it keeps "live = pink" legible.
#   run   a job in flight: simulator, session recording, replay.
#   warn  waiting / stale / disconnected / paused -- not errors.
#   err   actual failures and destructive buttons, nothing else.
COLOR_LIVE_TONES = PALETTE["pink"]
COLOR_RUN_TONES = PALETTE["cyan"]
COLOR_WARN_TONES = PALETTE["amber"]
COLOR_ERR_TONES = PALETTE["red"]
COLOR_OK_TONES = (COLOR_ACCENT, PALETTE["green"][1], PALETTE["green"][2])

# --- The names the rest of the app was written against -----------------
# Kept as aliases so every call site keeps working; each is a token.
COLOR_PRIMARY = COLOR_ACCENT
COLOR_PRIMARY_HOVER = COLOR_ACCENT2
COLOR_ALERT = COLOR_ERR_TONES[0]
COLOR_ALERT_HOVER = COLOR_ERR_TONES[0]
COLOR_ALERT_DIM = COLOR_ERR_TONES[2]
COLOR_SUCCESS = COLOR_ACCENT
COLOR_SUCCESS_DIM = COLOR_OK_TONES[2]
COLOR_LIVE = COLOR_LIVE_TONES[0]
COLOR_LIVE_DIM = COLOR_LIVE_TONES[2]
COLOR_WARNING = COLOR_WARN_TONES[0]
COLOR_WARNING_DIM = COLOR_WARN_TONES[2]
COLOR_SURFACE = COLOR_CARD
COLOR_SURFACE_HOVER = COLOR_HOVER
COLOR_BUTTON = COLOR_CARD
COLOR_BUTTON_HOVER = COLOR_HOVER
COLOR_INPUT_BG = COLOR_WELL
COLOR_INPUT_BORDER = COLOR_LINE
COLOR_INPUT_FOCUS = COLOR_ACCENT
COLOR_TEXT = COLOR_TXT
COLOR_TEXT_ON_PRIMARY = COLOR_INK
COLOR_TEXT_MUTED = COLOR_MUTED
# Chain borders / connectors / the value ramp charge from the frame colour
# (idle = just another outlined card) to the live pink.
COLOR_CHAIN_IDLE = COLOR_LINE
COLOR_CHAIN_LIVE = COLOR_LIVE
COLOR_VALUE_LO = COLOR_LINE
COLOR_VALUE_HI = COLOR_LIVE
# Flat brushes: the gradient profiles are gone, so these are the colours.
COLOR_BG_BRUSH = COLOR_BG
COLOR_SURFACE_BRUSH = COLOR_CARD
COLOR_PRIMARY_BRUSH = COLOR_ACCENT
# Native window frame is left to the system in both modes.
COLOR_WINDOW_BORDER = None
COLOR_WINDOW_CAPTION = None
COLOR_WINDOW_CAPTION_TEXT = None

# --- Input simulator ---
# The page-level simulator publishes its wave under these two parameter
# addresses. A chain listens to them like any custom OSC parameter, but
# through its type filter: the Pen address only reaches chains that accept
# penetration, the Touch address only chains that accept touch -- so
# "simulate a penetration" versus "simulate a touch" is the chain's own
# choice. Import-safe on purpose: the router and the UI both need them and
# neither may import the other at startup.
SIM_PEN_ADDRESS = "OGP/Sim/Pen"
SIM_TOUCH_ADDRESS = "OGP/Sim/Touch"
SIM_ADDRESSES = (SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS)

# --- UI Dimensions ---
WINDOW_GEOMETRY = "1100x700"
# Sidebar: the two-column block of mode buttons and the link rows (name +
# status pill) need ~210px, and when the nav overflows vertically the 10px
# scrollbar eats into that -- 240 keeps the content clear of both.
SIDEBAR_WIDTH = 240
BTN_HEIGHT_LARGE = 35
BTN_HEIGHT_SMALL = 30

# --- Timing & System (ms/seconds) ---
# Haptic engine loop period. 10 ms (100 Hz) keeps the time between a target
# changing and the command going out small. The loop only emits on change and
# dispatches fire-and-forget, so a faster tick costs almost nothing. The loop
# rate sets end-to-end *latency*; the per-feature command rate to real hardware
# is capped separately by HAPTIC_MAX_SEND_HZ below, so a fast loop is safe.
HAPTIC_POLL_RATE = 0.01
# Per-feature send-rate cap (Hz). The engine loop runs fast for low latency, but
# actual commands to any single motor are throttled to this rate so a real
# Bluetooth toy is never flooded on a continuously-changing signal. The cap only
# delays *consecutive* rapid changes (by up to one interval); the first change
# after a quiet gap is sent immediately, so step/edge latency is unaffected.
# ~60 Hz sits above OGB's 15 Hz and around OGP's old 50 Hz loop; lower it if a
# physical toy ever backlogs.
HAPTIC_MAX_SEND_HZ = 60

# --- Linear actuator (stroker) send shaping ---
# Linear features get their own, lower send cap. Since Buttplug Spec v4 the
# server enforces a per-device message gap and COALESCES anything faster
# (latest-wins): a cloud stroker is flushed once per 50 ms (20 Hz, per the
# buttplug device config), other BLE strokers default to 75 ms. Pushing 60 Hz
# at the server is pure waste — worse, the coalescing broke the duration math
# below (durations sized for a ~17 ms send gap, but arriving 50 ms apart =
# stepping). 20 Hz matches the tightest real flush rate; the stroke physics
# still ticks every loop, and the first send after a quiet gap is never
# delayed, so edge latency is unaffected.
LINEAR_MAX_SEND_HZ = 20
# A linear toy interpolates "move to position X over `duration` ms", then HOLDS at
# X until the next command. If `duration` is shorter than the real gap until that
# next command, the sleeve reaches X and freezes between every command — perceived
# as "stepping", worst at slow speeds. So we command a duration that OVERSHOOTS the
# send gap: duration = clamp(time-since-last-send) * LINEAR_DURATION_OVERLAP. With
# overlap > 1 the device is still travelling toward the latest position when the
# next command lands, so slow motion stays continuous. This trades a little
# positional lag (~one send interval) for smoothness; it does NOT add command
# dispatch latency — we still tick the physics and dispatch every loop. Lower it for
# snappier/steppier, raise it for smoother/laggier. See haptic_actuators.
# compute_send_duration_ms and the linear branch of HapticEngine.async_worker.
LINEAR_DURATION_OVERLAP = 2.0
# Ceiling (ms) on the gap estimate so the first command after an idle gap can't be
# commanded over a sluggish duration; the floor is the per-feature send interval.
# Sized to the 20 Hz linear cadence: a jittered/stalled gap is still covered
# (clamped gap * overlap = up to 200 ms) without post-idle moves turning syrupy.
LINEAR_MAX_SEND_INTERVAL_MS = 100.0
# Don't re-transmit a position the actuator hasn't moved past (float-jitter floor);
# lets a held/resting stroke go quiet instead of re-commanding the same spot.
LINEAR_MIN_POSITION_DELTA = 1e-4

ROUTER_POLL_RATE_MS = 16
QUEUE_POLL_RATE_MS = 50
UI_REFRESH_RATE_MS = 250
OSC_BOOT_DELAY_MS = 500
AUTO_REFRESH_RATE_S = 30.0
# --- Looking for toys ---
# One scan is TOY_SCAN_SECONDS of Bluetooth listening. With a toy connected
# the app rescans every AUTO_REFRESH_RATE_S and no faster: scanning shares
# the radio with the toy's own link, and that link's latency comes first.
# With NO toy connected there is nothing to protect, so the app searches
# hard -- a scan starts every TOY_SEARCH_RATE_S -- but only for
# TOY_SEARCH_WINDOW_S after the last reason to expect a toy (the toy server
# came up, a toy dropped, the user opened the window). Unbounded, it would
# keep the radio 40% busy and add ~3.5 MB a day to the toy server's log for
# every session spent with the toys switched off.
TOY_SCAN_SECONDS = 2.0
TOY_SEARCH_RATE_S = 5.0
TOY_SEARCH_WINDOW_S = 180.0

# --- OGP avatar parameters (VRChat expression-menu control) ---
# Stored/compared in the bare parameter_store form (the OSC prefix is
# stripped on ingest and re-added on send).
OGP_MODE_PARAMETER = "OGP/Mode"    # Int 0-3: switches the active routing mode
OGP_TEST_PARAMETER = "OGP/Test"    # Bool: hold to run the connectivity pulse
# Global output multiplier, 0.0-1.0. A radial-menu puppet drives this
# directly; it is the one knob that decides how strong everything runs.
OGP_STRENGTH_PARAMETER = "OGP/Strength"   # Float 0-1
# Panic silence. Toggle ON and every backend's dispatch multiply zeroes;
# toggle OFF and the previous strength returns untouched.
OGP_OFF_PARAMETER = "OGP/Off"      # Bool
# Sleep. Toggle ON and the toy chain's Wake stage switches to the
# stroke counter, so a brush against a sleeping partner does nothing.
OGP_SLEEP_PARAMETER = "OGP/Sleep"  # Bool
# Level the OGP/Test pulse drives every connected motor at — high enough
# to feel, low enough to be unmistakably a connectivity check.
OGP_TEST_LEVEL = 0.2
# Safety bound on the test pulse: the release edge is a single OSC bool,
# and a VRChat crash mid-hold would otherwise latch every motor at the
# test level forever. The hold auto-releases after this
# many seconds; tap again to keep testing.
OGP_TEST_MAX_HOLD_S = 10.0
# After an avatar swap VRChat replays the (possibly stale or reset) saved
# parameter values; incoming OGP/* control values inside this window are
# ignored and the app's current state is re-asserted instead, so an avatar
# load can never yank the mode, strength or toggles out from under the user.
OGP_MODE_SYNC_GUARD_S = 2.0
# Ignore inbound OGP/Strength jitter below this: VRChat sends a radial
# puppet as a stream of floats, and a change smaller than this is menu
# noise, not intent. Also the granularity we echo back at.
OGP_STRENGTH_EPSILON = 0.01

# Icon choices offered by the mode editor (any emoji works; this is just
# the picker's palette).
MODE_ICON_CHOICES = [
    "\U0001F507", "\U0001F508", "\U0001F509", "\U0001F50A",   # volume family
    "\U0001F319", "\U0001F0CF", "⭐", "\U0001F525",       # moon joker star fire
    "\U0001F49C", "\U0001F499", "\U0001F43E", "\U0001F4A4",   # hearts paws zzz
    "⚡", "\U0001F3B2", "\U0001F9CA", "\U0001F30A",       # bolt dice ice wave
]

# --- Network ---
INTIFACE_WS_URL = "ws://127.0.0.1:12345"
VRC_DEFAULT_PORT = 9000

# --- Integrated Intiface engine ---
# When the user runs in "integrated" mode (the default), OscGoesPurrr spawns
# and supervises its own bundled `intiface-engine` instead of relying on a
# separately-launched Intiface Central. The binary is looked up in this
# folder (next to the source, or under the PyInstaller _MEIPASS at runtime).
# See intiface_integrated.py.
INTIFACE_ENGINE_DIRNAME = "intiface-engine"
# Grace window to confirm the spawned engine survived startup before the real
# Buttplug client dials it. This is NOT a readiness timeout: the engine binds
# its websocket within a few hundred ms, and the actual readiness gate is the
# client connect (a failed dial just makes the auto-reconnect loop retry). We
# only watch that the process doesn't immediately exit (bad flag, instant
# crash). Honored directly (with a 0.5 s floor) by _await_engine_startup.
INTIFACE_ENGINE_STARTUP_GRACE_S = 2.0

# --- Application Data ---
APP_NAME = "OscGoesPurrr"
