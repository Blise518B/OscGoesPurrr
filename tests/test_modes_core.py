"""Tests for the routing-mode core in config_manager.py: schema v4
load/save, the identity-stability contract the router's compile cache
relies on, the routing/rig/feel split, the shipped chain preset, and the
global strength + Off toggle.

There is no migration from any older config — the app is pre-release, so a
schema this build can't read is preserved aside and replaced with fresh
defaults rather than upgraded (see TestUnsupportedFile).

ModeManager normally composes the real settings managers (which read/write
the live AppData files), so every test swaps them for stubs and points
MODES_FILE at tmp_path before construction."""

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config_manager
from config_manager import ModeManager, is_routing_key, preset_motor_mix
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
    monkeypatch.setattr(config_manager, "MODES_FILE",
                        tmp_path / "modes.json")
    for name in ("AppSettingsManager", "SpsSourceManager"):
        monkeypatch.setattr(config_manager, name, _StubSettings)
    monkeypatch.setattr(config_manager, "KnownDevicesRegistry",
                        _StubKnownDevices)
    return tmp_path


class TestHarnessIsolation:
    """Guard for conftest's autouse `_never_touch_real_appdata`. If the
    path constants it patches ever drift from the ones config_manager
    actually reads, that fixture silently stops protecting anything and
    a suite run edits the user's live config — which has happened once
    already, when the live file was renamed and one module still patched
    only the old constant."""

    def test_config_paths_are_outside_the_real_appdata(self):
        from settings import APPDATA_DIR
        for const in ("MODES_FILE",):
            patched = getattr(config_manager, const, None)
            assert patched is not None, f"{const} missing — update conftest"
            assert APPDATA_DIR not in Path(patched).parents, (
                f"{const} still points inside the real AppData dir")


class TestRoutingKeyAllowlist:
    """What belongs to a mode vs what is shared. The suffix test (not the
    `motor_` prefix) decides, so rig facts stay shared."""

    @pytest.mark.parametrize("key", [
        "osc_addresses",
        "motor_0_zones", "motor_12_zones",
        "motor_0_touch", "motor_0_pen", "motor_0_self", "motor_0_others",
        "motor_0_param_out_enabled", "motor_0_param_out_address",
    ])
    def test_routing(self, key):
        assert is_routing_key(key) is True

    @pytest.mark.parametrize("key", [
        "motor_count", "motor_kinds", "icon_override", "mix",
        "motor_0_speed_blend", "motor_0_linear_mode", "motor_0_linear_idle",
        "", None, 3,
    ])
    def test_shared(self, key):
        assert is_routing_key(key) is False


class TestFreshInstall:
    def test_creates_four_routing_modes_and_persists(self, isolated):
        mm = ModeManager()
        assert len(mm.modes) == ModeManager.MODE_COUNT == 4
        assert mm.active_mode == ModeManager.DEFAULT_ACTIVE_MODE == 0
        names = [m["name"] for m in mm.modes]
        assert names == ["Combined", "Separate", "Custom 1", "Custom 2"]
        assert all(isinstance(m["routing"], dict) for m in mm.modes)
        on_disk = json.loads((isolated / "modes.json").read_text("utf-8"))
        assert on_disk["schema"] == 4
        assert len(on_disk["modes"]) == 4
        assert on_disk["strength"] == ModeManager.DEFAULT_STRENGTH
        assert on_disk["feel"] == {}

    def test_ships_neither_muted_nor_asleep(self, isolated):
        mm = ModeManager()
        assert mm.output_off is False
        assert mm.sleep_active is False
        assert mm.get_master_scale() == ModeManager.DEFAULT_STRENGTH


class TestUnsupportedFile:
    """A modes.json this build can't use is preserved aside and replaced
    with fresh defaults, never guessed at."""

    @staticmethod
    def _rescues(tmp, tag):
        return sorted(tmp.glob(f"modes.json.{tag}-*.bak"))

    def test_unknown_schema_backed_up_and_reset(self, isolated):
        old = {"schema": 2, "global_profiles": {"Default": {"ToyA": {}}}}
        (isolated / "modes.json").write_text(json.dumps(old), "utf-8")
        mm = ModeManager()
        assert mm.wiring == {}
        rescued = self._rescues(isolated, "unusable")
        assert len(rescued) == 1
        assert json.loads(rescued[0].read_text("utf-8")) == old
        assert json.loads(
            (isolated / "modes.json").read_text("utf-8"))["schema"] == 4

    def test_schemaless_dict_is_reset(self, isolated):
        (isolated / "modes.json").write_text(
            json.dumps({"Default": {"ToyA": {}}}), "utf-8")  # bare v1 shape
        mm = ModeManager()
        assert mm.wiring == {}
        assert len(self._rescues(isolated, "unusable")) == 1

    def test_a_second_rescue_never_overwrites_the_first(self, isolated,
                                                        monkeypatch):
        """The failure this guards is real: alternate a v4 build with an
        older v3 one and rescue #1 holds the only good config while rescue
        #2 holds the already-wiped file. A fixed `.bak` name loses the
        good one."""
        stamps = iter([1000, 2000])
        monkeypatch.setattr(config_manager.time, "time",
                            lambda: next(stamps))
        good = {"schema": 99, "wiring": {"ToyA": {"motor_count": 1}}}
        (isolated / "modes.json").write_text(json.dumps(good), "utf-8")
        ModeManager()                                   # rescue #1
        wiped = {"schema": 99, "wiring": {}}
        (isolated / "modes.json").write_text(json.dumps(wiped), "utf-8")
        ModeManager()                                   # rescue #2
        rescued = self._rescues(isolated, "unusable")
        assert len(rescued) == 2
        assert json.loads(rescued[0].read_text("utf-8")) == good

    def test_a_v3_payload_in_modes_json_is_not_migrated(self, isolated):
        """modes.json is v4 by construction — a v3 body in it is a hand
        edit or a stray copy, not an upgrade path."""
        v3 = {"schema": 3, "wiring": {"ToyA": {"motor_count": 1}},
              "modes": [], "active_mode": 3}
        (isolated / "modes.json").write_text(json.dumps(v3), "utf-8")
        mm = ModeManager()
        assert mm.wiring == {}
        rescued = self._rescues(isolated, "unusable")
        assert len(rescued) == 1
        assert json.loads(rescued[0].read_text("utf-8")) == v3


class TestIdentityStability:
    """The router's compiled-config cache keys on id(); a mode switch must
    mutate the existing dicts in place, never rebuild them."""

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

    def test_osc_addresses_always_present_as_a_stable_object(self, isolated):
        # motor_router keys its compile cache on id(osc_addresses); a
        # missing key would hand it a fresh {} default every tick.
        mm = self._mm_with_toy(isolated)
        mm.set_active_mode(2)   # a mode that never had this device routed
        dev = mm.wiring["ToyA"]
        assert dev["osc_addresses"] == {}
        assert dev["osc_addresses"] is mm.wiring["ToyA"]["osc_addresses"]
        assert dev["osc_addresses"] is mm.modes[2]["routing"]["ToyA"]["osc_addresses"]


class TestLayerSplit:
    """Feel is shared by every mode; routing belongs to the active one."""

    def _mm_with_toy(self, isolated):
        mm = ModeManager()
        mm.update_device_config("ToyA", "motor_count", 1)
        return mm

    def test_feel_is_shared_across_modes(self, isolated):
        mm = self._mm_with_toy(isolated)
        marker = {"0": {"chains": [], "merge": "add"}}
        mm.update_device_config("ToyA", "mix", marker)
        assert mm.feel["ToyA"] is marker
        for slot in range(ModeManager.MODE_COUNT):
            mm.set_active_mode(slot)
            assert mm.wiring["ToyA"]["mix"] is marker

    def test_routing_write_lands_in_the_active_mode_only(self, isolated):
        mm = self._mm_with_toy(isolated)
        mm.set_active_mode(1)
        mm.update_device_config("ToyA", "motor_0_zones", "Boob")
        assert mm.modes[1]["routing"]["ToyA"]["motor_0_zones"] == "Boob"
        assert "motor_0_zones" not in mm.modes[2]["routing"].get("ToyA", {})
        mm.set_active_mode(2)
        assert mm.get_profile_config("ToyA", "motor_0_zones") is None
        mm.set_active_mode(1)
        assert mm.get_profile_config("ToyA", "motor_0_zones") == "Boob"

    def test_switching_clears_the_previous_modes_routing(self, isolated):
        # The bug this guards: a mode with no filter on motor 1 must leave
        # it unfiltered, not inherit whatever the last mode had.
        mm = self._mm_with_toy(isolated)
        mm.set_active_mode(0)
        mm.update_device_config("ToyA", "motor_1_zones", "Pussy")
        mm.update_device_config("ToyA", "motor_1_self", True)
        mm.set_active_mode(1)
        dev = mm.wiring["ToyA"]
        assert "motor_1_zones" not in dev
        assert "motor_1_self" not in dev

    def test_rig_write_visible_in_every_mode(self, isolated):
        mm = self._mm_with_toy(isolated)
        mm.set_active_mode(1)
        mm.update_device_config("ToyA", "icon_override", "edge")
        for slot in range(ModeManager.MODE_COUNT):
            mm.set_active_mode(slot)
            assert mm.get_profile_config("ToyA", "icon_override") == "edge"


class TestPersistence:
    def test_round_trip(self, isolated):
        mm = ModeManager()
        mm.update_device_config("ToyA", "motor_count", 1)
        mm.update_device_config("ToyA", "mix",
                                {"0": {"chains": [], "merge": "max"}})
        mm.set_active_mode(2)
        mm.update_device_config("ToyA", "motor_0_zones", "Ass")
        mm.set_mode_name(3, "Wildcard")
        mm.set_strength(0.42)

        again = ModeManager()
        assert again.active_mode == 2
        assert again.modes[3]["name"] == "Wildcard"
        assert again.get_strength() == 0.42
        # Feel is shared, so it round-trips once — not per mode.
        assert again.feel["ToyA"] == {"0": {"chains": [], "merge": "max"}}
        assert again.wiring["ToyA"]["mix"] == {"0": {"chains": [],
                                                     "merge": "max"}}
        # Routing was written while slot 2 was active and belongs to it.
        assert again.modes[2]["routing"]["ToyA"]["motor_0_zones"] == "Ass"
        assert "motor_0_zones" not in again.modes[0]["routing"].get("ToyA", {})
        assert "motor_count" in again.wiring["ToyA"]

    def test_neither_toggle_survives_a_restart(self, isolated):
        mm = ModeManager()
        mm.set_output_off(True)
        mm.set_sleep_active(True)
        mm.save_profiles()
        again = ModeManager()
        assert again.output_off is False
        assert again.sleep_active is False

    def test_stores_are_kept_out_of_the_wiring_section(self, isolated):
        mm = ModeManager()
        mm.update_device_config("ToyA", "motor_count", 1)
        mm.update_device_config("ToyA", "motor_0_zones", "Ass")
        mm.update_device_config("ToyA", "mix", {"0": {}})
        mm.save_profiles()
        on_disk = json.loads((isolated / "modes.json").read_text("utf-8"))
        assert on_disk["wiring"]["ToyA"] == {"motor_count": 1}

    def test_malformed_modes_fall_back_per_slot(self, isolated):
        (isolated / "modes.json").write_text(json.dumps({
            "schema": 4, "wiring": {}, "feel": {},
            "modes": [None, {"name": "", "routing": "nonsense"}],
            "active_mode": 99, "strength": "banana",
        }), "utf-8")
        mm = ModeManager()
        assert len(mm.modes) == 4
        assert mm.modes[0]["name"] == "Combined"
        assert mm.modes[1]["name"] == "Separate"     # empty name rejected
        assert mm.modes[1]["routing"] == {}          # mis-shaped section dropped
        assert mm.active_mode == ModeManager.DEFAULT_ACTIVE_MODE
        assert mm.get_strength() == ModeManager.DEFAULT_STRENGTH

    def test_hand_edited_rig_key_in_a_routing_block_is_dropped(self, isolated):
        (isolated / "modes.json").write_text(json.dumps({
            "schema": 4, "wiring": {}, "feel": {},
            "modes": [{"name": "Combined",
                       "routing": {"ToyA": {"motor_0_zones": "Ass",
                                            "motor_count": 9}}}],
            "active_mode": 0,
        }), "utf-8")
        mm = ModeManager()
        routing = mm.modes[0]["routing"]["ToyA"]
        assert routing["motor_0_zones"] == "Ass"
        assert "motor_count" not in routing


class TestCleanReload:
    def test_clean_v4_reload_does_not_rewrite_the_file(self, isolated):
        ModeManager()   # fresh install writes a clean file
        before = (isolated / "modes.json").read_text("utf-8")
        ModeManager()
        assert (isolated / "modes.json").read_text("utf-8") == before


class TestDegradedLoadProtection:
    """A file that existed but couldn't be READ must never be traded for
    this session's in-memory defaults (the boot seeder saves immediately,
    which used to clobber it before the reload could recover it)."""

    def test_save_skipped_while_file_is_healthy(self, isolated):
        mm = ModeManager()
        mm.set_mode_name(3, "Precious")     # real content on disk
        before = (isolated / "modes.json").read_text("utf-8")
        degraded = ModeManager.__new__(ModeManager)
        degraded.__dict__.update(mm.__dict__)
        degraded.modes = ModeManager._fresh_modes()   # session defaults
        degraded.wiring = {}
        degraded._degraded_load = True
        degraded.save_profiles()
        assert (isolated / "modes.json").read_text("utf-8") == before
        assert degraded._degraded_load is True        # still protected

    def test_corrupt_file_backed_up_then_overwritten(self, isolated):
        ModeManager()   # create a valid file first
        (isolated / "modes.json").write_text("{corrupt", "utf-8")
        degraded = ModeManager.__new__(ModeManager)
        degraded.wiring = {}
        degraded.feel = {}
        degraded.modes = ModeManager._fresh_modes()
        degraded.active_mode = 0
        degraded._strength = ModeManager.DEFAULT_STRENGTH
        degraded.avatar_last_mode = {}
        degraded._degraded_load = True
        degraded.save_profiles()
        baks = list(isolated.glob("modes.json.*.bak"))
        assert baks and baks[0].read_text("utf-8") == "{corrupt"
        reloaded = json.loads((isolated / "modes.json").read_text("utf-8"))
        assert reloaded["schema"] == 4

    def test_reload_clears_degraded_flag(self, isolated):
        mm = ModeManager()
        mm._degraded_load = True
        mm.load_profiles()
        assert mm._degraded_load is False


class TestStrength:
    """One global multiplier, independent of which routing mode is live."""

    def test_applies_in_every_mode(self, isolated):
        mm = ModeManager()
        mm.set_strength(0.5)
        for slot in range(ModeManager.MODE_COUNT):
            mm.set_active_mode(slot)
            assert mm.get_master_scale() == 0.5

    @pytest.mark.parametrize("raw,expected", [
        (1.5, 1.0), (-0.2, 0.0), (0.0, 0.0), (1.0, 1.0), ("0.3", 0.3),
    ])
    def test_clamps(self, isolated, raw, expected):
        mm = ModeManager()
        mm.set_strength(raw)
        assert mm.get_strength() == pytest.approx(expected)

    @pytest.mark.parametrize("raw", [float("nan"), None, "banana", object()])
    def test_junk_leaves_it_alone(self, isolated, raw):
        mm = ModeManager()
        mm.set_strength(0.4)
        assert mm.set_strength(raw) is False
        assert mm.get_strength() == 0.4

    def test_reports_whether_it_changed(self, isolated):
        mm = ModeManager()
        assert mm.set_strength(0.4) is True
        assert mm.set_strength(0.4) is False

    def test_save_false_applies_without_touching_disk(self, isolated):
        mm = ModeManager()
        before = (isolated / "modes.json").read_text("utf-8")
        assert mm.set_strength(0.33, save=False) is True
        assert mm.get_strength() == 0.33
        assert (isolated / "modes.json").read_text("utf-8") == before
        mm.save_profiles()
        assert ModeManager().get_strength() == 0.33


class TestToggles:
    def test_off_silences_whatever_the_strength(self, isolated):
        mm = ModeManager()
        mm.set_strength(1.0)
        mm.set_output_off(True)
        assert mm.get_master_scale() == 0.0

    def test_off_restores_the_previous_level(self, isolated):
        mm = ModeManager()
        mm.set_strength(0.7)
        mm.set_output_off(True)
        mm.set_output_off(False)
        assert mm.get_master_scale() == 0.7

    def test_off_survives_a_mode_switch(self, isolated):
        mm = ModeManager()
        mm.set_output_off(True)
        mm.set_active_mode(2)
        assert mm.get_master_scale() == 0.0

    @pytest.mark.parametrize("setter,attr", [
        ("set_output_off", "output_off"),
        ("set_sleep_active", "sleep_active"),
    ])
    def test_reports_whether_it_changed(self, isolated, setter, attr):
        mm = ModeManager()
        assert getattr(mm, setter)(True) is True
        assert getattr(mm, setter)(True) is False
        assert getattr(mm, attr) is True
        assert getattr(mm, setter)(False) is True

    def test_sleep_does_not_touch_the_dispatch_scale(self, isolated):
        # Sleep works by overriding the chain's Wake stage in the router,
        # not by attenuating output.
        mm = ModeManager()
        mm.set_strength(0.7)
        mm.set_sleep_active(True)
        assert mm.get_master_scale() == 0.7


class TestDeviceLifecycle:
    def test_delete_device_removes_everywhere(self, isolated):
        mm = ModeManager()
        mm.update_device_config("ToyA", "motor_count", 1)
        mm.update_device_config("ToyA", "mix", {"0": {}})
        for mode in mm.modes:
            mode["routing"]["ToyA"] = {"motor_0_zones": "Ass"}
        mm.delete_device("ToyA")
        assert "ToyA" not in mm.wiring
        assert "ToyA" not in mm.feel
        assert all("ToyA" not in m["routing"] for m in mm.modes)

    def test_fresh_device_gets_the_shared_feel_reference(self, isolated):
        mm = ModeManager()
        mm.update_device_config("New", "motor_count", 1)
        assert mm.wiring["New"]["mix"] is mm.feel["New"]


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
        mm.set_active_mode(2)
        again = ModeManager()
        assert again.avatar_last_mode == {"avtr_a": 2}


class TestPreset:
    """One shipped chain for the whole app — the hand-tuned one, at full
    scale. Level differences are the strength slider's job now."""

    def test_is_a_fresh_copy(self):
        assert preset_motor_mix() is not MotorRouter.DEFAULT_MIX_CONFIG
        assert preset_motor_mix() == preset_motor_mix()
        assert preset_motor_mix() is not preset_motor_mix()

    def test_is_the_tested_chain_at_full_strength(self):
        chain = preset_motor_mix()["chains"][0]
        assert chain["depth"]["gain"] == 0.38
        assert chain["speed"]["gain"] == 0.41
        assert chain["punch"]["gain"] == 1.32
        assert chain["combine"] == "add"
        assert chain["wake"] == {**MotorRouter.DEFAULT_MIX_CONFIG[
            "chains"][0]["wake"], "enabled": True, "mode": "activity"}
        assert chain["zerocut"]["enabled"] is True
        assert chain["smoothing"] == {"rise_ms": 120.0, "fall_ms": 200.0}
        assert chain["speed"]["decay_ms"] == 350.0
        assert chain["texture"]["enabled"] is False

    def test_stays_inside_router_ranges(self):
        chain = preset_motor_mix()["chains"][0]
        for part in ("depth", "speed", "punch"):
            assert 0.0 <= chain[part]["gain"] <= 2.0
            assert math.isfinite(chain[part]["gain"])
        assert 0.0 <= chain["texture"]["amount"] <= 0.9
        assert set(chain) == {"depth", "speed", "punch", "combine",
                              "wake", "smoothing", "texture", "zerocut",
                              "output", "type", "duck"}

    def test_ships_an_untrimmed_output(self):
        # Unity gain over the toy's full range — the Output stage is
        # calibration, and a fresh install has nothing to calibrate yet.
        assert preset_motor_mix()["chains"][0]["output"] == {
            "gain": 1.0, "min": 0.0, "max": 1.0,
        }
