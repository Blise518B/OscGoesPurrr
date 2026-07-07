"""Regression tests for the settings-loader hardening.

The pattern under test: SETTERS always clamped, but LOADERS trusted the
file — so a hand-edited or corrupted JSON could crash app boot (bare int()
in a getter feeding engine config), kill a router tick (unvalidated nested
entry), or be silently clobbered with defaults (losing the user's tuning).

Every manager points FILE_PATH at tmp_path — nothing touches real AppData.
"""

import json

import pytest

from settings._base import JsonSettingsManager
from settings.bhaptics import BHapticsSettingsManager
from settings.coyote import CoyoteSettingsManager
from settings.pishock import PiShockSettingsManager
from settings.steamvr import SteamVRSettingsManager


def _sub(base_cls, tmp_path, name):
    return type(name, (base_cls,), {"FILE_PATH": tmp_path / f"{name}.json"})


# ---------------------------------------------------------------- base


class TestBaseRecovery:
    def test_corrupt_json_is_backed_up_not_destroyed(self, tmp_path):
        cls = _sub(JsonSettingsManager, tmp_path, "CorruptMgr")
        cls.DEFAULTS = {"a": 1}
        path = cls.FILE_PATH
        path.write_text('{"a": 1,,,}')          # trailing-comma hand-edit
        m = cls()
        assert m.settings == {"a": 1}           # running on defaults
        backup = path.with_name(path.name + ".bak")
        assert backup.exists()                  # user's data preserved
        assert backup.read_text() == '{"a": 1,,,}'

    def test_raising_post_load_degrades_to_defaults_not_boot_crash(self, tmp_path):
        # A structurally-malformed (but valid-JSON) file used to propagate
        # a TypeError out of the manager constructor -> app boot loop.
        def bad_post_load(self, loaded):
            raise TypeError("devices is an int")

        cls = _sub(JsonSettingsManager, tmp_path, "PostLoadMgr")
        cls.DEFAULTS = {"a": 1}
        cls._post_load = bad_post_load
        cls.FILE_PATH.write_text(json.dumps({"a": 5, "devices": 3}))
        m = cls()                                # must not raise
        assert m.settings == {"a": 1}

    def test_non_dict_json_backed_up(self, tmp_path):
        cls = _sub(JsonSettingsManager, tmp_path, "ListMgr")
        cls.DEFAULTS = {"a": 1}
        cls.FILE_PATH.write_text(json.dumps([1, 2, 3]))
        m = cls()
        assert m.settings == {"a": 1}
        assert cls.FILE_PATH.with_name(cls.FILE_PATH.name + ".bak").exists()

    def test_degraded_load_backs_up_healthy_file_before_first_save(self, tmp_path):
        # A transient READ failure at boot runs the session on defaults;
        # the first later save (a settings edit, the quit-time save) must
        # preserve the possibly-healthy on-disk file before overwriting it
        # with the defaults-based state.
        cls = _sub(JsonSettingsManager, tmp_path, "DegMgr")
        cls.DEFAULTS = {"a": 1}
        cls.FILE_PATH.write_text(json.dumps({"a": 42}))
        m = cls()                          # healthy load
        m._degraded_load = True            # simulate boot-time read failure
        m.set("a", 2)                      # first save while degraded
        backup = cls.FILE_PATH.with_name(cls.FILE_PATH.name + ".bak")
        assert json.loads(backup.read_text()) == {"a": 42}   # preserved
        assert json.loads(cls.FILE_PATH.read_text())["a"] == 2
        m.set("a", 3)                      # later saves don't re-backup
        assert json.loads(backup.read_text()) == {"a": 42}


# ---------------------------------------------------------------- pishock


class TestPiShockTolerantGetters:
    def _mgr(self, tmp_path, payload=None):
        cls = _sub(PiShockSettingsManager, tmp_path, "PS")
        if payload is not None:
            cls.FILE_PATH.write_text(json.dumps(payload))
        return cls()

    def test_null_and_garbage_caps_do_not_crash_boot(self, tmp_path):
        # get_engine_config() runs at startup (before the UI exists); a
        # hand-edited "max_intensity": null used to TypeError there.
        m = self._mgr(tmp_path, {"max_intensity": None,
                                 "max_duration_ms": "300ms",
                                 "min_interval_s": "fast"})
        caps = m.get_caps()
        assert caps == {"max_intensity": 30, "max_duration_ms": 1000,
                        "min_interval_s": 1.0}
        cfg = m.get_engine_config()              # must not raise
        assert cfg["max_intensity"] == 30

    def test_out_of_range_caps_clamped_on_read(self, tmp_path):
        m = self._mgr(tmp_path, {"max_intensity": 9999,
                                 "max_duration_ms": -5,
                                 "min_interval_s": 0.01})
        caps = m.get_caps()
        assert caps["max_intensity"] == 100      # absolute ceiling
        assert caps["max_duration_ms"] == 1      # floor
        assert caps["min_interval_s"] == 0.3     # safety floor

    def test_global_rate_tolerant(self, tmp_path):
        m = self._mgr(tmp_path, {"rate_max_events": None,
                                 "rate_window_s": float("nan")})
        rate = m.get_global_rate()
        assert rate == {"max_events": 6, "window_s": 10.0}


# ---------------------------------------------------------------- coyote


class TestCoyoteLimits:
    def test_null_limit_defaults_and_hand_edited_9999_clamps(self, tmp_path):
        cls = _sub(CoyoteSettingsManager, tmp_path, "Coy")
        cls.FILE_PATH.write_text(json.dumps({"limit_a": None, "limit_b": 9999}))
        m = cls()
        lim = m.get_limits()                     # used to TypeError at connect
        assert lim == {"limit_a": 100, "limit_b": 200}


# ---------------------------------------------------------------- steamvr


class TestSteamVRCleaning:
    def _mgr(self, tmp_path, payload):
        cls = _sub(SteamVRSettingsManager, tmp_path, "SVR")
        cls.FILE_PATH.write_text(json.dumps(payload))
        return cls()

    def test_null_tracker_entry_cleaned_not_thread_killing(self, tmp_path):
        m = self._mgr(tmp_path, {"trackers": {"LHR-123": None}})
        cfg = m.get_tracker("LHR-123")           # used to TypeError
        assert cfg["enabled"] is True
        assert cfg["multiplier_override"] == 1.0

    def test_garbage_multiplier_coerced(self, tmp_path):
        m = self._mgr(tmp_path, {"trackers": {"LHR-1": {"multiplier_override": "x"}}})
        assert m.get_tracker("LHR-1")["multiplier_override"] == 1.0

    def test_get_tracker_unknown_serial_is_read_only(self, tmp_path):
        # This getter runs on the feedback threads every tick — it must
        # not persist entries (a disk write from a reader thread).
        m = self._mgr(tmp_path, {"trackers": {}})
        before = m.FILE_PATH.read_text()
        cfg = m.get_tracker("LHR-NEW")
        assert cfg["enabled"] is True
        assert "LHR-NEW" not in m.settings["trackers"]
        assert m.FILE_PATH.read_text() == before

    def test_truncated_patterns_repair_preserves_surviving_slot(self, tmp_path):
        # The old all-or-nothing length check wiped BOTH tuned patterns
        # when the list wasn't exactly 2 entries long.
        defaults = SteamVRSettingsManager.DEFAULTS["patterns"]
        key = next(k for k, v in defaults[0].items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool))
        tuned = {**defaults[0], key: 37}
        m = self._mgr(tmp_path, {"patterns": [tuned]})   # truncated to 1
        patterns = m.get_patterns()
        assert len(patterns) == 2
        assert patterns[0][key] == 37                    # survivor kept
        assert patterns[1] == defaults[1]                # missing slot default

    def test_extra_pattern_slot_ignored_without_wiping(self, tmp_path):
        defaults = SteamVRSettingsManager.DEFAULTS["patterns"]
        m = self._mgr(tmp_path, {"patterns": [defaults[0], defaults[1], {"future": 1}]})
        assert len(m.get_patterns()) == 2

    def test_garbage_pattern_field_coerced_to_default(self, tmp_path):
        defaults = SteamVRSettingsManager.DEFAULTS["patterns"]
        key = next(k for k, v in defaults[0].items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool))
        bad = {**defaults[0], key: "not a number"}
        m = self._mgr(tmp_path, {"patterns": [bad, defaults[1]]})
        assert m.get_patterns()[0][key] == defaults[0][key]


# ---------------------------------------------------------------- bhaptics


class TestBHapticsDeviceCleaning:
    def _mgr(self, tmp_path, payload):
        cls = _sub(BHapticsSettingsManager, tmp_path, "BH")
        cls.FILE_PATH.write_text(json.dumps(payload))
        return cls()

    def test_null_entry_and_garbage_intensity_cleaned(self, tmp_path):
        # One bad entry used to kill ALL bHaptics output: from_dict raised
        # inside the router's 60 Hz tick, every tick.
        m = self._mgr(tmp_path, {"devices": {"Head": None,
                                             "VestFront": {"intensity": "abc"}}})
        devs = m.settings["devices"]
        assert devs["Head"] == {"enabled": True, "intensity": 100}
        assert devs["VestFront"]["intensity"] == 100

    def test_intensity_clamped(self, tmp_path):
        m = self._mgr(tmp_path, {"devices": {"Head": {"intensity": 999}}})
        assert m.settings["devices"]["Head"]["intensity"] == 100

    def test_unknown_position_preserved(self, tmp_path):
        # Forward-compat: a newer build's extra position must survive the
        # round-trip instead of being dropped on the next save.
        m = self._mgr(tmp_path, {"devices": {"Tail": {"enabled": False,
                                                      "intensity": 40}}})
        assert m.settings["devices"]["Tail"]["enabled"] is False
        assert m.settings["devices"]["Tail"]["intensity"] == 40
