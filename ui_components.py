# OscGoesPurrr - UI Components Module
from typing import List, Optional

import customtkinter as ctk
from constants import *
from parameter_store import store


class OscGoesPurrrUI:
    """UI Component class - handles all GUI rendering and updates"""
    
    def __init__(self, controller, app_root: "Optional[ctk.CTk]" = None):
        """
        Initialize the UI component.

        Args:
            controller: Reference to the main application controller
            app_root: Optional pre-built root window. When omitted, the UI
                creates its own framework-specific root so the controller
                stays framework-agnostic.
        """
        self.controller = controller
        self.app = app_root if app_root is not None else ctk.CTk()
        
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
            elif view_name == "Help":
                self._setup_help_view(view_frame)
            else:
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
        
        # ---- Profile Selector Frame (4 configurable profile slots) ----
        profile_frame = ctk.CTkFrame(parent_frame, corner_radius=8, fg_color="transparent")
        profile_frame.pack(expand=False, fill="x", padx=20, pady=(0, 15))

        profile_header = ctk.CTkLabel(
            profile_frame,
            text="Active Profile",
            font=("Arial", 16, "bold"),
            text_color=COLOR_TEXT
        )
        profile_header.pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(
            profile_frame,
            text="Each profile keeps its own toy settings (SPS zones, custom OSC parameters, filters).",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
        ).pack(anchor="w", pady=(0, 8))

        # Wrapping flow of profile tiles; rebuilt dynamically so the user can
        # add/remove as many profiles as they want.
        self.profile_buttons_frame = ctk.CTkFrame(profile_frame, fg_color="transparent")
        self.profile_buttons_frame.pack(expand=False, fill="x")

        self.profile_buttons = []
        self._build_profile_slots()
        
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
    
    def _build_profile_slots(self):
        """Render every existing profile as a tile, followed by a '+ New' tile.
        Wraps across rows so the user can add as many profiles as they want."""
        if not hasattr(self, "profile_buttons_frame") or self.profile_buttons_frame is None:
            return

        for child in self.profile_buttons_frame.winfo_children():
            child.destroy()

        self.profile_buttons = []
        current_profile = self.controller.profile_manager.current_profile
        names = list(self.controller.profile_manager.profiles.keys())

        cols = 4
        for i in range(cols):
            self.profile_buttons_frame.grid_columnconfigure(i, weight=1, uniform="profilecol")

        can_delete = len(names) > 1

        def place(widget, idx):
            widget.grid(row=idx // cols, column=idx % cols, padx=(0, 8), pady=(0, 6), sticky="ew")

        for i, name in enumerate(names):
            is_active = (name == current_profile)
            slot = ctk.CTkFrame(self.profile_buttons_frame, fg_color="transparent")
            place(slot, i)
            slot.grid_columnconfigure(0, weight=1)

            name_btn = ctk.CTkButton(
                slot, text=name,
                font=("Arial", 13), height=36,
                fg_color=COLOR_PRIMARY if is_active else COLOR_SURFACE,
                hover_color=COLOR_PRIMARY_HOVER if is_active else COLOR_SURFACE_HOVER,
                text_color=COLOR_TEXT, corner_radius=6,
                command=lambda n=name: self.controller.switch_profile(n),
            )
            name_btn.grid(row=0, column=0, sticky="ew")

            ctk.CTkButton(
                slot, text="✎", width=28, height=36,
                font=("Arial", 14),
                fg_color=COLOR_SURFACE, hover_color=COLOR_SURFACE_HOVER,
                text_color=COLOR_TEXT_MUTED, corner_radius=6,
                command=lambda n=name: self._start_profile_rename(n),
            ).grid(row=0, column=1, padx=(4, 0))

            del_btn = ctk.CTkButton(
                slot, text="🗑", width=28, height=36,
                font=("Arial", 13),
                fg_color=COLOR_SURFACE,
                hover_color=COLOR_ALERT_HOVER if can_delete else COLOR_SURFACE,
                text_color=COLOR_ALERT if can_delete else COLOR_TEXT_MUTED,
                corner_radius=6,
                state="normal" if can_delete else "disabled",
                command=lambda n=name: self._confirm_profile_delete(n),
            )
            del_btn.grid(row=0, column=2, padx=(4, 0))

            self.profile_buttons.append(name_btn)

        # Trailing "+ New Profile" tile
        add_slot = ctk.CTkFrame(self.profile_buttons_frame, fg_color="transparent")
        place(add_slot, len(names))
        add_slot.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            add_slot, text="+ New Profile",
            font=("Arial", 13), height=36,
            fg_color=COLOR_SURFACE, hover_color=COLOR_PRIMARY_HOVER,
            text_color=COLOR_TEXT, corner_radius=6,
            command=self._add_new_profile,
        ).grid(row=0, column=0, sticky="ew")

    # Alias kept for callers in main.py that already use this name.
    def _refresh_profile_buttons(self):
        self._build_profile_slots()

    def _add_new_profile(self):
        name = self.controller.create_profile()
        # Drop the user straight into renaming the freshly-created profile.
        self._build_profile_slots()
        self._start_profile_rename(name)

    def _confirm_profile_delete(self, name: str):
        """Show a small confirmation dialog before deleting a profile."""
        if len(self.controller.profile_manager.profiles) <= 1:
            return
        dlg = ctk.CTkToplevel(self.app)
        dlg.title("Delete Profile")
        dlg.geometry("360x160")
        dlg.transient(self.app)
        try:
            dlg.grab_set()
        except Exception:
            pass

        ctk.CTkLabel(
            dlg, text=f"Delete profile '{name}'?",
            font=("Arial", 15, "bold"), text_color=COLOR_TEXT,
        ).pack(pady=(20, 6))
        ctk.CTkLabel(
            dlg,
            text="This removes the profile's saved per-toy settings.\nYour toys themselves remain.",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED,
            justify="center",
        ).pack(pady=(0, 14))

        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack()
        ctk.CTkButton(
            row, text="Cancel",
            fg_color=COLOR_SURFACE, hover_color=COLOR_SURFACE_HOVER,
            command=dlg.destroy,
        ).pack(side="left", padx=6)

        def do_delete():
            dlg.destroy()
            self.controller.delete_profile(name)

        ctk.CTkButton(
            row, text="Delete",
            fg_color=COLOR_ALERT, hover_color=COLOR_ALERT_HOVER,
            command=do_delete,
        ).pack(side="left", padx=6)

    def _start_profile_rename(self, current_name: str):
        """Open an inline rename entry in the tile for `current_name`."""
        if not hasattr(self, "profile_buttons_frame"):
            return
        if current_name not in self.controller.profile_manager.profiles:
            return

        # Find the tile by walking children and matching against the name button text.
        target_slot = None
        for slot in self.profile_buttons_frame.winfo_children():
            for sub in slot.winfo_children():
                try:
                    if isinstance(sub, ctk.CTkButton) and sub.cget("text") == current_name:
                        target_slot = slot
                        break
                except Exception:
                    pass
            if target_slot is not None:
                break
        if target_slot is None:
            return

        for w in target_slot.winfo_children():
            w.destroy()
        target_slot.grid_columnconfigure(0, weight=1)

        entry = ctk.CTkEntry(target_slot, font=("Arial", 13), height=36)
        entry.insert(0, current_name)
        entry.select_range(0, "end")
        entry.grid(row=0, column=0, sticky="ew")

        def confirm(_evt=None):
            new_name = entry.get().strip()
            if new_name and new_name != current_name:
                self.controller.rename_profile(current_name, new_name)
            self._build_profile_slots()

        def cancel(_evt=None):
            self._build_profile_slots()

        entry.bind("<Return>", confirm)
        entry.bind("<Escape>", cancel)
        entry.bind("<FocusOut>", confirm)
        entry.focus_set()

        ctk.CTkButton(
            target_slot, text="✓", width=28, height=36,
            font=("Arial", 14, "bold"),
            fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER,
            command=confirm,
        ).grid(row=0, column=1, padx=(4, 0))
    
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
    
    def _setup_help_view(self, parent_frame: ctk.CTkFrame):
        """Setup the Help view — explains how settings, profiles, devices and
        the OSC inspector work so the user doesn't have to dig through code or
        external docs."""
        title_label = ctk.CTkLabel(
            parent_frame, text="Help & How It Works",
            font=("Arial", 28, "bold"), text_color=COLOR_PRIMARY,
        )
        title_label.pack(pady=(0, 12))

        scroller = ctk.CTkScrollableFrame(parent_frame, fg_color="transparent")
        scroller.pack(expand=True, fill="both", padx=20, pady=(0, 20))

        def section(title: str, body: str):
            card = ctk.CTkFrame(scroller, fg_color=COLOR_SURFACE, corner_radius=8)
            card.pack(fill="x", pady=(0, 10))
            ctk.CTkLabel(
                card, text=title, font=("Arial", 16, "bold"),
                text_color=COLOR_PRIMARY, anchor="w", justify="left",
            ).pack(anchor="w", padx=15, pady=(12, 4))
            ctk.CTkLabel(
                card, text=body.strip(), font=("Arial", 12),
                text_color=COLOR_TEXT, anchor="w", justify="left",
                wraplength=720,
            ).pack(anchor="w", padx=15, pady=(0, 12), fill="x")

        section(
            "Profiles — what they are",
            """
A profile is a complete bundle of toy settings, selectable on the
Dashboard. The currently-selected profile is the one the haptic engine
uses for routing OSC parameters to motor outputs.

  • Click a profile tile to switch to it.
  • Click the pencil (✎) to rename it.
  • Click the trash (🗑) to delete it (disabled when only one profile remains).
  • Click "+ New Profile" to add another. There is no fixed cap.
""",
        )

        section(
            "What is saved per profile vs. globally",
            """
Per profile (each profile keeps its own copy):
  • SPS zones selected for each motor (Pussy, Ass, Dick, etc., or "All SPS")
  • Custom OSC parameter addresses mapped to each motor
  • Interaction filters: Touch, Penetration, Self, Others
  • Linear-actuator mode (Position / Speed) and idle behaviour (Hold / Rest)

Global (shared by all profiles):
  • The list of known toys (every toy you've ever connected). New or empty
    profiles automatically inherit this list with default settings, so
    switching profiles never loses sight of a toy.
  • App settings: OSC network bind, auto-connect, auto-refresh,
    minimize-to-tray, hide-console, etc. (see the Settings tab).
""",
        )

        section(
            "Switching profiles",
            """
Switching profiles instantly swaps the active routing rules. Every motor
re-evaluates against the new profile's zones, filters and custom OSC
addresses. The set of toys you see does not change — it's the same global
toy list — only their settings do.

If you switch to a brand-new profile, every previously-seen toy appears
with default settings, ready for you to configure.
""",
        )

        section(
            "Deleting a toy",
            """
The red "Delete" button on a toy card forgets that toy entirely — it is
removed from every profile and from the global known-toys list. The card
will not reappear when you switch profiles. To use the toy again, simply
reconnect it; it will be re-registered automatically.
""",
        )

        section(
            "Custom OSC addresses on a motor",
            """
Under each motor, the "+ Add Variable" button lets you map any number of
OSC parameters to that motor. The motor's output is the maximum of all
mapped parameters' normalized values (plus any contribution from
selected SPS zones, if enabled).

The picker shows live avatar parameters captured by the OSC inspector
(see the Network & Debug tab). Double-click a row to add it, or use the
manual entry field for parameters not currently on the avatar (wildcards
like OGB/Tail/* are accepted).

Tick "Include non-avatar parameters" to also see OGB / SPS / system
paths in the same picker.

The × on each chip removes that mapping for the current profile only.
""",
        )

        section(
            "Real-Time OSC Inspector",
            """
Network & Debug → Real-Time OSC Inspector shows every OSC parameter
your avatar is broadcasting. Useful for finding the exact name of a
parameter before mapping it to a motor. Use the search box to filter.
The active SPS zones panel above lists detected OGB orifices and
penetrators on the loaded avatar.
""",
        )

        section(
            "Where settings live on disk",
            """
%APPDATA%\\OscGoesPurrr\\
  • profiles.json         — per-profile device settings
  • known_devices.json    — global toy list (name, motor count, motor kinds)
  • app_settings.json     — global app preferences

Deleting known_devices.json forces a rebuild from profiles.json on next
launch. Deleting profiles.json wipes all profile settings (toys remain
known and will be re-seeded with defaults).
""",
        )

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
                    # Not connected - show warning, clear stale battery reading
                    status_label.configure(text=f"⚠ {device_name}", text_color=COLOR_ALERT)
                    delete_button.configure(state="normal", fg_color=COLOR_ALERT, hover_color=COLOR_ALERT_HOVER)
                    battery_label = self.device_ui_frames.get(device_name, {}).get("battery_label")
                    if battery_label:
                        battery_label.configure(text="")
        self._reorder_device_frames()

    def update_battery_label(self, device_name: str, level: float):
        """Update the battery label for a device with a 0.0–1.0 level reading."""
        if device_name not in self.device_ui_frames:
            return
        battery_label = self.device_ui_frames[device_name].get("battery_label")
        if not battery_label:
            return
        pct = int(level * 100)
        if pct > 50:
            color = COLOR_SUCCESS
        elif pct > 20:
            color = COLOR_ALERT
        else:
            color = "#FF4444"
        battery_label.configure(text=f"🔋 {pct}%", text_color=color)

    def _create_device_frame(self, device_name: str, is_connected: bool, osc_addresses: dict, motor_count: int, motor_kinds: Optional[List[str]] = None) -> dict:
        """
        Create a UI frame for a device with all controls.

        This helper method extracts the common frame creation logic used by both
        build_stored_devices_ui() and build_device_list_ui().

        Args:
            device_name: Name of the device
            is_connected: Whether the device is currently connected (determines status color)
            osc_addresses: Dict mapping motor index string -> OSC address (e.g. {"0": "/param/0", "1": "/param/1"})
            motor_count: Number of motors/vibration features on the device
            motor_kinds: Optional list of feature-kind strings per motor (e.g. ["vibrate", "linear-d"]).
                When provided, motors whose kind is "linear" or "linear-d" get extra UI controls
                for switching between Position / Speed mode and Hold / Rest idle behavior.

        Returns:
            Dictionary containing frame data with keys:
                - frame: The device frame widget
                - status_label: The status label widget
                - delete_button: The delete button widget
                - motors: List of motor control dictionaries with 'slider', 'vibe_meter', and 'addresses' (list[str])
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

        # Battery level — populated by battery poll; empty until first reading
        battery_label = ctk.CTkLabel(
            header_frame,
            text="",
            font=("Arial", 11),
            text_color=COLOR_SUCCESS,
            width=65,
            anchor="w",
        )
        battery_label.pack(side="left", padx=(10, 0))

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
            legacy_zone = self.controller.get_profile_config(device_name, f"motor_{motor_idx}_zone", "All SPS")
            zones_var = ctk.StringVar(value=self.controller.get_profile_config(device_name, f"motor_{motor_idx}_zones", legacy_zone or "All SPS"))

            def get_btn_text(var):
                # Don't count "None" as an active zone
                count = len([z for z in var.get().split(",") if z.strip() and z.strip() != "None"])
                return f"Select Zones ({count} enabled)" if count > 0 else "Select Zones..."

            zone_expanded = [False]
            zone_panel_cb_vars = []

            # Inline expanding zone panel (initially hidden)
            zone_panel = ctk.CTkFrame(motor_frame, fg_color=COLOR_SURFACE_HOVER, corner_radius=4)

            def build_zone_panel(dn=device_name, midx=motor_idx, var=zones_var):
                for w in zone_panel.winfo_children():
                    w.destroy()
                zone_panel_cb_vars.clear()

                fresh_zones = []
                detected = self.controller.get_detected_zones()
                fresh_zones.extend(detected.get("Orifices", []))
                fresh_zones.extend(detected.get("Penetrators", []))

                if not fresh_zones:
                    ctk.CTkLabel(zone_panel, text="No zones detected yet.\nMake sure VRChat is running and avatar loaded.", text_color=COLOR_ALERT).pack(anchor="w", padx=8, pady=5)
                    return

                current_selected = [z.strip() for z in var.get().split(",") if z.strip()]
                is_all_sps_active = ("All SPS" in current_selected)

                def sync_individual_checkboxes():
                    new_selected = [z.strip() for z in var.get().split(",") if z.strip()]
                    new_all_sps = ("All SPS" in new_selected)
                    all_sps_var.set(new_all_sps)
                    for zone_name, cb_v in zone_panel_cb_vars:
                        cb_v.set(False if new_all_sps else (zone_name in new_selected))

                def toggle_zone(zone, cb_var):
                    selected = [z.strip() for z in var.get().split(",") if z.strip()]
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
                    zone_btn.configure(text=get_btn_text(var) + " ▲")

                all_sps_var = ctk.BooleanVar(value=is_all_sps_active)

                def on_all_sps_toggle():
                    new_val = "All SPS" if all_sps_var.get() else ""
                    var.set(new_val)
                    self.controller.update_device_config(dn, f"motor_{midx}_zones", new_val)
                    self.controller.save_profiles()
                    if hasattr(self.controller, 'force_recalculate'):
                        self.controller.force_recalculate()
                    zone_btn.configure(text=get_btn_text(var) + " ▲")
                    sync_individual_checkboxes()

                all_sps_cb = ctk.CTkCheckBox(zone_panel, text="All SPS (match any zone)", variable=all_sps_var, command=on_all_sps_toggle)
                all_sps_cb.pack(anchor="w", pady=(6, 2), padx=8)

                sep = ctk.CTkLabel(zone_panel, text="─── Detected Zones ───", text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(size=11))
                sep.pack(pady=(5, 3))

                for zone in fresh_zones:
                    if zone == "None":
                        continue
                    initial_state = (zone in current_selected) if not is_all_sps_active else False
                    cb_var = ctk.BooleanVar(value=initial_state)
                    zone_panel_cb_vars.append((zone, cb_var))
                    cb = ctk.CTkCheckBox(zone_panel, text=zone, variable=cb_var,
                                         command=lambda z=zone, v=cb_var: toggle_zone(z, v))
                    cb.pack(anchor="w", pady=3, padx=8)

                ctk.CTkFrame(zone_panel, height=6, fg_color="transparent").pack()

            def toggle_zone_panel():
                zone_expanded[0] = not zone_expanded[0]
                if zone_expanded[0]:
                    build_zone_panel()
                    zone_panel.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 5), sticky="ew")
                    zone_btn.configure(text=get_btn_text(zones_var) + " ▲")
                else:
                    zone_panel.grid_forget()
                    zone_btn.configure(text=get_btn_text(zones_var))

            zone_btn = ctk.CTkButton(
                motor_frame,
                text=get_btn_text(zones_var),
                fg_color=COLOR_SURFACE,
                hover_color=COLOR_SURFACE_HOVER,
                command=toggle_zone_panel
            )
            zone_btn.grid(row=0, column=1, padx=(0, 10), pady=(10, 5), sticky="ew")

            # Row 2: Interaction Filters
            filter_frame = ctk.CTkFrame(motor_frame, fg_color="transparent")
            filter_frame.grid(row=2, column=0, columnspan=2, padx=10, pady=0, sticky="ew")
            
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

            # Row 3: Linear-actuator controls (only when this motor is a stroker).
            # Lets the user pick between OGB-style depth-based "Position" mode and
            # the new continuous-oscillation "Speed" mode, plus what to do when the
            # routed level returns to zero ("Hold" = freeze, "Rest" = drift to resting_pos).
            this_kind = motor_kinds[motor_idx] if (motor_kinds and motor_idx < len(motor_kinds)) else None
            if this_kind in ("linear", "linear-d"):
                linear_frame = ctk.CTkFrame(motor_frame, fg_color="transparent")
                linear_frame.grid(row=3, column=0, columnspan=2, padx=10, pady=(2, 4), sticky="ew")

                ctk.CTkLabel(linear_frame, text="Mode:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
                current_mode = self.controller.get_profile_config(device_name, f"motor_{motor_idx}_linear_mode", "position")
                mode_btn = ctk.CTkSegmentedButton(
                    linear_frame,
                    values=["Position", "Speed"],
                    width=140, height=22,
                    command=lambda val, dn=device_name, idx=motor_idx: (
                        self.controller.update_device_config(dn, f"motor_{idx}_linear_mode", val.lower()),
                        self.controller.save_profiles(),
                        self.controller.update_linear_motor_config(dn, idx) if hasattr(self.controller, "update_linear_motor_config") else None,
                    ),
                )
                mode_btn.set("Speed" if current_mode == "speed" else "Position")
                mode_btn.pack(side="left", padx=(0, 12))

                ctk.CTkLabel(linear_frame, text="Idle:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 4))
                current_idle = self.controller.get_profile_config(device_name, f"motor_{motor_idx}_linear_idle", "rest")
                idle_btn = ctk.CTkSegmentedButton(
                    linear_frame,
                    values=["Hold", "Rest"],
                    width=110, height=22,
                    command=lambda val, dn=device_name, idx=motor_idx: (
                        self.controller.update_device_config(dn, f"motor_{idx}_linear_idle", val.lower()),
                        self.controller.save_profiles(),
                        self.controller.update_linear_motor_config(dn, idx) if hasattr(self.controller, "update_linear_motor_config") else None,
                    ),
                )
                idle_btn.set("Hold" if current_idle == "hold" else "Rest")
                idle_btn.pack(side="left")

            # Row 4: Custom OSC Addresses (list of chips + Add button).
            # Each motor can have N addresses; the router takes the max.
            raw_entry = osc_addresses.get(str(motor_idx), [])
            if isinstance(raw_entry, str):
                addresses_list = [raw_entry] if raw_entry.strip() else []
            elif isinstance(raw_entry, list):
                addresses_list = [a for a in raw_entry if isinstance(a, str)]
            else:
                addresses_list = []

            self._setup_motor_address_row(
                motor_frame, device_name, motor_idx, addresses_list, row=4
            )

            # Row 5: Intensity Slider
            slider = ctk.CTkSlider(motor_frame, from_=0.0, to=1.0, command=lambda val, dn=device_name, idx=motor_idx: self.controller.update_device_target(dn, float(val), idx))
            slider.set(0.0)
            slider.grid(row=5, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="ew")

            # Row 6: Vibe Meter
            vibe_meter = ctk.CTkProgressBar(motor_frame, height=6)
            vibe_meter.set(0.0)
            vibe_meter.grid(row=6, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew")

            motor_vars.append({
                "slider": slider,
                "vibe_meter": vibe_meter,
                "addresses": addresses_list,
            })
        
        # Return unified frame data with all elements
        return {
            "frame": device_frame,
            "status_label": name_label,
            "battery_label": battery_label,
            "delete_button": delete_button,
            "motors": motor_vars
        }

    def _setup_motor_address_row(self, motor_frame, device_name, motor_idx, addresses_list, row):
        """Build the per-motor custom-address row (chip list + Add Variable button).
        Lives in its own method so each motor gets its own closure scope."""
        addr_container = ctk.CTkFrame(motor_frame, fg_color="transparent")
        addr_container.grid(row=row, column=0, columnspan=2, padx=10, pady=(5, 5), sticky="ew")
        addr_container.grid_columnconfigure(0, weight=1)

        chips_frame = ctk.CTkFrame(addr_container, fg_color="transparent")
        chips_frame.grid(row=0, column=0, columnspan=2, sticky="ew")

        def persist():
            current = self.controller.get_profile_config(device_name, "osc_addresses", {}) or {}
            if not isinstance(current, dict):
                current = {}
            current[str(motor_idx)] = list(addresses_list)
            self.controller.update_device_config(device_name, "osc_addresses", current)
            self.controller.save_profiles()
            if hasattr(self.controller, 'force_recalculate'):
                self.controller.force_recalculate()

        def render():
            for w in chips_frame.winfo_children():
                w.destroy()
            if not addresses_list:
                ctk.CTkLabel(
                    chips_frame,
                    text="No addresses — click 'Add Variable' to map an OSC parameter.",
                    font=ctk.CTkFont(size=11),
                    text_color=COLOR_TEXT_MUTED,
                ).pack(anchor="w", padx=4, pady=2)
                return
            for i, addr in enumerate(addresses_list):
                chip = ctk.CTkFrame(chips_frame, fg_color=COLOR_SURFACE_HOVER, corner_radius=10)
                chip.pack(side="top", anchor="w", fill="x", pady=1)
                ctk.CTkLabel(
                    chip, text=addr, font=ctk.CTkFont(size=11), anchor="w"
                ).pack(side="left", padx=(8, 4), pady=2, fill="x", expand=True)
                ctk.CTkButton(
                    chip, text="×", width=22, height=20,
                    fg_color="transparent", hover_color=COLOR_ALERT_HOVER,
                    text_color=COLOR_ALERT,
                    font=ctk.CTkFont(size=14, weight="bold"),
                    command=lambda idx=i: self._remove_motor_address(addresses_list, idx, render, persist),
                ).pack(side="right", padx=(2, 4))

        def add_address(new_addr):
            cleaned = (new_addr or "").strip()
            if cleaned.startswith("/avatar/parameters/"):
                cleaned = cleaned[len("/avatar/parameters/"):]
            elif cleaned.startswith("/"):
                cleaned = cleaned[1:]
            if not cleaned or cleaned in addresses_list:
                return
            addresses_list.append(cleaned)
            render()
            persist()

        ctk.CTkButton(
            addr_container,
            text="+ Add Variable",
            height=BTN_HEIGHT_SMALL,
            fg_color=COLOR_SURFACE,
            hover_color=COLOR_SURFACE_HOVER,
            command=lambda: self._open_variable_picker(add_address),
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 2))

        render()

    @staticmethod
    def _remove_motor_address(lst, idx, render, persist):
        if 0 <= idx < len(lst):
            lst.pop(idx)
            render()
            persist()

    def _open_variable_picker(self, on_pick):
        """Open a modal that lists live avatar parameters from the store.

        Uses a native ttk.Treeview because CTk widgets are far too heavy when
        there are several hundred avatar parameters (rebuilding the list on
        every keystroke caused multi-second freezes). The Treeview can handle
        thousands of rows without breaking a sweat.
        """
        import tkinter as tk
        from tkinter import ttk

        win = ctk.CTkToplevel(self.app)
        win.title("Add OSC Variable")
        win.geometry("560x600")
        win.transient(self.app)
        try:
            win.grab_set()
        except Exception:
            pass

        ctk.CTkLabel(
            win, text="Add OSC Variable", font=("Arial", 18, "bold"),
            text_color=COLOR_PRIMARY,
        ).pack(pady=(12, 4))
        ctk.CTkLabel(
            win,
            text="Pick from live avatar parameters (double-click to add) or enter one manually.",
            font=ctk.CTkFont(size=11),
            text_color=COLOR_TEXT_MUTED,
        ).pack(pady=(0, 8))

        search_var = ctk.StringVar()
        search_entry = ctk.CTkEntry(
            win,
            placeholder_text="Search avatar parameters...",
            textvariable=search_var,
            height=30,
        )
        search_entry.pack(fill="x", padx=12, pady=(0, 6))

        show_all_var = ctk.BooleanVar(value=False)
        toggle_row = ctk.CTkFrame(win, fg_color="transparent")
        toggle_row.pack(fill="x", padx=12, pady=(0, 4))
        ctk.CTkCheckBox(
            toggle_row,
            text="Include non-avatar parameters (OGB/SPS, system, etc.)",
            variable=show_all_var,
            font=ctk.CTkFont(size=11),
            command=lambda: refresh(force=True),
        ).pack(side="left")

        # Native tk frame to host the Treeview (CTk's scrollable frame is far too
        # slow for hundreds of rows).
        tree_frame = tk.Frame(win, bg=COLOR_BG, highlightthickness=0, bd=0)
        tree_frame.pack(expand=True, fill="both", padx=12, pady=(0, 8))

        # Style the Treeview to fit the dark theme.
        ttk_style = ttk.Style(win)
        try:
            ttk_style.theme_use("clam")
        except tk.TclError:
            pass
        ttk_style.configure(
            "Picker.Treeview",
            background=COLOR_BG, foreground=COLOR_TEXT,
            fieldbackground=COLOR_BG, bordercolor=COLOR_BG,
            rowheight=22, font=("Consolas", 10),
        )
        ttk_style.map(
            "Picker.Treeview",
            background=[("selected", COLOR_PRIMARY)],
            foreground=[("selected", "white")],
        )
        ttk_style.configure(
            "Picker.Treeview.Heading",
            background=COLOR_SURFACE, foreground=COLOR_TEXT,
            relief="flat", font=("Arial", 10, "bold"),
        )

        tree = ttk.Treeview(
            tree_frame,
            columns=("value",),
            show="tree headings",
            style="Picker.Treeview",
            selectmode="browse",
        )
        tree.heading("#0", text="Parameter")
        tree.heading("value", text="Value")
        tree.column("#0", width=380, anchor="w", stretch=True)
        tree.column("value", width=120, anchor="e", stretch=False)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", expand=True, fill="both")
        vsb.pack(side="right", fill="y")

        empty_label = ctk.CTkLabel(
            win, text="No avatar parameters seen yet.",
            text_color=COLOR_TEXT_MUTED, font=ctk.CTkFont(size=11),
        )

        state = {
            "closed": False,
            "last_filtered": None,   # tuple of currently shown keys
            "last_keys": None,       # tuple of all avatar param keys (sorted)
            "last_query": None,
            "tick_id": None,
            "debounce_id": None,
        }

        def is_avatar_param(addr: str) -> bool:
            # Store strips "/avatar/parameters/" before keys are written, so the
            # avatar variables are everything that isn't an OGB/SPS detection path.
            return not addr.startswith("OGB/")

        def fmt(val):
            if isinstance(val, float):
                return f"{val:.2f}"
            return str(val)

        def add_selected(_evt=None):
            sel = tree.selection()
            if sel:
                add_and_close(sel[0])

        def add_and_close(addr):
            try:
                on_pick(addr)
            finally:
                close_window()

        def rebuild_tree(filtered_keys, params):
            tree.delete(*tree.get_children())
            for key in filtered_keys:
                tree.insert("", "end", iid=key, text=key, values=(fmt(params.get(key, "")),))

        def update_values_only(filtered_keys, params):
            for key in filtered_keys:
                try:
                    tree.set(key, "value", fmt(params.get(key, "")))
                except tk.TclError:
                    pass

        def refresh(force=False):
            if state["closed"]:
                return
            # Cancel any pending tick so we don't stack timers on forced refreshes.
            if state.get("tick_id") is not None:
                try:
                    win.after_cancel(state["tick_id"])
                except Exception:
                    pass
                state["tick_id"] = None

            params = store.get_all_parameters()
            include_all = bool(show_all_var.get())
            if include_all:
                keys = tuple(sorted(params.keys()))
            else:
                keys = tuple(sorted(k for k in params.keys() if is_avatar_param(k)))
            query = search_var.get().strip().lower()

            keys_changed = keys != state["last_keys"]
            query_changed = query != state["last_query"]
            state["last_keys"] = keys
            state["last_query"] = query

            if not keys:
                tree.delete(*tree.get_children())
                empty_label.pack(pady=10)
                state["last_filtered"] = ()
            else:
                empty_label.pack_forget()
                if force or keys_changed or query_changed:
                    filtered = tuple(k for k in keys if not query or query in k.lower())
                    state["last_filtered"] = filtered
                    rebuild_tree(filtered, params)
                else:
                    update_values_only(state["last_filtered"] or (), params)

            # Periodic value refresh (cheap when nothing changed).
            state["tick_id"] = win.after(1500, refresh)

        def on_search_change(*_):
            # Debounce: only re-filter after the user pauses typing.
            if state["debounce_id"] is not None:
                try:
                    win.after_cancel(state["debounce_id"])
                except Exception:
                    pass
            state["debounce_id"] = win.after(180, refresh)

        search_var.trace_add("write", on_search_change)
        tree.bind("<Double-Button-1>", add_selected)
        tree.bind("<Return>", add_selected)

        # Bottom row: manual entry + Add Selected
        bottom = ctk.CTkFrame(win, fg_color=COLOR_SURFACE, corner_radius=6)
        bottom.pack(fill="x", padx=12, pady=(0, 12))
        ctk.CTkLabel(
            bottom, text="Or add manually (wildcards allowed, e.g. OGB/Tail/*):",
            font=ctk.CTkFont(size=11), text_color=COLOR_TEXT_MUTED, anchor="w",
        ).pack(fill="x", padx=8, pady=(6, 2))
        manual_row = ctk.CTkFrame(bottom, fg_color="transparent")
        manual_row.pack(fill="x", padx=8, pady=(0, 8))
        manual_entry = ctk.CTkEntry(manual_row, placeholder_text="e.g. OGB/Tail/Touch")
        manual_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def submit_manual(_evt=None):
            text = manual_entry.get().strip()
            if text:
                add_and_close(text)

        manual_entry.bind("<Return>", submit_manual)
        ctk.CTkButton(
            manual_row, text="Add Manual", width=100, height=BTN_HEIGHT_SMALL,
            fg_color=COLOR_SURFACE_HOVER, hover_color=COLOR_PRIMARY_HOVER,
            command=submit_manual,
        ).pack(side="right")

        action_row = ctk.CTkFrame(bottom, fg_color="transparent")
        action_row.pack(fill="x", padx=8, pady=(0, 8))
        ctk.CTkButton(
            action_row, text="Add Selected", height=BTN_HEIGHT_SMALL,
            fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY_HOVER,
            command=add_selected,
        ).pack(side="right")

        def close_window():
            state["closed"] = True
            for key in ("tick_id", "debounce_id"):
                aid = state.get(key)
                if aid is not None:
                    try:
                        win.after_cancel(aid)
                    except Exception:
                        pass
                    state[key] = None
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", close_window)
        refresh()
        search_entry.focus_set()

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
            
            # Get OSC addresses dict from config, with backward compatibility.
            # Each value is expected to be a list[str]; older configs may still
            # have a string which _create_device_frame will normalize.
            osc_addresses = config.get("osc_addresses", {})
            if not osc_addresses and config.get("osc_address"):
                osc_addresses["0"] = [config.get("osc_address")]
            
            # Pull persisted motor kinds (saved by _sync_linear_configs on connect).
            # Falls back to None when the device has never been seen by this build,
            # which simply means no linear UI is rendered until first connect.
            stored_motor_kinds = config.get("motor_kinds")

            # Create frame using the helper method
            frame_data = self._create_device_frame(
                device_name=device_name,
                is_connected=is_connected,
                osc_addresses=osc_addresses,
                motor_count=stored_motor_count,
                motor_kinds=stored_motor_kinds,
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
                    osc_addresses[str(i)] = [f"{device_name.replace(' ', '_')}{suffix}"]
                
                # Store motor count in profile via controller
                controller.update_device_config(device_name, "motor_count", motor_count)
                
                # Pull motor kinds from the device payload so linear motors render
                # the Mode/Idle controls; vibrate-only devices stay visually unchanged.
                motor_kinds = device_info.get("motor_kinds") if isinstance(device_info, dict) else None

                # Device is connected since it was just discovered, so use green checkmark
                frame_data = self._create_device_frame(
                    device_name=device_name,
                    is_connected=True,
                    osc_addresses=osc_addresses,
                    motor_count=actual_motor_count,
                    motor_kinds=motor_kinds,
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
        self._reorder_device_frames()

    def _reorder_device_frames(self):
        """Re-pack device frames so connected devices appear at the top."""
        connected_names = self.controller.get_connected_device_names()
        all_names = list(self.device_ui_frames.keys())
        all_names.sort(key=lambda name: (name not in connected_names, name.lower()))
        for name in all_names:
            frame = self.device_ui_frames[name]["frame"]
            frame.pack_forget()
            frame.pack(expand=False, fill="x", pady=(0, 10), padx=5)

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

    # ============================================================
    # Framework-agnostic facade — main.py interacts with the UI
    # exclusively through these methods so the GUI toolkit can be
    # swapped (CustomTkinter -> PySide6) without touching the
    # controller.
    # ============================================================

    # --- Window lifecycle ---
    def set_title(self, text: str) -> None:
        if self.app:
            self.app.title(text)

    def set_geometry(self, geometry: str) -> None:
        if self.app and geometry:
            self.app.geometry(geometry)

    def get_geometry(self) -> str:
        if self.app:
            try:
                return self.app.geometry()
            except Exception:
                return ""
        return ""

    def set_close_handler(self, callback) -> None:
        if self.app:
            self.app.protocol("WM_DELETE_WINDOW", callback)

    def schedule_callback(self, delay_ms: int, func) -> None:
        """Schedule `func` to run on the UI thread after `delay_ms`."""
        if self.app:
            self.app.after(delay_ms, func)

    def schedule_on_main_thread(self, func) -> None:
        """Run `func` on the UI thread as soon as possible (thread-safe)."""
        if self.app:
            self.app.after(0, func)

    def hide_window(self) -> None:
        if self.app:
            self.app.withdraw()

    def show_window(self) -> None:
        """Restore the window from a hidden/tray state (thread-safe)."""
        if self.app:
            self.app.after(0, self.app.deiconify)

    def run(self) -> None:
        """Enter the UI event loop. Blocks until the window is closed."""
        if self.app:
            self.app.mainloop()

    def shutdown(self) -> None:
        """Exit the event loop and tear down the window."""
        if self.app:
            try:
                self.app.quit()
            finally:
                self.app.destroy()

    # --- Settings checkbox state ---
    def get_auto_connect_enabled(self) -> bool:
        var = getattr(self, "auto_connect_var", None)
        return bool(var.get()) if var is not None else False

    def get_auto_refresh_enabled(self) -> bool:
        var = getattr(self, "auto_refresh_var", None)
        return bool(var.get()) if var is not None else False

    def get_osc_auto_connect_enabled(self) -> bool:
        var = getattr(self, "osc_auto_connect_var", None)
        return bool(var.get()) if var is not None else False

    # --- OSC debugger ---
    def get_osc_search_query(self) -> str:
        var = getattr(self, "osc_search_var", None)
        if var is None:
            return ""
        try:
            return var.get().lower()
        except Exception:
            return ""

    def update_sps_status(self, text: str) -> None:
        label = getattr(self, "sps_status_label", None)
        if label is not None:
            label.configure(text=text)

    def update_motor_vibe(self, device_name: str, motor_idx: int, value: float) -> None:
        """Update only the vibe-meter visualization for a motor (leaves
        the user-facing slider alone). Used by the OSC haptic update path."""
        if device_name not in self.device_ui_frames:
            return
        motors = self.device_ui_frames[device_name].get("motors", [])
        if 0 <= motor_idx < len(motors):
            motors[motor_idx]["vibe_meter"].set(value)

    # --- Device frame management ---
    def remove_device_frame(self, device_name: str) -> None:
        """Destroy and forget the stored-device card for `device_name`."""
        frame_data = self.stored_device_frames.pop(device_name, None)
        if frame_data:
            frame = frame_data.get("frame")
            if frame is not None:
                try:
                    frame.destroy()
                except Exception:
                    pass
        self.device_ui_frames.pop(device_name, None)

    def clear_device_caches(self) -> None:
        """Drop cached device-frame references (used on profile switch)."""
        try:
            self.device_ui_frames.clear()
            self.stored_device_frames.clear()
        except Exception:
            pass

    def get_known_device_names(self) -> list:
        return list(self.device_ui_frames.keys())
