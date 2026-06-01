"""Per-user settings managers. One JSON file per concern, all under the
same AppData directory.

Each manager is a thin wrapper around its JSON file with defaults,
validation, and migration helpers. ProfileManager (in config_manager.py)
composes these for the parts of state that belong to a profile.
"""

from ._paths import (
    APPDATA_DIR,
    APP_SETTINGS_FILE,
    BHAPTICS_SETTINGS_FILE,
    KNOWN_DEVICES_FILE,
    PROFILE_FILE,
    SESSIONS_DIR,
    SESSIONS_SETTINGS_FILE,
    SPS_SOURCES_FILE,
    STEAMVR_SETTINGS_FILE,
)
from .app import AppSettingsManager, DEFAULT_APP_SETTINGS
from .bhaptics import BHapticsSettingsManager
from .known_devices import KnownDevicesRegistry
from .sessions import SessionSettingsManager
from .sps_sources import SpsSourceManager
from .steamvr import SteamVRSettingsManager

__all__ = [
    "APPDATA_DIR",
    "APP_SETTINGS_FILE",
    "BHAPTICS_SETTINGS_FILE",
    "KNOWN_DEVICES_FILE",
    "PROFILE_FILE",
    "SESSIONS_DIR",
    "SESSIONS_SETTINGS_FILE",
    "SPS_SOURCES_FILE",
    "STEAMVR_SETTINGS_FILE",
    "AppSettingsManager",
    "BHapticsSettingsManager",
    "DEFAULT_APP_SETTINGS",
    "KnownDevicesRegistry",
    "SessionSettingsManager",
    "SpsSourceManager",
    "SteamVRSettingsManager",
]
