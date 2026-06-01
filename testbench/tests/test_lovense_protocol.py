"""Tests for the virtual-toy Lovense protocol decoder.

Covers the pure, I/O-free core in `testbench.toy.lovense_protocol`: the WSDM
handshake JSON, the `DeviceType;` / `Battery;` query replies, and decoding
each motor command into normalised 0..1 levels for every model in the menu.
No websocket, Intiface, or Qt is touched.

Run from the repo root:  pytest testbench
"""

import json

import pytest

from testbench.toy.lovense_protocol import (
    DEFAULT_WS_IDENTIFIER,
    MODELS,
    MODELS_BY_NAME,
    LovenseProtocol,
    random_address,
)


def _proto(model_name: str, **kw) -> LovenseProtocol:
    return LovenseProtocol(MODELS_BY_NAME[model_name], "AABBCCDDEEFF", **kw)


def _levels(proto: LovenseProtocol, frame: str):
    """Run one frame and return just the (idx, level) update list."""
    updates, _resp, _logs = proto.process_command(frame.encode("ascii"))
    return updates


# ============================================================ model menu

class TestModelMenu:
    def test_names_are_unique(self):
        names = [m.name for m in MODELS]
        assert len(names) == len(set(names))

    def test_lookup_matches_tuple(self):
        for m in MODELS:
            assert MODELS_BY_NAME[m.name] is m

    def test_random_address_is_12_hex(self):
        addr = random_address()
        assert len(addr) == 12
        assert all(c in "0123456789ABCDEF" for c in addr)


# ============================================================ handshake

class TestHandshake:
    def test_handshake_has_three_required_fields(self):
        proto = _proto("Lovense Hush", ws_identifier="OGPSim")
        doc = json.loads(proto.handshake_text())
        assert doc == {
            "identifier": "OGPSim",
            "address": "AABBCCDDEEFF",
            "version": 0,
        }

    def test_default_identifier(self):
        proto = _proto("Lovense Hush")
        assert json.loads(proto.handshake_text())["identifier"] == DEFAULT_WS_IDENTIFIER


# ============================================================ queries

class TestQueries:
    def test_device_type_reply_shape(self):
        proto = _proto("Lovense Nora")  # letter "A", firmware "11"
        _u, resp, _l = proto.process_command(b"DeviceType;")
        assert resp == b"A:11:AABBCCDDEEFF;"

    def test_device_type_pads_short_address(self):
        proto = LovenseProtocol(MODELS_BY_NAME["Lovense Hush"], "1234")
        _u, resp, _l = proto.process_command(b"DeviceType;")
        assert resp == b"Z:11:123400000000;"

    def test_battery_reply_uses_current_pct(self):
        proto = _proto("Lovense Hush", battery_pct=42)
        _u, resp, _l = proto.process_command(b"Battery;")
        assert resp == b"42;"

    def test_battery_reply_tracks_setter_value(self):
        proto = _proto("Lovense Hush", battery_pct=90)
        proto.battery_pct = 5
        _u, resp, _l = proto.process_command(b"Battery;")
        assert resp == b"5;"


# ============================================================ vibrate

class TestVibrate:
    def test_single_vibrator_normalises_to_max_20(self):
        proto = _proto("Lovense Hush")
        assert _levels(proto, "Vibrate:10;") == [(0, pytest.approx(0.5))]
        assert proto.levels[0] == pytest.approx(0.5)

    def test_vibrate_full_scale(self):
        proto = _proto("Lovense Hush")
        assert _levels(proto, "Vibrate:20;") == [(0, pytest.approx(1.0))]

    def test_over_range_clamps_to_one(self):
        proto = _proto("Lovense Hush")
        assert _levels(proto, "Vibrate:99;") == [(0, pytest.approx(1.0))]

    def test_dual_vibrator_indexes_by_suffix(self):
        proto = _proto("Lovense Edge")
        assert _levels(proto, "Vibrate1:20;") == [(0, pytest.approx(1.0))]
        assert _levels(proto, "Vibrate2:10;") == [(1, pytest.approx(0.5))]

    def test_bare_vibrate_hits_first_vibrator(self):
        proto = _proto("Lovense Edge")
        assert _levels(proto, "Vibrate:20;") == [(0, pytest.approx(1.0))]

    def test_non_numeric_value_ignored(self):
        proto = _proto("Lovense Hush")
        assert _levels(proto, "Vibrate:abc;") == []


# ============================================================ rotate

class TestRotate:
    def test_rotate_targets_rotate_feature(self):
        proto = _proto("Lovense Nora")  # idx0 vibrate, idx1 rotate
        assert _levels(proto, "Rotate:5;") == [(1, pytest.approx(0.25))]

    def test_rotate_change_toggles_direction(self):
        proto = _proto("Lovense Nora")
        assert proto.rotate_dir == 1
        proto.process_command(b"RotateChange;")
        assert proto.rotate_dir == -1
        proto.process_command(b"RotateChange;")
        assert proto.rotate_dir == 1

    def test_rotate_ignored_when_no_rotate_feature(self):
        proto = _proto("Lovense Hush")  # vibrate-only
        assert _levels(proto, "Rotate:5;") == []


# ============================================================ air pump

class TestAirPump:
    def test_air_level_normalises_to_max_3(self):
        proto = _proto("Lovense Max")  # idx0 vibrate, idx1 air (max_raw 3)
        assert _levels(proto, "Air:Level:3;") == [(1, pytest.approx(1.0))]
        assert _levels(proto, "Air:Level:0;") == [(1, pytest.approx(0.0))]

    def test_relative_air_nudge_sets_no_level(self):
        proto = _proto("Lovense Max")
        assert _levels(proto, "Air:In:1;") == []
        assert _levels(proto, "Air:Out:1;") == []


# ============================================================ stroker

class TestStroker:
    def test_fsetsite_position_normalises_to_max_100(self):
        proto = _proto("Lovense Solace Pro")
        assert _levels(proto, "FSetSite:50;") == [(0, pytest.approx(0.5))]
        assert _levels(proto, "FSetSite:100;") == [(0, pytest.approx(1.0))]

    def test_mply_speed_maps_onto_first_output(self):
        proto = _proto("Lovense Solace Pro")  # cap 100, used directly as raw
        assert _levels(proto, "Mply:50:5;") == [(0, pytest.approx(0.5))]


# ============================================================ framing

class TestFraming:
    def test_multiple_commands_in_one_frame(self):
        proto = _proto("Lovense Edge")
        updates = _levels(proto, "Vibrate1:20;Vibrate2:10;")
        assert updates == [(0, pytest.approx(1.0)), (1, pytest.approx(0.5))]

    def test_blank_tokens_skipped(self):
        proto = _proto("Lovense Hush")
        # leading/trailing/duplicate separators must not crash or log blanks
        _u, _r, logs = proto.process_command(b";;Vibrate:10;;")
        assert logs == ["Vibrate:10;"]

    def test_unknown_command_logged_but_inert(self):
        proto = _proto("Lovense Hush")
        updates, resp, logs = proto.process_command(b"Foobar:5;")
        assert updates == []
        assert resp is None
        assert logs == ["Foobar:5;"]

    def test_invalid_utf8_does_not_break_following_command(self):
        proto = _proto("Lovense Hush")
        # A stray non-UTF-8 byte run as its own token must be replace-decoded
        # (never raise) and skipped, leaving a later valid command intact.
        updates, _resp, _logs = proto.process_command(b"\xff\xfe;Vibrate:10;")
        assert updates == [(0, pytest.approx(0.5))]
