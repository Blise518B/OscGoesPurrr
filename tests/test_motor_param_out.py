"""Tests for the per-motor 'mirror to VRChat parameter' resolver
(motor_param_out.py).

Pure mapping config -> (osc address, value); no engine, no thread, no OSC
socket, no AppData. Covers the enable gate, address normalisation, the
0..1 clamp, and bad input.
"""

import pytest

from motor_param_out import param_out_keys, resolve_param_out


class TestParamOutKeys:
    def test_key_names(self):
        assert param_out_keys(0) == (
            "motor_0_param_out_enabled",
            "motor_0_param_out_address",
        )
        assert param_out_keys(3) == (
            "motor_3_param_out_enabled",
            "motor_3_param_out_address",
        )


def _cfg(idx=0, enabled=True, address="TailWag"):
    enabled_key, address_key = param_out_keys(idx)
    return {enabled_key: enabled, address_key: address}


class TestResolveParamOut:
    def test_enabled_returns_full_address_and_value(self):
        out = resolve_param_out(_cfg(address="TailWag"), 0, 0.5)
        assert out == ("/avatar/parameters/TailWag", 0.5)

    def test_disabled_returns_none(self):
        assert resolve_param_out(_cfg(enabled=False), 0, 0.5) is None

    def test_missing_keys_default_off(self):
        assert resolve_param_out({}, 0, 0.5) is None

    def test_blank_address_returns_none(self):
        assert resolve_param_out(_cfg(address=""), 0, 0.5) is None
        assert resolve_param_out(_cfg(address="   "), 0, 0.5) is None

    def test_full_path_is_stripped_then_re_added(self):
        out = resolve_param_out(
            _cfg(address="/avatar/parameters/Glow"), 0, 0.25
        )
        assert out == ("/avatar/parameters/Glow", 0.25)

    def test_leading_slash_stripped(self):
        out = resolve_param_out(_cfg(address="/Glow"), 0, 0.25)
        assert out == ("/avatar/parameters/Glow", 0.25)

    def test_value_clamped_high(self):
        _addr, v = resolve_param_out(_cfg(), 0, 1.7)
        assert v == 1.0

    def test_value_clamped_low(self):
        _addr, v = resolve_param_out(_cfg(), 0, -0.3)
        assert v == 0.0

    def test_non_numeric_value_returns_none(self):
        assert resolve_param_out(_cfg(), 0, None) is None
        assert resolve_param_out(_cfg(), 0, "nope") is None

    def test_per_motor_isolation(self):
        # Config for motor 1 only; motor 0 must not pick it up.
        cfg = _cfg(idx=1, address="Tail")
        assert resolve_param_out(cfg, 0, 0.5) is None
        assert resolve_param_out(cfg, 1, 0.5) == ("/avatar/parameters/Tail", 0.5)

    def test_non_dict_config_returns_none(self):
        assert resolve_param_out(None, 0, 0.5) is None
        assert resolve_param_out("not a dict", 0, 0.5) is None
