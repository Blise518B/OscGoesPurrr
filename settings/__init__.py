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
    COYOTE_SETTINGS_FILE,
    HANDY_SETTINGS_FILE,
    KNOWN_DEVICES_FILE,
    OWO_SETTINGS_FILE,
    PISHOCK_SETTINGS_FILE,
    PROFILE_FILE,
    SESSIONS_DIR,
    SESSIONS_SETTINGS_FILE,
    SPS_SOURCES_FILE,
    STEAMVR_SETTINGS_FILE,
)
from .app import AppSettingsManager, DEFAULT_APP_SETTINGS
from .bhaptics import BHapticsSettingsManager
from .coyote import CoyoteSettingsManager
from .handy import HandySettingsManager
from .known_devices import KnownDevicesRegistry
from .owo import OwoSettingsManager
from .pishock import PiShockSettingsManager
from .sessions import SessionSettingsManager
from .sps_sources import SpsSourceManager
from .steamvr import SteamVRSettingsManager

__all__ = [
    "APPDATA_DIR",
    "APP_SETTINGS_FILE",
    "BHAPTICS_SETTINGS_FILE",
    "COYOTE_SETTINGS_FILE",
    "HANDY_SETTINGS_FILE",
    "KNOWN_DEVICES_FILE",
    "OWO_SETTINGS_FILE",
    "PISHOCK_SETTINGS_FILE",
    "PROFILE_FILE",
    "SESSIONS_DIR",
    "SESSIONS_SETTINGS_FILE",
    "SPS_SOURCES_FILE",
    "STEAMVR_SETTINGS_FILE",
    "AppSettingsManager",
    "BHapticsSettingsManager",
    "CoyoteSettingsManager",
    "DEFAULT_APP_SETTINGS",
    "HandySettingsManager",
    "KnownDevicesRegistry",
    "OwoSettingsManager",
    "PiShockSettingsManager",
    "SessionSettingsManager",
    "SpsSourceManager",
    "SteamVRSettingsManager",
]
