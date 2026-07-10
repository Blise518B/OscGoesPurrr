# handy_engine.py
# Sealed engine for The Handy (Handy 2 / Handy Pro 2) speaking the official
# handyfeeling.com REST API v3. Firmware 4 devices (every Handy 2) are cloud
# routed: the device must be on Wi-Fi and linked to handyfeeling.com, and
# every request carries the device connection key (shown in the Handyverse
# app) plus an API key issued at user.handyfeeling.com.
#
# Two control modes, both lifted from the official examples
# (gitlab.com/sweettechas/platform/platform-api-examples):
#
#   * speed    — HAMP: PUT /hamp/start once, then PUT /hamp/velocity (0-1)
#                on change. The first-party fit for a continuous intensity
#                signal; the device strokes on its own at the commanded speed.
#   * position — HDSP: PUT /hdsp/xpt position+duration commands with
#                stop_on_target=false + immediate_rsp=true (the official
#                client's fire-and-forget defaults). Same send shaping as the
#                Buttplug linear path: duration covers the real send gap with
#                margin so slow motion doesn't "step".
#
# The cloud API is rate limited (documented example window: 240 requests per
# minute), so the engine owns a latest-wins send loop: the router's
# set_level() is O(1) and never blocks, and one worker thread serializes HTTP
# commands under a configurable per-command cap. The first command after a
# quiet gap goes out immediately — the cap only spaces consecutive sends
# (see ARCHITECTURE.md "Latency budget").

import threading
import time
from collections import deque
from typing import Any, Callable, Dict, Optional, Tuple

from engine_base import ReconnectingEngine
from haptic_actuators import compute_send_duration_ms

try:
    import requests
    _REQUESTS_AVAILABLE = True
except Exception:
    requests = None  # type: ignore
    _REQUESTS_AVAILABLE = False

API_BASE = "https://www.handyfeeling.com/api/handy-rest/v3"
HTTP_TIMEOUT_S = 10.0

MODE_SPEED = "speed"
MODE_POSITION = "position"

# Velocity quantization step — /hamp/velocity takes 0-1; 0.01 steps keep a
# noisy analog contact from burning the request budget on imperceptible deltas.
VELOCITY_STEP = 0.01
# Don't re-send a position the slider is already at (float-jitter floor).
POSITION_MIN_DELTA = 0.005
# Position-mode duration shaping. The cloud cadence is far slower than the
# 60 Hz local stroker path, so the band and overlap are tuned for ~100-1000 ms
# send gaps rather than constants.py's BLE values.
POS_DURATION_OVERLAP = 1.25
POS_MIN_INTERVAL_MS = 80.0
POS_MAX_INTERVAL_MS = 1000.0
# Hold-off after the server answers 429 before trying again.
RATE_LIMIT_BACKOFF_S = 5.0


class HandyRateLimited(Exception):
    """Server said 429 — back off without dropping the connection."""


def build_headers(connection_key: str, api_key: str) -> Dict[str, str]:
    """v3 auth: every device call carries the connection key and an API key
    (Application ID or Key). Pure + testable."""
    return {
        "X-Connection-Key": str(connection_key or "").strip(),
        "X-Api-Key": str(api_key or "").strip(),
        "Accept": "application/json",
    }


def quantize_velocity(level01: float, max_velocity: float) -> float:
    """Shape a 0-1 level into the 0-1 HAMP velocity: apply the user's speed
    cap, then snap to VELOCITY_STEP so held contacts don't re-send."""
    try:
        lv = max(0.0, min(1.0, float(level01)))
        cap = max(0.0, min(1.0, float(max_velocity)))
    except (TypeError, ValueError):
        return 0.0
    return round(round(lv * cap / VELOCITY_STEP) * VELOCITY_STEP, 4)


class HandySpeedPlanner:
    """Pure decision core for HAMP speed mode (no I/O, no clock reads).

    The engine calls step() whenever it is allowed to send; it returns at
    most ONE command tuple and updates its own bookkeeping assuming the
    engine executes it (the engine resets the planner on disconnect):

        ("hamp_start", None)       — begin alternating motion (velocity 0)
        ("hamp_velocity", v01)     — set stroke speed
        ("hamp_stop", None)        — idle timeout reached, stop the slide
    """

    def __init__(self, idle_stop_s: float = 5.0):
        self.idle_stop_s = float(idle_stop_s)
        self.playing = False
        self.last_velocity: Optional[float] = None
        self._idle_since: Optional[float] = None

    def reset(self) -> None:
        self.playing = False
        self.last_velocity = None
        self._idle_since = None

    def step(self, velocity01: float, now_s: float) -> Optional[Tuple[str, Any]]:
        v = max(0.0, min(1.0, float(velocity01)))
        if v > 0.0:
            self._idle_since = None
            if not self.playing:
                # /hamp/start begins the motion at velocity 0; the real
                # velocity follows on the next allowed send.
                self.playing = True
                self.last_velocity = 0.0
                return ("hamp_start", None)
            if self.last_velocity != v:
                self.last_velocity = v
                return ("hamp_velocity", v)
            return None
        # Level is zero: park at velocity 0, then stop after the idle grace
        # so the device isn't left in PLAY forever.
        if not self.playing:
            return None
        if self.last_velocity != 0.0:
            self.last_velocity = 0.0
            self._idle_since = now_s
            return ("hamp_velocity", 0.0)
        if self._idle_since is None:
            self._idle_since = now_s
            return None
        if now_s - self._idle_since >= self.idle_stop_s:
            self.reset()
            return ("hamp_stop", None)
        return None


class HandyPositionPlanner:
    """Pure decision core for HDSP position mode.

    Maps a 0-1 level onto the 0-1 slider position. OGB convention: stronger
    contact pulls the sleeve DOWN (xp toward 0); `invert` flips that. Emits
    ("hdsp_move", {"xp": .., "t": ..}) and skips re-sends within
    POSITION_MIN_DELTA. The commanded duration covers the measured send gap
    with margin (compute_send_duration_ms) — the same anti-stepping policy
    as the Buttplug linear path.
    """

    def __init__(self, invert: bool = False):
        self.invert = bool(invert)
        self.last_xp: Optional[float] = None
        self.last_send_ms: Optional[float] = None

    def reset(self) -> None:
        self.last_xp = None
        self.last_send_ms = None

    def step(self, level01: float, now_ms: float) -> Optional[Tuple[str, Any]]:
        lv = max(0.0, min(1.0, float(level01)))
        xp = round(lv if self.invert else 1.0 - lv, 3)
        if self.last_xp is not None and abs(xp - self.last_xp) < POSITION_MIN_DELTA:
            return None
        if self.last_send_ms is None:
            interval_ms = POS_MIN_INTERVAL_MS
        else:
            interval_ms = now_ms - self.last_send_ms
        t = compute_send_duration_ms(
            interval_ms, POS_DURATION_OVERLAP,
            POS_MIN_INTERVAL_MS, POS_MAX_INTERVAL_MS)
        self.last_xp = xp
        self.last_send_ms = now_ms
        return ("hdsp_move", {"xp": xp, "t": int(t)})


class HandyEngine(ReconnectingEngine):
    def __init__(self,
                 get_connection_key: Callable[[], str],
                 get_api_key: Callable[[], str],
                 get_motion_config: Callable[[], Dict[str, Any]],
                 log: Optional[Callable[[str], None]] = None):
        super().__init__("Handy")
        self._get_connection_key = get_connection_key
        self._get_api_key = get_api_key
        # Snapshot of primitive motion settings: mode, stroke_min/max,
        # max_velocity, idle_stop_s, invert, max_cmd_hz.
        self._get_motion_config = get_motion_config
        self._log = log or (lambda _m: None)

        self._state_lock = threading.Lock()
        self._level = 0.0
        self._wake_evt = threading.Event()
        self._send_thread: Optional[threading.Thread] = None
        self._send_gen = 0  # bumped per connection; stale send loops exit
        # Cloud health telemetry for the status card: last HTTP round-trip
        # and requests in the last 60 s (vs the documented ~240/min budget).
        # RTT dominates this backend's end-to-end feel, so the user needs
        # to see it to tell "slow cloud path" apart from "wrong thresholds".
        self._rtt_lock = threading.Lock()
        self._last_rtt_ms: Optional[float] = None
        self._send_times: deque = deque()
        self._session = None
        self._device_info: Dict[str, Any] = {}
        self._stroke_dirty = False
        self._active_mode = MODE_SPEED
        self._speed = HandySpeedPlanner()
        self._pos = HandyPositionPlanner()
        self._next_allowed = 0.0

    @property
    def _available(self) -> bool:
        return _REQUESTS_AVAILABLE

    @property
    def _unavailable_reason(self) -> str:
        return "requests not installed (pip install requests)"

    # ---- hot path (called from the router thread) --------------------
    def set_level(self, level: float) -> None:
        try:
            lv = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            lv = 0.0
        with self._state_lock:
            self._level = lv
        self._wake_evt.set()

    def refresh_stroke_zone(self) -> None:
        """Re-push the slider stroke zone (called when the user edits it)."""
        self._stroke_dirty = True
        self._wake_evt.set()

    # ---- status for the facade (primitives only) ----------------------
    def get_status_extras(self) -> Dict[str, Any]:
        with self._state_lock:
            level = self._level
        with self._rtt_lock:
            cutoff = time.monotonic() - 60.0
            while self._send_times and self._send_times[0] < cutoff:
                self._send_times.popleft()
            sends_per_min = len(self._send_times)
            # An idle link says nothing about the cloud path *now*: once
            # no request has flowed for the whole window, stop reporting
            # the last sample as current health.
            rtt_ms = self._last_rtt_ms if self._send_times else None
        return {
            "fw_version": self._device_info.get("fw_version"),
            "hw_model_name": self._device_info.get("hw_model_name"),
            "fw_update_required": self._device_info.get("fw_status") == 2,
            "playing": self._speed.playing,
            "mode": self._active_mode,
            "level": level,
            "rtt_ms": rtt_ms,
            "sends_per_min": sends_per_min,
        }

    # ---- ReconnectingEngine transport hooks --------------------------
    def _open(self) -> None:
        if not _REQUESTS_AVAILABLE:
            raise RuntimeError(self._unavailable_reason)
        key = (self._get_connection_key() or "").strip()
        api_key = (self._get_api_key() or "").strip()
        if not key:
            raise RuntimeError("connection key not set (shown in the Handyverse app)")
        if not api_key:
            raise RuntimeError("API key not set (create one at user.handyfeeling.com)")

        session = requests.Session()
        session.headers.update(build_headers(key, api_key))
        try:
            payload = self._request(session, "GET", "/connected")
            if not (payload.get("result") or {}).get("connected"):
                raise RuntimeError(
                    "device offline (Handy must be on Wi-Fi and linked to handyfeeling.com)")
            try:
                info = (self._request(session, "GET", "/info").get("result") or {})
            except Exception:
                info = {}
        except Exception:
            session.close()
            raise

        self._device_info = {
            "fw_version": info.get("fw_version"),
            "fw_status": info.get("fw_status"),
            "hw_model_name": info.get("hw_model_name"),
        }
        if info.get("fw_status") == 2:
            self._log("Handy: firmware update REQUIRED — update via handyverse.com before use")

        self._session = session
        self._speed.reset()
        self._pos.reset()
        self._active_mode = MODE_SPEED
        self._stroke_dirty = True   # send loop pushes the stroke zone first
        self._next_allowed = 0.0
        self._connected = True
        self._start_send_thread()

    def _close(self) -> None:
        self._connected = False   # the send thread exits on this
        # Invalidate any send thread parked inside a slow HTTP call: a stale
        # loop must never resurrect against a future session or clobber its
        # _connected flag from a dying request.
        self._send_gen += 1
        self._wake_evt.set()
        session, self._session = self._session, None
        if session is not None:
            if self._speed.playing:
                try:
                    session.put(f"{API_BASE}/hamp/stop", timeout=2.0)
                except Exception:
                    pass
            self._speed.reset()
            try:
                session.close()
            except Exception:
                pass

    # ---- send loop ----------------------------------------------------
    def _start_send_thread(self) -> None:
        # Each connection gets a generation token: the loop exits when its
        # token goes stale, so an old thread blocked in a 10 s HTTP call can
        # never run beside a new session's thread or clobber its state.
        self._send_gen += 1
        t = threading.Thread(target=self._send_loop, args=(self._send_gen,),
                             daemon=True, name="HandySend")
        self._send_thread = t
        t.start()

    def _send_loop(self, gen: int) -> None:
        def live() -> bool:
            return self._connected and gen == self._send_gen

        while live():
            self._wake_evt.wait(timeout=0.1)
            self._wake_evt.clear()
            if not live():
                break
            now = time.monotonic()
            while live() and now < self._next_allowed:
                # Rate cap: sleep out the remainder, then fall THROUGH to
                # planning with the LATEST level (latest-wins coalescing).
                # Re-entering the (already cleared) event wait here used to
                # add up to +100 ms on every capped send.
                time.sleep(min(self._next_allowed - now, 0.1))
                now = time.monotonic()
            if not live():
                break
            cfg = self._get_motion_config() or {}
            cmd = self._plan_next(cfg, now)
            if cmd is None:
                continue
            try:
                self._execute(cmd)
            except HandyRateLimited:
                # The command was DROPPED by the cloud: undo the planners'
                # "already sent" bookkeeping so the next allowed send
                # re-emits it — otherwise the newest velocity/position/stroke
                # is silently lost until the level happens to change again.
                self._rollback_plan(cmd)
                self._log("Handy: cloud rate limit hit — backing off")
                self._next_allowed = time.monotonic() + RATE_LIMIT_BACKOFF_S
                continue
            except Exception as e:
                if gen != self._send_gen:
                    break  # our session was torn down mid-request; not ours to report
                self._log(f"Handy send failed: {e}")
                self._connected = False
                break
            try:
                hz = max(0.5, min(15.0, float(cfg.get("max_cmd_hz", 4.0))))
            except (TypeError, ValueError):
                hz = 4.0
            self._next_allowed = time.monotonic() + 1.0 / hz

    def _rollback_plan(self, cmd: Tuple[str, Any]) -> None:
        """A planned command was not delivered (rate-limited): rewind the
        planner bookkeeping that `_plan_next` committed optimistically, so
        the command is re-planned on the next allowed send."""
        kind, _arg = cmd
        if kind == "hamp_start":
            self._speed.reset()
        elif kind == "hamp_stop":
            # The device is still in PLAY: model it as playing at an unknown
            # velocity so the stop sequence re-plans (velocity 0 -> stop).
            self._speed.playing = True
            self._speed.last_velocity = None
            self._speed._idle_since = None
        elif kind == "hamp_velocity":
            self._speed.last_velocity = None
        elif kind == "hdsp_move":
            self._pos.last_xp = None
        elif kind == "stroke":
            self._stroke_dirty = True

    def _plan_next(self, cfg: Dict[str, Any], now_s: float) -> Optional[Tuple[str, Any]]:
        with self._state_lock:
            level = self._level

        if self._stroke_dirty:
            self._stroke_dirty = False
            return ("stroke", _clean_stroke(cfg))

        mode = str(cfg.get("mode", MODE_SPEED))
        if mode not in (MODE_SPEED, MODE_POSITION):
            mode = MODE_SPEED
        if mode != self._active_mode:
            if self._speed.playing:
                # Leaving speed mode: stop the alternating motion first.
                self._speed.reset()
                return ("hamp_stop", None)
            self._active_mode = mode
            self._pos.reset()

        if self._active_mode == MODE_SPEED:
            try:
                self._speed.idle_stop_s = max(0.5, float(cfg.get("idle_stop_s", 5.0)))
            except (TypeError, ValueError):
                self._speed.idle_stop_s = 5.0
            target = quantize_velocity(level, cfg.get("max_velocity", 1.0))
            return self._speed.step(target, now_s)

        self._pos.invert = bool(cfg.get("invert", False))
        return self._pos.step(level, now_s * 1000.0)

    def _execute(self, cmd: Tuple[str, Any]) -> None:
        kind, arg = cmd
        session = self._session
        if session is None:
            raise ConnectionError("no session")
        if kind == "hamp_start":
            self._request(session, "PUT", "/hamp/start")
        elif kind == "hamp_stop":
            self._request(session, "PUT", "/hamp/stop")
        elif kind == "hamp_velocity":
            self._request(session, "PUT", "/hamp/velocity", {"velocity": arg})
        elif kind == "hdsp_move":
            self._request(session, "PUT", "/hdsp/xpt", {
                "xp": arg["xp"],
                "t": arg["t"],
                "stop_on_target": False,
                "immediate_rsp": True,
            })
        elif kind == "stroke":
            self._request(session, "PUT", "/slider/stroke", arg)

    # ---- HTTP ----------------------------------------------------------
    def _request(self, session, method: str, path: str,
                 body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        t0 = time.monotonic()
        r = session.request(method, API_BASE + path, json=body, timeout=HTTP_TIMEOUT_S)
        now = time.monotonic()
        with self._rtt_lock:
            self._last_rtt_ms = (now - t0) * 1000.0
            self._send_times.append(now)
            cutoff = now - 60.0
            while self._send_times and self._send_times[0] < cutoff:
                self._send_times.popleft()
        if r.status_code == 429:
            raise HandyRateLimited()
        if r.status_code in (401, 403):
            raise RuntimeError("auth rejected (check the API key and connection key)")
        r.raise_for_status()
        try:
            payload = r.json() or {}
        except ValueError:
            payload = {}
        err = payload.get("error")
        if err:
            name = err.get("name") or "error"
            if err.get("connected") is False:
                raise ConnectionError(f"device dropped offline ({name})")
            raise RuntimeError(f"API error: {name}")
        return payload


def _clean_stroke(cfg: Dict[str, Any]) -> Dict[str, float]:
    """Clamp the configured slider zone into a sane 0-1 window. Pure."""
    try:
        mn = max(0.0, min(1.0, float(cfg.get("stroke_min", 0.0))))
    except (TypeError, ValueError):
        mn = 0.0
    try:
        mx = max(0.0, min(1.0, float(cfg.get("stroke_max", 1.0))))
    except (TypeError, ValueError):
        mx = 1.0
    if mx < mn:
        mn, mx = mx, mn
    if mx - mn < 0.05:   # keep a usable window even on bad input
        mx = min(1.0, mn + 0.05)
        mn = mx - 0.05
    return {"min": round(mn, 3), "max": round(mx, 3)}
