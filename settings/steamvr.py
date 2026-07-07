"""SteamVR Haptics section state: autostart, vibration patterns,
no-data timeout, and per-tracker config keyed by tracker serial."""

import json
from typing import Any, Dict

from utilities import strip_param_prefix

from ._base import JsonSettingsManager
from ._paths import STEAMVR_SETTINGS_FILE


class SteamVRSettingsManager(JsonSettingsManager):
    """Persists SteamVR Haptics section state: autostart flag, vibration
    pattern configs, no-data timeout, and per-tracker config (keyed by
    tracker serial). Lives outside profiles because SteamVR trackers are
    physical hardware, not avatar-bound state.
    """

    FILE_PATH = STEAMVR_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        "autostart_with_steamvr": False,
        "auto_connect_steamvr": True,
        # Joke / vanity feature: register a virtual OpenVR driver so the
        # user's connected toys show up alongside the HMD/controllers in
        # SteamVR's device strip. Off by default — opt-in from Settings.
        "show_toys_in_steamvr": False,
        "no_data_enabled": True,
        # Two-timer anti-stuck (ported from VRC-Haptic-Pancake): mid-range
        # values are cleared faster than saturated (==1.0) ones, since a
        # legitimate full-contact hold is more common than a stuck mid value.
        "no_data_timeout_active_s": 7,
        "no_data_timeout_peaked_s": 15,
        "battery_poll_interval_s": 5.0,
        "patterns": [
            {"pattern": "Linear",   "str_min": 0,  "str_max": 80, "speed": 4},   # PROXIMITY
            {"pattern": "None",     "str_min": 40, "str_max": 80, "speed": 16},  # VELOCITY
        ],
        "trackers": {},  # serial -> {enabled, address_list, multiplier_override, battery_threshold}
    }

    def _migrate_tracker_addresses(self) -> bool:
        """Strip any legacy `/avatar/parameters/` prefixes from saved tracker
        address lists and battery-out addresses. Returns True if anything
        changed so the caller can re-save."""
        changed = False
        trackers = self.settings.get("trackers") or {}
        for cfg in trackers.values():
            if not isinstance(cfg, dict):
                continue
            addrs = cfg.get("address_list")
            if isinstance(addrs, list):
                new_addrs = []
                for a in addrs:
                    if not isinstance(a, str):
                        continue
                    bare = strip_param_prefix(a)
                    new_addrs.append(bare if bare else "...")
                if new_addrs != addrs:
                    cfg["address_list"] = new_addrs
                    changed = True
            bat = cfg.get("battery_osc_address")
            if isinstance(bat, str):
                bare = strip_param_prefix(bat)
                if bare != bat:
                    cfg["battery_osc_address"] = bare
                    changed = True
        return changed

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        # Patterns: per-SLOT repair instead of all-or-nothing. The old
        # length-!=-2 check wiped BOTH tuned pattern configs when a future
        # build appended a third entry or a truncation dropped one — and
        # never type-checked the elements it kept. Each slot merges over
        # its default with numeric fields coerced, extra slots ignored.
        defaults = json.loads(json.dumps(self.DEFAULTS["patterns"]))
        raw_patterns = loaded.get("patterns")
        raw_patterns = raw_patterns if isinstance(raw_patterns, list) else []
        repaired = []
        for i, default_slot in enumerate(defaults):
            slot = raw_patterns[i] if i < len(raw_patterns) else None
            merged = {**default_slot, **slot} if isinstance(slot, dict) \
                else dict(default_slot)
            for k, dv in default_slot.items():
                if isinstance(dv, bool):
                    merged[k] = bool(merged.get(k, dv))
                elif isinstance(dv, (int, float)):
                    try:
                        fv = float(merged.get(k, dv))
                        if fv != fv:  # NaN
                            raise ValueError
                        merged[k] = type(dv)(fv)
                    except (TypeError, ValueError):
                        merged[k] = dv
            repaired.append(merged)
        self.settings["patterns"] = repaired

        # Trackers: per-entry validation — a null / garbage entry used to
        # survive load and then raise inside that tracker's feedback
        # thread (TrackerConfig.from_dict), silently killing its haptics.
        raw_trackers = loaded.get("trackers")
        raw_trackers = raw_trackers if isinstance(raw_trackers, dict) else {}
        self.settings["trackers"] = {
            str(serial): self._clean_tracker(cfg)
            for serial, cfg in raw_trackers.items()
        }
        # One-shot migration: older configs stored full
        # `/avatar/parameters/MyParam` paths. The router and UI both speak in
        # bare names now, so strip the prefix at load time and persist the
        # cleaned form.
        if self._migrate_tracker_addresses():
            self._save()

    _TRACKER_DEFAULTS: Dict[str, Any] = {
        "enabled": True,
        "address_list": ["..."],
        "multiplier_override": 1.0,
        "battery_threshold": 20,
        "battery_osc_address": "",
    }

    @classmethod
    def _clean_tracker(cls, cfg: Any) -> Dict[str, Any]:
        """Merge an entry over the defaults with coerced/clamped fields.
        Unknown extra keys inside the entry are preserved."""
        out = dict(cfg) if isinstance(cfg, dict) else {}
        merged = {**json.loads(json.dumps(cls._TRACKER_DEFAULTS)), **out}
        merged["enabled"] = bool(merged.get("enabled", True))
        addrs = merged.get("address_list")
        if isinstance(addrs, list):
            merged["address_list"] = \
                [str(a) for a in addrs if isinstance(a, str)] or ["..."]
        else:
            merged["address_list"] = ["..."]
        try:
            f = float(merged.get("multiplier_override", 1.0))
            merged["multiplier_override"] = f if f == f else 1.0
        except (TypeError, ValueError):
            merged["multiplier_override"] = 1.0
        try:
            merged["battery_threshold"] = max(
                0, min(100, int(merged.get("battery_threshold", 20))))
        except (TypeError, ValueError):
            merged["battery_threshold"] = 20
        merged["battery_osc_address"] = str(
            merged.get("battery_osc_address") or "")
        return merged

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

    def get_show_toys(self) -> bool:
        return bool(self.settings.get("show_toys_in_steamvr", False))

    def set_show_toys(self, value: bool) -> None:
        self.settings["show_toys_in_steamvr"] = bool(value)
        self._save()

    def get_no_data(self) -> Dict[str, Any]:
        # Backward-compat: older configs only stored `no_data_timeout_s`. Use
        # it as the peaked timeout (the original semantics) and derive a
        # reasonable active timeout if nothing newer is set. Coercion is
        # tolerant — this getter runs on every feedback-thread tick (the
        # anti-stuck fuse), and a hand-edited value must not kill it.
        def _int(value, default):
            try:
                return max(1, int(value))
            except (TypeError, ValueError):
                return default

        legacy = self.settings.get("no_data_timeout_s")
        peaked = _int(self.settings.get(
            "no_data_timeout_peaked_s",
            legacy if legacy is not None else 15), 15)
        active = _int(self.settings.get(
            "no_data_timeout_active_s", max(1, int(peaked * 7 / 15))),
            max(1, int(peaked * 7 / 15)))
        return {
            "enabled": bool(self.settings.get("no_data_enabled", True)),
            "timeout_active_s": active,
            "timeout_peaked_s": peaked,
            # Keep the legacy key in the response so any old consumer that
            # reads `timeout_s` keeps working (we use the peaked value).
            "timeout_s": peaked,
        }

    def set_no_data(self, enabled: bool, timeout_active_s: int,
                    timeout_peaked_s: int) -> None:
        self.settings["no_data_enabled"] = bool(enabled)
        self.settings["no_data_timeout_active_s"] = int(timeout_active_s)
        self.settings["no_data_timeout_peaked_s"] = int(timeout_peaked_s)
        # Mirror to the legacy key so a downgrade still finds a sane value.
        self.settings["no_data_timeout_s"] = int(timeout_peaked_s)
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
        """READ-ONLY: this getter runs on every per-tracker feedback-thread
        tick (via the engine's config provider), so it must never mutate
        settings or write to disk from those threads. Unknown serials get a
        clean default copy; the entry is persisted by the first
        set_tracker() from the UI. (_post_load already backfilled fields
        on every stored entry.)"""
        trackers = self.settings.get("trackers")
        if not isinstance(trackers, dict):
            return self._clean_tracker({})
        cfg = trackers.get(serial)
        if not isinstance(cfg, dict):
            return self._clean_tracker({})
        return dict(cfg)

    def set_tracker(self, serial: str, cfg: Dict[str, Any]) -> None:
        # Defensive normalisation: addresses are always stored as bare
        # parameter names (no /avatar/parameters/ prefix). The UI strips
        # too, but a stale caller pasting a full path here shouldn't
        # poison the on-disk state.
        clean = dict(cfg)
        addrs = clean.get("address_list")
        if isinstance(addrs, list):
            clean["address_list"] = [
                strip_param_prefix(a) or "..."
                for a in addrs if isinstance(a, str)
            ] or ["..."]
        bat = clean.get("battery_osc_address")
        if isinstance(bat, str):
            clean["battery_osc_address"] = strip_param_prefix(bat)
        trackers = self.settings.setdefault("trackers", {})
        trackers[serial] = clean
        self._save()
