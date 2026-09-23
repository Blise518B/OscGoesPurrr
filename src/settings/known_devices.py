"""Global registry of every toy that's ever been connected. Stored outside
profiles so a new/empty profile still shows previously-seen toys."""

import json
import os
from typing import Any, Dict

from utilities import atomic_write_json

from ._paths import KNOWN_DEVICES_FILE


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
            atomic_write_json(KNOWN_DEVICES_FILE, self.devices, indent=2)
        except OSError as e:
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
