"""Filesystem paths for all per-user settings files.

Kept in one module so the individual settings managers and the
ProfileManager all agree on AppData layout. Importing this module
ensures the AppData directory exists.
"""

import os
from pathlib import Path

from constants import APP_NAME


# AppData directory for persistent storage
APPDATA_DIR = Path.home() / "AppData" / "Roaming" / APP_NAME

# Profile file path (managed by ProfileManager in config_manager.py)
PROFILE_FILE = APPDATA_DIR / "profiles.json"

# App settings file path
APP_SETTINGS_FILE = APPDATA_DIR / "app_settings.json"

# SteamVR settings file path (autostart, vibration patterns, per-tracker config)
STEAMVR_SETTINGS_FILE = APPDATA_DIR / "steamvr_settings.json"

# bHaptics settings file path (Player connection, per-device enable + intensity)
BHAPTICS_SETTINGS_FILE = APPDATA_DIR / "bhaptics_settings.json"

# Known devices file path — global registry of every toy that's ever been
# connected, independent of any profile. Lets new/empty profiles still show
# previously-seen toys with default settings.
KNOWN_DEVICES_FILE = APPDATA_DIR / "known_devices.json"

# Synthetic SPS sources file path — global registry of user-defined virtual
# contact zones (proximity + activation gate + velocity multiplier). Global,
# like known_devices, so the sources are shared across profiles and visible
# to both the Buttplug and bHaptics routers. See sps_source.py.
SPS_SOURCES_FILE = APPDATA_DIR / "sps_sources.json"

# Newer backends — one settings file per integration, same convention as the
# managers above. OWO suit (muscle e-stim), PiShock (shock collar), DG-Lab
# Coyote (A/B e-stim), The Handy (cloud stroker). Like SteamVR/bHaptics these
# hold hardware + routing config, not avatar-bound profile state.
OWO_SETTINGS_FILE = APPDATA_DIR / "owo_settings.json"
PISHOCK_SETTINGS_FILE = APPDATA_DIR / "pishock_settings.json"
COYOTE_SETTINGS_FILE = APPDATA_DIR / "coyote_settings.json"
HANDY_SETTINGS_FILE = APPDATA_DIR / "handy_settings.json"

# Session logger: a directory holding one JSONL file per recorded VR
# session, plus a tiny settings file for the engine's enable / auto-start
# / retention preferences. The directory is created at first session
# start, not on import, because it's empty until the user opts in.
SESSIONS_DIR = APPDATA_DIR / "sessions"
SESSIONS_SETTINGS_FILE = APPDATA_DIR / "sessions_settings.json"


os.makedirs(APPDATA_DIR, exist_ok=True)
