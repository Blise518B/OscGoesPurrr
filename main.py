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
#   Pillar 1: Main thread - customtkinter mainloop() + UI updates
#   Pillar 2: Async thread - asyncio event loop for buttplug/OSC
#   Pillar 3: Queue-based communication between threads (threading-safe)

import customtkinter as ctk
import threading
import asyncio
import queue
import json
import os
from typing import Optional, Dict, Any

from pathlib import Path

# AppData directory for persistent storage
APPDATA_DIR = Path.home() / "AppData" / "Roaming" / "OscGoesPurrr"
PROFILE_FILE = APPDATA_DIR / "profiles.json"

# Ensure AppData directory exists
os.makedirs(APPDATA_DIR, exist_ok=True)

# Third-party imports (at module level for proper virtual environment resolution)
from buttplug import ButtplugClient, DeviceOutputCommand, OutputType
from pythonosc.udp_client import SimpleUDPClient


class OscGoesPurrrApp:
    def __init__(self):
        # Initialize main window
        self.app = ctk.CTk()
        self.app.title("OscGoesPurrr")
        self.app.geometry("800x600")
        
        # Thread-safe communication queue (standard library, not asyncio)
        self.thread_queue: queue.Queue = queue.Queue()
        self.async_loop: asyncio.AbstractEventLoop = None
        
        # Buttplug and OSC clients
        self.buttplug_client: Optional[ButtplugClient] = None
        self.osc_client = None
        
        # GUI State
        self.status_label = None
        self.connection_button = None
        self.is_connected = False
        
        # Stored devices UI tracking
        self.stored_device_frames: Dict[str, dict] = {}  # device_name -> frame references
        
        # Device-specific state (replaces single global intensity)
        # Using tuple key: (device_name, motor_index) where motor_index=-1 means all motors
        self.device_targets: Dict[tuple, float] = {}  # (device_name, motor_index) -> target intensity
        self.device_last_sent: Dict[tuple, float] = {}  # (device_name, motor_index) -> last sent intensity
        self.device_ui_frames: Dict[str, dict] = {}    # device_name -> config UI frame references
        
        # Profile system state
        self.profiles: Dict[str, Any] = {}  # All loaded profiles
        self.current_profile = "Default"    # Currently active profile
        
        # Manual Purr UI components (kept for legacy Purr-Check functionality)
        self.testing_frame = None
        self.purr_check_button = None
        
        # Setup UI
        self.setup_ui()
        
        # Load profiles on startup
        self.load_profiles()
        # Build stored devices UI after loading profiles
        self.build_stored_devices_ui()
        
    def setup_ui(self):
        """Create and arrange all GUI elements"""
        main_frame = ctk.CTkFrame(self.app, fg_color="transparent")
        main_frame.pack(expand=True, fill="both", padx=20, pady=20)
        
        # Title
        title_label = ctk.CTkLabel(
            main_frame,
            text="OscGoesPurrr",
            font=("Arial", 32, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 10))
        
        # Status Label
        self.status_label = ctk.CTkLabel(
            main_frame,
            text="Ready to connect",
            font=("Arial", 14),
            text_color="#888888"
        )
        self.status_label.pack(pady=10)
        
        # Connection Button
        self.connection_button = ctk.CTkButton(
            main_frame,
            text="Connect to Intiface",
            command=self.connect_to_intiface,
            font=("Arial", 16),
            height=50,
            fg_color="#6B4EFF",
            hover_color="#5A3DCC"
        )
        self.connection_button.pack(pady=20)
        
        # Manual Purr Testing Frame (now only for Purr-Check)
        self.testing_frame = ctk.CTkFrame(main_frame, corner_radius=8)
        self.testing_frame.pack(expand=False, fill="x", pady=(10, 20))
        
        # Purr-Check Button
        self.purr_check_button = ctk.CTkButton(
            self.testing_frame,
            text="Purr-Check (Test All)",
            command=self.trigger_purr_check,
            font=("Arial", 14),
            height=40
        )
        self.purr_check_button.pack(pady=(0, 10))
        
        # Unified Devices Frame - contains saved toys and active controls
        self.devices_container_frame = ctk.CTkFrame(main_frame, corner_radius=8, fg_color="#1E1E2E")
        self.devices_container_frame.pack(expand=False, fill="x", pady=(0, 10), padx=5)
        
        # Header for devices section
        devices_header_label = ctk.CTkLabel(
            self.devices_container_frame,
            text="Toys",
            font=("Arial", 16, "bold"),
            text_color="#FFFFFF"
        )
        devices_header_label.pack(pady=(10, 5))
        
        # Unified devices scrollable frame (contains both saved and active devices with full controls)
        self.unified_devices_frame = ctk.CTkScrollableFrame(
            self.devices_container_frame,
            corner_radius=8,
            fg_color="transparent",
            height=250
        )
        self.unified_devices_frame.pack(expand=False, fill="x", pady=(5, 10), padx=5)
        
        # Log/Output Box
        log_frame = ctk.CTkFrame(main_frame, corner_radius=8)
        log_frame.pack(expand=True, fill="both", pady=(0, 10))
        
        self.log_text = ctk.CTkTextbox(
            log_frame,
            font=("Courier New", 12),
            state="disabled",
            fg_color="#1E1E2E"
        )
        self.log_text.pack(expand=True, fill="both", padx=10, pady=10)
        
    def load_profiles(self) -> Dict[str, Any]:
        """Load profiles from JSON file or create default if not exists
        
        Returns:
            Dictionary containing all loaded profiles
        """
        if os.path.exists(PROFILE_FILE):
            try:
                with open(PROFILE_FILE, 'r') as f:
                    self.profiles = json.load(f)
                    self.log_message(f"Loaded profiles from {PROFILE_FILE}")
                    return self.profiles
            except (json.JSONDecodeError, IOError) as e:
                self.log_message(f"Profile load error: {e}, creating default profile")
        
        # Create default profile if file doesn't exist or has errors
        default_profiles = {
            "Default": {}
        }
        self.profiles = default_profiles
        self.save_profiles()
        return self.profiles
    
    def save_profiles(self):
        """Save current profiles to JSON file"""
        try:
            with open(PROFILE_FILE, 'w') as f:
                json.dump(self.profiles, f, indent=2)
            self.log_message(f"Profiles saved to {PROFILE_FILE}")
        except IOError as e:
            self.push_ui_update(f"Profile save error: {e}")
    
    def _get_motor_display_name(self, motor_index: int) -> str:
        """Convert motor index to display name for OptionMenu
        
        Args:
            motor_index: -1 for all motors, 0+ for specific motor
            
        Returns:
            Display string for the option menu
        """
        if motor_index == -1:
            return "All Motors"
        else:
            return f"Motor {motor_index}"
    
    def get_profile_config(self, device_name: str, key: str, default=None):
        """Get a specific config value for a device from current profile
        
        Args:
            device_name: Name of the device
            key: Config key (e.g., 'osc_address', 'motor_index')
            default: Default value if not found
            
        Returns:
            The config value or default
        """
        if self.current_profile in self.profiles:
            profile = self.profiles[self.current_profile]
            if device_name in profile:
                return profile[device_name].get(key, default)
        return default
    
    def update_device_config(self, device_name: str, key: str, value):
        """Update a config value for a device in current profile
        
        Args:
            device_name: Name of the device
            key: Config key to update
            value: New value
        """
        if self.current_profile not in self.profiles:
            self.profiles[self.current_profile] = {}
        
        if device_name not in self.profiles[self.current_profile]:
            self.profiles[self.current_profile][device_name] = {}
            
        self.profiles[self.current_profile][device_name][key] = value
    
    def start_async_loop(self):
        """Start the asyncio event loop in a separate thread"""
        def run_loop():
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            self.async_loop = loop
            
            try:
                loop.run_until_complete(self.async_worker())
            finally:
                loop.close()
        
        # Start async thread
        self.async_thread = threading.Thread(target=run_loop, daemon=True)
        self.async_thread.start()
        
    def push_stored_devices_refresh(self):
        """Push stored devices refresh request from async thread to main thread"""
        self.thread_queue.put(("stored_devices_refresh", None))
    
    def push_ui_update(self, message: str):
        """Push a UI update from the async thread to the main thread via queue"""
        self.thread_queue.put(("ui_update", message))
        
    def push_connection_status(self, connected: bool, server: str = ""):
        """Push connection status from async thread to main thread"""
        self.thread_queue.put(("connection_status", (connected, server)))
        
    def process_async_queue(self):
        """Process messages from queue (called from main thread)"""
        try:
            while True:
                msg = self.thread_queue.get_nowait()
                
                if isinstance(msg, tuple):
                    msg_type, data = msg
                    
                    if msg_type == "ui_update":
                        self.log_message(data)
                    elif msg_type == "connection_status":
                        connected, server = data
                        self.update_connection_status(connected, server)
                    elif msg_type == "devices_found":
                        self.build_device_list_ui(data)
                    elif msg_type == "stored_devices_refresh":
                        self.build_stored_devices_ui()
                        
        except queue.Empty:
            pass  # No more messages in queue
            
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"> {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        
    def save_all_profiles(self):
        """Save all device configurations from UI to profiles.json"""
        for device_name, frame_data in self.device_ui_frames.items():
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
        self.is_connected = connected
        if connected:
            self.connection_button.configure(
                text=f"Disconnect from Intiface",
                fg_color="#FF5E57",
                hover_color="#DD4E46"
            )
            self.status_label.configure(
                text=f"Connected to Intiface ✓",
                text_color="#00C853"
            )
        else:
            self.connection_button.configure(
                text="Connect to Intiface",
                fg_color="#6B4EFF",
                hover_color="#5A3DCC"
            )
            self.status_label.configure(
                text="Ready to connect",
                text_color="#888888"
            )
        
        # Update stored devices status indicators
        self.update_stored_devices_ui()
    
    def get_connected_device_names(self) -> set:
        """Get set of currently connected device names"""
        if not self.is_connected or not self.buttplug_client:
            return set()
        return {device.name for device in self.buttplug_client.devices.values()}
    
    def update_stored_devices_ui(self):
        """Update the stored devices UI to show connection status"""
        # Get currently connected devices
        connected_names = self.get_connected_device_names()
        
        # Update each stored device frame with connection status
        for device_name, frame_data in self.stored_device_frames.items():
            status_label = frame_data.get("status_label")
            delete_button = frame_data.get("delete_button")
            
            if status_label and delete_button:
                if device_name in connected_names:
                    # Connected - show green checkmark
                    status_label.configure(text=f"✓ {device_name}", text_color="#00C853")
                    delete_button.configure(state="normal", fg_color="#FF5E57", hover_color="#DD4E46")
                else:
                    # Not connected - show yellow warning
                    status_label.configure(text=f"⚠ {device_name}", text_color="#FDB914")
                    delete_button.configure(state="normal", fg_color="#FFA500", hover_color="#E69500")
    
    def delete_stored_device(self, device_name: str):
        """Delete a stored device from profiles and UI"""
        if self.current_profile in self.profiles:
            if device_name in self.profiles[self.current_profile]:
                del self.profiles[self.current_profile][device_name]
                self.save_profiles()
        
        # Remove from UI
        if device_name in self.stored_device_frames:
            frame_data = self.stored_device_frames[device_name]
            frame_data.get("frame").destroy()
            del self.stored_device_frames[device_name]
        
        self.log_message(f"Deleted stored toy: {device_name}")
    
    def build_stored_devices_ui(self):
        """Build the UI for all stored devices from profiles with full controls in unified view
        
        Each device shows:
        - Device name with connection status (✓/⚠)
        - Editable OSC address entry
        - Motor sliders + vibe meters for active control
        - Delete button
        
        Uses detected motor count if available, otherwise falls back to profile or default.
        
        Preserves existing frames from build_device_list_ui() when no profiles exist but devices are connected.
        """
        # Get connected device names BEFORE clearing anything
        connected_names = self.get_connected_device_names()
        
        # Check if we have any saved devices in this profile
        has_saved_devices = bool(self.profiles.get(self.current_profile))
        
        # If no saved devices and we already have frames (from build_device_list_ui), don't clear
        if not has_saved_devices and self.device_ui_frames:
            # Just update status labels for connected devices, don't rebuild everything
            self.update_stored_devices_ui()
            return
        
        # Clear existing frames from unified_devices_frame
        for widget in self.unified_devices_frame.winfo_children():
            widget.destroy()
        
        # Clear UI tracking dicts (we'll rebuild unified view)
        self.stored_device_frames.clear()
        self.device_ui_frames.clear()
        
        if not has_saved_devices:
            no_stored_label = ctk.CTkLabel(
                self.unified_devices_frame,
                text="No saved toys yet. Connect devices to save them.",
                font=("Arial", 12),
                text_color="#666666"
            )
            no_stored_label.pack(pady=5)
            return
        
        # Get actual motor counts from connected devices (if available)
        device_motor_counts = {}
        if self.is_connected and self.buttplug_client:
            for device in self.buttplug_client.devices.values():
                try:
                    features = device.get_features_with_output(OutputType.VIBRATE)
                    device_motor_counts[device.name] = len(features)
                except Exception:
                    pass
        
        for device_name, config in self.profiles[self.current_profile].items():
            # Determine if connected (green) or saved but not connected (yellow)
            is_connected = device_name in connected_names
            
            # Get motor count from detected values first, then profile, then default to 1
            stored_motor_count = device_motor_counts.get(device_name, config.get("motor_count", 1))
            
            # Create frame container for this device with full controls
            device_frame = ctk.CTkFrame(
                self.unified_devices_frame,
                corner_radius=8,
                fg_color="#2A2A3E"
            )
            device_frame.pack(expand=False, fill="x", pady=(0, 10), padx=5)
            
            # Header row: status icon + name + delete button
            header_frame = ctk.CTkFrame(device_frame, fg_color="transparent")
            header_frame.pack(expand=True, fill="x", padx=5, pady=(5, 2))
            
            # Status label (icon only)
            status_icon = "✓" if is_connected else "⚠"
            status_text = f"{status_icon} {device_name}"
            status_color = "#00C853" if is_connected else "#FDB914"
            
            name_label = ctk.CTkLabel(
                header_frame,
                text=status_text,
                font=("Arial", 14, "bold"),
                text_color="#FFFFFF",
                anchor="w"
            )
            name_label.pack(side="left")
            
            # Delete button on right
            delete_button = ctk.CTkButton(
                header_frame,
                text="Delete",
                command=lambda name=device_name: self.delete_stored_device(name),
                font=("Arial", 12),
                height=30,
                width=60,
                fg_color="#FF5E57" if is_connected else "#FFA500",
                hover_color="#DD4E46" if is_connected else "#E69500"
            )
            delete_button.pack(side="right")
            
            # OSC Address Entry
            osc_address = config.get("osc_address", "/avatar/parameters/" + device_name.replace(" ", "_"))
            osc_entry = ctk.CTkEntry(
                device_frame,
                placeholder_text="OSC Address",
                width=250,
                font=("Arial", 12)
            )
            osc_entry.insert(0, osc_address)
            osc_entry.pack(pady=(5, 5))
            
            # Motor controls (sliders + vibe meters) for each motor
            motor_vars = []
            for motor_idx in range(stored_motor_count):
                # Motor label
                motor_label = ctk.CTkLabel(
                    device_frame,
                    text=f"Motor {motor_idx}:",
                    font=("Arial", 12, "bold"),
                    text_color="#FFFFFF"
                )
                motor_label.pack(pady=(5, 2))
                
                # Slider for this specific motor
                slider = ctk.CTkSlider(
                    device_frame,
                    from_=0.0,
                    to=1.0,
                    command=lambda val, name=device_name, m=motor_idx: self.update_device_target(name, val, m),
                    width=250
                )
                slider.set(0.0)
                slider.pack(pady=(0, 5))
                
                # Vibe meter (progress bar) for this motor
                vibe_meter = ctk.CTkProgressBar(
                    device_frame,
                    width=250,
                    height=15
                )
                vibe_meter.set(0.0)
                vibe_meter.pack(pady=(0, 5))
                
                motor_vars.append({
                    "slider": slider,
                    "vibe_meter": vibe_meter
                })
            
            # Store unified frame data with all elements
            self.device_ui_frames[device_name] = {
                "frame": device_frame,
                "osc_entry": osc_entry,
                "status_label": name_label,
                "delete_button": delete_button,
                "motors": motor_vars
            }
            
            # Initialize state for this device
            self.device_targets[(device_name, -1)] = 0.0
            self.device_last_sent[(device_name, -1)] = 0.0
            
            # Also store in stored_device_frames for status updates
            self.stored_device_frames[device_name] = {
                "frame": device_frame,
                "status_label": name_label,
                "delete_button": delete_button
            }
    
    def build_device_list_ui(self, devices_dict: dict):
        """Build dynamic UI controls for each discovered device and merge into unified view
        
        This method updates existing frames or creates new ones for connected devices.
        
        Args:
            devices_dict: Dictionary mapping device.index -> {"name": name, "motor_count": count}
        """
        if not devices_dict:
            # No devices found - clear any placeholder
            return
        
        connected_names = {device.name for device in self.buttplug_client.devices.values()}
        
        # Get actual motor counts from connected devices (if available)
        device_motor_counts = {}
        if self.is_connected and self.buttplug_client:
            for device in self.buttplug_client.devices.values():
                try:
                    features = device.get_features_with_output(OutputType.VIBRATE)
                    device_motor_counts[device.name] = len(features)
                except Exception:
                    pass
        
        # Process each discovered device
        for index, device_info in devices_dict.items():
            # Unpack device info
            if isinstance(device_info, dict):
                device_name = device_info.get("name", f"Device_{index}")
                motor_count = device_info.get("motor_count", 1)
            else:
                device_name = str(device_info)
                motor_count = 1
            
            # Use actual detected motor count if available, otherwise use profile/default
            actual_motor_count = device_motor_counts.get(device_name, motor_count)
            
            self.push_ui_update(f"DEBUG: {device_name} - devices_dict motor_count={motor_count}, actual_motor_count={actual_motor_count}")
            
            # Check if we already have a frame for this device in the unified view
            if device_name not in self.device_ui_frames:
                # Create new frame for this device
                # Get OSC address from profile or use default
                osc_address = self.get_profile_config(device_name, "osc_address", "/avatar/parameters/" + device_name.replace(" ", "_"))
                
                # Store motor count in profile
                self.update_device_config(device_name, "motor_count", motor_count)
                
                # Create frame container for this device with full controls
                device_frame = ctk.CTkFrame(
                    self.unified_devices_frame,
                    corner_radius=8,
                    fg_color="#2A2A3E"
                )
                device_frame.pack(expand=False, fill="x", pady=(0, 10), padx=5)
                
                # Header row: status icon + name + delete button
                header_frame = ctk.CTkFrame(device_frame, fg_color="transparent")
                header_frame.pack(expand=True, fill="x", padx=5, pady=(5, 2))
                
                # Status label with green checkmark for connected device
                name_label = ctk.CTkLabel(
                    header_frame,
                    text=f"✓ {device_name}",
                    font=("Arial", 14, "bold"),
                    text_color="#00C853",
                    anchor="w"
                )
                name_label.pack(side="left")
                
                # Delete button on right
                delete_button = ctk.CTkButton(
                    header_frame,
                    text="Delete",
                    command=lambda name=device_name: self.delete_stored_device(name),
                    font=("Arial", 12),
                    height=30,
                    width=60,
                    fg_color="#FF5E57",
                    hover_color="#DD4E46"
                )
                delete_button.pack(side="right")
                
                # OSC Address Entry (editable)
                osc_entry = ctk.CTkEntry(
                    device_frame,
                    placeholder_text="OSC Address",
                    width=250,
                    font=("Arial", 12)
                )
                osc_entry.insert(0, osc_address)
                osc_entry.pack(pady=(5, 5))
                
                # Motor controls (sliders + vibe meters) for each motor
                motor_vars = []
                for motor_idx in range(actual_motor_count):
                    # Motor label
                    motor_label = ctk.CTkLabel(
                        device_frame,
                        text=f"Motor {motor_idx}:",
                        font=("Arial", 12, "bold"),
                        text_color="#FFFFFF"
                    )
                    motor_label.pack(pady=(5, 2))
                    
                    # Slider for this specific motor
                    slider = ctk.CTkSlider(
                        device_frame,
                        from_=0.0,
                        to=1.0,
                        command=lambda val, name=device_name, m=motor_idx: self.update_device_target(name, val, m),
                        width=250
                    )
                    slider.set(0.0)
                    slider.pack(pady=(0, 5))
                    
                    # Vibe meter (progress bar) for this motor
                    vibe_meter = ctk.CTkProgressBar(
                        device_frame,
                        width=250,
                        height=15
                    )
                    vibe_meter.set(0.0)
                    vibe_meter.pack(pady=(0, 5))
                    
                    motor_vars.append({
                        "slider": slider,
                        "vibe_meter": vibe_meter
                    })
                
                # Store unified frame data with all elements
                self.device_ui_frames[device_name] = {
                    "frame": device_frame,
                    "osc_entry": osc_entry,
                    "status_label": name_label,
                    "delete_button": delete_button,
                    "motors": motor_vars
                }
                
                # Initialize state for this device
                self.device_targets[(device_name, -1)] = 0.0
                self.device_last_sent[(device_name, -1)] = 0.0
                
                # Also store in stored_device_frames for status updates
                self.stored_device_frames[device_name] = {
                    "frame": device_frame,
                    "status_label": name_label,
                    "delete_button": delete_button
                }
        
        self.log_message(f"Connected devices: {len(devices_dict)}")
        
    def update_device_target(self, device_name: str, value: float, motor_index: int):
        """Update target intensity for a specific device and motor
        
        Args:
            device_name: Name of the device
            value: New intensity value (0.0 to 1.0)
            motor_index: Motor index (-1 for all motors, 0+ for specific)
        """
        # Update target in state dictionary using tuple key
        self.device_targets[(device_name, motor_index)] = float(value)
        
        # Update the corresponding vibe meter if we have per-motor frames
        if device_name in self.device_ui_frames:
            frame_data = self.device_ui_frames[device_name]
            if "motors" in frame_data and motor_index >= 0 and motor_index < len(frame_data["motors"]):
                # Update specific motor's vibe meter
                frame_data["motors"][motor_index]["vibe_meter"].set(float(value))
        
        # Also update all-motors entry (for backward compatibility)
        if motor_index != -1:
            self.device_targets[(device_name, -1)] = float(value)
    
    def trigger_purr_check(self):
        """Trigger Purr-Check from main thread"""
        if self.async_loop and self.is_connected:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._async_purr_check(),
                    self.async_loop
                )
                future.result(timeout=3)
            except Exception as e:
                self.push_ui_update(f"Purr-Check failed: {e}")
    
    async def _async_set_vibration(self, intensity: float):
        """Set vibration intensity for all connected devices"""
        if not self.buttplug_client or not self.is_connected:
            return
            
        try:
            for device in self.buttplug_client.devices.values():
                if device.has_output(OutputType.VIBRATE):
                    await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, intensity))
                    
        except Exception as e:
            self.push_ui_update(f"Vibration error: {e}")
    
    async def _async_purr_check(self):
        """Test all devices by setting them to 0.1, waiting 1 second, then 0"""
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
        if not self.buttplug_client:
            return
            
        await self.buttplug_client.connect("ws://127.0.0.1:12345")
        
        # Start scanning for devices after connection
        await self.buttplug_client.start_scanning()
        await asyncio.sleep(2.0)  # Give Intiface time to find devices
        
        # Stop scanning and get device list
        await self.buttplug_client.stop_scanning()
        
        # Construct dictionary of found devices: {index: {"name": name, "motor_count": count}}
        found_devices = {}
        for device in self.buttplug_client.devices.values():
            # Detect motor count by counting vibration features
            # buttplug-py v1.0.0+ API: device.get_features_with_output(OutputType.VIBRATE)
            # This returns a list of DeviceFeature objects that support VIBRATE output
            try:
                features = device.get_features_with_output(OutputType.VIBRATE)
                motor_count = len(features)
                
                self.push_ui_update(f"Detected {motor_count} vibrate feature(s) for {device.name}")
                if hasattr(device, 'features'):
                    self.push_ui_update(f"  Full device features: {len(device.features)} total")
            except Exception as e:
                # Fallback to default of 1 motor
                motor_count = 1
                self.push_ui_update(f"Error detecting features for {device.name}: {e}")
            
            # Default to 1 if no vibration features found (shouldn't happen for vibe toys, but just in case)
            if motor_count == 0:
                motor_count = 1
            
            self.push_ui_update(f"Final motor count for {device.name}: {motor_count} motors")
            
            found_devices[device.index] = {
                "name": device.name,
                "motor_count": motor_count
            }
            
            # Save device info to profile if not already present
            if self.current_profile in self.profiles:
                # Only create the OSC address if it's a brand new device
                if device.name not in self.profiles[self.current_profile]:
                    osc_address = "/avatar/parameters/" + device.name.replace(" ", "_")
                    self.update_device_config(device.name, "osc_address", osc_address)
                
                # ALWAYS update the motor count to match physical hardware
                self.update_device_config(device.name, "motor_count", motor_count)
                self.save_profiles()
        
        # Update connection status before triggering UI rebuild (fixes race condition)
        self.push_connection_status(True, "Intiface")
        
        # Push message to refresh stored devices UI from main thread
        self.push_stored_devices_refresh()
        
        # Send to main thread via queue
        self.thread_queue.put(("devices_found", found_devices))
        
        self.push_ui_update(f"Scan complete. Devices found: {len(self.buttplug_client.devices)}")
    
    async def _async_disconnect(self):
        """Internal async method to disconnect from Intiface"""
        if self.buttplug_client:
            try:
                await self.buttplug_client.disconnect()
            except Exception:
                pass
    
    def connect_to_intiface(self):
        """Handle connection button click - connects/disconnects from main thread"""
        if not self.is_connected:
            # Connect when clicked (if not already connected)
            if self.async_loop and self.buttplug_client:
                try:
                    self.push_ui_update("Connecting to Intiface...")
                    # Schedule the async connect to run in the async thread
                    future = asyncio.run_coroutine_threadsafe(
                        self._async_connect(),
                        self.async_loop
                    )
                    # Wait for result with a timeout
                    future.result(timeout=5)
                    self.push_ui_update("Connected to Intiface successfully")
                except Exception as e:
                    error_msg = f"Connection failed: {e}"
                    self.push_ui_update(error_msg)
                    self.push_connection_status(False, "")
        else:
            # Disconnect when clicked (if connected)
            if self.async_loop and self.buttplug_client:
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._async_disconnect(),
                        self.async_loop
                    )
                    future.result(timeout=2)
                    self.push_connection_status(False, "")
                except Exception as e:
                    pass
    
    async def async_worker(self):
        """Main async worker for buttplug and OSC operations"""
        
        self.push_ui_update("Async thread started")
        
        try:
            # Initialize OSC client
            self.osc_client = SimpleUDPClient("localhost", 9000)
            self.push_ui_update("OSC client initialized (port 9000)")
            
            # Initialize Buttplug client
            self.buttplug_client = ButtplugClient("OscGoesPurrr")
            self.push_ui_update("Buttplug client created")
            
        except Exception as e:
            self.push_ui_update(f"Initialization error: {e}")
        
        # Main async loop - Golden Loop, polls each device's intensity and sends (10Hz polling)
        while True:
            if self.is_connected and self.buttplug_client:
                # Iterate through each discovered device
                for device in self.buttplug_client.devices.values():
                    device_name = device.name
                    
                    # Get all vibration features for this device
                    vibration_features = device.get_features_with_output(OutputType.VIBRATE)
                    
                    # Iterate through all motors for this device and send updates if needed
                    if device_name in self.device_ui_frames:
                        frame_data = self.device_ui_frames[device_name]
                        if "motors" in frame_data:
                            motor_vars = frame_data["motors"]
                            # Send updates for each motor that has a target intensity != 0
                            for motor_idx, motor_data in enumerate(motor_vars):
                                target_intensity = self.device_targets.get((device_name, motor_idx), 0.0)
                                last_sent = self.device_last_sent.get((device_name, motor_idx), 0.0)
                                
                                if target_intensity != last_sent:
                                    try:
                                        if motor_idx < len(vibration_features):
                                            feature = vibration_features[motor_idx]
                                            await feature.run_output(DeviceOutputCommand(OutputType.VIBRATE, target_intensity))
                                        self.device_last_sent[(device_name, motor_idx)] = target_intensity
                                    except Exception as e:
                                        self.push_ui_update(f"Vibration error for {device_name} motor {motor_idx}: {e}")
                                    
                                    # Also update "all motors" entry
                                    if motor_idx == 0:  # Only update once (use first motor as trigger)
                                        self.device_last_sent[(device_name, -1)] = target_intensity
            
            await asyncio.sleep(0.1)  # Poll at 10Hz to avoid rate-limit crashes
    
    def run(self):
        """Start the Three-Pillar application"""
        # Start async loop in background thread
        self.start_async_loop()
        
        # Periodically check for UI updates from async thread
        def check_queue():
            self.process_async_queue()
            self.app.after(50, check_queue)  # Check every 50ms
            
        self.app.after(100, check_queue)
        
        # Run GUI mainloop on main thread
        self.app.mainloop()


if __name__ == "__main__":
    app = OscGoesPurrrApp()
    app.run()