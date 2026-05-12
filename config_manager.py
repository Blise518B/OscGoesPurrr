# Config Manager - Profile and Configuration Handling
# Extracted from OscGoesPurrr to separate concerns

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


# AppData directory for persistent storage
APPDATA_DIR = Path.home() / "AppData" / "Roaming" / "OscGoesPurrr"

# Profile file path
PROFILE_FILE = APPDATA_DIR / "profiles.json"

# Ensure AppData directory exists
os.makedirs(APPDATA_DIR, exist_ok=True)


class ProfileManager:
    """Manages profile loading, saving, and device configuration."""
    
    def __init__(self):
        self.profiles: Dict[str, Any] = {}
        self.current_profile = "Default"
        self._load_or_create_default()
    
    def _load_or_create_default(self) -> None:
        """Load profiles from JSON file or create default if not exists."""
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE, 'r') as f:
                    self.profiles = json.load(f)
                    print(f"Loaded profiles from {PROFILE_FILE}")
                    return
            except (json.JSONDecodeError, IOError) as e:
                print(f"Profile load error: {e}, creating default profile")
        
        # Create default profile if file doesn't exist or has errors
        self.profiles = {"Default": {}}
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