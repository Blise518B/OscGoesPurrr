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
import math
import time
from typing import Any, Dict, List, Optional, Tuple

from buttplug import ButtplugClient, DeviceOutputCommand, OutputType
from constants import (
    APP_NAME,
    HAPTIC_MAX_SEND_HZ,
    HAPTIC_POLL_RATE,
    LINEAR_DURATION_OVERLAP,
    LINEAR_MAX_SEND_HZ,
    LINEAR_MAX_SEND_INTERVAL_MS,
    LINEAR_MIN_POSITION_DELTA,
)
from haptic_actuators import (
    LinearActuator,
    StrokeSpeedActuator,
)
from intiface_connection import (
    MODE_EXTERNAL,
    MODE_INTEGRATED,
    make_intiface_connection,
)
from send_gate import FeatureSendGate


# ----------------------------------------------------------------- feature classification
# Per-feature output selection priority. The first six entries (vibrate through
# linear) match OscGoesBrrr's selection order in Buttplug.ts:addDevice. We then
# append the auxiliary outputs buttplug.io defines (LED, temperature, spray) so
# that any device the protocol can drive gets at least one controllable slot.
#
# Kinds are granular for diagnostics ("2x vibrate, 1x linear, 1x led" in the
# connect log) but dispatch only cares whether the kind is in LINEAR_KINDS.
# Non-linear kinds all go through the same continuous-send path (see the
# `else` branch of the dispatch loop), so distinct labels for oscillate /
# constrict cost nothing at dispatch time but let the UI tell the user
# what each motor actually does. Concrete case: the Lovense Max's pump
# (CONSTRICT) was previously labelled "Vibrate" on the motor card,
# which was misleading even though dispatch was correct.
#
# Ordering note: _classify_feature walks this list in order and
# returns the first OutputType a feature declares (`feature.has_output`).
# The buttplug device config currently splits each motor into its
# own single-output feature (e.g. the Max is two separate features,
# vibrate + constrict), so the ordering only matters as a tiebreaker
# for the hypothetical case of a feature that declares multiple
# OutputTypes simultaneously. If such a device shows up and is
# misclassified, reorder this list — don't promote a feature's
# secondary outputs separately.
_FEATURE_PRIORITY: List[Tuple[OutputType, str]] = [
    (OutputType.VIBRATE, "vibrate"),
    (OutputType.OSCILLATE, "oscillate"),
    (OutputType.CONSTRICT, "constrict"),
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

    `kind` is one of: `"vibrate"`, `"oscillate"`, `"constrict"` (e.g. Lovense Max's
    contraction pump), `"rotate"`, `"linear-d"` (POSITION_WITH_DURATION, preferred
    for stroker hardware that accepts a duration), `"linear"` (POSITION), `"led"`,
    `"temperature"`, `"spray"`. Only the linear kinds change the dispatch path;
    everything else flows through the same continuous-send loop with its
    feature-specific `OutputType` attached, so distinct kinds are purely a
    UI-labelling concern.
    """
    result: List[Tuple[str, OutputType, object]] = []
    try:
        # ButtplugDevice.features is a dict[int, DeviceFeature] keyed by feature index,
        # NOT an iterable of features. Iterating it directly hands us the integer keys
        # and silently breaks classification (every "feature" then fails has_output()
        # and gets skipped), leaving connected devices with motor_count = 0.
        raw_features = getattr(device, "features", None)
        if isinstance(raw_features, dict):
            features = list(raw_features.values())
        elif raw_features is not None:
            features = list(raw_features)
        else:
            features = []
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

        # Per-feature send bookkeeping + decision rules (change gate, in-flight
        # guard, rate caps, linear delta gate, duration sizing). Extracted to
        # send_gate.FeatureSendGate so the dispatch invariants are pure and
        # testable; see that module's docstring for the full rationale. Sends
        # themselves stay fire-and-forget (mirrors OGB's `sendAndForget`) so
        # the worker loop never blocks on Intiface's ack round-trip.
        self._send_gate = FeatureSendGate(
            1000.0 / max(1.0, float(HAPTIC_MAX_SEND_HZ)))
        # Linear actuators use their own, lower cap (LINEAR_MAX_SEND_HZ —
        # Intiface coalesces strokers to ~one flush per 50 ms anyway); their
        # physics still ticks every loop, independent of the cap.
        self._min_linear_send_interval_ms = 1000.0 / max(1.0, float(LINEAR_MAX_SEND_HZ))

        # Strong references to in-flight fire-and-forget send tasks. asyncio only
        # holds weak refs to tasks, so without this a send could be garbage-
        # collected mid-flight. Each task removes itself on completion.
        self._pending_tasks: set = set()

        # Hardware clients - these will be set when async_worker runs
        self.buttplug_client: Optional[ButtplugClient] = None

        # How the Buttplug server is provisioned: "integrated" (we spawn and
        # supervise a bundled intiface-engine) or "external" (connect to a
        # user-run Intiface Central). Set by the controller from the
        # `use_integrated_intiface` app setting via set_connection_mode().
        # The active provider object is built lazily at connect time and kept
        # across reconnects so a transient websocket drop reuses the same
        # running engine instead of respawning it. See intiface_connection.py.
        self._connection_mode = MODE_INTEGRATED
        self._connection = None

        # Serializes connect attempts so a manual Connect racing the auto-
        # reconnect loop can't both build a ButtplugClient and orphan one
        # websocket. Only ever acquired on the async worker loop. (asyncio.Lock
        # is constructed without a running loop on 3.10+ and binds on first use.)
        self._connect_lock = asyncio.Lock()

        # Connection state
        self.is_connected = False

        # Per-(device_name, motor_idx) physics state for linear actuators. Both
        # actuator types are pre-allocated for every linear motor at connect time;
        # the dispatch loop picks one based on the user's current mode setting.
        self.linear_actuators: Dict[Tuple[str, int], LinearActuator] = {}
        self.stroke_speed_actuators: Dict[Tuple[str, int], StrokeSpeedActuator] = {}

        # Guards re-entrant device-list polls in async_worker (see _poll_device_list).
        self._device_poll_in_flight = False

        # Guards re-entrant battery polls in async_worker (see _poll_device_batteries).
        self._battery_poll_in_flight = False

        # Per-(device_name, motor_idx) user-configured linear behavior.
        #   mode: "position" (default) or "speed"
        #   idle: "rest"     (default) or "hold"
        # Updated externally via set_linear_config(); read by the worker loop.
        self.linear_configs: Dict[Tuple[str, int], Dict[str, str]] = {}

        # Cache of [(kind, output_type, feature), ...] per device name, built at
        # connect time so the worker loop doesn't reflect each tick.
        self._motor_features: Dict[str, List[Tuple[str, OutputType, object]]] = {}

    def update_target(self, device_name: str, motor_idx: int, target_val: float):
        """Thread-safe entry point for the Main Thread to command hardware.

        The engine is the last line of defense: coerce and clamp to [0, 1]
        here so no caller (router bug, UI test path) can push garbage, an
        out-of-range value, or NaN into the device output command."""
        try:
            v = float(target_val)
        except (TypeError, ValueError):
            v = 0.0
        if not math.isfinite(v):
            v = 0.0
        self.device_targets[(device_name, motor_idx)] = min(max(v, 0.0), 1.0)

    def _dispatch_output(self, device_name: str, motor_idx: int, coro) -> None:
        """Fire-and-forget a continuous-output command on the engine loop.

        `coro` is an un-awaited ``run_output(...)`` coroutine. We schedule it as
        a task instead of awaiting it inline so the worker loop doesn't stall on
        Intiface's ack round-trip (and so one slow toy can't hold up the others).
        The feature is marked in-flight until the task settles; send errors are
        routed through ``_handle_feature_error`` exactly as the inline await did.
        Must be called from the engine's own event loop (async_worker)."""
        key = (device_name, motor_idx)
        self._send_gate.set_inflight(key, True)

        async def _runner():
            try:
                await coro
            except Exception as e:
                self._handle_feature_error(device_name, motor_idx, e)
            finally:
                self._send_gate.set_inflight(key, False)

        try:
            task = asyncio.create_task(_runner())
        except RuntimeError:
            # No running loop (shouldn't happen inside async_worker). Clear the
            # flag so the feature isn't wedged and close the orphaned coroutine.
            self._send_gate.set_inflight(key, False)
            try:
                coro.close()
            except Exception:
                pass
            return
        # Hold a strong ref until the task settles (asyncio keeps only weak refs).
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def mark_connected(self, connected: bool) -> None:
        """Thread-safe facade: external observers (the VRChat OSC link, the
        Controller's auto-connect logic) flip the engine's connection flag
        through this setter instead of poking `is_connected` directly. Keeps
        the engine's internal state owned by the engine (ARCHITECTURE.md
        rule #3)."""
        self.is_connected = bool(connected)

    def set_connection_mode(self, mode: str) -> None:
        """Primitive facade: choose how the Buttplug server is provisioned —
        "integrated" (spawn our own intiface-engine) or "external" (a user-run
        Intiface Central). Takes effect on the next connect; the controller is
        responsible for bouncing an active connection if the user flips this
        mid-session. A plain string write, owned by the engine like
        `is_connected` (ARCHITECTURE.md rule #3)."""
        self._connection_mode = (
            MODE_EXTERNAL if mode == MODE_EXTERNAL else MODE_INTEGRATED
        )

    def release_managed_server(self) -> None:
        """Best-effort, synchronous teardown of any server this engine spawned
        (the integrated intiface-engine). No-op in external mode or when
        nothing was started. Called from the app-quit path so a clean exit
        doesn't momentarily leave the engine holding the Bluetooth radio while
        the OS reclaims the process.

        Thread note: `self._connection` is otherwise written on the async worker
        loop (async_connect/disconnect), and this reads it from the main thread.
        That's safe by construction — the pointer read is GIL-atomic, the
        provider's terminate() is idempotent and thread-safe, and on the quit
        path the Windows Job Object kill-on-close is the real backstop, so the
        worst a race can do is briefly leave an engine the OS then reaps."""
        conn = self._connection
        if conn is not None:
            try:
                conn.terminate()
            except Exception:
                pass

    def set_linear_config(self, device_name: str, motor_idx: int,
                          mode: str = "position", idle: str = "rest",
                          min_pos: Optional[float] = None,
                          max_pos: Optional[float] = None,
                          resting_pos: Optional[float] = None,
                          resting_time_s: Optional[float] = None) -> None:
        """Thread-safe entry point for the controller to push per-motor linear
        actuator behavior. Only meaningful for motors whose feature kind is in
        LINEAR_KINDS; calling for a vibrate motor is a harmless no-op at
        dispatch time. `mode` is "position" or "speed"; `idle` is "rest"
        or "hold". The min_pos/max_pos/resting_pos/resting_time_s kwargs
        are Phase 2 per-motor overrides — when `None`, the actuator keeps
        whatever it was constructed with (the haptic_actuators defaults)."""
        if mode not in ("position", "speed"):
            mode = "position"
        if idle not in ("rest", "hold"):
            idle = "rest"
        cfg: Dict[str, Any] = {"mode": mode, "idle": idle}
        if min_pos is not None:
            cfg["min_pos"] = float(min_pos)
        if max_pos is not None:
            cfg["max_pos"] = float(max_pos)
        if resting_pos is not None:
            cfg["resting_pos"] = float(resting_pos)
        if resting_time_s is not None:
            cfg["resting_time_s"] = float(resting_time_s)
        self.linear_configs[(device_name, motor_idx)] = cfg
        # Push the per-motor overrides into BOTH live actuator instances so
        # the change takes effect on the next tick without waiting for a
        # disconnect/reconnect cycle. The stroke-speed actuator shares the
        # same attribute names; skipping it left the "Stroke setup" knobs
        # (range / resting) silently dead in Speed mode.
        for actuator in (self.linear_actuators.get((device_name, motor_idx)),
                         self.stroke_speed_actuators.get((device_name, motor_idx))):
            if actuator is None:
                continue
            if min_pos is not None:
                actuator.min_pos = float(min_pos)
            if max_pos is not None:
                actuator.max_pos = float(max_pos)
            if resting_pos is not None:
                actuator.resting_pos = float(resting_pos)
            if resting_time_s is not None:
                actuator.resting_time_ms = float(resting_time_s) * 1000.0

    def _build_actuator(self, key: Tuple[str, int], cls):
        """Construct a LinearActuator / StrokeSpeedActuator seeded from the
        stored per-motor linear config, so user overrides (stroke range /
        resting behavior) survive reconnects and device rediscovery instead
        of resetting to the class defaults."""
        actuator = cls()
        cfg = self.linear_configs.get(key) or {}
        try:
            if "min_pos" in cfg:
                actuator.min_pos = float(cfg["min_pos"])
            if "max_pos" in cfg:
                actuator.max_pos = float(cfg["max_pos"])
            if "resting_pos" in cfg:
                actuator.resting_pos = float(cfg["resting_pos"])
            if "resting_time_s" in cfg:
                actuator.resting_time_ms = float(cfg["resting_time_s"]) * 1000.0
        except (TypeError, ValueError):
            pass
        return actuator

    # ------------------------------------------------------------------
    # Read-only introspection facades — return primitives only so callers
    # never need to touch self.buttplug_client. This is the sealed-box
    # boundary referenced in ARCHITECTURE.md (rule #3).
    # ------------------------------------------------------------------

    def list_connected_device_names(self) -> List[str]:
        """Names of every currently-connected toy. Empty list if disconnected."""
        if not self.is_connected or self.buttplug_client is None:
            return []
        try:
            return [d.name for d in self.buttplug_client.devices.values()]
        except Exception:
            return []

    def get_motor_count_map(self) -> Dict[str, int]:
        """`{device_name: motor_count}` for every connected device.

        Counts vibrate-class AND linear features (see `get_motor_features_for_device`).
        Empty dict if disconnected.
        """
        if not self.is_connected or self.buttplug_client is None:
            return {}
        out: Dict[str, int] = {}
        try:
            for device in self.buttplug_client.devices.values():
                try:
                    out[device.name] = len(get_motor_features_for_device(device))
                except Exception:
                    pass
        except Exception:
            pass
        return out

    def snapshot_discovered_devices(self) -> Dict[int, Dict[str, object]]:
        """Snapshot every connected toy as `{device_index: {"name": str,
        "motor_count": int, "motor_kinds": [str, ...]}}`. Used by scan/refresh
        paths to push primitive device records onto the main thread queue.

        Counts ALL controllable features via `get_motor_features_for_device`
        — the same classification every other discovery path uses. Counting
        only VIBRATE here used to shrink a multi-feature toy's persisted
        motor_count when the periodic scan re-reported it (a Max's constrict
        or a Nora's rotate motor silently dropped out of routing).
        """
        if not self.is_connected or self.buttplug_client is None:
            return {}
        out: Dict[int, Dict[str, object]] = {}
        try:
            for device in self.buttplug_client.devices.values():
                try:
                    features = get_motor_features_for_device(device)
                    motor_kinds = [kind for kind, _, _ in features]
                    motor_count = len(features)
                    if motor_count == 0:
                        motor_count = 1
                        motor_kinds = ["vibrate"]
                    out[device.index] = {
                        "name": device.name,
                        "motor_count": motor_count,
                        "motor_kinds": motor_kinds,
                    }
                except Exception:
                    pass
        except Exception:
            pass
        return out

    async def async_start_scan(self, scan_seconds: float = 2.0) -> None:
        """Run a one-shot scan on the engine's own loop. Awaitable so the
        caller can `run_coroutine_threadsafe` it. No return value — callers
        follow up with `snapshot_discovered_devices()`."""
        if self.buttplug_client is None:
            return
        try:
            await self.buttplug_client.start_scanning()
            await asyncio.sleep(scan_seconds)
            await self.buttplug_client.stop_scanning()
        except Exception:
            pass

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

    async def async_test_device(self, device_name: str, intensity: float = 0.4,
                                 duration_s: float = 1.0):
        """Pulse a single device's vibrate motors at `intensity` for `duration_s`,
        then drop back to 0. Linear motors are intentionally skipped (same
        rationale as Purr-Check)."""
        if not self.buttplug_client or not self.is_connected:
            return
        try:
            target = None
            for device in self.buttplug_client.devices.values():
                if device.name == device_name:
                    target = device
                    break
            if target is None or not target.has_output(OutputType.VIBRATE):
                return
            await target.run_output(DeviceOutputCommand(OutputType.VIBRATE, intensity))
            await asyncio.sleep(duration_s)
            await target.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.0))
        except Exception as e:
            self.push_ui_update(f"Test toy error ({device_name}): {e}")

    async def async_purr_check(self):
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

    async def _poll_device_list(self) -> None:
        """Manually re-request the server's device list.

        The Python `buttplug` client (v1.0.0) only processes bulk DeviceList
        messages in `_handle_server_message`; the per-device DeviceAdded /
        DeviceRemoved protocol messages that Intiface actually emits on BLE
        connect/disconnect are silently dropped. So our `on_device_added` /
        `on_device_removed` callbacks would never fire on a real-world toy
        powering off, despite the hooks being registered.

        Workaround: periodically call the client's internal _request_device_list,
        which routes through _handle_device_list -- the same code path that
        diffs the device map and fires our callbacks. This makes the engine's
        view of connected toys self-correcting within one poll interval.

        Guarded by _device_poll_in_flight so async_worker can fire-and-forget
        the coroutine without piling up overlapping requests if Intiface gets
        slow.
        """
        if self._device_poll_in_flight:
            return
        if not self.buttplug_client or not self.is_connected:
            return
        self._device_poll_in_flight = True
        try:
            await self.buttplug_client._request_device_list()

            # After the device list refreshes, re-check feature counts for every
            # already-known device. Lovense toys (Gravity, Solace Pro, etc.) go
            # through BLE service discovery AFTER Intiface first reports them, so
            # the initial _on_device_added callback fires before the rotate / linear
            # features are available. Once negotiation completes the feature dict
            # silently grows, but _on_device_added never fires again because the
            # device index is already in the client map.
            for device in list(self.buttplug_client.devices.values()):
                fresh = get_motor_features_for_device(device)
                if not fresh:
                    continue
                cached = self._motor_features.get(device.name)
                if cached is not None and len(fresh) == len(cached):
                    continue  # No change — skip

                # Feature set grew (or first time seeing this device in the cache).
                self._motor_features[device.name] = fresh
                motor_kinds = [kind for kind, _, _ in fresh]
                for motor_idx, (kind, _ot, _f) in enumerate(fresh):
                    if kind in LINEAR_KINDS:
                        key = (device.name, motor_idx)
                        if key not in self.linear_actuators:
                            self.linear_actuators[key] = \
                                self._build_actuator(key, LinearActuator)
                        if key not in self.stroke_speed_actuators:
                            self.stroke_speed_actuators[key] = \
                                self._build_actuator(key, StrokeSpeedActuator)
                self.push_ui_update(
                    f"Feature update: {device.name} now has {len(fresh)} motors"
                )
                # Push devices_found first so _sync_linear_configs persists the
                # new motor_kinds into the profile before the rebuild reads them.
                self.thread_queue.put((
                    "devices_found",
                    {
                        device.index: {
                            "name": device.name,
                            "motor_count": len(fresh),
                            "motor_kinds": motor_kinds,
                        }
                    },
                ))
                # Full rebuild so the new motor rows actually appear in the UI.
                self.push_stored_devices_refresh()

        except Exception:
            # Connector errors during a disconnect are handled by the
            # _on_server_disconnect path; nothing useful for us to do here.
            pass
        finally:
            self._device_poll_in_flight = False

    async def _poll_device_batteries(self) -> None:
        """Read battery level from every connected device that supports it."""
        if self._battery_poll_in_flight:
            return
        if not self.buttplug_client or not self.is_connected:
            return
        self._battery_poll_in_flight = True
        try:
            for device in list(self.buttplug_client.devices.values()):
                if not device.has_battery():
                    continue
                try:
                    level = await device.battery()
                    self.thread_queue.put(("battery_update", {
                        "device_name": device.name,
                        "level": level,
                    }))
                except Exception:
                    pass
        finally:
            self._battery_poll_in_flight = False

    def _on_device_added(self, device) -> None:
        """Buttplug client callback fired when a device appears AFTER the initial
        connect (e.g. user paired a new toy via Intiface, or a paired toy came
        back into BLE range after a battery swap).

        Pre-initial-scan additions are intentionally ignored here -- they get
        batched into the bulk `devices_found` push from `async_connect`. Gating
        on `is_connected` keeps us from double-pushing during the connect window.
        """
        if not self.is_connected:
            return
        try:
            device_name = getattr(device, "name", None)
            if not device_name:
                return

            features = get_motor_features_for_device(device)
            self._motor_features[device_name] = features
            motor_kinds = [kind for kind, _, _ in features]
            for motor_idx, (kind, _output_type, _feature) in enumerate(features):
                if kind in LINEAR_KINDS:
                    key = (device_name, motor_idx)
                    if key not in self.linear_actuators:
                        self.linear_actuators[key] = \
                            self._build_actuator(key, LinearActuator)
                    if key not in self.stroke_speed_actuators:
                        self.stroke_speed_actuators[key] = \
                            self._build_actuator(key, StrokeSpeedActuator)

            motor_count = len(features) if features else 1
            if not features:
                motor_kinds = ["vibrate"]

            self.push_ui_update(f"Device connected: {device_name} ({motor_count} motors)")
            self.thread_queue.put((
                "devices_found",
                {
                    getattr(device, "index", device_name): {
                        "name": device_name,
                        "motor_count": motor_count,
                        "motor_kinds": motor_kinds,
                    }
                },
            ))
        except Exception as e:
            self.push_ui_update(f"on_device_added handler error: {e}")

    def _on_device_removed(self, device) -> None:
        """Buttplug client callback fired when a device disconnects (toy powered
        off, BLE drop, battery dead, etc.). The device has already been removed
        from `buttplug_client.devices` by the time this fires.
        """
        try:
            device_name = getattr(device, "name", None)
            if not device_name:
                return

            # Drop all per-device state so a stale linear physics tick doesn't
            # try to command a feature that no longer exists.
            self._motor_features.pop(device_name, None)
            for k in list(self.linear_actuators.keys()):
                if k[0] == device_name:
                    self.linear_actuators.pop(k, None)
            for k in list(self.stroke_speed_actuators.keys()):
                if k[0] == device_name:
                    self.stroke_speed_actuators.pop(k, None)
            for k in list(self.device_targets.keys()):
                if k[0] == device_name:
                    self.device_targets.pop(k, None)
            self._send_gate.forget_device(device_name)
            for k in list(self.linear_configs.keys()):
                if k[0] == device_name:
                    self.linear_configs.pop(k, None)

            self.push_ui_update(f"Device disconnected: {device_name}")
            self.thread_queue.put(("device_removed", device_name))
        except Exception as e:
            self.push_ui_update(f"on_device_removed handler error: {e}")

    def _on_server_disconnect(self) -> None:
        """Buttplug client callback fired when the WS to Intiface closes.

        Safe to call from any thread/loop -- only does flag updates and queue puts,
        no I/O. Idempotent: a second invocation after we've already marked the
        engine disconnected is a no-op. The main thread's queue processor sees
        the pushed connection_status and reactivates the auto-reconnect loop.
        """
        if not self.is_connected:
            return
        # Neutral wording: the engine can't promise a retry — whether one
        # happens is the controller's call (it depends on auto-connect being
        # on). The auto-reconnect loop logs its own "Auto-connect: …" line.
        self.push_ui_update("Intiface server disconnected.")
        self.mark_connected(False)
        self.push_connection_status(False, "")

    async def async_connect(self):
        """Connect to the Buttplug server, serialized against itself.

        A manual Connect can race the auto-reconnect loop; without this guard
        both would build a ButtplugClient and one websocket would be orphaned.
        The lock makes the second caller wait, then return early if the first
        already connected (a still-disconnected state means the first failed, so
        retrying is correct)."""
        async with self._connect_lock:
            if self.is_connected:
                return
            await self._async_connect_impl()

    async def _async_connect_impl(self):
        """Internal async method to connect to the Buttplug server.

        The server is provisioned by the active connection provider — either
        spawning our bundled intiface-engine ("integrated") or just pointing at
        a user-run Intiface Central ("external"). Everything after the
        websocket connect is identical for both modes.
        """
        # (Re)build the provider only when missing or when the user switched
        # modes since the last connect. Reusing a live provider lets the
        # integrated engine survive a transient websocket drop + auto-reconnect.
        if self._connection is not None and self._connection.mode != self._connection_mode:
            try:
                await self._connection.shutdown()
            except Exception:
                pass
            self._connection = None
        if self._connection is None:
            self._connection = make_intiface_connection(
                self._connection_mode, log=self.push_ui_update
            )

        ws_url = await self._connection.prepare()

        self.buttplug_client = ButtplugClient(APP_NAME)

        await self.buttplug_client.connect(ws_url)

        # Register the server-disconnect event hook so we notice the moment Intiface
        # closes the websocket, even when no haptic commands are currently flowing.
        # The async_worker poll below is a defensive fallback for buttplug versions
        # where this hook never fires.
        try:
            self.buttplug_client.on_server_disconnect = self._on_server_disconnect
        except Exception:
            pass

        # Start scanning for devices after connection
        await self.buttplug_client.start_scanning()
        await asyncio.sleep(2.0)  # Give Intiface time to find devices

        # Stop scanning and get device list
        await self.buttplug_client.stop_scanning()

        # Rebuild feature/actuator caches from the freshly discovered devices.
        self._motor_features.clear()
        self.linear_actuators.clear()
        self.stroke_speed_actuators.clear()
        # Forgetting what we last sent is load-bearing: after a reconnect the
        # toy is physically at 0 (the server stops devices on disconnect), so
        # a routed target unchanged across the outage must be re-sent — see
        # FeatureSendGate.clear().
        self._send_gate.clear()
        for device in self.buttplug_client.devices.values():
            features = get_motor_features_for_device(device)
            self._motor_features[device.name] = features
            for motor_idx, (kind, _output_type, _feature) in enumerate(features):
                if kind in LINEAR_KINDS:
                    # Pre-allocate both modes so a UI toggle is instant,
                    # seeded from the stored per-motor config so overrides
                    # (stroke range / resting) survive a reconnect.
                    key = (device.name, motor_idx)
                    self.linear_actuators[key] = self._build_actuator(key, LinearActuator)
                    self.stroke_speed_actuators[key] = self._build_actuator(key, StrokeSpeedActuator)

        # Construct dictionary of found devices: {index: {"name", "motor_count", "motor_kinds"}}
        found_devices = {}
        for device in self.buttplug_client.devices.values():
            features = self._motor_features.get(device.name, [])
            motor_count = len(features)
            motor_kinds = [kind for kind, _, _ in features]

            kind_counts = {}
            for kind in motor_kinds:
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
            summary = ", ".join(f"{n}x {k}" for k, n in kind_counts.items()) or "none"
            self.push_ui_update(f"Detected motors for {device.name}: {summary}")

            # Fall back to a single vibrate slot if we genuinely found nothing -- keeps
            # the UI usable even for an undetected toy so the user can at least try
            # the global vibrate path.
            if motor_count == 0:
                motor_count = 1
                motor_kinds = ["vibrate"]

            self.push_ui_update(f"Final motor count for {device.name}: {motor_count} motors")

            found_devices[device.index] = {
                "name": device.name,
                "motor_count": motor_count,
                "motor_kinds": motor_kinds,
            }

        # Update connection status before triggering UI rebuild (fixes race condition)
        self.mark_connected(True)
        self.push_connection_status(True, self._connection.status_label)

        # Register device add/remove hooks AFTER the initial bulk sync. Doing it
        # earlier would cause per-device callbacks to fire during the initial
        # scan, racing with the bulk devices_found push below.
        try:
            self.buttplug_client.on_device_added = self._on_device_added
            self.buttplug_client.on_device_removed = self._on_device_removed
        except Exception:
            pass

        # Push message to refresh stored devices UI from main thread
        self.push_stored_devices_refresh()

        # Send found devices to main thread via queue
        self.thread_queue.put(("devices_found", found_devices))

        self.push_ui_update(f"Scan complete. Devices found: {len(self.buttplug_client.devices)}")

    async def async_disconnect(self):
        """Internal async method to disconnect from the Buttplug server.

        Beyond closing the websocket, this tears down the active connection
        provider — which, in integrated mode, stops the intiface-engine we
        spawned. The provider is dropped so the next connect rebuilds it
        (and respawns the engine) fresh. A websocket-only drop does NOT come
        through here, so auto-reconnect still reuses a live engine.
        """
        if self.buttplug_client:
            try:
                await self.buttplug_client.disconnect()
            except Exception:
                pass
        if self._connection is not None:
            try:
                await self._connection.shutdown()
            except Exception:
                pass
            self._connection = None
        self.mark_connected(False)
        self._motor_features.clear()
        self.linear_actuators.clear()
        self.stroke_speed_actuators.clear()
        # The devices are stopped by the server on disconnect — the next
        # session must not believe pre-disconnect values were delivered.
        self._send_gate.clear()

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

        # Re-request the device list on a slow cadence so toy hot-plug events
        # surface in real time. Buttplug protocol uses DeviceAdded / DeviceRemoved
        # messages, but the Python client v1.0.0 doesn't process them -- only the
        # bulk DeviceList. Polling every ~2s drives _handle_device_list ourselves.
        # Expressed in ticks so it tracks HAPTIC_POLL_RATE automatically.
        device_poll_tick_count = int(2.0 / max(HAPTIC_POLL_RATE, 0.001))
        ticks_since_device_poll = 0

        # Poll battery every ~30s. Start at max so first read fires immediately.
        battery_poll_tick_count = int(30.0 / max(HAPTIC_POLL_RATE, 0.001))
        ticks_since_battery_poll = battery_poll_tick_count

        # Main async loop - Golden Loop
        while True:
            if self.is_connected and self.buttplug_client:
                # Defensive health check: catch WS drops the on_server_disconnect
                # hook never surfaced (older buttplug versions, edge timing).
                try:
                    if not self.buttplug_client.connected:
                        self._on_server_disconnect()
                        await asyncio.sleep(HAPTIC_POLL_RATE)
                        continue
                except Exception:
                    pass

                # Drive device add/remove callbacks via periodic re-request.
                ticks_since_device_poll += 1
                if ticks_since_device_poll >= device_poll_tick_count:
                    ticks_since_device_poll = 0
                    # Fire-and-forget so dispatch never blocks on Intiface latency.
                    try:
                        asyncio.create_task(self._poll_device_list())
                    except Exception:
                        pass

                # Refresh battery levels on a slow cadence.
                ticks_since_battery_poll += 1
                if ticks_since_battery_poll >= battery_poll_tick_count:
                    ticks_since_battery_poll = 0
                    try:
                        asyncio.create_task(self._poll_device_batteries())
                    except Exception:
                        pass

                connection_dropped = False
                now_ms = time.monotonic() * 1000.0

                for device in list(self.buttplug_client.devices.values()):
                    if connection_dropped:
                        break
                    device_name = device.name
                    features = self._motor_features.get(device_name, [])

                    # --- Legacy device-wide vibrate (motor_idx == -1) -----------------
                    legacy_target = self.device_targets.get((device_name, -1))
                    if (legacy_target is not None
                            and self._send_gate.try_continuous(
                                (device_name, -1), legacy_target, now_ms)):
                        # Fire-and-forget (see _dispatch_output), rate-capped
                        # per feature; the loop never blocks on the ack.
                        self._dispatch_output(
                            device_name, -1,
                            device.run_output(
                                DeviceOutputCommand(OutputType.VIBRATE, legacy_target)
                            ),
                        )

                    # --- Per-feature dispatch ---------------------------------------
                    for motor_idx, (kind, output_type, feature) in enumerate(features):
                        target = self.device_targets.get((device_name, motor_idx), 0.0)

                        if kind in LINEAR_KINDS:
                            # Integrate the stroke physics EVERY loop so the
                            # trajectory stays smooth and fine-grained, decoupled
                            # from how often we actually transmit. tick() returns
                            # the current 0-1 position; the send policy below is
                            # what's rate-capped, not the physics.
                            cfg = self.linear_configs.get((device_name, motor_idx), {})
                            mode = cfg.get("mode", "position")
                            idle = cfg.get("idle", "rest")
                            if mode == "speed":
                                actuator = self.stroke_speed_actuators.get((device_name, motor_idx))
                            else:
                                actuator = self.linear_actuators.get((device_name, motor_idx))
                            if actuator is None:
                                continue
                            position = actuator.tick(target, now_ms, idle_mode=idle)

                            # Send policy (see FeatureSendGate.try_linear): the
                            # linear per-feature cap (20 Hz — Intiface flushes
                            # strokers at most once per 50 ms and coalesces the
                            # rest) + in-flight guard (stroke positions must
                            # never arrive out of order) + min-delta gate (a
                            # held/resting stroke goes quiet instead of
                            # re-commanding the same spot). On grant it returns
                            # a duration that overshoots the real send gap so
                            # slow motion doesn't "step".
                            duration_ms = self._send_gate.try_linear(
                                (device_name, motor_idx), position, now_ms,
                                self._min_linear_send_interval_ms,
                                LINEAR_MIN_POSITION_DELTA,
                                LINEAR_DURATION_OVERLAP,
                                LINEAR_MAX_SEND_INTERVAL_MS,
                            )
                            if duration_ms is None:
                                continue

                            # Fire-and-forget like the continuous path so a linear
                            # toy's ack never stalls the loop (or other devices).
                            if kind == "linear-d":
                                coro = feature.run_output(
                                    DeviceOutputCommand(output_type, position, duration=duration_ms)
                                )
                            else:
                                coro = feature.run_output(
                                    DeviceOutputCommand(output_type, position)
                                )
                            self._dispatch_output(device_name, motor_idx, coro)
                        else:
                            # Continuous output (vibrate, rotate, led, temperature, spray):
                            # send the routed 0-1 level on change, fire-and-forget
                            # so the loop never blocks on Intiface's ack round-trip.
                            # Unchanged / in-flight / rate-capped: hold the newest
                            # value and dispatch it on a later tick (latest-wins —
                            # see FeatureSendGate.try_continuous).
                            if not self._send_gate.try_continuous(
                                    (device_name, motor_idx), target, now_ms):
                                continue
                            self._dispatch_output(
                                device_name, motor_idx,
                                feature.run_output(DeviceOutputCommand(output_type, target)),
                            )

            await asyncio.sleep(HAPTIC_POLL_RATE)  # engine tick (HAPTIC_POLL_RATE)

    def _handle_feature_error(self, device_name: str, motor_idx: int, e: Exception) -> bool:
        """Log a feature command error. Return True if the connection appears to have
        dropped (so the caller can stop iterating and let the auto-reconnect loop run)."""
        error_str = str(e).lower()
        self.push_ui_update(f"Vibration error for {device_name} motor {motor_idx}: {e}")
        if any(token in error_str for token in ("closed", "disconnect", "websocket", "connection")):
            self.push_ui_update("Intiface connection lost. Triggering auto-retry.")
            self.mark_connected(False)
            self.push_connection_status(False, "")
            return True
        return False


