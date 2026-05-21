# OscGoesPurrr - Main Orchestrator (The Traffic Cop)
#
# This file is the Controller. It boots the threads, holds the
# profile_manager, drains the cross-thread queue, and routes data
# between layers. Per-engine UI-facing methods live as mixins under
# `controllers/` and are composed into OscGoesPurrrApp via multiple
# inheritance below.
#
# See ARCHITECTURE.md for the full picture (Brain / Eardrum / Muscles
# family / stateless Routers / Face / Traffic Cop) and the four
# anti-tangling rules that keep the layers separate.

import threading
import asyncio
import queue
import pystray
from typing import Optional, Dict, List, Any

# ProfileManager from config manager module
from config_manager import PROFILE_FILE, ProfileManager

# UI Components for the Visual Shell (The Face / View)
from ui_components import OscGoesPurrrUI

# Haptic Engine for async hardware operations
from haptic_engine import HapticEngine

# VRChat OSC Manager for OSC discovery and routing
from vrchat_osc import VRChatOSCManager
from motor_router import MotorRouter
from parameter_store import store
from steamvr_engine import SteamVREngine
from steamvr_router import SteamVRRouter, SteamVRBatteryBroadcaster
from bhaptics_engine import BHapticsEngine
from bhaptics_router import BHapticsRouter
from hardware_monitor import HardwareMonitorEngine
from constants import *
from utilities import value_to_hex_color, toggle_windows_console, create_default_icon
from version import __version__

# Per-engine facade mixins extend the controller's call surface without
# bloating main.py — each mixin's docstring covers its assumed attributes.
from controllers import (
    SteamVRFacade,
    SteamVRToysFacade,
    BHapticsFacade,
    HardwareMonitorFacade,
)


class OscGoesPurrrApp(
    SteamVRFacade,
    SteamVRToysFacade,
    BHapticsFacade,
    HardwareMonitorFacade,
):
    def __init__(self):
        self.async_loop: asyncio.AbstractEventLoop = None
        
        # Thread-safe communication queue (standard library, not asyncio)
        self.thread_queue: queue.Queue = queue.Queue()
        
        # Profile manager instance
        self.profile_manager = ProfileManager()

        # Seed *every* profile with every known toy on startup. Toys are
        # global; profiles are settings overlays. Running this for all
        # profiles means a stale config from before the global registry
        # existed gets unified the first time you launch the new build.
        for _pname in list(self.profile_manager.profiles.keys()):
            self._seed_profile_with_known_devices(_pname)
        print(f"[profiles] known toys: {list(self.profile_manager.known_devices.all().keys())}")

        # Keep aliases for backward compatibility during refactoring
        self.profiles = self.profile_manager.profiles
        self.current_profile = self.profile_manager.current_profile
        
        # UI Component - handles all GUI rendering and updates
        self.ui: OscGoesPurrrUI = None
        
        # Haptic Engine - async hardware interface (single source of truth for connection state)
        self.haptic_engine: Optional[HapticEngine] = None
        
        # Signal raised by the async worker thread once its event loop is
        # bound; replaces the old polling-sleep startup race.
        self._loop_ready = threading.Event()

        # Auto-refresh state - loaded from config in _setup_components
        self.auto_refresh_enabled = True
        self._auto_refresh_task = None  # For storing the periodic scan task
        
        # Auto-connect state - loaded from config in _setup_components
        self.auto_connect_enabled = True
        self._auto_connect_task = None  # For storing the auto-connect retry loop task reference
        
        # OSC Debugger state
        self.is_debugging_osc = False
        
        # UI Lock - prevent programmatic UI changes from echoing back to the controller
        self._is_updating_ui = False
        
        # Dirty flag to debounce rapid OSC bundles
        self._needs_recalculation = False

        # Cache of latest battery level per device (0..1). Populated from
        # battery_update queue messages; surfaced via get_simple_mode_toys()
        # so the Simple Mode panel can show a live battery icon next to each
        # connected toy.
        self._battery_cache: Dict[str, float] = {}
        
        # Initialize components in correct order
        self._setup_components()
        
        # Apply OS-level settings on boot
        self.apply_console_visibility()
    
    def _setup_components(self):
        """Initialize UI component and backend services."""
        # Instantiate Haptic Engine (now owns its own state)
        self.haptic_engine = HapticEngine(self.thread_queue)

        # Initialize standalone OSC routing engine
        self.motor_router = MotorRouter()
        # Restore any persisted speed-blend tuning (kept in app settings so
        # we can tweak the math at runtime via the debug spinboxes without
        # editing source). Missing keys fall back to MotorRouter defaults.
        self._apply_saved_speed_tuning()

        # SteamVR Haptics — independent pipeline that shares the parameter_store
        # but targets SteamVR trackers via OpenVR.
        self.steamvr_engine = SteamVREngine(
            get_tracker_config=self._steamvr_get_tracker_config,
            get_pattern_configs=self._steamvr_get_pattern_configs,
            get_no_data_config=self._steamvr_get_no_data,
        )
        self.steamvr_router = SteamVRRouter(
            engine=self.steamvr_engine,
            get_all_configs=self._steamvr_get_all_tracker_configs,
        )
        self.steamvr_battery = SteamVRBatteryBroadcaster(
            engine=self.steamvr_engine,
            get_all_configs=self._steamvr_get_all_tracker_configs,
            send_osc=self._steamvr_send_osc,
            poll_interval_s=self._steamvr_get_battery_interval(),
            get_auto_connect=self._steamvr_get_auto_connect,
        )

        # bHaptics integration — independent pipeline that shares the
        # parameter_store and translates v1 bHapticsOSC bool params into
        # dot-mode frames sent to the bHaptics Player over WebSocket.
        bs = self.profile_manager.bhaptics_settings
        self.bhaptics_engine = BHapticsEngine(host=bs.get_host(), port=bs.get_port())
        self.bhaptics_engine.set_auto_connect_getter(self._bhaptics_get_auto_connect)
        # Re-publish bhaptics devices into the SteamVR strip whenever the
        # Player connects/disconnects or its connected-position set changes.
        # Routed through the queue so the bridge update happens on the main
        # thread, matching how Lovense device-changed events flow.
        self.bhaptics_engine.set_state_callback(
            lambda: self.thread_queue.put(("bhaptics_state_changed", None))
        )
        self.bhaptics_router = BHapticsRouter(
            engine=self.bhaptics_engine,
            get_device_configs=self._bhaptics_get_device_configs,
            get_antistuck=self._bhaptics_get_antistuck,
        )

        # Hardware Monitor — broadcasts system stats (CPU/RAM/GPU/VRAM) to
        # VRChat over OSC. Off by default; opt-in via the Hardware Monitor
        # panel. Runs its own poll thread and never touches the UI directly.
        self.hardware_monitor = HardwareMonitorEngine(
            get_config=self._hardware_monitor_get_config,
            send_osc=self._hardware_monitor_send_osc,
        )

        # Instantiate VRChat OSC Manager
        bind_all = self.profile_manager.app_settings.settings.get("bind_all_interfaces", True)
        self.osc_manager = VRChatOSCManager(local_listen_port=0, bind_all_interfaces=bind_all)

        # Link our router to the global OSC callback
        self.osc_manager.global_osc_callback = self.on_osc_message

        # Connection hook - push to queue for thread-safe UI update
        self.osc_manager.on_connected = lambda ports: self.thread_queue.put(
            ("osc_status", (True, ports.get("local_listen_port")))
        )
        # Disconnect hook (mDNS removal or health-check failure) -- routes the
        # same queue message so the UI/log path is symmetric.
        self.osc_manager.on_disconnected = lambda: self.thread_queue.put(
            ("osc_status", (False, self.osc_manager.local_listen_port if self.osc_manager else None))
        )
        
        # Load profiles using profile manager (also initializes app_settings)
        self.profile_manager.load_profiles()
        
        # Load app settings (auto_connect, auto_refresh)
        self.auto_refresh_enabled = self.profile_manager.app_settings.get("auto_refresh", True)
        self.auto_connect_enabled = self.profile_manager.app_settings.get("auto_connect", True)
        
        # SteamVR virtual-toy-device feature — must be initialised BEFORE
        # the UI is constructed, because the Settings tab queries
        # `get_steamvr_toys_status()` while building the SteamVR card.
        # The facade no-ops the bridge/install steps when the user hasn't
        # enabled the feature, so it's cheap to call unconditionally.
        try:
            self._steamvr_toys_init()
        except Exception as e:
            print(f"[steamvr-toys] init failed: {e}")

        # Instantiate UI Component (must be after haptic_engine is created).
        # The UI owns its own root window so this controller stays
        # framework-agnostic.
        self.ui = OscGoesPurrrUI(self)
        # Now that the UI exists, let the SteamVR-toys bridge log through it.
        try:
            self._steamvr_toys_attach_ui()
        except Exception:
            pass

        # Push window-chrome settings through the UI facade.
        self.ui.set_title(f"{APP_NAME} - v{__version__}")
        saved_geometry = self.profile_manager.app_settings.settings.get(
            "window_geometry", WINDOW_GEOMETRY
        )
        self.ui.set_geometry(saved_geometry)

        # Build stored devices UI after loading profiles
        self.ui.build_stored_devices_ui()
    
    def start_async_loop(self):
        """Start the asyncio event loop in a separate thread"""
        def run_loop():
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            self.async_loop = loop
            # Tell the main thread the loop is ready; `run()` waits on this
            # instead of polling-sleeping until self.async_loop becomes non-None.
            self._loop_ready.set()

            try:
                # Run the haptic engine async worker (main hardware loop)
                loop.run_until_complete(self.haptic_engine.async_worker())
            finally:
                loop.close()

        # Start async thread
        self.async_thread = threading.Thread(target=run_loop, daemon=True)
        self.async_thread.start()
    
    # Cap how many queue messages we drain per tick. Under an OSC storm this
    # keeps the UI thread responsive — anything not drained this tick gets
    # picked up on the next 100 ms poll.
    _QUEUE_BATCH_CAP = 500

    def process_async_queue(self):
        """Process messages from queue (called from main thread).

        Drains up to `_QUEUE_BATCH_CAP` messages per tick. Consecutive
        `osc_haptic_update` messages for the same `(device, motor)` are
        coalesced — only the most recent target value matters for hardware,
        so we drop the stale ones and dispatch a single command per motor.
        """
        # Collect-and-coalesce phase. We need to preserve relative order of
        # non-haptic events, so haptic updates land in a side dict keyed by
        # (device, motor) and replay at the end. Sequence preservation matters
        # for stuff like `connection_status` → `devices_found`.
        try:
            haptic_latest: Dict[tuple, tuple] = {}
            ordered_events: List[tuple] = []
            drained = 0
            while drained < self._QUEUE_BATCH_CAP:
                msg = self.thread_queue.get_nowait()
                drained += 1
                if isinstance(msg, tuple) and len(msg) == 2 and msg[0] == "osc_haptic_update":
                    device_name, val_float, motor_index = msg[1]
                    haptic_latest[(device_name, motor_index)] = (device_name, val_float, motor_index)
                    continue
                ordered_events.append(msg)
        except queue.Empty:
            pass

        for msg in ordered_events:
            if not isinstance(msg, tuple):
                continue
            msg_type, data = msg

            if msg_type == "ui_update":
                self.ui.log_message(data)
            elif msg_type == "connection_status":
                connected, server = data
                # Route through the controller method (NOT directly to UI) --
                # the controller method is what restarts the auto-reconnect
                # loop when `connected` is False. Calling self.ui directly
                # only repainted the status label and left the engine state
                # in limbo with no retries.
                self.update_connection_status(connected, server)
            elif msg_type == "devices_found":
                # Update the global known-toys registry so future
                # empty profiles still see these toys.
                for _info in (data.values() if isinstance(data, dict) else []):
                    if isinstance(_info, dict):
                        self.profile_manager.known_devices.register(
                            _info.get("name", ""),
                            int(_info.get("motor_count", 1)),
                            _info.get("motor_kinds"),
                        )
                self.ui.build_device_list_ui(data)
                self._sync_linear_configs(data)
                # Re-evaluate the green-check vs yellow-warning icons on
                # every stored device frame so reconnects flip back to
                # connected immediately.
                self.ui.update_stored_devices_ui()
                # Mirror the new device list into the SteamVR toy driver
                # (no-op when the feature is disabled).
                try:
                    self.steamvr_toys_on_devices_changed()
                except Exception as e:
                    self.log_message(f"[steamvr-toys] sync failed: {e}")
            elif msg_type == "battery_update":
                try:
                    self._battery_cache[data["device_name"]] = float(data["level"])
                except (TypeError, ValueError):
                    pass
                self.ui.update_battery_label(data["device_name"], data["level"])
                # Push the same value into the Simple Mode panel if it
                # exposes a hook for live battery refresh.
                if hasattr(self.ui, "update_simple_mode_battery"):
                    self.ui.update_simple_mode_battery(data["device_name"], data["level"])
                try:
                    self.steamvr_toys_on_battery(data["device_name"], data["level"])
                except Exception:
                    pass
            elif msg_type == "device_removed":
                device_name = data
                self.log_message(f"Toy disconnected: {device_name}")
                # Frame stays (the device is "stored"); just flip its
                # connection-status icon from green to yellow.
                self.ui.update_stored_devices_ui()
                try:
                    self.steamvr_toys_on_devices_changed()
                except Exception:
                    pass
            elif msg_type == "bhaptics_state_changed":
                # bHaptics engine reported a connection-state or
                # connected-positions change. Mirror it into the SteamVR
                # device strip (no-op when the SteamVR toy feature is off)
                # AND push the user-configured connection bool to VRChat
                # so an avatar animation can react.
                try:
                    self.steamvr_toys_on_bhaptics_state_changed()
                except Exception:
                    pass
                try:
                    self._bhaptics_send_connected_bool()
                except Exception:
                    pass
            elif msg_type == "stored_devices_refresh":
                self.ui.build_stored_devices_ui()
            elif msg_type == "osc_status":
                is_connected, port = data
                self.ui.update_osc_status(is_connected, port)
                if is_connected:
                    self.ui.log_message(f"VRChat OSC Connected! Listening on port {port}")
                    # Dump full diagnostics on every connect so the user has
                    # a clean baseline (which ports were chosen, etc.) in the
                    # log when a future silent-connection failure happens.
                    try:
                        diag = self.osc_manager.get_diagnostics() if self.osc_manager else {}
                        self.ui.log_message(
                            f"OSC diag: our_listen={diag.get('our_listen_port')} "
                            f"our_http={diag.get('our_http_phonebook_port')} "
                            f"vrc_http={diag.get('vrc_http_port')} "
                            f"vrc_osc={diag.get('vrc_osc_port')} "
                            f"udp_socket={diag.get('udp_socket_bound')}"
                        )
                    except Exception:
                        pass
                    # /avatar/change fires only when the avatar loads.
                    # If we connected mid-session we'll never see it,
                    # so probe the OSCQuery HTTP node for the current
                    # value as soon as the OSCQuery handshake settles.
                    self._schedule_avatar_id_probe()
                    # Re-push the bHaptics connection bool — VRChat just
                    # came back, so its avatar parameter cache no longer
                    # reflects whatever we sent during the prior session.
                    try:
                        self._bhaptics_send_connected_bool()
                    except Exception:
                        pass
                else:
                    self.ui.log_message("VRChat OSC Disconnected. Waiting for VRChat to come back...")
                    # Dump diagnostics so we can see whether packets ever
                    # arrived this session.
                    try:
                        diag = self.osc_manager.get_diagnostics() if self.osc_manager else {}
                        self.ui.log_message(
                            f"OSC diag at disconnect: packets_handled={diag.get('packets_handled')} "
                            f"phonebook_GETs={diag.get('phonebook_GETs')} "
                            f"handler_exc={diag.get('handler_exceptions')} "
                            f"session_age_s={diag.get('session_age_s')}"
                        )
                    except Exception:
                        pass
            elif msg_type == "ui_slider_update":
                device_name, value, motor_idx = data
                self._is_updating_ui = True  # Lock the UI to prevent echo loops
                try:
                    # Tell the UI to handle its own widgets
                    self.ui.update_device_visuals(device_name, motor_idx, value)
                finally:
                    self._is_updating_ui = False  # Unlock
            elif msg_type == "avatar_change":
                self._on_avatar_change(data)

        # Dispatch the coalesced haptic targets last — one command per motor
        # carrying the freshest value.
        for device_name, val_float, motor_index in haptic_latest.values():
            self.update_device_target(device_name, val_float, motor_index)
    
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        self.ui.log_message(message)
    
    def save_all_profiles(self):
        """Persist all profiles. Per-motor addresses are kept up-to-date in the
        profile dict on every UI add/remove, so this just flushes to disk and
        ensures every device has at least one default address."""
        for device_name in self.ui.get_known_device_names():
            existing = self.get_profile_config(device_name, "osc_addresses", None)
            if not existing:
                default_addr = device_name.replace(" ", "_")
                self.update_device_config(device_name, "osc_addresses", {"0": [default_addr]})
        self.save_profiles()
        self.log_message("All device profiles saved")
    
    def update_connection_status(self, connected: bool, server: str):
        """Update connection UI elements (main thread only)"""
        # Sync with haptic engine (haptic_engine.is_connected is now the single source of truth)
        if self.haptic_engine:
            self.haptic_engine.mark_connected(connected)
        
        # Update UI via ui component
        self.ui.update_connection_status(connected, server)
        
        # If auto-connect is enabled and we just disconnected, restart the retry loop
        if not connected and self.auto_connect_enabled and self.async_loop:
            try:
                self._auto_connect_task = asyncio.run_coroutine_threadsafe(
                    self._async_auto_connect_loop(),
                    self.async_loop
                )
            except Exception as e:
                self.log_message(f"Auto-reconnect restart failed: {e}")
    
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
            # If not connected, start the retry loop
            if not self.haptic_engine.is_connected and self.async_loop:
                try:
                    self._auto_connect_task = asyncio.run_coroutine_threadsafe(
                        self._async_auto_connect_loop(),
                        self.async_loop
                    )
                except Exception as e:
                    self.log_message(f"Failed to start auto connect: {e}")
    
    async def _async_attempt_connection(self):
        """Attempt to connect to Intiface once. Returns True if successful."""
        try:
            await self.haptic_engine.async_connect()
            return True
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
    
    def get_connected_device_names(self) -> set:
        """Get set of currently connected device names"""
        if not self.haptic_engine:
            return set()
        return set(self.haptic_engine.list_connected_device_names())
    
    # ====================
    # Facade Methods
    # Delegate to subordinate components to provide a clean single-entry API.
    # ====================

    def apply_console_visibility(self):
        """Applies the current console visibility setting via OS utilities."""
        show_console = not self.get_app_setting("hide_console", True)
        toggle_windows_console(show_console)

    def update_stored_devices_ui(self):
        """Update the stored devices UI to show connection status"""
        self.ui.update_stored_devices_ui()
    
    def delete_stored_device(self, device_name: str):
        """Forget a toy entirely — removes it from every profile and the
        global known-toys registry. The card will not reappear on profile
        switch. To use this toy again, reconnect it."""
        for source in (self.profile_manager.profiles,
                       self.profile_manager.avatar_profiles):
            for profile in source.values():
                if isinstance(profile, dict) and device_name in profile:
                    del profile[device_name]
        self.save_profiles()
        self.profile_manager.known_devices.forget(device_name)

        # Remove from UI via the framework-agnostic facade
        self.ui.remove_device_frame(device_name)

        self.log_message(f"Deleted stored toy: {device_name}")
    
    def build_stored_devices_ui(self):
        """Build the UI for all stored devices from profiles"""
        self.ui.build_stored_devices_ui()
    
    def build_device_list_ui(self, devices_dict: dict):
        """Build dynamic UI controls for each discovered device"""
        self.ui.build_device_list_ui(devices_dict)
    
    def get_profile_config(self, device_name: str, key: str, default=None):
        """Get a specific config value for a device from current profile using profile_manager"""
        return self.profile_manager.get_profile_config(device_name, key, default)
    
    def get_app_setting(self, key: str, default: Any = None):
        """Facade method for UI to safely read app settings."""
        if hasattr(self.profile_manager.app_settings, 'get'):
            return self.profile_manager.app_settings.get(key, default)
        return self.profile_manager.app_settings.settings.get(key, default)
    
    def set_app_setting(self, key: str, value: Any):
        """Facade method for UI to safely update app settings."""
        self.profile_manager.app_settings.set(key, value)

    # ------------------------------------------------------------------
    # Speed-blend tuning facade (UI debug knobs)
    # ------------------------------------------------------------------

    def _apply_saved_speed_tuning(self) -> None:
        if not hasattr(self, "motor_router"):
            return
        overrides = {}
        for key in self.motor_router.SPEED_TUNING_KEYS:
            saved = self.get_app_setting(key, None)
            if saved is not None:
                overrides[key] = saved
        if overrides:
            self.motor_router.apply_speed_tuning(**overrides)

    def get_speed_tuning(self) -> Dict[str, float]:
        """Snapshot of the live speed-blend tuning values, for UI display."""
        if not hasattr(self, "motor_router"):
            return {}
        return self.motor_router.get_speed_tuning()

    def set_speed_tuning_value(self, key: str, value: float) -> Dict[str, float]:
        """Update one tuning knob, persist it, and re-evaluate so the change
        is audible immediately. Returns the clamped snapshot so the UI can
        show the actually-applied value if it differs from the user's input.
        """
        if not hasattr(self, "motor_router"):
            return {}
        snapshot = self.motor_router.apply_speed_tuning(**{key: value})
        # Persist the post-clamp value so a stale UI input never resurrects
        # on the next launch.
        self.set_app_setting(key, snapshot.get(key, value))
        if hasattr(self, "force_recalculate"):
            self.force_recalculate()
        return snapshot

    def reset_speed_tuning(self) -> Dict[str, float]:
        """Revert every speed-blend tuning knob to the MotorRouter factory
        defaults, persist them, and force a recalc so the next tick uses the
        fresh values. Returns the applied snapshot for the UI."""
        if not hasattr(self, "motor_router"):
            return {}
        defaults = self.motor_router.get_speed_tuning_defaults()
        snapshot = self.motor_router.apply_speed_tuning(**defaults)
        for key, value in snapshot.items():
            self.set_app_setting(key, value)
        if hasattr(self, "force_recalculate"):
            self.force_recalculate()
        return snapshot

    # ==================================================================
    # Feature toggles — Settings → Features panel uses these to gate the
    # expensive background subsystems (bHaptics, Hardware Monitor, SteamVR
    # haptics/battery, OSC Inspector). Each toggle starts/stops the matching
    # engine so disabled features actually free their threads.
    # ==================================================================

    FEATURE_KEYS = (
        "feature_osc_inspector",
        "feature_bhaptics",
        "feature_hardware_monitor",
        "feature_steamvr_haptics",
        "feature_steamvr_battery",
        "feature_intiface",
    )

    def get_feature_enabled(self, key: str) -> bool:
        return bool(self.get_app_setting(key, True))

    def get_feature_flags(self) -> Dict[str, bool]:
        return {k: self.get_feature_enabled(k) for k in self.FEATURE_KEYS}

    def set_feature_enabled(self, key: str, enabled: bool) -> None:
        enabled = bool(enabled)
        self.set_app_setting(key, enabled)
        try:
            self._apply_feature_state(key, enabled)
        except Exception as e:
            self.log_message(f"Feature toggle '{key}' apply error: {e}")
        # Sync the sidebar visibility so disabled features hide their nav entry.
        if self.ui is not None:
            try:
                self.ui.apply_feature_visibility()
            except Exception:
                pass

    def _apply_feature_state(self, key: str, enabled: bool) -> None:
        """Start or stop the background subsystem behind a feature toggle."""
        if key == "feature_bhaptics":
            if enabled:
                try:
                    self.bhaptics_engine.start()
                    self.bhaptics_router.start()
                except Exception as e:
                    self.log_message(f"bHaptics start failed: {e}")
            else:
                try:
                    self.bhaptics_router.stop()
                    self.bhaptics_engine.stop()
                except Exception:
                    pass
        elif key == "feature_hardware_monitor":
            if enabled:
                try:
                    self.hardware_monitor.start()
                except Exception as e:
                    self.log_message(f"Hardware monitor start failed: {e}")
            else:
                try:
                    self.hardware_monitor.stop()
                except Exception:
                    pass
        elif key == "feature_steamvr_haptics":
            if enabled:
                try:
                    self.steamvr_router.start()
                except Exception as e:
                    self.log_message(f"SteamVR haptics start failed: {e}")
            else:
                try:
                    self.steamvr_router.stop()
                except Exception:
                    pass
        elif key == "feature_steamvr_battery":
            if enabled:
                try:
                    self.steamvr_battery.start()
                except Exception as e:
                    self.log_message(f"SteamVR battery start failed: {e}")
            else:
                try:
                    self.steamvr_battery.stop()
                except Exception:
                    pass
        elif key == "feature_osc_inspector":
            # Pure UI / debug feature — refresh loop checks the flag itself.
            pass
        elif key == "feature_intiface":
            # Intiface toy communication. Turning it off disconnects any
            # active session and the auto-connect loop short-circuits on the
            # flag, so no reconnection happens until the user re-enables it.
            if enabled:
                if (self.auto_connect_enabled
                        and self.haptic_engine
                        and not self.haptic_engine.is_connected
                        and self.async_loop):
                    try:
                        self._auto_connect_task = asyncio.run_coroutine_threadsafe(
                            self._async_auto_connect_loop(),
                            self.async_loop,
                        )
                    except Exception as e:
                        self.log_message(f"Intiface auto-connect restart failed: {e}")
            else:
                if (self.haptic_engine
                        and self.haptic_engine.is_connected
                        and self.async_loop):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.haptic_engine.async_disconnect(),
                            self.async_loop,
                        )
                    except Exception as e:
                        self.log_message(f"Intiface disconnect failed: {e}")
    
    def get_detected_zones(self) -> Dict[str, List[str]]:
        """Facade method for UI to safely read detected zones from the Central Store."""
        return store.get_detected_zones()

    def get_osc_diagnostics(self) -> Dict[str, Any]:
        """Facade: dump VRChat OSC manager diagnostics. Empty dict when the
        manager isn't running yet. UI panels (or the user manually triggering
        a dump) can show this to debug the 'connected but silent' failure."""
        if not getattr(self, "osc_manager", None):
            return {}
        try:
            return self.osc_manager.get_diagnostics()
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    def log_osc_diagnostics(self) -> None:
        """Dump the OSC diagnostics dict to the in-app log on demand.
        Useful while reproducing the silent-connection bug."""
        diag = self.get_osc_diagnostics()
        if not diag:
            self.log_message("OSC diag: manager not running")
            return
        self.log_message(
            "OSC diag: " + ", ".join(f"{k}={v}" for k, v in diag.items())
        )

    def get_osc_event_log(self) -> List[str]:
        """Facade: snapshot of the OSC manager's event ring buffer."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            return []
        try:
            return mgr.get_event_log()
        except Exception:
            return []

    def get_osc_other_clients(self) -> Dict[str, Dict[str, Any]]:
        """Facade: which non-VRChat OSCQuery clients have we seen this session."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            return {}
        try:
            return mgr.get_other_clients()
        except Exception:
            return {}

    def force_osc_rehandshake(self) -> None:
        """Facade: manually fire a re-poll of VRChat's OSCQuery endpoint and
        a fresh handshake ping. Wired to the 'Force re-handshake' button on
        the OSC Diagnostics panel — try this when packets stop flowing and
        you don't want to flip Disconnect/Connect to test if VRChat will
        resume sending."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            self.log_message("Force re-handshake: OSC manager not running")
            return
        self.log_message("Force re-handshake: re-polling VRChat OSCQuery...")
        try:
            mgr._reprobe_silent_connection()
        except Exception as e:
            self.log_message(f"Force re-handshake failed: {type(e).__name__}: {e}")

    def force_osc_reregister_mdns(self) -> None:
        """Facade: rip our mDNS advertisement and re-publish under a fresh
        unique name. The strongest non-destructive recovery for the
        'connected but silent' bug — forces VRChat's OSCQuery client cache
        to enumerate us as a brand-new client and re-query our phonebook.
        Wired to the 'Re-publish mDNS' button on the Diagnostics panel."""
        mgr = getattr(self, "osc_manager", None)
        if mgr is None:
            self.log_message("Re-publish mDNS: OSC manager not running")
            return
        self.log_message("Re-publish mDNS: unregistering and re-advertising under a fresh name...")
        try:
            ok = mgr.reregister_mdns()
            if ok:
                self.log_message("Re-publish mDNS: done. Wait ~5s for VRChat to re-query us.")
            else:
                self.log_message("Re-publish mDNS: completed with errors — see OSC Diagnostics log.")
        except Exception as e:
            self.log_message(f"Re-publish mDNS failed: {type(e).__name__}: {e}")

    def open_osc_log_folder(self) -> None:
        """Facade: open the directory containing the persistent OSC log file
        in the system file explorer. Wired to the 'Open log folder' button."""
        mgr = getattr(self, "osc_manager", None)
        path = mgr.get_log_file_path() if mgr is not None else None
        if not path:
            self.log_message("Open log folder: no log path available (appdata denied?)")
            return
        try:
            import os as _os
            import subprocess as _subp
            folder = _os.path.dirname(path)
            self.log_message(f"OSC log file: {path}")
            if _os.name == "nt":
                _os.startfile(folder)  # type: ignore[attr-defined]
            else:
                # Fallback for non-Windows; this app targets Windows but
                # keep it from crashing if someone runs it elsewhere.
                _subp.Popen(["xdg-open", folder])
        except Exception as e:
            self.log_message(f"Open log folder failed: {type(e).__name__}: {e}")
    
    def update_device_config(self, device_name: str, key: str, value):
        """Update a config value for a device in current profile using profile_manager"""
        self.profile_manager.update_device_config(device_name, key, value)
    
    def on_osc_message(self, address: str, value):
        """Acts as a trigger ping when new UDP data arrives. Sets a flag to batch rapid updates."""
        self._needs_recalculation = True
        # VRChat reports the freshly-loaded avatar's ID via /avatar/change.
        # The OSC layer strips the leading slash, so we see "avatar/change".
        if address == "avatar/change":
            self.thread_queue.put(("avatar_change", str(value) if value is not None else ""))

    def force_recalculate(self):
        """Forces the router to recalculate output based on current state and new UI configs.

        Reads from whichever profile the manager considers *active* — an avatar
        profile when the current VRChat avatar has one bound, otherwise the
        selected global profile. In Simple Mode, profile config is bypassed
        and every connected motor gets the same global SPS max value.
        """
        if not (hasattr(self, 'motor_router') and hasattr(self, 'osc_manager')):
            return
        params, _version, zones = store.snapshot()
        if self.get_app_setting("simple_mode", False):
            motor_counts = self.get_device_motor_counts()
            blend = self.get_app_setting("simple_mode_speed_blend", 0.0)
            updates = self.motor_router.reevaluate_simple_mode(
                motor_counts, params, zones=zones, speed_blend=blend
            )
        else:
            active = self.profile_manager.get_active_profile_dict()
            if active is None:
                return
            updates = self.motor_router.reevaluate_state(active, params, zones=zones)
        for device_name, target_val, motor_idx in updates:
            self.thread_queue.put(("osc_haptic_update", (device_name, target_val, motor_idx)))

    def sync_motor_to_filters(self, device_name: str, motor_idx: int):
        """Recalculate the max value for a motor based on the live shadow state and filter checkboxes.

        Used when user toggles a checkbox to immediately stop output if all interaction types are blocked.
        With the stateless router, this just triggers a full recalculation against the shadow state.
        """
        self.force_recalculate()

    def toggle_osc_debugger(self, *args):
        """Toggle the OSC debugger on/off (accepts *args for safe UI toggle compatibility)"""
        self.is_debugging_osc = not self.is_debugging_osc
        if self.is_debugging_osc:
            self.ui.log_message("OSC Debugger Started")
        else:
            self.ui.log_message("OSC Debugger Stopped")
        
        # Update button appearance to reflect current state
        self.ui.update_osc_debugger_button(self.is_debugging_osc)

    def refresh_debugger_ui(self):
        """Refresh the debugger display at 10Hz (100ms intervals)"""
        # Update SPS Zones Status
        if hasattr(self, 'osc_manager'):
            fresh_zones = store.get_detected_zones()
            orifices = fresh_zones.get("Orifices", [])
            penetrators = fresh_zones.get("Penetrators", [])

            # Create a simple state tracker
            current_state = orifices + penetrators

            # Only update UI if the zones have actually changed to avoid flickering
            if not hasattr(self, '_last_detected_zones') or self._last_detected_zones != current_state:
                self._last_detected_zones = current_state

                # Update text with proper newlines
                sps_text = f"Orifices: {', '.join(orifices) if orifices else 'None'}\n\nPenetrators: {', '.join(penetrators) if penetrators else 'None'}"
                self.ui.update_sps_status(sps_text)

        if getattr(self, 'is_debugging_osc', False) and hasattr(self, 'osc_manager'):
            # Get search filter
            search_query = self.ui.get_osc_search_query()

            lines = []  # list of (addr_prefix, val_str, hex_color) triplets
            # Sort alphabetically, using Central Store for thread-safe data
            for addr, val in sorted(store.get_all_parameters().items()):
                if search_query in addr.lower():
                    # Cleanly format floats to 4 decimal places, leave bools/ints alone
                    if isinstance(val, float):
                        val_str = f"{val:.4f}"
                    else:
                        val_str = str(val)

                    color = value_to_hex_color(val)
                    lines.append((addr, val_str, color))

            if not lines and search_query:
                debug_data = [("No parameters match your search.", "", COLOR_TEXT_MUTED)]
            elif not lines:
                debug_data = [("Waiting for OSC data...", "", COLOR_TEXT_MUTED)]
            else:
                debug_data = lines

            # Push to the UI as a list of (text, color) tuples
            self.ui.update_debugger_display(debug_data)

        # Refresh the Simple Mode panel on the same cadence so newly connected
        # toys, fresh battery readings and zone changes appear without waiting
        # for a hard rebuild.
        if hasattr(self.ui, "refresh_simple_mode_view"):
            self.ui.refresh_simple_mode_view()
        # The diagnostics panel self-skips when it isn't the active view,
        # so this is cheap when the user is elsewhere.
        if hasattr(self.ui, "refresh_osc_diagnostics_view"):
            self.ui.refresh_osc_diagnostics_view()

        # Schedule the next refresh (Throttled to save UI thread)
        self.ui.schedule_callback(UI_REFRESH_RATE_MS, self.refresh_debugger_ui)

    def get_device_motor_counts(self) -> dict:
        """Facade method to get motor counts safely from the hardware engine."""
        if not self.haptic_engine:
            return {}
        return self.haptic_engine.get_motor_count_map()

    def update_linear_motor_config(self, device_name: str, motor_idx: int) -> None:
        """Facade: read the persisted mode/idle settings for one motor and forward
        them to the HapticEngine. Called by the UI when the user toggles the
        per-motor Mode or Idle control, and by `_sync_linear_configs` on connect.
        """
        if not self.haptic_engine:
            return
        mode = self.profile_manager.get_profile_config(
            device_name, f"motor_{motor_idx}_linear_mode", "position"
        )
        idle = self.profile_manager.get_profile_config(
            device_name, f"motor_{motor_idx}_linear_idle", "rest"
        )
        self.haptic_engine.set_linear_config(device_name, motor_idx, mode=mode, idle=idle)

    def _sync_linear_configs(self, devices_dict: dict) -> None:
        """Push the persisted linear mode/idle setting for every motor on every
        freshly discovered device into the engine. Called once on `devices_found`
        so the engine starts with the right behavior even before the user touches
        the UI.
        """
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
                self.profile_manager.update_device_config(device_name, "motor_kinds", list(kinds))
            for motor_idx in range(motor_count):
                self.update_linear_motor_config(device_name, motor_idx)

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
            
        # Send the command safely to the Haptic Engine
        if self.haptic_engine:
            self.haptic_engine.update_target(device_name, motor_index, float(value))
        
        # Update the corresponding vibe meter via the UI facade
        self.ui.update_motor_vibe(device_name, motor_index, float(value))

    
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

    # ==================================================================
    # Simple Mode Facade
    # When enabled, every detected SPS source drives every connected toy
    # with no per-toy profile config. Toggle, source list and toy list are
    # surfaced through these methods so the UI never reaches into backend
    # state directly.
    # ==================================================================

    def get_simple_mode(self) -> bool:
        return bool(self.get_app_setting("simple_mode", False))

    def set_simple_mode(self, enabled: bool):
        enabled = bool(enabled)
        if self.get_simple_mode() == enabled:
            return
        self.set_app_setting("simple_mode", enabled)
        # Clear router debounce so the new mode's first tick actually emits
        # values instead of being silently filtered as "unchanged".
        if hasattr(self, "motor_router"):
            self.motor_router.reset_outputs()
        # When turning OFF, also send zeros to every motor so they don't
        # hang at the last simple-mode value.
        if not enabled and self.haptic_engine and self.haptic_engine.is_connected:
            for device_name, motor_count in self.get_device_motor_counts().items():
                for motor_idx in range(motor_count):
                    self.thread_queue.put(("osc_haptic_update", (device_name, 0.0, motor_idx)))
        self.log_message(f"Simple Mode {'enabled' if enabled else 'disabled'}")
        # Rebuild device cards: the Device Routing view is now mostly
        # decorative while Simple Mode is on, but no clear-out is needed.
        self.force_recalculate()

    def get_simple_mode_sources(self) -> Dict[str, List[str]]:
        """Live snapshot of detected SPS zones — {'Orifices': [...],
        'Penetrators': [...]}. Returns empty lists when no avatar is loaded."""
        params = store.get_all_parameters()
        orifices: set = set()
        penetrators: set = set()
        for path in params.keys():
            parts = path.split("/")
            if len(parts) >= 3 and parts[0] == "OGB":
                category = parts[1]
                zone_name = parts[2]
                if category in ("Orifice", "Orf"):
                    orifices.add(zone_name)
                elif category in ("Penetrator", "Pen"):
                    penetrators.add(zone_name)
        return {
            "Orifices": sorted(orifices),
            "Penetrators": sorted(penetrators),
        }

    def get_simple_mode_toys(self) -> List[Dict[str, Any]]:
        """Snapshot of connected toys for the Simple Mode panel.
        Each entry: {'name': str, 'motor_count': int, 'connected': bool}."""
        out: List[Dict[str, Any]] = []
        if not self.haptic_engine:
            return out
        motor_counts = self.haptic_engine.get_motor_count_map()
        for name in self.haptic_engine.list_connected_device_names():
            out.append({
                "name": name,
                "motor_count": int(motor_counts.get(name, 1)),
                "connected": True,
                "battery": self._battery_cache.get(name),
            })
        out.sort(key=lambda d: d["name"].lower())
        return out
    
    def toggle_network_bind(self, value: bool):
        """Handle network bind toggle from Settings UI."""
        self.profile_manager.app_settings.update_setting("bind_all_interfaces", value)
        self.ui.log_message("Network bind changed. PLEASE RESTART APP to apply.")

    def _seed_profile_with_known_devices(self, profile_name: str) -> None:
        """Make sure every known toy has a default entry in the given profile.

        This is what gives new/empty profiles the "remember my toys" behaviour
        — the user gets blank-but-present device cards to configure, rather
        than having to reconnect each toy to see it.
        """
        profile = self.profile_manager.profiles.setdefault(profile_name, {})
        known = self.profile_manager.known_devices.all()
        if not known:
            return
        added = []
        for name, meta in known.items():
            if name in profile:
                continue
            motor_count = int(meta.get("motor_count", 1))
            entry = {"motor_count": motor_count}
            if meta.get("motor_kinds"):
                entry["motor_kinds"] = list(meta["motor_kinds"])
            # Default per-motor OSC addresses match what build_device_list_ui
            # would seed for a freshly-discovered device.
            addrs = {}
            for i in range(motor_count):
                suffix = f"_{i}" if motor_count > 1 else ""
                addrs[str(i)] = [f"{name.replace(' ', '_')}{suffix}"]
            entry["osc_addresses"] = addrs
            profile[name] = entry
            added.append(name)
        if added:
            self.profile_manager.save_profiles()
            print(f"[profiles] seeded profile '{profile_name}' with {len(added)} known toy(s): {added}")

    def switch_profile(self, profile_name: str):
        """Switch to a different profile and reload the device UI.

        Auto-creates an empty profile if `profile_name` doesn't exist yet, so
        the four dashboard slots feel like real profile slots even before the
        user has saved anything to them.

        Args:
            profile_name: Name of the profile to switch to.
        """
        if profile_name not in self.profile_manager.profiles:
            self.profile_manager.profiles[profile_name] = {}
            self.profile_manager.save_profiles()
            self.log_message(f"Created new profile: {profile_name}")

        # Toys are global; profiles are pure settings overlays. Every profile
        # therefore has an entry for every known toy (default settings until
        # the user changes them). "Delete" is the explicit way to forget a toy
        # across all profiles — see delete_stored_device.
        self._seed_profile_with_known_devices(profile_name)

        self.profile_manager.current_profile = profile_name
        self.current_profile = profile_name
        # Remember this choice for the currently-loaded avatar (if any) so
        # the next time that avatar loads, this global stays selected
        # instead of auto-switching to a bound avatar profile.
        self.profile_manager.record_choice("global", profile_name)

        # Clear cached UI frames so build_stored_devices_ui doesn't short-circuit
        # and leave the previous profile's device cards on screen when the new
        # profile is empty.
        self.ui.clear_device_caches()

        self.ui.build_stored_devices_ui()
        if hasattr(self.ui, "_refresh_profile_buttons"):
            self.ui._refresh_profile_buttons()
        if hasattr(self, "force_recalculate"):
            self.force_recalculate()
        self.log_message(f"Switched to profile: {profile_name}")

        # Refresh the profile buttons on the Dashboard
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()
    
    def create_profile(self, base_name: str = "New Profile") -> str:
        """Create a fresh profile and return its name. If `base_name` is
        already taken, appends ' 2', ' 3', ... until a free name is found."""
        existing = set(self.profile_manager.profiles.keys())
        name = base_name
        n = 2
        while name in existing:
            name = f"{base_name} {n}"
            n += 1
        self.profile_manager.profiles[name] = {}
        self._seed_profile_with_known_devices(name)
        self.profile_manager.save_profiles()
        self.log_message(f"Created profile '{name}'")
        if hasattr(self.ui, "_refresh_profile_buttons"):
            self.ui._refresh_profile_buttons()
        return name

    def delete_profile(self, profile_name: str):
        """Delete a profile. Refuses to delete the last remaining profile.
        If the deleted profile is currently active, switches to another."""
        if profile_name not in self.profile_manager.profiles:
            return
        if len(self.profile_manager.profiles) <= 1:
            self.log_message("Cannot delete the only remaining profile.")
            return

        del self.profile_manager.profiles[profile_name]
        self.profile_manager.save_profiles()
        self.log_message(f"Deleted profile '{profile_name}'")

        if self.profile_manager.current_profile == profile_name:
            fallback = next(iter(self.profile_manager.profiles.keys()))
            self.switch_profile(fallback)
        elif hasattr(self.ui, "_refresh_profile_buttons"):
            self.ui._refresh_profile_buttons()

    def rename_profile(self, old_name: str, new_name: str):
        """Rename a profile, or create a new one if `old_name` is a placeholder
        slot (e.g. "Profile 3") that hasn't been used yet.

        Args:
            old_name: Current name of the profile (or placeholder slot name).
            new_name: New name for the profile.
        """
        new_name = new_name.strip()
        if not new_name:
            return
        if new_name in self.profile_manager.profiles and new_name != old_name:
            self.log_message(f"Cannot rename: profile '{new_name}' already exists.")
            return

        if old_name in self.profile_manager.profiles:
            data = self.profile_manager.profiles.pop(old_name)
            self.profile_manager.profiles[new_name] = data
            self.log_message(f"Renamed profile '{old_name}' to '{new_name}'")
        else:
            # Renaming an empty placeholder slot creates a fresh profile,
            # seeded with all previously-seen toys (default settings).
            self.profile_manager.profiles[new_name] = {}
            self._seed_profile_with_known_devices(new_name)
            self.log_message(f"Created profile '{new_name}'")

        self.profile_manager.save_profiles()

        if self.profile_manager.current_profile == old_name:
            self.profile_manager.current_profile = new_name
            self.current_profile = new_name

        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

    # ====================
    # Avatar profiles + clipboard (copy/paste)
    # ====================

    def _schedule_avatar_id_probe(self):
        """Spawn a short background poll that asks VRChat's OSCQuery server
        for the current avatar id. Posts an avatar_change queue message on
        success. Safe to call repeatedly — it's just a few HTTP GETs."""
        def _probe():
            import time as _t
            # OSCQuery mDNS discovery + JSON build can lag a couple of seconds
            # after OSC starts. Retry briefly so the user doesn't see "not
            # detected" on first launch.
            for attempt in range(6):
                if not self.osc_manager or not self.osc_manager.is_connected:
                    return
                avatar_id = self.osc_manager.query_avatar_id()
                if avatar_id:
                    self.thread_queue.put(("avatar_change", avatar_id))
                    return
                _t.sleep(1.0)
        threading.Thread(target=_probe, daemon=True).start()

    def _on_avatar_change(self, avatar_id: str):
        """Handle a fresh /avatar/change message from VRChat.

        If an avatar profile is bound to this id, it becomes the active
        profile silently — device cards rebuild against the new settings.
        Otherwise we keep the currently-selected global profile.
        """
        avatar_id = (avatar_id or "").strip()
        previously_active = self.profile_manager.get_active_profile_info()
        bound_name = self.profile_manager.set_current_avatar(avatar_id)
        now_active = self.profile_manager.get_active_profile_info()

        if previously_active != now_active:
            if now_active["kind"] == "avatar":
                self.log_message(
                    f"Avatar changed → activating avatar profile '{now_active['name']}'"
                )
            else:
                self.log_message(
                    f"Avatar changed → no bound profile, staying on global '{now_active['name']}'"
                )
            self.ui.clear_device_caches()
            self.ui.build_stored_devices_ui()
            self.force_recalculate()
        else:
            self.log_message(f"Avatar changed (id={avatar_id or 'unknown'})")

        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

        # Avatar swaps reset every avatar parameter on the VRChat side, so
        # the bHaptics-connected bool needs to be re-asserted whether or not
        # the engine state changed.
        try:
            self._bhaptics_send_connected_bool()
        except Exception:
            pass

    def get_current_avatar_id(self) -> str:
        return self.profile_manager.current_avatar_id or ""

    def get_active_profile_info(self) -> dict:
        """{"kind": "avatar"|"global", "name": str} — for UI display."""
        return self.profile_manager.get_active_profile_info()

    def get_avatar_profile_names(self) -> list:
        return list(self.profile_manager.avatar_profiles.keys())

    def get_avatar_binding(self, profile_name: str) -> str:
        return self.profile_manager.avatar_bindings.get(profile_name, "")

    def create_avatar_profile(self, base_name: str = "New Avatar Profile") -> str:
        """Create an avatar profile bound to the *current* avatar id and seeded
        from the currently-active profile's settings (per design decision).
        """
        active = self.profile_manager.get_active_profile_dict() or {}
        new_name = self.profile_manager.create_avatar_profile(
            base_name=base_name,
            avatar_id=self.profile_manager.current_avatar_id,
            copy_from=active,
        )
        self.log_message(f"Created avatar profile '{new_name}'")
        # The new profile is automatically bound to the current avatar (if any),
        # which makes it the active profile. Rebuild device cards so the user
        # sees the inherited settings under the new profile name.
        self.ui.clear_device_caches()
        self.ui.build_stored_devices_ui()
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()
        return new_name

    def delete_avatar_profile(self, name: str):
        if name not in self.profile_manager.avatar_profiles:
            return
        was_active = (self.profile_manager.get_active_profile_info()
                      == {"kind": "avatar", "name": name})
        self.profile_manager.delete_avatar_profile(name)
        self.log_message(f"Deleted avatar profile '{name}'")
        if was_active:
            self.ui.clear_device_caches()
            self.ui.build_stored_devices_ui()
            self.force_recalculate()
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

    def rename_avatar_profile(self, old: str, new: str):
        if self.profile_manager.rename_avatar_profile(old, new):
            self.log_message(f"Renamed avatar profile '{old}' → '{new}'")
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

    def bind_avatar_profile_to_current(self, name: str):
        """Bind `name` to the current avatar and record it as the user's
        remembered choice for that avatar."""
        self.profile_manager.bind_avatar_profile(
            name, self.profile_manager.current_avatar_id
        )
        self.log_message(
            f"Bound avatar profile '{name}' to "
            f"{self.profile_manager.current_avatar_id or 'no avatar'}"
        )
        self.ui.clear_device_caches()
        self.ui.build_stored_devices_ui()
        self.force_recalculate()
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

    def copy_profile(self, kind: str, name: str):
        """Copy a profile into the in-memory clipboard. `kind` is 'global'|'avatar'."""
        ok = self.profile_manager.copy_profile_to_clipboard(kind, name)
        if ok:
            self.log_message(f"Copied {kind} profile '{name}' to clipboard")
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

    def paste_profile(self, target_kind: str):
        """Paste the clipboard into a new profile in the target section."""
        bind_avatar = self.profile_manager.current_avatar_id if target_kind == "avatar" else None
        name = self.profile_manager.paste_profile(target_kind, avatar_id=bind_avatar)
        if name:
            self.log_message(f"Pasted clipboard → new {target_kind} profile '{name}'")
            if target_kind == "avatar" and bind_avatar:
                self.ui.clear_device_caches()
                self.ui.build_stored_devices_ui()
                self.force_recalculate()
            if hasattr(self.ui, '_refresh_profile_buttons'):
                self.ui._refresh_profile_buttons()
        else:
            self.log_message("Paste failed — clipboard is empty")

    def paste_profile_into(self, target_kind: str, target_name: str):
        """Overwrite an existing profile with the current clipboard contents,
        then clear the clipboard so the row toggles back to Copy mode."""
        ok = self.profile_manager.paste_into_profile(target_kind, target_name)
        if not ok:
            self.log_message("Paste failed — clipboard empty or target missing")
            return
        self.profile_manager.clear_clipboard()
        self.log_message(
            f"Pasted clipboard onto {target_kind} profile '{target_name}'"
        )
        # If we just overwrote the currently-active profile, reapply it so
        # devices pick up the new settings immediately.
        active = self.profile_manager.get_active_profile_info() or {}
        if active.get("kind") == target_kind and active.get("name") == target_name:
            self.ui.clear_device_caches()
            self.ui.build_stored_devices_ui()
            self.force_recalculate()
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

    def clear_clipboard(self):
        """Cancel a pending copy — used when the user clicks the source row
        again to dismiss the paste-mode UI."""
        if not self.profile_manager.has_clipboard():
            return
        self.profile_manager.clear_clipboard()
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()

    def has_clipboard(self) -> bool:
        return self.profile_manager.has_clipboard()

    def get_clipboard_source_name(self) -> str:
        return self.profile_manager.get_clipboard_source_name() or ""

    def get_clipboard_source_kind(self) -> str:
        """Facade: which section ('global'|'avatar') the clipboard came from."""
        return self.profile_manager.get_clipboard_source_kind() or ""

    # ---- Profile-list facades (used by the UI to render rows) ----

    def get_global_profile_names(self) -> List[str]:
        """Facade: ordered list of every global profile's name."""
        return list(self.profile_manager.profiles.keys())

    def get_current_global_profile_name(self) -> str:
        """Facade: the global profile most recently selected by the user.
        Falls back to the resolver's active name if none is set."""
        return self.profile_manager.current_profile or ""

    def profile_exists(self, kind: str, name: str) -> bool:
        """Facade: True if a profile with this name exists in the given pool."""
        pool = (self.profile_manager.profiles if kind == "global"
                else self.profile_manager.avatar_profiles)
        return name in pool

    def get_active_profile_dict(self) -> Dict[str, Any]:
        """Facade: the live dict of per-device settings the router/UI read."""
        return self.profile_manager.get_active_profile_dict() or {}

    # ---- Haptic engine facades ----

    def set_haptic_connected(self, connected: bool) -> None:
        """Facade: keep the haptic engine's connection flag in sync with the
        VRChat OSC link. Setter-only so the UI never holds the object."""
        if hasattr(self, 'haptic_engine') and self.haptic_engine:
            self.haptic_engine.mark_connected(connected)

    def toggle_osc_connection(self):
        """Toggles the VRChat OSC connection on and off safely (non-blocking)."""
        if hasattr(self, 'osc_manager') and self.osc_manager and self.osc_manager.is_connected:
            # --- Disconnect Path ---
            self.log_message("Disconnecting VRChat OSC...")
            try:
                self.osc_manager.stop()
            except Exception:
                pass
            self.osc_manager.is_connected = False
            self.ui.update_osc_status(False)
        else:
            # --- Connect Path ---
            self.log_message("Starting VRChat OSC server...")
            self.ui.update_osc_status(False)  # Reset UI to waiting state
            
            # Rebuild manager for a clean socket state
            bind_all = self.profile_manager.app_settings.settings.get("bind_all_interfaces", True)
            self.osc_manager = VRChatOSCManager(local_listen_port=0, bind_all_interfaces=bind_all)
            self.osc_manager.global_osc_callback = self.on_osc_message
            self.osc_manager.on_connected = lambda ports: self.thread_queue.put(
                ("osc_status", (True, ports.get("local_listen_port")))
            )
            self.osc_manager.on_disconnected = lambda: self.thread_queue.put(
                ("osc_status", (False, self.osc_manager.local_listen_port if self.osc_manager else None))
            )
            
            # Run startup in a background thread to prevent UI lockup
            threading.Thread(target=self.osc_manager.start, daemon=True).start()

    def restart_osc(self):
        """Legacy wrapper: disconnect if connected, then reconnect via toggle."""
        if hasattr(self, 'osc_manager') and self.osc_manager and self.osc_manager.is_connected:
            try:
                self.osc_manager.stop()
            except Exception:
                pass
            self.osc_manager.is_connected = False
        self.toggle_osc_connection()

    def toggle_osc_auto_connect(self):
        """Handle OSC auto-connect checkbox toggle from UI"""
        if not self.ui.get_osc_auto_connect_enabled():
            # Checkbox unchecked - disable OSC auto connect
            self.profile_manager.app_settings.set("auto_connect_osc", False)
            self.log_message("VRChat OSC Auto connect disabled")
        else:
            # Checkbox checked - enable OSC auto connect
            self.profile_manager.app_settings.set("auto_connect_osc", True)
            self.log_message("VRChat OSC Auto connect enabled")
            # If OSC server is not running, start it
            if self.osc_manager:
                try:
                    self.osc_manager.start()
                except Exception:
                    pass  # Server may already be running
    
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
                
                # Start auto-refresh scanning loop if enabled
                if self.auto_refresh_enabled:
                    try:
                        self._auto_refresh_task = asyncio.run_coroutine_threadsafe(
                            self._async_auto_refresh_loop(),
                            self.async_loop
                        )
                    except Exception as e:
                        self.log_message(f"Failed to start auto refresh: {e}")
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
    
    def save_profiles(self):  # Facade -> profile_manager.save_profiles()
        self.profile_manager.save_profiles()

    def load_profiles(self) -> Dict[str, Any]:  # Facade -> profile_manager.load_profiles()
        return self.profile_manager.load_profiles()
    
    def _on_closing(self):
        """Handle window close event: either minimize to tray or fully quit."""
        if self.get_app_setting("minimize_to_tray", False):
            self.minimize_to_tray()
        else:
            self.quit_app()
            
    def minimize_to_tray(self):
        """Hides the UI and spawns the system tray icon in a background thread."""
        self.ui.hide_window()

        image = create_default_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Show OscGoesPurrr", self.restore_from_tray, default=True),
            pystray.MenuItem("Quit", self.quit_from_tray)
        )
        self.tray_icon = pystray.Icon("OscGoesPurrr", image, "OscGoesPurrr", menu)

        # pystray blocks, so we must run it in a daemon thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def restore_from_tray(self, icon, item):
        """Restores the UI from the system tray (thread-safe)."""
        icon.stop()
        self.ui.show_window()

    def quit_from_tray(self, icon, item):
        """Fully shuts down the app from the system tray (thread-safe)."""
        icon.stop()
        self.ui.schedule_on_main_thread(self.quit_app)

    def quit_app(self):
        """Executes the final, clean shutdown sequence."""
        self.log_message("Shutting down...")
        current_geometry = self.ui.get_geometry()
        if current_geometry:
            self.profile_manager.app_settings.update_setting("window_geometry", current_geometry)

        self.save_profiles()

        # Cleanly disconnect Intiface so its log doesn't show an abrupt
        # websocket drop and so it stops scanning when we leave. Best-effort
        # with a short timeout — daemon-killing the async thread on exit is
        # the safe fallback if something hangs.
        try:
            if (self.async_loop and self.haptic_engine
                    and self.haptic_engine.is_connected):
                future = asyncio.run_coroutine_threadsafe(
                    self.haptic_engine.async_disconnect(),
                    self.async_loop,
                )
                future.result(timeout=2.0)
        except Exception:
            pass

        try:
            self.steamvr_router.stop()
            self.steamvr_battery.stop()
            self.steamvr_engine.shutdown()
        except Exception:
            pass

        try:
            self.bhaptics_router.stop()
            self.bhaptics_engine.stop()
        except Exception:
            pass

        try:
            self.hardware_monitor.stop()
        except Exception:
            pass

        try:
            bridge = getattr(self, "_steamvr_toy_bridge", None)
            if bridge is not None:
                bridge.clear_devices()
                bridge.stop()
        except Exception:
            pass

        # Stop the VRChat OSC manager so its mDNS records are torn down and
        # its sockets released before the process exits. Cheap; the manager's
        # stop() is idempotent.
        try:
            mgr = getattr(self, "osc_manager", None)
            if mgr is not None:
                mgr.stop()
        except Exception:
            pass

        self.ui.shutdown()

    # Engine-specific facade methods live in `controllers/` mixin modules:
    #   - SteamVRFacade            (SteamVR haptics + battery)
    #   - BHapticsFacade           (bHaptics player dot grid)
    #   - HardwareMonitorFacade    (CPU/RAM/GPU OSC broadcaster)
    # The mixins assume `self.profile_manager`, the engine attributes, and
    # `self.osc_manager` exist on the host controller.

    def run(self):
        """Start the Three-Pillar application"""
        # Start async loop in background thread
        self.start_async_loop()

        # Wait for the worker thread to publish its event loop, with a timeout
        # so a stuck worker doesn't hang startup forever.
        if not self._loop_ready.wait(timeout=5.0):
            self.log_message("Async worker did not start within 5s; continuing anyway")

        # Start auto-connect if enabled (single source of truth is haptic_engine.is_connected).
        # Skip when the Intiface feature has been disabled in Settings → Features.
        if (self.auto_connect_enabled
                and self.get_feature_enabled("feature_intiface")
                and not self.haptic_engine.is_connected
                and self.async_loop):
            try:
                self._auto_connect_task = asyncio.run_coroutine_threadsafe(
                    self._async_auto_connect_loop(),
                    self.async_loop
                )
            except Exception as e:
                self.log_message(f"Failed to start auto connect: {e}")

        # Decoupled routing tick (Batches rapid OSC updates to max ~30Hz)
        def routing_tick():
            if getattr(self, '_needs_recalculation', False):
                self._needs_recalculation = False
                self.force_recalculate()
            self.ui.schedule_callback(ROUTER_POLL_RATE_MS, routing_tick)

        # Periodically check for UI updates from async thread
        def check_queue():
            self.process_async_queue()
            self.ui.schedule_callback(QUEUE_POLL_RATE_MS, check_queue)

        # Register clean shutdown handler to auto-save profiles
        self.ui.set_close_handler(self._on_closing)

        self.ui.schedule_callback(UI_REFRESH_RATE_MS, check_queue)

        # Start the routing tick loop
        self.ui.schedule_callback(ROUTER_POLL_RATE_MS, routing_tick)

        # Start SteamVR Haptics router. Engine init is deferred to first refresh
        # — the router itself is cheap and just polls the parameter store.
        # Each half (haptics / battery) is gated by its own feature toggle so
        # users who only want one side don't pay for the other.
        if self.get_feature_enabled("feature_steamvr_haptics"):
            try:
                self.steamvr_router.start()
            except Exception as e:
                self.log_message(f"SteamVR haptics router failed to start: {e}")
        if self.get_feature_enabled("feature_steamvr_battery"):
            try:
                self.steamvr_battery.start()
            except Exception as e:
                self.log_message(f"SteamVR battery broadcaster failed to start: {e}")

        # Start bHaptics engine + router. Engine's reconnect thread sits
        # idle when auto-connect is off.
        if self.get_feature_enabled("feature_bhaptics"):
            try:
                self.bhaptics_engine.start()
                self.bhaptics_router.start()
            except Exception as e:
                self.log_message(f"bHaptics startup failed: {e}")

        # Hardware monitor thread is gated by its feature toggle so the OSC
        # broadcast + polling thread don't run when the user has no use for it.
        if self.get_feature_enabled("feature_hardware_monitor"):
            try:
                self.hardware_monitor.start()
            except Exception as e:
                self.log_message(f"Hardware monitor startup failed: {e}")

        # Apply saved SteamVR autostart on boot (no-op if SteamVR is offline).
        if self.profile_manager.steamvr_settings.get_autostart():
            try:
                self.steamvr_engine.setup_autostart(True)
            except Exception:
                pass

        # If auto-connect is enabled, try an immediate refresh so the device
        # list populates without waiting for the first broadcaster tick.
        if self.profile_manager.steamvr_settings.get_auto_connect():
            try:
                self.steamvr_engine.refresh_devices(quiet=True)
            except Exception:
                pass

        # Boot OSC server 500ms after UI launches to prevent freezing
        if self.profile_manager.app_settings.settings.get("auto_connect_osc", True):
            self.ui.schedule_callback(OSC_BOOT_DELAY_MS, self.toggle_osc_connection)

        # Start the OSC debugger UI refresh loop
        self.refresh_debugger_ui()

        # Run GUI event loop on main thread
        self.ui.run()


if __name__ == "__main__":
    app = OscGoesPurrrApp()
    app.run()