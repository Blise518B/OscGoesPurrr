# steamvr_engine.py
# Sealed black box that owns the OpenVR connection and per-tracker
# vibration loops. Outside callers go through the facade methods only —
# never reach through `engine.vr` or `engine.threads`.
#
# Patterns / FeedbackThread adapted from VRC-Haptic-Pancake (GPL3).

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# Lazy import: app should still launch if openvr/SteamVR aren't installed.
try:
    import openvr  # type: ignore
    _OPENVR_AVAILABLE = True
except Exception:
    openvr = None  # type: ignore
    _OPENVR_AVAILABLE = False

from steamvr_manifest import SteamVRManifest


VIB_PATTERN_LIST = ["None", "Constant", "Linear", "Sine", "Throb"]

PATTERN_PROXIMITY = 0
PATTERN_VELOCITY = 1


@dataclass
class PatternConfig:
    pattern: str = "Linear"
    str_min: int = 0
    str_max: int = 80
    speed: int = 4

    def to_dict(self) -> dict:
        return {"pattern": self.pattern, "str_min": int(self.str_min),
                "str_max": int(self.str_max), "speed": int(self.speed)}

    @classmethod
    def from_dict(cls, d: dict) -> "PatternConfig":
        return cls(
            pattern=str(d.get("pattern", "Linear")),
            str_min=int(d.get("str_min", 0)),
            str_max=int(d.get("str_max", 80)),
            speed=int(d.get("speed", 4)),
        )


@dataclass
class TrackerConfig:
    enabled: bool = True
    address_list: List[str] = field(default_factory=lambda: ["..."])
    multiplier_override: float = 1.0
    battery_threshold: int = 20
    battery_osc_address: str = ""  # outgoing — empty disables battery broadcast

    def to_dict(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "address_list": list(self.address_list),
            "multiplier_override": float(self.multiplier_override),
            "battery_threshold": int(self.battery_threshold),
            "battery_osc_address": str(self.battery_osc_address or ""),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TrackerConfig":
        addrs = d.get("address_list") or []
        if not addrs and d.get("address"):
            addrs = str(d["address"]).split(";")
        if not addrs:
            addrs = ["..."]
        return cls(
            enabled=bool(d.get("enabled", True)),
            address_list=list(addrs),
            multiplier_override=float(d.get("multiplier_override", 1.0)),
            battery_threshold=int(d.get("battery_threshold", 20)),
            battery_osc_address=str(d.get("battery_osc_address", "") or ""),
        )


DEVICE_CLASS_HMD = "hmd"
DEVICE_CLASS_CONTROLLER = "controller"
DEVICE_CLASS_TRACKER = "tracker"
DEVICE_CLASS_OTHER = "other"


# Standable virtual-tracker serials and models — filtered from discovery.
# Their model strings typically contain "STNDBL" / "Standable"; serials use
# the STBL_ prefix. Match case-insensitively across both fields.
_STANDABLE_MARKERS = ("stndbl", "standable", "stbl_")


def _is_standable(serial: str, model: str) -> bool:
    s = (serial or "").lower()
    m = (model or "").lower()
    return any(mark in s or mark in m for mark in _STANDABLE_MARKERS)


@dataclass
class VRTracker:
    index: int
    model: str
    serial: str
    device_class: str = DEVICE_CLASS_TRACKER

    @property
    def supports_haptics(self) -> bool:
        # HMDs cannot pulse; trackers and controllers can.
        return self.device_class in (DEVICE_CLASS_TRACKER, DEVICE_CLASS_CONTROLLER)

    @property
    def pulse_multiplier(self) -> float:
        if self.model.startswith("VIVE Controller"):
            return 100.0
        return 1.0


# --- Pattern math --------------------------------------------------------

class _VibrationPattern:
    def __init__(self, patterns: List[PatternConfig]):
        self.patterns = patterns

    def apply(self, value: float, delta: float) -> float:
        prox = self.patterns[PATTERN_PROXIMITY]
        vel = self.patterns[PATTERN_VELOCITY]
        p_idx = VIB_PATTERN_LIST.index(prox.pattern) if prox.pattern in VIB_PATTERN_LIST else 0
        v_idx = VIB_PATTERN_LIST.index(vel.pattern) if vel.pattern in VIB_PATTERN_LIST else 0
        p_out = self._apply_one(p_idx, value, prox.speed)
        v_out = self._apply_one(v_idx, delta, vel.speed)
        p_out = self._map(p_out, prox.str_min / 100.0, prox.str_max / 100.0)
        v_out = self._map(v_out, vel.str_min / 100.0, vel.str_max / 100.0)
        return max(p_out, v_out)

    @staticmethod
    def _apply_one(idx: int, value: float, speed: int) -> float:
        if idx == 0:  # None
            return 0.0
        if idx == 1:  # Constant
            return 1.0 if value > 0 else 0.0
        if idx == 2:  # Linear
            return value
        if idx == 3:  # Sine
            return -(math.cos(math.pi * value) - 1) / 2.0
        if idx == 4:  # Throb
            t = (time.time() * max(speed, 1)) % 2
            saw = t if t <= 1 else (2 - t)
            return saw * value
        return 0.0

    @staticmethod
    def _map(value: float, lo: float, hi: float) -> float:
        if value == 0:
            return 0.0
        return lo + value * (hi - lo)


# --- Per-tracker vibration loop -----------------------------------------

class _FeedbackThread(threading.Thread):
    LOW_BATTERY_ALERT_COUNT = 8

    def __init__(self, tracker: VRTracker, engine: "SteamVREngine"):
        super().__init__(daemon=True)
        self.tracker = tracker
        self.engine = engine
        self._stop = threading.Event()

        self.strength = 0.0
        self.strength_delta = 0.0
        self.last_set_time = time.time()
        self.battery_low_notif = self.LOW_BATTERY_ALERT_COUNT

        # Pulse timing — Tundra needs microsecond units + 4ms ceiling
        self.interval_ms = 50.0
        self.hack_pulse_mult_to_ms = 0
        self.hack_pulse_limit_ms = 0
        self.hack_pulse_limit_exceeded = False
        self.hack_pulse_force_stop_time = 0.0
        if self.tracker.model.startswith("Tundra"):
            self.hack_pulse_mult_to_ms = 1 / 1000
            self.hack_pulse_limit_ms = 4000 * self.hack_pulse_mult_to_ms
            self.interval_ms = self.hack_pulse_limit_ms
        self.interval_s = self.interval_ms / 1000.0

    def stop(self):
        self._stop.set()

    def set_strength(self, value: float):
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = 0.0
        value = max(value, 0.0)
        self.strength_delta += abs(value - self.strength)
        self.strength = value
        self.last_set_time = time.time()

    def force_pulse(self, length_ms: float):
        if self.hack_pulse_limit_ms > 0:
            self.hack_pulse_force_stop_time = time.time() + (length_ms / 1000.0)
        else:
            length = length_ms
            if self.hack_pulse_mult_to_ms:
                length = length / self.hack_pulse_mult_to_ms
            self.engine._raw_pulse(self.tracker.index, int(length * self.tracker.pulse_multiplier))

    def _clear_stuck(self):
        # Two-timer anti-stuck (VRC-Haptic-Pancake parity): saturated values
        # (==1.0) usually represent a legitimate hold and get a longer fuse;
        # mid-range stuck values are almost always avatar swaps / dropped
        # packets and are cleared sooner. VRChat OSC only fires on parameter
        # change, so without this the last value would vibrate forever.
        cfg = self.engine.no_data_config
        if self.strength == 0 or not cfg["enabled"]:
            return
        # Defensive lookups so older config dicts (single timeout_s key)
        # still work after a downgrade.
        peaked_delay = cfg.get("timeout_peaked_s", cfg.get("timeout_s", 15))
        active_delay = cfg.get("timeout_active_s", max(1, int(peaked_delay * 7 / 15)))
        elapsed = time.time() - self.last_set_time
        delay = peaked_delay if self.strength >= 1.0 else active_delay
        if elapsed >= delay:
            self.set_strength(0)

    def _calc_strength(self) -> float:
        cfg = self.engine.get_tracker_config(self.tracker.serial)
        if self.engine._battery_level(self.tracker.index) < (cfg.battery_threshold / 100.0):
            if self.battery_low_notif > 0:
                self.battery_low_notif -= 1
                # Low-battery alert: buzz the tracker N times at progressively
                # weaker intensities to get the user's attention without locking
                # the motor at full strength. `int % 0.9` produces 8→0.8,
                # 7→0.7, ..., 1→0.1 — a stepped fade-out, not arithmetic.
                return self.battery_low_notif % 0.9
            return 0.0
        self.battery_low_notif = self.LOW_BATTERY_ALERT_COUNT

        patterns = self.engine.get_pattern_configs()
        patterned = _VibrationPattern(patterns).apply(self.strength, self.strength_delta)
        self.strength_delta -= patterned
        if self.strength_delta < 0:
            self.strength_delta = 0.0
        if patterned <= 0:
            return 0.0
        return patterned * self.tracker.pulse_multiplier * cfg.multiplier_override

    def run(self):
        print(f"[SteamVR] Vibration thread started for {self.tracker.serial} ({self.tracker.model})")
        while not self._stop.is_set():
            start = time.time()
            self._clear_stuck()
            pulse_length = 0.0

            strength = self._calc_strength()
            if strength > 0:
                pulse_length = strength * self.interval_ms

            if start < self.hack_pulse_force_stop_time:
                forced = (self.hack_pulse_force_stop_time - start) * 1000
                pulse_length = max(pulse_length, forced)

            if self.hack_pulse_limit_ms > 0 and pulse_length > self.hack_pulse_limit_ms:
                if not self.hack_pulse_limit_exceeded:
                    print(f"[SteamVR] {self.tracker.serial} pulse exceeds {self.interval_ms}ms limit, extending")
                    self.hack_pulse_limit_exceeded = True
                self.force_pulse(pulse_length)
                pulse_length = self.hack_pulse_limit_ms

            if self.hack_pulse_mult_to_ms:
                pulse_length = pulse_length / self.hack_pulse_mult_to_ms

            pulse_length = int(pulse_length)
            if pulse_length > 0:
                self.engine._raw_pulse(self.tracker.index, pulse_length)

            sleep = max(self.interval_s - (time.time() - start), 0.0)
            time.sleep(sleep)


# --- Engine facade ------------------------------------------------------

class SteamVREngine:
    """Owns OpenVR + per-tracker threads. Threadsafe facade."""

    def __init__(self,
                 get_tracker_config: Callable[[str], TrackerConfig],
                 get_pattern_configs: Callable[[], List[PatternConfig]],
                 get_no_data_config: Callable[[], dict]):
        self._lock = threading.Lock()
        self._vr = None
        self._vr_apps = None
        self._threads: Dict[str, _FeedbackThread] = {}
        self._devices: List[VRTracker] = []
        self._manifest = SteamVRManifest()

        # Config providers (called every tick — keep them cheap)
        self.get_tracker_config = get_tracker_config
        self.get_pattern_configs = get_pattern_configs
        self._get_no_data = get_no_data_config

    # ---- Properties --------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if the openvr python binding is importable."""
        return _OPENVR_AVAILABLE

    @property
    def is_alive(self) -> bool:
        return self._vr is not None

    @property
    def is_app_bundled(self) -> bool:
        return self._manifest.is_app_bundled

    @property
    def no_data_config(self) -> dict:
        return self._get_no_data()

    # ---- Lifecycle ---------------------------------------------------

    def try_init(self, quiet: bool = False) -> bool:
        if not _OPENVR_AVAILABLE:
            if not quiet:
                print("[SteamVR] openvr python binding not available.")
            return False
        if self._vr is not None:
            return True
        try:
            self._vr = openvr.init(openvr.VRApplication_Background)
            self._vr_apps = openvr.VRApplications()
            print("[SteamVR] Initialized OpenVR successfully.")
            return True
        except Exception as e:
            if not quiet:
                print(f"[SteamVR] Failed to initialize OpenVR: {e}")
            return False

    def shutdown(self):
        with self._lock:
            for t in self._threads.values():
                t.stop()
            self._threads.clear()
            if self._vr is not None and _OPENVR_AVAILABLE:
                try:
                    openvr.shutdown()
                except Exception:
                    pass
            self._vr = None
            self._vr_apps = None

    # ---- Discovery ---------------------------------------------------

    def refresh_devices(self, quiet: bool = False) -> List[VRTracker]:
        if not self.try_init(quiet):
            return []

        try:
            poses = self._vr.getDeviceToAbsoluteTrackingPose(
                openvr.TrackingUniverseStanding, 0, openvr.k_unMaxTrackedDeviceCount)
        except Exception as e:
            if not quiet:
                print(f"[SteamVR] Pose query failed: {e}")
            return self._devices

        devices: List[VRTracker] = []
        for i in range(openvr.k_unMaxTrackedDeviceCount):
            try:
                if not self._vr.isTrackedDeviceConnected(i):
                    continue
            except Exception:
                continue
            cls = self._vr.getTrackedDeviceClass(i)
            if cls == openvr.TrackedDeviceClass_HMD:
                dev_class = DEVICE_CLASS_HMD
            elif cls == openvr.TrackedDeviceClass_Controller:
                dev_class = DEVICE_CLASS_CONTROLLER
            elif cls == openvr.TrackedDeviceClass_GenericTracker:
                dev_class = DEVICE_CLASS_TRACKER
            else:
                # Base stations and other peripherals — skip.
                continue
            try:
                serial = self._vr.getStringTrackedDeviceProperty(i, openvr.Prop_SerialNumber_String)
            except Exception:
                continue
            if not serial:
                continue
            try:
                model = self._vr.getStringTrackedDeviceProperty(i, openvr.Prop_ModelNumber_String)
            except Exception:
                model = "Unknown"

            # Standable virtual trackers — pose-only, never haptic, drown the UI.
            if _is_standable(serial, model):
                continue

            devices.append(VRTracker(i, model, serial, dev_class))

        # Sort: HMD first, then controllers, then trackers (alphabetical inside class).
        _class_order = {DEVICE_CLASS_HMD: 0, DEVICE_CLASS_CONTROLLER: 1,
                        DEVICE_CLASS_TRACKER: 2, DEVICE_CLASS_OTHER: 3}
        devices.sort(key=lambda d: (_class_order.get(d.device_class, 9), d.serial))
        self._devices = devices

        # Spawn a haptic feedback thread for each haptic-capable device.
        with self._lock:
            for dev in devices:
                if dev.supports_haptics and dev.serial not in self._threads:
                    th = _FeedbackThread(dev, self)
                    self._threads[dev.serial] = th
                    th.start()

        return devices

    def snapshot_devices(self) -> List[VRTracker]:
        return list(self._devices)

    # ---- Vibration dispatch -----------------------------------------

    def set_strength(self, serial: str, value: float):
        th = self._threads.get(serial)
        if th is not None:
            th.set_strength(value)

    def pulse_test(self, serial: str, length_ms: float = 500):
        th = self._threads.get(serial)
        if th is not None:
            th.force_pulse(length_ms)

    def _raw_pulse(self, index: int, length: int):
        if not self.is_alive:
            return
        try:
            self._vr.triggerHapticPulse(index, 0, length)
        except Exception:
            pass

    def _battery_level(self, index: int) -> float:
        if not self.is_alive:
            return 1.0
        try:
            return self._vr.getFloatTrackedDeviceProperty(index, openvr.Prop_DeviceBatteryPercentage_Float)
        except Exception:
            return 1.0

    def battery_for(self, serial: str) -> Optional[float]:
        for d in self._devices:
            if d.serial == serial:
                return self._battery_level(d.index)
        return None

    # ---- Autostart manifest -----------------------------------------

    def is_registered(self) -> bool:
        if not self.try_init(True) or self._vr_apps is None:
            return False
        try:
            return self._vr_apps.isApplicationInstalled(self._manifest.app_key)
        except Exception:
            return False

    def setup_autostart(self, enabled: bool):
        if not self.try_init(False) or self._vr_apps is None:
            return
        if enabled:
            self._manifest.save()
            if not self.is_registered():
                try:
                    self._vr_apps.addApplicationManifest(self._manifest.manifest_path, False)
                except Exception as e:
                    print(f"[SteamVR] addApplicationManifest failed: {e}")
            try:
                self._vr_apps.setApplicationAutoLaunch(self._manifest.app_key, True)
            except Exception as e:
                print(f"[SteamVR] setApplicationAutoLaunch(True) failed: {e}")
        else:
            if self.is_registered():
                self._manifest.save()
                try:
                    self._vr_apps.setApplicationAutoLaunch(self._manifest.app_key, False)
                except Exception as e:
                    print(f"[SteamVR] setApplicationAutoLaunch(False) failed: {e}")
