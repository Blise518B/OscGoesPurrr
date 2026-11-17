"""Tests for the PSVR2 contact-receiver read (psvr2_router.contact_strength),
the level shaping (compute_psvr2_level), and the router's single-key target
computation. Pure / hardware-free."""

from psvr2_router import PSVR2Router, compute_psvr2_level, contact_strength


def _c(**kw):
    base = {
        "enabled": True, "parameter": "Contact/HeadPat",
        "threshold": 0.0, "gain": 1.0,
    }
    base.update(kw)
    return base


class TestContactStrength:
    def test_reads_the_named_receiver(self):
        assert contact_strength("Contact/HeadPat",
                                {"Contact/HeadPat": 0.75}) == 0.75

    def test_missing_parameter_is_zero(self):
        assert contact_strength("Contact/Nope", {"Contact/HeadPat": 1.0}) == 0.0

    def test_blank_name_is_zero(self):
        assert contact_strength("", {"Contact/HeadPat": 1.0}) == 0.0
        assert contact_strength(None, {"Contact/HeadPat": 1.0}) == 0.0

    def test_bool_receiver_reads_as_one(self):
        # A constant-type (on/off) receiver is a legitimate source.
        assert contact_strength("C", {"C": True}) == 1.0
        assert contact_strength("C", {"C": False}) == 0.0

    def test_int_byte_param_is_rescaled(self):
        # normalize_osc_value gives genuine ints the 0-255 rescale.
        assert contact_strength("C", {"C": 255}) == 1.0

    def test_float_above_one_saturates(self):
        assert contact_strength("C", {"C": 1.5}) == 1.0

    def test_negative_clamps_to_zero(self):
        assert contact_strength("C", {"C": -0.5}) == 0.0

    def test_nan_is_zero_not_full_power(self):
        # min(1.0, nan) is nan in CPython — a NaN surviving to the mapper
        # would command a nonsense rumble byte.
        assert contact_strength("C", {"C": float("nan")}) == 0.0

    def test_garbage_is_zero(self):
        assert contact_strength("C", {"C": "loud"}) == 0.0


class TestComputePSVR2Level:
    def test_disabled_is_zero(self):
        assert compute_psvr2_level(_c(enabled=False), 1.0) == 0.0

    def test_empty_cfg_is_zero(self):
        assert compute_psvr2_level({}, 1.0) == 0.0

    def test_full_maps_to_full(self):
        assert compute_psvr2_level(_c(), 1.0) == 1.0

    def test_half_maps_to_half(self):
        assert compute_psvr2_level(_c(), 0.5) == 0.5

    def test_threshold_deadband(self):
        assert compute_psvr2_level(_c(threshold=0.5), 0.4) == 0.0

    def test_threshold_then_gain(self):
        assert compute_psvr2_level(_c(threshold=0.2, gain=1.0), 0.6) == 0.4

    def test_gain_amplifies_and_clamps(self):
        assert compute_psvr2_level(_c(gain=2.0), 0.6) == 1.0

    def test_quantized_to_level_step(self):
        assert compute_psvr2_level(_c(), 0.333) == 0.34

    def test_master_scale_attenuates(self):
        assert compute_psvr2_level(_c(), 1.0, scale=0.5) == 0.5

    def test_off_mode_silences(self):
        assert compute_psvr2_level(_c(), 1.0, scale=0.0) == 0.0

    def test_nan_strength_is_zero(self):
        assert compute_psvr2_level(_c(), float("nan")) == 0.0


# --- the router: every tick, Off, VRChat quiet, Toy Safety, the Test floor --

class _FakeEngine:
    def __init__(self):
        self.is_connected = True
        self.levels = []

    def set_level(self, level):
        self.levels.append(level)


class _Store:
    def __init__(self, **values):
        self.values = dict(values)

    def get_values(self, names):
        return {n: self.values[n] for n in names if n in self.values}


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


SAFETY = {"enabled": True, "active_s": 1.0, "peaked_s": 10.0}


def _router(cfg=None, scale=1.0, test=0.0, safety=None, **values):
    from router_base import StaleSignalMonitor
    eng, clock = _FakeEngine(), _Clock()
    state = {"scale": scale, "test": test, "cfg": cfg or _c()}
    r = PSVR2Router(eng, get_contact_config=lambda: state["cfg"],
                    get_master_scale=lambda: state["scale"],
                    get_test_level=lambda: state["test"],
                    get_antistuck=lambda: safety,
                    clock=clock, param_store=_Store(**values))
    r._stale = StaleSignalMonitor(cutoff_s=0)      # never stale unless a test says
    r.configure()
    return r, eng, clock, state


class TestRouterTick:
    def test_the_level_goes_out(self):
        r, eng, _c2, _s = _router(**{"Contact/HeadPat": 0.5})
        r.tick()
        assert eng.levels == [0.5]
        assert r.live() == {"strength": 0.5, "level": 0.5}

    def test_every_tick_zeros_too(self):
        # the engine plays nothing it isn't sent again, so a held contact
        # and silence both go out every tick
        r, eng, _c2, _s = _router(**{"Contact/HeadPat": 0.5})
        r.tick(); r.tick()
        r._store.values.clear()
        r.tick()
        assert eng.levels == [0.5, 0.5, 0.0]

    def test_nothing_while_the_headset_isnt_connected(self):
        r, eng, _c2, _s = _router(**{"Contact/HeadPat": 0.5})
        eng.is_connected = False
        r.tick()
        assert eng.levels == []

    def test_off_sends_zero(self):
        r, eng, _c2, state = _router(**{"Contact/HeadPat": 1.0})
        state["scale"] = 0.0
        r.tick()
        assert eng.levels == [0.0]

    def test_strength_scales_it(self):
        r, eng, _c2, _s = _router(scale=0.5, **{"Contact/HeadPat": 1.0})
        r.tick()
        assert eng.levels == [0.5]

    def test_vrchat_going_quiet_sends_zero(self):
        from router_base import StaleSignalMonitor
        r, eng, _c2, _s = _router(**{"Contact/HeadPat": 1.0})

        class _Quiet(StaleSignalMonitor):
            def is_stale(self):
                return True
        r._stale = _Quiet()
        r.tick()
        assert eng.levels == [0.0]

    def test_disabled_contact_is_zero(self):
        r, eng, _c2, _s = _router(cfg=_c(enabled=False), **{"Contact/HeadPat": 1.0})
        r.tick()
        assert eng.levels == [0.0]


class TestToySafety:
    def test_a_frozen_mid_level_is_cut(self):
        r, eng, clock, _s = _router(safety=SAFETY, **{"Contact/HeadPat": 0.5})
        r.tick()
        clock.t += 0.9
        r.tick()
        clock.t += 0.2                      # still for 1.1 s
        r.tick()
        assert eng.levels == [0.5, 0.5, 0.0]

    def test_a_moving_contact_keeps_playing(self):
        r, eng, clock, _s = _router(safety=SAFETY, **{"Contact/HeadPat": 0.5})
        for v in (0.5, 0.55, 0.6, 0.65):
            r._store.values["Contact/HeadPat"] = v
            r.tick()
            clock.t += 0.6
        assert all(level > 0 for level in eng.levels)    # 0.6 s apart, never cut

    def test_a_cut_contact_comes_back_on_a_new_value(self):
        r, eng, clock, _s = _router(safety=SAFETY, **{"Contact/HeadPat": 0.5})
        r.tick()
        clock.t += 1.5
        r.tick()
        r._store.values["Contact/HeadPat"] = 0.7
        r.tick()
        assert eng.levels == [0.5, 0.0, 0.7]

    def test_one_held_at_the_top_fades_after_peaked_s(self):
        r, eng, clock, _s = _router(safety=SAFETY, **{"Contact/HeadPat": 1.0})
        r.tick()
        clock.t += 9.0
        r.tick()
        assert eng.levels[-1] == 1.0        # under peaked_s: still plays
        clock.t += 30.0
        r.tick()
        assert eng.levels[-1] == 0.0        # faded out

    def test_switched_off_never_cuts(self):
        r, eng, clock, _s = _router(safety={"enabled": False},
                                    **{"Contact/HeadPat": 0.5})
        r.tick()
        clock.t += 60.0
        r.tick()
        assert eng.levels == [0.5, 0.5]


class TestTestFloor:
    def test_floors_an_enabled_contact(self):
        r, eng, _c2, _s = _router(test=0.5)
        r.tick()
        assert eng.levels == [0.5]

    def test_ignored_when_the_contact_is_off(self):
        r, eng, _c2, _s = _router(cfg=_c(enabled=False), test=0.5)
        r.tick()
        assert eng.levels == [0.0]

    def test_never_while_output_is_off(self):
        # like the suits: nothing plays while Off
        r, eng, _c2, _s = _router(scale=0.0, test=0.5)
        r.tick()
        assert eng.levels == [0.0]


class TestWake:
    def test_the_contact_wakes_it(self):
        r, _eng, _c2, _s = _router()
        r._wake.clear()
        r.notify("/avatar/parameters/Contact/Other")
        assert not r._wake.is_set()
        r.notify("/avatar/parameters/Contact/HeadPat")
        assert r._wake.is_set()

    def test_a_new_contact_is_followed(self):
        r, _eng, _c2, state = _router()
        state["cfg"] = _c(parameter="HapticHead")
        r.configure()
        r._wake.clear()
        r.notify("HapticHead")
        assert r._wake.is_set()

    def test_the_thread_runs_and_stops(self):
        r, eng, _c2, _s = _router(**{"Contact/HeadPat": 0.5})
        r._poll_s = 0.005
        r.start()
        try:
            import time
            end = time.monotonic() + 2.0
            while not eng.levels and time.monotonic() < end:
                time.sleep(0.01)
        finally:
            r.stop()
        assert eng.levels and eng.levels[0] == 0.5

    def test_a_headset_coming_or_going_wakes_it(self):
        r, _eng, _c2, _s = _router()
        r._wake.clear()
        r.wake()
        assert r._wake.is_set()

    def test_it_idles_while_no_headset_is_connected(self):
        """60 wakeups a second only while there is a headset to send to."""
        import time
        from psvr2_router import IDLE_POLL_S
        r, eng, _c2, _s = _router()
        eng.is_connected = False
        calls = []
        r.tick = lambda: calls.append(time.monotonic())
        r._poll_s = 0.005
        r.start()
        try:
            time.sleep(0.2)
        finally:
            r.stop()
        assert len(calls) <= 1 and IDLE_POLL_S >= 0.25
