# psvr2_engine.py
# Sealed engine for the PlayStation VR2 headset rumble motor, driven through
# the PSVR2Toolkit C API (see psvr2_capi.py for the ctypes binding).
#
# The headset exposes exactly ONE knob: a rumble FREQUENCY byte, 0-25 Hz,
# where 0 stops the motor. There is no separate amplitude — a 0-1 contact
# level maps onto the Hz band, so light contact reads as a slow thump and
# strong contact as a fast buzz. That is the only expression the hardware
# offers; the usable band is configurable because the extremes of 0-25 are
# not equally useful on every unit.
#
# Requires a JAILBROKEN headset. On a stock unit the call succeeds and the
# motor stays inert, and nothing in the API reports that — so a silent
# headset with a healthy "connected" status is the expected symptom.
#
# WHY THE ENGINE OWNS A SEND THREAD
# ---------------------------------
# psvr2_toolkit_set_hmd_rumble() blocks until the driver acknowledges (the
# toolkit spins on a shared-memory `isFulfilled` flag, up to 5 s) and the
# driver turns every command into a USB control transfer to the headset. That
# is precisely the ack-blocking pattern ARCHITECTURE.md's latency budget bans
# from hot paths, so the engine owns a latest-wins send loop: the router's
# set_level() is O(1) and never blocks, and one worker thread serializes the
# actual calls under a configurable command cap. The cap is a HARDWARE
# requirement here, not politeness — a 60 Hz router hammering USB control
# transfers would both hurt the headset and starve other toolkit clients out
# of the shared command ring buffer. The first command after a quiet gap goes
# out immediately; the cap only spaces consecutive sends.
#
# The 0-25 Hz integer quantization does most of the debouncing for free:
# across the whole 0-1 level range there are at most 26 distinct commands.
#
# THE LAST GATE (this edition's rules, on top of main's engine)
# -------------------------------------------------------------
# The driver writes the frequency to a headset register that LATCHES, so a
# value nobody takes back would buzz forever. So, as for the haptic trackers:
#   * the router re-sends the level every tick, and a level not re-sent for
#     LEVEL_TTL_S plays nothing -- if the router dies, the motor stops;
#   * paused (Home's On / Off) holds the motor at 0 and refuses test buzzes;
#   * stop / quit sends a last 0 (main's _close).
# set_level() wakes the send thread only when the level changes (or an
# expired one comes back), so a held contact costs no extra wakeups.

import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Optional

import psvr2_capi
from engine_base import ReconnectingEngine

# A non-zero contact must never map to 0 Hz — that byte means "motor off", so
# the bottom of the band is clamped up to 1.
MIN_ACTIVE_HZ = 1
# Default test-pulse length for the UI button. Bounded so a test can never
# latch the motor on if the user navigates away mid-pulse.
TEST_PULSE_S = 1.5
# A level the router stops re-sending plays nothing after this (the router
# ticks at ~60 Hz; the send loop notices within its 0.1 s wait).
LEVEL_TTL_S = 0.25


def level_to_rumble_hz(level01: float, min_hz: float, max_hz: float) -> int:
    """Map a 0-1 level onto the headset's rumble frequency byte. Pure.

    Zero level is zero Hz (motor off). Any non-zero level lands inside the
    configured [min_hz..max_hz] band — the band's floor exists because low
    frequencies may not move the motor at all, so a barely-there contact
    should still produce something felt rather than silence. Deadbanding
    weak contact is the router's threshold's job, not this function's.
    """
    try:
        lv = float(level01)
    except (TypeError, ValueError):
        return 0
    if not lv > 0.0:                     # also NaN, which min() would make 1.0
        return 0
    lv = min(1.0, lv)
    try:
        lo = float(min_hz)
    except (TypeError, ValueError):
        lo = MIN_ACTIVE_HZ
    try:
        hi = float(max_hz)
    except (TypeError, ValueError):
        hi = psvr2_capi.RUMBLE_HZ_MAX
    lo = max(MIN_ACTIVE_HZ, min(psvr2_capi.RUMBLE_HZ_MAX, lo))
    hi = max(MIN_ACTIVE_HZ, min(psvr2_capi.RUMBLE_HZ_MAX, hi))
    if hi < lo:
        lo, hi = hi, lo
    return int(round(lo + lv * (hi - lo)))


class HmdRumblePlanner:
    """Pure decision core: which rumble byte to send, if any. No I/O, no
    clock reads (the engine passes `now_s`).

    The driver writes the value straight to a headset register, so it is
    treated as latching: send on change and stay quiet otherwise. The
    keepalive is a hedge — if the register turns out to decay rather than
    latch on some firmware, a non-zero value can be re-sent every
    `keepalive_s`. Off by default; a keepalive costs a USB control transfer
    per interval for no benefit when the value really does latch.
    """

    def __init__(self, keepalive_s: float = 0.0):
        self.keepalive_s = float(keepalive_s)
        self.last_hz: Optional[int] = None
        self._last_send_s: float = 0.0

    def reset(self) -> None:
        """Forget what the device holds, so the next step() re-sends. Called
        on connect: a fresh link must not assume the motor's state."""
        self.last_hz = None
        self._last_send_s = 0.0

    def step(self, hz: int, now_s: float) -> Optional[int]:
        hz = int(hz)
        if hz != self.last_hz:
            self.last_hz = hz
            self._last_send_s = now_s
            return hz
        if (self.keepalive_s > 0.0 and hz > 0
                and now_s - self._last_send_s >= self.keepalive_s):
            self._last_send_s = now_s
            return hz
        return None


class PSVR2Engine(ReconnectingEngine):
    def __init__(self,
                 get_output_config: Callable[[], Dict[str, Any]],
                 log: Optional[Callable[[str], None]] = None,
                 capi=None,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__("PSVR2")
        # Stamps each routed level for LEVEL_TTL_S; injectable for tests.
        self._clock = clock
        # Snapshot of primitive output settings: min_hz, max_hz, max_cmd_hz,
        # keepalive_s. Re-read every send tick so edits apply live.
        self._get_output_config = get_output_config
        self._log = log or (lambda _m: None)
        # Injectable so the send loop and lifecycle are testable without the
        # toolkit installed (the CAPI is Windows + PSVR2 hardware only).
        self._capi = capi if capi is not None else psvr2_capi

        self._state_lock = threading.Lock()
        # Serializes every call into the DLL. Uncontended on the hot path (one
        # send thread), but load-bearing at teardown: _close()'s "stop the
        # motor" 0 must not overtake a send already blocked inside the driver
        # ack, or the stale command would land last and leave the headset
        # buzzing after we disconnected.
        self._send_lock = threading.Lock()
        self._level = 0.0
        self._level_at = float("-inf")   # when the router last sent it
        self._paused = False
        self._test_hz = 0
        self._test_until = 0.0
        self._wake_evt = threading.Event()
        self._send_thread: Optional[threading.Thread] = None
        self._send_gen = 0  # bumped per connection; stale send loops exit
        self._planner = HmdRumblePlanner()
        self._next_allowed = 0.0
        # Status telemetry for the card. The ack round-trip is worth showing:
        # it is the one number that separates "the toolkit is fine and the
        # headset just isn't jailbroken" from "the driver is wedged".
        self._tel_lock = threading.Lock()
        self._last_rtt_ms: Optional[float] = None
        self._send_times: deque = deque()
        self._driver_active = False
        self._slotless = False

    @property
    def _available(self) -> bool:
        return self._capi.is_available()

    @property
    def _unavailable_reason(self) -> str:
        return self._capi.load_error() or "PSVR2Toolkit not detected"

    # ---- hot path (called from the router thread) --------------------
    def set_level(self, level: float) -> None:
        """O(1), never blocks. The send thread picks up the latest value.
        The router calls this every tick (zeros too): a level that isn't
        sent again for LEVEL_TTL_S plays nothing. Wakes the send thread
        only on a change, or when an expired level comes back."""
        try:
            lv = float(level)
        except (TypeError, ValueError):
            lv = 0.0
        # NaN first: min(1.0, nan) is 1.0, so a NaN clamped would buzz full
        lv = 0.0 if lv != lv else max(0.0, min(1.0, lv))
        now = self._clock()
        with self._state_lock:
            changed = (lv != self._level
                       or (lv > 0.0 and now - self._level_at > LEVEL_TTL_S))
            self._level = lv
            self._level_at = now
        if changed:
            self._wake_evt.set()

    def set_paused(self, paused: bool) -> None:
        """Home's On / Off. Paused holds the motor at 0 (the send loop
        takes it there at once) and refuses test buzzes."""
        with self._state_lock:
            self._paused = bool(paused)
            if self._paused:
                self._test_until = 0.0
        self._wake_evt.set()
        self._notify_state_change()

    @property
    def is_paused(self) -> bool:
        return self._paused

    def test_pulse(self, hz: Optional[int] = None,
                   duration_s: float = TEST_PULSE_S) -> bool:
        """Buzz the headset for a bounded moment so the user can confirm the
        whole chain end-to-end (jailbreak included) without an avatar. Time
        bounded by construction — the send loop reverts to the routed level
        when the deadline passes, so a test can never latch the motor on.
        False (nothing sent) while paused or not connected."""
        if self._paused or not self._connected:
            return False
        cfg = self._get_output_config() or {}
        if hz is None:
            hz = level_to_rumble_hz(1.0, cfg.get("min_hz", MIN_ACTIVE_HZ),
                                    cfg.get("max_hz", psvr2_capi.RUMBLE_HZ_MAX))
        try:
            dur = max(0.1, min(10.0, float(duration_s)))
        except (TypeError, ValueError):
            dur = TEST_PULSE_S
        with self._state_lock:
            self._test_hz = max(0, min(psvr2_capi.RUMBLE_HZ_MAX, int(hz)))
            self._test_until = self._clock() + dur
        self._wake_evt.set()
        return True

    # ---- status for the facade (primitives only) ----------------------
    def get_status_extras(self) -> Dict[str, Any]:
        level = self._live_level(self._clock())
        with self._tel_lock:
            cutoff = time.monotonic() - 60.0
            while self._send_times and self._send_times[0] < cutoff:
                self._send_times.popleft()
            sends_per_min = len(self._send_times)
            # An idle link says nothing about the driver path *now*: once no
            # command has flowed for the whole window, stop reporting the last
            # sample as current health.
            rtt_ms = self._last_rtt_ms if self._send_times else None
        return {
            "driver_active": self._driver_active,
            "level": level,
            "rumble_hz": self._planner.last_hz,
            "rtt_ms": rtt_ms,
            "sends_per_min": sends_per_min,
            "slotless": self._slotless,
            "paused": self._paused,
            "dll_path": self._capi.dll_path(),
        }

    def _live_level(self, now_s: float) -> float:
        """The routed level, or 0 while paused or once it went unsent for
        LEVEL_TTL_S."""
        with self._state_lock:
            if self._paused or now_s - self._level_at > LEVEL_TTL_S:
                return 0.0
            return self._level

    # ---- ReconnectingEngine transport hooks --------------------------
    def _open(self) -> None:
        if not self._capi.is_available():
            raise RuntimeError(self._unavailable_reason)
        # init() is idempotent in the DLL: the slot lives in a module global
        # and is re-used, so a send loop that exited without closing (driver
        # went away mid-session) costs nothing to recover from.
        result = self._capi.init()
        # experimental-1's init() said DRIVER_INACTIVE; since experimental-2
        # it succeeds without SteamVR, so ask -- or the 1 s liveness check
        # would drop a "connected" link every second while SteamVR is off.
        driver_off = result == psvr2_capi.RESULT_DRIVER_INACTIVE
        if not driver_off:
            try:
                driver_off = not self._capi.get_driver_active()
            except Exception:
                driver_off = True
            if driver_off:
                try:
                    self._capi.deinit()      # don't sit on a slot meanwhile
                except Exception:
                    pass
        if driver_off:
            raise RuntimeError(
                "PSVR2 driver not active — start SteamVR with PSVR2Toolkit installed")
        # RESULT_NO_SLOT is survivable: headset rumble is the one command that
        # doesn't require a claimed IPC slot (the toolkit skips the slot guard
        # for it), so all 8 slots being taken by other apps costs us nothing.
        self._slotless = (result == psvr2_capi.RESULT_NO_SLOT)
        if self._slotless:
            self._log("PSVR2: all toolkit client slots are in use — headset "
                      "rumble still works (it needs no slot)")
        elif result != psvr2_capi.RESULT_OK:
            raise RuntimeError(f"PSVR2 CAPI init failed (code {result})")

        self._driver_active = True
        # A fresh link must not assume what the motor is holding: reset makes
        # the first send tick push the current level unconditionally.
        self._planner.reset()
        self._next_allowed = 0.0
        self._connected = True
        self._start_send_thread()

    def _close(self) -> None:
        self._connected = False   # the send thread exits on this
        # Invalidate any send thread parked inside a blocking ack: a stale
        # loop must never run beside a new connection's thread.
        self._send_gen += 1
        self._wake_evt.set()
        # Leave the motor OFF. Only worth a (blocking) call when we believe
        # it is actually running — this runs on the caller's thread at app
        # shutdown, and an unnecessary ack wait would stall the quit. Taking
        # the send lock makes this the LAST command to reach the headset even
        # if the send thread was mid-ack when we were called.
        if self._planner.last_hz:
            try:
                with self._send_lock:
                    self._capi.set_hmd_rumble(0)
            except Exception:
                pass
        self._planner.reset()
        self._driver_active = False
        self._slotless = False
        try:
            self._capi.deinit()
        except Exception:
            pass

    # ---- send loop ----------------------------------------------------
    def _start_send_thread(self) -> None:
        # Each connection gets a generation token: the loop exits when its
        # token goes stale, so an old thread blocked in a 5 s ack can never
        # run beside a new connection's thread or clobber its state.
        self._send_gen += 1
        t = threading.Thread(target=self._send_loop, args=(self._send_gen,),
                             daemon=True, name="PSVR2Send")
        self._send_thread = t
        t.start()

    def _send_loop(self, gen: int) -> None:
        def live() -> bool:
            return self._connected and gen == self._send_gen

        next_driver_check = 0.0
        while live():
            self._wake_evt.wait(timeout=0.1)
            self._wake_evt.clear()
            if not live():
                break
            now = time.monotonic()

            # Cheap liveness poll (~1 Hz): SteamVR closing takes the driver
            # with it, and without this we would sit "connected" forever
            # instead of letting the reconnect loop retry.
            if now >= next_driver_check:
                next_driver_check = now + 1.0
                try:
                    self._driver_active = bool(self._capi.get_driver_active())
                except Exception:
                    self._driver_active = False
                if not self._driver_active:
                    self._log("PSVR2: driver went away — will reconnect")
                    self._connected = False
                    self._notify_state_change()
                    break

            while live() and now < self._next_allowed:
                # Command cap: sleep out the remainder, then fall THROUGH to
                # planning with the LATEST level (latest-wins coalescing).
                time.sleep(min(self._next_allowed - now, 0.05))
                now = time.monotonic()
            if not live():
                break

            cfg = self._get_output_config() or {}
            hz = self._resolve_hz(cfg, self._clock())
            try:
                self._planner.keepalive_s = max(0.0, float(cfg.get("keepalive_s", 0.0)))
            except (TypeError, ValueError):
                self._planner.keepalive_s = 0.0
            cmd = self._planner.step(hz, now)
            if cmd is None:
                continue
            try:
                self._send(cmd)
            except Exception as e:
                if gen != self._send_gen:
                    break  # our link was torn down mid-call; not ours to report
                self._log(f"PSVR2 rumble send failed: {e}")
                self._connected = False
                # The register latches: if the driver is still there (a
                # timeout), try to leave the motor off. Best effort, on this
                # thread; a driver that's gone answers at once.
                try:
                    with self._send_lock:
                        self._capi.set_hmd_rumble(0)
                except Exception:
                    pass
                self._planner.reset()
                self._notify_state_change()
                break
            try:
                rate = max(1.0, min(30.0, float(cfg.get("max_cmd_hz", 10.0))))
            except (TypeError, ValueError):
                rate = 10.0
            self._next_allowed = time.monotonic() + 1.0 / rate

    def _resolve_hz(self, cfg: Dict[str, Any], now_s: float) -> int:
        """The frequency this tick should hold: 0 while paused; else a live
        test pulse wins over the routed level until its deadline passes; a
        routed level not re-sent for LEVEL_TTL_S is 0."""
        with self._state_lock:
            if self._paused:
                return 0
            level = self._level if now_s - self._level_at <= LEVEL_TTL_S else 0.0
            test_hz = self._test_hz
            test_until = self._test_until
        if now_s < test_until:
            return test_hz
        return level_to_rumble_hz(level, cfg.get("min_hz", MIN_ACTIVE_HZ),
                                  cfg.get("max_hz", psvr2_capi.RUMBLE_HZ_MAX))

    def _send(self, hz: int) -> None:
        t0 = time.monotonic()
        with self._send_lock:
            result = self._capi.set_hmd_rumble(hz)
        failed = psvr2_capi.rumble_failed(result)
        if failed:
            # the send loop drops the link; the reconnect loop takes over
            raise RuntimeError(failed)
        now = time.monotonic()
        with self._tel_lock:
            self._last_rtt_ms = (now - t0) * 1000.0
            self._send_times.append(now)
            cutoff = now - 60.0
            while self._send_times and self._send_times[0] < cutoff:
                self._send_times.popleft()
