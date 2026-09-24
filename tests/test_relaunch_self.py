"""utilities.relaunch_self — the restart after a colour-mode switch or a
settings restore.

A one-file exe's child inherits the _PYI_* variables and reuses the parent's
unpacked _MEI folder, which is deleted as the parent exits: the restarted
app died on "No module named 'pydantic_core._pydantic_core'". The frozen
relaunch must ask PyInstaller for a fresh unpack.
"""
import sys

import utilities


def _capture(monkeypatch):
    seen = {}

    def fake_popen(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return object()
    monkeypatch.setattr(utilities.subprocess, "Popen", fake_popen)
    return seen


def test_frozen_relaunch_unpacks_its_own_copy(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\OscGoesPurrr.exe")
    monkeypatch.setattr(sys, "argv", [r"C:\Apps\OscGoesPurrr.exe"])
    utilities.relaunch_self()
    assert seen["cmd"] == [r"C:\Apps\OscGoesPurrr.exe"]
    assert seen["kwargs"]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"


def test_source_relaunch_keeps_the_environment(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.delattr(sys, "frozen", raising=False)
    utilities.relaunch_self()
    assert seen["kwargs"]["env"] is None
