# OscGoesPurrr - Main Orchestrator (The Traffic Cop)
# Architecture: 5-Part MVC Ecosystem
# 1. The Brain (parameter_store.py) - Central State Vault
# 2. The Eardrum (vrchat_osc.py) - Network Listener
# 3. The Muscle (haptic_engine.py) - Async Hardware Driver
# 4. The Face (ui_components.py) - Dumb View Layer
# 5. The Traffic Cop (main.py) - Controller & Event Router

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
from steamvr_engine import SteamVREngine, TrackerConfig as SteamVRTrackerConfig, PatternConfig as SteamVRPatternConfig
from steamvr_router import SteamVRRouter, SteamVRBatteryBroadcaster
from bhaptics_engine import BHapticsEngine, DeviceConfig as BHapticsDeviceConfig
from bhaptics_router import BHapticsRouter, device_table as bhaptics_device_table, display_name as bhaptics_display_name, grid_layout as bhaptics_grid_layout, detected_positions as bhaptics_detected_positions
from hardware_monitor import HardwareMonitorEngine
from constants import *
from utilities import value_to_hex_color, toggle_windows_console, create_default_icon
from version import __version__


class OscGoesPurrrApp:
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
        
        # Instantiate UI Component (must be after haptic_engine is created).
        # The UI owns its own root window so this controller stays
        # framework-agnostic.
        self.ui = OscGoesPurrrUI(self)

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
            
            try:
                # Run the haptic engine async worker (main hardware loop)
                loop.run_until_complete(self.haptic_engine.async_worker())
            finally:
                loop.close()
        
        # Start async thread
        self.async_thread = threading.Thread(target=run_loop, daemon=True)
        self.async_thread.start()
    
    def process_async_queue(self):
        """Process messages from queue (called from main thread)"""
        try:
            while True:
                msg = self.thread_queue.get_nowait()
                
                if isinstance(msg, tuple):
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
                    elif msg_type == "device_removed":
                        device_name = data
                        self.log_message(f"Toy disconnected: {device_name}")
                        # Frame stays (the device is "stored"); just flip its
                        # connection-status icon from green to yellow.
                        self.ui.update_stored_devices_ui()
                    elif msg_type == "stored_devices_refresh":
                        self.ui.build_stored_devices_ui()
                    elif msg_type == "osc_status":
                        is_connected, port = data
                        self.ui.update_osc_status(is_connected, port)
                        if is_connected:
                            self.ui.log_message(f"VRChat OSC Connected! Listening on port {port}")
                            # /avatar/change fires only when the avatar loads.
                            # If we connected mid-session we'll never see it,
                            # so probe the OSCQuery HTTP node for the current
                            # value as soon as the OSCQuery handshake settles.
                            self._schedule_avatar_id_probe()
                        else:
                            self.ui.log_message("VRChat OSC Disconnected. Waiting for VRChat to come back...")
                    elif msg_type == "osc_haptic_update":
                        device_name, val_float, motor_index = data
                        # This is now safely running on the Main UI thread!
                        self.update_device_target(device_name, val_float, motor_index)
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
                        
        except queue.Empty:
            pass  # No more messages in queue
    
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
            self.haptic_engine.is_connected = connected
        
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
                pass
    
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
            await self.haptic_engine._async_connect()
            return True
        except Exception as e:
            self.log_message(f"Connection attempt failed: {e}")
            return False
    
    async def _async_auto_connect_loop(self):
        """Background task that retries connection every 2 seconds"""
        while (self.auto_connect_enabled
               and self.get_feature_enabled("feature_intiface")
               and not self.haptic_engine.is_connected):
            await asyncio.sleep(2.0)
            if (self.auto_connect_enabled
                    and self.get_feature_enabled("feature_intiface")
                    and not self.haptic_engine.is_connected):
                try:
                    success = await self._async_attempt_connection()
                    if success:
                        self.log_message("Auto-connect: Successfully connected!")
                except Exception as e:
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
                            self.haptic_engine._async_disconnect(),
                            self.async_loop,
                        )
                    except Exception as e:
                        self.log_message(f"Intiface disconnect failed: {e}")
    
    def get_detected_zones(self) -> Dict[str, List[str]]:
        """Facade method for UI to safely read detected zones from the Central Store."""
        return store.get_detected_zones()
    
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
        params = store.get_all_parameters()
        if self.get_app_setting("simple_mode", False):
            motor_counts = self.get_device_motor_counts()
            updates = self.motor_router.reevaluate_simple_mode(motor_counts, params)
        else:
            active = self.profile_manager.get_active_profile_dict()
            if active is None:
                return
            updates = self.motor_router.reevaluate_state(active, params)
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
                    self.haptic_engine._async_purr_check(),
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
                self.haptic_engine._async_test_device(device_name),
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
            self.haptic_engine.is_connected = connected

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
                    self.haptic_engine._async_connect(),
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
                    self.haptic_engine._async_disconnect(),
                    self.async_loop
                )
                future.result(timeout=2)
                self.update_connection_status(False, "")
                
                # Stop auto-refresh if disconnecting
                self.auto_refresh_enabled = False
                if self._auto_refresh_task:
                    self._auto_refresh_task.cancel()
                    self._auto_refresh_task = None
                
                # Stop auto-connect if disconnecting
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

        self.ui.shutdown()

    # ==================================================================
    # SteamVR Haptics Facade
    # The UI and other backend services must go through these methods —
    # they MUST NOT touch self.steamvr_engine / self.steamvr_router /
    # self.profile_manager.steamvr_settings directly.
    # ==================================================================

    def _steamvr_settings(self):
        return self.profile_manager.steamvr_settings

    def _steamvr_get_tracker_config(self, serial: str) -> SteamVRTrackerConfig:
        return SteamVRTrackerConfig.from_dict(self._steamvr_settings().get_tracker(serial))

    def _steamvr_get_all_tracker_configs(self) -> Dict[str, SteamVRTrackerConfig]:
        return {
            serial: SteamVRTrackerConfig.from_dict(d)
            for serial, d in self._steamvr_settings().get_tracker_dict().items()
        }

    def _steamvr_get_pattern_configs(self) -> List[SteamVRPatternConfig]:
        return [SteamVRPatternConfig.from_dict(d) for d in self._steamvr_settings().get_patterns()]

    def _steamvr_get_no_data(self) -> Dict[str, Any]:
        return self._steamvr_settings().get_no_data()

    def _steamvr_get_battery_interval(self) -> float:
        return float(self._steamvr_settings().get_battery_interval())

    def _steamvr_get_auto_connect(self) -> bool:
        return self._steamvr_settings().get_auto_connect()

    def _steamvr_send_osc(self, address: str, value: float) -> None:
        # Reuse the existing outbound VRChat client (already targets the
        # discovered OSCQuery port). No-op if VRChat isn't connected.
        if not self.osc_manager or not getattr(self.osc_manager, "is_connected", False):
            return
        try:
            self.osc_manager.send_parameter(address, float(value), ignore_rate_limit=True)
        except Exception as e:
            self.log_message(f"SteamVR battery OSC send failed ({address}): {e}")

    def get_steamvr_status(self) -> Dict[str, Any]:
        """Snapshot for the UI: runtime alive, device list, autostart, manifest reg."""
        devices = self.steamvr_engine.snapshot_devices()
        return {
            "available": self.steamvr_engine.is_available,
            "alive": self.steamvr_engine.is_alive,
            "bundled": self.steamvr_engine.is_app_bundled,
            "autostart": self._steamvr_settings().get_autostart(),
            "auto_connect": self._steamvr_settings().get_auto_connect(),
            "registered": self.steamvr_engine.is_registered() if self.steamvr_engine.is_alive else False,
            "battery_interval_s": self._steamvr_get_battery_interval(),
            "trackers": [
                {
                    "serial": d.serial,
                    "model": d.model,
                    "device_class": d.device_class,
                    "supports_haptics": d.supports_haptics,
                    "battery": self.steamvr_engine.battery_for(d.serial),
                    "config": self._steamvr_settings().get_tracker(d.serial),
                }
                for d in devices
            ],
        }

    def refresh_steamvr_trackers(self) -> int:
        devices = self.steamvr_engine.refresh_devices(quiet=False)
        return len(devices)

    def pulse_steamvr_tracker(self, serial: str, length_ms: int = 500) -> None:
        self.steamvr_engine.pulse_test(serial, length_ms)

    def set_steamvr_tracker_config(self, serial: str, cfg: Dict[str, Any]) -> None:
        self._steamvr_settings().set_tracker(serial, cfg)

    def set_steamvr_autostart(self, enabled: bool) -> None:
        self._steamvr_settings().set_autostart(enabled)
        try:
            self.steamvr_engine.setup_autostart(enabled)
        except Exception as e:
            self.log_message(f"SteamVR autostart toggle failed: {e}")

    def set_steamvr_pattern(self, index: int, pattern_dict: Dict[str, Any]) -> None:
        self._steamvr_settings().set_pattern(index, pattern_dict)

    def get_steamvr_pattern_configs(self) -> List[Dict[str, Any]]:
        return list(self._steamvr_settings().get_patterns())

    def get_steamvr_no_data(self) -> Dict[str, Any]:
        return self._steamvr_settings().get_no_data()

    def set_steamvr_no_data(self, enabled: bool, timeout_s: int) -> None:
        self._steamvr_settings().set_no_data(enabled, timeout_s)

    def set_steamvr_battery_interval(self, seconds: float) -> None:
        self._steamvr_settings().set_battery_interval(seconds)
        self.steamvr_battery.set_interval(seconds)

    def set_steamvr_auto_connect(self, enabled: bool) -> None:
        self._steamvr_settings().set_auto_connect(enabled)
        # If just turned on, try one immediate refresh so the UI updates quickly.
        if enabled:
            try:
                self.steamvr_engine.refresh_devices(quiet=True)
            except Exception:
                pass

    # ==================================================================
    # bHaptics Facade
    # ==================================================================

    def _bhaptics_settings(self):
        return self.profile_manager.bhaptics_settings

    def _bhaptics_get_auto_connect(self) -> bool:
        return self._bhaptics_settings().get_auto_connect()

    def _bhaptics_get_device_configs(self) -> Dict[str, BHapticsDeviceConfig]:
        raw = self._bhaptics_settings().get_devices()
        return {pos: BHapticsDeviceConfig.from_dict(d) for pos, d in raw.items()}

    def _bhaptics_get_antistuck(self) -> Dict[str, Any]:
        return self._bhaptics_settings().get_antistuck()

    def get_bhaptics_status(self) -> Dict[str, Any]:
        s = self._bhaptics_settings()
        detected = bhaptics_detected_positions(store.get_all_parameters())
        return {
            "available": self.bhaptics_engine.is_available,
            "connected": self.bhaptics_engine.is_connected,
            "last_error": self.bhaptics_engine.last_error,
            "auto_connect": s.get_auto_connect(),
            "host": s.get_host(),
            "port": s.get_port(),
            "antistuck": s.get_antistuck(),
            "devices": [
                {
                    "position": pos,
                    "display_name": bhaptics_display_name(pos),
                    "node_count": count,
                    "grid": bhaptics_grid_layout(pos),  # (cols, rows)
                    "config": s.get_device(pos),
                    "detected": pos in detected,
                }
                for pos, _slot, count in bhaptics_device_table()
            ],
        }

    def get_bhaptics_snapshot(self) -> Dict[str, List[int]]:
        """Live per-device dot intensities (0-100). Used by the debug grid."""
        return self.bhaptics_router.get_snapshot()

    def set_bhaptics_auto_connect(self, enabled: bool) -> None:
        self._bhaptics_settings().set_auto_connect(enabled)

    def set_bhaptics_endpoint(self, host: str, port: int) -> None:
        self._bhaptics_settings().set_endpoint(host, port)
        self.bhaptics_engine.set_endpoint(host, port)

    def set_bhaptics_device(self, position: str, cfg: Dict[str, Any]) -> None:
        self._bhaptics_settings().set_device(position, cfg)

    def set_bhaptics_manual_dot(self, position: str, index: int, intensity) -> None:
        """Debug-only: drive a single bHaptics dot at fixed intensity (or
        None to release). Used by the UI's click-to-test grid."""
        self.bhaptics_router.set_manual_override(position, index, intensity)

    def bhaptics_connect_now(self) -> bool:
        return self.bhaptics_engine.manual_connect()

    def set_bhaptics_antistuck(self, enabled: bool, hold_s: float, ramp_s: float) -> None:
        self._bhaptics_settings().set_antistuck(enabled, hold_s, ramp_s)

    # ==================================================================
    # Hardware Monitor Facade
    # UI talks to the engine and its settings only through these methods.
    # ==================================================================

    def _hardware_monitor_settings(self):
        return self.profile_manager.hardware_monitor_settings

    def _hardware_monitor_get_config(self) -> Dict[str, Any]:
        return self._hardware_monitor_settings().get_all()

    def _hardware_monitor_send_osc(self, address: str, value: float) -> None:
        if not self.osc_manager or not getattr(self.osc_manager, "is_connected", False):
            return
        try:
            self.osc_manager.send_parameter(address, float(value), ignore_rate_limit=True)
        except Exception as e:
            self.log_message(f"HardwareMonitor OSC send failed ({address}): {e}")

    def get_hardware_monitor_status(self) -> Dict[str, Any]:
        """Snapshot for the UI: live hardware stats merged with current settings."""
        snap = self.hardware_monitor.snapshot()
        cfg = self._hardware_monitor_settings().get_all()
        return {"stats": snap, "settings": cfg}

    def set_hardware_monitor_enabled(self, enabled: bool) -> None:
        self._hardware_monitor_settings().set_enabled(bool(enabled))

    def set_hardware_monitor_send_osc(self, enabled: bool) -> None:
        self._hardware_monitor_settings().set_send_osc(bool(enabled))

    def set_hardware_monitor_gpu_enabled(self, enabled: bool) -> None:
        self._hardware_monitor_settings().set_gpu_enabled(bool(enabled))

    def set_hardware_monitor_poll_rate(self, seconds: float) -> None:
        self._hardware_monitor_settings().set_poll_rate(seconds)

    def set_hardware_monitor_address(self, key: str, address: str) -> None:
        self._hardware_monitor_settings().set_address(key, address)

    def set_hardware_monitor_send_toggle(self, key: str, enabled: bool) -> None:
        self._hardware_monitor_settings().set_send_toggle(key, bool(enabled))

    def run(self):
        """Start the Three-Pillar application"""
        # Start async loop in background thread
        self.start_async_loop()

        # Wait for async_loop to be ready (race condition: thread needs time to set self.async_loop)
        import time
        timeout = 5.0
        start_time = time.time()
        while self.async_loop is None and (time.time() - start_time) < timeout:
            time.sleep(0.05)

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