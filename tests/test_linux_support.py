"""The Linux build: where settings live, what system programs inherit from
a frozen build, how the AppImage restarts, the built-in engine's process
care, and the build files that have to agree with each other.

Everything runs on any OS: platform branches are taken by passing or
patching the platform, never by needing the real one.
"""

import os
import re
import sys
from pathlib import Path

import pytest

import intiface_integrated
import utilities
from settings import _paths

REPO = Path(__file__).resolve().parent.parent


def _read(*parts):
    return (REPO.joinpath(*parts)).read_text(encoding="utf-8")


# ------------------------------------------------------------ settings folder


class TestSettingsFolder:
    def test_windows_keeps_appdata_roaming(self):
        assert _paths._config_root("win32") == Path.home() / "AppData" / "Roaming"

    def test_linux_uses_dot_config(self, monkeypatch):
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert _paths._config_root("linux") == Path.home() / ".config"

    def test_linux_honours_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert _paths._config_root("linux") == tmp_path

    def test_a_relative_xdg_config_home_is_ignored(self, monkeypatch):
        # The XDG spec says a relative value is invalid.
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative/dir")
        assert _paths._config_root("linux") == Path.home() / ".config"

    def test_help_texts_name_this_platforms_folder(self):
        from constants import SETTINGS_DIR_DISPLAY
        if sys.platform == "win32":
            assert SETTINGS_DIR_DISPLAY == "%APPDATA%\\OscGoesPurrr"
        else:
            assert SETTINGS_DIR_DISPLAY == "~/.config/OscGoesPurrr"


# ------------------------------------------- environment for system programs


@pytest.fixture
def frozen_linux(monkeypatch, tmp_path):
    """A frozen Linux build whose bundle is tmp_path/_internal."""
    bundle = str(tmp_path / "_internal")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", bundle, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    return bundle


class TestSystemEnv:
    def test_restores_the_original_library_path(self, frozen_linux, monkeypatch):
        monkeypatch.setenv("LD_LIBRARY_PATH", frozen_linux)
        monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/opt/mine")
        env = utilities.system_env()
        assert env["LD_LIBRARY_PATH"] == "/opt/mine"
        assert "LD_LIBRARY_PATH_ORIG" not in env

    def test_drops_a_library_path_that_only_points_into_the_bundle(
            self, frozen_linux, monkeypatch):
        monkeypatch.setenv("LD_LIBRARY_PATH", frozen_linux)
        monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
        assert "LD_LIBRARY_PATH" not in utilities.system_env()

    def test_drops_qt_and_pyinstaller_variables_of_the_bundle(
            self, frozen_linux, monkeypatch):
        monkeypatch.setenv("QT_PLUGIN_PATH", frozen_linux + "/PySide6/plugins")
        monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", frozen_linux)
        monkeypatch.setenv("HOME_STAYS", "/home/someone")
        env = utilities.system_env()
        assert "QT_PLUGIN_PATH" not in env
        assert "_PYI_APPLICATION_HOME_DIR" not in env
        assert env["HOME_STAYS"] == "/home/someone"

    def test_windows_and_source_runs_get_the_environment_unchanged(
            self, monkeypatch):
        monkeypatch.setenv("LD_LIBRARY_PATH", "/x")
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert utilities.system_env()["LD_LIBRARY_PATH"] == "/x"
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        assert utilities.system_env()["LD_LIBRARY_PATH"] == "/x"


class TestOpenFolder:
    def test_linux_uses_xdg_open_with_the_system_environment(
            self, frozen_linux, monkeypatch):
        seen = {}

        def fake_popen(cmd, **kwargs):
            seen["cmd"], seen["env"] = cmd, kwargs["env"]
            return object()

        monkeypatch.setenv("LD_LIBRARY_PATH", frozen_linux)
        monkeypatch.setattr(utilities.subprocess, "Popen", fake_popen)
        utilities.open_folder("/home/someone/.config/OscGoesPurrr")
        assert seen["cmd"] == ["xdg-open", "/home/someone/.config/OscGoesPurrr"]
        assert "LD_LIBRARY_PATH" not in seen["env"]


# ------------------------------------------------------------ AppImage


class TestAppImageRelaunch:
    def test_restart_starts_the_appimage_not_the_mounted_binary(
            self, frozen_linux, monkeypatch, tmp_path):
        # The mount sys.executable lives in disappears when we exit.
        appimage = tmp_path / "OscGoesPurrr-Linux-x86_64.AppImage"
        appimage.write_bytes(b"x")
        monkeypatch.setenv("APPIMAGE", str(appimage))
        monkeypatch.setattr(sys, "executable", "/tmp/.mount_X/usr/lib/OscGoesPurrr/OscGoesPurrr")
        monkeypatch.setattr(sys, "argv", [sys.executable, "--flag"])
        seen = {}

        def fake_popen(cmd, **kwargs):
            seen["cmd"], seen["env"] = cmd, kwargs["env"]
            return object()

        monkeypatch.setattr(utilities.subprocess, "Popen", fake_popen)
        utilities.relaunch_self()
        assert seen["cmd"] == [str(appimage), "--flag"]
        assert seen["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"

    def test_no_appimage_on_windows_or_from_source(self, monkeypatch, tmp_path):
        appimage = tmp_path / "a.AppImage"
        appimage.write_bytes(b"x")
        monkeypatch.setenv("APPIMAGE", str(appimage))
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert utilities.running_appimage() is None
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        assert utilities.running_appimage() is None


# ------------------------------------------------------------ built-in engine


class TestEngineProcess:
    def test_no_preexec_hook_off_linux(self, monkeypatch):
        monkeypatch.setattr(intiface_integrated.sys, "platform", "win32")
        assert intiface_integrated._die_with_parent() is None

    @pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs Linux libc")
    def test_linux_gets_a_parent_death_hook(self):
        assert callable(intiface_integrated._die_with_parent())

    @pytest.mark.skipif(os.name != "posix", reason="exec bits are POSIX")
    def test_a_lost_exec_bit_is_restored(self, tmp_path):
        engine = tmp_path / "intiface-engine"
        engine.write_bytes(b"#!/bin/sh\n")
        os.chmod(engine, 0o644)
        intiface_integrated._ensure_executable(engine)
        assert os.stat(engine).st_mode & 0o100


# ------------------------------------------------------------ build files


class TestBuildFilesAgree:
    def test_the_appimage_bundles_the_license_and_notices(self):
        script = _read("tools", "build_linux.sh")
        assert '--add-data "$ROOT/LICENSE:."' in script
        assert '--add-data "$ROOT/THIRD_PARTY_NOTICES.md:."' in script
        assert '--add-data "$ROOT/src/intiface-engine:intiface-engine"' in script

    def test_the_notice_names_one_buttplug_commit_for_both_engines(self):
        # build_linux.sh and the workflow's cache key grep the first one.
        commits = set(re.findall(r"buttplug/tree/([0-9a-f]{40})",
                                 _read("THIRD_PARTY_NOTICES.md")))
        assert len(commits) == 1

    def test_the_engine_lock_copy_is_there(self):
        lock = _read("tools", "intiface-engine-Cargo.lock")
        assert 'name = "intiface-engine"' in lock

    def test_the_workflow_runs_the_build_script_and_attaches_both_files(self):
        wf = _read(".github", "workflows", "linux.yml")
        assert "bash tools/build_linux.sh" in wf
        assert "types: [published]" in wf
        assert "dist/OscGoesPurrr-Linux-x86_64.AppImage.zsync" in wf

    def test_shell_scripts_check_out_with_lf(self):
        assert "*.sh text eol=lf" in _read(".gitattributes")
