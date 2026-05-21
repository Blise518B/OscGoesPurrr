"""App-level settings (auto_connect, auto_refresh, simple mode, etc.)."""

import json
import os
from typing import Any, Dict

from utilities import atomic_write_json

from ._paths import APP_SETTINGS_FILE


# Default app settings
DEFAULT_APP_SETTINGS = {
    "auto_connect": True,
    "auto_refresh": True,
    "auto_connect_osc": True,
    "bind_all_interfaces": True,
    "hide_console": True,
    "minimize_to_tray": False,
    # Default ON so the first launch lands on the stripped Simple Mode panel.
    # The user can disable it from the Simple Mode panel or Settings.
    "simple_mode": True,
    # Simple Mode Position↔Speed blend (0.0 = pure SPS depth, 1.0 = pure
    # motion-derived speed). Per-toy profiles have their own per-motor
    # `motor_{i}_speed_blend` key; this app-level value applies in Simple Mode.
    "simple_mode_speed_blend": 0.0,
    # Speed-blend tuning knobs (exposed in the UI as debug spinboxes for now —
    # we can fold them back into hard-coded defaults once the values settle).
    # See MotorRouter for the math; these mirror its instance attributes
    # and must stay in sync with the `DEFAULT_SPEED_*` class constants there.
    "speed_input_deadband": 0.005,
    "speed_gain": 0.75,
    "speed_decay_tau": 0.30,
    "speed_output_cutoff": 0.02,
    # Feature toggles — turn off subsystems the user doesn't need so their
    # background threads / OSC traffic don't run. All default ON to match
    # pre-toggle behaviour.
    "feature_osc_inspector": True,
    "feature_bhaptics": True,
    "feature_hardware_monitor": True,
    "feature_steamvr_haptics": True,
    "feature_steamvr_battery": True,
    "feature_intiface": True,
}


class AppSettingsManager:
    """Manages app-level settings (auto_connect, auto_refresh, etc.)"""

    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._load_or_create_defaults()

    def _load_or_create_defaults(self) -> None:
        """Load settings from JSON file or create defaults if not exists."""
        if os.path.exists(APP_SETTINGS_FILE):
            try:
                with open(APP_SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    self.settings = {**DEFAULT_APP_SETTINGS, **loaded}
                    print(f"Loaded app settings from {APP_SETTINGS_FILE}")
                    return
            except (json.JSONDecodeError, IOError) as e:
                print(f"App settings load error: {e}, using defaults")

        # Use defaults if file doesn't exist or has errors
        self.settings = DEFAULT_APP_SETTINGS.copy()
        self._save_settings()

    def _save_settings(self) -> None:
        """Save current settings to JSON file."""
        try:
            atomic_write_json(APP_SETTINGS_FILE, self.settings, indent=2)
        except OSError as e:
            print(f"App settings save error: {e}")

    def get(self, key: str, default=None) -> Any:
        """Get a setting value"""
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value and save to file"""
        self.settings[key] = value
        self._save_settings()

    def update_setting(self, key: str, value: Any) -> None:
        """Update a setting value and persist to file (alias for set)"""
        self.settings[key] = value
        self._save_settings()
