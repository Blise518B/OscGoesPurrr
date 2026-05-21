# steamvr_router.py
# Watches the global parameter_store and dispatches OSC values to the
# SteamVR haptic engine based on each tracker's configured address list.
#
# Mirrors the Buttplug-side MotorRouter pattern: stateless evaluator
# polled on a timer, debounced so we only push when the value changes.

from typing import Callable, Dict, Optional

from parameter_store import store
from polling import PollingThread
from steamvr_engine import SteamVREngine, TrackerConfig
from utilities import strip_param_prefix


class SteamVRRouter(PollingThread):
    def __init__(self,
                 engine: SteamVREngine,
                 get_all_configs: Callable[[], Dict[str, TrackerConfig]],
                 poll_rate_s: float = 0.033):
        super().__init__("SteamVRRouter")
        self.engine = engine
        self.get_all_configs = get_all_configs
        self.poll_rate_s = poll_rate_s
        self._last_sent: Dict[str, float] = {}

    def _run(self):
        print("[SteamVR] Router thread started")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f"[SteamVR][Router] tick error: {e}")
            self._interruptible_sleep(self.poll_rate_s)

    def _tick(self):
        params = store.get_all_parameters()
        if not params:
            return
        configs = self.get_all_configs()
        if not configs:
            return

        for serial, cfg in configs.items():
            if not cfg.enabled:
                continue
            best = 0.0
            for addr in cfg.address_list:
                if not addr or addr.strip() in ("", "..."):
                    continue
                # Stored form is the bare parameter name (UI strips any
                # /avatar/parameters/ the user pastes), but stay defensive
                # in case a stale config or upgrade path slips a prefix
                # through — parameter_store keys are always the short form.
                lookup = strip_param_prefix(addr)
                if lookup in params:
                    try:
                        v = float(params[lookup])
                    except (TypeError, ValueError):
                        continue
                    if v > best:
                        best = v
            # Debounce: only push when the value actually changes
            if self._last_sent.get(serial) != best:
                self._last_sent[serial] = best
                self.engine.set_strength(serial, best)


class SteamVRBatteryBroadcaster(PollingThread):
    """Periodically polls the SteamVR engine for each device's battery level
    and pushes the value to its configured outgoing OSC address. Sends are
    debounced so the same value doesn't go out twice in a row."""

    def __init__(self,
                 engine: SteamVREngine,
                 get_all_configs: Callable[[], Dict[str, TrackerConfig]],
                 send_osc: Callable[[str, float], None],
                 poll_interval_s: float = 5.0,
                 get_auto_connect: Optional[Callable[[], bool]] = None):
        super().__init__("SteamVRBatteryBroadcaster")
        self.engine = engine
        self.get_all_configs = get_all_configs
        self.send_osc = send_osc
        self.poll_interval_s = poll_interval_s
        # When True, try to (re)connect to SteamVR each tick if not alive.
        self.get_auto_connect = get_auto_connect or (lambda: False)
        self._last_sent: Dict[str, float] = {}

    def set_interval(self, seconds: float):
        self.poll_interval_s = max(1.0, float(seconds))

    def _run(self):
        print("[SteamVR] Battery broadcaster started")
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                print(f"[SteamVR][Battery] tick error: {e}")
            self._interruptible_sleep(self.poll_interval_s, slice_s=0.25)

    def _tick(self):
        # Auto-(re)connect: cheap when already alive (try_init early-outs),
        # and pulls in newly-connected devices each pass.
        if self.get_auto_connect():
            try:
                self.engine.refresh_devices(quiet=True)
            except Exception:
                pass

        configs = self.get_all_configs()
        if not configs:
            return
        for dev in self.engine.snapshot_devices():
            cfg = configs.get(dev.serial)
            if cfg is None:
                continue
            addr = (cfg.battery_osc_address or "").strip()
            if not addr:
                continue
            level = self.engine.battery_for(dev.serial)
            if level is None:
                continue
            # OpenVR returns 0.0 - 1.0; clamp defensively.
            try:
                value = max(0.0, min(1.0, float(level)))
            except (TypeError, ValueError):
                continue
            if self._last_sent.get(dev.serial) == value:
                continue
            self._last_sent[dev.serial] = value
            try:
                self.send_osc(addr, value)
            except Exception as e:
                print(f"[SteamVR][Battery] send failed for {dev.serial}: {e}")
