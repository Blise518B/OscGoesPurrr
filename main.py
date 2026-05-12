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
        
        # Haptic Engine - async hardware interface
        self.haptic_engine: Optional[HapticEngine] = None
        
        # Connection status tracking
        self.is_connected = False
        
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
        
        # Instantiate UI Component (must be after haptic_engine is created)
        self.ui = OscGoesPurrrUI(self.app, self)
        
        # Load profiles using profile manager
        self.profile_manager.load_profiles()
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
                        
        except queue.Empty:
            pass  # No more messages in queue
    
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        self.ui.log_message(message)
    
    def save_all_profiles(self):
        """Save all device configurations from UI to profiles.json"""
        for device_name, frame_data in self.ui.device_ui_frames.items():
            osc_entry = frame_data.get("osc_entry")
            
            if osc_entry and hasattr(osc_entry, 'get'):
                osc_address = osc_entry.get()
            else:
                osc_address = "/avatar/parameters/" + device_name.replace(" ", "_")
            
            # Store OSC address in profile
            self.update_device_config(device_name, "osc_address", osc_address)
        
        self.save_profiles()
        self.log_message("All device profiles saved")
    
    def update_connection_status(self, connected: bool, server: str):
        """Update connection UI elements (main thread only)"""
        # Sync with haptic engine
        if self.haptic_engine:
            self.haptic_engine.is_connected = connected
        
        # Update UI via ui component
        self.ui.update_connection_status(connected, server)
    
    def get_connected_device_names(self) -> set:
        """Get set of currently connected device names"""
        if not self.haptic_engine or not self.haptic_engine.buttplug_client:
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
    
    def update_device_target(self, device_name: str, value: float, motor_index: int):
        """Update target intensity for a specific device and motor
        
        Args:
            device_name: Name of the device
            value: New intensity value (0.0 to 1.0)
            motor_index: Motor index (-1 for all motors, 0+ for specific)
        """
        # Update target in state dictionary using tuple key
        self.device_targets[(device_name, motor_index)] = float(value)
        
        # Update the corresponding vibe meter via ui component
        if device_name in self.ui.device_ui_frames:
            frame_data = self.ui.device_ui_frames[device_name]
            if "motors" in frame_data and motor_index >= 0 and motor_index < len(frame_data["motors"]):
                # Update specific motor's vibe meter
                frame_data["motors"][motor_index]["vibe_meter"].set(float(value))
        
        # Also update all-motors entry (for backward compatibility)
        if motor_index != -1:
            self.device_targets[(device_name, -1)] = float(value)
    
    def trigger_purr_check(self):
        """Trigger Purr-Check from main thread"""
        if self.async_loop and self.haptic_engine:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.haptic_engine._async_purr_check(),
                    self.async_loop
                )
                future.result(timeout=3)
            except Exception as e:
                self.log_message(f"Purr-Check failed: {e}")
    
    def connect_to_intiface(self):
        """Handle connection button click - connects/disconnects from main thread"""
        if not self.haptic_engine or not self.async_loop:
            return
            
        is_connected = self.haptic_engine.is_connected if hasattr(self.haptic_engine, 'is_connected') else False
        
        if not is_connected:
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
            except Exception as e:
                pass
    
    def save_profiles(self):
        """Save profiles using profile manager"""
        self.profile_manager.save_profiles()
    
    def load_profiles(self) -> Dict[str, Any]:
        """Load profiles using profile manager"""
        return self.profile_manager.load_profiles()
    
    def run(self):
        """Start the Three-Pillar application"""
        # Start async loop in background thread
        self.start_async_loop()
        
        # Periodically check for UI updates from async thread
        def check_queue():
            self.process_async_queue()
            if self.app:
                self.app.after(50, check_queue)  # Check every 50ms
            
        if self.app:
            self.app.after(100, check_queue)
            
            # Run GUI mainloop on main thread
            self.app.mainloop()


if __name__ == "__main__":
    app = OscGoesPurrrApp()
    app.run()