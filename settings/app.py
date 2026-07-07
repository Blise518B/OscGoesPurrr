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
    # Help Mode toggle for the Device Routing view header. Persisted so
    # the user doesn't have to re-enable it every session.
    "help_mode_enabled": False,
    # Anti-stuck safety cutoff for the toy (Device Routing / Buttplug) path.
    # VRChat OSC only fires on parameter change, so a frozen SPS proximity
    # (avatar swap, partner leaves, OSC routing loss) would otherwise drive a
    # motor at its last value forever. Two-timer model, parity with the
    # SteamVR/bHaptics backends (which have their own): a mid-range value
    # stuck for `active_s` is cut hard; a saturated (~100%) value gets the
    # longer `peaked_s` fuse then a gentle ramp. Defaults match the SteamVR
    # backend (7 / 15 s). Configured from the Device Routing → Anti-stuck card.
    "toy_antistuck_enabled": True,
    "toy_antistuck_active_s": 7,
    "toy_antistuck_peaked_s": 15,
    # How often the router re-evaluates all motors. Time-constant math
    # (decay_tau / attack_ms / release_ms) is wall-clock-based so this
    # is purely a CPU-vs-fidelity knob — no recalibration needed when
    # the rate changes. 30 / 60 / 90 / 120 are the UI presets; any
    # int in [10, 240] is accepted. Default matches the common headset
    # refresh rate (Index, Quest 2/3) so the router stays in step with
    # VRChat's avatar-parameter update cadence.
    "router_poll_rate_hz": 90,
    # Feature toggles — turn off subsystems the user doesn't need so their
    # background threads / OSC traffic don't run. All default ON to match
    # pre-toggle behaviour.
    "feature_osc_inspector": True,
    "feature_bhaptics": True,
    "feature_steamvr_haptics": True,
    "feature_steamvr_battery": True,
    "feature_intiface": True,
    # Newer backends. Visible by default so they're discoverable; each engine
    # still requires an explicit connect (e-stim auto-connect defaults OFF in
    # the per-backend settings) before anything fires.
    "feature_pishock": True,
    "feature_owo": True,
    "feature_coyote": True,
    "feature_handy": True,
    # Intiface server provisioning. True (default) = OscGoesPurrr spawns and
    # supervises its own bundled intiface-engine, so no separate Intiface
    # Central launch is needed. False = connect to a user-run Intiface Central
    # (the original behavior). See intiface_connection.py and the Settings →
    # Intiface Engine toggle.
    "use_integrated_intiface": True,
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
