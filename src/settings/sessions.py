"""Session-logger preferences: master enable, auto-start, retention."""

import json
import os
from typing import Any, Dict

from utilities import atomic_write_json

from ._paths import SESSIONS_SETTINGS_FILE


class SessionSettingsManager:
    """Persists the session logger's user-facing preferences.

    The values here are read by the controller's session facade — the
    logger engine itself stays primitive in / primitive out and
    doesn't import settings."""

    DEFAULTS: Dict[str, Any] = {
        # Master toggle. Opt-in: a fresh install does not record by
        # default — the user explicitly turns it on from the Sessions
        # tab (matches the SPS-mirror precedent).
        "enabled":    False,
        # When True (and `enabled` is also True), a new session starts
        # automatically on app launch. False means the user clicks
        # Start each time they want to record.
        "auto_start": False,
        # Maximum number of session files kept on disk. On each new
        # session start, anything beyond this count is pruned
        # oldest-first. Default 20 holds roughly a week of "1 session
        # per day" use before rotation.
        "retention":  20,
    }

    _RETENTION_MIN = 1
    _RETENTION_MAX = 1000

    def __init__(self):
        self.settings: Dict[str, Any] = {}
        self._load_or_create_defaults()

    def _load_or_create_defaults(self) -> None:
        if os.path.exists(SESSIONS_SETTINGS_FILE):
            try:
                with open(SESSIONS_SETTINGS_FILE, "r") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        self.settings = {**self.DEFAULTS, **loaded}
                        return
            except (json.JSONDecodeError, IOError) as e:
                print(f"Session settings load error: {e}, using defaults")
        self.settings = dict(self.DEFAULTS)
        self._save()

    def _save(self) -> None:
        try:
            atomic_write_json(SESSIONS_SETTINGS_FILE, self.settings, indent=2)
        except OSError as e:
            print(f"Session settings save error: {e}")

    # ---- enabled (master) ----

    def get_enabled(self) -> bool:
        return bool(self.settings.get("enabled", False))

    def set_enabled(self, value: bool) -> None:
        self.settings["enabled"] = bool(value)
        self._save()

    # ---- auto-start on app launch ----

    def get_auto_start(self) -> bool:
        return bool(self.settings.get("auto_start", False))

    def set_auto_start(self, value: bool) -> None:
        self.settings["auto_start"] = bool(value)
        self._save()

    # ---- retention ----

    def get_retention(self) -> int:
        try:
            v = int(self.settings.get("retention", 20))
        except (TypeError, ValueError):
            return 20
        return max(self._RETENTION_MIN, min(self._RETENTION_MAX, v))

    def set_retention(self, value: int) -> None:
        try:
            v = max(self._RETENTION_MIN, min(self._RETENTION_MAX, int(value)))
        except (TypeError, ValueError):
            v = 20
        self.settings["retention"] = v
        self._save()

    # ---- snapshot for UI ----

    def snapshot(self) -> Dict[str, Any]:
        """Read-only view of all three fields. Used by the UI panel to
        populate its toggles + spinbox in one round-trip."""
        return {
            "enabled":    self.get_enabled(),
            "auto_start": self.get_auto_start(),
            "retention":  self.get_retention(),
        }
