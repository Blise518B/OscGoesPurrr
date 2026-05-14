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
from constants import *


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
        
        # GUI State
        self.status_label = None
        self.connection_button = None
        self.testing_frame = None
        self.purr_check_button = None
        self.devices_container_frame = None
        self.unified_devices_frame = None
        self.log_text = None
        
        # Stored devices UI tracking
        self.stored_device_frames: dict = {}  # device_name -> frame references
        
        # Device-specific state
        self.device_ui_frames: dict = {}  # device_name -> config UI frame references
        
        # Sidebar Navigation State
        self.sidebar_frame = None
        self.main_frame = None
        self.nav_buttons: dict = {}
        self.views: dict = {}
        
        # OSC Routing Dashboard State
        self.osc_status_label = None
        self.osc_port_label = None
        
        # OSC Debugger State
        self.debugger_textbox = None
        
        # Profile Selector State
        self.profile_selector = None
        
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
        self.sidebar_frame = ctk.CTkFrame(self.app, width=SIDEBAR_WIDTH, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        
        # Configure sidebar grid - row 7 expands to push bottom elements to bottom
        self.sidebar_frame.grid_rowconfigure(7, weight=1)
        
        # Title Label at top of sidebar
        title_label = ctk.CTkLabel(
            self.sidebar_frame,
            text="OscGoesPurrr",
            font=("Arial", 24, "bold"),
            text_color="#6B4EFF"
        )
        title_label.grid(row=0, column=0, sticky="ew", padx=10, pady=(20, 30))
        
        # Navigation Buttons - New order
        nav_buttons = ["Dashboard", "Device Routing", "Network & Debug", "System Log", "Settings", "Help"]
        
        for i, view_name in enumerate(nav_buttons, start=1):
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
        
        # ====================
        # BOTTOM SIDEBAR FRAME - Anchored to bottom via row 7 weight=1 expansion
        # Contains VRChat OSC status + Intiface Central connection status (no checkboxes)
        # ====================
        bottom_sidebar_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        bottom_sidebar_frame.grid(row=8, column=0, sticky="sew", padx=10, pady=(0, 20))
        
        # --- VRChat OSC Section ---
        ctk.CTkLabel(bottom_sidebar_frame, text="VRChat OSC", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(0, 2))
        
        self.osc_status_label = ctk.CTkLabel(bottom_sidebar_frame, text="Status: Waiting for VRChat...", text_color=COLOR_WARNING)
        self.osc_status_label.pack(pady=(0, 0))
        
        self.osc_port_label = ctk.CTkLabel(bottom_sidebar_frame, text="Listening on Port: --")
        self.osc_port_label.pack(pady=(0, 5))

        self.osc_connection_button = ctk.CTkButton(
            bottom_sidebar_frame,
            text="Connect to VRChat",
            command=self.controller.toggle_osc_connection,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=BTN_HEIGHT_LARGE,
            fg_color=COLOR_BTN_PRIMARY, # Neutral Purple
            hover_color=COLOR_BTN_PRIMARY_HOVER
        )
        self.osc_connection_button.pack(pady=(0, 5))

        self.osc_auto_connect_checkbox = ctk.CTkCheckBox(bottom_sidebar_frame, text="Auto Connect", font=ctk.CTkFont(size=12), command=self.controller.toggle_osc_auto_connect)
        self.osc_auto_connect_checkbox.pack(pady=(0, 15))
        # Initialize checkbox state from app settings
        if self.controller.profile_manager.app_settings.get("auto_connect_osc", True):
            self.osc_auto_connect_checkbox.select()

        # --- Separator Line ---
        separator = ctk.CTkFrame(bottom_sidebar_frame, height=2, fg_color=COLOR_SEPARATOR)
        separator.pack(fill="x", padx=15, pady=(0, 15))

        # --- Intiface Central Section ---
        ctk.CTkLabel(bottom_sidebar_frame, text="Intiface Central", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(0, 2))
        
        self.status_label = ctk.CTkLabel(bottom_sidebar_frame, text="Status: Disconnected", text_color=COLOR_WARNING)
        self.status_label.pack(pady=(0, 5))

        self.connection_button = ctk.CTkButton(
            bottom_sidebar_frame,
            text="Connect to Intiface",
            command=self.controller.connect_to_intiface,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=BTN_HEIGHT_LARGE,
            fg_color=COLOR_BTN_PRIMARY, # Neutral Purple
            hover_color=COLOR_BTN_PRIMARY_HOVER
        )
        self.connection_button.pack(pady=(0, 5))

        self.auto_connect_checkbox = ctk.CTkCheckBox(bottom_sidebar_frame, text="Auto Connect", font=ctk.CTkFont(size=12), command=self.controller.toggle_auto_connect)
        self.auto_connect_checkbox.pack(pady=(0, 10))
        # Initialize checkbox state from app settings
        if self.controller.profile_manager.app_settings.get("auto_connect", True):
            self.auto_connect_checkbox.select()
        
        # ====================
        # MAIN CONTENT AREA (Column 1)
        # ====================
        self.main_frame = ctk.CTkFrame(self.app, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        
        # Create views dictionary and frames
        view_names = ["Dashboard", "Device Routing", "Network & Debug", "System Log", "Settings", "Help"]
        
        for view_name in view_names:
            view_frame = ctk.CTkFrame(self.main_frame, corner_radius=8, fg_color="transparent")
            
            if view_name == "Dashboard":
                self._setup_dashboard_view(view_frame)
            elif view_name == "Device Routing":
                self._setup_device_routing_view(view_frame)
            elif view_name == "Network & Debug":
                self._setup_network_debug_view(view_frame)
            elif view_name == "System Log":
                self._setup_system_log_view(view_frame)
            elif view_name == "Settings":
                self._setup_settings_view(view_frame)
            else:
                # Placeholder for Help view
                placeholder_label = ctk.CTkLabel(
                    view_frame,
                    text=f"{view_name} will go here",
                    font=("Arial", 16),
                    text_color="#888888"
                )
                placeholder_label.pack(expand=True)
            
            self.views[view_name] = view_frame
        
        # Default to Dashboard view
        self.select_view("Dashboard")
    
    def _setup_dashboard_view(self, parent_frame: ctk.CTkFrame):
        """Setup the Dashboard view with profile selector and Purr-Check button"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
            text="Dashboard",
            font=("Arial", 28, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 15))
        
        # ---- Profile Selector Frame (4 configurable profile buttons) ----
        profile_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="transparent")
        profile_frame.pack(expand=False, fill="x", padx=20, pady=(0, 15))
        
        profile_header = ctk.CTkLabel(
            profile_frame,
            text="Active Profile",
            font=("Arial", 16, "bold"),
            text_color="#FFFFFF"
        )
        profile_header.pack(anchor="w", pady=(0, 8))
        
        # Create a row of 4 profile buttons
        profile_buttons_frame = ctk.CTkFrame(profile_frame, fg_color="transparent")
        profile_buttons_frame.pack(expand=False, fill="x")
        
        self.profile_buttons = []
        current_profile = self.controller.profile_manager.current_profile
        
        for i in range(4):
            # Get profile name (use existing profiles or default names)
            profile_keys = list(self.controller.profile_manager.profiles.keys())
            if i < len(profile_keys):
                profile_name = profile_keys[i]
            else:
                profile_name = f"Profile {i + 1}"
            
            is_active = (profile_name == current_profile)
            
            btn = ctk.CTkButton(
                profile_buttons_frame,
                text=profile_name,
                font=("Arial", 13),
                height=36,
                width=0,
                fg_color="#6B4EFF" if is_active else "#2A2A3E",
                hover_color="#5A3DCC" if is_active else "#3A3A4A",
                text_color="#FFFFFF",
                corner_radius=6,
                command=lambda name=profile_name: self.controller.switch_profile(name)
            )
            btn.grid(row=0, column=i, padx=(0, 8), sticky="ew")
            
            # Bind double-click (Double-<Button-1>) to rename
            btn.bind("<Double-Button-1>", lambda e, b=btn, idx=i: self._start_profile_rename(b, idx))
            
            self.profile_buttons.append(btn)
        
        # Purr Testing Frame
        self.testing_frame = ctk.CTkFrame(parent_frame, corner_radius=8)
        self.testing_frame.pack(expand=True, fill="x", pady=(0, 20))
        
        # Purr-Check Button
        self.purr_check_button = ctk.CTkButton(
            self.testing_frame,
            text="Purr-Check (Test All)",
            command=self.controller.trigger_purr_check,
            font=("Arial", 14),
            height=40
        )
        self.purr_check_button.pack(pady=(0, 10))
    
    def _start_profile_rename(self, button_widget, index):
        """Start renaming a profile by replacing the button with an entry field"""
        current_name = button_widget.cget("text")
        
        # Destroy the button in its grid cell
        button_widget.grid_forget()
        
        # Create frame to hold entry + confirm button
        rename_frame = ctk.CTkFrame(self.profile_buttons[index].grid_info()['in'] if hasattr(self.profile_buttons[index], 'grid_info') else button_widget.master, fg_color="transparent")
        
        # Actually place it in the parent of the buttons frame
        parent = button_widget.master
        
        entry = ctk.CTkEntry(
            parent,
            font=("Arial", 13),
            width=120,
            height=BTN_HEIGHT_SMALL
        )
        entry.insert(0, current_name)
        
        # Find the grid position of the replaced button and place the entry there
        # We need to temporarily use the grid slot
        row_info = {"row": 0, "column": index}
        
        def confirm_rename():
            new_name = entry.get().strip()
            if new_name and new_name != current_name:
                self.controller.rename_profile(current_name, new_name)
            # Rebuild the profile buttons after rename
            self._refresh_profile_buttons()
        
        entry.bind("<Return>", lambda e: confirm_rename())
        entry.bind("<Escape>", lambda e: self._refresh_profile_buttons())
        
        entry.focus_set()
        
        # Replace button with entry in the grid
        for child in parent.winfo_children():
            if isinstance(child, ctk.CTkButton):
                info = child.grid_info()
                if info and info.get('column') == index:
                    child.grid_forget()
                    break
        
        entry.grid(row=0, column=index, padx=(0, 8), sticky="ew")
        
        # Store reference so we can clean up
        self._rename_entry = entry
    
    def _refresh_profile_buttons(self):
        """Rebuild the 4 profile buttons in the Dashboard"""
        parent = None
        for btn in self.profile_buttons:
            if btn.master:
                parent = btn.master
                break
        
        if not parent:
            return
        
        # Clear existing children from the buttons frame
        for child in parent.winfo_children():
            child.destroy()
        
        self.profile_buttons = []
        current_profile = self.controller.profile_manager.current_profile
        profile_keys = list(self.controller.profile_manager.profiles.keys())
        
        for i in range(4):
            if i < len(profile_keys):
                profile_name = profile_keys[i]
            else:
                profile_name = f"Profile {i + 1}"
            
            is_active = (profile_name == current_profile)
            
            btn = ctk.CTkButton(
                parent,
                text=profile_name,
                font=("Arial", 13),
                height=36,
                width=0,
                fg_color="#6B4EFF" if is_active else "#2A2A3E",
                hover_color="#5A3DCC" if is_active else "#3A3A4A",
                text_color="#FFFFFF",
                corner_radius=6,
                command=lambda name=profile_name: self.controller.switch_profile(name)
            )
            btn.grid(row=0, column=i, padx=(0, 8), sticky="ew")
            
            btn.bind("<Double-Button-1>", lambda e, b=btn, idx=i: self._start_profile_rename(b, idx))
            
            self.profile_buttons.append(btn)
    
    def _setup_device_routing_view(self, parent_frame: ctk.CTkFrame):
        """Setup the Device Routing view (formerly Hardware Tester) - no save button"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
            text="Device Routing",
            font=("Arial", 28, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 10))
        
        # Unified Devices Frame - contains saved toys and active controls
        self.devices_container_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="#1E1E2E")
        self.devices_container_frame.pack(expand=True, fill="both", pady=(0, 10), padx=5)
        
        # Header for devices section
        devices_header_label = ctk.CTkLabel(
            self.devices_container_frame,
            text="Toys",
            font=("Arial", 16, "bold"),
            text_color="#FFFFFF"
        )
        devices_header_label.pack(pady=(10, 5))
        
        # Unified devices scrollable frame
        self.unified_devices_frame = ctk.CTkScrollableFrame(
            self.devices_container_frame,
            corner_radius=8,
            fg_color="transparent",
            height=250
        )
        self.unified_devices_frame.pack(expand=True, fill="both", pady=(5, 10), padx=5)
    
    def _setup_network_debug_view(self, parent_frame: ctk.CTkFrame):
        """Setup the Network & Debug view with OSC restart button and real-time debugger"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
            text="Network & Debug",
            font=("Arial", 28, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 20))
        
        # --- OSC Controls Frame ---
        osc_controls_frame = ctk.CTkFrame(
            parent_frame,
            corner_radius=8,
            fg_color="#1E1E2E"
        )
        osc_controls_frame.pack(expand=False, fill="x", padx=20, pady=(0, 20))
        
        # Note: VRChat OSC status moved to sidebar bottom frame
        controls_title = ctk.CTkLabel(
            osc_controls_frame,
            text="VRChat OSC Controls",
            font=("Arial", 18, "bold"),
            text_color="#FFFFFF"
        )
        controls_title.pack(pady=(15, 10))
        
        # Manual Reconnect Button
        reconnect_button = ctk.CTkButton(
            osc_controls_frame,
            text="Restart OSC Server",
            command=self.controller.restart_osc,
            font=("Arial", 12),
            height=BTN_HEIGHT_SMALL,
            fg_color=COLOR_BTN_SECONDARY,
            hover_color=COLOR_BTN_SECONDARY_HOVER
        )
        reconnect_button.pack(pady=(10, 15))
        
        # --- Real-Time OSC Debugger Section ---
        debugger_title = ctk.CTkLabel(
            parent_frame,
            text="Real-Time OSC Inspector",
            font=("Arial", 20, "bold"),
            text_color="#6B4EFF"
        )
        debugger_title.pack(pady=(10, 10))
        
        # Toggle Button Frame
        button_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="transparent")
        button_frame.pack(expand=False, fill="x", padx=20, pady=(0, 10))
        
        # Toggle button
        toggle_button = ctk.CTkButton(
            button_frame,
            text="Start OSC Debugger",
            command=self.controller.toggle_osc_debugger,
            font=("Arial", 14),
            height=40,
            fg_color="#6B4EFF",
            hover_color="#5A3DCC"
        )
        toggle_button.pack(pady=(0, 10))
        
        # Debugger Textbox Frame
        textbox_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="#1E1E2E")
        textbox_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))
        
        # Header label inside textbox frame
        debugger_header = ctk.CTkLabel(
            textbox_frame,
            text="Live OSC Variables (toggle to start)",
            font=("Arial", 14, "bold"),
            text_color="#888888"
        )
        debugger_header.pack(pady=(10, 5))
        
        # Large textbox for displaying variables
        self.debugger_textbox = ctk.CTkTextbox(
            textbox_frame,
            font=("Courier New", 12),
            state="disabled",
            fg_color="#1E1E2E",
            corner_radius=0
        )
        self.debugger_textbox.pack(expand=True, fill="both", padx=10, pady=(0, 10))
    
    def _setup_system_log_view(self, parent_frame: ctk.CTkFrame):
        """Setup the System Log view with the main log textbox"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
            text="System Log",
            font=("Arial", 28, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 10), fill="x")
        
        # Log Textbox - fills entire remaining frame
        self.log_text = ctk.CTkTextbox(
            parent_frame,
            font=("Courier New", 12),
            state="disabled",
            fg_color="#1E1E2E"
        )
        self.log_text.pack(expand=True, fill="both", padx=5, pady=(0, 5))
    
    def _setup_settings_view(self, parent_frame: ctk.CTkFrame):
        """Setup the Settings view with application configuration controls"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
            text="Application Settings",
            font=("Arial", 28, "bold"),
            text_color="#6B4EFF"
        )
        title_label.pack(pady=(0, 20))
        
        # Settings Dashboard Frame
        settings_frame = ctk.CTkFrame(
            parent_frame,
            corner_radius=8,
            fg_color="#1E1E2E"
        )
        settings_frame.pack(expand=False, fill="x", padx=20, pady=(0, 20))
        
        # Section Header
        section_label = ctk.CTkLabel(
            settings_frame,
            text="Network Configuration",
            font=("Arial", 18, "bold"),
            text_color="#FFFFFF"
        )
        section_label.pack(pady=(15, 10))
        
        # Fetch current bind_all_interfaces value
        bind_val = self.controller.profile_manager.app_settings.settings.get("bind_all_interfaces", True)
        
        # BooleanVar for the switch
        self.network_bind_var = ctk.BooleanVar(value=bind_val)
        
        # Network Bind Switch
        network_switch = ctk.CTkSwitch(
            settings_frame,
            text="Network Bind (0.0.0.0 vs 127.0.0.1)",
            variable=self.network_bind_var,
            command=lambda value=self.network_bind_var.get(): self.controller.toggle_network_bind(value),
            font=("Arial", 14)
        )
        network_switch.pack(pady=(5, 5))
        
        # If initial value is True, select the switch; otherwise deselect
        if bind_val:
            network_switch.select()
        else:
            network_switch.deselect()
        
        # Warning label
        warning_label = ctk.CTkLabel(
            settings_frame,
            text="* 0.0.0.0 is recommended for VRChat Discovery. Requires app restart if changed.",
            font=("Arial", 11),
            text_color="#FDB914"
        )
        warning_label.pack(pady=(5, 15))
        
        # ====================
        # Connection Settings Section
        # ====================
        conn_section_label = ctk.CTkLabel(
            settings_frame,
            text="Connection Settings",
            font=("Arial", 18, "bold"),
            text_color="#FFFFFF"
        )
        conn_section_label.pack(pady=(15, 10))
        
        # Auto Refresh Devices checkbox
        auto_refresh_default = self.controller.profile_manager.app_settings.get("auto_refresh", True)
        self.auto_refresh_var = ctk.BooleanVar(value=auto_refresh_default)
        auto_refresh_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="Auto Refresh Devices",
            variable=self.auto_refresh_var,
            command=self.controller.toggle_auto_refresh,
            font=("Arial", 14)
        )
        auto_refresh_checkbox.pack(pady=(5, 5))
        if auto_refresh_default:
            auto_refresh_checkbox.select()
        
        # Auto Connect (Intiface) checkbox
        auto_connect_default = self.controller.profile_manager.app_settings.get("auto_connect", True)
        self.auto_connect_var = ctk.BooleanVar(value=auto_connect_default)
        auto_connect_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="Auto Connect (Intiface)",
            variable=self.auto_connect_var,
            command=self.controller.toggle_auto_connect,
            font=("Arial", 14)
        )
        auto_connect_checkbox.pack(pady=(5, 5))
        if auto_connect_default:
            auto_connect_checkbox.select()
        
        # Auto Connect (VRChat OSC) checkbox
        auto_connect_osc_default = self.controller.profile_manager.app_settings.get("auto_connect_osc", True)
        self.osc_auto_connect_var = ctk.BooleanVar(value=auto_connect_osc_default)
        osc_auto_connect_checkbox = ctk.CTkCheckBox(
            settings_frame,
            text="Auto Connect (VRChat OSC)",
            variable=self.osc_auto_connect_var,
            command=self.controller.toggle_osc_auto_connect,
            font=("Arial", 14)
        )
        osc_auto_connect_checkbox.pack(pady=(5, 10))
        if auto_connect_osc_default:
            osc_auto_connect_checkbox.select()
    
    def select_view(self, view_name: str):
        """
        Switch between different views in the UI.
        
        Args:
            view_name: Name of the view to switch to
        """
        # 1. Update button colors (highlight active tab)
        for name, button in self.nav_buttons.items():
            if name == view_name:
                button.configure(fg_color=COLOR_TAB_ACTIVE)  # Active color
            else:
                button.configure(fg_color="transparent")  # Inactive color
        
        # 2. Hide all views
        for frame in self.views.values():
            frame.pack_forget()
        
        # 3. Show selected view
        self.views[view_name].pack(expand=True, fill="both", padx=20, pady=20)
    
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        if self.log_text:
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
                text="Disconnect from Intiface",
                fg_color=COLOR_BTN_DELETE,
                hover_color=COLOR_BTN_DELETE_HOVER
            )
            self.status_label.configure(
                text="Status: Connected to Intiface ✓",
                text_color="#00C853"
            )
        else:
            self.connection_button.configure(
                text="Connect to Intiface",
                fg_color=COLOR_BTN_PRIMARY, # Neutral Purple (matches sidebar default)
                hover_color=COLOR_BTN_PRIMARY_HOVER
            )
            self.status_label.configure(
                text="Status: Disconnected",
                text_color=COLOR_WARNING
            )
        
        # Update stored devices status indicators
        self.update_stored_devices_ui()
    
    def update_osc_status(self, is_connected: bool, port: int = None):
        """Update the OSC Routing dashboard with current connection status (main thread only)"""
        if is_connected:
            self.osc_status_label.configure(text="Status: Connected to VRChat", text_color=COLOR_SUCCESS)
            if port:
                self.osc_port_label.configure(text=f"Listening on Port: {port}")
            if self.osc_connection_button:
                self.osc_connection_button.configure(text="Disconnect VRChat", fg_color=COLOR_BTN_DELETE, hover_color=COLOR_BTN_DELETE_H
        else:
            self.osc_status_label.configure(text="Status: Waiting for VRChat...", text_color=COLOR_WARNING)
            self.osc_port_label.configure(text="Listening on Port: --")
            if self.osc_connection_button:
                self.osc_connection_button.configure(text="Connect to VRChat", fg_color=COLOR_BTN_PRIMARY, hover_color=COLOR_BTN_PRIMARY_HOVER)
    
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
                    delete_button.configure(state="normal", fg_color=COLOR_BTN_DELETE, hover_color=COLOR_BTN_DELETE_HOVER)
                else:
                    # Not connected - show yellow warning
                    status_label.configure(text=f"⚠ {device_name}", text_color="#FDB914")
                    delete_button.configure(state="normal", fg_color="#FFA500", hover_color="#E69500")
    
    def _create_device_frame(self, device_name: str, is_connected: bool, osc_addresses: dict, motor_count: int) -> dict:
        """
        Create a UI frame for a device with all controls.
        
        This helper method extracts the common frame creation logic used by both
        build_stored_devices_ui() and build_device_list_ui().
        
        Args:
            device_name: Name of the device
            is_connected: Whether the device is currently connected (determines status color)
            osc_addresses: Dict mapping motor index string -> OSC address (e.g. {"0": "/param/0", "1": "/param/1"})
            motor_count: Number of motors/vibration features on the device
            
        Returns:
            Dictionary containing frame data with keys:
                - frame: The device frame widget
                - status_label: The status label widget
                - delete_button: The delete button widget
                - motors: List of motor control dictionaries with 'slider', 'vibe_meter', and 'osc_entry'
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
            height=BTN_HEIGHT_SMALL,
            width=60,
            fg_color=COLOR_BTN_DELETE if is_connected else "#FFA500",
            hover_color=COLOR_BTN_DELETE_HOVER if is_connected else "#E69500"
        )
        delete_button.pack(side="right")
        
        # Motor controls (sliders + vibe meters + per-motor OSC entry) for each motor
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
            
            # Per-motor OSC Address Entry with auto-save on focus-out
            motor_osc_entry = ctk.CTkEntry(
                device_frame,
                placeholder_text=f"OSC Address for Motor {motor_idx}",
                width=250,
                font=("Arial", 12)
            )
            motor_osc_entry.insert(0, osc_addresses.get(str(motor_idx), ""))
            motor_osc_entry.pack(pady=(0, 2))
            
            # Bind focus-out to trigger auto-save
            motor_osc_entry.bind("<FocusOut>", lambda e, dn=device_name: self.controller.save_profiles())
            
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
                "vibe_meter": vibe_meter,
                "osc_entry": motor_osc_entry
            })
        
        # Return unified frame data with all elements
        return {
            "frame": device_frame,
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
            
            # Get OSC addresses dict from config, with backward compatibility
            osc_addresses = config.get("osc_addresses", {})
            if not osc_addresses and config.get("osc_address"):
                osc_addresses["0"] = config.get("osc_address")
            
            # Create frame using the helper method
            frame_data = self._create_device_frame(
                device_name=device_name,
                is_connected=is_connected,
                osc_addresses=osc_addresses,
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
    
    def update_debugger_display(self, text: str):
        """Update the debugger textbox with new content (main thread only)"""
        if self.debugger_textbox:
            self.debugger_textbox.configure(state="normal")
            self.debugger_textbox.delete("1.0", "end")
            self.debugger_textbox.insert("1.0", text)
            self.debugger_textbox.configure(state="disabled")

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
                # Generate default per-motor OSC addresses
                osc_addresses = {}
                for i in range(actual_motor_count):
                    suffix = f"_{i}" if actual_motor_count > 1 else ""
                    osc_addresses[str(i)] = f"/avatar/parameters/{device_name.replace(' ', '_')}{suffix}"
                
                # Store motor count in profile via controller
                controller.update_device_config(device_name, "motor_count", motor_count)
                
                # Device is connected since it was just discovered, so use green checkmark
                frame_data = self._create_device_frame(
                    device_name=device_name,
                    is_connected=True,
                    osc_addresses=osc_addresses,
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