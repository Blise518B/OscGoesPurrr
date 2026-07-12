# constants.py

import json as _json
from pathlib import Path as _Path

# --- Theme & Colors ---
# Each accent has a semantic job — see ARCHITECTURE.md / UI restyle notes.
# Brand primary identity drives nav/selection/focus. The other accents
# carry meaning: live = "now firing", green = healthy, orange = warning,
# red = error. Don't reach for primary just to make something "pop"; pick
# the accent whose meaning fits the state.
#
# The colors ship as named PROFILES. "purrple" is the original indigo /
# electric-purple identity and stays byte-identical; "noir" is the black
# & green alternative. The active profile comes from the persisted app
# setting `color_profile`, read straight from app_settings.json below —
# constants must stay import-safe (no project imports, no Qt), and every
# module copies these values at import time, so switching profiles in
# Settings applies on the next launch.

# The original identity, defined once — "purrple" ships it verbatim and
# "purrple_gradient" derives from it (same palette, gradient brushes).
_PURRPLE = {
    "label": "Purrple (default)",
        # Primary brand — punchier than the prior #6B4EFF so it reads
        # against the deeper indigo canvas.
        "PRIMARY": "#7C4DFF",        # Main brand accent (Electric Purple)
        "PRIMARY_HOVER": "#6A3DEC",
        "ALERT": "#FF1150",          # Error / destructive (Hot Red-Pink)
        "ALERT_HOVER": "#DD0E45",
        "SUCCESS": "#07FF77",        # Connected / Good (Neon Green)
        "LIVE": "#FF3D7F",           # Live data, "now firing" (Hot Pink)
        "LIVE_DIM": "#7A1E3F",       # Pill background tint for LIVE text
        "WARNING": "#FF7300",        # Attention but not error (Orange)
        "WARNING_DIM": "#7A3700",
        "SUCCESS_DIM": "#073D24",
        "ALERT_DIM": "#5A0820",
        # Surfaces — tinted deep indigo, not neutral grey. The hue shift
        # is what separates the look from a generic dark theme.
        "BG": "#0D0924",             # Deep app background (indigo-black)
        "SURFACE": "#1D1553",        # Cards, active tabs, separators
        "SURFACE_HOVER": "#2A2070",  # Hover state for tabs
        # Interactive surfaces — clearly lighter than cards so they read
        # as "clickable".
        "BUTTON": "#3A2C8C",
        "BUTTON_HOVER": "#4D3CB3",
        "INPUT_BG": "#1A1240",       # Text inputs, combo boxes, pickers
        "INPUT_BORDER": "#3A2C8C",
        "INPUT_FOCUS": "#9A7BFF",    # Focus border (lighter purple)
        "TEXT": "#FFFFFF",
        "TEXT_ON_PRIMARY": "#FFFFFF",  # Label text sitting on a PRIMARY fill
        "TEXT_MUTED": "#9A9AB8",     # Secondary labels — slight purple tint
        # Signal-chain activity ramp (fold cards / stage cards / arrows):
        # idle end matches the canvas, live end pulls attention.
        "CHAIN_IDLE": "#5030A0",     # dark purple
        "CHAIN_LIVE": "#FF40A0",     # vivid pink
        # OSC-inspector value ramp (0 → 1 tint for numeric params).
        "VALUE_LO": "#7C4DFF",
        "VALUE_HI": "#FF3D7F",
}

COLOR_PROFILES = {
    "purrple": _PURRPLE,
    "purrple_gradient": {
        **_PURRPLE,
        "label": "Purrple (gradient)",
        # The default identity with its brand pair as real gradients:
        # indigo → violet → wine sweeping the whole background, a subtle
        # card sheen, and purple → pink primary buttons (same pair the
        # seg controls / scrollbars already paint).
        "BG_BRUSH": (
            "qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #0D0924, stop:0.35 #120C33,"
            " stop:0.65 #1A0D38, stop:1 #260B2E)"
        ),
        "SURFACE_BRUSH": (
            "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #221A5E, stop:1 #181048)"
        ),
        "PRIMARY_BRUSH": (
            "qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #7C4DFF, stop:1 #FF3D7F)"
        ),
        "WINDOW_BORDER": "#7C4DFF",
        "WINDOW_CAPTION": "#0D0924",
        "WINDOW_CAPTION_TEXT": "#FFFFFF",
    },
    "noir": {
        "label": "Noir (black & green)",
        # ONE green. Neutral black/gray base everywhere; the single
        # vibrant green (#07FF77) carries every highlight — outlines,
        # focus, selection, chain activity, window border. No tinted
        # surfaces, no gradient of green hues. Red stays for errors,
        # orange for warnings, and a selective blue marks live/
        # significant numbers — which also makes the gradient elements
        # (scrollbars, meters, seg controls: PRIMARY → LIVE) run the
        # green → light-blue sweep.
        "PRIMARY": "#07FF77",        # THE highlight green
        "PRIMARY_HOVER": "#00D95C",  # pressed/hover shade of the same green
        "ALERT": "#FF1150",          # Error stays red — semantics over style
        "ALERT_HOVER": "#DD0E45",
        "SUCCESS": "#07FF77",        # Connected / Good — same green
        "LIVE": "#4DB8FF",           # Live data numbers (selective blue)
        "LIVE_DIM": "#123246",
        "WARNING": "#FF7300",        # Warning stays orange
        "WARNING_DIM": "#7A3700",
        "SUCCESS_DIM": "#073D24",
        "ALERT_DIM": "#5A0820",
        # Surfaces — neutral black and gray, no hue tint.
        "BG": "#0A0A0A",             # App background (near-black)
        "SURFACE": "#161616",        # Cards, active tabs, separators
        "SURFACE_HOVER": "#202020",  # Hover state for tabs
        "BUTTON": "#242424",
        "BUTTON_HOVER": "#303030",
        "INPUT_BG": "#101010",       # Fields: black…
        "INPUT_BORDER": "#07FF77",   # …with the vibrant green outline
        "INPUT_FOCUS": "#B3FFD1",    # Focused field pops brighter
        "TEXT": "#FFFFFF",
        # Vibrant green is far too light for white labels (~1.35:1) —
        # buttons/selections carry near-black text on the green fill.
        "TEXT_ON_PRIMARY": "#0A0A0A",
        "TEXT_MUTED": "#9A9A9A",     # Secondary labels — neutral gray
        "CHAIN_IDLE": "#3A3A3A",     # idle = gray, part of the base
        "CHAIN_LIVE": "#07FF77",     # live = the highlight green
        # OSC-inspector value ramp: gray base → green highlight. The low
        # end doubles as TEXT (the inspector paints values with it), so
        # it must stay legible on the near-black background — mid-gray,
        # not the surface gray.
        "VALUE_LO": "#9A9A9A",
        "VALUE_HI": "#07FF77",
        # Native window frame (Windows 11 DWM). Purrple leaves the
        # system frame untouched; noir claims it for the identity.
        "WINDOW_BORDER": "#07FF77",
        "WINDOW_CAPTION": "#0A0A0A",
        "WINDOW_CAPTION_TEXT": "#FFFFFF",
    },
    "aurora": {
        "label": "Aurora (gradient)",
        # GitHub-website-inspired: a deep navy→teal gradient sweeping the
        # ENTIRE app background, subtle card sheen, and the hero pair
        # (green #07FF77 → light blue #4DB8FF) as smooth gradients on the
        # highlights — primary buttons, scrollbars, meters. Base tones
        # follow GitHub dark (#0D1117 family). The optional *_BRUSH keys
        # are full QSS brush expressions; profiles without them (purrple,
        # noir) render the flat color and their stylesheets stay
        # byte-identical.
        "PRIMARY": "#07FF77",
        "PRIMARY_HOVER": "#00D95C",
        "PRIMARY_BRUSH": (
            "qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #07FF77, stop:1 #4DB8FF)"
        ),
        "ALERT": "#FF1150",
        "ALERT_HOVER": "#DD0E45",
        "SUCCESS": "#07FF77",
        "LIVE": "#4DB8FF",
        "LIVE_DIM": "#123246",
        "WARNING": "#FF7300",
        "WARNING_DIM": "#7A3700",
        "SUCCESS_DIM": "#073D24",
        "ALERT_DIM": "#5A0820",
        "BG": "#0D1117",             # flat fallback (painted widgets, masks)
        "BG_BRUSH": (
            "qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            " stop:0 #0D1117, stop:0.35 #101C2C,"
            " stop:0.65 #0F2431, stop:1 #0C2B20)"
        ),
        "SURFACE": "#161C23",
        "SURFACE_BRUSH": (
            "qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #1A2129, stop:1 #141A21)"
        ),
        "SURFACE_HOVER": "#1F2833",
        "BUTTON": "#21262D",
        "BUTTON_HOVER": "#30363D",
        "INPUT_BG": "#0D1117",
        "INPUT_BORDER": "#30363D",
        "INPUT_FOCUS": "#58A6FF",
        "TEXT": "#FFFFFF",
        "TEXT_ON_PRIMARY": "#0A0A0A",
        "TEXT_MUTED": "#8B949E",
        # Chain activity: idle slate-blue → live green, so the arrows and
        # rings sweep across the aurora spectrum as signal flows.
        "CHAIN_IDLE": "#2D4A66",
        "CHAIN_LIVE": "#07FF77",
        # Inspector value ramp: calm blue → hot green.
        "VALUE_LO": "#4DB8FF",
        "VALUE_HI": "#07FF77",
        "WINDOW_BORDER": "#4DB8FF",
        "WINDOW_CAPTION": "#0D1117",
        "WINDOW_CAPTION_TEXT": "#FFFFFF",
    },
}

DEFAULT_COLOR_PROFILE = "purrple"


# ---------------------------------------------------------------------------
# Custom theme derivation — the whole palette from two user-picked colors.
# Pure hex math (stdlib only; this module must stay import-safe). Color A is
# the hero/highlight (primary, outlines, success, chain-live, window border),
# color B the second accent (live pill, value-ramp low end, gradient partner).
# The base stays neutral near-black/gray — per the design language, tint
# belongs in highlights and gradients, never in surfaces. Alert red and
# warning amber are fixed: error semantics don't re-theme.
# ---------------------------------------------------------------------------

def _crgb(hex_color):
    h = str(hex_color).lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _chex(r, g, b):
    return "#%02X%02X%02X" % (
        max(0, min(255, int(round(r)))),
        max(0, min(255, int(round(g)))),
        max(0, min(255, int(round(b)))),
    )


def _cmix(hex_a, hex_b, t):
    """Blend a→b by t (0..1)."""
    a, b = _crgb(hex_a), _crgb(hex_b)
    return _chex(*(a[i] + (b[i] - a[i]) * t for i in range(3)))


def _cluma(hex_color):
    """Cheap relative luminance (0..1) for text-contrast picks."""
    r, g, b = _crgb(hex_color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def _valid_hex(value, fallback):
    # Strict char check — int(x, 16) tolerates whitespace/signs/fullwidth
    # digits inside the slices, which would let a malformed accent leak
    # verbatim into QSS color slots and gradient strings.
    v = str(value or "")
    if (len(v) == 7 and v[0] == "#"
            and all(ch in "0123456789abcdefABCDEF" for ch in v[1:])):
        return v.upper()
    return fallback


def derive_custom_palette(color_a, color_b, gradient=False):
    """Build a full profile palette dict from two accents. Same key set the
    shipped profiles carry (validated by tests/test_color_profiles.py);
    `gradient=True` adds the BG/SURFACE/PRIMARY brush sweeps like Aurora."""
    a = _valid_hex(color_a, "#07FF77")
    b = _valid_hex(color_b, "#4DB8FF")
    on_a = "#0A0A0A" if _cluma(a) > 0.45 else "#FFFFFF"
    bg = "#0C0D0E"
    palette = {
        "label": "Custom (yours)",
        "PRIMARY": a,
        "PRIMARY_HOVER": _cmix(a, "#FFFFFF", 0.18),
        "ALERT": "#F44336", "ALERT_HOVER": "#EF5350",
        "ALERT_DIM": "#5A1F1F",
        "WARNING": "#FFC107", "WARNING_DIM": "#5A4A1F",
        "SUCCESS": a, "SUCCESS_DIM": _cmix(a, bg, 0.72),
        "LIVE": b, "LIVE_DIM": _cmix(b, bg, 0.72),
        "BG": bg,
        "SURFACE": "#17181A", "SURFACE_HOVER": "#202224",
        "BUTTON": "#232527", "BUTTON_HOVER": "#2E3134",
        "INPUT_BG": "#101214",
        "INPUT_BORDER": a,
        "INPUT_FOCUS": _cmix(a, "#FFFFFF", 0.45),
        "TEXT": "#FFFFFF",
        "TEXT_ON_PRIMARY": on_a,
        "TEXT_MUTED": "#9A9EA3",
        "CHAIN_IDLE": _cmix(a, bg, 0.75),
        "CHAIN_LIVE": a,
        "VALUE_LO": b, "VALUE_HI": a,
        "WINDOW_BORDER": a,
        "WINDOW_CAPTION": bg,
        "WINDOW_CAPTION_TEXT": "#FFFFFF",
    }
    if gradient:
        corner_a = _cmix(bg, a, 0.14)
        mid = _cmix(bg, _cmix(a, b, 0.5), 0.08)
        corner_b = _cmix(bg, b, 0.14)
        palette["BG_BRUSH"] = (
            f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {corner_a}, "
            f"stop:0.35 {mid}, stop:0.65 {bg}, stop:1 {corner_b})"
        )
        palette["SURFACE_BRUSH"] = (
            f"qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            f"stop:0 {_cmix('#17181A', a, 0.06)}, stop:1 #141517)"
        )
        palette["PRIMARY_BRUSH"] = (
            f"qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {a}, stop:1 {b})"
        )
    return palette


def _load_color_profile() -> str:
    """Read the persisted profile choice without importing the settings
    package (which imports this module). A "custom" choice derives its
    palette from the two saved accents and registers it before resolving.
    Any failure — missing file, bad JSON, unknown name — falls back to the
    default palette."""
    try:
        p = (_Path.home() / "AppData" / "Roaming" / "OscGoesPurrr"
             / "app_settings.json")
        with open(p, "r", encoding="utf-8") as f:
            settings = _json.load(f)
        choice = settings.get("color_profile")
        if choice == "custom":
            colors = settings.get("custom_colors")
            colors = colors if isinstance(colors, dict) else {}
            COLOR_PROFILES["custom"] = derive_custom_palette(
                colors.get("a"), colors.get("b"),
                gradient=bool(colors.get("gradient", True)),
            )
            return "custom"
        if choice in COLOR_PROFILES:
            return choice
    except Exception:
        pass
    return DEFAULT_COLOR_PROFILE


COLOR_PROFILE = _load_color_profile()
_PALETTE = COLOR_PROFILES[COLOR_PROFILE]

COLOR_PRIMARY = _PALETTE["PRIMARY"]
COLOR_PRIMARY_HOVER = _PALETTE["PRIMARY_HOVER"]
COLOR_ALERT = _PALETTE["ALERT"]
COLOR_ALERT_HOVER = _PALETTE["ALERT_HOVER"]
COLOR_SUCCESS = _PALETTE["SUCCESS"]
COLOR_LIVE = _PALETTE["LIVE"]
COLOR_LIVE_DIM = _PALETTE["LIVE_DIM"]
COLOR_WARNING = _PALETTE["WARNING"]
COLOR_WARNING_DIM = _PALETTE["WARNING_DIM"]
COLOR_SUCCESS_DIM = _PALETTE["SUCCESS_DIM"]
COLOR_ALERT_DIM = _PALETTE["ALERT_DIM"]
COLOR_BG = _PALETTE["BG"]
COLOR_SURFACE = _PALETTE["SURFACE"]
COLOR_SURFACE_HOVER = _PALETTE["SURFACE_HOVER"]
COLOR_BUTTON = _PALETTE["BUTTON"]
COLOR_BUTTON_HOVER = _PALETTE["BUTTON_HOVER"]
COLOR_INPUT_BG = _PALETTE["INPUT_BG"]
COLOR_INPUT_BORDER = _PALETTE["INPUT_BORDER"]
COLOR_INPUT_FOCUS = _PALETTE["INPUT_FOCUS"]
COLOR_TEXT = _PALETTE["TEXT"]
COLOR_TEXT_ON_PRIMARY = _PALETTE["TEXT_ON_PRIMARY"]
COLOR_TEXT_MUTED = _PALETTE["TEXT_MUTED"]
COLOR_CHAIN_IDLE = _PALETTE["CHAIN_IDLE"]
COLOR_CHAIN_LIVE = _PALETTE["CHAIN_LIVE"]
COLOR_VALUE_LO = _PALETTE["VALUE_LO"]
COLOR_VALUE_HI = _PALETTE["VALUE_HI"]
# QSS brush expressions for the big fills. Profiles may override these
# with gradient brushes (aurora); everywhere else they resolve to the
# flat color so the generated stylesheet is unchanged.
COLOR_BG_BRUSH = _PALETTE.get("BG_BRUSH", COLOR_BG)
COLOR_SURFACE_BRUSH = _PALETTE.get("SURFACE_BRUSH", COLOR_SURFACE)
COLOR_PRIMARY_BRUSH = _PALETTE.get("PRIMARY_BRUSH", COLOR_PRIMARY)
# Native window frame (Windows 11 DWM attributes). None = leave the
# system default exactly as-is (the purrple profile does this).
COLOR_WINDOW_BORDER = _PALETTE.get("WINDOW_BORDER")
COLOR_WINDOW_CAPTION = _PALETTE.get("WINDOW_CAPTION")
COLOR_WINDOW_CAPTION_TEXT = _PALETTE.get("WINDOW_CAPTION_TEXT")

# --- UI Dimensions ---
WINDOW_GEOMETRY = "1100x700"
SIDEBAR_WIDTH = 200
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
# (latest-wins): The Handy is flushed once per 50 ms (20 Hz, per the official
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

# --- OGP avatar parameters (VRChat expression-menu control) ---
# Stored/compared in the bare parameter_store form (the OSC prefix is
# stripped on ingest and re-added on send).
OGP_MODE_PARAMETER = "OGP/Mode"    # Int 0-5: switches the active mode
OGP_TEST_PARAMETER = "OGP/Test"    # Bool: hold to run the connectivity pulse
# Level the test pulse drives vibration-type backends at (toys, SteamVR,
# bHaptics). E-stim/EMS backends (PiShock, Coyote, OWO) are deliberately
# excluded from the test pulse — a surprise shock is not a connectivity check.
OGP_TEST_LEVEL = 0.2
# Safety bound on the test pulse: the release edge is a single OSC bool,
# and a VRChat crash mid-hold would otherwise latch every vibration
# backend at the test level forever. The hold auto-releases after this
# many seconds; tap again to keep testing.
OGP_TEST_MAX_HOLD_S = 10.0
# After an avatar swap VRChat replays the (possibly stale or reset) saved
# parameter values; incoming OGP/Mode inside this window is ignored and the
# app's current mode is re-asserted instead, so an avatar load can never
# yank the mode out from under the user.
OGP_MODE_SYNC_GUARD_S = 2.0

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
