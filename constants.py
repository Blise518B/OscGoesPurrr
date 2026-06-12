# constants.py

# --- Theme & Colors ---
# Each accent has a semantic job — see ARCHITECTURE.md / UI restyle notes.
# Brand primary identity (purple) drives nav/selection/focus.
# The other accents carry meaning: pink = live data, green = healthy,
# orange = warning, red-pink = error. Don't reach for primary just to make
# something "pop"; pick the accent whose meaning fits the state.

# Primary brand — punchier than the prior #6B4EFF so it reads against the
# deeper indigo canvas.
COLOR_PRIMARY = "#7C4DFF"         # Main brand accent (Electric Purple)
COLOR_PRIMARY_HOVER = "#6A3DEC"

# Error / destructive (was COLOR_ALERT — kept name for back-compat).
COLOR_ALERT = "#FF1150"           # Error / destructive (Hot Red-Pink)
COLOR_ALERT_HOVER = "#DD0E45"

# Success / healthy / connected
COLOR_SUCCESS = "#07FF77"         # Connected / Good (Neon Green)

# New semantic accents
COLOR_LIVE = "#FF3D7F"            # Live data, "now firing" feedback (Hot Pink)
COLOR_LIVE_DIM = "#7A1E3F"        # Pill background tint for COLOR_LIVE text
COLOR_WARNING = "#FF7300"         # Attention but not error (Orange)
COLOR_WARNING_DIM = "#7A3700"     # Pill background tint for COLOR_WARNING text
COLOR_SUCCESS_DIM = "#073D24"     # Pill background tint for COLOR_SUCCESS text
COLOR_ALERT_DIM = "#5A0820"       # Pill background tint for COLOR_ALERT text

# Surfaces — tinted deep indigo, not neutral grey. The hue shift is what
# separates the look from a generic dark theme.
COLOR_BG = "#0D0924"              # Deep app background (indigo-black)
COLOR_SURFACE = "#1D1553"         # Cards, active tabs, separators
COLOR_SURFACE_HOVER = "#2A2070"   # Hover state for tabs

# Interactive surfaces — buttons and clickable areas sit on top of cards
# (COLOR_SURFACE), so they need to be clearly lighter to read as "clickable".
COLOR_BUTTON = "#3A2C8C"          # Secondary/idle buttons, segmented controls
COLOR_BUTTON_HOVER = "#4D3CB3"    # Hover state for interactive buttons

# Interactive widget surfaces — slightly lighter so dropdowns, search fields
# and pickers stand out from cards/window background as obviously clickable.
COLOR_INPUT_BG = "#1A1240"        # Text inputs, combo boxes, pickers
COLOR_INPUT_BORDER = "#3A2C8C"    # Resting border for interactive widgets
COLOR_INPUT_FOCUS = "#9A7BFF"     # Focus border (lighter purple)

# Text
COLOR_TEXT = "#FFFFFF"
COLOR_TEXT_MUTED = "#9A9AB8"      # Secondary labels — slight purple tint

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
LINEAR_MAX_SEND_INTERVAL_MS = 60.0
# Don't re-transmit a position the actuator hasn't moved past (float-jitter floor);
# lets a held/resting stroke go quiet instead of re-commanding the same spot.
LINEAR_MIN_POSITION_DELTA = 1e-4

ROUTER_POLL_RATE_MS = 16
QUEUE_POLL_RATE_MS = 50
UI_REFRESH_RATE_MS = 250
OSC_BOOT_DELAY_MS = 500
AUTO_REFRESH_RATE_S = 30.0

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
