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
HAPTIC_POLL_RATE = 0.02
ROUTER_POLL_RATE_MS = 16
QUEUE_POLL_RATE_MS = 50
UI_REFRESH_RATE_MS = 250
OSC_BOOT_DELAY_MS = 500
AUTO_REFRESH_RATE_S = 30.0

# --- Network ---
INTIFACE_WS_URL = "ws://127.0.0.1:12345"
VRC_DEFAULT_PORT = 9000

# --- Application Data ---
APP_NAME = "OscGoesPurrr"
