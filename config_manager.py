# Config Manager - ProfileManager + re-exports of the settings/ package.
#
# The individual settings managers (AppSettingsManager, SteamVRSettingsManager,
# etc.) and their file-path constants live in the `settings/` package. They are
# re-exported here so existing callers `from config_manager import X` keep
# working.

import json
import os
from typing import Any, Dict, Optional

from utilities import atomic_write_json, strip_param_prefix

from settings import (
    APPDATA_DIR,
    APP_SETTINGS_FILE,
    BHAPTICS_SETTINGS_FILE,
    KNOWN_DEVICES_FILE,
    PROFILE_FILE,
    SPS_SOURCES_FILE,
    STEAMVR_SETTINGS_FILE,
    AppSettingsManager,
    BHapticsSettingsManager,
    DEFAULT_APP_SETTINGS,
    KnownDevicesRegistry,
    SpsSourceManager,
    SteamVRSettingsManager,
)


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
        self.sps_sources = SpsSourceManager()
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
        # Recovery path: when known_devices.json is empty (fresh
        # install, deleted cache) but profiles already have device
        # entries, seed known_devices from those entries so the
        # registry isn't empty until each toy reconnects.
        #
        # Defensive: skip entries already present in known_devices.
        # A profile snapshot can hold stale structural facts
        # (motor_count, motor_kinds) when the engine's classification
        # table grew between sessions — overwriting a freshly-
        # classified known_devices entry with stale profile data
        # silently regresses the kind labels. The engine's last
        # report wins; backfill only fills gaps.
        added = 0
        for source in (self.profiles, self.avatar_profiles):
            for profile in source.values():
                if not isinstance(profile, dict):
                    continue
                for name, cfg in profile.items():
                    if not isinstance(cfg, dict):
                        continue
                    if name in self.known_devices.devices:
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
        migrated = False

        for source in (self.profiles, self.avatar_profiles):
            for profile in source.values():
                for device in profile.values():
                    osc_addresses = device.get("osc_addresses", {})
                    if isinstance(osc_addresses, dict):
                        for key, val in list(osc_addresses.items()):
                            if isinstance(val, str):
                                cleaned = strip_param_prefix(val)
                                new_list = [cleaned] if cleaned else []
                                osc_addresses[key] = new_list
                                migrated = True
                            elif isinstance(val, list):
                                new_list = [strip_param_prefix(a) for a in val if isinstance(a, str) and a.strip()]
                                if new_list != val:
                                    osc_addresses[key] = new_list
                                    migrated = True

                    # Legacy single osc_address key
                    legacy_addr = device.get("osc_address", "")
                    if isinstance(legacy_addr, str) and (
                        legacy_addr.startswith("/avatar/parameters/") or legacy_addr.startswith("/")
                    ):
                        device["osc_address"] = strip_param_prefix(legacy_addr)
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
            atomic_write_json(PROFILE_FILE, payload, indent=2)
            print(f"Profiles saved to {PROFILE_FILE}")
        except OSError as e:
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
