"""Tests for the Handy level shaping (handy_router.compute_handy_level) and
the router's single-key target computation. Pure / network-free."""

from handy_router import HandyRouter, compute_handy_level


def _z(**kw):
    base = {
        "enabled": True, "ogb_zone": "Snoot", "zone_type": "Orf",
        "filters": ["TouchSelf"], "threshold": 0.0, "gain": 1.0,
    }
    base.update(kw)
    return base


class TestComputeHandyLevel:
    def test_disabled_is_zero(self):
        assert compute_handy_level(_z(enabled=False), 1.0) == 0.0

    def test_empty_cfg_is_zero(self):
        assert compute_handy_level({}, 1.0) == 0.0

    def test_full_maps_to_full(self):
        assert compute_handy_level(_z(), 1.0) == 1.0

    def test_half_maps_to_half(self):
        assert compute_handy_level(_z(), 0.5) == 0.5

    def test_threshold_deadband(self):
        assert compute_handy_level(_z(threshold=0.5), 0.4) == 0.0

    def test_threshold_then_gain(self):
        # (0.6 - 0.2) * 1.0 = 0.4
        assert compute_handy_level(_z(threshold=0.2, gain=1.0), 0.6) == 0.4

    def test_gain_amplifies_and_clamps(self):
        assert compute_handy_level(_z(gain=2.0), 0.6) == 1.0

    def test_quantized_to_level_step(self):
        # 0.333 snaps to the nearest 0.02 step so analog jitter debounces.
        assert compute_handy_level(_z(), 0.333) == 0.34

    def test_bad_values_fall_back(self):
        assert compute_handy_level(_z(threshold="x", gain="y"), 0.5) == 0.5


class _FakeEngine:
    is_connected = True

    def __init__(self):
        self.levels = []

    def set_level(self, level):
        self.levels.append(level)


class TestHandyRouter:
    def _router(self, engine, cfg):
        return HandyRouter(engine=engine, get_zone_config=lambda: cfg)

    def test_compute_targets_single_key(self):
        eng = _FakeEngine()
        r = self._router(eng, _z())
        params = {"OGB/Orf/Snoot/TouchSelf": 0.5}
        assert r.compute_targets(params) == {"_handy": 0.5}

    def test_zone_miss_is_zero(self):
        eng = _FakeEngine()
        r = self._router(eng, _z(ogb_zone="Elsewhere"))
        params = {"OGB/Orf/Snoot/TouchSelf": 0.5}
        assert r.compute_targets(params) == {"_handy": 0.0}

    def test_dispatch_pushes_level_to_engine(self):
        eng = _FakeEngine()
        r = self._router(eng, _z())
        r.dispatch("_handy", 0.42)
        assert eng.levels == [0.42]

    def test_engine_ready_follows_connection(self):
        eng = _FakeEngine()
        r = self._router(eng, _z())
        assert r._engine_ready() is True
        eng.is_connected = False
        assert r._engine_ready() is False
