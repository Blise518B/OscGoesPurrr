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

# Default app settings
DEFAULT_APP_SETTINGS = {
    "auto_connect": True,
    "auto_refresh": True,
    "auto_connect_osc": True,
    "bind_all_interfaces": True
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


class ProfileManager:
    """Manages profile loading, saving, and device configuration."""
    
    def __init__(self):
        self.profiles: Dict[str, Any] = {}
        self.current_profile = "Default"
        self.app_settings = AppSettingsManager()
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

    def _migrate_osc_addresses(self) -> None:
        """One-time migration: strip /avatar/parameters/ prefix from all saved OSC addresses.

        Safe to run multiple times (idempotent). Modifies profiles in-place and persists changes.
        """
        prefix = "/avatar/parameters/"
        migrated = False

        for profile in self.profiles.values():
            for device in profile.values():
                # Handle dict-style osc_addresses (e.g. {"0": "/avatar/parameters/...", "1": "..."})
                osc_addresses = device.get("osc_addresses", {})
                if isinstance(osc_addresses, dict):
                    for key in osc_addresses:
                        addr = osc_addresses[key]
                        if isinstance(addr, str) and addr.startswith(prefix):
                            osc_addresses[key] = addr[len(prefix):]
                            migrated = True
                        elif isinstance(addr, str) and addr.startswith("/"):
                            osc_addresses[key] = addr[1:]
                            migrated = True

                # Handle legacy single osc_address key
                legacy_addr = device.get("osc_address", "")
                if isinstance(legacy_addr, str):
                    if legacy_addr.startswith(prefix):
                        device["osc_address"] = legacy_addr[len(prefix):]
                        migrated = True
                    elif legacy_addr.startswith("/"):
                        device["osc_address"] = legacy_addr[1:]
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