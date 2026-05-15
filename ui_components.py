# OscGoesPurrr - UI Components Module
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
            text_color=COLOR_PRIMARY
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
                hover_color=COLOR_SURFACE_HOVER
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
        
        self.osc_status_label = ctk.CTkLabel(bottom_sidebar_frame, text="Status: Waiting for VRChat...", text_color=COLOR_ALERT)
        self.osc_status_label.pack(pady=(0, 0))
        
        self.osc_port_label = ctk.CTkLabel(bottom_sidebar_frame, text="Listening on Port: --")
        self.osc_port_label.pack(pady=(0, 5))

        self.osc_connection_button = ctk.CTkButton(
            bottom_sidebar_frame,
            text="Connect to VRChat",
            command=self.controller.toggle_osc_connection,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=BTN_HEIGHT_LARGE,
            fg_color=COLOR_PRIMARY, # Unified Purple
            hover_color=COLOR_PRIMARY_HOVER
        )
        self.osc_connection_button.pack(pady=(0, 5))

        self.osc_auto_connect_checkbox = ctk.CTkCheckBox(bottom_sidebar_frame, text="Auto Connect", font=ctk.CTkFont(size=12), command=self.controller.toggle_osc_auto_connect)
        self.osc_auto_connect_checkbox.pack(pady=(0, 15))
        # Initialize checkbox state from app settings
        if self.controller.get_app_setting("auto_connect_osc", True):
            self.osc_auto_connect_checkbox.select()

        # --- Separator Line ---
        separator = ctk.CTkFrame(bottom_sidebar_frame, height=2, fg_color=COLOR_SURFACE)
        separator.pack(fill="x", padx=15, pady=(0, 15))

        # --- Intiface Central Section ---
        ctk.CTkLabel(bottom_sidebar_frame, text="Intiface Central", font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(0, 2))
        
        self.status_label = ctk.CTkLabel(bottom_sidebar_frame, text="Status: Disconnected", text_color=COLOR_ALERT)
        self.status_label.pack(pady=(0, 5))

        self.connection_button = ctk.CTkButton(
            bottom_sidebar_frame,
            text="Connect to Intiface",
            command=self.controller.connect_to_intiface,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=BTN_HEIGHT_LARGE,
            fg_color=COLOR_PRIMARY, # Unified Purple
            hover_color=COLOR_PRIMARY_HOVER
        )
        self.connection_button.pack(pady=(0, 5))

        self.auto_connect_checkbox = ctk.CTkCheckBox(bottom_sidebar_frame, text="Auto Connect", font=ctk.CTkFont(size=12), command=self.controller.toggle_auto_connect)
        self.auto_connect_checkbox.pack(pady=(0, 10))
        # Initialize checkbox state from app settings
        if self.controller.get_app_setting("auto_connect", True):
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
                    text_color=COLOR_TEXT_MUTED
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
            text_color=COLOR_PRIMARY
        )
        title_label.pack(pady=(0, 15))
        
        # ---- Profile Selector Frame (4 configurable profile buttons) ----
        profile_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="transparent")
        profile_frame.pack(expand=False, fill="x", padx=20, pady=(0, 15))
        
        profile_header = ctk.CTkLabel(
            profile_frame,
            text="Active Profile",
            font=("Arial", 16, "bold"),
            text_color=COLOR_TEXT
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
                fg_color=COLOR_PRIMARY if is_active else COLOR_SURFACE,
                hover_color=COLOR_PRIMARY_HOVER if is_active else COLOR_SURFACE_HOVER,
                text_color=COLOR_TEXT,
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
                fg_color=COLOR_PRIMARY if is_active else COLOR_SURFACE,
                hover_color=COLOR_PRIMARY_HOVER if is_active else COLOR_SURFACE_HOVER,
                text_color=COLOR_TEXT,
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
            text_color=COLOR_PRIMARY
        )
        title_label.pack(pady=(0, 10))
        
        # Unified Devices Frame - contains saved toys and active controls
        self.devices_container_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color=COLOR_BG)
        self.devices_container_frame.pack(expand=True, fill="both", pady=(0, 10), padx=5)
        
        # Header for devices section
        devices_header_label = ctk.CTkLabel(
            self.devices_container_frame,
            text="Toys",
            font=("Arial", 16, "bold"),
            text_color=COLOR_TEXT
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
        """Setup the Network & Debug view with the real-time OSC debugger"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
        text="Network & Debug",
            font=("Arial", 28, "bold"),
            text_color=COLOR_PRIMARY
        )
        title_label.pack(pady=(0, 20))
        
        # --- Detected SPS Zones ---
        sps_frame = ctk.CTkFrame(parent_frame, fg_color=COLOR_SURFACE, corner_radius=8)
        sps_frame.pack(fill="x", padx=30, pady=(10, 10))
        ctk.CTkLabel(sps_frame, text="Active Avatar SPS Zones", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=15, pady=(10, 0))
        self.sps_status_label = ctk.CTkLabel(sps_frame, text="Waiting for VRChat...", justify="left", font=ctk.CTkFont(size=12), wraplength=400)
        self.sps_status_label.pack(anchor="w", padx=15, pady=(5, 15))
        
        # --- Real-Time OSC Debugger Section ---
        debugger_title = ctk.CTkLabel(
            parent_frame,
            text="Real-Time OSC Inspector",
            font=("Arial", 20, "bold"),
            text_color=COLOR_PRIMARY
        )
        debugger_title.pack(pady=(10, 10))
        
        # Toggle Button Frame
        button_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="transparent")
        button_frame.pack(expand=False, fill="x", padx=20, pady=(0, 10))
        
        # Toggle button - store reference so controller can update its state
        self.osc_debugger_button = ctk.CTkButton(
            button_frame,
            text="Start OSC Debugger",
            command=self.controller.toggle_osc_debugger,
            font=("Arial", 14),
            height=40,
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY_HOVER
        )
        self.osc_debugger_button.pack(pady=(0, 10))
        
        # Debugger Textbox Frame
        textbox_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color=COLOR_BG)
        textbox_frame.pack(expand=True, fill="both", padx=20, pady=(0, 20))
        
        # Header label inside textbox frame
        debugger_header = ctk.CTkLabel(
            textbox_frame,
            text="Live OSC Variables (toggle to start)",
            font=("Arial", 14, "bold"),
            text_color=COLOR_TEXT_MUTED
        )
        debugger_header.pack(pady=(10, 5))
        
        # --- Live Search Filter ---
        self.osc_search_var = ctk.StringVar()
        self.osc_search_entry = ctk.CTkEntry(
            textbox_frame,
            placeholder_text="Search parameters (e.g., Orifice, Touch, Float)...",
            textvariable=self.osc_search_var,
            height=30
        )
        self.osc_search_entry.pack(fill="x", padx=10, pady=(5, 5))
        
        # --- Dense Data Textbox ---
        self.debugger_textbox = ctk.CTkTextbox(
            textbox_frame,
            height=300,
            state="disabled",
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="none"
        )
        self.debugger_textbox.pack(expand=True, fill="both", padx=10, pady=(0, 10))
    
    def _setup_system_log_view(self, parent_frame: ctk.CTkFrame):
        """Setup the System Log view with the main log textbox"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
            text="System Log",
            font=("Arial", 28, "bold"),
            text_color=COLOR_PRIMARY
        )
        title_label.pack(pady=(0, 10), fill="x")
        
        # Log Textbox - fills entire remaining frame
        self.log_text = ctk.CTkTextbox(
            parent_frame,
            font=("Courier New", 12),
            state="disabled",
            fg_color=COLOR_BG
        )
        self.log_text.pack(expand=True, fill="both", padx=5, pady=(0, 5))
    
    def _setup_settings_view(self, parent_frame: ctk.CTkFrame):
        """Setup the Settings view with application configuration controls"""
        # Title
        title_label = ctk.CTkLabel(
            parent_frame,
            text="Application Settings",
            font=("Arial", 28, "bold"),
            text_color=COLOR_PRIMARY
        )
        title_label.pack(pady=(0, 20))
        
        # --- Network Settings Card ---
        network_card = ctk.CTkFrame(parent_frame, fg_color=COLOR_SURFACE, corner_radius=8)
        network_card.pack(fill="x", padx=30, pady=10)

        # Card Headers
        ctk.CTkLabel(network_card, text="OSC Network Bind", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(15, 5))
        ctk.CTkLabel(network_card, text="Determines how VRChat discovers this application on your local network.", font=ctk.CTkFont(size=12), text_color="gray").pack(anchor="w", padx=20, pady=(0, 15))

        # Switch Container (Horizontal Layout)
        switch_frame = ctk.CTkFrame(network_card, fg_color="transparent")
        switch_frame.pack(fill="x", padx=20, pady=(0, 10))

        # Left Label (Off State)
        ctk.CTkLabel(switch_frame, text="127.0.0.1 (Strict)", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(0, 10))

        # The Switch (Empty Text)
        bind_val = self.controller.get_app_setting("bind_all_interfaces", True)
        self.network_bind_switch = ctk.CTkSwitch(
            switch_frame,
            text="", 
            width=50,
            switch_width=40,
            progress_color=COLOR_SUCCESS,
            command=lambda: self.controller.toggle_network_bind(self.network_bind_switch.get() == 1)
        )
        self.network_bind_switch.pack(side="left", padx=10)

        # Right Label (On State)
        ctk.CTkLabel(switch_frame, text="0.0.0.0 (Recommended)", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(10, 0))

        # Warning Footer
        warning_label = ctk.CTkLabel(
            network_card,
            text="* Requires application restart to apply changes.",
            font=ctk.CTkFont(size=12, slant="italic"),
            text_color=COLOR_ALERT
        )
        warning_label.pack(anchor="w", padx=20, pady=(0, 15))

        # Apply initial state
        if bind_val:
            self.network_bind_switch.select()
        else:
            self.network_bind_switch.deselect()
        
        # ====================
        # Connection Settings Card
        # ====================
        conn_card = ctk.CTkFrame(parent_frame, fg_color=COLOR_SURFACE, corner_radius=8)
        conn_card.pack(fill="x", padx=30, pady=10)

        ctk.CTkLabel(conn_card, text="Connection Settings", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(15, 10))

        # Auto Refresh Devices checkbox
        auto_refresh_default = self.controller.get_app_setting("auto_refresh", True)
        self.auto_refresh_var = ctk.BooleanVar(value=auto_refresh_default)
        auto_refresh_checkbox = ctk.CTkCheckBox(
            conn_card,
            text="Auto Refresh Devices",
            variable=self.auto_refresh_var,
            command=self.controller.toggle_auto_refresh,
            font=ctk.CTkFont(size=14)
        )
        auto_refresh_checkbox.pack(anchor="w", padx=20, pady=(5, 5))
        if auto_refresh_default:
            auto_refresh_checkbox.select()

        # Auto Connect (Intiface) checkbox
        auto_connect_default = self.controller.get_app_setting("auto_connect", True)
        self.auto_connect_var = ctk.BooleanVar(value=auto_connect_default)
        auto_connect_checkbox = ctk.CTkCheckBox(
            conn_card,
            text="Auto Connect (Intiface)",
            variable=self.auto_connect_var,
            command=self.controller.toggle_auto_connect,
            font=ctk.CTkFont(size=14)
        )
        auto_connect_checkbox.pack(anchor="w", padx=20, pady=(5, 5))
        if auto_connect_default:
            auto_connect_checkbox.select()

        # Auto Connect (VRChat OSC) checkbox
        auto_connect_osc_default = self.controller.get_app_setting("auto_connect_osc", True)
        self.osc_auto_connect_var = ctk.BooleanVar(value=auto_connect_osc_default)
        osc_auto_connect_checkbox = ctk.CTkCheckBox(
            conn_card,
            text="Auto Connect (VRChat OSC)",
            variable=self.osc_auto_connect_var,
            command=self.controller.toggle_osc_auto_connect,
            font=ctk.CTkFont(size=14)
        )
        osc_auto_connect_checkbox.pack(anchor="w", padx=20, pady=(5, 15))
        if auto_connect_osc_default:
            osc_auto_connect_checkbox.select()

        # ====================
        # Quality of Life Settings Card
        # ====================
        ql_card = ctk.CTkFrame(parent_frame, fg_color=COLOR_SURFACE, corner_radius=8)
        ql_card.pack(fill="x", padx=30, pady=10)

        ctk.CTkLabel(ql_card, text="Quality of Life", font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=20, pady=(15, 10))

        # Hide Console Switch
        hide_console_var = ctk.BooleanVar(value=self.controller.get_app_setting("hide_console", True))
        def on_hide_console():
            self.controller.set_app_setting("hide_console", hide_console_var.get())
            self.controller.apply_console_visibility()
            
        hide_console_switch = ctk.CTkSwitch(
            ql_card, 
            text="Hide Terminal Console", 
            variable=hide_console_var,
            command=on_hide_console,
            progress_color=COLOR_SUCCESS
        )
        hide_console_switch.pack(pady=5, padx=20, anchor="w")

        # Minimize to Tray Switch
        tray_var = ctk.BooleanVar(value=self.controller.get_app_setting("minimize_to_tray", False))
        def on_tray_toggle():
            self.controller.set_app_setting("minimize_to_tray", tray_var.get())
            
        tray_switch = ctk.CTkSwitch(
            ql_card, 
            text="Minimize to System Tray", 
            variable=tray_var,
            command=on_tray_toggle,
            progress_color=COLOR_SUCCESS
        )
        tray_switch.pack(pady=5, padx=20, anchor="w")
    
    def select_view(self, view_name: str):
        """
        Switch between different views in the UI.
        
        Args:
            view_name: Name of the view to switch to
        """
        # 1. Update button colors (highlight active tab)
        for name, button in self.nav_buttons.items():
            if name == view_name:
                button.configure(fg_color=COLOR_SURFACE)  # Active color
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
                fg_color=COLOR_ALERT,
                hover_color=COLOR_ALERT_HOVER
            )
            self.status_label.configure(
                text="Status: Connected to Intiface",
                text_color=COLOR_SUCCESS
            )
        else:
            self.connection_button.configure(
                text="Connect to Intiface",
                fg_color=COLOR_PRIMARY, # Unified Purple (matches sidebar default)
                hover_color=COLOR_PRIMARY_HOVER
            )
            self.status_label.configure(
                text="Status: Disconnected",
                text_color=COLOR_ALERT
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
                self.osc_connection_button.configure(text="Disconnect VRChat", fg_color=COLOR_ALERT, hover_color=COLOR_ALERT_HOVER)
        else:
            self.osc_status_label.configure(text="Status: Waiting for VRChat...", text_color=COLOR_ALERT)
            self.osc_port_label.configure(text="Listening on Port: --")
            if self.osc_connection_button:
                self.osc_connection_button.configure(text="Connect to VRChat", fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER)
    
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
                    status_label.configure(text=f"✓ {device_name}", text_color=COLOR_SUCCESS)
                    delete_button.configure(state="normal", fg_color=COLOR_ALERT, hover_color=COLOR_ALERT_HOVER)
                else:
                    # Not connected - show warning
                    status_label.configure(text=f"⚠ {device_name}", text_color=COLOR_ALERT)
                    delete_button.configure(state="normal", fg_color=COLOR_ALERT, hover_color=COLOR_ALERT_HOVER)
    
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
            fg_color=COLOR_SURFACE
        )
        device_frame.pack(expand=False, fill="x", pady=(0, 10), padx=5)
        
        # Header row: status icon + name + delete button
        header_frame = ctk.CTkFrame(device_frame, fg_color="transparent")
        header_frame.pack(expand=True, fill="x", padx=5, pady=(5, 2))
        
        # Status label (icon only) - green for connected, yellow otherwise
        status_icon = "✓" if is_connected else "⚠"
        status_text = f"{status_icon} {device_name}"
        status_color = COLOR_SUCCESS if is_connected else COLOR_ALERT
        
        name_label = ctk.CTkLabel(
            header_frame,
            text=status_text,
            font=("Arial", 14, "bold"),
            text_color=COLOR_TEXT,
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
            fg_color=COLOR_ALERT if is_connected else COLOR_ALERT,
            hover_color=COLOR_ALERT_HOVER if is_connected else COLOR_ALERT_HOVER
        )
        delete_button.pack(side="right")
        
        # Fetch available zones directly via controller facade
        available_zones = ["All SPS", "None"]
        detected = self.controller.get_detected_zones()
        available_zones.extend(detected.get("Orifices", []))
        available_zones.extend(detected.get("Penetrators", []))

        motor_vars = []
        for motor_idx in range(motor_count):
            motor_frame = ctk.CTkFrame(device_frame, fg_color=COLOR_SURFACE, corner_radius=6)
            motor_frame.pack(fill="x", padx=10, pady=5)
            motor_frame.grid_columnconfigure(1, weight=1)

            # Row 0: Motor Label & Submenu Button
            motor_label = ctk.CTkLabel(motor_frame, text=f"Motor {motor_idx}:", font=ctk.CTkFont(weight="bold"))
            motor_label.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="w")

            # Read from the new 'zones' key, fallback to legacy 'zone' key if it exists
            legacy_zone = self.controller.get_profile_config(device_name, f"motor_{motor_idx}_zone", "")
            zones_var = ctk.StringVar(value=self.controller.get_profile_config(device_name, f"motor_{motor_idx}_zones", legacy_zone))

            def get_btn_text(var):
                # Don't count "None" as an active zone
                count = len([z for z in var.get().split(",") if z.strip() and z.strip() != "None"])
                return f"Select Zones ({count} enabled)" if count > 0 else "Select Zones..."

            def open_zone_submenu(dn=device_name, midx=motor_idx, var=zones_var, btn=None):
                popup = ctk.CTkToplevel(self.app)
                popup.title(f"Select Zones for Motor {midx}")
                popup.geometry("300x400")
                popup.transient(self.app)
                popup.grab_set()

                scroll = ctk.CTkScrollableFrame(popup)
                scroll.pack(fill="both", expand=True, padx=10, pady=10)

                # Fetch fresh zones directly via controller facade
                fresh_zones = []
                detected = self.controller.get_detected_zones()
                fresh_zones.extend(detected.get("Orifices", []))
                fresh_zones.extend(detected.get("Penetrators", []))

                if not fresh_zones:
                    ctk.CTkLabel(scroll, text="No zones detected yet...\nMake sure VRChat is running and avatar loaded.", text_color=COLOR_ALERT).pack(pady=20)
                    return

                current_selected = [z.strip() for z in var.get().split(",") if z.strip()]
                is_all_sps_active = ("All SPS" in current_selected)

                # Store references to individual zone checkbox vars so we can sync them live
                individual_cb_vars = []

                def sync_individual_checkboxes():
                    """Re-read var and update all individual checkbox visuals to match."""
                    new_selected = [z.strip() for z in var.get().split(",") if z.strip()]
                    new_all_sps = ("All SPS" in new_selected)
                    all_sps_var.set(new_all_sps)
                    for zone_name, cb_v in individual_cb_vars:
                        if new_all_sps:
                            # When All SPS is active, individual checkboxes should appear unchecked
                            cb_v.set(False)
                        else:
                            cb_v.set(zone_name in new_selected)

                def toggle_zone(zone, cb_var):
                    selected = [z.strip() for z in var.get().split(",") if z.strip()]
                    # If "All SPS" is currently in selected, remove it first (individual toggle implies not All SPS)
                    if "All SPS" in selected:
                        selected.remove("All SPS")
                        all_sps_var.set(False)
                    if cb_var.get():
                        if zone not in selected and zone != "None":
                            selected.append(zone)
                    else:
                        if zone in selected:
                            selected.remove(zone)

                    new_val = ", ".join(selected)
                    var.set(new_val)
                    self.controller.update_device_config(dn, f"motor_{midx}_zones", new_val)
                    self.controller.save_profiles()
                    
                    if hasattr(self.controller, 'force_recalculate'):
                        self.controller.force_recalculate()
                        
                    if btn: btn.configure(text=get_btn_text(var))

                # Render "All SPS" checkbox (matches any incoming zone)
                all_sps_var = ctk.BooleanVar(value=is_all_sps_active)
                def on_all_sps_toggle():
                    if all_sps_var.get():
                        # Selecting All SPS means clearing individual zones and setting the special flag
                        new_val = "All SPS"
                    else:
                        # Deselecting All SPS clears the value back to empty
                        new_val = ""
                    var.set(new_val)
                    self.controller.update_device_config(dn, f"motor_{midx}_zones", new_val)
                    self.controller.save_profiles()
                    
                    if hasattr(self.controller, 'force_recalculate'):
                        self.controller.force_recalculate()
                        
                    if btn: btn.configure(text=get_btn_text(var))
                    
                    # CRITICAL FIX: Sync all individual checkbox visuals after toggling All SPS
                    sync_individual_checkboxes()

                all_sps_cb = ctk.CTkCheckBox(scroll, text="All SPS (match any zone)", variable=all_sps_var, command=on_all_sps_toggle)
                all_sps_cb.pack(anchor="w", pady=(5, 2), padx=5)

                # Render separator before individual zones
                sep = ctk.CTkLabel(scroll, text="--- Detected Zones ---", text_color=COLOR_TEXT_MUTED)
                sep.pack(pady=(10, 5))

                # Render a checkbox for every detected zone
                for zone in fresh_zones:
                    if zone == "None":
                        continue
                    # If All SPS is active, individual zones should appear unchecked
                    initial_state = (zone in current_selected) if not is_all_sps_active else False
                    cb_var = ctk.BooleanVar(value=initial_state)
                    individual_cb_vars.append((zone, cb_var))
                    cb = ctk.CTkCheckBox(scroll, text=zone, variable=cb_var,
                                         command=lambda z=zone, v=cb_var: toggle_zone(z, v))
                    cb.pack(anchor="w", pady=5, padx=5)

            zone_btn = ctk.CTkButton(
                motor_frame,
                text=get_btn_text(zones_var),
                fg_color=COLOR_SURFACE,
                hover_color=COLOR_SURFACE_HOVER
            )
            # Pass the button itself so the submenu can immediately update its text on click
            zone_btn.configure(command=lambda btn=zone_btn: open_zone_submenu(btn=btn))
            zone_btn.grid(row=0, column=1, padx=(0, 10), pady=(10, 5), sticky="ew")

            # Row 1: Interaction Filters
            filter_frame = ctk.CTkFrame(motor_frame, fg_color="transparent")
            filter_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=0, sticky="ew")
            
            def create_cb(parent, text, key, default):
                var = ctk.BooleanVar(value=self.controller.get_profile_config(device_name, key, default))
                cb = ctk.CTkCheckBox(
                    parent, text=text, variable=var, font=ctk.CTkFont(size=11), width=60,
                    command=lambda dn=device_name, k=key, v=var: (
                        self.controller.update_device_config(dn, k, v.get()),
                        self.controller.save_profiles(),
                        self.controller.force_recalculate() if hasattr(self.controller, 'force_recalculate') else None
                    )
                )
                return cb, var
            cb_touch, _ = create_cb(filter_frame, "Touch", f"motor_{motor_idx}_touch", True)
            cb_pen, _ = create_cb(filter_frame, "Penetration", f"motor_{motor_idx}_pen", True)
            cb_self, _ = create_cb(filter_frame, "Self", f"motor_{motor_idx}_self", False)
            cb_others, _ = create_cb(filter_frame, "Others", f"motor_{motor_idx}_others", True)
            
            cb_touch.grid(row=0, column=0, padx=5, pady=2, sticky="w")
            cb_pen.grid(row=0, column=1, padx=5, pady=2, sticky="w")
            cb_self.grid(row=0, column=2, padx=5, pady=2, sticky="w")
            cb_others.grid(row=0, column=3, padx=5, pady=2, sticky="w")

            # Row 2: Custom Parameter Fallback
            osc_entry = ctk.CTkEntry(motor_frame, placeholder_text="Custom override (e.g. OGB/Tail/Touch)")
            osc_entry.insert(0, osc_addresses.get(str(motor_idx), ""))
            osc_entry.grid(row=2, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="ew")
            osc_entry.bind("<FocusOut>", lambda e, dn=device_name: (
                self.controller.save_profiles(),
                self.controller.force_recalculate() if hasattr(self.controller, 'force_recalculate') else None
            ))

            # Row 3: Intensity Slider
            slider = ctk.CTkSlider(motor_frame, from_=0.0, to=1.0, command=lambda val, dn=device_name, idx=motor_idx: self.controller.update_device_target(dn, float(val), idx))
            slider.set(0.0)
            slider.grid(row=3, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="ew")

            # Row 4: Vibe Meter
            vibe_meter = ctk.CTkProgressBar(motor_frame, height=6)
            vibe_meter.set(0.0)
            vibe_meter.grid(row=4, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")

            motor_vars.append({
                "slider": slider,
                "vibe_meter": vibe_meter,
                "osc_entry": osc_entry
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
                text_color=COLOR_TEXT_MUTED
            )
            no_stored_label.pack(pady=5)
            return
        
        # Get actual motor counts via controller facade
        device_motor_counts = controller.get_device_motor_counts()
        
        curr_profile = self.controller.profile_manager.current_profile
        if curr_profile not in self.controller.profiles:
            return
            
        all_devices = list(self.controller.profiles[curr_profile].keys())
        
        # Sort logic: 
        # 1. Connected devices first (name not in connected_names evaluates to False, which comes before True)
        # 2. Alphabetical secondary sort
        all_devices.sort(key=lambda name: (name not in connected_names, name.lower()))
        
        for device_name in all_devices:
            config = self.controller.profiles[curr_profile][device_name]
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
            
            # Tell the orchestrator to initialize hardware state for this device
            if hasattr(controller, 'update_device_target'):
                controller.update_device_target(device_name, 0.0, -1)
            
            # Also store in stored_device_frames for status updates
            self.stored_device_frames[device_name] = {
                "frame": frame_data["frame"],
                "status_label": frame_data["status_label"],
                "delete_button": frame_data["delete_button"]
            }
    
    def update_osc_debugger_button(self, is_running: bool):
        """Update the OSC debugger toggle button text and color."""
        if self.osc_debugger_button:
            if is_running:
                self.osc_debugger_button.configure(
                    text="Stop OSC Debugger",
                    fg_color=COLOR_ALERT,
                    hover_color=COLOR_ALERT_HOVER
                )
            else:
                self.osc_debugger_button.configure(
                    text="Start OSC Debugger",
                    fg_color=COLOR_PRIMARY,
                    hover_color=COLOR_PRIMARY_HOVER
                )

    def update_debugger_display(self, data):
        """Updates the OSC debugger textbox with color-coded data."""
        if self.debugger_textbox:
            # 1. Capture current scroll position
            try:
                scroll_pos = self.debugger_textbox._textbox.yview()
            except Exception:
                scroll_pos = (0.0, 1.0)
            
            self.debugger_textbox.configure(state="normal")
            textbox = self.debugger_textbox._textbox
            
            # Remove all old tags to avoid memory leaks on each refresh cycle
            for old_tag in textbox.tag_names():
                textbox.tag_remove(old_tag, "1.0", "end")
            
            textbox.delete("1.0", "end")
            
            if isinstance(data, list):
                # List of (addr_prefix, val_str, color) triplets
                # Address tag is shared (all same gray), value tags are unique per line
                addr_tag = "_dbg_addr"
                textbox.tag_configure(addr_tag, foreground=COLOR_TEXT_MUTED)
                
                for idx, (addr_prefix, val_str, color) in enumerate(data):
                    val_tag = f"_v{idx}"
                    textbox.tag_configure(val_tag, foreground=color)
                    if addr_prefix:
                        textbox.insert("end", addr_prefix, addr_tag)
                    if val_str:
                        textbox.insert("end", val_str, val_tag)
                    textbox.insert("end", "\n")
            else:
                # Plain string fallback (backward compatible)
                textbox.insert("1.0", data)
            
            self.debugger_textbox.configure(state="disabled")
            
            # 2. Restore scroll position
            try:
                self.debugger_textbox._textbox.yview_moveto(scroll_pos[0])
            except Exception:
                pass

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
        
        # Get actual motor counts via controller facade
        device_motor_counts = controller.get_device_motor_counts()
        
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
                    osc_addresses[str(i)] = f"{device_name.replace(' ', '_')}{suffix}"
                
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
                
                # Tell the orchestrator to initialize hardware state for this device
                if hasattr(controller, 'update_device_target'):
                    controller.update_device_target(device_name, 0.0, -1)
                
                # Also store in stored_device_frames for status updates
                self.stored_device_frames[device_name] = {
                    "frame": frame_data["frame"],
                    "status_label": frame_data["status_label"],
                    "delete_button": frame_data["delete_button"]
                }
        
        controller.log_message(f"Connected devices: {len(devices_dict)}")
    
    def update_device_visuals(self, device_name: str, motor_idx: int, value: float):
        """Safely updates the sliders and vibe meters without exposing widgets to the backend."""
        if device_name in self.device_ui_frames:
            motor_vars = self.device_ui_frames[device_name].get("motors", [])
            if 0 <= motor_idx < len(motor_vars):
                motor_vars[motor_idx]["slider"].set(value)
                motor_vars[motor_idx]["vibe_meter"].set(value)
            elif motor_idx == -1:
                for mv in motor_vars:
                    mv["slider"].set(value)
                    mv["vibe_meter"].set(value)
