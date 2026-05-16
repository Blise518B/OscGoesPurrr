# Config Manager - Profile and Configuration Handling
# Extracted from OscGoesPurrr to separate concerns

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

from constants import APP_NAME


# AppData directory for persistent storage
APPDATA_DIR = Path.home() / "AppData" / "Roaming" / APP_NAME

# Profile file path
PROFILE_FILE = APPDATA_DIR / "profiles.json"

# App settings file path
APP_SETTINGS_FILE = APPDATA_DIR / "app_settings.json"

# Known devices file path — global registry of every toy that's ever been
# connected, independent of any profile. Lets new/empty profiles still show
# previously-seen toys with default settings.
KNOWN_DEVICES_FILE = APPDATA_DIR / "known_devices.json"

# Default app settings
DEFAULT_APP_SETTINGS = {
    "auto_connect": True,
    "auto_refresh": True,
    "auto_connect_osc": True,
    "bind_all_interfaces": True,
    "hide_console": True,
    "minimize_to_tray": False
}

# Ensure AppData directory exists
os.makedirs(APPDATA_DIR, exist_ok=True)


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
            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except IOError as e:
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
        try:
            with open(APP_SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")


class KnownDevicesRegistry:
    """Global registry of every toy that's ever been connected.

    Stored separately from profiles so switching to (or creating) a new empty
    profile still knows about toys the user has used before. Each entry holds
    the structural facts about the toy (motor_count, motor_kinds) — anything
    profile-specific (zones, custom OSC, filters) stays inside the profile.
    """

    def __init__(self):
        self.devices: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(KNOWN_DEVICES_FILE):
            try:
                with open(KNOWN_DEVICES_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.devices = loaded
                        return
            except (json.JSONDecodeError, IOError) as e:
                print(f"Known devices load error: {e}")
        self.devices = {}

    def save(self) -> None:
        try:
            with open(KNOWN_DEVICES_FILE, 'w') as f:
                json.dump(self.devices, f, indent=2)
        except IOError as e:
            print(f"Known devices save error: {e}")

    def register(self, name: str, motor_count: int, motor_kinds=None) -> bool:
        """Record/refresh a toy. Returns True if anything was added or changed."""
        if not name:
            return False
        entry = self.devices.get(name, {})
        changed = False
        if entry.get("motor_count") != motor_count:
            entry["motor_count"] = motor_count
            changed = True
        if motor_kinds is not None and entry.get("motor_kinds") != motor_kinds:
            entry["motor_kinds"] = list(motor_kinds)
            changed = True
        if name not in self.devices or changed:
            self.devices[name] = entry
            self.save()
            return True
        return False

    def forget(self, name: str) -> None:
        if name in self.devices:
            del self.devices[name]
            self.save()

    def all(self) -> Dict[str, Any]:
        return dict(self.devices)


class ProfileManager:
    """Manages profile loading, saving, and device configuration."""

    def __init__(self):
        self.profiles: Dict[str, Any] = {}
        self.current_profile = "Default"
        self.app_settings = AppSettingsManager()
        self.known_devices = KnownDevicesRegistry()
        self._load_or_create_default()
    
    def _load_or_create_default(self) -> None:
        """Load profiles from JSON file or create default if not exists."""
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE, 'r') as f:
                    self.profiles = json.load(f)
                    print(f"Loaded profiles from {PROFILE_FILE}")
            except (json.JSONDecodeError, IOError) as e:
                print(f"Profile load error: {e}, creating default profile")
                self.profiles = {"Default": {}}
                self.save_profiles()
        else:
            # Create default profile if file doesn't exist
            self.profiles = {"Default": {}}
            self.save_profiles()

        # Migrate legacy OSC addresses (strip /avatar/parameters/ prefix)
        # Always runs after load so existing profiles get cleaned up
        self._migrate_osc_addresses()

        # Backfill the global known-toys registry from whatever toys appear
        # in existing profiles, so users upgrading from an older build don't
        # lose their toy list before reconnecting each one.
        self._backfill_known_devices()

    def _backfill_known_devices(self) -> None:
        added = 0
        for profile in self.profiles.values():
            if not isinstance(profile, dict):
                continue
            for name, cfg in profile.items():
                if not isinstance(cfg, dict):
                    continue
                if self.known_devices.register(
                    name,
                    int(cfg.get("motor_count", 1)),
                    cfg.get("motor_kinds"),
                ):
                    added += 1
        if added:
            print(f"[profiles] backfilled {added} toy entries into the global known-devices registry")

    def _migrate_osc_addresses(self) -> None:
        """Normalizes saved OSC addresses: strips /avatar/parameters/ prefix and
        upgrades the old string-per-motor format to a list-per-motor.

        Safe to run multiple times (idempotent).
        """
        prefix = "/avatar/parameters/"
        migrated = False

        def clean(addr: str) -> str:
            if not isinstance(addr, str):
                return ""
            if addr.startswith(prefix):
                return addr[len(prefix):]
            if addr.startswith("/"):
                return addr[1:]
            return addr

        for profile in self.profiles.values():
            for device in profile.values():
                osc_addresses = device.get("osc_addresses", {})
                if isinstance(osc_addresses, dict):
                    for key, val in list(osc_addresses.items()):
                        if isinstance(val, str):
                            cleaned = clean(val)
                            new_list = [cleaned] if cleaned else []
                            osc_addresses[key] = new_list
                            migrated = True
                        elif isinstance(val, list):
                            new_list = [clean(a) for a in val if isinstance(a, str) and a.strip()]
                            if new_list != val:
                                osc_addresses[key] = new_list
                                migrated = True

                # Legacy single osc_address key
                legacy_addr = device.get("osc_address", "")
                if isinstance(legacy_addr, str) and (legacy_addr.startswith(prefix) or legacy_addr.startswith("/")):
                    device["osc_address"] = clean(legacy_addr)
                    migrated = True

        if migrated:
            self.save_profiles()
    
    def load_profiles(self) -> Dict[str, Any]:
        """Load profiles from JSON file or create default if not exists
        
        Returns:
            Dictionary containing all loaded profiles
        """
        return self._load_or_create_default()
    
    def save_profiles(self) -> None:
        """Save current profiles to JSON file."""
        try:
            with open(PROFILE_FILE, 'w') as f:
                json.dump(self.profiles, f, indent=2)
            print(f"Profiles saved to {PROFILE_FILE}")
        except IOError as e:
            print(f"Profile save error: {e}")
    
    def get_profile_config(self, device_name: str, key: str, default=None) -> Optional[Any]:
        """Get a specific config value for a device from current profile
        
        Args:
            device_name: Name of the device
            key: Config key (e.g., 'osc_address', 'motor_index')
            default: Default value if not found
            
        Returns:
            The config value or default
        """
        if self.current_profile in self.profiles:
            profile = self.profiles[self.current_profile]
            if device_name in profile:
                return profile[device_name].get(key, default)
        return default
    
    def update_device_config(self, device_name: str, key: str, value) -> None:
        """Update a config value for a device in current profile
        
        Args:
            device_name: Name of the device
            key: Config key to update
            value: New value
        """
        if self.current_profile not in self.profiles:
            self.profiles[self.current_profile] = {}
        
        if device_name not in self.profiles[self.current_profile]:
            self.profiles[self.current_profile][device_name] = {}
            
        self.profiles[self.current_profile][device_name][key] = value