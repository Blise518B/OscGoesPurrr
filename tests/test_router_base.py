"""Tests for the PollingRouter base (router_base.py).

The poll loop runs on a thread in production, but the debounce + compute /
dispatch + engine-gate logic is exercised by calling `_tick()` directly with a
faked parameter_store, so no thread or real timing is involved.
"""

import pytest

import router_base
from router_base import PollingRouter


class FakeStore:
    def __init__(self, params=None):
        self._p = params or {}

    def get_all_parameters(self):
        return dict(self._p)


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


@pytest.fixture
def patch_store(monkeypatch):
    def _set(params):
        monkeypatch.setattr(router_base, "store", FakeStore(params))
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
