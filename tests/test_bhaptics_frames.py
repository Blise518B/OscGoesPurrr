"""Golden-frame tests for BHapticsEngine.submit_dot_frame — pin the exact
JSON wire payload sent to the bHaptics Player (ws://…/v2/feedbacks, dot
mode, HerpDerpinstine/bHapticsOSC v1.0.0 schema). The Player is strict
about this shape, and every router-level test fakes the engine — so a
silent payload drift would stay green in CI while failing on real
hardware. Pure: no websocket, no threads."""

import json

from bhaptics_engine import BHapticsEngine, NODE_COUNTS
from bhaptics_router import device_table


class _FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, body):
        self.sent.append(body)

    def close(self):
        self.closed = True


class _ExplodingWS(_FakeWS):
    def send(self, body):
        raise RuntimeError("socket is already closed")


def _engine(ws=None):
    eng = BHapticsEngine()
    eng._connected = True
    eng._ws = _FakeWS() if ws is None else ws
    return eng


def _frame(body: str) -> dict:
    """Unwrap the single Submit entry's Frame from a sent body."""
    payload = json.loads(body)
    (entry,) = payload["Submit"]
    return entry


class TestGoldenFrame:
    def test_exact_wire_bytes(self):
        # The full serialized payload, byte for byte: key order, separators,
        # zero filtering, 0-based indices, and the 100 ms frame duration.
        ws = _FakeWS()
        eng = _engine(ws)
        eng.submit_dot_frame("Head", [0, 50, 100, 0, 25, 0])
        assert ws.sent == [
            '{"Submit": [{"Type": "frame", "Key": "oscgoespurrr_Head", '
            '"Frame": {"position": "Head", "dotPoints": ['
            '{"index": 1, "intensity": 50}, '
            '{"index": 2, "intensity": 100}, '
            '{"index": 4, "intensity": 25}], '
            '"durationMillis": 100}}]}'
        ]

    def test_all_zero_frame_is_still_submitted(self):
        # A zero frame is what silences a device (the router sends one when
        # a device is disabled) — it must go out, with an empty dot list.
        ws = _FakeWS()
        eng = _engine(ws)
        eng.submit_dot_frame("HandL", [0, 0, 0])
        frame = _frame(ws.sent[0])["Frame"]
        assert frame["dotPoints"] == []
        assert frame["position"] == "HandL"

    def test_intensities_clamp_to_0_100(self):
        ws = _FakeWS()
        eng = _engine(ws)
        eng.submit_dot_frame("FootR", [-5, 250, 30])
        frame = _frame(ws.sent[0])["Frame"]
        # -5 clamps to 0 and is filtered out; 250 clamps to 100.
        assert frame["dotPoints"] == [
            {"index": 1, "intensity": 100},
            {"index": 2, "intensity": 30},
        ]

    def test_float_intensities_truncate_to_int(self):
        # int() truncation, not rounding — pin it either way so a change
        # is a conscious decision (the Player rejects non-integer values).
        ws = _FakeWS()
        eng = _engine(ws)
        eng.submit_dot_frame("HandR", [50.9, 0.4, 0])
        frame = _frame(ws.sent[0])["Frame"]
        assert frame["dotPoints"] == [{"index": 0, "intensity": 50}]

    def test_key_is_unique_per_position(self):
        # Distinct Submit keys per device: the Player replaces frames by
        # Key, so sharing one would let the vest cancel the head.
        ws = _FakeWS()
        eng = _engine(ws)
        eng.submit_dot_frame("VestFront", [10] + [0] * 19)
        eng.submit_dot_frame("VestBack", [10] + [0] * 19)
        keys = [_frame(b)["Key"] for b in ws.sent]
        assert keys == ["oscgoespurrr_VestFront", "oscgoespurrr_VestBack"]


class TestSubmitGuards:
    def test_not_connected_sends_nothing(self):
        ws = _FakeWS()
        eng = _engine(ws)
        eng._connected = False
        eng.submit_dot_frame("Head", [100] * 6)
        assert ws.sent == []

    def test_unknown_position_sends_nothing(self):
        ws = _FakeWS()
        eng = _engine(ws)
        eng.submit_dot_frame("Tail", [100])
        assert ws.sent == []

    def test_missing_socket_is_a_quiet_noop(self):
        eng = _engine()
        eng._ws = None
        eng.submit_dot_frame("Head", [100] * 6)  # must not raise

    def test_send_failure_tears_down_the_connection(self):
        # A dead socket must flip the engine to disconnected (so the
        # reconnect loop takes over) and close/drop the socket — not
        # leave a half-open connection swallowing frames.
        ws = _ExplodingWS()
        eng = _engine(ws)
        eng.submit_dot_frame("Head", [100] * 6)
        assert eng.is_connected is False
        assert "send failed" in (eng.last_error or "")
        assert ws.closed is True
        assert eng._ws is None


class TestSchemaConsistency:
    def test_router_table_matches_engine_node_counts(self):
        # The router sizes its dot arrays from _DEVICE_TABLE while the
        # engine validates positions against NODE_COUNTS — they must agree
        # or frames get dropped / mis-sized silently.
        table = {pos: count for pos, _slot, count in device_table()}
        assert table == NODE_COUNTS
