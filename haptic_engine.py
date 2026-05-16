# OscGoesPurrr - Haptic Engine Module (The Muscle)
"""
HapticEngine - Async hardware interface for buttplug and OSC operations.
Isolated from UI logic to enable clean separation of concerns.

Supports both vibrating features (motors, oscillators, constrictors) and linear
actuators (Lovense Solace Pro, Gravity, OSR2, etc.). For linear actuators we run
the same velocity-limited physics model OscGoesBrrr uses in src/main/bridge.ts:
the routed 0-1 level becomes a target stroke position, and the engine smoothly
accelerates/decelerates toward it within configured maxv/maxa bounds. When the
level has been 0 for `resting_time` seconds, the actuator returns to `resting_pos`.
"""

import asyncio
import time
from typing import Dict, List, Optional, Tuple

from buttplug import ButtplugClient, DeviceOutputCommand, OutputType
from constants import APP_NAME, HAPTIC_POLL_RATE, INTIFACE_WS_URL


# Default linear-actuator config -- mirrors OscGoesBrrr getDefaultLinearActuatorConfig()
# in src/common/configTypes.ts.
LINEAR_DEFAULTS = {
    "max_v": 3.0,             # max velocity in normalized position units / second
    "max_a": 20.0,            # max acceleration in units / second^2
    "duration_mult": 1.0,     # multiplier on commanded duration vs tick delta
    "resting_pos": 0.0,       # position the actuator returns to when idle
    "resting_time_s": 3.0,    # seconds of zero level before returning to resting_pos
    "min_pos": 0.0,           # minimum stroke position (after remap)
    "max_pos": 1.0,           # maximum stroke position (after remap)
}


class LinearActuator:
    """Per-feature physics state for a linear actuator.

    Port of the linear branch in OscGoesBrrr's BridgeOutput.pushToBio
    (src/main/bridge.ts). Call `tick(level, now_ms)` once per engine cycle;
    it returns `(new_position, duration_ms)` if a new command should be sent,
    or `None` if the position didn't change.
    """

    def __init__(self, **config) -> None:
        merged = {**LINEAR_DEFAULTS, **config}
        self.max_v: float = merged["max_v"]
        self.max_a: float = merged["max_a"]
        self.duration_mult: float = merged["duration_mult"]
        self.resting_pos: float = merged["resting_pos"]
        self.resting_time_ms: float = merged["resting_time_s"] * 1000.0
        self.min_pos: float = merged["min_pos"]
        self.max_pos: float = merged["max_pos"]

        self.last_position: float = 0.0
        self.velocity: float = 0.0
        self.last_target: float = 0.0
        self.last_push_time_ms: float = 0.0
        # Initialize to -inf so the resting-return branch engages on the very
        # first tick at level=0, regardless of the caller's clock origin. (OGB
        # gets the same effect from Date.now() being a huge absolute number.)
        self.last_suck_time_ms: float = float("-inf")

    def tick(self, level: float, now_ms: float) -> Optional[Tuple[float, int]]:
        # Safety-limited tick interval (matches OGB's clamp(timeDeltaReal, 0, 250)).
        time_delta = max(0.0, min(250.0, now_ms - self.last_push_time_ms))
        time_delta_s = time_delta / 1000.0
        old_velocity = self.velocity
        max_v = self.max_v
        max_a = self.max_a

        # High level => low position ("sucked in"). Remap into the [min,max] stroke.
        clamped_level = max(0.0, min(1.0, level))
        target = 1.0 - clamped_level
        target = self.min_pos + target * (self.max_pos - self.min_pos)

        if clamped_level > 0:
            self.last_suck_time_ms = now_ms
        elif self.last_suck_time_ms < now_ms - self.resting_time_ms:
            # Resting timeout: snap back toward the resting position.
            target = max(0.0, min(1.0, self.resting_pos))
            max_a = 999.0
            max_v = max(0.0, min(1.0, max_v))

        target = max(0.0, min(1.0, target))
        current = self.last_position

        # How far we'd travel if we decelerated to zero right now.
        if max_a > 0:
            stop_distance = (old_velocity * old_velocity) / (2.0 * max_a)
        else:
            stop_distance = 0.0
        stop_pos = current + (-1.0 if old_velocity < 0 else 1.0) * stop_distance
        from_stop_to_target = target - stop_pos

        # New velocity if we accelerate vs decelerate this tick.
        v_add = old_velocity + max_a * time_delta_s
        v_sub = old_velocity - max_a * time_delta_s
        if abs(v_add) > max_v:
            v_add = (1.0 if v_add > 0 else -1.0) * max_v
        if abs(v_sub) > max_v:
            v_sub = (1.0 if v_sub > 0 else -1.0) * max_v

        pos_add = current + v_add * time_delta_s
        pos_sub = current + v_sub * time_delta_s

        if target == pos_add:
            new_velocity = v_add
        elif target == pos_sub:
            new_velocity = v_sub
        elif (pos_add < target) != (pos_sub < target):
            # Target lies between the accel and decel trajectories -- lock onto it.
            new_velocity = (target - current) / time_delta_s if time_delta_s > 0 else 0.0
        else:
            new_velocity = v_add if from_stop_to_target > 0 else v_sub

        new_position = current + new_velocity * time_delta_s
        if new_position > 1.0:
            new_position = 1.0
            new_velocity = 0.0
        if new_position < 0.0:
            new_position = 0.0
            new_velocity = 0.0

        self.velocity = new_velocity
        self.last_target = target
        self.last_push_time_ms = now_ms

        if new_position != self.last_position:
            duration = int(round(time_delta * self.duration_mult))
            self.last_position = new_position
            return new_position, duration
        return None


# ----------------------------------------------------------------- feature classification
# Per-feature output selection priority. The first six entries (vibrate through
# linear) match OscGoesBrrr's selection order in Buttplug.ts:addDevice. We then
# append the auxiliary outputs buttplug.io defines (LED, temperature, spray) so
# that any device the protocol can drive gets at least one controllable slot.
#
# Kinds are granular for diagnostics ("2x vibrate, 1x linear, 1x led" in the
# connect log) but dispatch only cares whether the kind is in LINEAR_KINDS.
_FEATURE_PRIORITY: List[Tuple[OutputType, str]] = [
    (OutputType.VIBRATE, "vibrate"),
    (OutputType.OSCILLATE, "vibrate"),
    (OutputType.CONSTRICT, "vibrate"),
    (OutputType.ROTATE, "rotate"),
    (OutputType.POSITION_WITH_DURATION, "linear-d"),
    (OutputType.POSITION, "linear"),
    (OutputType.LED, "led"),
    (OutputType.TEMPERATURE, "temperature"),
    (OutputType.SPRAY, "spray"),
]

# Kinds that require the linear-actuator physics tick. All other kinds get the
# simple send-on-change continuous path.
LINEAR_KINDS = frozenset({"linear", "linear-d"})


def _classify_feature(feature) -> Tuple[Optional[str], Optional[OutputType]]:
    for output_type, kind in _FEATURE_PRIORITY:
        try:
            if feature.has_output(output_type):
                return kind, output_type
        except Exception:
            continue
    return None, None


def get_motor_features_for_device(device) -> List[Tuple[str, OutputType, object]]:
    """Return `[(kind, output_type, feature), ...]` for every controllable feature on
    a device, preserving the device's own feature index order.

    `kind` is one of: `"vibrate"` (also covers oscillate / constrict), `"rotate"`,
    `"linear-d"` (POSITION_WITH_DURATION, preferred for stroker hardware that accepts a
    duration), `"linear"` (POSITION), `"led"`, `"temperature"`, `"spray"`.
    """
    result: List[Tuple[str, OutputType, object]] = []
    try:
        features = list(device.features) if hasattr(device, "features") else []
        try:
            features.sort(key=lambda f: getattr(f, "index", 0))
        except Exception:
            pass
        for feature in features:
            kind, output_type = _classify_feature(feature)
            if kind is not None and output_type is not None:
                result.append((kind, output_type, feature))
    except Exception:
        pass
    return result


class HapticEngine:
    """
    Async hardware engine for managing buttplug connections.

    This class is designed to run in its own async thread and communicate
    with the main UI thread via a queue-based message system.
    """

    def __init__(self, thread_queue):
        """
        Initialize the HapticEngine.
        Args:
            thread_queue: Thread-safe queue for communication with main thread
        """
        self.thread_queue = thread_queue

        # Engine exclusively owns its internal state now
        self.device_targets: dict = {}
        self.device_last_sent: dict = {}

        # Hardware clients - these will be set when async_worker runs
        self.buttplug_client: Optional[ButtplugClient] = None

        # Connection state
        self.is_connected = False

        # Per-(device_name, motor_idx) physics state for linear actuators.
        self.linear_actuators: Dict[Tuple[str, int], LinearActuator] = {}
        # Cache of [(kind, output_type, feature), ...] per device name, built at
        # connect time so the worker loop doesn't reflect each tick.
        self._motor_features: Dict[str, List[Tuple[str, OutputType, object]]] = {}

    def update_target(self, device_name: str, motor_idx: int, target_val: float):
        """Thread-safe entry point for the Main Thread to command hardware."""
        self.device_targets[(device_name, motor_idx)] = target_val

    def push_ui_update(self, message: str):
        """Push a UI update to the main thread via queue"""
        self.thread_queue.put(("ui_update", message))

    def push_connection_status(self, connected: bool, server: str = ""):
        """Push connection status to the main thread"""
        self.thread_queue.put(("connection_status", (connected, server)))

    def push_stored_devices_refresh(self):
        """Push stored devices refresh request to main thread"""
        self.thread_queue.put(("stored_devices_refresh", None))

    async def _async_set_vibration(self, intensity: float):
        """Set vibration intensity for all connected devices that support it.

        Linear actuators are intentionally untouched here -- forcing a stroke
        position on every device-wide vibrate command would be a startling UX.
        """
        if not self.buttplug_client or not self.is_connected:
            return

        try:
            for device in self.buttplug_client.devices.values():
                if device.has_output(OutputType.VIBRATE):
                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, intensity))

        except Exception as e:
            self.push_ui_update(f"Vibration error: {e}")

    async def _async_purr_check(self):
        """Test all devices by setting them to 0.1, waiting 1 second, then 0.

        Vibrate-only check by design -- we don't want a Purr-Check to fling a
        linear toy through its full stroke.
        """
        if not self.buttplug_client or not self.is_connected:
            return

        try:
            self.push_ui_update(f"Running Purr-Check on {len(self.buttplug_client.devices)} devices.")

            # Set all devices to 0.1 intensity
            for device in self.buttplug_client.devices.values():
                if device.has_output(OutputType.VIBRATE):
                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.1))

            self.push_ui_update("Purr-Check: All devices at 0.1")

            # Wait for 1 second
            await asyncio.sleep(1.0)

            # Set all devices back to 0.0 intensity
            for device in self.buttplug_client.devices.values():
                if device.has_output(OutputType.VIBRATE):
                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.0))

            self.push_ui_update("Purr-Check: All devices at 0.0 - Test Complete")

        except Exception as e:
            self.push_ui_update(f"Purr-Check error: {e}")

    async def _async_connect(self):
        """Internal async method to connect to Intiface"""
        self.buttplug_client = ButtplugClient(APP_NAME)

        await self.buttplug_client.connect(INTIFACE_WS_URL)

        # Start scanning for devices after connection
        await self.buttplug_client.start_scanning()
        await asyncio.sleep(2.0)  # Give Intiface time to find devices

        # Stop scanning and get device list
        await self.buttplug_client.stop_scanning()

        # Rebuild feature/actuator caches from the freshly discovered devices.
        self._motor_features.clear()
        self.linear_actuators.clear()
        for device in self.buttplug_client.devices.values():
            features = get_motor_features_for_device(device)
            self._motor_features[device.name] = features
            for motor_idx, (kind, _output_type, _feature) in enumerate(features):
                if kind in LINEAR_KINDS:
                    self.linear_actuators[(device.name, motor_idx)] = LinearActuator()

        # Construct dictionary of found devices: {index: {"name": name, "motor_count": count}}
        found_devices = {}
        for device in self.buttplug_client.devices.values():
            features = self._motor_features.get(device.name, [])
            motor_count = len(features)

            kind_counts = {}
            for kind, _, _ in features:
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
            summary = ", ".join(f"{n}x {k}" for k, n in kind_counts.items()) or "none"
            self.push_ui_update(f"Detected motors for {device.name}: {summary}")

            # Fall back to a single vibrate slot if we genuinely found nothing -- keeps
            # the UI usable even for an undetected toy so the user can at least try
            # the global vibrate path.
            if motor_count == 0:
                motor_count = 1

            self.push_ui_update(f"Final motor count for {device.name}: {motor_count} motors")

            found_devices[device.index] = {
                "name": device.name,
                "motor_count": motor_count
            }

        # Update connection status before triggering UI rebuild (fixes race condition)
        self.is_connected = True
        self.push_connection_status(True, "Intiface")

        # Push message to refresh stored devices UI from main thread
        self.push_stored_devices_refresh()

        # Send found devices to main thread via queue
        self.thread_queue.put(("devices_found", found_devices))

        self.push_ui_update(f"Scan complete. Devices found: {len(self.buttplug_client.devices)}")

    async def _async_disconnect(self):
        """Internal async method to disconnect from Intiface"""
        if self.buttplug_client:
            try:
                await self.buttplug_client.disconnect()
            except Exception:
                pass
        self.is_connected = False
        self._motor_features.clear()
        self.linear_actuators.clear()

    async def async_worker(self, app_instance=None):
        """
        Main async worker for buttplug operations.

        This is the primary loop that runs in the async thread, polling
        device targets and sending updates at a controlled rate.

        Vibrate features only emit when the routed level changes. Linear
        actuators tick every cycle regardless so the velocity-limited physics
        and resting-return can complete.

        Args:
            app_instance: Optional reference to OscGoesPurrrApp for buttplug client access
        """

        self.push_ui_update("Async thread started")

        # Main async loop - Golden Loop
        while True:
            if self.is_connected and self.buttplug_client:
                connection_dropped = False
                now_ms = time.monotonic() * 1000.0

                for device in list(self.buttplug_client.devices.values()):
                    if connection_dropped:
                        break
                    device_name = device.name
                    features = self._motor_features.get(device_name, [])

                    # --- Legacy device-wide vibrate (motor_idx == -1) -----------------
                    legacy_target = self.device_targets.get((device_name, -1))
                    if legacy_target is not None:
                        last = self.device_last_sent.get((device_name, -1), 0.0)
                        if legacy_target != last:
                            try:
                                await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, legacy_target))
                                self.device_last_sent[(device_name, -1)] = legacy_target
                            except Exception as e:
                                connection_dropped = self._handle_feature_error(device_name, -1, e)
                                if connection_dropped:
                                    break

                    # --- Per-feature dispatch ---------------------------------------
                    for motor_idx, (kind, output_type, feature) in enumerate(features):
                        target = self.device_targets.get((device_name, motor_idx), 0.0)

                        if kind in LINEAR_KINDS:
                            # Linear actuator: run velocity-limited physics every tick;
                            # only send a command when the computed position changes.
                            actuator = self.linear_actuators.get((device_name, motor_idx))
                            if actuator is None:
                                continue
                            result = actuator.tick(target, now_ms)
                            if result is None:
                                continue
                            new_position, duration_ms = result
                            try:
                                if kind == "linear-d":
                                    await feature.run_output(
                                        DeviceOutputCommand(output_type, new_position, duration=duration_ms)
                                    )
                                else:
                                    await feature.run_output(
                                        DeviceOutputCommand(output_type, new_position)
                                    )
                            except Exception as e:
                                connection_dropped = self._handle_feature_error(device_name, motor_idx, e)
                                if connection_dropped:
                                    break
                        else:
                            # Continuous output (vibrate, rotate, led, temperature, spray):
                            # send the routed 0-1 level directly, only on change.
                            last = self.device_last_sent.get((device_name, motor_idx), 0.0)
                            if target == last:
                                continue
                            try:
                                await feature.run_output(DeviceOutputCommand(output_type, target))
                                self.device_last_sent[(device_name, motor_idx)] = target
                            except Exception as e:
                                connection_dropped = self._handle_feature_error(device_name, motor_idx, e)
                                if connection_dropped:
                                    break

            await asyncio.sleep(HAPTIC_POLL_RATE)  # 50Hz tick

    def _handle_feature_error(self, device_name: str, motor_idx: int, e: Exception) -> bool:
        """Log a feature command error. Return True if the connection appears to have
        dropped (so the caller can stop iterating and let the auto-reconnect loop run)."""
        error_str = str(e).lower()
        self.push_ui_update(f"Vibration error for {device_name} motor {motor_idx}: {e}")
        if any(token in error_str for token in ("closed", "disconnect", "websocket", "connection")):
            self.push_ui_update("Intiface connection lost. Triggering auto-retry.")
            self.is_connected = False
            self.push_connection_status(False, "")
            return True
        return False


def get_device_motor_counts(buttplug_client) -> dict:
    """
    Detect controllable feature counts for all connected devices.

    Counts vibrate-class features (Vibrate, Oscillate, Constrict) AND linear
    actuator features (Position, HwPositionWithDuration) -- previously only
    Vibrate features were counted, which made linear-only toys like the
    Lovense Solace Pro or Gravity report 0 motors and get ignored entirely.

    Args:
        buttplug_client: The buttplug client instance with connected devices.

    Returns:
        Dictionary mapping device name -> motor count (vibrate + linear features).
        Returns empty dict if client is None or not connected.
    """
    if buttplug_client is None:
        return {}

    device_motor_counts = {}
    try:
        for device in buttplug_client.devices.values():
            try:
                device_motor_counts[device.name] = len(get_motor_features_for_device(device))
            except Exception:
                pass
    except Exception:
        pass

    return device_motor_counts
