# constants.py

# --- Theme & Colors ---
COLOR_PRIMARY = "#6B4EFF"         # Main brand accent (Purple)
COLOR_PRIMARY_HOVER = "#5A3DCC"
COLOR_ALERT = "#FF5E57"           # Unified Warning/Danger action color
COLOR_ALERT_HOVER = "#DD4E46"
COLOR_SUCCESS = "#00C853"         # Connected / Good (Green)

# Surfaces
COLOR_BG = "#1E1E2E"              # Deep app background
COLOR_SURFACE = "#2A2A3E"         # Cards, active tabs, separators, secondary btns
COLOR_SURFACE_HOVER = "#3A3A4A"   # Hover state for tabs & secondary btns

# Interactive widget surfaces — slightly lighter so dropdowns, search fields
# and pickers stand out from cards/window background as obviously clickable.
COLOR_INPUT_BG = "#363649"        # Text inputs, combo boxes, pickers
COLOR_INPUT_BORDER = "#5A5A78"    # Resting border for interactive widgets
COLOR_INPUT_FOCUS = "#8A78FF"     # Focus border (lighter purple)

# Text
COLOR_TEXT = "#FFFFFF"
COLOR_TEXT_MUTED = "#888888"

# --- UI Dimensions ---
WINDOW_GEOMETRY = "1100x700"
SIDEBAR_WIDTH = 200
BTN_HEIGHT_LARGE = 35
BTN_HEIGHT_SMALL = 30

# --- Timing & System (ms/seconds) ---
HAPTIC_POLL_RATE = 0.02
ROUTER_POLL_RATE_MS = 33
QUEUE_POLL_RATE_MS = 50
UI_REFRESH_RATE_MS = 250
OSC_BOOT_DELAY_MS = 500
AUTO_REFRESH_RATE_S = 30.0

# --- Network ---
INTIFACE_WS_URL = "ws://127.0.0.1:12345"
VRC_DEFAULT_PORT = 9000

# --- Application Data ---
APP_NAME = "OscGoesPurrr"
