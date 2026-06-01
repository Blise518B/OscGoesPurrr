"""Tests for the bench's persistent toy-identity state.

The state file path is redirected via the OGP_TESTBENCH_STATE env var so the
tests never touch the real %APPDATA% file.
"""

from __future__ import annotations

from testbench import state


def test_toy_address_is_stable_per_model(tmp_path, monkeypatch):
    monkeypatch.setenv("OGP_TESTBENCH_STATE", str(tmp_path / "s.json"))
    a1 = state.toy_address("Lovense Hush")
    a2 = state.toy_address("Lovense Hush")
    assert a1 == a2                      # same model -> same address
    assert len(a1) == 12                 # 12-hex fake MAC
    b = state.toy_address("Lovense Lush")
    assert b != a1                       # different model -> own address
    # survives a fresh load (persisted to disk, not just memoised)
    assert state.toy_address("Lovense Hush") == a1


def test_remember_and_last_toy_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("OGP_TESTBENCH_STATE", str(tmp_path / "s.json"))
    assert state.last_toy() == {}
    state.remember_toy("Lovense Hush", "OGPSim", "ws://127.0.0.1:54817")
    lt = state.last_toy()
    assert lt == {
        "model": "Lovense Hush",
        "identifier": "OGPSim",
        "url": "ws://127.0.0.1:54817",
    }
    # remembering the toy must not disturb saved addresses
    addr = state.toy_address("Lovense Hush")
    state.remember_toy("Lovense Lush", "OGPSim", "ws://127.0.0.1:54817")
    assert state.toy_address("Lovense Hush") == addr


def test_missing_file_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setenv("OGP_TESTBENCH_STATE", str(tmp_path / "does_not_exist.json"))
    assert state.last_toy() == {}          # no file -> empty, no crash
    assert len(state.toy_address("X")) == 12
