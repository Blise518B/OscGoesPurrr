# pishock_engine.py
# Sealed shocker engine: the USB hub link's lifecycle plus the hot pulse /
# hold path, with the hard safety rules that are the last gate before a
# shock reaches a person. The hub runs PiShock's firmware or OpenShock's;
# the link speaks both (pishock_serial.py), and nothing here depends on
# which.
#
# Every send goes through here, so nothing — a buggy router, a test button,
# a hand-edited settings file — can get past these rules:
#   * intensity is capped at the user's ceilings -- one for shocks, its own
#     for vibrates, never above 100 -- and pulse length at the user's max
#     (never above 15 s); each shocker may have its own of these three, one
#     without takes the hub-wide ones;
#   * shock turns into vibrate until shocks are armed (the arming is the
#     user's, remembered across launches by the settings);
#   * a shocker rests `cooldown_s` after a pulse ends before the next one —
#     except that a STRONGER pulse may replace one that is still running, so
#     a hard hit whose receivers arrive a moment apart still lands at the
#     strength of the hardest one;
#   * a continuous hold runs at most `max_hold_s`, then the shocker is forced
#     to rest `hold_rest_s`;
#   * paused (the page's Stop) ends everything and refuses every send.
#
# Holds ("continuous") are sent as short overlapping chunks: the hub runs each
# operate for its duration and a new one for the same shocker takes over, so
# while a hold is live the engine re-sends every HOLD_REFRESH_S a chunk of
# HOLD_CHUNK_MS, and on release it sends `end`. If the link or the app dies
# mid-hold the shocker stops on its own within one chunk.

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import pishock_serial
from pishock_limits import RANGES

OP_SHOCK = "shock"
OP_VIBRATE = "vibrate"
OP_BEEP = "beep"
VALID_OPS = (OP_SHOCK, OP_VIBRATE, OP_BEEP)

HOLD_CHUNK_MS = 300
HOLD_REFRESH_S = 0.2
# A hold whose strength moves is re-sent at most this often (the first send
# after idle is never delayed).
HOLD_CHANGE_GAP_S = 0.05

_RECONNECT_EVERY_S = 3.0
# A hub that refuses commands (OpenShock's E-Stop) says so on every send;
# the log hears about it at most this often.
_HUB_ERROR_LOG_EVERY_S = 5.0
_NEG_INF = -1e18


@dataclass
class _Shocker:
    pulse_until: float = _NEG_INF
    pulse_intensity: int = 0
    pulse_op: str = ""
    hold_op: Optional[str] = None       # what the router wants held now
    hold_intensity: int = 0
    hold_started: float = _NEG_INF
    sent_op: Optional[str] = None       # what the last hold chunk carried
    sent_intensity: int = 0
    sent_at: float = _NEG_INF
    rest_until: float = _NEG_INF
    released_at: float = _NEG_INF       # when a hold last let go


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _clamp_float(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:
        return default
    return max(lo, min(hi, v))


class PiShockEngine:
    """Drives the shockers paired to one USB hub. Public surface is
    primitive-only; the link, the shocker list and the per-shocker state
    are private."""

    def __init__(self,
                 link_factory: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 log: Optional[Callable[[str], None]] = None):
        self._link_factory = link_factory or pishock_serial.PiShockSerialLink
        self._clock = clock
        self._log = log or (lambda _m: None)
        self._state_callback: Callable[[], None] = lambda: None

        self._lock = threading.RLock()        # per-shocker hot-path state
        self._connect_lock = threading.Lock()  # one connect attempt at a time
        self._link = None
        self._connecting = False
        self._last_error: Optional[str] = None
        self._port_setting = ""                # "" = find the hub
        self._info: Dict[str, Any] = {}
        self._shockers: Dict[int, _Shocker] = {}
        self._os_shockers: List[Dict[str, Any]] = []
        self._names: Dict[str, str] = {}       # your names, by shocker id
        self._hub_error_logged_at = _NEG_INF

        self._want_connected = False
        self._supervisor: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self._armed = False
        self._paused = False
        self._max_intensity = 30
        self._max_vibrate = 30
        self._max_pulse_ms = 1000
        self._cooldown_s = 0.5
        self._max_hold_s = 10.0
        self._hold_rest_s = 2.0
        # a shocker's own caps by id -- only the ones it has
        self._shocker_own: Dict[int, Dict[str, int]] = {}

    # ---- status ------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return pishock_serial.SERIAL_AVAILABLE

    @property
    def is_connected(self) -> bool:
        link = self._link
        return link is not None and link.is_open

    @property
    def is_connecting(self) -> bool:
        return self._connecting

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def port(self) -> str:
        link = self._link
        return link.port if link is not None else ""

    @property
    def hub_kind(self) -> str:
        """pishock_serial.PISHOCK / OPENSHOCK while connected, else ""."""
        link = self._link
        return link.kind if link is not None else ""

    @property
    def firmware(self) -> str:
        return str(self._info.get("version", ""))

    @property
    def board(self) -> str:
        return str(self._info.get("board", "") or "")

    @property
    def is_armed(self) -> bool:
        return self._armed

    @property
    def is_paused(self) -> bool:
        return self._paused

    def shockers(self) -> List[Dict[str, Any]]:
        names = self._names
        return [dict(s, name=names[str(s["id"])]) if str(s.get("id")) in names else dict(s)
                for s in self._info.get("shockers", [])]

    def shocker_ids(self) -> List[int]:
        return [s["id"] for s in self._info.get("shockers", [])]

    def limits(self) -> Dict[str, Any]:
        return {
            "max_intensity": self._max_intensity,
            "max_vibrate": self._max_vibrate,
            "max_pulse_ms": self._max_pulse_ms,
            "cooldown_s": self._cooldown_s,
            "max_hold_s": self._max_hold_s,
            "hold_rest_s": self._hold_rest_s,
        }

    def limits_for(self, shocker_id: int) -> Dict[str, int]:
        """One shocker's caps: its own, else the hub-wide ones."""
        shock, vib, ms = self._caps_of(shocker_id)
        return {"max_intensity": shock, "max_vibrate": vib, "max_pulse_ms": ms}

    def _caps_of(self, shocker_id: int) -> Tuple[int, int, int]:
        """(max shock, max vibrate, longest pulse ms) for one shocker."""
        own = self._shocker_own.get(shocker_id) or {}
        return (own.get("max_intensity", self._max_intensity),
                own.get("max_vibrate", self._max_vibrate),
                own.get("max_pulse_ms", self._max_pulse_ms))

    def output_snapshot(self) -> Dict[int, Dict[str, Any]]:
        """What each shocker is doing right now (for the page's live row)."""
        now = self._clock()
        out: Dict[int, Dict[str, Any]] = {}
        with self._lock:
            for sid, st in self._shockers.items():
                if now < st.pulse_until:
                    out[sid] = {"kind": "pulse", "op": st.pulse_op,
                                "intensity": st.pulse_intensity}
                elif st.sent_op is not None:
                    out[sid] = {"kind": "hold", "op": st.sent_op,
                                "intensity": st.sent_intensity}
                elif now < st.rest_until:
                    out[sid] = {"kind": "rest", "op": "", "intensity": 0}
        return out

    # ---- configuration -----------------------------------------------
    def set_state_callback(self, fn: Optional[Callable[[], None]]) -> None:
        """Called from background threads whenever the connection state or
        shocker list changes. Must be cheap and thread-safe."""
        self._state_callback = fn or (lambda: None)

    def set_port(self, port: str) -> None:
        self._port_setting = str(port or "").strip()

    def set_shocker_names(self, names: Dict[str, str]) -> None:
        """Your names for the shockers (by id), over what the hub calls
        them -- every list of shockers carries them from here on."""
        self._names = {str(k): str(v) for k, v in (names or {}).items() if v}

    def set_openshock_shockers(self, shockers: List[Dict[str, Any]]) -> None:
        """The page's list for an OpenShock hub (id, model, name). A shocker
        taken off the list is stopped first, while the link still knows its
        model."""
        self._os_shockers = [dict(s) for s in shockers or []]
        link = self._link
        if link is None:
            return
        keep = {s.get("id") for s in self._os_shockers}
        if link.kind == pishock_serial.OPENSHOCK:
            with self._lock:
                gone = [sid for sid in self._shockers if sid not in keep]
                for sid in gone:
                    st = self._shockers[sid]
                    st.hold_op = st.sent_op = None
            for sid in gone:
                link.end(sid)
        link.set_openshock_shockers(self._os_shockers)

    def set_limits(self, max_intensity, max_pulse_ms, cooldown_s,
                   max_hold_s, hold_rest_s, max_vibrate=None) -> None:
        """User caps, clamped to the absolute ceilings so a hand-edited
        settings file can't widen them. Without `max_vibrate`, vibrates
        share the shock cap."""
        self._max_intensity = _clamp_int(max_intensity, *RANGES["max_intensity"])
        self._max_vibrate = (self._max_intensity if max_vibrate is None
                             else _clamp_int(max_vibrate, *RANGES["max_vibrate"]))
        self._max_pulse_ms = _clamp_int(max_pulse_ms, *RANGES["max_pulse_ms"])
        self._cooldown_s = _clamp_float(cooldown_s, *RANGES["cooldown_s"])
        self._max_hold_s = _clamp_float(max_hold_s, *RANGES["max_hold_s"])
        self._hold_rest_s = _clamp_float(hold_rest_s, *RANGES["hold_rest_s"])

    def set_shocker_limits(self, per_shocker: Dict[Any, Dict[str, Any]]) -> None:
        """Each shocker's own caps, by id ({"24325": {"max_intensity": 20}});
        what one leaves out, it takes from the hub-wide caps. Clamped to the
        absolute ceilings like those, so a hand-edited file can't widen them."""
        own_by_id: Dict[int, Dict[str, int]] = {}
        for key, own in (per_shocker or {}).items():
            try:
                sid = int(key)
            except (TypeError, ValueError):
                continue
            own = own if isinstance(own, dict) else {}
            cleaned = {name: _clamp_int(own[name], *RANGES[name])
                       for name in ("max_intensity", "max_vibrate", "max_pulse_ms")
                       if name in own}
            if cleaned:
                own_by_id[sid] = cleaned
        self._shocker_own = own_by_id

    def set_armed(self, armed: bool) -> None:
        # Under the lock: a pulse being decided right now either goes out
        # before this (and the end_all below stops it) or sees the change.
        with self._lock:
            self._armed = bool(armed)
            if not self._armed:
                # A shock chunk already on the wire keeps running for its
                # duration; disarming must stop it now.
                self.end_all()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
            if self._paused:
                self.end_all()

    # ---- connection lifecycle (cold path) ----------------------------
    def start(self, want_connected: bool) -> None:
        """Start the supervisor that keeps the link up while it is wanted
        (auto-connect, or after the user pressed Connect)."""
        self._want_connected = bool(want_connected)
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._stop = threading.Event()
        self._supervisor = threading.Thread(
            target=self._supervise, args=(self._stop,), daemon=True,
            name="PiShockSupervisor")
        self._supervisor.start()

    def stop(self) -> None:
        self._stop.set()
        self._want_connected = False
        self.end_all()
        self._drop_link()

    def connect(self) -> None:
        """Ask for the link. Returns at once; the supervisor connects on its
        own thread (the info handshake can take seconds)."""
        self._want_connected = True
        self._last_error = None
        if self._supervisor is None or not self._supervisor.is_alive():
            self.start(True)
        else:
            threading.Thread(target=self._try_connect, daemon=True,
                             name="PiShockConnect").start()

    def disconnect(self) -> None:
        self._want_connected = False
        self.end_all()
        self._drop_link()
        self._notify()

    def _supervise(self, stop: threading.Event) -> None:
        while not stop.is_set():
            if self._want_connected and not self.is_connected:
                self._try_connect()
            stop.wait(_RECONNECT_EVERY_S)

    def _try_connect(self) -> None:
        if not self._connect_lock.acquire(blocking=False):
            return  # an attempt is already running
        try:
            if self.is_connected or not self._want_connected:
                return
            if not self.is_available:
                self._last_error = "pyserial is not installed"
                return
            self._connecting = True
            self._notify()
            ports = ([self._port_setting] if self._port_setting
                     else pishock_serial.hub_candidates())
            if not ports:
                self._last_error = "no hub found on USB"
                return
            errors = []
            for port in ports:
                link = self._link_factory(on_info=self._on_info,
                                          on_lost=self._on_lost,
                                          on_error=self._on_hub_error)
                link.set_openshock_shockers(self._os_shockers)
                try:
                    info = link.open(port)
                except Exception as e:
                    errors.append(f"{port}: {e}")
                    continue
                if not self._want_connected or self._stop.is_set():
                    link.close()  # disconnect/stop raced the handshake
                    return
                with self._lock:
                    self._link = link
                    self._info = info
                    self._shockers = {s["id"]: _Shocker() for s in info["shockers"]}
                self._last_error = None
                ids = ", ".join(str(s["id"]) for s in info["shockers"]) or "none"
                name = pishock_serial.HUB_NAMES.get(link.kind, "Shocker")
                self._log(f"{name} hub connected on {port} "
                          f"(firmware {info.get('version') or '?'}, shockers {ids})")
                return
            self._last_error = "; ".join(errors)
        finally:
            self._connecting = False
            self._connect_lock.release()
            self._notify()

    def _drop_link(self) -> None:
        with self._lock:
            link, self._link = self._link, None
        if link is not None:
            link.close()

    def _on_info(self, info: Dict[str, Any]) -> None:
        with self._lock:
            self._info = dict(info)
            listed = {s["id"] for s in info.get("shockers", [])}
            for sid in list(self._shockers):
                if sid not in listed:
                    del self._shockers[sid]
            for sid in listed:
                self._shockers.setdefault(sid, _Shocker())
        self._notify()

    def _on_hub_error(self, message: str) -> None:
        now = self._clock()
        if now - self._hub_error_logged_at < _HUB_ERROR_LOG_EVERY_S:
            return
        self._hub_error_logged_at = now
        hint = (" - is the hub's E-Stop pressed?"
                if "failed to send" in message.lower() else "")
        self._log(f"Shocker hub refused a command ({message}){hint}")

    def _on_lost(self, reason: str) -> None:
        now = self._clock()
        with self._lock:
            self._link = None
            for st in self._shockers.values():
                st.sent_op = None
                st.hold_op = None
                st.pulse_until = min(st.pulse_until, now)
        self._last_error = f"hub disconnected ({reason})"
        self._log(f"Shocker {self._last_error}")
        self._notify()

    def _notify(self) -> None:
        try:
            self._state_callback()
        except Exception:
            pass

    # ---- hot path ----------------------------------------------------
    def _effective_op(self, op: str) -> str:
        return OP_VIBRATE if op == OP_SHOCK and not self._armed else op

    def _cap(self, op: str, shocker_id: int) -> int:
        """The ceiling for an op that is about to go out on this shocker
        (after unarmed shocks became vibrates)."""
        shock, vib, _ms = self._caps_of(shocker_id)
        return shock if op == OP_SHOCK else vib

    # Every send below is decided AND written under the lock, so the wire
    # sees things in the order they were decided: a Stop, an Off or a
    # disarm that lands while a pulse is being decided either comes first
    # (and the pulse sees it) or comes after it (and ends it). The write
    # itself doesn't block (the link times out after 0.1 s at worst).
    def pulse(self, shocker_id: int, op: str, intensity: int,
              duration_ms: int) -> bool:
        """One discrete operation. Returns True when it went out, False when
        a rule dropped it (not connected, paused, cooldown). A hold's
        forced rest doesn't stop a pulse: it only limits continuous time."""
        if op not in VALID_OPS:
            return False
        now = self._clock()
        with self._lock:
            link = self._link
            if link is None or self._paused:
                return False
            op = self._effective_op(op)
            intensity = _clamp_int(intensity, 1, self._cap(op, shocker_id), 1)
            duration_ms = _clamp_int(duration_ms, 1, self._caps_of(shocker_id)[2], 300)
            st = self._shockers.get(shocker_id)
            if st is None:
                return False
            running = now < st.pulse_until
            upgrade = running and intensity > st.pulse_intensity
            if not upgrade and now < st.pulse_until + self._cooldown_s:
                return False
            st.pulse_until = now + duration_ms / 1000.0
            st.pulse_intensity = intensity
            st.pulse_op = op
            # The pulse took the shocker over; a live hold re-sends once it
            # ends instead of cutting it short.
            st.sent_op = None
            st.sent_at = _NEG_INF
            return link.operate(shocker_id, op, intensity, duration_ms)

    def hold(self, shocker_id: int, op: str, intensity: int) -> None:
        """Keep `shocker_id` running at `intensity` until release(). Call it
        every router tick while the input holds; it only writes when the
        strength changes or the running chunk needs topping up."""
        if intensity <= 0 or op not in VALID_OPS:
            self.release(shocker_id)
            return
        now = self._clock()
        with self._lock:
            link = self._link
            if link is None or self._paused:
                return
            op = self._effective_op(op)
            intensity = _clamp_int(intensity, 1, self._cap(op, shocker_id), 1)
            st = self._shockers.get(shocker_id)
            if st is None or now < st.rest_until:
                return
            # A let-go shorter than the rest doesn't restart the clock: an
            # input flickering around its threshold still gets the forced
            # break.
            if st.hold_op is None and now - st.released_at >= self._hold_rest_s:
                st.hold_started = now
            if now - st.hold_started >= self._max_hold_s:
                # Forced break: the shocker rests, then a still-held input
                # starts a fresh hold.
                was_sent = st.sent_op is not None
                st.hold_op = None
                st.sent_op = None
                st.rest_until = now + self._hold_rest_s
                st.released_at = _NEG_INF
                if was_sent and now >= st.pulse_until:
                    link.end(shocker_id)
                return
            st.hold_op, st.hold_intensity = op, intensity
            if now < st.pulse_until:
                return  # a pulse owns the shocker right now
            changed = (op != st.sent_op or intensity != st.sent_intensity)
            since = now - st.sent_at
            if since < HOLD_REFRESH_S and not (changed and since >= HOLD_CHANGE_GAP_S):
                return
            st.sent_op, st.sent_intensity, st.sent_at = op, intensity, now
            link.operate(shocker_id, op, intensity, HOLD_CHUNK_MS)

    def release(self, shocker_id: int) -> None:
        """The input let go. Cheap no-op when nothing was held."""
        with self._lock:
            st = self._shockers.get(shocker_id)
            if st is None or (st.hold_op is None and st.sent_op is None):
                return
            now = self._clock()
            was_sent = st.sent_op is not None
            st.hold_op = None
            st.sent_op = None
            st.released_at = now
            link = self._link
            if was_sent and now >= st.pulse_until and link is not None:
                link.end(shocker_id)

    def end(self, shocker_id: int) -> None:
        """Stop one shocker now -- a hold and a running pulse alike (a
        friend's Stop). Its cooldown still applies, as with end_all."""
        now = self._clock()
        with self._lock:
            st = self._shockers.get(shocker_id)
            if st is None:
                return
            st.hold_op = None
            st.sent_op = None
            st.released_at = now
            st.pulse_until = min(st.pulse_until, now)
            link = self._link
            if link is not None:
                link.end(shocker_id)

    def end_all(self) -> None:
        """Stop every shocker now (Stop, Off, disarm, shutdown). A cut-short
        pulse still counts as ended now, so its cooldown still applies."""
        now = self._clock()
        with self._lock:
            for st in self._shockers.values():
                st.hold_op = None
                st.sent_op = None
                st.released_at = now
                st.pulse_until = min(st.pulse_until, now)
            link = self._link
            if link is not None:
                for sid in list(self._shockers):
                    link.end(sid)
