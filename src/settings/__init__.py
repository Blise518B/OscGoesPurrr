"""Per-user settings managers. One JSON file per concern, all under the
same AppData directory.

Each manager is a thin wrapper around its JSON file with defaults,
validation, and migration helpers. ModeManager (in config_manager.py)
composes these for the parts of state that belong to a profile.
"""

from ._paths import (
    APPDATA_DIR,
    APP_SETTINGS_FILE,
    KNOWN_DEVICES_FILE,
    MODES_FILE,
    SESSIONS_DIR,
    SESSIONS_SETTINGS_FILE,
    SPS_SOURCES_FILE,
    STATS_FILE,
)
from .app import AppSettingsManager, DEFAULT_APP_SETTINGS
from .known_devices import KnownDevicesRegistry
from .sessions import SessionSettingsManager
from .sps_sources import SpsSourceManager

__all__ = [
    "APPDATA_DIR",
    "APP_SETTINGS_FILE",
    "KNOWN_DEVICES_FILE",
    "MODES_FILE",
    "SESSIONS_DIR",
    "SESSIONS_SETTINGS_FILE",
    "SPS_SOURCES_FILE",
    "STATS_FILE",
    "AppSettingsManager",
    "DEFAULT_APP_SETTINGS",
    "KnownDevicesRegistry",
    "SessionSettingsManager",
    "SpsSourceManager",
]
