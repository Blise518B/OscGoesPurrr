# pyside_ui.py - Full Hardware-Accelerated UI for OscGoesPurrr
import sys
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QStackedWidget, QScrollArea, QSlider, QProgressBar, QPlainTextEdit, 
    QCheckBox, QFrame, QLineEdit, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

# Use our newly consolidated 10-color system
from constants import *
from utilities import value_to_hex_color

class OscGoesPurrrUI(QMainWindow):
    """Modern PySide6 UI Component - handles all GUI rendering and updates."""
    
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        
        # UI Element Tracking
        self.nav_buttons = []
        self.device_ui_frames = {}       # Tracking widgets for updates
        self.stored_device_frames = {}   # Legacy tracking
        
        # Setup Main Window
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 750)
        self.apply_stylesheet()
        
        # Main Layout (Sidebar + Stacked Content)
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Initialize Core UI Components
        self.stacked_widget = QStackedWidget()
        self._build_sidebar()
        self.main_layout.addWidget(self.stacked_widget, stretch=1)
        
        # Build All Views (1-to-1 feature parity)
        self._build_dashboard_view()
        self._build_devices_view()
        self._build_logs_view()
        self._build_settings_view()

        # Hook Window Close Event for System Tray
        self.setAttribute(Qt.WA_DeleteOnClose, False)

    def apply_stylesheet(self):
        """Injects our strict 10-color constants into the global Qt StyleSheet."""
        stylesheet = f"""
            QMainWindow, QWidget {{
                background-color: {COLOR_BG};
                color: {COLOR_TEXT};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QFrame#Sidebar {{
                background-color: {COLOR_SURFACE};
                border-right: 1px solid {COLOR_BG};
            }}
            QFrame#Card {{
                background-color: {COLOR_SURFACE};
                border-radius: 8px;
                padding: 10px;
            }}
            
            /* Buttons */
            QPushButton {{
                background-color: {COLOR_PRIMARY};
                color: {COLOR_TEXT};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {COLOR_PRIMARY_HOVER}; }}
            QPushButton:disabled {{ background-color: {COLOR_SURFACE_HOVER}; color: {COLOR_TEXT_MUTED}; }}
            
            QPushButton#DangerButton {{ background-color: {COLOR_ALERT}; }}
            QPushButton#DangerButton:hover {{ background-color: {COLOR_ALERT_HOVER}; }}
            
            QPushButton#SecondaryButton {{ background-color: {COLOR_SURFACE_HOVER}; }}
            QPushButton#SecondaryButton:hover {{ background-color: {COLOR_PRIMARY}; }}
            
            QPushButton#NavButton {{
                background-color: transparent;
                text-align: left;
                padding: 12px 20px;
                border-radius: 0px;
                font-size: 14px;
            }}
            QPushButton#NavButton:hover {{ background-color: {COLOR_SURFACE_HOVER}; }}
            QPushButton#NavButton:checked {{
                background-color: {COLOR_BG};
                border-left: 4px solid {COLOR_PRIMARY};
            }}

            /* Inputs & Controls */
            QLineEdit {{
                background-color: {COLOR_BG};
                color: {COLOR_TEXT};
                border: 1px solid {COLOR_SURFACE_HOVER};
                border-radius: 4px;
                padding: 6px;
            }}
            QCheckBox::indicator {{
                width: 18px; height: 18px;
                border-radius: 4px;
                background-color: {COLOR_BG};
                border: 1px solid {COLOR_SURFACE_HOVER};
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLOR_PRIMARY};
                border: 1px solid {COLOR_PRIMARY};
            }}
            
            /* Typography */
            QLabel#Header {{ font-size: 18px; font-weight: bold; }}
            QLabel#SubHeader {{ font-size: 14px; font-weight: bold; color: {COLOR_TEXT_MUTED}; }}
            QLabel#Muted {{ color: {COLOR_TEXT_MUTED}; }}
            QLabel#Success {{ color: {COLOR_SUCCESS}; font-weight: bold; }}
            QLabel#Alert {{ color: {COLOR_ALERT}; font-weight: bold; }}
            
            /* Hardware Controls */
            QSlider::groove:horizontal {{
                border-radius: 4px; height: 8px; background: {COLOR_BG};
            }}
            QSlider::handle:horizontal {{
                background: {COLOR_PRIMARY}; width: 16px; height: 16px;
                margin: -4px 0; border-radius: 8px;
            }}
            QProgressBar {{
                border: none; border-radius: 4px; background-color: {COLOR_BG};
                text-align: center; color: transparent; height: 8px;
            }}
            QProgressBar::chunk {{ background-color: {COLOR_PRIMARY}; border-radius: 4px; }}
            
            /* Consoles */
            QPlainTextEdit {{
                background-color: {COLOR_BG};
                border: 1px solid {COLOR_SURFACE_HOVER};
                border-radius: 4px;
                font-family: Consolas, monospace; padding: 10px;
            }}
            QScrollBar:vertical {{ background: {COLOR_BG}; width: 12px; }}
            QScrollBar::handle:vertical {{ background: {COLOR_SURFACE_HOVER}; border-radius: 6px; }}
        """
        self.setStyleSheet(stylesheet)

    # ==========================================
    # CORE LAYOUT BUILDERS
    # ==========================================
    
    def _build_sidebar(self):
        self.sidebar = QFrame(objectName="Sidebar")
        self.sidebar.setFixedWidth(SIDEBAR_WIDTH)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 20, 0, 20)
        
        # App Title
        sidebar_layout.addWidget(QLabel(APP_NAME, objectName="Header", alignment=Qt.AlignCenter))
        
        # Global Status
        self.global_status_label = QLabel("Disconnected", objectName="Alert", alignment=Qt.AlignCenter)
        sidebar_layout.addWidget(self.global_status_label)
        sidebar_layout.addSpacing(20)
        
        # Navigation
        self._add_nav_btn("Dashboard", 0, sidebar_layout)
        self._add_nav_btn("Device Routing", 1, sidebar_layout)
        self._add_nav_btn("System Logs", 2, sidebar_layout)
        self._add_nav_btn("Settings", 3, sidebar_layout)
        
        sidebar_layout.addStretch()
        self.main_layout.addWidget(self.sidebar)

    def _add_nav_btn(self, text, index, layout):
        btn = QPushButton(text, objectName="NavButton")
        btn.setCheckable(True)
        if index == 0: btn.setChecked(True)
        btn.clicked.connect(lambda: self._switch_page(index, btn))
        layout.addWidget(btn)
        self.nav_buttons.append(btn)

    def _switch_page(self, index, active_btn):
        self.stacked_widget.setCurrentIndex(index)
        for btn in self.nav_buttons:
            btn.setChecked(btn == active_btn)

    # ==========================================
    # VIEW: DASHBOARD
    # ==========================================
    
    def _build_dashboard_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.addWidget(QLabel("OSC & Hardware Dashboard", objectName="Header"))
        
        # --- Card 1: Haptic Engine ---
        hw_card = QFrame(objectName="Card")
        hw_layout = QVBoxLayout(hw_card)
        hw_layout.addWidget(QLabel("Intiface Central Engine", objectName="SubHeader"))
        
        hw_ctrl_layout = QHBoxLayout()
        self.hw_status_label = QLabel("Disconnected", objectName="Alert")
        self.hw_connect_btn = QPushButton("Connect Intiface")
        self.hw_connect_btn.clicked.connect(self.controller.toggle_connection)
        
        hw_auto_cb = QCheckBox("Auto-Connect Hardware")
        hw_auto_cb.setChecked(self.controller.get_app_setting("auto_connect", True))
        hw_auto_cb.toggled.connect(lambda v: self.controller.set_app_setting("auto_connect", v))
        
        hw_ctrl_layout.addWidget(self.hw_status_label)
        hw_ctrl_layout.addWidget(self.hw_connect_btn)
        hw_ctrl_layout.addStretch()
        hw_ctrl_layout.addWidget(hw_auto_cb)
        hw_layout.addLayout(hw_ctrl_layout)
        layout.addWidget(hw_card)
        
        # --- Card 2: VRChat OSC Network ---
        osc_card = QFrame(objectName="Card")
        osc_layout = QVBoxLayout(osc_card)
        osc_layout.addWidget(QLabel("VRChat OSC Network", objectName="SubHeader"))
        
        osc_ctrl_layout = QHBoxLayout()
        self.osc_status_label = QLabel("Disconnected", objectName="Alert")
        
        self.osc_port_input = QLineEdit()
        self.osc_port_input.setPlaceholderText("Port (Default 9000)")
        self.osc_port_input.setFixedWidth(120)
        self.osc_port_input.setText(str(self.controller.get_profile_config("Network", "OSC Port", 9000)))
        
        self.osc_connect_btn = QPushButton("Connect OSC")
        self.osc_connect_btn.clicked.connect(self._handle_osc_connect_click)
        
        osc_auto_cb = QCheckBox("Auto-Connect OSC")
        osc_auto_cb.setChecked(self.controller.get_app_setting("auto_connect_osc", True))
        osc_auto_cb.toggled.connect(lambda v: self.controller.set_app_setting("auto_connect_osc", v))
        
        osc_ctrl_layout.addWidget(self.osc_status_label)
        osc_ctrl_layout.addWidget(self.osc_port_input)
        osc_ctrl_layout.addWidget(self.osc_connect_btn)
        osc_ctrl_layout.addStretch()
        osc_ctrl_layout.addWidget(osc_auto_cb)
        osc_layout.addLayout(osc_ctrl_layout)
        layout.addWidget(osc_card)
        
        # --- Card 3: OSC Debugger (Shadow State) ---
        dbg_card = QFrame(objectName="Card")
        dbg_layout = QVBoxLayout(dbg_card)
        
        dbg_header_layout = QHBoxLayout()
        dbg_header_layout.addWidget(QLabel("OSC Shadow State Monitor", objectName="SubHeader"))
        self.dbg_stats_label = QLabel("Parameters: 0", objectName="Muted")
        dbg_header_layout.addWidget(self.dbg_stats_label)
        dbg_header_layout.addStretch()
        
        self.dbg_refresh_cb = QCheckBox("Live Auto-Refresh")
        self.dbg_refresh_cb.setChecked(self.controller.get_app_setting("auto_refresh", True))
        self.dbg_refresh_cb.toggled.connect(lambda v: self.controller.set_app_setting("auto_refresh", v))
        dbg_header_layout.addWidget(self.dbg_refresh_cb)
        
        dbg_layout.addLayout(dbg_header_layout)
        
        self.debugger_text = QPlainTextEdit()
        self.debugger_text.setReadOnly(True)
        dbg_layout.addWidget(self.debugger_text)
        layout.addWidget(dbg_card, stretch=1)
        
        self.stacked_widget.addWidget(page)

    def _handle_osc_connect_click(self):
        """Saves the port before telling the Orchestrator to connect."""
        try:
            port = int(self.osc_port_input.text())
            self.controller.update_device_config("Network", "OSC Port", port)
            self.controller.save_profiles()
        except ValueError:
            pass # Fall back to backend defaults if invalid
        self.controller.toggle_osc_connection()

    # ==========================================
    # VIEW: DEVICE ROUTING
    # ==========================================
    
    def _build_devices_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.addWidget(QLabel("Connected Toys & Routing", objectName="Header"))
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        
        self.devices_container = QWidget()
        self.devices_layout = QVBoxLayout(self.devices_container)
        self.devices_layout.setAlignment(Qt.AlignTop)
        self.devices_layout.setSpacing(15)
        
        scroll_area.setWidget(self.devices_container)
        layout.addWidget(scroll_area)
        self.stacked_widget.addWidget(page)

    def build_device_list_ui(self, devices_dict: dict):
        """Clears and rebuilds the full device routing view dynamically."""
        for i in reversed(range(self.devices_layout.count())): 
            widget = self.devices_layout.itemAt(i).widget()
            if widget: widget.deleteLater()
            
        self.device_ui_frames.clear()

        if not devices_dict:
            self.devices_layout.addWidget(QLabel("No toys currently connected or saved.", objectName="Muted"))
            return

        motor_counts = self.controller.get_device_motor_counts()

        for name, config in devices_dict.items():
            card = QFrame(objectName="Card")
            card_layout = QVBoxLayout(card)
            
            # --- Device Header ---
            header_layout = QHBoxLayout()
            header_layout.addWidget(QLabel(name, objectName="SubHeader"))
            
            purr_btn = QPushButton("Intense Purr Check", objectName="SecondaryButton")
            # Briefly spike all motors to 100% to test connection
            purr_btn.clicked.connect(lambda _, n=name: self.controller.update_device_target(n, 1.0, -1))
            
            del_btn = QPushButton("Remove Device", objectName="DangerButton")
            del_btn.clicked.connect(lambda _, n=name: self.controller.delete_device_profile(n))
            
            header_layout.addStretch()
            header_layout.addWidget(purr_btn)
            header_layout.addWidget(del_btn)
            card_layout.addLayout(header_layout)
            
            # --- Motor Routing Rows ---
            count = motor_counts.get(name, config.get("motor_count", 1))
            motors = []
            
            for i in range(count):
                motor_frame = QFrame()
                motor_frame.setStyleSheet(f"background-color: {COLOR_BG}; border-radius: 4px; padding: 5px;")
                m_layout = QVBoxLayout(motor_frame)
                
                # Routing Row
                route_row = QHBoxLayout()
                route_row.addWidget(QLabel(f"Motor {i} Osc Override:", objectName="Muted"))
                
                addr_input = QLineEdit()
                addr_input.setPlaceholderText("/avatar/parameters/...")
                saved_addr = config.get("osc_addresses", {}).get(str(i), "")
                addr_input.setText(saved_addr)
                
                # Save override text to config when user stops typing
                addr_input.editingFinished.connect(
                    lambda n=name, idx=i, inp=addr_input: self._save_osc_override(n, idx, inp.text())
                )
                
                route_row.addWidget(addr_input, stretch=1)
                m_layout.addLayout(route_row)
                
                # Hardware Display Row (Slider + Progress)
                hw_row = QHBoxLayout()
                
                slider = QSlider(Qt.Horizontal)
                slider.setRange(0, 1000)
                # Send manual debug signals to backend
                slider.valueChanged.connect(lambda val, n=name, idx=i: self.controller.update_device_target(n, val/1000.0, idx))
                
                meter = QProgressBar()
                meter.setRange(0, 100)
                meter.setTextVisible(False)
                
                hw_row.addWidget(slider, stretch=1)
                hw_row.addWidget(meter, stretch=1)
                m_layout.addLayout(hw_row)
                
                motors.append({"slider": slider, "vibe_meter": meter})
                card_layout.addWidget(motor_frame)

            self.device_ui_frames[name] = {"motors": motors}
            self.devices_layout.addWidget(card)

    def _save_osc_override(self, device_name, motor_idx, new_address):
        """Helper to save the custom OSC address routing for a specific motor."""
        current_addresses = self.controller.get_profile_config(device_name, "osc_addresses", {})
        current_addresses[str(motor_idx)] = new_address
        self.controller.update_device_config(device_name, "osc_addresses", current_addresses)
        self.controller.save_profiles()

    def update_device_visuals(self, device_name: str, motor_idx: int, value: float):
        """Translates the float target (0.0 to 1.0) to Qt Int ranges."""
        if device_name in self.device_ui_frames:
            motors = self.device_ui_frames[device_name].get("motors", [])
            
            slider_val = int(value * 1000)
            meter_val = int(value * 100)
            
            if 0 <= motor_idx < len(motors):
                motors[motor_idx]["slider"].blockSignals(True)
                motors[motor_idx]["slider"].setValue(slider_val)
                motors[motor_idx]["slider"].blockSignals(False)
                motors[motor_idx]["vibe_meter"].setValue(meter_val)
            elif motor_idx == -1: # Update all motors
                for m in motors:
                    m["slider"].blockSignals(True)
                    m["slider"].setValue(slider_val)
                    m["slider"].blockSignals(False)
                    m["vibe_meter"].setValue(meter_val)

    # ==========================================
    # VIEW: SYSTEM LOGS
    # ==========================================
    
    def _build_logs_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("System Event Logs", objectName="Header"))
        header_layout.addStretch()
        
        clear_btn = QPushButton("Clear Logs", objectName="SecondaryButton")
        clear_btn.clicked.connect(lambda: self.log_text.clear())
        header_layout.addWidget(clear_btn)
        layout.addLayout(header_layout)
        
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)
        self.stacked_widget.addWidget(page)

    def log_message(self, msg: str):
        """Appends to log and auto-scrolls."""
        if hasattr(self, 'log_text') and self.log_text:
            self.log_text.appendPlainText(msg)
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    # ==========================================
    # VIEW: SETTINGS
    # ==========================================
    
    def _build_settings_view(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.addWidget(QLabel("Application Settings", objectName="Header"))
        
        card = QFrame(objectName="Card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(15)
        
        # OSC Bind Setting
        self.bind_cb = QCheckBox("Bind OSC to all local IP Interfaces (0.0.0.0 instead of 127.0.0.1)")
        self.bind_cb.setChecked(self.controller.get_app_setting("bind_all_interfaces", True))
        self.bind_cb.toggled.connect(lambda v: self.controller.set_app_setting("bind_all_interfaces", v))
        card_layout.addWidget(self.bind_cb)
        
        # OS-Level Settings
        self.console_cb = QCheckBox("Hide Terminal Console (Requires restart to show again)")
        self.console_cb.setChecked(self.controller.get_app_setting("hide_console", True))
        self.console_cb.toggled.connect(lambda v: self._update_os_setting("hide_console", v))
        card_layout.addWidget(self.console_cb)
        
        self.tray_cb = QCheckBox("Minimize Application to System Tray on close")
        self.tray_cb.setChecked(self.controller.get_app_setting("minimize_to_tray", False))
        self.tray_cb.toggled.connect(lambda v: self.controller.set_app_setting("minimize_to_tray", v))
        card_layout.addWidget(self.tray_cb)
        
        layout.addWidget(card)
        layout.addStretch()
        self.stacked_widget.addWidget(page)

    def _update_os_setting(self, key, val):
        """Saves setting and immediately pings controller to apply OS changes."""
        self.controller.set_app_setting(key, val)
        if key == "hide_console":
            self.controller.apply_console_visibility()

    # ==========================================
    # STATUS FACADES (Updates from Orchestrator)
    # ==========================================

    def update_connection_status(self, connected: bool, server: str):
        if connected:
            self.hw_status_label.setText("Connected")
            self.hw_status_label.setObjectName("Success")
            self.global_status_label.setText("HW Active")
            self.global_status_label.setObjectName("Success")
            self.hw_connect_btn.setText("Disconnect Intiface")
            self.hw_connect_btn.setObjectName("DangerButton")
        else:
            self.hw_status_label.setText("Disconnected")
            self.hw_status_label.setObjectName("Alert")
            self.global_status_label.setText("Disconnected")
            self.global_status_label.setObjectName("Alert")
            self.hw_connect_btn.setText("Connect Intiface")
            self.hw_connect_btn.setObjectName("")
        self._refresh_widget_style(self.hw_status_label, self.global_status_label, self.hw_connect_btn)

    def update_osc_status(self, is_connected: bool, port: int = None):
        if is_connected:
            self.osc_status_label.setText(f"Listening on Port {port}")
            self.osc_status_label.setObjectName("Success")
            self.osc_connect_btn.setText("Stop OSC Listener")
            self.osc_connect_btn.setObjectName("DangerButton")
            self.osc_port_input.setEnabled(False)
        else:
            self.osc_status_label.setText("Disconnected")
            self.osc_status_label.setObjectName("Alert")
            self.osc_connect_btn.setText("Connect OSC")
            self.osc_connect_btn.setObjectName("")
            self.osc_port_input.setEnabled(True)
        self._refresh_widget_style(self.osc_status_label, self.osc_connect_btn)

    def update_debugger_display(self, formatted_text: str):
        if hasattr(self, 'debugger_text') and self.debugger_text:
            if not self.controller.get_app_setting("auto_refresh", True):
                return
                
            # Count the lines (roughly equals parameter count)
            param_count = len(formatted_text.split('\n')) - 1 
            self.dbg_stats_label.setText(f"Parameters tracking: {param_count}")
            self.debugger_text.setPlainText(formatted_text)

    def _refresh_widget_style(self, *widgets):
        """Forces Qt to re-evaluate QSS dynamically."""
        for w in widgets:
            w.style().unpolish(w)
            w.style().polish(w)

    def closeEvent(self, event):
        """Intercept the native OS window close button for System Tray routing."""
        if self.controller.get_app_setting("minimize_to_tray", False):
            event.ignore()
            self.controller.minimize_to_tray()
        else:
            self.controller.quit_app()
            event.accept()