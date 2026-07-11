"""Tests for ModesFacade: seeding (wiring + per-mode feel presets), mode
switching side-effects (cache resets, mute survival, OSC echo), the
OGP/Mode sync guard, and the OGP/Test pulse plumbing.

The facade is composed standalone onto a minimal host (mirrors how
OscGoesPurrrApp mixes it in) with the real ModeManager isolated onto
tmp_path — integration at the data layer, stubs at the hardware layer."""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config_manager
from config_manager import ModeManager
from constants import OGP_TEST_LEVEL
from controllers.modes_facade import ModesFacade

from test_modes_core import _StubKnownDevices, _StubSettings  # noqa: E402


@pytest.fixture
def isolated(monkeypatch, tmp_path):
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


class _StubMotorRouter:
    def __init__(self):
        self.resets = 0

    def reset_outputs(self):
        self.resets += 1


class _StubPollingRouter:
    def __init__(self):
        self.resets = 0

    def reset_dispatch_cache(self):
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
        self.steamvr_router = _StubPollingRouter()
        self.bhaptics_router = _StubPollingRouter()
        self._muted_devices = set()
        self.app_settings = {}
        self.recalcs = 0
        self.bhaptics_bool_sends = 0

    def log_message(self, msg):
        self.logs.append(msg)

    def get_app_setting(self, key, default=None):
        return self.app_settings.get(key, default)

    def force_recalculate(self, dispatch_direct=False):
        self.recalcs += 1

    def _bhaptics_send_connected_bool(self):
        self.bhaptics_bool_sends += 1


def _host(isolated) -> _Host:
    return _Host(ModeManager())


class TestSeeding:
    def test_seeds_wiring_and_all_six_feel_layers(self, isolated):
        h = _host(isolated)
        h.mode_manager.known_devices.devices = {
            "ToyA": {"motor_count": 2, "motor_kinds": ["Vibrate", "Rotate"]},
        }
        h._seed_known_devices()
        wiring = h.mode_manager.wiring["ToyA"]
        assert wiring["motor_count"] == 2
        assert wiring["osc_addresses"] == {"0": ["ToyA_0"], "1": ["ToyA_1"]}
        for slot, mode in enumerate(h.mode_manager.modes):
            per_dev = mode["mix"]["ToyA"]
            assert set(per_dev) == {"0", "1"}
        # Slot presets differ (Low is not High).
        low = h.mode_manager.modes[1]["mix"]["ToyA"]["0"]["chains"][0]
        high = h.mode_manager.modes[3]["mix"]["ToyA"]["0"]["chains"][0]
        assert low["speed"]["gain"] != high["speed"]["gain"]

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
        wiring = h.mode_manager.wiring["ToyA"]
        assert wiring["motor_count"] == 2
        assert wiring["motor_0_zones"] == "Boob"
        assert "1" in h.mode_manager.modes[1]["mix"]["ToyA"]

    def test_seeding_is_idempotent_on_disk(self, isolated):
        h = _host(isolated)
        h.mode_manager.known_devices.devices = {
            "ToyA": {"motor_count": 1, "motor_kinds": None}}
        h._seed_known_devices()
        before = (isolated / "profiles.json").read_text("utf-8")
        h._seed_known_devices()
        assert (isolated / "profiles.json").read_text("utf-8") == before


class TestSwitching:
    def test_switch_resets_every_dispatch_cache(self, isolated):
        h = _host(isolated)
        h.switch_mode(1)
        assert h.motor_router.resets == 1
        assert h.steamvr_router.resets == 1
        assert h.bhaptics_router.resets == 1
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
        h._on_ogp_mode_osc(4)
        assert h.mode_manager.get_active_mode_index() == 4

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
        h.switch_mode(3)          # sends 3, records it
        h.switch_mode(5)          # sends 5, records it
        h._on_ogp_mode_osc(3)     # stale echo of the first send
        assert h.mode_manager.get_active_mode_index() == 5
        h._on_ogp_mode_osc(5)     # echo of the second send: no-op anyway
        assert h.mode_manager.get_active_mode_index() == 5


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

    def test_sets_sync_guard_and_reasserts(self, isolated):
        h = _host(isolated)
        h._on_avatar_change("avtr_a")
        assert h._ogp_mode_guard_until > time.monotonic()
        assert h.osc_manager.sent[-1][0] == "/avatar/parameters/OGP/Mode"
        assert h.bhaptics_bool_sends == 1


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
