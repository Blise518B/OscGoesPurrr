"""Filesystem paths for all per-user settings files.

Kept in one module so the individual settings managers and the
ModeManager all agree on AppData layout. Importing this module
ensures the AppData directory exists.
"""

import os
from pathlib import Path

from constants import APP_NAME


# AppData directory for persistent storage
APPDATA_DIR = Path.home() / "AppData" / "Roaming" / APP_NAME

# Routing modes + rig + feel (schema v4, managed by ModeManager in
# config_manager.py). This is the live config file, and the only one the
# app reads or writes.
#
# There is deliberately NO migration from any earlier config. While the app
# is pre-release, a schema bump starts from defaults rather than carrying a
# reader for every shape the file has ever had. The distinct filename still
# earns its keep: an older build finds no modes.json and starts fresh
# instead of renaming a file it cannot parse.
MODES_FILE = APPDATA_DIR / "modes.json"

# App settings file path
APP_SETTINGS_FILE = APPDATA_DIR / "app_settings.json"

# Known devices file path — global registry of every toy that's ever been
# connected, independent of any profile. Lets new/empty profiles still show
# previously-seen toys with default settings.
KNOWN_DEVICES_FILE = APPDATA_DIR / "known_devices.json"

# Synthetic SPS sources file path — global registry of user-defined virtual
# contact zones (proximity + activation gate + velocity multiplier). Global,
# like known_devices, so the sources are shared across profiles and visible
# to the Buttplug router. See sps_source.py.
SPS_SOURCES_FILE = APPDATA_DIR / "sps_sources.json"

# Session logger: a directory holding one JSONL file per recorded VR
# session, plus a tiny settings file for the engine's enable / auto-start
# / retention preferences. The directory is created at first session
# start, not on import, because it's empty until the user opts in.
SESSIONS_DIR = APPDATA_DIR / "sessions"
SESSIONS_SETTINGS_FILE = APPDATA_DIR / "sessions_settings.json"

# Usage statistics — lifetime totals (on-time, thrusts, per-toy /
# per-zone usage) plus the recent-session summaries. Owned by
# stats_tracker.StatsTracker, not a settings manager.
STATS_FILE = APPDATA_DIR / "stats.json"


os.makedirs(APPDATA_DIR, exist_ok=True)
