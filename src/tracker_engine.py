# tracker_engine.py
# Sealed engine for haptic trackers: a Vive Tracker with a vibration motor
# on its pogo pins (a Haptic Pancake), a Tundra tracker with a Tundra
# Tapper board, a controller set up as a tracker. It joins a running
# SteamVR through OpenVR as a background app -- it never starts SteamVR,
# and a PC without SteamVR just finds nothing.
#
# Every OpenVR call happens on the engine's one thread: attaching, the
# device list (every SCAN_S), SteamVR's Quit, and the pulses. A pulse is
# OpenVR's TriggerHapticPulse, sent again every period while a tracker's
# level is above zero; how long each pulse is carries the strength. The
# timings are what works on each kind (documented by the Haptic Pancake
# and Tundra Tapper projects; written here from those numbers, not their
# code -- that code is GPL):
#   * Vive Tracker: a pulse every 50 ms, value 50 at full.
#   * Tundra: microseconds, under 4 ms a pulse -> a pulse every 4 ms.
#   * Controllers: microseconds as well, every 50 ms, near 4 ms at full.
#
# This is the last gate before a motor: a level the router stops sending
# for LEVEL_TTL_S plays nothing (if the router dies, the trackers stop),
# each tracker's cap (default DEFAULT_CAP %: a plain motor on a Vive
# Tracker's pin shouldn't run at full for long) holds whatever is asked,
# and paused refuses everything.
#
# Latency: set_levels() only stores the newest value and wakes the thread
# when it rises, so a new touch pulses at once instead of at the next
# period; nothing waits on a device.

import importlib.util
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import tracker_spots

# OpenVR's binding (and its DLL) loads only when the engine starts -- the
# app runs without it, and someone who never switches trackers on never
# pays for it.
_openvr = None


def _load_openvr():
    global _openvr
    if _openvr is None:
        try:
            import openvr  # type: ignore
            _openvr = openvr
        except Exception:  # noqa: BLE001 -- trackers are just never found
            return None
    return _openvr


def _openvr_installed() -> bool:
    try:
        return importlib.util.find_spec("openvr") is not None
    except (ImportError, ValueError):
        return False

SCAN_S = 2.0            # device list, battery and roles while SteamVR runs
ATTACH_RETRY_S = 3.0    # how often to look for SteamVR while it isn't there
LEVEL_TTL_S = 0.25      # a level nobody sends again plays nothing after this
IDENTIFY_S = 0.6        # the page's Buzz / Feel it
MIN_GAP_S = 0.004       # two pulses on one tracker never closer than this
DEFAULT_CAP = 80        # % of a full pulse; the page can raise it to 100
_FAILS_TO_DETACH = 3    # device-list reads in a row that fail: SteamVR is gone
_PULSE_FAILS_TO_DETACH = 50

# Virtual trackers that only carry a pose (Standable, the SlimeVR-style
# ones some people use) -- never haptic, and they crowd the list.
_VIRTUAL_MARKERS = ("stndbl", "standable", "stbl_")
_OWN_SYSTEM = "oscgoespurrr"   # OGP's own toy devices in SteamVR's strip


@dataclass(frozen=True)
class Timing:
    kind: str           # "vive", "tundra", "controller"
    period_s: float     # one pulse this often while a level plays
    full: int           # the pulse value a level of 1.0 sends


VIVE = Timing("vive", 0.050, 50)
TUNDRA = Timing("tundra", 0.004, 3999)
CONTROLLER = Timing("controller", 0.050, 3999)


def timing_for(model: str) -> Timing:
    m = str(model or "").lower()
    if m.startswith("tundra"):
        return TUNDRA
    if "controller" in m or "knuckles" in m:
        return CONTROLLER
    return VIVE


def pulse_value(timing: Timing, level: float, cap_pct: int) -> int:
    """0..1 -> the pulse value, under the tracker's cap; 0 = no pulse."""
    try:
        level = float(level)
        cap = max(0, min(100, int(cap_pct))) / 100.0
    except (TypeError, ValueError):
        return 0
    if not level > 0:                     # also NaN
        return 0
    return max(0, int(round(min(level, 1.0, cap) * timing.full)))


def is_virtual(serial: str, model: str) -> bool:
    s, m = str(serial or "").lower(), str(model or "").lower()
    return any(mark in s or mark in m for mark in _VIRTUAL_MARKERS)


@dataclass
class _Device:
    index: int
    serial: str
    model: str
    timing: Timing
    battery: Optional[int] = None
    role: str = ""
    next_due: float = 0.0       # 0 = not pulsing
    last_pulse: float = -1.0
    last_value: int = 0


def _read_steamvr_settings(cache: Dict[str, Any]) -> Dict[str, str]:
    """SteamVR's saved roles, re-read only when the file changes."""
    for path in tracker_spots.steamvr_settings_paths():
        try:
            stamp = (path, os.path.getmtime(path))
        except OSError:
            continue
        if cache.get("stamp") != stamp:
            try:
                with open(path, encoding="utf-8") as f:
                    cache["roles"] = tracker_spots.roles_from_settings(f.read())
            except OSError:
                cache["roles"] = {}
            cache["stamp"] = stamp
        return cache.get("roles") or {}
    return {}


class TrackerEngine:
    """Haptic trackers through SteamVR. Thread-safe; primitives only."""

    def __init__(self, log: Callable[[str], None] = print, vr_module: Any = None,
                 clock: Callable[[], float] = time.monotonic,
                 read_roles: Optional[Callable[[Dict[str, Any]], Dict[str, str]]] = None):
        self._log = log
        self._vr_mod = vr_module            # None until start() loads OpenVR
        self._installed = vr_module is not None or _openvr_installed()
        self._clock = clock
        self._read_roles = read_roles or _read_steamvr_settings
        self._roles_cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state_cb: Optional[Callable[[], None]] = None
        # shared (under _lock)
        self._levels: Dict[str, Tuple[float, float]] = {}   # serial -> (level, when)
        self._caps: Dict[str, int] = {}
        self._identify: Dict[str, float] = {}               # serial -> until
        self._paused = False
        # engine thread only
        self._devices: Dict[str, _Device] = {}
        # read by anyone (swapped whole)
        self._public: List[Dict[str, Any]] = []
        self._alive = False
        self._playing: Dict[str, float] = {}
        self._pulse_fails = 0

    # ---- controller-facing --------------------------------------------
    @property
    def is_available(self) -> bool:
        """The OpenVR binding is there (it can't attach without it)."""
        return self._installed

    @property
    def is_alive(self) -> bool:
        """Attached to a running SteamVR."""
        return self._alive

    def set_state_callback(self, cb: Optional[Callable[[], None]]) -> None:
        self._state_cb = cb

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self._vr_mod is None:
            self._vr_mod = _load_openvr()
        if self._vr_mod is None:
            self._installed = False
            self._log("Trackers: the OpenVR library didn't load — no tracker haptics.")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="TrackerEngine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        t, self._thread = self._thread, None
        if t is not None and t is not threading.current_thread():
            t.join(timeout=1.5)
        with self._lock:
            self._levels.clear()
            self._identify.clear()

    def set_levels(self, levels: Mapping[str, float]) -> None:
        """The router, every tick: each placed tracker's 0..1 level. A
        level that rises wakes the thread so it pulses now."""
        now = self._clock()
        rose = False
        with self._lock:
            for serial, v in levels.items():
                try:
                    v = max(0.0, min(1.0, float(v)))
                except (TypeError, ValueError):
                    v = 0.0
                if v != v:                       # NaN
                    v = 0.0
                old = self._levels.get(serial)
                if v > 0 and (old is None or v > old[0] + 1e-3 or now - old[1] > LEVEL_TTL_S):
                    rose = True
                self._levels[serial] = (v, now)
        if rose:
            self._wake.set()

    def set_caps(self, caps: Mapping[str, int]) -> None:
        """Each tracker's top, % of a full pulse (DEFAULT_CAP when absent)."""
        clean = {}
        for serial, c in caps.items():
            try:
                clean[str(serial)] = max(0, min(100, int(c)))
            except (TypeError, ValueError):
                continue
        with self._lock:
            self._caps = clean

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = bool(paused)
            if paused:
                self._identify.clear()
        self._wake.set()

    def identify(self, serial: str) -> bool:
        """A short buzz on one tracker (under its cap), to find it or feel
        it. False when paused or it isn't there."""
        with self._lock:
            if self._paused or not any(d["serial"] == serial for d in self._public):
                return False
            self._identify[serial] = self._clock() + IDENTIFY_S
        self._wake.set()
        return True

    def status_snapshot(self) -> Dict[str, Any]:
        return {"available": self.is_available, "alive": self._alive,
                "paused": self._paused, "devices": [dict(d) for d in self._public]}

    def output_snapshot(self) -> Dict[str, float]:
        """What each tracker plays right now, 0..1 (after its cap)."""
        return dict(self._playing)

    # ---- engine thread --------------------------------------------------
    def _notify(self) -> None:
        cb = self._state_cb
        if cb is not None:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass

    def _run(self) -> None:
        vr = None
        next_attach = 0.0
        next_scan = 0.0
        scan_fails = 0
        try:
            while not self._stop.is_set():
                now = self._clock()
                if vr is None:
                    if now >= next_attach:
                        vr = self._attach()
                        next_attach = now + ATTACH_RETRY_S
                        next_scan, scan_fails = now, 0
                    if vr is None:
                        self._sleep(next_attach - self._clock())
                        continue
                if now >= next_scan:
                    ok = self._scan(vr)
                    scan_fails = 0 if ok else scan_fails + 1
                    if ok is None or scan_fails >= _FAILS_TO_DETACH:
                        vr = self._detach("SteamVR closed" if ok is None else "SteamVR stopped answering")
                        continue
                    next_scan = now + SCAN_S
                wait = self._pulse_all(vr, self._clock())
                if wait is None:
                    vr = self._detach("SteamVR stopped taking pulses")
                    continue
                self._sleep(min(wait, next_scan - self._clock()))
        finally:
            if vr is not None:
                self._detach(None)

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            self._wake.wait(seconds)
        self._wake.clear()

    def _attach(self):
        mod = self._vr_mod
        try:
            vr = mod.init(mod.VRApplication_Background)
        except Exception:  # noqa: BLE001 -- SteamVR not running (or not installed)
            return None
        self._alive = True
        self._log("Trackers: joined SteamVR")
        self._notify()
        return vr

    def _detach(self, why: Optional[str]):
        try:
            self._vr_mod.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self._devices = {}
        self._public, self._playing, self._alive = [], {}, False
        if why:
            self._log(f"Trackers: {why} — looking for it again")
        self._notify()
        return None

    def _scan(self, vr) -> Optional[bool]:
        """Read the device list. True = fine, False = the read failed,
        None = SteamVR asked us to quit (acknowledged, so it doesn't wait
        on us)."""
        mod = self._vr_mod
        try:
            event = mod.VREvent_t()
            quits = {getattr(mod, n, None) for n in
                     ("VREvent_Quit", "VREvent_ProcessQuit", "VREvent_DriverRequestedQuit")}
            quits.discard(None)
            while vr.pollNextEvent(event):
                if event.eventType in quits:
                    try:
                        vr.acknowledgeQuit_Exiting()
                    except Exception:  # noqa: BLE001
                        pass
                    return None
        except Exception:  # noqa: BLE001
            pass
        roles = self._read_roles(self._roles_cache)
        found: Dict[str, _Device] = {}
        try:
            for i in range(mod.k_unMaxTrackedDeviceCount):
                if vr.getTrackedDeviceClass(i) != mod.TrackedDeviceClass_GenericTracker:
                    continue
                if not vr.isTrackedDeviceConnected(i):
                    continue
                serial = self._prop_str(vr, i, mod.Prop_SerialNumber_String)
                if not serial:
                    continue
                model = self._prop_str(vr, i, mod.Prop_ModelNumber_String)
                system = self._prop_str(vr, i, mod.Prop_TrackingSystemName_String).lower()
                if system == _OWN_SYSTEM or is_virtual(serial, model):
                    continue
                battery = None
                try:
                    b = float(vr.getFloatTrackedDeviceProperty(i, mod.Prop_DeviceBatteryPercentage_Float))
                    if 0.0 <= b <= 1.0:
                        battery = int(round(b * 100))
                except Exception:  # noqa: BLE001 -- some trackers report none
                    pass
                dev = self._devices.get(serial) or _Device(i, serial, model, timing_for(model))
                dev.index, dev.model, dev.timing = i, model, timing_for(model)
                dev.battery, dev.role = battery, tracker_spots.role_of(serial, roles)
                found[serial] = dev
        except Exception:  # noqa: BLE001
            return False
        self._devices = found
        public = [{"serial": d.serial, "model": d.model or "Tracker", "kind": d.timing.kind,
                   "battery": d.battery, "role": d.role,
                   "role_spot": tracker_spots.spot_for_role(d.role)}
                  for d in sorted(found.values(), key=lambda d: d.serial)]
        if public != self._public:
            added = {d["serial"] for d in public} - {d["serial"] for d in self._public}
            self._public = public
            for d in public:
                if d["serial"] in added:
                    self._log(f"Trackers: found {d['model']} {d['serial']}")
            self._notify()
        return True

    @staticmethod
    def _prop_str(vr, index: int, prop) -> str:
        try:
            return str(vr.getStringTrackedDeviceProperty(index, prop) or "")
        except Exception:  # noqa: BLE001
            return ""

    def _pulse_all(self, vr, now: float) -> Optional[float]:
        """Send every pulse that's due; seconds until the next one (SCAN_S
        when nothing plays), or None when SteamVR keeps refusing them."""
        with self._lock:
            paused = self._paused
            levels = dict(self._levels)
            caps = dict(self._caps)
            for serial in [s for s, until in self._identify.items() if until <= now]:
                del self._identify[serial]
            identify = dict(self._identify)
        wait = SCAN_S
        playing: Dict[str, float] = {}
        for serial, dev in self._devices.items():
            level = 0.0
            if not paused:
                got = levels.get(serial)
                if got is not None and now - got[1] <= LEVEL_TTL_S:
                    level = got[0]
                if serial in identify:
                    level = 1.0
            cap = caps.get(serial, DEFAULT_CAP)
            value = pulse_value(dev.timing, level, cap)
            if value <= 0:
                dev.next_due, dev.last_value = 0.0, 0
                continue
            playing[serial] = min(level, cap / 100.0)
            due = dev.next_due == 0.0 or now >= dev.next_due or value > dev.last_value
            if due and now - dev.last_pulse >= MIN_GAP_S:
                try:
                    vr.triggerHapticPulse(dev.index, 0, value)
                    self._pulse_fails = 0
                except Exception:  # noqa: BLE001
                    self._pulse_fails += 1
                    if self._pulse_fails >= _PULSE_FAILS_TO_DETACH:
                        return None
                period = dev.timing.period_s
                keep = dev.next_due and 0.0 <= now - dev.next_due < period
                dev.next_due = (dev.next_due + period) if keep else now + period
                dev.last_pulse, dev.last_value = now, value
            elif due:
                dev.next_due = dev.last_pulse + MIN_GAP_S
            wait = min(wait, max(0.0005, dev.next_due - now))
        self._playing = playing
        return wait
