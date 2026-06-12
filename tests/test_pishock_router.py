"""Tests for the PiShock discrete-event router logic (pishock_router.py).

The router runs on a thread, but every decision is a pure function/class:
decide_fire (rising-edge + cooldown), map_intensity, and RateLimiter. These
are the safety-critical core, so they're tested exhaustively without a thread.
"""

from pishock_router import FireEvent, RateLimiter, ZoneState, decide_fire, map_intensity


def _zone(**kw):
    base = {
        "name": "Z", "ogb_zone": "Boob", "zone_type": "Orf",
        "filters": ["TouchSelf"], "op": "shock",
        "threshold": 0.5, "hysteresis": 0.1,
        "min_int": 1, "max_int": 30, "duration_ms": 300,
        "min_interval_s": 1.0, "sustain": False, "cadence_s": 1.0,
        "enabled": True,
    }
    base.update(kw)
    return base


class TestMapIntensity:
    def test_at_threshold_is_lo(self):
        assert map_intensity(0.5, 0.5, 1, 30) == 1

    def test_at_full_is_hi(self):
        assert map_intensity(1.0, 0.5, 1, 30) == 30

    def test_midpoint(self):
        # frac 0.5 -> 1 + 0.5*29 = 15.5 -> 16
        assert map_intensity(0.75, 0.5, 1, 30) == 16

    def test_floor_is_one(self):
        assert map_intensity(0.0, 0.0, 0, 0) == 1


class TestDecideFire:
    def test_rising_edge_fires_once(self):
        st = ZoneState()
        z = _zone()
        ev = decide_fire(z, 0.8, st, now=100.0)
        assert isinstance(ev, FireEvent) and ev.op == "shock"
        assert st.armed is False
        # Held at the same strength -> no re-fire.
        assert decide_fire(z, 0.8, st, now=100.1) is None

    def test_rearm_requires_drop_below_hysteresis(self):
        st = ZoneState()
        z = _zone(threshold=0.5, hysteresis=0.1)
        decide_fire(z, 0.8, st, now=0.0)            # fires, disarms
        decide_fire(z, 0.45, st, now=1.0)           # 0.45 > 0.4 -> still disarmed
        assert st.armed is False
        decide_fire(z, 0.35, st, now=2.0)           # 0.35 < 0.4 -> re-armed
        assert st.armed is True
        assert decide_fire(z, 0.8, st, now=10.0) is not None

    def test_min_interval_blocks_too_soon(self):
        st = ZoneState()
        z = _zone(min_interval_s=5.0)
        assert decide_fire(z, 0.8, st, now=0.0) is not None
        decide_fire(z, 0.0, st, now=1.0)            # re-arm
        assert st.armed is True
        assert decide_fire(z, 0.8, st, now=2.0) is None   # 2s < 5s cooldown

    def test_first_after_idle_fires_immediately(self):
        # last_fire_ts starts far in the past -> no cooldown debt on first fire.
        assert decide_fire(_zone(min_interval_s=5.0), 0.9, ZoneState(), now=0.0) is not None

    def test_below_threshold_never_fires(self):
        assert decide_fire(_zone(threshold=0.5), 0.4, ZoneState(), now=0.0) is None

    def test_intensity_maps_within_zone_range(self):
        ev = decide_fire(_zone(threshold=0.5, min_int=10, max_int=20), 1.0, ZoneState(), now=0.0)
        assert ev.intensity == 20

    def test_invalid_op_falls_back_to_shock(self):
        ev = decide_fire(_zone(op="bogus"), 0.9, ZoneState(), now=0.0)
        assert ev.op == "shock"

    def test_sustain_refires_on_cadence(self):
        st = ZoneState()
        z = _zone(sustain=True, cadence_s=2.0, min_interval_s=0.5)
        assert decide_fire(z, 0.9, st, now=0.0) is not None     # initial edge
        assert decide_fire(z, 0.9, st, now=1.0) is None         # before cadence
        assert decide_fire(z, 0.9, st, now=2.5) is not None     # after cadence

    def test_no_sustain_does_not_refire_while_held(self):
        st = ZoneState()
        z = _zone(sustain=False)
        assert decide_fire(z, 0.9, st, now=0.0) is not None
        assert decide_fire(z, 0.9, st, now=100.0) is None       # still held, no sustain


class TestRateLimiter:
    def test_allows_up_to_max(self):
        rl = RateLimiter(max_events=3, window_s=10.0)
        assert rl.try_acquire(0.0) is True
        assert rl.try_acquire(1.0) is True
        assert rl.try_acquire(2.0) is True
        assert rl.try_acquire(3.0) is False     # 4th within window blocked

    def test_window_slides(self):
        rl = RateLimiter(max_events=2, window_s=5.0)
        assert rl.try_acquire(0.0) is True
        assert rl.try_acquire(1.0) is True
        assert rl.try_acquire(2.0) is False
        # 0.0 expires once now-window passes it; 1.0 still counts.
        assert rl.try_acquire(6.0) is True
