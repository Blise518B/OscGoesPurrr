"""Tests for the bench's persistent settings store.

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


def test_get_set_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("OGP_TESTBENCH_STATE", str(tmp_path / "s.json"))
    assert state.get("waveform") is None              # unset -> None
    assert state.get("waveform", "square") == "square"  # default honoured
    state.set("waveform", "sine")
    state.set("frequency", 1.4)
    state.set("cycles", 30)
    assert state.get("waveform") == "sine"            # persisted across loads
    assert state.get("frequency") == 1.4
    assert state.get("cycles") == 30


def test_set_does_not_clobber_toy_addresses(tmp_path, monkeypatch):
    monkeypatch.setenv("OGP_TESTBENCH_STATE", str(tmp_path / "s.json"))
    addr = state.toy_address("Lovense Hush")
    state.set("waveform", "square")       # writing a setting must not drop addrs
    assert state.toy_address("Lovense Hush") == addr


def test_missing_file_degrades_gracefully(tmp_path, monkeypatch):
    monkeypatch.setenv("OGP_TESTBENCH_STATE", str(tmp_path / "nope.json"))
    assert state.get("anything") is None          # no file -> default, no crash
    assert state.get("anything", 5) == 5
    assert len(state.toy_address("X")) == 12
