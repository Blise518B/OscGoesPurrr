"""Tests for the PollingRouter base (router_base.py).

The poll loop runs on a thread in production, but the debounce + compute /
dispatch + engine-gate logic is exercised by calling `_tick()` directly with a
faked parameter_store, so no thread or real timing is involved.
"""

import time

import pytest

import router_base
from router_base import PollingRouter


class FakeStore:
    def __init__(self, params=None):
        self._p = params or {}
        self.packets = 0  # bump to simulate live OSC traffic

    def get_all_parameters(self):
        return dict(self._p)

    def get_packets_received(self):
        return self.packets


class FakeEngine:
    def __init__(self, ready=True):
        self.ready = ready
        self.sent = []  # list of (key, target)


class DemoRouter(PollingRouter):
    """Maps a single 'x' param to target keyed 'out'. When gate=True it goes
    quiet while engine.ready is False (exercising the disconnect-clear path)."""

    def __init__(self, engine, gate=False):
        super().__init__("Demo", engine)
        self._gate = gate
        self.cleared = 0

    def _engine_ready(self):
        return self.engine.ready if self._gate else True

    def _on_cleared(self):
        self.cleared += 1

    def compute_targets(self, params):
        if "x" not in params:
            return {}
        return {"out": int(params["x"])}

    def dispatch(self, key, target):
        self.engine.sent.append((key, target))


class ZeroingDemoRouter(DemoRouter):
    """Like the real level routers (Coyote/OWO/Handy): an enabled output
    resolves to an explicit zero when its params are absent, instead of
    being omitted from the target map."""

    def compute_targets(self, params):
        return {"out": int(params.get("x", 0))}


@pytest.fixture
def patch_store(monkeypatch):
    def _set(params):
        fake = FakeStore(params)
        monkeypatch.setattr(router_base, "store", fake)
        return fake
    return _set


class TestDebounce:
    def test_dispatches_on_change(self, patch_store):
        eng = FakeEngine()
        r = DemoRouter(eng)
        patch_store({"x": 5})
        r._tick()
        assert eng.sent == [("out", 5)]

    def test_held_value_not_resent(self, patch_store):
        eng = FakeEngine()
        r = DemoRouter(eng)
        patch_store({"x": 5})
        r._tick()
        r._tick()  # same value -> debounced
        assert eng.sent == [("out", 5)]

    def test_changed_value_resent(self, patch_store):
        eng = FakeEngine()
        r = DemoRouter(eng)
        patch_store({"x": 5})
        r._tick()
        patch_store({"x": 7})
        r._tick()
        assert eng.sent == [("out", 5), ("out", 7)]

    def test_empty_params_skips(self, patch_store):
        eng = FakeEngine()
        r = DemoRouter(eng)
        patch_store({})
        r._tick()
        assert eng.sent == []


class TestEngineGate:
    def test_not_ready_skips_and_clears_then_resends(self, patch_store):
        eng = FakeEngine(ready=True)
        r = DemoRouter(eng, gate=True)
        patch_store({"x": 5})
        r._tick()
        assert eng.sent == [("out", 5)]
        # Engine drops: next tick clears debounce + fires _on_cleared, no dispatch.
        eng.ready = False
        r._tick()
        assert r.cleared == 1
        assert eng.sent == [("out", 5)]
        # Reconnect: same value re-sent because the debounce was cleared.
        eng.ready = True
        r._tick()
        assert eng.sent == [("out", 5), ("out", 5)]

    def test_default_engine_ready_is_true(self, patch_store):
        # Without the gate the router always ticks, regardless of engine state
        # — matching the SteamVR router's always-tick behavior.
        eng = FakeEngine(ready=False)
        r = DemoRouter(eng, gate=False)
        patch_store({"x": 3})
        r._tick()
        assert eng.sent == [("out", 3)]


class TestStaleSignalCutoff:
    """VRChat dying mid-contact must not latch outputs: after the cutoff with
    no OSC traffic, every enabled output is pulled to its zero level once."""

    def _stale(self, router):
        # Simulate the cutoff having elapsed with a static packet counter.
        router._stale_monitor._count = router_base.store.get_packets_received()
        router._stale_monitor._ts = time.monotonic() - 1000.0

    def test_stale_signal_pulls_outputs_to_zero_once(self, patch_store):
        eng = FakeEngine()
        r = ZeroingDemoRouter(eng)
        fake = patch_store({"x": 5})
        fake.packets = 1
        r._tick()
        assert eng.sent == [("out", 5)]
        self._stale(r)          # traffic stops; params stay latched at x=5
        r._tick()
        assert eng.sent == [("out", 5), ("out", 0)]   # pulled to zero
        r._tick()
        assert eng.sent == [("out", 5), ("out", 0)]   # then fully idle
        assert r.cleared >= 1

    def test_signal_return_resends_current_values(self, patch_store):
        eng = FakeEngine()
        r = ZeroingDemoRouter(eng)
        fake = patch_store({"x": 5})
        fake.packets = 1
        r._tick()
        self._stale(r)
        r._tick()               # zeroed
        fake.packets += 1       # VRChat is back
        r._tick()
        assert eng.sent == [("out", 5), ("out", 0), ("out", 5)]

    def test_advancing_packets_never_stale(self, patch_store):
        eng = FakeEngine()
        r = ZeroingDemoRouter(eng)
        fake = patch_store({"x": 5})
        r._stale_monitor._ts = time.monotonic() - 1000.0  # old timestamp...
        fake.packets = 42                                 # ...but fresh traffic
        r._tick()
        assert eng.sent == [("out", 5)]                   # normal dispatch

    def test_cutoff_disabled_with_nonpositive_value(self, patch_store):
        eng = FakeEngine()
        r = ZeroingDemoRouter(eng)
        r.stale_signal_cutoff_s = 0
        fake = patch_store({"x": 5})
        r._tick()
        self._stale(r)
        r._tick()
        assert eng.sent == [("out", 5)]                # never zeroed

    def test_emptied_store_pulls_live_outputs_to_zero(self, patch_store):
        # An OSCQuery rebuild yielding no params must not latch a live
        # output (the old early-out returned before computing anything).
        eng = FakeEngine()
        r = ZeroingDemoRouter(eng)
        fake = patch_store({"x": 5})
        fake.packets = 1
        r._tick()
        assert eng.sent == [("out", 5)]
        fake._p = {}            # store emptied; traffic still flowing
        fake.packets += 1
        r._tick()
        assert eng.sent == [("out", 5), ("out", 0)]
        fake.packets += 1
        r._tick()               # stays idle, no re-dispatch
        assert eng.sent == [("out", 5), ("out", 0)]
