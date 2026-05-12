# OscGoesPurrr - UI Components Module
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

import customtkinter as ctk


class OscGoesPurrrUI:
    """UI Component class - handles all GUI rendering and updates"""
    
    def __init__(self, app_root: ctk.CTk, controller):
        """
        Initialize the UI component.
        
        Args:
            app_root: The main customtkinter application window
            controller: Reference to the main application controller
        """
        self.app = app_root
        self.controller = controller
        
        # GUI State - moved from main.py
        self.status_label = None
        self.connection_button = None
        self.testing_frame = None
        self.purr_check_button = None
        self.devices_container_frame = None
        self.unified_devices_frame = None
        self.log_text = None
        
        # Stored devices UI tracking - moved from main.py
        self.stored_device_frames: dict = {}  # device_name -> frame references
        
        # Device-specific state - moved from main.py
        self.device_ui_frames: dict = {}  # device_name -> config UI frame references
        
        # Sidebar Navigation State
        self.sidebar_frame = None
        self.main_frame = None
        self.nav_buttons: dict = {}
        self.views: dict = {}
        
        # Setup the UI
        self.setup_ui()
    
    def setup_ui(self):
        """Create and arrange all GUI elements with sidebar navigation"""
        # Configure main grid: 1 row, 2 columns
        # Column 0 (Sidebar) has fixed width, Column 1 (Main Content) expands
        self.app.grid_rowconfigure(0, weight=1)
        self.app.grid_columnconfigure(1, weight=1)
        
        # ====================
        # SIDEBAR (Column 0)
        # ====================
        self.sidebar_frame = ctk.CTkFrame(self.app, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        
        # Configure sidebar grid - row 6 expands to push bottom elements down
        self.sidebar_frame.grid_rowconfigure(6, weight=1)
        
        # Title Label at top of sidebar
        title_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="OscGoesPurrr",
            font=("Arial", 24, "bold"),
            text_color="#6B4EFF"
        )
        title_label.grid(row=0, column=0, sticky="ew", padx=10, pady=(20, 30))
        
        # Navigation Buttons
        view_names = ["VR Dashboard", "OSC Routing", "Hardware Tester", "Settings", "Help"]
        
        for i, view_name in enumerate(view_names, start=1):
            nav_button = ctk.CTkButton(
                self.sidebar_frame,
                text=view_name,
                command=lambda name=view_name: self.select_view(name),
                font=("Arial", 14),
                height=40,
                fg_color="transparent",
                hover_color="#3a3a45"
            )
            nav_button.grid(row=i, column=0, sticky="ew", padx=10, pady=5)
            self.nav_buttons[view_name] = nav_button
        
        # Status Label - at bottom of sidebar (row 7)
        self.status_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="Ready to connect",
            font=("Arial", 12),
            text_color="#888888"
        )
        self.status_label.grid(row=7, column=0, sticky="ew", padx=15, pady=(0, 5))
        
        # Connection Button - at bottom of sidebar (row 8)
        self.connection_button = ctk.CTkButton(
            self.sidebar_frame,
            text="Connect to Intiface",
            command=self.controller.connect_to_intiface,
            font=("Arial", 12),
            height=40,
            fg_color="#6B4EFF",
            hover_color="#5A3DCC"
        )
        self.connection_button.grid(row=8, column=0, sticky="ew", padx=15, pady=(0, 10))
        
        # Auto-refresh checkbox - below connection button (row 9)
        # Load saved state from config, default to True
        auto_refresh_default = True
        if hasattr(self.controller, 'profile_manager') and self.controller.profile_manager:
            auto_refresh_default = self.controller.profile_manager.app_settings.get("auto_refresh", True)
        self.auto_refresh_var = ctk.BooleanVar(value=auto_refresh_default)
        self.auto_refresh_checkbox = ctk.CTkCheckBox(
            self.sidebar_frame,
            text="Auto Refresh Devices",
            variable=self.auto_refresh_var,
            command=self.controller.toggle_auto_refresh
        )
        self.auto_refresh_checkbox.grid(row=9, column=0, sticky="ew", padx=15, pady=(0, 10))
        
        # Auto-connect checkbox - below auto-refresh (row 10)
        # Load saved state from config, default to True
        auto_connect_default = True
        if hasattr(self.controller, 'profile_manager') and self.controller.profile_manager:
            auto_connect_default = self.controller.profile_manager.app_settings.get("auto_connect", True)
        self.auto_connect_var = ctk.BooleanVar(value=auto_connect_default)
        self.auto_connect_checkbox = ctk.CTkCheckBox(
            self.sidebar_frame,
            text="Auto Connect",
            variable=self.auto_connect_var,
            command=self.controller.toggle_auto_connect
        )
        self.auto_connect_checkbox.grid(row=10, column=0, sticky="ew", padx=15, pady=(0, 20))
        
        # ====================
        # MAIN CONTENT AREA (Column 1)
        # ====================
        self.main_frame = ctk.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        
        # Create views dictionary and frames
        view_names = ["VR Dashboard", "OSC Routing", "Hardware Tester", "Settings", "Help"]
        
        for view_name in view_names:
            view_frame = ctk.CTkFrame(self.main_frame, corner_radius=8, fg_color="transparent")
            
            if view_name == "Hardware Tester":
                # Hardware Tester: Contains the migrated existing UI
                self._setup_hardware_tester_view(view_frame)
            else:
                # Placeholder for other views
                placeholder_label = ctk.CTkLabel(
                    view_frame,
                    text=f"{view_name} will go here",
                    font=("Arial", 16),
                    text_color="#888888"
                )
                placeholder_label.pack(expand=True)
            
            self.views[view_name] = view_frame
        
        # Default to Hardware Tester view
        self.select_view("Hardware Tester")
    
    def _setup_hardware_tester_view(self, parent_frame: ctk.CTkFrame):
        """Setup the Hardware Tester view with migrated existing UI elements"""
        # Title for Hardware Tester section
        title_label = ctk.CTkLabel(
            parent_frame,
            text="Hardware Tester",
            font=("Arial", 28, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 10))
        
        
        # Manual Purr Testing Frame (now only for Purr-Check)
        self.testing_frame = ctk.CTkFrame(parent_frame, corner_radius=8)
        self.testing_frame.pack(expand=False, fill="x", pady=(10, 20))
        
        # Purr-Check Button
        self.purr_check_button = ctk.CTkButton(
            self.testing_frame,
            text="Purr-Check (Test All)",
            command=self.controller.trigger_purr_check,
            font=("Arial", 14),
            height=40
        )
        self.purr_check_button.pack(pady=(0, 10))
        
        # Unified Devices Frame - contains saved toys and active controls
        self.devices_container_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="#1E1E2E")
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
        
        # Save Profiles Button
        save_profiles_button = ctk.CTkButton(
            self.devices_container_frame,
            text="Save Profiles",
            command=self.controller.save_all_profiles,
            font=("Arial", 14),
            height=40,
            fg_color="#2E8B57",
            hover_color="#277A4D"
        )
        save_profiles_button.pack(pady=(0, 10))
        
        # Log/Output Box
        log_frame = ctk.CTkFrame(parent_frame, corner_radius=8)
        log_frame.pack(expand=False, fill="both", pady=(0, 10))
        
        self.log_text = ctk.CTkTextbox(
            log_frame,
            font=("Courier New", 12),
            state="disabled",
            fg_color="#1E1E2E"
        )
        self.log_text.pack(expand=False, fill="both", padx=10, pady=10)
    
    def select_view(self, view_name: str):
        """
        Switch between different views in the UI.
        
        Args:
            view_name: Name of the view to switch to
        """
        # 1. Update button colors (highlight active tab)
        for name, button in self.nav_buttons.items():
            if name == view_name:
                button.configure(fg_color=("#333333", "#2B2B36"))  # Active color
            else:
                button.configure(fg_color="transparent")  # Inactive color
        
        # 2. Hide all views
        for frame in self.views.values():
            frame.pack_forget()
        
        # 3. Show selected view
        self.views[view_name].pack(expand=True, fill="both", padx=20, pady=20)
    
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"> {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
    
    def update_connection_status(self, connected: bool, server: str):
        """Update connection UI elements (main thread only)"""
        # Also sync with haptic engine via controller
        if hasattr(self.controller, 'haptic_engine') and self.controller.haptic_engine:
            self.controller.haptic_engine.is_connected = connected
        
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
    
    def update_stored_devices_ui(self):
        """Update the stored devices UI to show connection status"""
        # Get currently connected devices via controller
        connected_names = self.controller.get_connected_device_names()
        
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
    
    def _create_device_frame(self, device_name: str, is_connected: bool, osc_address: str, motor_count: int) -> dict:
        """
        Create a UI frame for a device with all controls.
        
        This helper method extracts the common frame creation logic used by both
        build_stored_devices_ui() and build_device_list_ui().
        
        Args:
            device_name: Name of the device
            is_connected: Whether the device is currently connected (determines status color)
            osc_address: OSC address for this device
            motor_count: Number of motors/vibration features on the device
            
        Returns:
            Dictionary containing frame data with keys:
                - frame: The device frame widget
                - osc_entry: The OSC address entry widget
                - status_label: The status label widget
                - delete_button: The delete button widget
                - motors: List of motor control dictionaries with 'slider' and 'vibe_meter'
        """
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
        
        # Status label (icon only) - green for connected, yellow otherwise
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
            command=lambda name=device_name: self.controller.delete_stored_device(name),
            font=("Arial", 12),
            height=30,
            width=60,
            fg_color="#FF5E57" if is_connected else "#FFA500",
            hover_color="#DD4E46" if is_connected else "#E69500"
        )
        delete_button.pack(side="right")
        
        # OSC Address Entry
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
        for motor_idx in range(motor_count):
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
                command=lambda val, name=device_name, m=motor_idx: self.controller.update_device_target(name, val, m),
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
        
        # Return unified frame data with all elements
        return {
            "frame": device_frame,
            "osc_entry": osc_entry,
            "status_label": name_label,
            "delete_button": delete_button,
            "motors": motor_vars
        }
    
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
        controller = self.controller
        
        # Get connected device names via controller
        connected_names = controller.get_connected_device_names()
        
        # Check if we have any saved devices in this profile via controller
        has_saved_devices = bool(controller.profiles.get(controller.current_profile))
        
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
        
        # Get actual motor counts from connected devices (if available) via controller
        device_motor_counts = {}
        if controller.haptic_engine and controller.haptic_engine.is_connected and controller.haptic_engine.buttplug_client:
            try:
                from haptic_engine import OutputType
                for device in controller.haptic_engine.buttplug_client.devices.values():
                    try:
                        features = device.get_features_with_output(OutputType.VIBRATE)
                        device_motor_counts[device.name] = len(features)
                    except Exception:
                        pass
            except Exception:
                pass
        
        for device_name, config in controller.profiles[controller.current_profile].items():
            # Determine if connected (green) or saved but not connected (yellow)
            is_connected = device_name in connected_names
            
            # Get motor count from detected values first, then profile, then default to 1
            stored_motor_count = device_motor_counts.get(device_name, config.get("motor_count", 1))
            
            # Get OSC address from config or use default
            osc_address = config.get("osc_address", "/avatar/parameters/" + device_name.replace(" ", "_"))
            
            # Create frame using the helper method
            frame_data = self._create_device_frame(
                device_name=device_name,
                is_connected=is_connected,
                osc_address=osc_address,
                motor_count=stored_motor_count
            )
            
            # Store unified frame data with all elements
            self.device_ui_frames[device_name] = frame_data
            
            # Initialize state for this device via controller
            controller.device_targets[(device_name, -1)] = 0.0
            controller.device_last_sent[(device_name, -1)] = 0.0
            
            # Also store in stored_device_frames for status updates
            self.stored_device_frames[device_name] = {
                "frame": frame_data["frame"],
                "status_label": frame_data["status_label"],
                "delete_button": frame_data["delete_button"]
            }
    
    def build_device_list_ui(self, devices_dict: dict):
        """Build dynamic UI controls for each discovered device and merge into unified view
        
        This method updates existing frames or creates new ones for connected devices.
        
        Args:
            devices_dict: Dictionary mapping device.index -> {"name": name, "motor_count": count}
        """
        controller = self.controller
        
        if not devices_dict:
            # No devices found - clear any placeholder
            return
        
        connected_names = {device.name for device in controller.haptic_engine.buttplug_client.devices.values()}
        
        # Get actual motor counts from connected devices (if available)
        device_motor_counts = {}
        if controller.haptic_engine and controller.haptic_engine.is_connected and controller.haptic_engine.buttplug_client:
            try:
                from haptic_engine import OutputType
                for device in controller.haptic_engine.buttplug_client.devices.values():
                    try:
                        features = device.get_features_with_output(OutputType.VIBRATE)
                        device_motor_counts[device.name] = len(features)
                    except Exception:
                        pass
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
            
            controller.log_message(f"DEBUG: {device_name} - devices_dict motor_count={motor_count}, actual_motor_count={actual_motor_count}")
            
            # Check if we already have a frame for this device in the unified view
            if device_name not in self.device_ui_frames:
                # Create new frame for this device
                # Get OSC address from profile or use default via controller
                osc_address = controller.get_profile_config(device_name, "osc_address", "/avatar/parameters/" + device_name.replace(" ", "_"))
                
                # Store motor count in profile via controller
                controller.update_device_config(device_name, "motor_count", motor_count)
                
                # Device is connected since it was just discovered, so use green checkmark
                frame_data = self._create_device_frame(
                    device_name=device_name,
                    is_connected=True,
                    osc_address=osc_address,
                    motor_count=actual_motor_count
                )
                
                # Store unified frame data with all elements
                self.device_ui_frames[device_name] = frame_data
                
                # Initialize state for this device via controller
                controller.device_targets[(device_name, -1)] = 0.0
                controller.device_last_sent[(device_name, -1)] = 0.0
                
                # Also store in stored_device_frames for status updates
                self.stored_device_frames[device_name] = {
                    "frame": frame_data["frame"],
                    "status_label": frame_data["status_label"],
                    "delete_button": frame_data["delete_button"]
                }
        
        controller.log_message(f"Connected devices: {len(devices_dict)}")