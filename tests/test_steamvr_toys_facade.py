"""The controller side of "Show toys in SteamVR" (steamvr_toys_facade.py).

A stand-in host with fake settings, engine and bridge: the facade is on by
default, stays out of the way on a PC without SteamVR, mirrors the
connected toys (serial, icon, battery) into the bridge while it is on,
takes the driver out of SteamVR when switched off, and reports what the
Settings page should say next.
"""

import pytest

import steamvr_toy_driver_installer as installer
from controllers import steamvr_toys_facade as facade_mod
from controllers.steamvr_toys_facade import SETTING_KEY, SteamVRToysFacade


class _Settings(dict):
    def set(self, key, value):
        self[key] = value


class _Modes:
    def __init__(self, enabled):
        values = {} if enabled is None else {SETTING_KEY: enabled}
        self.app_settings = _Settings(values)

    def get_profile_config(self, device_name, key, default=None):
        return default


class _Engine:
    def __init__(self, names):
        self.names = names

    def list_connected_device_names(self):
        return list(self.names)


class _Bridge:
    def __init__(self):
        self.running = False
        self.sent = []
        self.batteries = []

    def set_logger(self, fn):
        pass

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def set_devices(self, entries):
        self.sent.append([(e.serial, e.name, e.icon_key, e.battery) for e in entries])

    def clear_devices(self):
        self.sent.append([])

    def update_battery(self, serial, level):
        self.batteries.append((serial, level))

    is_connected = False


class _Host(SteamVRToysFacade):
    def __init__(self, enabled, names=("Lovense Gush",)):
        self.mode_manager = _Modes(enabled)
        self.haptic_engine = _Engine(names)
        self.logged = []
        self.ui = None

    def log_message(self, msg):
        self.logged.append(msg)


@pytest.fixture(autouse=True)
def fake_installer(monkeypatch):
    calls = {"install": 0, "uninstall": 0}

    def install(log):
        calls["install"] += 1

    def uninstall(log=None, remove_files=False):
        calls["uninstall"] += 1
        return True

    monkeypatch.setattr(facade_mod, "SteamVRToyBridge", _Bridge)
    monkeypatch.setattr(facade_mod, "driver_listening", lambda: True)
    monkeypatch.setattr(installer, "is_supported", lambda: True)
    monkeypatch.setattr(installer, "steamvr_present", lambda: True)
    monkeypatch.setattr(installer, "is_installed", lambda: True)
    monkeypatch.setattr(installer, "needs_update", lambda: False)
    monkeypatch.setattr(installer, "install_or_raise", install)
    monkeypatch.setattr(installer, "uninstall", uninstall)
    monkeypatch.setattr(installer, "resolve_installed_icon_path",
                        lambda name: f"C:/icons/{name}")
    return calls


def _host(enabled, **kw):
    host = _Host(enabled, **kw)
    host._steamvr_toys_init()
    return host


def test_on_by_default():
    host = _host(None)            # a settings file that has never seen the key
    assert host._steamvr_toy_bridge.running
    assert host._steamvr_toy_bridge.sent[-1][0][0] == "OGP_TOY_LOVENSE_GUSH"
    assert host.get_steamvr_toys_status()["enabled"] is True


def test_no_steamvr_leaves_everything_alone(monkeypatch, fake_installer):
    monkeypatch.setattr(installer, "steamvr_present", lambda: False)
    monkeypatch.setattr(installer, "is_installed", lambda: False)
    host = _host(True)
    assert fake_installer["install"] == 0
    assert not host._steamvr_toy_bridge.running
    status = host.set_steamvr_toys_enabled(True)
    assert status["error_kind"] == "no_steamvr"
    assert fake_installer["install"] == 0
    assert not host._steamvr_toy_bridge.running


def test_switched_off_does_nothing():
    host = _host(False)
    host.steamvr_toys_on_devices_changed()
    assert host._steamvr_toy_bridge.sent == []
    assert host.get_steamvr_toys_status()["enabled"] is False


def test_switching_on_sends_the_connected_toys():
    host = _host(False, names=("Lovense Gush", "Mystery Toy"))
    status = host.set_steamvr_toys_enabled(True)
    bridge = host._steamvr_toy_bridge
    assert bridge.running
    assert bridge.sent[-1] == [
        ("OGP_TOY_LOVENSE_GUSH", "Lovense Gush", "gush_2", 1.0),
        ("OGP_TOY_MYSTERY_TOY", "Mystery Toy", "", 1.0),
    ]
    assert status["enabled"] is True and status["error_kind"] == ""
    assert status["driver_loaded"] is True


def test_switching_on_says_when_steamvr_has_not_loaded_the_driver(monkeypatch):
    monkeypatch.setattr(facade_mod, "driver_listening", lambda: False)
    host = _host(False)
    assert host.set_steamvr_toys_enabled(True)["driver_loaded"] is False


def test_switching_on_again_reinstalls_what_off_removed(monkeypatch, fake_installer):
    host = _host(True)
    host.set_steamvr_toys_enabled(False)
    monkeypatch.setattr(installer, "is_installed", lambda: False)
    status = host.set_steamvr_toys_enabled(True)
    assert fake_installer["install"] == 1
    assert status["installed_now"] is True


def test_battery_reaches_the_bridge_and_the_next_list():
    host = _host(True)
    host.steamvr_toys_on_battery("Lovense Gush", 0.4)
    assert host._steamvr_toy_bridge.batteries == [("OGP_TOY_LOVENSE_GUSH", 0.4)]
    host.steamvr_toys_on_devices_changed()
    assert host._steamvr_toy_bridge.sent[-1][0][3] == 0.4


def test_switching_off_clears_the_list_stops_and_leaves_steamvr(fake_installer):
    host = _host(True)
    host.set_steamvr_toys_enabled(False)
    assert host._steamvr_toy_bridge.sent[-1] == []
    assert not host._steamvr_toy_bridge.running
    assert fake_installer["uninstall"] == 1
    assert host.mode_manager.app_settings[SETTING_KEY] is False


def test_a_locked_driver_is_reported(monkeypatch):
    host = _host(False)
    monkeypatch.setattr(installer, "is_installed", lambda: False)

    def locked(log):
        raise installer.InstallError("dll_locked", "SteamVR has it open")
    monkeypatch.setattr(installer, "install_or_raise", locked)
    status = host.set_steamvr_toys_enabled(True)
    assert status["error_kind"] == "dll_locked"
    assert status["installed_now"] is False


def test_serials_are_stable_and_safe():
    assert SteamVRToysFacade.steamvr_toy_serial("Lovense Gush") == "OGP_TOY_LOVENSE_GUSH"
    assert SteamVRToysFacade.steamvr_toy_serial("") == "OGP_TOY_TOY"
    assert len(SteamVRToysFacade.steamvr_toy_serial("x" * 200)) == 64
