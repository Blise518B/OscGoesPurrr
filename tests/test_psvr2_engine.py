"""Tests for the PSVR2 engine's pure decision cores — the level → rumble-Hz
mapping and the send planner — plus the connection lifecycle against a fake
CAPI. No threads, no DLL: the send thread is stubbed out where a test needs
_open(), so everything here is deterministic on any platform."""

import threading
import time

import pytest

import psvr2_capi
from psvr2_engine import HmdRumblePlanner, PSVR2Engine, level_to_rumble_hz


class _FakeCapi:
    """Stand-in for psvr2_capi with the same call surface."""

    RESULT_OK = psvr2_capi.RESULT_OK
    RESULT_DRIVER_INACTIVE = psvr2_capi.RESULT_DRIVER_INACTIVE
    RESULT_NO_SLOT = psvr2_capi.RESULT_NO_SLOT
    RUMBLE_HZ_MAX = psvr2_capi.RUMBLE_HZ_MAX

    def __init__(self, available=True, init_result=0, driver_active=True):
        self._available = available
        self._init_result = init_result
        self._driver_active = driver_active
        self.sent = []
        self.init_calls = 0
        self.deinit_calls = 0

    def is_available(self):
        return self._available

    def load_error(self):
        return None if self._available else "PSVR2Toolkit not detected"

    def dll_path(self):
        return r"C:\fake\psvr2_toolkit_capi.dll"

    def init(self):
        self.init_calls += 1
        return self._init_result

    def deinit(self):
        self.deinit_calls += 1

    def get_driver_active(self):
        return self._driver_active

    # experimental-1's DLL returned nothing: None stands in for that
    rumble_result = None

    def set_hmd_rumble(self, hz):
        self.sent.append(int(hz))
        return self.rumble_result


def _engine(capi, clock=None, **out):
    cfg = {"min_hz": 5.0, "max_hz": 25.0, "max_cmd_hz": 10.0, "keepalive_s": 0.0}
    cfg.update(out)
    kw = {"clock": clock} if clock is not None else {}
    eng = PSVR2Engine(get_output_config=lambda: cfg, capi=capi, **kw)
    # The send thread is exercised on hardware, not here — stubbing it keeps
    # every lifecycle assertion deterministic.
    eng._start_send_thread = lambda: None
    return eng


class TestLevelToRumbleHz:
    def test_zero_level_stops_the_motor(self):
        assert level_to_rumble_hz(0.0, 5, 25) == 0

    def test_negative_level_stops_the_motor(self):
        assert level_to_rumble_hz(-1.0, 5, 25) == 0

    def test_full_level_hits_the_top_of_the_band(self):
        assert level_to_rumble_hz(1.0, 5, 25) == 25

    def test_any_nonzero_level_lands_inside_the_band(self):
        # The band floor exists because very low frequencies may not move the
        # motor at all — a faint contact must still be felt, not silent.
        assert level_to_rumble_hz(0.001, 5, 25) == 5

    def test_midpoint_is_the_middle_of_the_band(self):
        assert level_to_rumble_hz(0.5, 5, 25) == 15

    def test_level_clamped_above_one(self):
        assert level_to_rumble_hz(2.0, 5, 25) == 25

    def test_band_clamped_to_hardware_range(self):
        assert level_to_rumble_hz(1.0, 0, 99) == psvr2_capi.RUMBLE_HZ_MAX
        # 0 means "off" on the wire, so the floor can never be 0.
        assert level_to_rumble_hz(0.001, 0, 99) == 1

    def test_inverted_band_is_ordered(self):
        assert level_to_rumble_hz(1.0, 20, 10) == 20
        assert level_to_rumble_hz(0.001, 20, 10) == 10

    def test_narrow_band_is_constant(self):
        assert level_to_rumble_hz(0.3, 12, 12) == 12
        assert level_to_rumble_hz(1.0, 12, 12) == 12

    def test_nan_level_stops_the_motor(self):
        # min(1.0, nan) is 1.0: without its own check a NaN would buzz full.
        assert level_to_rumble_hz(float("nan"), 5, 25) == 0

    def test_garbage_falls_back_to_the_full_range(self):
        assert level_to_rumble_hz("x", 5, 25) == 0
        assert level_to_rumble_hz(1.0, "x", "y") == psvr2_capi.RUMBLE_HZ_MAX


class TestHmdRumblePlanner:
    def test_first_value_is_always_sent(self):
        p = HmdRumblePlanner()
        assert p.step(0, 0.0) == 0

    def test_change_is_sent(self):
        p = HmdRumblePlanner()
        p.step(0, 0.0)
        assert p.step(12, 0.1) == 12

    def test_held_value_sends_nothing(self):
        p = HmdRumblePlanner()
        p.step(12, 0.0)
        assert p.step(12, 0.1) is None
        assert p.step(12, 99.0) is None

    def test_release_is_sent(self):
        p = HmdRumblePlanner()
        p.step(12, 0.0)
        assert p.step(0, 0.1) == 0

    def test_keepalive_resends_a_held_value(self):
        p = HmdRumblePlanner(keepalive_s=2.0)
        p.step(12, 0.0)
        assert p.step(12, 1.0) is None      # inside the interval
        assert p.step(12, 2.5) == 12        # interval elapsed
        assert p.step(12, 3.0) is None      # timer restarted

    def test_keepalive_never_resends_zero(self):
        # Re-sending "off" costs a USB transfer to change nothing.
        p = HmdRumblePlanner(keepalive_s=1.0)
        p.step(0, 0.0)
        assert p.step(0, 50.0) is None

    def test_reset_forces_a_resend(self):
        p = HmdRumblePlanner()
        p.step(12, 0.0)
        assert p.step(12, 0.1) is None
        p.reset()
        assert p.step(12, 0.2) == 12


class TestLifecycle:
    def test_unavailable_reports_the_load_error(self):
        eng = _engine(_FakeCapi(available=False))
        assert eng.is_available is False
        assert "not detected" in eng._unavailable_reason

    def test_open_without_toolkit_raises(self):
        eng = _engine(_FakeCapi(available=False))
        with pytest.raises(RuntimeError):
            eng._open()

    def test_open_with_inactive_driver_raises(self):
        capi = _FakeCapi(init_result=psvr2_capi.RESULT_DRIVER_INACTIVE)
        eng = _engine(capi)
        with pytest.raises(RuntimeError, match="driver not active"):
            eng._open()
        assert eng.is_connected is False

    def test_open_succeeds(self):
        capi = _FakeCapi()
        eng = _engine(capi)
        eng._open()
        assert eng.is_connected is True
        assert capi.init_calls == 1
        assert eng.get_status_extras()["slotless"] is False

    def test_no_slot_still_connects(self):
        # Headset rumble is the one toolkit command that needs no client
        # slot, so slot exhaustion must not take this backend down.
        capi = _FakeCapi(init_result=psvr2_capi.RESULT_NO_SLOT)
        eng = _engine(capi)
        eng._open()
        assert eng.is_connected is True
        assert eng.get_status_extras()["slotless"] is True

    def test_close_releases_the_slot(self):
        capi = _FakeCapi()
        eng = _engine(capi)
        eng._open()
        eng._close()
        assert eng.is_connected is False
        assert capi.deinit_calls == 1

    def test_close_stops_a_running_motor(self):
        capi = _FakeCapi()
        eng = _engine(capi)
        eng._open()
        eng._planner.step(18, 0.0)   # as if the send loop had sent 18 Hz
        eng._close()
        assert capi.sent == [0]

    def test_close_stop_waits_for_an_in_flight_send(self):
        # The stop-the-motor 0 must be the LAST command to reach the headset.
        # Without the send lock, a send already blocked inside the driver ack
        # would land after it and leave the headset buzzing.
        capi = _FakeCapi()
        eng = _engine(capi)
        eng._open()
        eng._planner.step(18, 0.0)
        entered, release = threading.Event(), threading.Event()
        real_send = capi.set_hmd_rumble

        def slow_send(hz):
            if hz == 18:
                entered.set()
                release.wait(2.0)
            real_send(hz)

        capi.set_hmd_rumble = slow_send
        t = threading.Thread(target=eng._send, args=(18,), daemon=True)
        t.start()
        assert entered.wait(2.0)          # the 18 Hz send is mid-ack
        closer = threading.Thread(target=eng._close, daemon=True)
        closer.start()
        # Give the closer time to reach the DLL call. With the lock it parks
        # there; without one it would send its 0 now and the released 18 would
        # land after it — which is exactly the failure this pins.
        time.sleep(0.05)
        release.set()
        t.join(2.0); closer.join(2.0)
        assert capi.sent[-1] == 0

    def test_open_asks_whether_the_driver_runs(self):
        # Since experimental-2, init() succeeds without SteamVR. Connecting
        # anyway would drop the link every second (the liveness check).
        capi = _FakeCapi(init_result=psvr2_capi.RESULT_OK, driver_active=False)
        eng = _engine(capi)
        with pytest.raises(RuntimeError, match="driver not active"):
            eng._open()
        assert eng.is_connected is False
        assert capi.deinit_calls == 1          # no slot held meanwhile

    def test_a_failed_send_raises(self):
        capi = _FakeCapi()
        eng = _engine(capi)
        eng._open()
        capi.rumble_result = psvr2_capi.RESULT_TIMEOUT
        with pytest.raises(RuntimeError, match="didn't answer"):
            eng._send(12)
        capi.rumble_result = psvr2_capi.RESULT_DRIVER_INACTIVE
        with pytest.raises(RuntimeError, match="driver"):
            eng._send(12)

    def test_an_old_dlls_missing_result_is_success(self):
        # experimental-1 returned void: whatever the register held shows
        capi = _FakeCapi()
        eng = _engine(capi)
        eng._open()
        for junk in (None, psvr2_capi.RESULT_OK, 1, 255, 0x7FFF):
            capi.rumble_result = junk
            eng._send(12)
        assert capi.sent == [12] * 5

    def test_close_skips_the_stop_when_already_silent(self):
        # Every command blocks on a driver ack, so don't pay for one at
        # shutdown when the motor is already known to be off.
        capi = _FakeCapi()
        eng = _engine(capi)
        eng._open()
        eng._planner.step(0, 0.0)
        eng._close()
        assert capi.sent == []


class TestResolveHz:
    def _cfg(self):
        return {"min_hz": 5.0, "max_hz": 25.0}

    def test_routed_level_maps_through_the_band(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng.set_level(0.5)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 15

    def test_set_level_clamps(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng.set_level(5.0)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 25
        eng.set_level(-3.0)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 0

    def test_set_level_survives_garbage(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng.set_level("nope")
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 0
        eng.set_level(float("nan"))
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 0

    def test_test_pulse_overrides_then_expires(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng._open()
        eng.set_level(0.0)
        assert eng.test_pulse(hz=20, duration_s=1.0) is True
        deadline = eng._test_until
        assert eng._resolve_hz(self._cfg(), now_s=deadline - 0.5) == 20
        # Bounded by construction: past the deadline the routed level wins
        # again, so a test can never latch the motor on.
        assert eng._resolve_hz(self._cfg(), now_s=deadline + 0.1) == 0

    def test_test_pulse_defaults_to_the_top_of_the_band(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now, min_hz=5.0, max_hz=18.0)
        eng._open()
        eng.test_pulse()
        assert eng._resolve_hz(self._cfg(), now_s=eng._test_until - 0.5) == 18


class TestLastGate:
    """This edition's rules on top of main's engine: the motor LATCHES, so
    a level nobody re-sends must stop by itself, and Home's Off holds it
    at 0."""

    def _cfg(self):
        return {"min_hz": 5.0, "max_hz": 25.0}

    def test_a_level_not_sent_again_plays_nothing(self, clock):
        # If the router dies mid-contact the headset must not buzz on.
        from psvr2_engine import LEVEL_TTL_S
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng.set_level(1.0)
        clock.advance(LEVEL_TTL_S - 0.01)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 25
        clock.advance(0.02)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 0
        assert eng.get_status_extras()["level"] == 0.0

    def test_resending_keeps_it_playing(self, clock):
        from psvr2_engine import LEVEL_TTL_S
        eng = _engine(_FakeCapi(), clock=clock.now)
        for _ in range(10):
            eng.set_level(0.5)
            clock.advance(LEVEL_TTL_S / 2)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 15

    def test_paused_holds_zero(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng.set_paused(True)
        eng.set_level(1.0)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 0
        assert eng.get_status_extras()["paused"] is True
        eng.set_paused(False)
        eng.set_level(1.0)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 25

    def test_paused_refuses_a_test_buzz(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng._open()
        eng.set_paused(True)
        assert eng.test_pulse(hz=20) is False
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 0

    def test_pausing_ends_a_running_test_buzz(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng._open()
        assert eng.test_pulse(hz=20) is True
        eng.set_paused(True)
        eng.set_paused(False)
        assert eng._resolve_hz(self._cfg(), now_s=clock.now()) == 0

    def test_no_test_buzz_while_not_connected(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        assert eng.test_pulse(hz=20) is False

    def test_pausing_tells_the_controller(self, clock):
        eng = _engine(_FakeCapi(), clock=clock.now)
        calls = []
        eng.set_state_callback(lambda: calls.append(1))
        eng.set_paused(True)
        assert calls == [1]

    def test_a_held_level_wakes_the_send_thread_once(self, clock):
        # The router sends every tick; a held contact costs no wakeups.
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng.set_level(0.5)
        assert eng._wake_evt.is_set()
        eng._wake_evt.clear()
        for _ in range(5):
            clock.advance(0.016)
            eng.set_level(0.5)
        assert not eng._wake_evt.is_set()
        eng.set_level(0.6)
        assert eng._wake_evt.is_set()

    def test_an_expired_level_coming_back_wakes_it(self, clock):
        from psvr2_engine import LEVEL_TTL_S
        eng = _engine(_FakeCapi(), clock=clock.now)
        eng.set_level(0.5)
        eng._wake_evt.clear()
        clock.advance(LEVEL_TTL_S + 0.1)
        eng.set_level(0.5)
        assert eng._wake_evt.is_set()


class TestSendLoop:
    """The real send thread against the fake CAPI: a routed level goes out,
    a level the router stops sending is taken back, and stop() leaves the
    motor off."""

    def _wait_for(self, cond, timeout=2.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return True
            time.sleep(0.005)
        return False

    def test_level_out_then_back_to_zero(self):
        capi = _FakeCapi()
        cfg = {"min_hz": 5.0, "max_hz": 25.0, "max_cmd_hz": 30.0, "keepalive_s": 0.0}
        eng = PSVR2Engine(get_output_config=lambda: cfg, capi=capi)
        eng._open()                       # starts the real send thread
        try:
            eng.set_level(1.0)
            assert self._wait_for(lambda: 25 in capi.sent)
            # the router stops sending: within the TTL + one loop wait
            assert self._wait_for(lambda: capi.sent[-1] == 0)
        finally:
            eng.stop()
        assert capi.sent[-1] == 0

    def test_a_failed_send_drops_the_link_and_tries_a_zero(self):
        capi = _FakeCapi()
        capi.rumble_result = psvr2_capi.RESULT_TIMEOUT
        cfg = {"min_hz": 5.0, "max_hz": 25.0, "max_cmd_hz": 30.0, "keepalive_s": 0.0}
        eng = PSVR2Engine(get_output_config=lambda: cfg, capi=capi)
        changed = []
        eng.set_state_callback(lambda: changed.append(1))
        eng._open()
        try:
            eng.set_level(1.0)
            assert self._wait_for(lambda: not eng.is_connected)
            assert capi.sent[:2] == [25, 0]
            assert changed
        finally:
            eng.stop()

    def test_off_takes_it_to_zero_at_once(self):
        capi = _FakeCapi()
        cfg = {"min_hz": 5.0, "max_hz": 25.0, "max_cmd_hz": 30.0, "keepalive_s": 0.0}
        eng = PSVR2Engine(get_output_config=lambda: cfg, capi=capi)
        eng._open()
        try:
            eng.set_level(1.0)
            assert self._wait_for(lambda: 25 in capi.sent)
            eng.set_paused(True)
            eng.set_level(1.0)            # still sent: paused wins
            assert self._wait_for(lambda: capi.sent[-1] == 0, timeout=0.2)
        finally:
            eng.stop()


@pytest.fixture
def clean_capi():
    """psvr2_capi caches its load attempt in module globals; save/restore
    them so these tests can't leak into each other or the rest of the suite."""
    saved = (psvr2_capi._lib, psvr2_capi._ATTEMPTED,
             psvr2_capi._LOAD_ERROR, psvr2_capi._DLL_PATH)
    psvr2_capi._lib = None
    psvr2_capi._ATTEMPTED = False
    psvr2_capi._LOAD_ERROR = None
    psvr2_capi._DLL_PATH = None
    yield
    (psvr2_capi._lib, psvr2_capi._ATTEMPTED,
     psvr2_capi._LOAD_ERROR, psvr2_capi._DLL_PATH) = saved


class TestDiscovery:
    """Finding the DLL the way the toolkit's own loader does: it writes its
    CAPI directory into %TEMP%\\psvr2tk_capi_path.txt on first launch."""

    def _publish(self, tmp_path, dll_dir):
        (tmp_path / "psvr2tk_capi_path.txt").write_text(
            str(dll_dir), encoding="utf-8")

    def test_absent_when_the_toolkit_never_ran(self, tmp_path, monkeypatch):
        monkeypatch.setattr(psvr2_capi, "_temp_dirs", lambda: [str(tmp_path)])
        assert psvr2_capi._find_dll() is None

    def test_found_via_the_published_path(self, tmp_path, monkeypatch):
        dll_dir = tmp_path / "toolkit"
        dll_dir.mkdir()
        dll = dll_dir / "psvr2_toolkit_capi.dll"
        dll.write_bytes(b"not a real dll")
        self._publish(tmp_path, dll_dir)
        monkeypatch.setattr(psvr2_capi, "_temp_dirs", lambda: [str(tmp_path)])
        assert psvr2_capi._find_dll() == str(dll)

    def test_stale_path_file_without_the_dll_is_absent(self, tmp_path, monkeypatch):
        self._publish(tmp_path, tmp_path / "gone")
        monkeypatch.setattr(psvr2_capi, "_temp_dirs", lambda: [str(tmp_path)])
        assert psvr2_capi._find_dll() is None

    def test_missing_toolkit_stays_retryable(self, tmp_path, monkeypatch,
                                             clean_capi):
        # Someone can install the toolkit while the app is already open, so
        # "not there yet" must not latch the way a broken DLL does.
        monkeypatch.setattr(psvr2_capi.os, "name", "nt")
        monkeypatch.setattr(psvr2_capi, "_temp_dirs", lambda: [str(tmp_path)])
        assert psvr2_capi.load() is False
        assert psvr2_capi._ATTEMPTED is False
        assert "not detected" in psvr2_capi.load_error()

    def test_broken_dll_latches(self, tmp_path, monkeypatch, clean_capi):
        # A DLL that won't load won't start loading later either; retrying it
        # on every 5 s tick would just spam.
        dll_dir = tmp_path / "toolkit"
        dll_dir.mkdir()
        (dll_dir / "psvr2_toolkit_capi.dll").write_bytes(b"not a real dll")
        (tmp_path / "psvr2tk_capi_path.txt").write_text(
            str(dll_dir), encoding="utf-8")
        monkeypatch.setattr(psvr2_capi.os, "name", "nt")
        monkeypatch.setattr(psvr2_capi, "_temp_dirs", lambda: [str(tmp_path)])
        monkeypatch.setattr(
            psvr2_capi.ctypes, "CDLL",
            lambda *a, **k: (_ for _ in ()).throw(OSError("bad image")))
        assert psvr2_capi.load() is False
        assert psvr2_capi._ATTEMPTED is True
        assert "load failed" in psvr2_capi.load_error()

    def test_calls_without_a_library_raise(self, clean_capi):
        # Fail loudly rather than silently no-op if a caller skips
        # is_available().
        with pytest.raises(RuntimeError):
            psvr2_capi.set_hmd_rumble(10)


class TestSettings:
    """The output config the engine's send loop reads every tick. FILE_PATH
    is redirected at tmp_path so nothing touches the real AppData dir."""

    def _mgr(self, tmp_path):
        from settings.psvr2 import PSVR2SettingsManager
        cls = type("TmpPSVR2", (PSVR2SettingsManager,),
                   {"FILE_PATH": tmp_path / "psvr2.json"})
        return cls()

    def test_defaults_are_a_usable_band(self, tmp_path):
        out = self._mgr(tmp_path).get_output()
        assert out["min_hz"] == 10.0    # the headset takes 1-9 Hz as 10
        assert out["max_hz"] == 25.0
        assert out["keepalive_s"] == 0.0   # the register latches; off by default

    def test_band_clamped_to_hardware_range(self, tmp_path):
        m = self._mgr(tmp_path)
        m.set_output({"min_hz": -5.0, "max_hz": 900.0})
        out = m.get_output()
        assert out["min_hz"] == 1.0
        assert out["max_hz"] == 25.0

    def test_inverted_band_is_ordered_on_save(self, tmp_path):
        m = self._mgr(tmp_path)
        m.set_output({"min_hz": 20.0, "max_hz": 8.0})
        out = m.get_output()
        assert (out["min_hz"], out["max_hz"]) == (8.0, 20.0)

    def test_command_rate_is_capped(self, tmp_path):
        # The cap protects the headset's USB path and the toolkit's shared
        # command buffer, so it must survive a hand-edited settings file.
        m = self._mgr(tmp_path)
        m.set_output({"max_cmd_hz": 5000.0})
        assert m.get_output()["max_cmd_hz"] == 30.0

    def test_auto_connect_defaults_on(self, tmp_path):
        # feature_psvr2 (off by default) is the opt-in in this edition
        assert self._mgr(tmp_path).get_auto_connect() is True

    def test_contact_defaults_disabled_and_unset(self, tmp_path):
        c = self._mgr(tmp_path).get_contact()
        assert c["enabled"] is False
        assert c["parameter"] == ""

    def test_contact_parameter_is_stored_bare(self, tmp_path):
        # The router looks the name up against parameter_store's bare keys,
        # so a full OSC path (hand-edited, or pasted from the Inspector)
        # has to be stripped or it would silently never match.
        m = self._mgr(tmp_path)
        m.set_contact({"enabled": True,
                       "parameter": "/avatar/parameters/Contact/HeadPat"})
        assert m.get_contact()["parameter"] == "Contact/HeadPat"

    def test_contact_shaping_is_clamped(self, tmp_path):
        m = self._mgr(tmp_path)
        m.set_contact({"parameter": "C", "threshold": 5.0, "gain": 99.0})
        c = m.get_contact()
        assert c["threshold"] == 1.0
        assert c["gain"] == 5.0

    def test_contact_survives_garbage(self, tmp_path):
        m = self._mgr(tmp_path)
        m.set_contact({"parameter": "C", "threshold": "x", "gain": None})
        c = m.get_contact()
        assert c["threshold"] == 0.0
        assert c["gain"] == 1.0

    def test_switched_on_by_default_and_remembered(self, tmp_path):
        # Home's On / Off: Off holds the motor at 0 across restarts too.
        m = self._mgr(tmp_path)
        assert m.get_enabled() is True
        m.set_enabled(False)
        assert self._mgr(tmp_path).get_enabled() is False

    def test_the_full_editions_keys_survive(self, tmp_path):
        # Both editions share psvr2_settings.json; ours must not drop theirs.
        import json
        path = tmp_path / "psvr2.json"
        path.write_text(json.dumps({"min_hz": 7.0, "their_key": 1}), encoding="utf-8")
        m = self._mgr(tmp_path)
        m.set_enabled(False)
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["their_key"] == 1 and saved["min_hz"] == 7.0
