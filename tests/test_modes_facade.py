"""Tests for ModesFacade: seeding (rig + shared feel + per-mode routing),
mode switching side-effects (cache resets, mute survival, OSC echo), the
OGP/Mode sync guard, the strength / Off / Sleep controls and their OSC
sync, and the OGP/Test pulse plumbing.

The facade is composed standalone onto a minimal host (mirrors how
OscGoesPurrrApp mixes it in) with the real ModeManager isolated onto
tmp_path — integration at the data layer, stubs at the hardware layer."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config_manager
from config_manager import ModeManager
from constants import OGP_TEST_LEVEL
from controllers.modes_facade import ModesFacade

from test_modes_core import _StubKnownDevices, _StubSettings  # noqa: E402


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config_manager, "MODES_FILE",
                        tmp_path / "modes.json")
    for name in ("AppSettingsManager", "SpsSourceManager"):
        monkeypatch.setattr(config_manager, name, _StubSettings)
    monkeypatch.setattr(config_manager, "KnownDevicesRegistry",
                        _StubKnownDevices)
    return tmp_path


class _StubMotorRouter:
    def __init__(self):
        self.resets = 0

    def reset_outputs(self):
        self.resets += 1


class _StubOsc:
    def __init__(self):
        self.is_connected = True
        self.sent = []

    def send_parameter(self, address, value, **kwargs):
        self.sent.append((address, value, kwargs))


class _StubEngine:
    def __init__(self, counts):
        self.is_connected = True
        self._counts = counts
        self.targets = []

    def get_motor_count_map(self):
        return dict(self._counts)

    def update_target(self, device, motor, value):
        self.targets.append((device, motor, value))


class _Host(ModesFacade):
    def __init__(self, mm):
        self.mode_manager = mm
        self.ui = None
        self.logs = []
        self.osc_manager = _StubOsc()
        self.haptic_engine = _StubEngine({})
        self.motor_router = _StubMotorRouter()
        self._muted_devices = set()
        self.app_settings = {}
        self.recalcs = 0

    def log_message(self, msg):
        self.logs.append(msg)

    def get_app_setting(self, key, default=None):
        return self.app_settings.get(key, default)

    def force_recalculate(self, dispatch_direct=False):
        self.recalcs += 1


def _host(isolated) -> _Host:
    return _Host(ModeManager())


class TestSeeding:
    def test_seeds_rig_shared_feel_and_routing_in_every_mode(self, isolated):
        h = _host(isolated)
        h.mode_manager.known_devices.devices = {
            "ToyA": {"motor_count": 2, "motor_kinds": ["Vibrate", "Rotate"]},
        }
        h._seed_known_devices()
        mm = h.mode_manager
        assert mm.wiring["ToyA"]["motor_count"] == 2
        # Feel: one shared copy, one block per motor, on the tuned preset.
        assert set(mm.feel["ToyA"]) == {"0", "1"}
        assert mm.feel["ToyA"]["0"]["chains"][0]["speed"]["gain"] == 0.41
        assert mm.wiring["ToyA"]["mix"] is mm.feel["ToyA"]
        # Routing: a new toy is routable whichever mode you switch to, not
        # only the one that happened to be active during discovery.
        for mode in mm.modes:
            assert mode["routing"]["ToyA"]["osc_addresses"] == {
                "0": ["ToyA_0"], "1": ["ToyA_1"]}
        assert mm.wiring["ToyA"]["osc_addresses"] == {
            "0": ["ToyA_0"], "1": ["ToyA_1"]}
        # Independent copies per mode.
        mm.modes[0]["routing"]["ToyA"]["osc_addresses"]["0"] = ["edited"]
        assert mm.modes[1]["routing"]["ToyA"]["osc_addresses"]["0"] == ["ToyA_0"]

    def test_structural_refresh_preserves_user_fields(self, isolated):
        h = _host(isolated)
        h.mode_manager.known_devices.devices = {
            "ToyA": {"motor_count": 1, "motor_kinds": None}}
        h._seed_known_devices()
        h.mode_manager.update_device_config("ToyA", "motor_0_zones", "Boob")
        # Engine reclassifies: two motors now.
        h.mode_manager.known_devices.devices["ToyA"] = {
            "motor_count": 2, "motor_kinds": ["Vibrate", "Vibrate"]}
        h._seed_known_devices()
        mm = h.mode_manager
        assert mm.wiring["ToyA"]["motor_count"] == 2
        assert mm.wiring["ToyA"]["motor_0_zones"] == "Boob"
        assert "1" in mm.feel["ToyA"]

    def test_reseeding_does_not_refill_a_cleared_address_block(self, isolated):
        # An empty address block is a legitimate choice (zone routing
        # instead) — a later reseed must not "helpfully" undo it.
        h = _host(isolated)
        h.mode_manager.known_devices.devices = {
            "ToyA": {"motor_count": 1, "motor_kinds": None}}
        h._seed_known_devices()
        h.mode_manager.update_device_config("ToyA", "osc_addresses", {})
        h._seed_known_devices()
        assert h.mode_manager.wiring["ToyA"]["osc_addresses"] == {}

    def test_seeding_is_idempotent_on_disk(self, isolated):
        h = _host(isolated)
        h.mode_manager.known_devices.devices = {
            "ToyA": {"motor_count": 1, "motor_kinds": None}}
        h._seed_known_devices()
        before = (isolated / "modes.json").read_text("utf-8")
        h._seed_known_devices()
        assert (isolated / "modes.json").read_text("utf-8") == before


class TestSwitching:
    def test_switch_resets_every_dispatch_cache(self, isolated):
        h = _host(isolated)
        h.switch_mode(1)
        assert h.motor_router.resets == 1
        assert h.recalcs == 1

    def test_switch_keeps_per_toy_mutes(self, isolated):
        h = _host(isolated)
        h._muted_devices.add("ToyA")
        h.switch_mode(3)
        assert "ToyA" in h._muted_devices

    def test_ui_switch_echoes_to_vrchat_osc_switch_does_not(self, isolated):
        h = _host(isolated)
        h.switch_mode(1, source="ui")
        assert h.osc_manager.sent[-1][0] == "/avatar/parameters/OGP/Mode"
        assert h.osc_manager.sent[-1][1] == 1
        assert h.osc_manager.sent[-1][2].get("force_type") == "i"
        sends = len(h.osc_manager.sent)
        h.switch_mode(3, source="osc")
        assert len(h.osc_manager.sent) == sends

    def test_same_index_is_a_cheap_no_op(self, isolated):
        h = _host(isolated)
        active = h.mode_manager.get_active_mode_index()
        h.switch_mode(active)
        assert h.motor_router.resets == 0
        assert h.recalcs == 0


class TestOgpModeIn:
    def test_incoming_int_switches(self, isolated):
        h = _host(isolated)
        h._on_ogp_mode_osc(2)
        assert h.mode_manager.get_active_mode_index() == 2

    def test_guard_window_reasserts_instead_of_following(self, isolated):
        h = _host(isolated)
        h._ogp_mode_guard_until = time.monotonic() + 5.0
        before = h.mode_manager.get_active_mode_index()
        h._on_ogp_mode_osc(0)   # stale replayed "Off" right after avatar load
        assert h.mode_manager.get_active_mode_index() == before
        assert h.osc_manager.sent[-1][1] == before

    def test_garbage_value_ignored(self, isolated):
        h = _host(isolated)
        before = h.mode_manager.get_active_mode_index()
        h._on_ogp_mode_osc("purr")
        assert h.mode_manager.get_active_mode_index() == before

    def test_out_of_range_reasserts_instead_of_desyncing(self, isolated):
        # A mis-built menu toggle (Value=6) must not leave VRChat's menu
        # highlighting a phantom mode while the app silently disagrees.
        h = _host(isolated)
        before = h.mode_manager.get_active_mode_index()
        h._on_ogp_mode_osc(6)
        assert h.mode_manager.get_active_mode_index() == before
        assert h.osc_manager.sent[-1][1] == before

    def test_own_echo_does_not_yank_mode_backwards(self, isolated):
        # VRChat echoes our sends back; after two quick app-side switches
        # the FIRST echo arrives while the app is already on the second
        # mode — it must be recognized as an echo, not user intent.
        h = _host(isolated)
        h.switch_mode(1)          # sends 1, records it
        h.switch_mode(3)          # sends 3, records it
        h._on_ogp_mode_osc(1)     # stale echo of the first send
        assert h.mode_manager.get_active_mode_index() == 3
        h._on_ogp_mode_osc(3)     # echo of the second send: no-op anyway
        assert h.mode_manager.get_active_mode_index() == 3


class TestStrengthControl:
    def _sent(self, h, name):
        return [s for s in h.osc_manager.sent
                if s[0] == f"/avatar/parameters/OGP/{name}"]

    def test_applies_and_pushes_to_hardware(self, isolated):
        h = _host(isolated)
        h.set_strength(0.5)
        assert h.get_strength() == 0.5
        # A strength change alters output without changing any router
        # input, so the debounce caches must be cleared or devices would
        # hold the old level until the next contact change.
        assert h.motor_router.resets == 1
        assert h.recalcs == 1

    def test_ui_change_echoes_osc_change_does_not(self, isolated):
        h = _host(isolated)
        h.set_strength(0.5, source="ui")
        sent = self._sent(h, "Strength")
        assert sent[-1][1] == 0.5
        assert sent[-1][2].get("force_type") == "f"
        h.set_strength(0.25, source="osc")
        assert len(self._sent(h, "Strength")) == len(sent)

    def test_unchanged_value_is_a_cheap_no_op(self, isolated):
        h = _host(isolated)
        h.set_strength(0.5)
        h.set_strength(0.5)
        assert h.recalcs == 1

    def test_incoming_float_applies(self, isolated):
        h = _host(isolated)
        h._on_ogp_strength_osc(0.25)
        assert h.get_strength() == 0.25

    @pytest.mark.parametrize("junk", ["purr", None, float("nan")])
    def test_incoming_junk_ignored(self, isolated, junk):
        h = _host(isolated)
        before = h.get_strength()
        h._on_ogp_strength_osc(junk)
        assert h.get_strength() == before

    def test_incoming_out_of_range_clamps(self, isolated):
        h = _host(isolated)
        h._on_ogp_strength_osc(3.7)
        assert h.get_strength() == 1.0

    def test_menu_jitter_below_epsilon_ignored(self, isolated):
        h = _host(isolated)
        h.set_strength(0.5)
        recalcs = h.recalcs
        h._on_ogp_strength_osc(0.5005)
        assert h.recalcs == recalcs

    def test_guard_window_reasserts_instead_of_following(self, isolated):
        h = _host(isolated)
        h.set_strength(0.8)
        h._ogp_mode_guard_until = time.monotonic() + 5.0
        h._on_ogp_strength_osc(0.1)   # stale replay right after avatar load
        assert h.get_strength() == 0.8
        assert self._sent(h, "Strength")[-1][1] == 0.8

    def test_own_echo_does_not_drag_the_value_backwards(self, isolated):
        h = _host(isolated)
        h.set_strength(0.4)           # sends 0.4, records it
        h.set_strength(0.9)           # sends 0.9, records it
        h._on_ogp_strength_osc(0.4)   # stale echo of the first send
        assert h.get_strength() == 0.9


class TestToggleControls:
    def _sent(self, h, name):
        return [s for s in h.osc_manager.sent
                if s[0] == f"/avatar/parameters/OGP/{name}"]

    def test_off_silences_and_pushes_to_hardware(self, isolated):
        h = _host(isolated)
        h.set_strength(1.0)
        h.set_output_off(True)
        assert h.is_output_off() is True
        assert h.get_master_scale() == 0.0
        assert h.motor_router.resets == 2   # strength change, then Off
        assert self._sent(h, "Off")[-1][1] is True

    def test_off_release_restores_the_level(self, isolated):
        h = _host(isolated)
        h.set_strength(0.7)
        h.set_output_off(True)
        h.set_output_off(False)
        assert h.get_master_scale() == 0.7

    def test_sleep_toggles_and_pushes_to_hardware(self, isolated):
        h = _host(isolated)
        h.set_sleep_active(True)
        assert h.is_sleep_active() is True
        assert h.recalcs == 1
        assert self._sent(h, "Sleep")[-1][1] is True

    def test_sleep_leaves_the_dispatch_scale_alone(self, isolated):
        h = _host(isolated)
        h.set_strength(0.7)
        h.set_sleep_active(True)
        assert h.get_master_scale() == 0.7

    @pytest.mark.parametrize("setter,getter", [
        ("set_output_off", "is_output_off"),
        ("set_sleep_active", "is_sleep_active"),
    ])
    def test_edge_triggered(self, isolated, setter, getter):
        h = _host(isolated)
        getattr(h, setter)(True)
        getattr(h, setter)(True)
        assert h.recalcs == 1
        assert getattr(h, getter)() is True

    @pytest.mark.parametrize("which,param", [("off", "Off"),
                                             ("sleep", "Sleep")])
    def test_incoming_bool_applies(self, isolated, which, param):
        h = _host(isolated)
        h._on_ogp_toggle_osc(which, True)
        assert (h.is_output_off() if which == "off"
                else h.is_sleep_active()) is True
        # OSC-sourced: no echo back to VRChat, the menu already holds it.
        assert self._sent(h, param) == []

    @pytest.mark.parametrize("which,param", [("off", "Off"),
                                             ("sleep", "Sleep")])
    def test_guard_window_reasserts_instead_of_following(self, isolated,
                                                         which, param):
        h = _host(isolated)
        h._ogp_mode_guard_until = time.monotonic() + 5.0
        h._on_ogp_toggle_osc(which, True)   # stale replay after avatar load
        assert h.is_output_off() is False
        assert h.is_sleep_active() is False
        assert self._sent(h, param)[-1][1] is False


class TestAvatarChange:
    def test_restore_only_when_setting_enabled(self, isolated):
        h = _host(isolated)
        h.mode_manager.set_current_avatar("avtr_a")
        h.switch_mode(3)
        h.mode_manager.set_current_avatar(None)
        h.switch_mode(1)

        h._on_avatar_change("avtr_a")          # setting OFF (default)
        assert h.mode_manager.get_active_mode_index() == 1

        h.app_settings["avatar_modes_enabled"] = True
        h._on_avatar_change("avtr_a")          # setting ON
        assert h.mode_manager.get_active_mode_index() == 3

    def test_sets_sync_guard_and_reasserts_the_whole_control_set(self,
                                                                 isolated):
        # An avatar swap resets every parameter on the VRChat side, so all
        # four OGP controls have to be re-asserted, not just the mode.
        h = _host(isolated)
        h.set_strength(0.6)
        h.set_sleep_active(True)
        h.osc_manager.sent.clear()
        h._on_avatar_change("avtr_a")
        assert h._ogp_mode_guard_until > time.monotonic()
        sent = {addr: value for addr, value, _ in h.osc_manager.sent}
        assert sent["/avatar/parameters/OGP/Mode"] == \
            h.mode_manager.get_active_mode_index()
        assert sent["/avatar/parameters/OGP/Strength"] == 0.6
        assert sent["/avatar/parameters/OGP/Off"] is False
        assert sent["/avatar/parameters/OGP/Sleep"] is True


class TestOgpTest:
    def test_activate_pushes_floor_to_unmuted_toys(self, isolated):
        h = _host(isolated)
        h.haptic_engine = _StubEngine({"ToyA": 2, "ToyB": 1})
        h._muted_devices.add("ToyB")
        h.set_ogp_test_active(True)
        assert ("ToyA", 0, OGP_TEST_LEVEL) in h.haptic_engine.targets
        assert ("ToyA", 1, OGP_TEST_LEVEL) in h.haptic_engine.targets
        assert not any(d == "ToyB" for d, _, _ in h.haptic_engine.targets)
        assert h.get_ogp_test_level() == OGP_TEST_LEVEL
        assert h.recalcs == 1

    def test_immediate_push_is_remapped_into_each_motor_band(self, isolated):
        """The activation push goes straight to the engine, bypassing
        intiface_facade's per-tick floor — so it has to apply the same
        band remap, or the pulse starts in a motor's dead zone and then
        jumps on the next recalc."""
        h = _host(isolated)
        h.haptic_engine = _StubEngine({"ToyA": 2})
        bands = {("ToyA", 0): (0.4, 1.0)}     # motor 1 left uncalibrated

        def _map(device, motor, level):
            floor, ceiling = bands.get((device, motor), (0.0, 1.0))
            return floor + level * (ceiling - floor) if level > 0 else 0.0

        h.motor_router.map_into_output_band = _map
        h.set_ogp_test_active(True)
        pushed = {(d, m): v for d, m, v in h.haptic_engine.targets}
        assert pushed[("ToyA", 0)] == pytest.approx(
            0.4 + OGP_TEST_LEVEL * 0.6)
        # Uncalibrated motor is untouched by the remap.
        assert pushed[("ToyA", 1)] == pytest.approx(OGP_TEST_LEVEL)

    def test_immediate_push_survives_a_router_without_the_hook(self, isolated):
        """Never let a missing/raising router break the pulse — it falls
        back to the raw level, which is what it did before bands."""
        h = _host(isolated)
        h.haptic_engine = _StubEngine({"ToyA": 1})

        def _boom(*_a):
            raise RuntimeError("nope")

        h.motor_router.map_into_output_band = _boom
        h.set_ogp_test_active(True)
        assert ("ToyA", 0, OGP_TEST_LEVEL) in h.haptic_engine.targets

    def test_release_restores_routed_output(self, isolated):
        h = _host(isolated)
        h.set_ogp_test_active(True)
        h.set_ogp_test_active(False)
        assert h.get_ogp_test_level() == 0.0
        assert h.motor_router.resets == 2 and h.recalcs == 2

    def test_toggle_is_edge_triggered(self, isolated):
        h = _host(isolated)
        h.set_ogp_test_active(True)
        h.set_ogp_test_active(True)
        assert h.recalcs == 1


class TestTouchPenetrationSplit:
    """A motor configured before the split keeps its tuning and gains the
    half it never had, rather than being reshaped or reset."""

    @staticmethod
    def _legacy_mix():
        from config_manager import preset_motor_mix
        mix = preset_motor_mix()
        # Pre-split shape: exactly one chain, no type.
        one = mix["chains"][0]
        one.pop("type", None)
        one["depth"]["gain"] = 0.71          # something the user tuned
        return {"chains": [one], "merge": "max"}

    def test_existing_chain_is_kept_and_becomes_penetration(self):
        from controllers.modes_facade import _split_touch_from_penetration
        from motor_router import CHAIN_TYPE_PENETRATION, CHAIN_TYPE_TOUCH
        mix = self._legacy_mix()
        assert _split_touch_from_penetration(mix) is True
        assert len(mix["chains"]) == 2
        pen, touch = mix["chains"]
        assert pen["type"] == CHAIN_TYPE_PENETRATION
        assert pen["depth"]["gain"] == 0.71       # tuning untouched
        assert touch["type"] == CHAIN_TYPE_TOUCH

    def test_the_new_touch_chain_is_tuned_for_touch(self):
        from config_manager import _TOUCH_FEEL
        from controllers.modes_facade import _split_touch_from_penetration
        mix = self._legacy_mix()
        _split_touch_from_penetration(mix)
        touch = mix["chains"][1]
        assert touch["depth"]["gain"] == _TOUCH_FEEL["depth_gain"]
        # A brush is not a thrust: the punch accent is off.
        assert touch["punch"]["gain"] == 0.0

    def test_the_new_chain_inherits_the_toys_output_calibration(self):
        """Output min/max describe the motor's usable range, not the
        feel, so the second chain driving that same motor must keep it."""
        from controllers.modes_facade import _split_touch_from_penetration
        mix = self._legacy_mix()
        mix["chains"][0]["output"] = {"gain": 1.0, "min": 0.25, "max": 0.8}
        _split_touch_from_penetration(mix)
        assert mix["chains"][1]["output"]["min"] == 0.25
        assert mix["chains"][1]["output"]["max"] == 0.8

    def test_is_idempotent(self):
        """It runs from the device seeder on every launch, so a second
        pass must not keep appending chains."""
        from controllers.modes_facade import _split_touch_from_penetration
        mix = self._legacy_mix()
        assert _split_touch_from_penetration(mix) is True
        assert _split_touch_from_penetration(mix) is False
        assert len(mix["chains"]) == 2

    def test_a_hand_built_multi_chain_motor_is_labelled_not_reshaped(self):
        """Two chains already there means the user arranged something
        deliberately; label them custom rather than adding a third."""
        from controllers.modes_facade import _split_touch_from_penetration
        from motor_router import CHAIN_TYPE_CUSTOM
        mix = self._legacy_mix()
        mix["chains"].append(dict(mix["chains"][0]))
        assert _split_touch_from_penetration(mix) is True
        assert len(mix["chains"]) == 2
        assert all(c["type"] == CHAIN_TYPE_CUSTOM for c in mix["chains"])

    def test_junk_is_left_alone(self):
        from controllers.modes_facade import _split_touch_from_penetration
        assert _split_touch_from_penetration(None) is False
        assert _split_touch_from_penetration({}) is False
        assert _split_touch_from_penetration({"chains": []}) is False
        assert _split_touch_from_penetration({"chains": "nope"}) is False
