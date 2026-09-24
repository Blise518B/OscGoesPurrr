"""Installing the SteamVR toy driver (steamvr_toy_driver_installer.py).

Runs against a throwaway LOCALAPPDATA, so neither the real driver folder
nor the real openvrpaths.vrpath is touched. The load-bearing rule: other
apps' entries in openvrpaths.vrpath (Space Calibrator, SlimeVR, ...) must
survive every install and uninstall, and an unreadable file is never
overwritten — a broken one stops SteamVR from starting.
"""

import json
import sys

import pytest

import steamvr_toy_driver_installer as installer

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="the toy driver is Windows-only")

OTHER = "D:\\SteamLibrary\\steamapps\\common\\SlimeVR"


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def _vrpath(appdata):
    return json.loads((appdata / "openvr" / "openvrpaths.vrpath").read_text(encoding="utf-8"))


def test_steamvr_present_only_once_steamvr_has_run(appdata):
    # SteamVR writes openvrpaths.vrpath on its first start; before that the
    # feature (on by default) must not touch anything.
    assert installer.steamvr_present() is False
    paths = appdata / "openvr" / "openvrpaths.vrpath"
    paths.parent.mkdir(parents=True)
    paths.write_text('{"external_drivers": []}', encoding="utf-8")
    assert installer.steamvr_present() is True


def test_install_lays_out_the_driver_and_registers_it(appdata):
    installer.install_or_raise(lambda m: None)
    root = installer.driver_install_root()
    assert (root / "bin" / "win64" / "driver_oscgoespurrr.dll").is_file()
    assert (root / "driver.vrdrivermanifest").is_file()
    assert (root / "resources" / "input" / "oscgoespurrr_toy_profile.json").is_file()
    assert installer.resolve_installed_icon_path("gush_2.png")
    assert str(root) in _vrpath(appdata)["external_drivers"]
    assert installer.is_installed()


def test_other_drivers_survive_install_and_uninstall(appdata):
    paths = appdata / "openvr" / "openvrpaths.vrpath"
    paths.parent.mkdir(parents=True)
    paths.write_text(json.dumps({"external_drivers": [OTHER], "jsonid": "vrpathreg",
                                 "runtime": ["C:\\SteamVR"], "version": 1}), encoding="utf-8")
    installer.install_or_raise(lambda m: None)
    installer.install_or_raise(lambda m: None)          # idempotent: no duplicate
    ext = _vrpath(appdata)["external_drivers"]
    assert ext == [OTHER, str(installer.driver_install_root())]
    installer.uninstall()
    assert _vrpath(appdata)["external_drivers"] == [OTHER]
    assert _vrpath(appdata)["runtime"] == ["C:\\SteamVR"]


def test_an_unreadable_vrpath_is_never_overwritten(appdata):
    paths = appdata / "openvr" / "openvrpaths.vrpath"
    paths.parent.mkdir(parents=True)
    paths.write_text("{ not json", encoding="utf-8")
    with pytest.raises(installer.InstallError) as err:
        installer.install_or_raise(lambda m: None)
    assert err.value.kind == "register_failed"
    assert paths.read_text(encoding="utf-8") == "{ not json"
    assert paths.with_name(paths.name + ".bak").is_file()


def test_needs_update_spots_a_changed_or_missing_file(appdata):
    installer.install_or_raise(lambda m: None)
    assert installer.needs_update() is False
    settings = installer.driver_install_root() / "resources" / "settings" / "default.vrsettings"
    settings.write_text("{}", encoding="utf-8")
    assert installer.needs_update() is True
    installer.install_or_raise(lambda m: None)
    assert installer.needs_update() is False
    settings.unlink()
    assert installer.needs_update() is True


def test_the_shipped_driver_never_makes_toys_trackers():
    # The presentation the driver reads at start: a TrackingReference
    # (class 4) with no valid pose, so no app can use a toy as a tracker.
    shipped = installer._bundle_root() / "resources" / "settings" / "default.vrsettings"
    cfg = json.loads(shipped.read_text(encoding="utf-8"))["driver_oscgoespurrr"]
    assert cfg["toy_device_class"] == 4
    assert cfg["toy_pose_valid"] is False
    assert "trackers" not in json.loads(shipped.read_text(encoding="utf-8"))
