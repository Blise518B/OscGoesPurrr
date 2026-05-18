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

# SteamVR settings file path (autostart, vibration patterns, per-tracker config)
STEAMVR_SETTINGS_FILE = APPDATA_DIR / "steamvr_settings.json"

# bHaptics settings file path (Player connection, per-device enable + intensity)
BHAPTICS_SETTINGS_FILE = APPDATA_DIR / "bhaptics_settings.json"

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
    "minimize_to_tray": False,
    # Default ON so the first launch lands on the stripped Simple Mode panel.
    # The user can disable it from the Simple Mode panel or Settings.
    "simple_mode": True
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


class SteamVRSettingsManager:
    """Persists SteamVR Haptics section state: autostart flag, vibration
    pattern configs, no-data timeout, and per-tracker config (keyed by
    tracker serial). Lives outside profiles because SteamVR trackers are
    physical hardware, not avatar-bound state.
    """

    DEFAULTS: Dict[str, Any] = {
        "autostart_with_steamvr": False,
        "auto_connect_steamvr": True,
        "no_data_enabled": True,
        "no_data_timeout_s": 15,
        "battery_poll_interval_s": 5.0,
        "patterns": [
            {"pattern": "Linear",   "str_min": 0,  "str_max": 80, "speed": 4},   # PROXIMITY
            {"pattern": "None",     "str_min": 40, "str_max": 80, "speed": 16},  # VELOCITY
        ],
        "trackers": {},  # serial -> {enabled, address_list, multiplier_override, battery_threshold}
    }

    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._load_or_create_defaults()

    def _load_or_create_defaults(self) -> None:
        if os.path.exists(STEAMVR_SETTINGS_FILE):
            try:
                with open(STEAMVR_SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        merged = {**self.DEFAULTS, **loaded}
                        if "patterns" not in loaded or not isinstance(loaded.get("patterns"), list) \
                                or len(loaded["patterns"]) != 2:
                            merged["patterns"] = self.DEFAULTS["patterns"]
                        if "trackers" not in loaded or not isinstance(loaded.get("trackers"), dict):
                            merged["trackers"] = {}
                        self.settings = merged
                        return
            except (json.JSONDecodeError, IOError) as e:
                print(f"SteamVR settings load error: {e}, using defaults")
        # Deep-copy defaults so callers don't mutate the class attribute
        self.settings = json.loads(json.dumps(self.DEFAULTS))
        self._save()

    def _save(self) -> None:
        try:
            with open(STEAMVR_SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except IOError as e:
            print(f"SteamVR settings save error: {e}")

    # ---- Top-level fields ----
    def get_autostart(self) -> bool:
        return bool(self.settings.get("autostart_with_steamvr", False))

    def set_autostart(self, value: bool) -> None:
        self.settings["autostart_with_steamvr"] = bool(value)
        self._save()

    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect_steamvr", True))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect_steamvr"] = bool(value)
        self._save()

    def get_no_data(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.settings.get("no_data_enabled", True)),
            "timeout_s": int(self.settings.get("no_data_timeout_s", 15)),
        }

    def set_no_data(self, enabled: bool, timeout_s: int) -> None:
        self.settings["no_data_enabled"] = bool(enabled)
        self.settings["no_data_timeout_s"] = int(timeout_s)
        self._save()

    def get_battery_interval(self) -> float:
        try:
            return float(self.settings.get("battery_poll_interval_s", 5.0))
        except (TypeError, ValueError):
            return 5.0

    def set_battery_interval(self, seconds: float) -> None:
        try:
            seconds = max(1.0, float(seconds))
        except (TypeError, ValueError):
            seconds = 5.0
        self.settings["battery_poll_interval_s"] = seconds
        self._save()

    # ---- Pattern configs (2 entries: PROXIMITY, VELOCITY) ----
    def get_patterns(self) -> list:
        return list(self.settings.get("patterns", self.DEFAULTS["patterns"]))

    def set_pattern(self, index: int, pattern_dict: Dict[str, Any]) -> None:
        patterns = list(self.settings.get("patterns", []))
        while len(patterns) <= index:
            patterns.append(dict(self.DEFAULTS["patterns"][len(patterns)]))
        patterns[index] = dict(pattern_dict)
        self.settings["patterns"] = patterns
        self._save()

    # ---- Per-tracker configs ----
    def get_tracker_dict(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.settings.get("trackers", {}))

    def get_tracker(self, serial: str) -> Dict[str, Any]:
        trackers = self.settings.setdefault("trackers", {})
        if serial not in trackers:
            trackers[serial] = {
                "enabled": True,
                "address_list": ["/avatar/parameters/..."],
                "multiplier_override": 1.0,
                "battery_threshold": 20,
                "battery_osc_address": "",
            }
            self._save()
        else:
            # Backfill new fields onto pre-existing entries.
            if "battery_osc_address" not in trackers[serial]:
                trackers[serial]["battery_osc_address"] = ""
                self._save()
        return dict(trackers[serial])

    def set_tracker(self, serial: str, cfg: Dict[str, Any]) -> None:
        trackers = self.settings.setdefault("trackers", {})
        trackers[serial] = dict(cfg)
        self._save()


class BHapticsSettingsManager:
    """Persists bHaptics integration state: Player connection endpoint,
    auto-connect flag, and per-device enable + intensity. Per-device
    defaults match the v1.0.0 bHapticsOSC layout (9 device categories)."""

    _DEFAULT_DEVICES: Dict[str, Dict[str, Any]] = {
        "Head":      {"enabled": True, "intensity": 100},
        "VestFront": {"enabled": True, "intensity": 100},
        "VestBack":  {"enabled": True, "intensity": 100},
        "ForearmL":  {"enabled": True, "intensity": 100},
        "ForearmR":  {"enabled": True, "intensity": 100},
        "HandL":     {"enabled": True, "intensity": 100},
        "HandR":     {"enabled": True, "intensity": 100},
        "FootL":     {"enabled": True, "intensity": 100},
        "FootR":     {"enabled": True, "intensity": 100},
    }

    DEFAULTS: Dict[str, Any] = {
        "auto_connect": True,
        "host": "127.0.0.1",
        "port": 15881,
        # Anti-stuck: when a dot's input value hasn't changed for `hold_s`
        # seconds, linearly ramp it down to 0 over `ramp_s` seconds. Guards
        # against avatars that latch a contact at full strength and never
        # release it (e.g. when the sending controller drops out mid-touch).
        "antistuck_enabled": True,
        "antistuck_hold_s": 2.0,
        "antistuck_ramp_s": 2.0,
        "devices": _DEFAULT_DEVICES,
    }

    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._load_or_create_defaults()

    def _load_or_create_defaults(self) -> None:
        if os.path.exists(BHAPTICS_SETTINGS_FILE):
            try:
                with open(BHAPTICS_SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        merged = {**self.DEFAULTS, **loaded}
                        # Backfill any newly-added devices into older configs.
                        devs = dict(self._DEFAULT_DEVICES)
                        devs.update(loaded.get("devices", {}) or {})
                        merged["devices"] = devs
                        self.settings = merged
                        return
            except (json.JSONDecodeError, IOError) as e:
                print(f"bHaptics settings load error: {e}, using defaults")
        self.settings = json.loads(json.dumps(self.DEFAULTS))
        self._save()

    def _save(self) -> None:
        try:
            with open(BHAPTICS_SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except IOError as e:
            print(f"bHaptics settings save error: {e}")

    # ---- Endpoint ----
    def get_host(self) -> str:
        return str(self.settings.get("host", "127.0.0.1"))

    def get_port(self) -> int:
        try:
            return int(self.settings.get("port", 15881))
        except (TypeError, ValueError):
            return 15881

    def set_endpoint(self, host: str, port: int) -> None:
        self.settings["host"] = str(host or "127.0.0.1").strip()
        try:
            self.settings["port"] = int(port)
        except (TypeError, ValueError):
            self.settings["port"] = 15881
        self._save()

    # ---- Auto-connect ----
    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", True))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    # ---- Anti-stuck ----
    def get_antistuck(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.settings.get("antistuck_enabled", True)),
            "hold_s": float(self.settings.get("antistuck_hold_s", 2.0)),
            "ramp_s": float(self.settings.get("antistuck_ramp_s", 2.0)),
        }

    def set_antistuck(self, enabled: bool, hold_s: float, ramp_s: float) -> None:
        self.settings["antistuck_enabled"] = bool(enabled)
        try:
            self.settings["antistuck_hold_s"] = max(0.1, float(hold_s))
        except (TypeError, ValueError):
            self.settings["antistuck_hold_s"] = 2.0
        try:
            self.settings["antistuck_ramp_s"] = max(0.1, float(ramp_s))
        except (TypeError, ValueError):
            self.settings["antistuck_ramp_s"] = 2.0
        self._save()

    # ---- Devices ----
    def get_devices(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.settings.get("devices", {}))

    def get_device(self, position: str) -> Dict[str, Any]:
        devs = self.settings.setdefault("devices", {})
        if position not in devs:
            devs[position] = dict(self._DEFAULT_DEVICES.get(position, {"enabled": True, "intensity": 100}))
            self._save()
        return dict(devs[position])

    def set_device(self, position: str, cfg: Dict[str, Any]) -> None:
        devs = self.settings.setdefault("devices", {})
        devs[position] = dict(cfg)
        self._save()


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
    """Manages profile loading, saving, and device configuration.

    Profiles come in two flavors:
      * Global profiles (`profiles`) — manually selected via the Dashboard.
      * Avatar profiles (`avatar_profiles`) — bound to a specific VRChat
        avatar ID. When VRChat reports an avatar change via /avatar/change
        and the new ID is bound, that avatar profile becomes the *active*
        profile until the user switches avatars again.

    Get/set methods (`get_profile_config`, `update_device_config`) operate
    on the *active* profile so the controller and router transparently
    follow the auto-switch without needing to know which flavor is live.
    """

    SCHEMA_VERSION = 2

    def __init__(self):
        self.profiles: Dict[str, Any] = {}
        self.avatar_profiles: Dict[str, Any] = {}
        # profile_name -> avtr_xxxx id. Many profiles may bind to the same
        # avatar id; `avatar_active` picks which of them is the one that
        # actually drives haptics when that avatar loads.
        self.avatar_bindings: Dict[str, str] = {}
        # avtr_xxxx id -> profile_name (the user's preferred profile for that
        # avatar). When unset for an avatar id, the first binding match wins.
        self.avatar_active: Dict[str, str] = {}
        self.current_profile = "Default"
        # Transient: latest avatar id reported by VRChat /avatar/change. Not persisted.
        self.current_avatar_id: Optional[str] = None
        # Persisted per-avatar memory of the user's last profile choice:
        #   {avatar_id: {"kind": "avatar"|"global", "name": profile_name}}
        # When the avatar loads, the resolver applies this choice. Updated
        # every time the user clicks a profile while that avatar is loaded.
        self.avatar_last_choice: Dict[str, Dict[str, str]] = {}
        # In-memory clipboard for copy/paste between profile sections.
        # Stored as {"name": str, "config": dict} or None.
        self._clipboard: Optional[Dict[str, Any]] = None

        self.app_settings = AppSettingsManager()
        self.steamvr_settings = SteamVRSettingsManager()
        self.bhaptics_settings = BHapticsSettingsManager()
        self.known_devices = KnownDevicesRegistry()
        self._load_or_create_default()

    # ------------------------------------------------------------------
    # Load / save with schema migration
    # ------------------------------------------------------------------

    def _load_or_create_default(self) -> None:
        """Load profiles from JSON file or create default if not exists."""
        raw: Any = None
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE, 'r') as f:
                    raw = json.load(f)
                    print(f"Loaded profiles from {PROFILE_FILE}")
            except (json.JSONDecodeError, IOError) as e:
                print(f"Profile load error: {e}, creating default profile")
                raw = None

        if not isinstance(raw, dict):
            # Brand-new install (or unreadable file): start fresh.
            self.profiles = {"Default": {}}
            self.avatar_profiles = {}
            self.avatar_bindings = {}
            self.save_profiles()
        elif raw.get("schema") == self.SCHEMA_VERSION:
            # New format
            self.profiles = raw.get("global_profiles", {}) or {}
            self.avatar_profiles = raw.get("avatar_profiles", {}) or {}
            self.avatar_bindings = raw.get("avatar_bindings", {}) or {}
            self.avatar_last_choice = raw.get("avatar_last_choice", {}) or {}
            # Backwards compat: prior schema stored `avatar_active[id]=name`
            # (avatar-only). Promote those into last_choice entries.
            legacy_active = raw.get("avatar_active", {}) or {}
            for avtr, name in legacy_active.items():
                self.avatar_last_choice.setdefault(
                    avtr, {"kind": "avatar", "name": name}
                )
            if not self.profiles:
                self.profiles = {"Default": {}}
        else:
            # Legacy format: top-level dict is {profile_name: {device: settings}}.
            # Promote it to the new schema in place and re-save so the migration
            # is one-shot.
            self.profiles = raw
            self.avatar_profiles = {}
            self.avatar_bindings = {}
            self.avatar_last_choice = {}
            print("[profiles] migrating profiles.json to schema v2 (added avatar profiles)")
            self.save_profiles()

        # Backfill last_choice from one-to-one bindings so existing avatars
        # remember their previously-bound profile even after a fresh install.
        for name, avtr in self.avatar_bindings.items():
            self.avatar_last_choice.setdefault(
                avtr, {"kind": "avatar", "name": name}
            )

        # Migrate legacy OSC addresses (strip /avatar/parameters/ prefix)
        # Always runs after load so existing profiles get cleaned up
        self._migrate_osc_addresses()

        # Backfill the global known-toys registry from whatever toys appear
        # in existing profiles, so users upgrading from an older build don't
        # lose their toy list before reconnecting each one.
        self._backfill_known_devices()

    def _backfill_known_devices(self) -> None:
        added = 0
        for source in (self.profiles, self.avatar_profiles):
            for profile in source.values():
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

        for source in (self.profiles, self.avatar_profiles):
            for profile in source.values():
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
        """Save current profiles to JSON file in the v2 schema."""
        payload = {
            "schema": self.SCHEMA_VERSION,
            "global_profiles": self.profiles,
            "avatar_profiles": self.avatar_profiles,
            "avatar_bindings": self.avatar_bindings,
            "avatar_last_choice": self.avatar_last_choice,
        }
        try:
            with open(PROFILE_FILE, 'w') as f:
                json.dump(payload, f, indent=2)
            print(f"Profiles saved to {PROFILE_FILE}")
        except IOError as e:
            print(f"Profile save error: {e}")

    # ------------------------------------------------------------------
    # Active-profile resolution (avatar binding takes precedence)
    # ------------------------------------------------------------------

    DEFAULT_FALLBACK_PROFILE = "Default"

    def get_active_profile_info(self) -> Dict[str, str]:
        """Returns metadata about the currently-active profile:
            {"kind": "avatar"|"global", "name": str}

        Resolution order:
          1. If we have a current avatar id with a remembered last choice
             that's still valid (the profile exists; for an avatar choice,
             still bound to this avatar), apply it.
          2. Otherwise, if any avatar profile is bound to this avatar,
             activate the first such binding (legacy fallback).
          3. Otherwise default to the global "Default" profile when it
             exists, else the selected global profile.
        """
        avtr = self.current_avatar_id
        if avtr:
            choice = self.avatar_last_choice.get(avtr)
            if choice:
                kind = choice.get("kind")
                name = choice.get("name", "")
                if kind == "avatar" and name in self.avatar_profiles \
                        and self.avatar_bindings.get(name) == avtr:
                    return {"kind": "avatar", "name": name}
                if kind == "global" and name in self.profiles:
                    return {"kind": "global", "name": name}
                # Stale entry — fall through and pick something sensible.
            for n, bound in self.avatar_bindings.items():
                if bound == avtr and n in self.avatar_profiles:
                    return {"kind": "avatar", "name": n}
            if self.DEFAULT_FALLBACK_PROFILE in self.profiles:
                return {"kind": "global", "name": self.DEFAULT_FALLBACK_PROFILE}
        return {"kind": "global", "name": self.current_profile}

    def record_choice(self, kind: str, name: str) -> None:
        """Persist `(kind, name)` as the user's choice for the current avatar.
        No-op when no avatar is currently loaded."""
        if not self.current_avatar_id:
            return
        self.avatar_last_choice[self.current_avatar_id] = {
            "kind": kind,
            "name": name,
        }
        self.save_profiles()

    def get_active_profile_dict(self) -> Dict[str, Any]:
        """Return the actual settings dict the router/UI should read & write."""
        info = self.get_active_profile_info()
        if info["kind"] == "avatar":
            return self.avatar_profiles.setdefault(info["name"], {})
        return self.profiles.setdefault(info["name"], {})

    def get_bound_avatar_profile(self, avatar_id: Optional[str]) -> Optional[str]:
        """Return the avatar-profile name currently active for `avatar_id`,
        or None. Delegates to `get_active_profile_info` so callers see the
        same resolution as the rest of the app."""
        if not avatar_id:
            return None
        # Temporarily swap current_avatar_id so the resolver runs against the
        # caller's id (lets external callers query arbitrary avatars).
        prev = self.current_avatar_id
        self.current_avatar_id = avatar_id
        try:
            info = self.get_active_profile_info()
        finally:
            self.current_avatar_id = prev
        return info["name"] if info["kind"] == "avatar" else None

    def get_profiles_for_avatar(self, avatar_id: Optional[str]) -> list:
        """All avatar-profile names bound to `avatar_id` (insertion order)."""
        if not avatar_id:
            return []
        return [
            n for n, bound in self.avatar_bindings.items()
            if bound == avatar_id and n in self.avatar_profiles
        ]

    def set_current_avatar(self, avatar_id: Optional[str]) -> Optional[str]:
        """Update `current_avatar_id`. Returns the bound avatar-profile name
        if the resolver would activate one for this avatar, else None.

        No transient flags to clear — `avatar_last_choice` is the single
        source of truth for "what should be active when this avatar loads".
        """
        self.current_avatar_id = (avatar_id or None)
        return self.get_bound_avatar_profile(self.current_avatar_id)

    # ------------------------------------------------------------------
    # Device-config get/set (route through the active profile)
    # ------------------------------------------------------------------

    def get_profile_config(self, device_name: str, key: str, default=None) -> Optional[Any]:
        """Get a specific config value for a device from the active profile."""
        profile = self.get_active_profile_dict()
        if device_name in profile:
            return profile[device_name].get(key, default)
        return default

    def update_device_config(self, device_name: str, key: str, value) -> None:
        """Update a config value for a device in the active profile."""
        profile = self.get_active_profile_dict()
        if device_name not in profile:
            profile[device_name] = {}
        profile[device_name][key] = value

    # ------------------------------------------------------------------
    # Avatar-profile CRUD + binding
    # ------------------------------------------------------------------

    def create_avatar_profile(self, base_name: str, avatar_id: Optional[str],
                              copy_from: Optional[Dict[str, Any]] = None) -> str:
        """Create a new avatar profile and bind it to `avatar_id` (when given).

        Multiple profiles may bind to the same avatar id — the new profile
        becomes the *active* pick for that avatar without removing any other
        bindings, so prior profiles for the same avatar remain visible and
        switchable.
        """
        name = self._unique_name(base_name, set(self.avatar_profiles.keys()))
        self.avatar_profiles[name] = _deep_copy_profile(copy_from) if copy_from else {}
        if avatar_id:
            self.avatar_bindings[name] = avatar_id
            # Make the new profile the remembered choice for this avatar.
            self.avatar_last_choice[avatar_id] = {"kind": "avatar", "name": name}
        self.save_profiles()
        return name

    def delete_avatar_profile(self, name: str) -> None:
        self.avatar_profiles.pop(name, None)
        bound_id = self.avatar_bindings.pop(name, None)
        # Drop any remembered choice that pointed at this profile, regardless
        # of which avatar it was bound to.
        for avtr, choice in list(self.avatar_last_choice.items()):
            if choice.get("kind") == "avatar" and choice.get("name") == name:
                del self.avatar_last_choice[avtr]
        self.save_profiles()

    def rename_avatar_profile(self, old: str, new: str) -> bool:
        new = (new or "").strip()
        if not new or old not in self.avatar_profiles:
            return False
        if new in self.avatar_profiles and new != old:
            return False
        self.avatar_profiles[new] = self.avatar_profiles.pop(old)
        if old in self.avatar_bindings:
            self.avatar_bindings[new] = self.avatar_bindings.pop(old)
        # Update last_choice entries that referenced the old name.
        for avtr, choice in self.avatar_last_choice.items():
            if choice.get("kind") == "avatar" and choice.get("name") == old:
                choice["name"] = new
        self.save_profiles()
        return True

    def bind_avatar_profile(self, name: str, avatar_id: Optional[str]) -> None:
        """Bind `name` to `avatar_id` (or unbind when `avatar_id` is falsy).

        When binding, also records the profile as the remembered choice for
        that avatar. Other profiles bound to the same avatar are left intact
        so the user can switch back.
        """
        if name not in self.avatar_profiles:
            return
        if not avatar_id:
            self.avatar_bindings.pop(name, None)
            for avtr, choice in list(self.avatar_last_choice.items()):
                if choice.get("kind") == "avatar" and choice.get("name") == name:
                    del self.avatar_last_choice[avtr]
        else:
            self.avatar_bindings[name] = avatar_id
            self.avatar_last_choice[avatar_id] = {"kind": "avatar", "name": name}
        self.save_profiles()

    # ------------------------------------------------------------------
    # Clipboard (copy / paste between profiles)
    # ------------------------------------------------------------------

    def copy_profile_to_clipboard(self, kind: str, name: str) -> bool:
        """Capture a deep copy of the named profile into the clipboard.
        `kind` is "global" or "avatar". Returns True on success."""
        src = self.profiles if kind == "global" else self.avatar_profiles
        if name not in src:
            return False
        self._clipboard = {
            "kind": kind,
            "name": name,
            "config": _deep_copy_profile(src[name]),
        }
        return True

    def has_clipboard(self) -> bool:
        return self._clipboard is not None

    def get_clipboard_source_name(self) -> Optional[str]:
        return self._clipboard.get("name") if self._clipboard else None

    def get_clipboard_source_kind(self) -> Optional[str]:
        return self._clipboard.get("kind") if self._clipboard else None

    def paste_into_profile(self, target_kind: str, target_name: str) -> bool:
        """Overwrite an existing profile's contents with the clipboard.

        Preserves the target profile's name (and, for avatar profiles, its
        binding). Returns True on success, False if the clipboard is empty
        or the target doesn't exist.
        """
        if self._clipboard is None:
            return False
        src = self.profiles if target_kind == "global" else self.avatar_profiles
        if target_name not in src:
            return False
        src[target_name] = _deep_copy_profile(self._clipboard["config"])
        self.save_profiles()
        return True

    def clear_clipboard(self) -> None:
        self._clipboard = None

    def paste_profile(self, target_kind: str,
                      avatar_id: Optional[str] = None) -> Optional[str]:
        """Create a new profile in the target section from the clipboard.
        `target_kind` is "global" or "avatar". If avatar, `avatar_id` may
        be supplied to immediately bind the new profile. Returns the new
        profile name, or None if the clipboard is empty."""
        if self._clipboard is None:
            return None
        base = f"{self._clipboard['name']} (paste)"
        config = _deep_copy_profile(self._clipboard["config"])
        if target_kind == "avatar":
            name = self._unique_name(base, set(self.avatar_profiles.keys()))
            self.avatar_profiles[name] = config
            if avatar_id:
                self.bind_avatar_profile(name, avatar_id)
            else:
                self.save_profiles()
            return name
        else:
            name = self._unique_name(base, set(self.profiles.keys()))
            self.profiles[name] = config
            self.save_profiles()
            return name

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unique_name(base: str, taken: set) -> str:
        if base not in taken:
            return base
        i = 2
        while f"{base} {i}" in taken:
            i += 1
        return f"{base} {i}"


def _deep_copy_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-copy a profile-shaped dict using JSON round-trip (profiles only
    contain JSON-safe values, so this is correct and avoids importing copy)."""
    try:
        return json.loads(json.dumps(profile))
    except (TypeError, ValueError):
        # Fallback: shallow copy if something weird is in there.
        return dict(profile)