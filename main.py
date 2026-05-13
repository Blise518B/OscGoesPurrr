# OscGoesPurrr - Three-Pillar Threading Architecture
# Copyright (C) 2024-2025  OscGoesPurrr Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

# Three-Pillar Threading Architecture:
#
#   Pillar 1: Main thread - customtkinter mainloop() + UI updates (ui_components.py)
#   Pillar 2: Async thread - asyncio event loop for buttplug/OSC (haptic_engine.py)
#   Pillar 3: Queue-based communication between threads (threading-safe)

import threading
import asyncio
import queue
from typing import Optional, Dict, Any

# ProfileManager from config manager module
from config_manager import PROFILE_FILE, ProfileManager

# UI Components for the Visual Shell (Pillar 1)
from ui_components import OscGoesPurrrUI

# Haptic Engine for async hardware operations
from haptic_engine import HapticEngine

# VRChat OSC Manager for OSC discovery and routing
from vrchat_osc import VRChatOSCManager


class OscGoesPurrrApp:
    def __init__(self):
        # Initialize main window
        self.app = None
        self.async_loop: asyncio.AbstractEventLoop = None
        
        # Thread-safe communication queue (standard library, not asyncio)
        self.thread_queue: queue.Queue = queue.Queue()
        
        # Device-specific state (replaces single global intensity)
        # Using tuple key: (device_name, motor_index) where motor_index=-1 means all motors
        self.device_targets: Dict[tuple, float] = {}  # (device_name, motor_index) -> target intensity
        self.device_last_sent: Dict[tuple, float] = {}  # (device_name, motor_index) -> last sent intensity
        
        # Profile manager instance
        self.profile_manager = ProfileManager()
        
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
        self.osc_debug_data = {}
        self.is_debugging_osc = False
        
        # UI Lock - prevent programmatic UI changes from echoing back to the controller
        self._is_updating_ui = False
        
        # Initialize components in correct order
        self._setup_components()
    
    def _setup_components(self):
        """Initialize main window and UI component"""
        import customtkinter as ctk
        
        # Initialize main window first (required before UI setup)
        self.app = ctk.CTk()
        self.app.title("OscGoesPurrr")
        self.app.geometry("800x600")
        
        # Instantiate Haptic Engine
        self.haptic_engine = HapticEngine(self.thread_queue, self.device_targets, self.device_last_sent)

        # Instantiate VRChat OSC Manager
        bind_all = self.profile_manager.app_settings.settings.get("bind_all_interfaces", True)
        self.osc_manager = VRChatOSCManager(local_listen_port=0, bind_all_interfaces=bind_all)

        # Link our router to the global OSC callback
        self.osc_manager.global_osc_callback = self.on_osc_message

        # Connection hook - push to queue for thread-safe UI update
        self.osc_manager.on_connected = lambda ports: self.thread_queue.put(
            ("osc_status", (True, ports.get("local_listen_port")))
        )
        
        # Load profiles using profile manager (also initializes app_settings)
        self.profile_manager.load_profiles()
        
        # Load app settings (auto_connect, auto_refresh)
        self.auto_refresh_enabled = self.profile_manager.app_settings.get("auto_refresh", True)
        self.auto_connect_enabled = self.profile_manager.app_settings.get("auto_connect", True)
        
        # Instantiate UI Component (must be after haptic_engine is created)
        self.ui = OscGoesPurrrUI(self.app, self)
        
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
                        self.ui.update_connection_status(connected, server)
                    elif msg_type == "devices_found":
                        self.ui.build_device_list_ui(data)
                    elif msg_type == "stored_devices_refresh":
                        self.ui.build_stored_devices_ui()
                    elif msg_type == "osc_status":
                        is_connected, port = data
                        self.ui.update_osc_status(is_connected, port)
                        self.ui.log_message(f"VRChat OSC Connected! Listening on port {port}")
                    elif msg_type == "osc_haptic_update":
                        device_name, val_float, motor_index = data
                        # This is now safely running on the Main UI thread!
                        self.update_device_target(device_name, val_float, motor_index)
                    elif msg_type == "ui_slider_update":
                        device_name, value, motor_idx = data
                        if device_name in self.ui.device_ui_frames:
                            motor_vars = self.ui.device_ui_frames[device_name].get("motors", [])
                            
                            self._is_updating_ui = True  # Lock the UI
                            try:
                                if 0 <= motor_idx < len(motor_vars):
                                    motor_vars[motor_idx]["slider"].set(value)
                                    motor_vars[motor_idx]["vibe_meter"].set(value)
                                elif motor_idx == -1:
                                    for mv in motor_vars:
                                        mv["slider"].set(value)
                                        mv["vibe_meter"].set(value)
                            finally:
                                self._is_updating_ui = False  # Unlock
                        
        except queue.Empty:
            pass  # No more messages in queue
    
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        self.ui.log_message(message)
    
    def save_all_profiles(self):
        """Save all device configurations from UI to profiles.json"""
        for device_name, frame_data in self.ui.device_ui_frames.items():
            # Build per-motor OSC address dictionary from motor osc_entries
            osc_addresses = {}
            for motor_data in frame_data.get("motors", []):
                osc_entry = motor_data.get("osc_entry")
                if osc_entry and hasattr(osc_entry, 'get'):
                    # The motor index is derived from the position in the list
                    motor_idx = frame_data["motors"].index(motor_data)
                    osc_addresses[str(motor_idx)] = osc_entry.get()
            
            # If no per-motor entries found, fall back to default
            if not osc_addresses:
                osc_addresses["0"] = "/avatar/parameters/" + device_name.replace(" ", "_")
            
            # Store per-motor OSC addresses in profile
            self.update_device_config(device_name, "osc_addresses", osc_addresses)
        
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
        if not self.ui.auto_connect_var.get():
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
    
    def update_stored_devices_ui(self):
        """Update the stored devices UI to show connection status"""
        # Update via ui component
        self.ui.update_stored_devices_ui()
    
    def delete_stored_device(self, device_name: str):
        """Delete a stored device from profiles and UI"""
        if self.current_profile in self.profiles:
            if device_name in self.profiles[self.current_profile]:
                del self.profiles[self.current_profile][device_name]
                self.save_profiles()
        
        # Remove from UI via ui component
        if device_name in self.ui.stored_device_frames:
            frame_data = self.ui.stored_device_frames[device_name]
            frame_data.get("frame").destroy()
            del self.ui.stored_device_frames[device_name]
        
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
    
    def update_device_config(self, device_name: str, key: str, value):
        """Update a config value for a device in current profile using profile_manager"""
        self.profile_manager.update_device_config(device_name, key, value)
    
    def on_osc_message(self, address: str, value):
        if self.is_debugging_osc:
            self.osc_debug_data[address] = value

        curr_profile = self.profile_manager.current_profile
        profiles = self.profile_manager.profiles

        if curr_profile not in profiles:
            return
            
        try:
            val_float = float(value)
            # Normalize VRChat 8-bit ints (0-255) to Buttplug floats (0.0-1.0)
            if val_float > 1.0:
                val_float = val_float / 255.0
            val_float = max(0.0, min(1.0, val_float))
        except (ValueError, TypeError):
            return
            
        for device_name, config in profiles[curr_profile].items():
            osc_addresses = config.get("osc_addresses", {})
            for motor_idx_str, saved_address in osc_addresses.items():
                # UX Fix: Auto-prepend prefix if user just typed the parameter name
                clean_saved = saved_address.strip()
                if clean_saved and not clean_saved.startswith("/"):
                    clean_saved = "/avatar/parameters/" + clean_saved
                    
                if clean_saved == address.strip():
                    self.thread_queue.put(("osc_haptic_update", (device_name, val_float, int(motor_idx_str))))

    def toggle_osc_debugger(self, *args):
        """Toggle the OSC debugger on/off (accepts *args for safe UI toggle compatibility)"""
        self.is_debugging_osc = not self.is_debugging_osc
        if self.is_debugging_osc:
            self.osc_debug_data.clear()
            self.ui.log_message("OSC Debugger Started")
        else:
            self.ui.log_message("OSC Debugger Stopped")

    def refresh_debugger_ui(self):
        """Refresh the debugger display at 10Hz (100ms intervals)"""
        if self.is_debugging_osc and self.app:
            # Format the dictionary into a clean string
            debug_text = "Live OSC Variables:\n" + "-" * 30 + "\n"
            for addr in sorted(self.osc_debug_data.keys()):
                debug_text += f"{addr}: {self.osc_debug_data[addr]}\n"
            # Push to the UI
            self.ui.update_debugger_display(debug_text)
        
        # Schedule the next refresh (100ms = 10Hz)
        if self.app:
            self.app.after(100, self.refresh_debugger_ui)

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
            
        # Update target in state dictionary using tuple key
        self.device_targets[(device_name, motor_index)] = float(value)
        
        # Update the corresponding vibe meter via ui component
        if device_name in self.ui.device_ui_frames:
            frame_data = self.ui.device_ui_frames[device_name]
            if "motors" in frame_data and motor_index >= 0 and motor_index < len(frame_data["motors"]):
                # Update specific motor's vibe meter
                frame_data["motors"][motor_index]["vibe_meter"].set(float(value))
        
    
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

    def switch_profile(self, profile_name: str):
        """Switch to a different profile and reload the device UI.

        Args:
            profile_name: Name of the profile to switch to.
        """
        if profile_name not in self.profile_manager.profiles:
            self.log_message(f"Profile '{profile_name}' not found.")
            return

        self.profile_manager.current_profile = profile_name
        self.current_profile = profile_name

        # Rebuild the device UI for the new profile
        self.ui.build_stored_devices_ui()
        self.log_message(f"Switched to profile: {profile_name}")

        # Refresh the profile buttons on the Dashboard
        if hasattr(self.ui, '_refresh_profile_buttons'):
            self.ui._refresh_profile_buttons()
    
    def rename_profile(self, old_name: str, new_name: str):
        """Rename a profile in the profiles dictionary.

        Args:
            old_name: Current name of the profile.
            new_name: New name for the profile.
        """
        if old_name not in self.profile_manager.profiles:
            self.log_message(f"Cannot rename: profile '{old_name}' not found.")
            return
        
        # Prevent duplicate names
        if new_name in self.profile_manager.profiles and new_name != old_name:
            self.log_message(f"Cannot rename: profile '{new_name}' already exists.")
            return
        
        # Rename in the profiles dict
        data = self.profile_manager.profiles.pop(old_name)
        self.profile_manager.profiles[new_name] = data
        self.profile_manager.save_profiles()
        
        # Update current_profile if it was the renamed one
        if self.profile_manager.current_profile == old_name:
            self.profile_manager.current_profile = new_name
            self.current_profile = new_name
        
        self.log_message(f"Renamed profile '{old_name}' to '{new_name}'")
        
        # Refresh the profile buttons on the Dashboard
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
        if not self.ui.osc_auto_connect_var.get():
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
        if not self.ui.auto_refresh_var.get():
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
        scan_interval = 30.0  # Scan every 30 seconds
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
    
    def save_profiles(self):
        """Save profiles using profile manager"""
        self.profile_manager.save_profiles()
    
    def load_profiles(self) -> Dict[str, Any]:
        """Load profiles using profile manager"""
        return self.profile_manager.load_profiles()
    
    def _on_closing(self):
        """Handle clean shutdown: auto-save profiles before exiting."""
        self.save_profiles()
        if self.app:
            self.app.destroy()

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

        # Periodically check for UI updates from async thread
        def check_queue():
            self.process_async_queue()
            if self.app:
                self.app.after(50, check_queue)  # Check every 50ms

        if self.app:
            # Register clean shutdown handler to auto-save profiles
            self.app.protocol("WM_DELETE_WINDOW", self._on_closing)

            self.app.after(100, check_queue)

            # Boot OSC server 500ms after UI launches to prevent freezing
            if self.profile_manager.app_settings.settings.get("auto_connect_osc", True):
                self.app.after(500, self.toggle_osc_connection)

            # Start the OSC debugger UI refresh loop
            self.refresh_debugger_ui()

            # Run GUI mainloop on main thread
            self.app.mainloop()


if __name__ == "__main__":
    app = OscGoesPurrrApp()
    app.run()