"""Buttplug/Intiface facade mixin — the original backend's UI-facing call
surface, extracted from main.py so it follows the same recipe as every
other backend (ARCHITECTURE.md "How to add a new haptic backend").

Covers: the engine's asyncio loop bootstrap, connect/disconnect (manual +
auto-reconnect retry loop), the periodic device rescan loop, one-shot
scans, per-toy test pulses and session mutes, per-motor linear-actuator
config sync, hot target dispatch into the engine, and the status
snapshots the UI polls.

Host attributes assumed (provided by OscGoesPurrrApp):
  * ``haptic_engine`` (HapticEngine), ``motor_router`` (MotorRouter)
  * ``async_loop`` / ``async_thread`` / ``_loop_ready`` — the engine's
    asyncio loop thread (bootstrapped here via ``start_async_loop``)
  * ``thread_queue`` — cross-thread event queue drained by main
  * ``profile_manager`` + ``save_profiles()`` /
    ``_refresh_avatar_profile_motor_facts()``
  * ``ui`` (OscGoesPurrrUI) and ``log_message()``
  * ``auto_connect_enabled`` / ``auto_refresh_enabled`` flags and the
    ``_auto_connect_task`` / ``_auto_refresh_task`` future slots
  * ``_muted_devices`` (set), ``_is_updating_ui`` (bool)
  * ``get_feature_enabled()`` / ``set_app_setting()``
"""

import asyncio
import threading
from typing import Any, Dict

import debug_log
from constants import AUTO_REFRESH_RATE_S


class IntifaceFacade:

    # ------------------------------------------------------------------
    # Engine loop bootstrap
    # ------------------------------------------------------------------

    def start_async_loop(self):
        """Start the asyncio event loop in a separate thread"""
        def run_loop():
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            self.async_loop = loop
            # Surface otherwise-hidden async failures (fire-and-forget task
            # exceptions, etc.) into the debug log.
            debug_log.install_asyncio_handler(loop)
            # Tell the main thread the loop is ready; `run()` waits on this
            # instead of polling-sleeping until self.async_loop becomes non-None.
            self._loop_ready.set()

            try:
                # Run the haptic engine async worker (main hardware loop)
                loop.run_until_complete(self.haptic_engine.async_worker())
            except BaseException:
                # If the hardware loop ever dies, the toy pipeline goes silent
                # with no visible error under the windowed build — log it.
                debug_log.get_logger().critical(
                    "haptic async_worker exited unexpectedly", exc_info=True
                )
            finally:
                loop.close()

        # Start async thread
        self.async_thread = threading.Thread(target=run_loop, daemon=True)
        self.async_thread.start()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def update_connection_status(self, connected: bool, server: str):
        """Update connection UI elements (main thread only)"""
        # Sync with haptic engine (haptic_engine.is_connected is now the single source of truth)
        if self.haptic_engine:
            self.haptic_engine.mark_connected(connected)

        # Update UI via ui component
        self.ui.update_connection_status(connected, server)

        if connected:
            # Kick off the periodic rescan so toys powered on AFTER connect get
            # discovered automatically. This is the single choke point for "we
            # just connected" regardless of path (manual button, auto-connect,
            # or reconnect-after-drop) — previously only the manual button
            # started it, so a startup auto-connect never rescanned and newly
            # powered-on toys never appeared without a manual reconnect.
            self._ensure_auto_refresh_running()
        else:
            # Disconnected — including an unexpected engine/websocket drop. Make
            # sure the auto-reconnect retry loop is running. The helper is
            # idempotent and re-checks auto_connect_enabled itself, so a rapid
            # disconnect/reconnect flap can't stack duplicate reconnect loops.
            self._ensure_auto_connect_running()

    def _ensure_auto_refresh_running(self) -> None:
        """Start the periodic device-rescan loop if auto-refresh is enabled and
        it isn't already running. Idempotent — safe to call on every connect."""
        if not (self.auto_refresh_enabled and self.async_loop):
            return
        task = self._auto_refresh_task
        if task is not None and not task.done():
            return  # already running
        try:
            self._auto_refresh_task = asyncio.run_coroutine_threadsafe(
                self._async_auto_refresh_loop(),
                self.async_loop,
            )
        except Exception as e:
            self.log_message(f"Failed to start auto refresh: {e}")

    def _ensure_auto_connect_running(self) -> None:
        """Start the auto-reconnect retry loop if it should run and isn't
        already. Idempotent: safe to call from every disconnect / enable path,
        so an unexpected drop (or a flap) can never stack duplicate reconnect
        loops that would race async_connect() — which, in integrated mode, could
        spawn duplicate engine processes."""
        if not (self.auto_connect_enabled
                and self.get_feature_enabled("feature_intiface")
                and self.async_loop
                and self.haptic_engine
                and not self.haptic_engine.is_connected):
            return
        task = self._auto_connect_task
        if task is not None and not task.done():
            return  # already retrying
        try:
            self._auto_connect_task = asyncio.run_coroutine_threadsafe(
                self._async_auto_connect_loop(),
                self.async_loop,
            )
        except Exception as e:
            self.log_message(f"Failed to start auto connect: {e}")

    def toggle_auto_connect(self):
        """Handle auto-connect checkbox toggle from UI"""
        if not self.ui.get_auto_connect_enabled():
            # Checkbox unchecked - disable auto connect
            self.auto_connect_enabled = False
            self.profile_manager.app_settings.set("auto_connect", False)
            self.log_message("Auto connect disabled")
            if self._auto_connect_task:
                try:
                    self._auto_connect_task.cancel()
                except Exception:
                    pass
                self._auto_connect_task = None
        else:
            # Checkbox checked - enable auto connect
            self.auto_connect_enabled = True
            self.profile_manager.app_settings.set("auto_connect", True)
            self.log_message("Auto connect enabled")
            # If not connected, start the retry loop (idempotent guard).
            self._ensure_auto_connect_running()

    async def _async_attempt_connection(self):
        """Attempt to connect to Intiface once. Returns True if successful."""
        try:
            await self.haptic_engine.async_connect()
            return True
        except FileNotFoundError as e:
            # Permanent until the user acts (missing built-in engine binary):
            # retrying every 2s would just spam the log forever. Surface the
            # actionable message once and pause auto-connect for this session.
            # The flag is in-memory only (not persisted), so a manual Connect —
            # or relaunch after dropping the binary / switching to External
            # mode — resumes normally.
            self.log_message(f"{e}")
            self.log_message(
                "Auto-connect paused — fix the above, then click Connect "
                "(or toggle Auto Connect off/on)."
            )
            self.auto_connect_enabled = False
            return False
        except Exception as e:
            self.log_message(f"Connection attempt failed: {e}")
            return False

    async def _async_auto_connect_loop(self):
        """Background task that retries connection every 2 seconds.

        First attempt fires immediately so a freshly-launched Intiface gets
        picked up without the 2-second sleep delay; subsequent retries pace
        themselves between attempts.
        """
        first_iteration = True
        while (self.auto_connect_enabled
               and self.get_feature_enabled("feature_intiface")
               and not self.haptic_engine.is_connected):
            if not first_iteration:
                await asyncio.sleep(2.0)
            first_iteration = False
            if not (self.auto_connect_enabled
                    and self.get_feature_enabled("feature_intiface")
                    and not self.haptic_engine.is_connected):
                break
            try:
                success = await self._async_attempt_connection()
                if success:
                    self.log_message("Auto-connect: Successfully connected!")
            except Exception:
                pass  # Errors are logged in _async_attempt_connection

    def connect_to_intiface(self):
        """Handle connection button click - connects/disconnects from main thread"""
        if not self.haptic_engine or not self.async_loop:
            return

        # Refuse to dial out when the Intiface feature has been turned off in
        # Settings → Features. (Disconnect still works so the user can hang
        # up an active session even if they then disable the feature.)
        if (not self.haptic_engine.is_connected
                and not self.get_feature_enabled("feature_intiface")):
            self.log_message("Intiface feature is disabled in Settings → Features.")
            return

        # Use haptic_engine.is_connected directly as the source of truth
        if not self.haptic_engine.is_connected:
            # Connect when clicked (if not already connected)
            try:
                self.log_message("Connecting to Intiface...")
                # Schedule the async connect to run in the async thread
                future = asyncio.run_coroutine_threadsafe(
                    self.haptic_engine.async_connect(),
                    self.async_loop
                )
                # Wait for result with a timeout
                future.result(timeout=5)
                self.log_message("Connected to Intiface successfully")

                # Start the periodic rescan loop (guarded; update_connection_status
                # also calls this when the connection_status event lands, so the
                # helper de-dupes).
                self._ensure_auto_refresh_running()
            except Exception as e:
                error_msg = f"Connection failed: {e}"
                self.log_message(error_msg)
                self.update_connection_status(False, "")
        else:
            # Disconnect when clicked (if connected)
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.haptic_engine.async_disconnect(),
                    self.async_loop
                )
                future.result(timeout=2)
                self.update_connection_status(False, "")

                # Stop auto-refresh and auto-connect for the rest of this
                # session. We deliberately do NOT persist these to disk: the
                # user's long-term preferences in app_settings stay True,
                # so the next launch starts fresh. Setting only the in-memory
                # flag means a manual Disconnect respects the user's intent
                # ("stop doing that now") without overwriting the checkbox
                # state they configured earlier. Reconnect via the same
                # button leaves both flags off until the user re-toggles —
                # by design, so auto-reconnect doesn't immediately undo the
                # disconnect they just triggered.
                self.auto_refresh_enabled = False
                if self._auto_refresh_task:
                    self._auto_refresh_task.cancel()
                    self._auto_refresh_task = None

                self.auto_connect_enabled = False
                if self._auto_connect_task:
                    try:
                        self._auto_connect_task.cancel()
                    except Exception:
                        pass
                    self._auto_connect_task = None
            except Exception as e:
                pass

    def set_haptic_connected(self, connected: bool) -> None:
        """Facade: keep the haptic engine's connection flag in sync with the
        VRChat OSC link. Setter-only so the UI never holds the object."""
        if hasattr(self, 'haptic_engine') and self.haptic_engine:
            self.haptic_engine.mark_connected(connected)

    def set_intiface_integrated(self, enabled: bool) -> None:
        """Facade for the Settings → Intiface Engine toggle. Persists the
        choice, pushes the new provisioning mode to the engine, and — if a
        session is live — bounces the connection so the new backend takes
        effect immediately (the running server can't be swapped under an open
        websocket). UI passes a bool only; it never touches the engine."""
        enabled = bool(enabled)
        self.set_app_setting("use_integrated_intiface", enabled)
        mode = "integrated" if enabled else "external"
        if self.haptic_engine:
            self.haptic_engine.set_connection_mode(mode)
        self.log_message(
            "Intiface engine mode: "
            + ("Built-in (no Intiface Central needed)" if enabled
               else "External (run Intiface Central yourself)")
        )

        # Apply live only when already connected — otherwise the next connect
        # picks up the new mode on its own.
        if not (self.haptic_engine and self.haptic_engine.is_connected and self.async_loop):
            return
        self.log_message("Reconnecting Intiface to apply the new engine mode…")
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.haptic_engine.async_disconnect(), self.async_loop
            )
            future.result(timeout=6)
        except Exception as e:
            self.log_message(f"Disconnect during Intiface mode switch failed: {e}")
        # update_connection_status restarts the auto-reconnect loop when
        # auto-connect is on; only kick a manual attempt when it isn't, so we
        # never fire two overlapping connects.
        self.update_connection_status(False, "")
        if not self.auto_connect_enabled and self.get_feature_enabled("feature_intiface"):
            try:
                asyncio.run_coroutine_threadsafe(
                    self._async_attempt_connection(), self.async_loop
                )
            except Exception as e:
                self.log_message(f"Reconnect during Intiface mode switch failed: {e}")

    # ------------------------------------------------------------------
    # Device scanning (one-shot + periodic auto-refresh)
    # ------------------------------------------------------------------

    def toggle_auto_refresh(self):
        """Handle auto-refresh checkbox toggle from UI"""
        if not self.ui.get_auto_refresh_enabled():
            # Checkbox unchecked - disable auto refresh
            self.auto_refresh_enabled = False
            self.profile_manager.app_settings.set("auto_refresh", False)
            self.log_message("Auto refresh disabled")
            if self._auto_refresh_task:
                # Cancel any pending scan task
                self._auto_refresh_task.cancel()
                self._auto_refresh_task = None
        else:
            # Checkbox checked - enable auto refresh
            self.auto_refresh_enabled = True
            self.profile_manager.app_settings.set("auto_refresh", True)
            self.log_message("Auto refresh enabled")
            # If already connected, start the periodic scanning loop
            if self.haptic_engine and self.haptic_engine.is_connected and self.async_loop:
                try:
                    self._auto_refresh_task = asyncio.run_coroutine_threadsafe(
                        self._async_auto_refresh_loop(),
                        self.async_loop
                    )
                except Exception as e:
                    self.log_message(f"Failed to start auto refresh: {e}")

    async def _async_start_scanning(self):
        """Start scanning for devices without connecting (just scan)"""
        if not self.haptic_engine:
            return

        try:
            # Snapshot the pre-scan device set so we can diff after.
            known_devices = set(self.haptic_engine.list_connected_device_names())

            # Run a one-shot scan through the engine facade.
            await self.haptic_engine.async_start_scan(scan_seconds=2.0)

            # Snapshot every connected device (primitives only) and pick out
            # the new ones — never reach into buttplug_client here.
            snapshot = self.haptic_engine.snapshot_discovered_devices()
            new_devices = {
                idx: info for idx, info in snapshot.items()
                if info.get("name") not in known_devices
            }

            if new_devices:
                new_names = {info.get("name") for info in new_devices.values()}
                self.log_message(f"Auto-refresh found new devices: {new_names}")

                # Push new devices to UI
                self.thread_queue.put(("devices_found", new_devices))

                # Refresh stored devices UI to include new devices
                self.thread_queue.put(("stored_devices_refresh", None))

        except Exception as e:
            self.log_message(f"Scan error: {e}")

    async def _async_auto_refresh_loop(self):
        """Background task for periodic device scanning"""
        scan_interval = AUTO_REFRESH_RATE_S
        while self.auto_refresh_enabled and self.haptic_engine.is_connected:
            await asyncio.sleep(scan_interval)
            if self.auto_refresh_enabled and self.haptic_engine.is_connected:
                try:
                    await self._async_start_scanning()
                except Exception as e:
                    pass  # Errors are logged in _async_start_scanning

    def scan_for_toys(self) -> None:
        """Facade: trigger an immediate one-shot rescan for newly powered-on
        toys (a manual "scan now"). Fire-and-forget so the UI never blocks.
        Complements the periodic auto-refresh loop for users who don't want to
        wait up to AUTO_REFRESH_RATE_S after switching a toy on. No-op (with a
        hint) when not connected. UI calls this facade — never the engine."""
        if not (self.async_loop and self.haptic_engine and self.haptic_engine.is_connected):
            self.log_message("Scan for toys: connect to Intiface first.")
            return
        self.log_message("Scanning for new toys…")
        try:
            asyncio.run_coroutine_threadsafe(self._async_start_scanning(), self.async_loop)
        except Exception as e:
            self.log_message(f"Scan for toys failed: {e}")

    # ------------------------------------------------------------------
    # Status snapshots + engine introspection (primitives only)
    # ------------------------------------------------------------------

    def get_connected_device_names(self) -> set:
        """Get set of currently connected device names"""
        if not self.haptic_engine:
            return set()
        return set(self.haptic_engine.list_connected_device_names())

    def get_device_motor_counts(self) -> dict:
        """Facade method to get motor counts safely from the hardware engine."""
        if not self.haptic_engine:
            return {}
        return self.haptic_engine.get_motor_count_map()

    def get_intiface_status(self) -> Dict[str, Any]:
        """Quick snapshot of the Buttplug/Intiface backend's state for
        the Overview view's System tile. UI gets primitives only —
        never reaches into self.haptic_engine directly."""
        engine = getattr(self, "haptic_engine", None)
        connected = bool(engine and engine.is_connected)
        try:
            device_count = len(engine.list_connected_device_names()) if connected else 0
        except Exception:
            device_count = 0
        return {"connected": connected, "device_count": device_count}

    # ------------------------------------------------------------------
    # Linear actuator config sync
    # ------------------------------------------------------------------

    def update_linear_motor_config(self, device_name: str, motor_idx: int) -> None:
        """Facade: read the persisted linear settings for one motor and forward
        them to the HapticEngine. Phase 2 promoted the physics knobs
        (min_pos/max_pos/resting_pos/resting_time_s) to per-motor, so this
        forwards any that are stored alongside mode/idle."""
        if not self.haptic_engine:
            return
        kwargs: Dict[str, Any] = {
            "mode": self.profile_manager.get_profile_config(
                device_name, f"motor_{motor_idx}_linear_mode", "position"
            ),
            "idle": self.profile_manager.get_profile_config(
                device_name, f"motor_{motor_idx}_linear_idle", "rest"
            ),
        }
        for key in ("min_pos", "max_pos", "resting_pos", "resting_time_s"):
            raw = self.profile_manager.get_profile_config(
                device_name, f"motor_{motor_idx}_{key}", None
            )
            if raw is None:
                continue
            try:
                kwargs[key] = float(raw)
            except (TypeError, ValueError):
                continue
        self.haptic_engine.set_linear_config(device_name, motor_idx, **kwargs)

    def _sync_linear_configs(self, devices_dict: dict) -> set:
        """Push the persisted linear mode/idle setting for every motor on every
        freshly discovered device into the engine. Called once on `devices_found`
        so the engine starts with the right behavior even before the user touches
        the UI.

        Returns the set of device names whose persisted motor_kinds
        differed from what the engine just reported — that signal tells
        the queue handler to rebuild ONLY those device frames so motor
        cards pick up the new kinds (the cards bake the kind into
        their widget at construction time and don't track changes
        otherwise). Empty set means no rebuild needed.
        """
        changed_devices: set = set()
        for index, info in (devices_dict or {}).items():
            if isinstance(info, dict):
                device_name = info.get("name")
                motor_count = info.get("motor_count", 0)
            else:
                continue
            if not device_name:
                continue
            # Persist motor_count and motor_kinds so build_stored_devices_ui can
            # render the correct number of motor rows and linear controls even
            # when the device is offline. motor_count must be saved here (not just
            # in build_device_list_ui) because that path skips devices already in
            # device_ui_frames, leaving a stale count in the profile after the
            # first incomplete hot-plug detection (e.g. Lovense Gravity reporting
            # only its vibrate motor before BLE negotiation finishes).
            if motor_count > 0:
                self.profile_manager.update_device_config(device_name, "motor_count", motor_count)
            kinds = info.get("motor_kinds")
            if kinds is not None:
                # Only flag a device as changed when its entry already
                # had kinds and they differ — first-time-connect
                # populates from None and is handled by
                # build_device_list_ui's fresh-frame construction
                # path; no rebuild needed.
                existing = self.profile_manager.get_profile_config(
                    device_name, "motor_kinds", None
                )
                fresh = list(kinds)
                if existing is not None and existing != fresh:
                    changed_devices.add(device_name)
                self.profile_manager.update_device_config(
                    device_name, "motor_kinds", fresh
                )
            for motor_idx in range(motor_count):
                self.update_linear_motor_config(device_name, motor_idx)
        if changed_devices:
            # Propagate the engine's fresh classification to every
            # avatar profile that holds these devices, so switching to
            # an avatar profile mid-session (or on next startup)
            # doesn't surface the old labels again.
            self._refresh_avatar_profile_motor_facts()
        return changed_devices

    # ------------------------------------------------------------------
    # Hot target dispatch + per-toy mutes
    # ------------------------------------------------------------------

    def update_device_target(self, device_name: str, value: float, motor_index: int):
        """Update target intensity for a specific device and motor

        Args:
            device_name: Name of the device
            value: New intensity value (0.0 to 1.0)
            motor_index: Motor index (-1 for all motors, 0+ for specific)
        """
        # Prevent programmatic UI changes from echoing back to the controller
        if getattr(self, '_is_updating_ui', False):
            return

        # Only send updates if connected
        if not self.haptic_engine or not self.haptic_engine.is_connected:
            return

        real_value = float(value)
        # Two ways the engine can be silenced for this motor:
        #   1. Per-toy session mute (Phase 1).
        #   2. Per-motor simulator suppression from the wrapper's
        #      Send-to-toy toggle (Cut 7). The router holds the
        #      suppression set; `should_send_to_toy` returns False
        #      while the wrapper has the toggle off mid-simulation.
        # Either forces the engine value to 0 while the meter keeps
        # showing the real mixer output.
        #
        # Note: `should_send_to_toy` is keyed by specific motor
        # indices. A `motor_index == -1` broadcast (only used at
        # construction time to zero all motors) bypasses the
        # suppression check because (device, -1) is never in the
        # set. That's fine because the simulator only suppresses
        # specific motors and -1 broadcasts already write 0.
        if (device_name in self._muted_devices
                or not self.motor_router.should_send_to_toy(
                    device_name, motor_index
                )):
            engine_value = 0.0
        else:
            engine_value = real_value

        # Send the command safely to the Haptic Engine
        self.haptic_engine.update_target(device_name, motor_index, engine_value)

        # Vibe meter shows the pre-mute value so the user can still see what
        # the mixer is producing while the toy is silent. The UI greys the
        # meter while the device is muted.
        self.ui.update_motor_vibe(device_name, motor_index, real_value)

    def set_device_muted(self, device_name: str, muted: bool) -> None:
        """Soft-mute a single toy (or unmute). When muted, the engine target
        for every motor on this device is forced to 0; the router and mixer
        keep computing so meters still reflect what *would* be playing.

        Session-only — see `_muted_devices` for the rationale. The UI calls
        this from the per-toy mute toggle in the collapsed bar."""
        if muted:
            if device_name in self._muted_devices:
                return
            self._muted_devices.add(device_name)
            # Push 0 to every motor of this device right now rather than
            # waiting for the next router tick — keeps the "mute is a safety
            # toggle" promise honest.
            if self.haptic_engine and self.haptic_engine.is_connected:
                try:
                    counts = self.haptic_engine.get_motor_count_map() or {}
                except Exception:
                    counts = {}
                motor_count = int(counts.get(device_name, 1))
                for motor_idx in range(motor_count):
                    self.haptic_engine.update_target(device_name, motor_idx, 0.0)
        else:
            self._muted_devices.discard(device_name)
            # Next router tick will push the real value back to the engine;
            # no need to forcibly restore anything here.

    def is_device_muted(self, device_name: str) -> bool:
        return device_name in self._muted_devices

    def clear_all_device_mutes(self) -> None:
        """Drop all per-toy mutes. Called on profile switch so a previous
        profile's safety toggle doesn't silently follow the user into a new
        config."""
        if not self._muted_devices:
            return
        self._muted_devices.clear()

    # ------------------------------------------------------------------
    # Test pulses
    # ------------------------------------------------------------------

    def test_device(self, device_name: str) -> None:
        """Fire a short test pulse on every vibrate motor of `device_name`.

        Phase 1 spec: 0.3s at 0.5 intensity. Fire-and-forget so the UI never
        blocks. Linear motors are intentionally skipped (same rationale as
        Purr-Check and Simple Mode's `test_toy`). Distinct from `test_toy`,
        which keeps its 1.0s/0.4 timing for the Simple Mode panel."""
        if not (self.async_loop and self.haptic_engine and self.haptic_engine.is_connected):
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.haptic_engine.async_test_device(
                    device_name, intensity=0.5, duration_s=0.3
                ),
                self.async_loop,
            )
        except Exception as e:
            self.log_message(f"test_device({device_name}) failed: {e}")

    def trigger_purr_check(self):
        """Trigger Purr-Check from main thread"""
        if self.async_loop and self.haptic_engine and self.haptic_engine.is_connected:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.haptic_engine.async_purr_check(),
                    self.async_loop
                )
                future.result(timeout=3)
            except Exception as e:
                self.log_message(f"Purr-Check failed: {e}")

    def test_toy(self, device_name: str):
        """Pulse a single toy for ~1 second. Used by the Simple Mode panel's
        per-toy test button. Fire-and-forget so the UI never blocks."""
        if not (self.async_loop and self.haptic_engine and self.haptic_engine.is_connected):
            return
        try:
            asyncio.run_coroutine_threadsafe(
                self.haptic_engine.async_test_device(device_name),
                self.async_loop,
            )
            self.log_message(f"Testing toy: {device_name}")
        except Exception as e:
            self.log_message(f"Test toy failed ({device_name}): {e}")
