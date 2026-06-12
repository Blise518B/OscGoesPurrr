"""Tests for PiShockEngine.fire() — the last safety gate before the wire.

The guarantee under test: even when handed illegal values (or a hostile
settings file), the sealed engine re-clamps intensity + duration and enforces
the global min-interval, so nothing downstream can exceed the caps. A fake
provider captures what would have hit the transport; a fake clock drives the
cooldown deterministically."""

from pishock_engine import PiShockEngine


class FakeProvider:
    is_available = True
    status_label = "fake"

    def __init__(self):
        self.ops = []
        self.ended = 0

    def configure(self, cfg):
        self.cfg = cfg

    def prepare(self):
        return True

    def operate(self, op, intensity, duration_ms):
        self.ops.append((op, intensity, duration_ms))

    def end(self):
        self.ended += 1

    def shutdown(self):
        pass


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _engine(clk, **caps):
    eng = PiShockEngine(clock=clk)
    eng._provider = FakeProvider()
    eng._connected = True
    base = {"max_intensity": 50, "max_duration_ms": 5000, "min_interval_s": 0.5}
    base.update(caps)
    eng.configure(base)
    return eng


class TestFireCaps:
    def test_intensity_clamped_to_cap(self):
        eng = _engine(FakeClock(), max_intensity=20)
        assert eng.fire("shock", 100, 300) is True
        assert eng._provider.ops[-1] == ("shock", 20, 300)

    def test_duration_clamped_to_cap(self):
        eng = _engine(FakeClock(), max_duration_ms=1000)
        eng.fire("shock", 10, 99999)
        assert eng._provider.ops[-1] == ("shock", 10, 1000)

    def test_absolute_ceiling_caps_the_setting(self):
        eng = _engine(FakeClock(), max_intensity=9999, max_duration_ms=9999999)
        assert eng.max_intensity == PiShockEngine.ABSOLUTE_MAX_INTENSITY
        assert eng.max_duration_ms == PiShockEngine.ABSOLUTE_MAX_DURATION_MS

    def test_absolute_min_interval_floor(self):
        eng = _engine(FakeClock(), min_interval_s=0.0)
        assert eng.min_interval_s == PiShockEngine.ABSOLUTE_MIN_INTERVAL_S

    def test_min_interval_drops_too_soon(self):
        clk = FakeClock()
        eng = _engine(clk, min_interval_s=2.0)
        assert eng.fire("shock", 10, 300) is True
        clk.t += 0.5
        assert eng.fire("shock", 10, 300) is False     # inside cooldown -> dropped
        assert len(eng._provider.ops) == 1
        clk.t += 2.0
        assert eng.fire("shock", 10, 300) is True       # cooldown elapsed
        assert len(eng._provider.ops) == 2

    def test_not_connected_drops(self):
        eng = _engine(FakeClock())
        eng._connected = False
        assert eng.fire("shock", 10, 300) is False

    def test_invalid_op_drops(self):
        eng = _engine(FakeClock())
        assert eng.fire("bogus", 10, 300) is False
        assert eng._provider.ops == []

    def test_stop_now_calls_provider_end(self):
        eng = _engine(FakeClock())
        eng.stop_now()
        assert eng._provider.ended == 1
