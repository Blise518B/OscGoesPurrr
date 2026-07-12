"""Tests for the six-mode core in config_manager.py: schema v3 load/save,
the v1/v2 → v3 migration (user tuning must land unchanged in the Custom
slot, with a backup on disk), the identity-stability contract the router's
compile cache relies on, and the master-scale clamps.

ModeManager normally composes the real settings managers (which read/write
the live AppData files), so every test swaps them for stubs and points
PROFILE_FILE at tmp_path before construction."""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config_manager
from config_manager import ModeManager, preset_motor_mix
from motor_router import MotorRouter


class _StubSettings:
    def __init__(self, *a, **kw):
        self.settings = {}

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value


class _StubKnownDevices:
    def __init__(self, *a, **kw):
        self.devices = {}

    def register(self, name, motor_count, motor_kinds=None):
        if name in self.devices:
            return False
        self.devices[name] = {"motor_count": motor_count,
                              "motor_kinds": motor_kinds}
        return True

    def all(self):
        return dict(self.devices)

    def forget(self, name):
        self.devices.pop(name, None)


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Point config_manager at tmp_path and stub every settings manager."""
    monkeypatch.setattr(config_manager, "PROFILE_FILE",
                        tmp_path / "profiles.json")
    for name in ("AppSettingsManager", "SteamVRSettingsManager",
                 "BHapticsSettingsManager", "PiShockSettingsManager",
                 "CoyoteSettingsManager", "OwoSettingsManager",
                 "HandySettingsManager", "SpsSourceManager"):
        monkeypatch.setattr(config_manager, name, _StubSettings)
    monkeypatch.setattr(config_manager, "KnownDevicesRegistry",
                        _StubKnownDevices)
    return tmp_path


def _v2_payload():
    """A realistic schema-2 profiles.json with user tuning worth keeping."""
    custom_mix = {
        "0": {
            "chains": [{
                "depth": {"gain": 1.7, "curve": "linear", "curve_param": 1.0},
                "speed": {"gain": 0.2, "curve": "linear", "curve_param": 1.0,
                          "decay_ms": 123.0},
                "combine": "max",
                "gate": {"enabled": True, "wake_threshold": 0.11,
                         "sleep_delay_s": 0.5, "attack_s": 0.05,
                         "release_s": 0.5},
                "smoothing": {"rise_ms": 77.0, "fall_ms": 33.0},
                "zerocut": {"enabled": True, "threshold": 0.02},
            }],
            "merge": "max",
        },
    }
    return {
        "schema": 2,
        "global_profiles": {
            "Default": {
                "ToyA": {
                    "motor_count": 2,
                    "motor_kinds": ["Vibrate", "Vibrate"],
                    "osc_addresses": {"0": ["ToyA_0"], "1": ["ToyA_1"]},
                    "motor_0_zones": "All SPS, Boob",
                    "motor_0_touch": True,
                    "mix": custom_mix,
                },
                "OldStroker": {
                    "motor_count": 1,
                    "osc_address": "/avatar/parameters/Legacy_Param",
                },
            },
            "Spare": {"ToyB": {"motor_count": 1}},
        },
        "avatar_profiles": {"AvProf": {"ToyA": {"motor_count": 2}}},
        "avatar_bindings": {"AvProf": "avtr_x"},
        "avatar_last_choice": {},
    }


class TestFreshInstall:
    def test_creates_six_modes_and_persists(self, isolated):
        mm = ModeManager()
        assert len(mm.modes) == ModeManager.MODE_COUNT == 6
        assert mm.active_mode == ModeManager.DEFAULT_ACTIVE_MODE
        names = [m["name"] for m in mm.modes]
        assert names == ["Off", "Low", "Medium", "High", "Sleep", "Custom"]
        on_disk = json.loads((isolated / "profiles.json").read_text("utf-8"))
        assert on_disk["schema"] == 3
        assert len(on_disk["modes"]) == 6

    def test_off_slot_ships_silent(self, isolated):
        mm = ModeManager()
        assert mm.modes[ModeManager.OFF_SLOT]["master_scale"] == 0.0
        mm.set_active_mode(ModeManager.OFF_SLOT)
        assert mm.get_master_scale() == 0.0


class TestMigration:
    def _write_v2(self, tmp):
        (tmp / "profiles.json").write_text(json.dumps(_v2_payload()),
                                           encoding="utf-8")

    def test_custom_slot_keeps_user_tuning(self, isolated):
        self._write_v2(isolated)
        mm = ModeManager()
        chain = mm.modes[ModeManager.CUSTOM_SLOT]["mix"]["ToyA"]["0"][
            "chains"][0]
        # Every tuned value survives the migration…
        assert chain["depth"]["gain"] == 1.7
        assert chain["speed"]["decay_ms"] == 123.0
        assert chain["smoothing"] == {"rise_ms": 77.0, "fall_ms": 33.0}
        assert chain["zerocut"] == {"enabled": True, "threshold": 0.02}
        # …and the legacy `gate` block is folded into the merged `wake`
        # stage (Gate+Arming were unified), preserving its threshold.
        assert "gate" not in chain and "arming" not in chain
        assert chain["wake"]["enabled"] is True
        assert chain["wake"]["mode"] == "activity"
        assert chain["wake"]["wake_threshold"] == 0.11
        # And the app lands ON Custom so the post-migration feel matches
        # the pre-migration behavior.
        assert mm.active_mode == ModeManager.CUSTOM_SLOT

    def test_wiring_extracted_without_mix(self, isolated):
        self._write_v2(isolated)
        mm = ModeManager()
        toy = mm.wiring["ToyA"]
        assert toy["motor_count"] == 2
        assert toy["motor_0_zones"] == "All SPS, Boob"
        on_disk = json.loads((isolated / "profiles.json").read_text("utf-8"))
        assert "mix" not in on_disk["wiring"]["ToyA"]

    def test_legacy_osc_address_upgraded(self, isolated):
        self._write_v2(isolated)
        mm = ModeManager()
        assert mm.wiring["OldStroker"]["osc_addresses"] == {
            "0": ["Legacy_Param"]}

    def test_presets_seeded_per_slot(self, isolated):
        self._write_v2(isolated)
        mm = ModeManager()
        low = mm.modes[1]["mix"]["ToyA"]["0"]["chains"][0]
        high = mm.modes[3]["mix"]["ToyA"]["1"]["chains"][0]
        sleep = mm.modes[4]["mix"]["ToyA"]["0"]["chains"][0]
        assert low["depth"]["gain"] == 0.55
        assert high["speed"]["gain"] == 1.6
        assert sleep["wake"]["enabled"] is True
        assert sleep["wake"]["mode"] == "strokes"
        assert sleep["wake"]["thrusts"] == 3

    def test_backup_written_and_old_profiles_dropped(self, isolated):
        self._write_v2(isolated)
        ModeManager()
        bak = isolated / "profiles.json.v2.bak"
        assert bak.exists()
        original = json.loads(bak.read_text("utf-8"))
        assert "Spare" in original["global_profiles"]
        migrated = json.loads((isolated / "profiles.json").read_text("utf-8"))
        assert "ToyB" not in migrated["wiring"]

    def test_source_follows_avatar_last_choice_not_default(self, isolated):
        # v2 never persisted current_profile; avatar_last_choice is the
        # only record of what the user actually played on. A user whose
        # active profile was 'MyTuned' must not get stock Default tuning.
        payload = _v2_payload()
        payload["global_profiles"]["MyTuned"] = {
            "ToyA": {"motor_count": 1,
                     "mix": {"0": {"chains": [], "merge": "multiply"}}},
        }
        payload["avatar_last_choice"] = {
            "avtr_x": {"kind": "global", "name": "MyTuned"},
            "avtr_y": {"kind": "global", "name": "MyTuned"},
        }
        (isolated / "profiles.json").write_text(json.dumps(payload), "utf-8")
        mm = ModeManager()
        assert mm.modes[ModeManager.CUSTOM_SLOT]["mix"]["ToyA"] == {
            "0": {"chains": [], "merge": "multiply"}}

    def test_source_can_be_a_bound_avatar_profile(self, isolated):
        payload = _v2_payload()
        payload["avatar_profiles"] = {
            "AvTuned": {"ToyZ": {"motor_count": 1,
                                 "mix": {"0": {"chains": [],
                                               "merge": "add"}}}},
        }
        payload["avatar_last_choice"] = {
            "avtr_x": {"kind": "avatar", "name": "AvTuned"}}
        (isolated / "profiles.json").write_text(json.dumps(payload), "utf-8")
        mm = ModeManager()
        assert "ToyZ" in mm.wiring
        assert mm.modes[ModeManager.CUSTOM_SLOT]["mix"]["ToyZ"]["0"][
            "merge"] == "add"

    def test_stale_last_choice_falls_back_to_default(self, isolated):
        payload = _v2_payload()
        payload["avatar_last_choice"] = {
            "avtr_x": {"kind": "global", "name": "Deleted"}}
        (isolated / "profiles.json").write_text(json.dumps(payload), "utf-8")
        mm = ModeManager()
        assert "ToyA" in mm.wiring  # Default carried

    def test_v1_bare_shape_migrates(self, isolated):
        v1 = {"Default": {"ToyA": {"motor_count": 1,
                                   "mix": {"0": {"chains": [], "merge": "max"}}}}}
        (isolated / "profiles.json").write_text(json.dumps(v1), "utf-8")
        mm = ModeManager()
        assert "ToyA" in mm.wiring
        assert mm.modes[ModeManager.CUSTOM_SLOT]["mix"]["ToyA"] == {
            "0": {"chains": [], "merge": "max"}}


class TestIdentityStability:
    """The router's compiled-config cache keys on id(); a mode switch must
    swap ONLY the "mix" value inside otherwise-stable dicts."""

    def _mm_with_toy(self, isolated):
        mm = ModeManager()
        mm.update_device_config("ToyA", "motor_count", 1)
        mm.update_device_config("ToyA", "osc_addresses", {"0": ["ToyA_0"]})
        return mm

    def test_top_and_device_dict_identity_survive_switch(self, isolated):
        mm = self._mm_with_toy(isolated)
        top = mm.get_active_profile_dict()
        dev = top["ToyA"]
        mm.set_active_mode(1)
        assert mm.get_active_profile_dict() is top
        assert top["ToyA"] is dev

    def test_switch_swaps_only_the_mix_reference(self, isolated):
        mm = self._mm_with_toy(isolated)
        dev = mm.wiring["ToyA"]
        mm.set_active_mode(1)
        mix_low = dev["mix"]
        mm.set_active_mode(3)
        mix_high = dev["mix"]
        assert mix_low is not mix_high
        assert dev["mix"] is mm.modes[3]["mix"]["ToyA"]

    def test_mix_write_lands_in_active_mode_only(self, isolated):
        mm = self._mm_with_toy(isolated)
        mm.set_active_mode(1)
        marker = {"0": {"chains": [], "merge": "add"}}
        mm.update_device_config("ToyA", "mix", marker)
        assert mm.modes[1]["mix"]["ToyA"] is marker
        mm.set_active_mode(3)
        assert mm.wiring["ToyA"]["mix"] is not marker
        mm.set_active_mode(1)
        assert mm.wiring["ToyA"]["mix"] is marker

    def test_wiring_write_visible_in_every_mode(self, isolated):
        mm = self._mm_with_toy(isolated)
        mm.set_active_mode(1)
        mm.update_device_config("ToyA", "motor_0_zones", "Boob")
        mm.set_active_mode(4)
        assert mm.get_profile_config("ToyA", "motor_0_zones") == "Boob"


class TestPersistence:
    def test_round_trip(self, isolated):
        mm = ModeManager()
        mm.update_device_config("ToyA", "motor_count", 1)
        mm.update_device_config("ToyA", "mix",
                                {"0": {"chains": [], "merge": "max"}})
        mm.set_mode_name(5, "Wildcard")
        mm.set_active_mode(5)
        again = ModeManager()
        assert again.active_mode == 5
        assert again.modes[5]["name"] == "Wildcard"
        # The mix was written while Medium (slot 2) was active — it belongs
        # to that mode, not to the now-active Custom slot.
        assert again.modes[2]["mix"]["ToyA"] == {
            "0": {"chains": [], "merge": "max"}}
        assert again.wiring["ToyA"]["mix"] == {}
        assert "motor_count" in again.wiring["ToyA"]

    def test_malformed_v3_modes_fall_back_per_slot(self, isolated):
        (isolated / "profiles.json").write_text(json.dumps({
            "schema": 3, "wiring": {},
            "modes": [None, {"name": "", "master_scale": float("nan")}],
            "active_mode": 99,
        }), "utf-8")
        mm = ModeManager()
        assert len(mm.modes) == 6
        assert mm.modes[0]["name"] == "Off"
        assert mm.modes[1]["name"] == "Low"          # empty name rejected
        assert mm.modes[1]["master_scale"] == 0.6    # NaN rejected
        assert mm.active_mode == ModeManager.DEFAULT_ACTIVE_MODE


class TestWakeMigration:
    """A chain saved before the Gate+Arming→Wake merge (separate `gate`/
    `arming` keys, no `wake`) must be folded to `wake` at load and
    persisted — otherwise the first UI edit backfills a bare-default
    `wake` that shadows a still-armed Sleep gate, silently disabling it."""

    def _legacy_v3(self, isolated, arming):
        # A schema-v3 file whose Custom-slot chain still carries a legacy
        # arming block (as if written just before the merge shipped).
        modes = [dict(m, mix={}) for m in ModeManager.DEFAULT_MODES]
        modes[ModeManager.CUSTOM_SLOT]["mix"] = {
            "ToyA": {"0": {"chains": [{
                "depth": {"gain": 1.0}, "arming": arming,
            }], "merge": "max"}}}
        (isolated / "profiles.json").write_text(json.dumps({
            "schema": 3, "wiring": {"ToyA": {"motor_count": 1}},
            "modes": modes, "active_mode": ModeManager.CUSTOM_SLOT,
        }), "utf-8")

    def test_legacy_arming_folds_into_wake_and_persists(self, isolated):
        self._legacy_v3(isolated, {
            "enabled": True, "thrusts": 5, "window_s": 8.0,
            "disarm_after_s": 60.0})
        mm = ModeManager()
        chain = mm.modes[ModeManager.CUSTOM_SLOT]["mix"]["ToyA"]["0"]["chains"][0]
        assert "arming" not in chain and "gate" not in chain
        assert chain["wake"]["enabled"] is True
        assert chain["wake"]["mode"] == "strokes"
        assert chain["wake"]["thrusts"] == 5
        assert chain["wake"]["disarm_after_s"] == 60.0
        # Persisted, so a re-load (and any UI edit) sees the merged shape.
        on_disk = json.loads((isolated / "profiles.json").read_text("utf-8"))
        disk_chain = on_disk["modes"][ModeManager.CUSTOM_SLOT][
            "mix"]["ToyA"]["0"]["chains"][0]
        assert "arming" not in disk_chain
        assert disk_chain["wake"]["thrusts"] == 5

    def test_migration_is_idempotent_no_extra_save(self, isolated):
        # A clean v3 file (already on `wake`) must not be rewritten.
        ModeManager()   # fresh install writes a clean file
        before = (isolated / "profiles.json").read_text("utf-8")
        ModeManager()   # second load: nothing legacy → no save
        assert (isolated / "profiles.json").read_text("utf-8") == before


class TestDegradedLoadProtection:
    """A file that existed but couldn't be READ must never be traded for
    this session's in-memory defaults (the boot seeder saves immediately,
    which used to clobber it before the reload could recover it)."""

    def test_save_skipped_while_file_is_healthy(self, isolated):
        mm = ModeManager()
        mm.set_mode_name(5, "Precious")     # real content on disk
        before = (isolated / "profiles.json").read_text("utf-8")
        degraded = ModeManager.__new__(ModeManager)
        degraded.__dict__.update(mm.__dict__)
        degraded.modes = ModeManager._fresh_modes()   # session defaults
        degraded.wiring = {}
        degraded._degraded_load = True
        degraded.save_profiles()
        assert (isolated / "profiles.json").read_text("utf-8") == before
        assert degraded._degraded_load is True        # still protected

    def test_corrupt_file_backed_up_then_overwritten(self, isolated):
        ModeManager()   # create a valid file first
        (isolated / "profiles.json").write_text("{corrupt", "utf-8")
        degraded = ModeManager.__new__(ModeManager)
        degraded.wiring = {}
        degraded.modes = ModeManager._fresh_modes()
        degraded.active_mode = 2
        degraded.avatar_last_mode = {}
        degraded._degraded_load = True
        degraded.save_profiles()
        baks = list(isolated.glob("profiles.json.*.bak"))
        assert baks and baks[0].read_text("utf-8") == "{corrupt"
        reloaded = json.loads((isolated / "profiles.json").read_text("utf-8"))
        assert reloaded["schema"] == 3

    def test_reload_clears_degraded_flag(self, isolated):
        mm = ModeManager()
        mm._degraded_load = True
        mm.load_profiles()
        assert mm._degraded_load is False


class TestMasterScale:
    def test_clamped_to_unit_range(self, isolated):
        mm = ModeManager()
        mm.set_mode_master_scale(2, 7.5)
        assert mm.modes[2]["master_scale"] == 1.0
        mm.set_mode_master_scale(2, -3)
        assert mm.modes[2]["master_scale"] == 0.0

    def test_non_finite_reads_fall_back(self, isolated):
        mm = ModeManager()
        mm.modes[mm.active_mode]["master_scale"] = float("inf")
        assert mm.get_master_scale() == 1.0
        mm.modes[mm.active_mode]["master_scale"] = float("nan")
        assert mm.get_master_scale() == 1.0


class TestDeviceLifecycle:
    def test_delete_device_removes_everywhere(self, isolated):
        mm = ModeManager()
        mm.update_device_config("ToyA", "motor_count", 1)
        for mode in mm.modes:
            mode.setdefault("mix", {})["ToyA"] = {"0": {}}
        mm.delete_device("ToyA")
        assert "ToyA" not in mm.wiring
        assert all("ToyA" not in m.get("mix", {}) for m in mm.modes)

    def test_fresh_device_gets_installed_mix_reference(self, isolated):
        mm = ModeManager()
        mm.update_device_config("New", "motor_count", 1)
        assert mm.wiring["New"]["mix"] is mm.modes[mm.active_mode]["mix"]["New"]


class TestAvatarMemory:
    def test_records_and_recalls_per_avatar(self, isolated):
        mm = ModeManager()
        mm.set_current_avatar("avtr_a")
        mm.set_active_mode(3)
        mm.set_current_avatar(None)
        mm.set_active_mode(1)
        assert mm.set_current_avatar("avtr_a") == 3

    def test_unknown_avatar_returns_none(self, isolated):
        mm = ModeManager()
        assert mm.set_current_avatar("avtr_new") is None

    def test_persisted(self, isolated):
        mm = ModeManager()
        mm.set_current_avatar("avtr_a")
        mm.set_active_mode(4)
        again = ModeManager()
        assert again.avatar_last_mode == {"avtr_a": 4}


class TestPresets:
    def test_plain_slots_match_router_defaults(self):
        assert preset_motor_mix(0) == MotorRouter.DEFAULT_MIX_CONFIG
        assert preset_motor_mix(5) == MotorRouter.DEFAULT_MIX_CONFIG
        # Fresh copies, never the shared default object.
        assert preset_motor_mix(0) is not MotorRouter.DEFAULT_MIX_CONFIG

    def test_feel_slots_stay_inside_router_ranges(self):
        for slot in range(6):
            chain = preset_motor_mix(slot)["chains"][0]
            for part in ("depth", "speed", "punch"):
                assert 0.0 <= chain[part]["gain"] <= 2.0
                assert math.isfinite(chain[part]["gain"])
            assert 0.0 <= chain["texture"]["amount"] <= 0.9
            assert set(chain) == {"depth", "speed", "punch", "combine",
                                  "wake", "smoothing", "texture", "zerocut"}

    def test_low_teases_and_high_punches(self):
        low = preset_motor_mix(1)["chains"][0]
        high = preset_motor_mix(3)["chains"][0]
        assert low["texture"]["enabled"] is True
        assert high["punch"]["gain"] > 0.0
        # And the accents stay OUT of the slots that didn't ask for them.
        assert preset_motor_mix(2)["chains"][0]["texture"]["enabled"] is False
        assert preset_motor_mix(2)["chains"][0]["punch"]["gain"] == 0.0

    def test_sleep_uses_the_wake_stage_in_strokes_mode(self):
        sleep = preset_motor_mix(4)["chains"][0]
        assert sleep["wake"]["enabled"] is True
        assert sleep["wake"]["mode"] == "strokes"
        # The other slots leave Wake off.
        for slot in (0, 1, 2, 3, 5):
            assert preset_motor_mix(slot)["chains"][0]["wake"]["enabled"] is False
