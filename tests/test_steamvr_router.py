"""SteamVR router tests — `compute_targets` (max-over-address-list
semantics), the battery broadcaster's debounce, and the deterministic
parts of the engine's pattern math.

No SteamVR needed: steamvr_engine guards its openvr import, the router
duck-types its configs, and the broadcaster gets a fake engine. The
poll/debounce loop itself is PollingRouter, covered in
test_router_base.py.
"""

from types import SimpleNamespace

import pytest

from steamvr_router import SteamVRBatteryBroadcaster, SteamVRRouter


def _cfg(enabled=True, addrs=("P",), battery_addr=""):
    """Duck-typed stand-in for steamvr_engine.TrackerConfig — the router
    only reads .enabled / .address_list / .battery_osc_address."""
    return SimpleNamespace(
        enabled=enabled,
        address_list=list(addrs),
        battery_osc_address=battery_addr,
    )


class _FakeHapticEngine:
    def __init__(self):
        self.calls = []

    def set_strength(self, serial, value):
        self.calls.append((serial, value))


def _router(configs):
    return SteamVRRouter(_FakeHapticEngine(), lambda: configs)


# ============================================================ compute_targets

class TestComputeTargets:
    def test_no_configs_returns_empty(self):
        assert _router({}).compute_targets({"P": 1.0}) == {}

    def test_max_over_address_list(self):
        r = _router({"T1": _cfg(addrs=("A", "B"))})
        assert r.compute_targets({"A": 0.3, "B": 0.8}) == {"T1": pytest.approx(0.8)}

    def test_disabled_tracker_skipped(self):
        r = _router({"T1": _cfg(enabled=False)})
        assert r.compute_targets({"P": 1.0}) == {}

    def test_placeholder_and_blank_addresses_ignored(self):
        # "..." is the stored placeholder for "no addresses configured".
        r = _router({"T1": _cfg(addrs=("...", "", "  ", "P"))})
        assert r.compute_targets({"P": 0.5}) == {"T1": pytest.approx(0.5)}

    def test_prefixed_address_is_stripped_for_lookup(self):
        # parameter_store keys are always the short form; a stale config
        # with the full /avatar/parameters/ prefix must still resolve.
        r = _router({"T1": _cfg(addrs=("/avatar/parameters/P",))})
        assert r.compute_targets({"P": 0.4}) == {"T1": pytest.approx(0.4)}

    def test_malformed_value_ignored(self):
        r = _router({"T1": _cfg(addrs=("P", "Q"))})
        assert r.compute_targets({"P": "garbage", "Q": 0.2}) == {"T1": pytest.approx(0.2)}

    def test_missing_params_report_zero(self):
        # An enabled tracker with no live params still reports 0.0 so the
        # debounced dispatch can pull a previously-driven motor back down.
        r = _router({"T1": _cfg(addrs=("P",))})
        assert r.compute_targets({}) == {"T1": 0.0}


# ============================================================ battery broadcaster

class _FakeVREngine:
    def __init__(self, devices, batteries):
        self._devices = devices
        self._batteries = batteries
        self.refreshed = 0

    def refresh_devices(self, quiet=False):
        self.refreshed += 1

    def snapshot_devices(self):
        return [SimpleNamespace(serial=s) for s in self._devices]

    def battery_for(self, serial):
        return self._batteries.get(serial)


class TestBatteryBroadcaster:
    def _bb(self, engine, configs, send=None, auto=False):
        sent = []
        bb = SteamVRBatteryBroadcaster(
            engine,
            lambda: configs,
            send_osc=send or (lambda addr, v: sent.append((addr, v))),
            get_auto_connect=lambda: auto,
        )
        return bb, sent

    def test_sends_battery_to_configured_address(self):
        eng = _FakeVREngine(["T1"], {"T1": 0.73})
        bb, sent = self._bb(eng, {"T1": _cfg(battery_addr="Bat1")})
        bb._tick()
        assert sent == [("Bat1", pytest.approx(0.73))]

    def test_debounces_repeat_values(self):
        eng = _FakeVREngine(["T1"], {"T1": 0.73})
        bb, sent = self._bb(eng, {"T1": _cfg(battery_addr="Bat1")})
        bb._tick()
        bb._tick()
        assert len(sent) == 1
        eng._batteries["T1"] = 0.5
        bb._tick()
        assert len(sent) == 2 and sent[-1] == ("Bat1", pytest.approx(0.5))

    def test_blank_address_and_unknown_device_skipped(self):
        eng = _FakeVREngine(["T1", "T2"], {"T1": 0.5, "T2": 0.5})
        bb, sent = self._bb(eng, {"T1": _cfg(battery_addr="")})  # T2 has no config
        bb._tick()
        assert sent == []

    def test_out_of_range_level_clamped(self):
        eng = _FakeVREngine(["T1"], {"T1": 1.4})
        bb, sent = self._bb(eng, {"T1": _cfg(battery_addr="Bat1")})
        bb._tick()
        assert sent == [("Bat1", pytest.approx(1.0))]

    def test_failed_send_does_not_stop_other_devices(self):
        eng = _FakeVREngine(["T1", "T2"], {"T1": 0.6, "T2": 0.7})
        sent = []

        def send(addr, v):
            if addr == "Bat1":
                raise RuntimeError("socket gone")
            sent.append((addr, v))

        bb, _ = self._bb(
            eng,
            {"T1": _cfg(battery_addr="Bat1"), "T2": _cfg(battery_addr="Bat2")},
            send=send,
        )
        bb._tick()
        assert sent == [("Bat2", pytest.approx(0.7))]

    def test_auto_connect_refreshes_devices(self):
        eng = _FakeVREngine([], {})
        bb, _ = self._bb(eng, {}, auto=True)
        bb._tick()
        assert eng.refreshed == 1


# ============================================================ pattern math

class TestVibrationPattern:
    """The deterministic patterns (None / Constant / Linear / Sine) and
    the min/max output window. Throb is time-based and only sanity-
    checked for bounds."""

    def _vp(self, prox, vel=("None", 0, 100, 4)):
        from steamvr_engine import PatternConfig, _VibrationPattern
        mk = lambda t: PatternConfig(
            pattern=t[0], str_min=t[1], str_max=t[2], speed=t[3])
        return _VibrationPattern([mk(prox), mk(vel)])

    def test_none_outputs_zero(self):
        vp = self._vp(("None", 0, 100, 4))
        assert vp.apply(1.0, 1.0) == 0.0

    def test_constant_is_binary(self):
        vp = self._vp(("Constant", 0, 100, 4))
        assert vp.apply(0.3, 0.0) == pytest.approx(1.0)
        assert vp.apply(0.0, 0.0) == 0.0

    def test_linear_passes_value_through(self):
        vp = self._vp(("Linear", 0, 100, 4))
        assert vp.apply(0.5, 0.0) == pytest.approx(0.5)

    def test_sine_eases_with_fixed_midpoint(self):
        import math
        vp = self._vp(("Sine", 0, 100, 4))
        assert vp.apply(0.5, 0.0) == pytest.approx(0.5)
        expected = -(math.cos(math.pi * 0.25) - 1) / 2.0
        assert vp.apply(0.25, 0.0) == pytest.approx(expected)

    def test_min_max_window_scales_output(self):
        vp = self._vp(("Linear", 20, 80, 4))
        # value 0.5 → 0.2 + 0.5 * (0.8 - 0.2) = 0.5; value 1.0 → 0.8.
        assert vp.apply(0.5, 0.0) == pytest.approx(0.5)
        assert vp.apply(1.0, 0.0) == pytest.approx(0.8)
        # Zero short-circuits below the window floor (no idle buzz).
        assert vp.apply(0.0, 0.0) == 0.0

    def test_channels_merge_max_wins(self):
        # Proximity Linear at 0.3 vs Velocity Constant driven → 1.0 wins.
        vp = self._vp(("Linear", 0, 100, 4), ("Constant", 0, 100, 4))
        assert vp.apply(0.3, 0.9) == pytest.approx(1.0)

    def test_throb_stays_in_bounds(self):
        vp = self._vp(("Throb", 0, 100, 4))
        out = vp.apply(1.0, 0.0)
        assert 0.0 <= out <= 1.0
