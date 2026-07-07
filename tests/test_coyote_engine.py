"""Tests for CoyoteEngine's software safety clamps (no BLE, no loop thread).

The BF frame pushes the user's per-channel limits to the hardware, but that
write is unacknowledged (response=False) — so the engine must ALSO enforce
the limits in software on every frame. These tests pin that second layer:
whatever a caller pushes into set_channel_strength, the strengths that reach
build_b0 (exposed via `strengths` / `_clamped_strengths`) never exceed
limit_a / limit_b, and a fresh session always starts from zero.
"""

from coyote_engine import CoyoteEngine
from coyote_protocol import STRENGTH_MAX


def _engine(**cfg) -> CoyoteEngine:
    eng = CoyoteEngine()
    if cfg:
        eng.configure(**cfg)
    return eng


class TestStrengthClamps:
    def test_absolute_max_clamp(self):
        eng = _engine()
        eng.set_channel_strength("A", 9999)
        assert eng._strength_a == STRENGTH_MAX

    def test_negative_clamps_to_zero(self):
        eng = _engine()
        eng.set_channel_strength("A", -5)
        assert eng._strength_a == 0

    def test_garbage_value_is_dropped(self):
        eng = _engine()
        eng.set_channel_strength("A", "abc")
        eng.set_channel_strength("A", None)
        assert eng._strength_a == 0

    def test_unknown_channel_ignored(self):
        eng = _engine()
        eng.set_channel_strength("C", 50)
        assert eng.strengths == (0, 0)


class TestSoftwareLimits:
    def test_output_clamped_to_channel_limits(self):
        # Even if the BF write was silently lost, the frame source must
        # respect the user's limits.
        eng = _engine(limit_a=50, limit_b=30)
        eng.set_channel_strength("A", 200)
        eng.set_channel_strength("B", 200)
        assert eng.strengths == (50, 30)

    def test_limits_apply_to_already_set_strengths(self):
        # Lowering a limit takes effect immediately on the live value.
        eng = _engine(limit_a=200, limit_b=200)
        eng.set_channel_strength("A", 180)
        eng.set_strength_limits(60, 60)
        assert eng.strengths == (60, 0)

    def test_configure_clamps_limits_to_absolute_max(self):
        eng = _engine(limit_a=9999, limit_b=-4)
        assert eng._limit_a == STRENGTH_MAX
        assert eng._limit_b == 0


class _FakeBleakClient:
    """Minimal async stand-in for bleak.BleakClient."""

    def __init__(self, address, disconnected_callback=None):
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.connected = False
        self.disconnect_calls = 0
        self.writes = []           # (uuid, bytes) pairs
        self.fail_writes = False

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.disconnect_calls += 1
        self.connected = False

    async def start_notify(self, _uuid, _cb):
        pass

    async def read_gatt_char(self, _uuid):
        return bytes([88])

    async def write_gatt_char(self, uuid, data, response=False):
        if self.fail_writes:
            raise RuntimeError("gatt write failed")
        self.writes.append((uuid, bytes(data)))


class TestOpenContract:
    """Pins the two safety behaviors of _open: a fresh session starts from
    zero strengths, and a failed BF (limits) write fails the whole connect
    with the client disconnected. No BLE — BleakClient is faked."""

    def _connect(self, monkeypatch, eng, client):
        import asyncio
        monkeypatch.setattr("coyote_engine.BleakClient",
                            lambda target, disconnected_callback=None: client)

        async def _resolve(_self=None):
            return "AA:BB"
        monkeypatch.setattr(eng, "_resolve_target", _resolve)

        async def run():
            await eng._open()
            # Tear down inside the same loop so the B0 task dies cleanly.
            await eng._close()
        asyncio.run(run())

    def test_open_zeroes_strengths_before_b0_starts(self, monkeypatch):
        eng = _engine(limit_a=200, limit_b=200)
        eng.set_channel_strength("A", 150)   # pre-disconnect leftover
        client = _FakeBleakClient("AA:BB")
        self._connect(monkeypatch, eng, client)
        # The leftover strength was zeroed during _open, so no B0 frame can
        # have replayed it.
        assert eng.strengths == (0, 0)

    def test_failed_bf_write_fails_the_connect(self, monkeypatch):
        import asyncio
        eng = _engine(limit_a=100, limit_b=100)
        client = _FakeBleakClient("AA:BB")
        client.fail_writes = True            # BF limits write raises
        monkeypatch.setattr("coyote_engine.BleakClient",
                            lambda target, disconnected_callback=None: client)

        async def _resolve(_self=None):
            return "AA:BB"
        monkeypatch.setattr(eng, "_resolve_target", _resolve)

        async def run():
            await eng._open()
        import pytest as _pytest
        with _pytest.raises(Exception):
            asyncio.run(run())
        assert eng.is_connected is False
        assert eng._client is None
        assert client.disconnect_calls >= 1  # no dangling BLE link

    def test_target_change_mid_dial_aborts_connect(self, monkeypatch):
        import asyncio
        eng = _engine()
        eng.configure(address="AA:BB")
        client = _FakeBleakClient("AA:BB")
        monkeypatch.setattr("coyote_engine.BleakClient",
                            lambda target, disconnected_callback=None: client)

        async def _resolve(_self=None):
            # User re-targets while we're mid-dial.
            eng._device_addr = "CC:DD"
            return "AA:BB"
        monkeypatch.setattr(eng, "_resolve_target", _resolve)

        import pytest as _pytest
        with _pytest.raises(RuntimeError, match="target changed"):
            asyncio.run(eng._open())
        assert eng.is_connected is False
        assert client.disconnect_calls >= 1

    def test_disconnect_callback_from_stale_client_is_ignored(self):
        eng = _engine()
        current = object()
        eng._client = current
        eng._connected = True
        eng._on_disconnect(object())         # a discarded client's callback
        assert eng._connected is True        # current session untouched
        eng._on_disconnect(current)          # the real client dropping
        assert eng._connected is False
