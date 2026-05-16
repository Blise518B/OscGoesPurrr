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
                        self.ui.update_battery_label(data["device_name"], data["level"])
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
        while self.auto_connect_enabled and not self.haptic_engine.is_connected:
            await asyncio.sleep(2.0)
            if self.auto_connect_enabled and not self.haptic_engine.is_connected:
                try:
                    success = await self._async_attempt_connection()
                    if success:
                        self.log_message("Auto-connect: Successfully connected!")
                except Exception as e:
                    pass  # Errors are logged in _async_attempt_connection
    
    def get_connected_device_names(self) -> set:
        """Get set of currently connected device names"""
        if not self.haptic_engine or not self.haptic_engine.buttplug_client or not self.haptic_engine.is_connected:
            return set()
        return {device.name for device in self.haptic_engine.buttplug_client.devices.values()}
    
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
        for profile in self.profile_manager.profiles.values():
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
    
    def get_detected_zones(self) -> Dict[str, List[str]]:
        """Facade method for UI to safely read detected zones from the Central Store."""
        return store.get_detected_zones()
    
    def update_device_config(self, device_name: str, key: str, value):
        """Update a config value for a device in current profile using profile_manager"""
        self.profile_manager.update_device_config(device_name, key, value)
    
    def on_osc_message(self, address: str, value):
        """Acts as a trigger ping when new UDP data arrives. Sets a flag to batch rapid updates."""
        self._needs_recalculation = True

    def force_recalculate(self):
        """Forces the router to recalculate output based on current state and new UI configs."""
        curr_profile = self.profile_manager.current_profile
        profiles = self.profile_manager.profiles
        if curr_profile in profiles and hasattr(self, 'motor_router') and hasattr(self, 'osc_manager'):
            # Pass a thread-safe copy from the Central Store into the router
            updates = self.motor_router.reevaluate_state(profiles[curr_profile], store.get_all_parameters())
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
                    # Pad the address so the colons align nicely (address is gray, value gets color)
                    lines.append((addr.ljust(60) + " : ", val_str, color))

            if not lines and search_query:
                debug_data = [("No parameters match your search.", "", COLOR_TEXT_MUTED)]
            elif not lines:
                debug_data = [("Waiting for OSC data...", "", COLOR_TEXT_MUTED)]
            else:
                debug_data = lines

            # Push to the UI as a list of (text, color) tuples
            self.ui.update_debugger_display(debug_data)

        # Schedule the next refresh (Throttled to save UI thread)
        self.ui.schedule_callback(UI_REFRESH_RATE_MS, self.refresh_debugger_ui)

    def get_device_motor_counts(self) -> dict:
        """Facade method to get motor counts safely from the hardware engine."""
        from haptic_engine import get_device_motor_counts as get_counts
        if self.haptic_engine and self.haptic_engine.is_connected and self.haptic_engine.buttplug_client:
            return get_counts(self.haptic_engine.buttplug_client)
        return {}

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
        if not self.haptic_engine or not self.haptic_engine.buttplug_client:
            return
        
        try:
            # Start scanning
            await self.haptic_engine.buttplug_client.start_scanning()
            await asyncio.sleep(2.0)  # Give Intiface time to find devices
            
            # Stop scanning and get device list
            await self.haptic_engine.buttplug_client.stop_scanning()
            
            # Find new devices (devices we haven't seen before)
            connected_names = {device.name for device in self.haptic_engine.buttplug_client.devices.values()}
            known_devices = set(self.get_connected_device_names())
            new_devices = connected_names - known_devices
            
            if new_devices:
                self.log_message(f"Auto-refresh found new devices: {new_devices}")
                
                # Find the newly discovered devices
                found_devices = {}
                for device in self.haptic_engine.buttplug_client.devices.values():
                    if device.name in new_devices:
                        try:
                            features = device.get_features_with_output(OutputType.VIBRATE)
                            motor_count = len(features) if features else 1
                            found_devices[device.index] = {
                                "name": device.name,
                                "motor_count": motor_count
                            }
                        except Exception:
                            pass
                
                # Push new devices to UI
                self.thread_queue.put(("devices_found", found_devices))
                
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

        self.ui.shutdown()

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

        # Start auto-connect if enabled (single source of truth is haptic_engine.is_connected)
        if self.auto_connect_enabled and not self.haptic_engine.is_connected and self.async_loop:
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