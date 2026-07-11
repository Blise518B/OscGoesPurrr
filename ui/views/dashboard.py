"""Dashboard, mode switcher, simple-mode panel, and device-routing view.

Mixin for ui_components.OscGoesPurrrUI. Relies on attributes initialised
by OscGoesPurrrUI.__init__ (self.controller, self.invoker, etc.)."""

from typing import List, Optional, Dict, Any, Callable
import os
import sys

from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QEvent, QSize, QPointF, QRectF
)
from PySide6.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor, QIcon,
    QPixmap, QPainter, QPen, QBrush, QPainterPath, QPolygonF
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QSlider, QProgressBar,
    QFrame, QScrollArea, QTextEdit, QPlainTextEdit, QSizePolicy, QSpacerItem,
    QDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QButtonGroup, QStackedWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QComboBox, QSpinBox, QDoubleSpinBox, QToolButton,
    QMenu, QInputDialog,
)
from ui import lovense_icons as _lovense_icons

from constants import *
from parameter_store import store
from utilities import strip_param_prefix

from ui.geometry import parse_tk_geometry as _parse_tk_geometry
from ui.geometry import format_tk_geometry as _format_tk_geometry
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout as _clear_layout
from ui.text_helpers import truncate as _truncate, html_escape as _html_escape
from ui.icons import (
    new_icon_pixmap as _new_icon_pixmap,
    icon_pencil as _icon_pencil,
    icon_copy as _icon_copy,
    icon_paste as _icon_paste,
    icon_trash as _icon_trash,
    icon_check as _icon_check,
    icon_cross as _icon_cross,
)
from ui.widgets import (
    ToggleSwitch,
    Invoker as _Invoker,
    MainWindow as _MainWindow,
    Card as _Card,
    BHapticsDotGrid as _BHapticsDotGrid,
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


class DashboardMixin:

    # ----------------------------------------------------------
    # Dashboard view
    # ----------------------------------------------------------

    def _build_dashboard_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Dashboard")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # ===== Modes card =====
        modes_card = _Card()
        modes_lay = _vbox(16, 10)
        modes_card.setLayout(modes_lay)

        modes_header_row = QWidget()
        mhlay = _hbox(0, 6)
        modes_header_row.setLayout(mhlay)
        modes_header = QLabel("Modes")
        modes_header.setObjectName("sectionTitle")
        mhlay.addWidget(modes_header)
        mhlay.addWidget(self._make_help_badge(
            "Modes",
            "Six fixed modes. A mode is the <b>feel</b> — the signal-chain "
            "settings you edit in Device Routing always apply to the "
            "<b>active</b> mode — plus a master intensity multiplier. "
            "<b>Off</b> is the panic mode: instant silence everywhere. "
            "Modes can also be switched from inside VRChat via the "
            "<b>OGP/Mode</b> Int parameter (menu setup guide: "
            "docs/VRCHAT_MENU.md). The menu's Test button "
            "(<b>OGP/Test</b>) pulses toys, SteamVR and bHaptics at a "
            "low level to confirm the link — e-stim backends are "
            "deliberately excluded from the test pulse."
        ))
        mhlay.addStretch(1)
        modes_lay.addWidget(modes_header_row)

        modes_lay.addWidget(self._muted_label(
            "Click a mode to make it live — Device Routing edits and the "
            "master intensity always target the active mode."
        ))

        # One row per mode, rebuilt by _refresh_mode_buttons whenever the
        # active mode or its metadata change.
        self.mode_list_host = QWidget()
        self.mode_list_layout = _vbox(0, 4)
        self.mode_list_host.setLayout(self.mode_list_layout)
        modes_lay.addWidget(self.mode_list_host)

        # ---- Footer: per-avatar memory + current avatar id ----
        footer = QWidget()
        flay = _hbox(0, 6)
        footer.setLayout(flay)
        self.avatar_modes_toggle = ToggleSwitch("Remember mode per avatar")
        self.avatar_modes_toggle.setChecked(
            bool(self.controller.get_app_setting("avatar_modes_enabled", False))
        )
        self.avatar_modes_toggle.toggled.connect(
            lambda checked: self.controller.set_app_setting(
                "avatar_modes_enabled", bool(checked))
        )
        flay.addWidget(self.avatar_modes_toggle)
        flay.addWidget(self._make_help_badge(
            "Remember mode per avatar",
            "When ON, each avatar restores the mode it last used as it "
            "loads. When OFF, the current mode simply carries across "
            "avatar changes."
        ))
        flay.addStretch(1)
        self.current_avatar_label = QLabel("Current avatar: (not detected)")
        self.current_avatar_label.setProperty("muted", "true")
        flay.addWidget(self.current_avatar_label)
        modes_lay.addWidget(footer)

        parent_layout.addWidget(modes_card)

        # ===== Purr-check card =====
        self.testing_frame = _Card()
        tlay = _vbox(12, 8)
        self.testing_frame.setLayout(tlay)
        self.purr_check_button = QPushButton("Purr-Check (Test All)")
        self.purr_check_button.setMinimumHeight(40)
        self.purr_check_button.clicked.connect(self.controller.trigger_purr_check)
        tlay.addWidget(self.purr_check_button, alignment=Qt.AlignHCenter)
        parent_layout.addWidget(self.testing_frame)
        parent_layout.addStretch(1)

        # Initial render of the mode rows (and the sidebar grid, which is
        # built before this view).
        self._refresh_mode_buttons()

    # ------------------------------------------------------------------
    # Modes section helpers
    # ------------------------------------------------------------------

    def _refresh_mode_buttons(self):
        """Repaint every mode surface from controller.get_modes_info():
        the sidebar grid buttons (restyled in place) and the Dashboard
        mode rows (rebuilt). The controller calls this after every mode
        change — including during early startup before the widgets
        exist, so every widget access is getattr-guarded."""
        ctl = self.controller
        if not hasattr(ctl, "get_modes_info"):
            return
        infos = ctl.get_modes_info()

        # ---- Sidebar grid: text + active highlight, updated in place ----
        for info, btn in zip(infos, getattr(self, "mode_grid_buttons", None) or []):
            try:
                btn.setText(f"{info.get('name', '')}\n{info.get('icon', '')}")
                btn.setProperty("active", "true" if info.get("active") else "false")
                self._repolish(btn)
            except RuntimeError:
                pass  # widget destroyed during a rebuild

        # ---- Current-avatar label (modes-card footer) ----
        lbl = getattr(self, "current_avatar_label", None)
        if lbl is not None:
            avatar_id = ctl.get_current_avatar_id() or ""
            if avatar_id:
                lbl.setText(f"Current avatar: {_truncate(avatar_id, 28)}")
            else:
                lbl.setText("Current avatar: (not detected)")

        # ---- Dashboard rows: rebuilt from scratch ----
        # Skipped while one of our own intensity spinboxes is mid-edit:
        # the controller echoes set_mode_master_scale straight back here,
        # and rebuilding the rows would destroy the very spinbox emitting
        # the change (killing arrow-repeat and keyboard focus).
        layout = getattr(self, "mode_list_layout", None)
        if layout is None or getattr(self, "_mode_scale_updating", False):
            return
        _clear_layout(layout)
        for info in infos:
            layout.addWidget(self._make_mode_row(info))

    def _make_mode_row(self, info: Dict[str, Any]) -> QWidget:
        """One Dashboard mode row: active dot · icon picker · name button
        (switches to the mode) · rename · master-intensity spinbox."""
        index = int(info.get("index", 0))
        is_active = bool(info.get("active"))
        row = QWidget()
        rlay = _hbox(0, 6)
        row.setLayout(rlay)

        # Leading dot: what's actually driving haptics right now.
        dot = QLabel("●" if is_active else "○")
        dot.setProperty("role", "success" if is_active else "muted")
        self._repolish(dot)
        rlay.addWidget(dot)

        icon_btn = QPushButton(info.get("icon", ""))
        icon_btn.setFixedSize(34, 34)
        icon_btn.setProperty("role", "secondary")
        icon_btn.setToolTip("Change icon")
        icon_btn.clicked.connect(
            lambda _=False, i=index, b=icon_btn: self._open_mode_icon_menu(i, b)
        )
        rlay.addWidget(icon_btn)

        name_btn = QPushButton(info.get("name", f"Mode {index}"))
        name_btn.setMinimumHeight(34)
        name_btn.setProperty(
            "role", "profileActive" if is_active else "profileIdle"
        )
        name_btn.clicked.connect(
            lambda _=False, i=index: self.controller.switch_mode(i)
        )
        rlay.addWidget(name_btn, 1)

        rename_btn = QPushButton("")
        rename_btn.setFixedSize(34, 34)
        rename_btn.setProperty("role", "secondary")
        rename_btn.setToolTip("Rename")
        rename_btn.setIcon(_icon_pencil())
        rename_btn.setIconSize(QSize(18, 18))
        rename_btn.clicked.connect(
            lambda _=False, i=index: self._dialog_rename_mode(i)
        )
        rlay.addWidget(rename_btn)

        scale_spin = QSpinBox()
        scale_spin.setRange(0, 100)
        scale_spin.setSuffix("%")
        # Commit on Enter/focus-out, not per typed digit — typing "100"
        # must not drive the hardware at 1% then 10% on the way there.
        # (Held-arrow auto-repeat is coalesced by the facade's debounced
        # save; the live value still applies per step, which is fine.)
        scale_spin.setKeyboardTracking(False)
        scale_spin.setToolTip(
            "Master intensity — multiplies every backend's output in this mode"
        )
        # Seed while signals are blocked, and connect only afterwards, so
        # the programmatic setValue can't echo into the controller.
        scale_spin.blockSignals(True)
        scale_spin.setValue(int(round(float(info.get("master_scale", 1.0)) * 100)))
        scale_spin.blockSignals(False)
        scale_spin.valueChanged.connect(
            lambda v, i=index: self._on_mode_scale_changed(i, v)
        )
        rlay.addWidget(scale_spin)
        return row

    def _on_mode_scale_changed(self, index: int, value: int):
        """Push a master-intensity spinbox edit to the controller. The
        re-entrancy flag makes the controller's synchronous refresh
        callback skip the row rebuild (see _refresh_mode_buttons)."""
        self._mode_scale_updating = True
        try:
            self.controller.set_mode_master_scale(int(index), float(value) / 100.0)
        finally:
            self._mode_scale_updating = False

    def _open_mode_icon_menu(self, index: int, anchor: QWidget):
        """Emoji picker for a mode's icon — a plain QMenu of
        MODE_ICON_CHOICES anchored under the row's icon button."""
        menu = QMenu(anchor)
        for icon in MODE_ICON_CHOICES:
            act = menu.addAction(icon)
            act.triggered.connect(
                lambda _=False, i=index, ic=icon:
                self.controller.set_mode_icon(i, ic)
            )
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _dialog_rename_mode(self, index: int):
        """Tiny modal rename prompt. Modes are renamed rarely; a dialog
        beats rebuilding the row around an inline editor."""
        infos = self.controller.get_modes_info()
        current = ""
        if 0 <= index < len(infos):
            current = str(infos[index].get("name", ""))
        new_name, ok = QInputDialog.getText(
            self.window, "Rename Mode",
            f"New name for '{current}':",
            text=current,
        )
        if ok:
            new_name = (new_name or "").strip()
            if new_name and new_name != current:
                self.controller.rename_mode(index, new_name)

    def _build_mode_grid(self) -> QWidget:
        """Compact 2-column × 3-row grid of mode buttons for the sidebar.
        The sidebar deliberately has no scroll area, so the grid must stay
        small: ~44px-tall buttons with 4px gaps inside the ~180px inner
        width. _refresh_mode_buttons restyles the buttons in place."""
        host = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        host.setLayout(grid)
        self.mode_grid_buttons = []
        ctl = self.controller
        infos = ctl.get_modes_info() if hasattr(ctl, "get_modes_info") else []
        for i in range(6):
            info = infos[i] if i < len(infos) else {}
            btn = QPushButton(
                f"{info.get('name', f'Mode {i}')}\n{info.get('icon', '')}"
            )
            btn.setProperty("role", "modeBtn")
            btn.setProperty("active", "true" if info.get("active") else "false")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(44)
            btn.clicked.connect(
                lambda _=False, i=i: self.controller.switch_mode(i)
            )
            grid.addWidget(btn, i // 2, i % 2)
            self.mode_grid_buttons.append(btn)
        return host

    # ----------------------------------------------------------
    # Simple Mode view
    # ----------------------------------------------------------

    def _build_simple_mode_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Simple Mode")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # ===== Getting-started checklist =====
        # Simple Mode is the de-facto onboarding flow, but its three cards
        # each only explain their own gap — a first-time user had to infer
        # the OSC -> zones -> toy dependency chain themselves. This card
        # ticks the chain off live and disappears once everything lines up.
        gs_card = _Card()
        gs_lay = _vbox(14, 6)
        gs_card.setLayout(gs_lay)
        gs_hdr = QLabel("Getting started")
        f = gs_hdr.font(); f.setBold(True); f.setPointSize(12)
        gs_hdr.setFont(f)
        gs_lay.addWidget(gs_hdr)
        gs_lay.addWidget(self._muted_label(
            "Three things have to line up before you feel anything — each "
            "row ticks green on its own as you get there."
        ))
        self._simple_mode_step_text = {
            "osc": "VRChat OSC connected — use the sidebar's "
                   "\"Connect to VRChat\" button (VRChat must be running "
                   "with OSC enabled)",
            "zones": "SPS zones detected — load an avatar with OGB / SPS "
                     "contacts",
            "toy": "A toy is connected — power it on; it's discovered "
                   "automatically",
        }
        self._simple_mode_steps: Dict[str, QLabel] = {}
        for key in ("osc", "zones", "toy"):
            row_lbl = QLabel("")
            row_lbl.setWordWrap(True)
            gs_lay.addWidget(row_lbl)
            self._simple_mode_steps[key] = row_lbl
        gs_lay.addWidget(self._muted_label(
            "Then press ▶ Test on a toy below — if you feel it, you're set."
        ))
        self._simple_mode_gs_card = gs_card
        parent_layout.addWidget(gs_card)

        # ===== Toggle card =====
        toggle_card = _Card()
        tlay = _vbox(14, 8)
        toggle_card.setLayout(tlay)

        self.simple_mode_toggle = ToggleSwitch("Enable Simple Mode")
        f = self.simple_mode_toggle.font(); f.setBold(True); f.setPointSize(13)
        self.simple_mode_toggle.setFont(f)
        self.simple_mode_toggle.setChecked(bool(self.controller.get_simple_mode()))
        self.simple_mode_toggle.toggled.connect(self._on_simple_mode_toggled)
        tlay.addWidget(self.simple_mode_toggle)

        tlay.addWidget(self._muted_label(
            "Routes every detected SPS source to every connected toy with no "
            "per-toy configuration. Per-motor Device Routing is bypassed "
            "while this is on; the active mode's master intensity still applies."
        ))

        self.simple_mode_status_label = QLabel("")
        self.simple_mode_status_label.setProperty("muted", "true")
        tlay.addWidget(self.simple_mode_status_label)

        # Phase 2 simplification: Simple Mode is pure depth (no speed
        # contribution). Users who want speed blending, curves, or per-toy
        # tuning use full Device Routing instead.

        hint = QLabel(
            "Tip: you can always come back to Simple Mode from Settings."
        )
        hint.setProperty("muted", "true")
        hint.setWordWrap(True)
        tlay.addWidget(hint)

        parent_layout.addWidget(toggle_card)

        # ===== Sources card =====
        src_card = _Card()
        slay = _vbox(14, 6)
        src_card.setLayout(slay)

        src_header = QLabel("SPS Sources")
        f = src_header.font(); f.setBold(True); f.setPointSize(12)
        src_header.setFont(f)
        slay.addWidget(src_header)
        slay.addWidget(self._muted_label("Detected from the active VRChat avatar."))

        sources_host = QWidget()
        self.simple_mode_sources_layout = _vbox(0, 3)
        sources_host.setLayout(self.simple_mode_sources_layout)
        slay.addWidget(sources_host)

        parent_layout.addWidget(src_card)

        # ===== Toys card =====
        toys_card = _Card()
        toylay = _vbox(14, 6)
        toys_card.setLayout(toylay)

        toys_header = QLabel("Connected Toys")
        f = toys_header.font(); f.setBold(True); f.setPointSize(12)
        toys_header.setFont(f)
        toylay.addWidget(toys_header)
        toylay.addWidget(self._muted_label("Battery and test pulse for every toy in range."))

        toys_host = QWidget()
        self.simple_mode_toys_layout = _vbox(0, 4)
        toys_host.setLayout(self.simple_mode_toys_layout)
        toylay.addWidget(toys_host)

        parent_layout.addWidget(toys_card)
        parent_layout.addStretch(1)

        # Initial paint.
        self.refresh_simple_mode_view(force=True)

    def _on_simple_mode_toggled(self, checked: bool):
        if hasattr(self.controller, "set_simple_mode"):
            self.controller.set_simple_mode(bool(checked))
        # Keep the two mirror checkboxes (Simple Mode panel + Settings) in
        # sync without re-firing the handler.
        for cb in (self.simple_mode_toggle, self.simple_mode_settings_toggle):
            if cb is not None and cb.isChecked() != bool(checked):
                cb.blockSignals(True)
                cb.setChecked(bool(checked))
                cb.blockSignals(False)
        self._apply_simple_mode_visibility()
        # Jump to a view that's actually visible in the new sidebar — the
        # Simple Mode entry disappears when the user turns it off, so we
        # land them on Dashboard rather than an orphaned page.
        if bool(checked):
            self.select_view("Simple Mode")
        else:
            self.select_view("Dashboard")
        self.refresh_simple_mode_view(force=True)

    # When Simple Mode is on, hide every advanced nav button — only
    # Simple Mode, Settings and Help remain. This is the "Just Works"
    # onboarding mode where the user shouldn't be surprised by SteamVR,
    # bHaptics, the OSC inspector, etc. before they've connected a toy.
    _SIMPLE_MODE_HIDDEN_VIEWS = (
        "Dashboard", "Device Routing", "SPS Sources", "SteamVR Device Comms",
        "bHaptics", "PiShock", "Coyote", "OWO", "Handy", "OSC Inspector",
        "OSC Diagnostics", "Overview", "System Log",
    )

    # Sidebar entries gated by Settings → Features. A view is hidden if any
    # of its required feature flags is off. "SteamVR Device Comms" is shown
    # when either haptics OR battery is enabled — both halves live in that
    # one view.
    _FEATURE_VIEW_REQUIREMENTS = {
        "bHaptics":              ("feature_bhaptics",),
        "PiShock":               ("feature_pishock",),
        "Coyote":                ("feature_coyote",),
        "OWO":                   ("feature_owo",),
        "Handy":                 ("feature_handy",),
        "OSC Inspector":         ("feature_osc_inspector",),
        "SteamVR Device Comms":  ("feature_steamvr_haptics", "feature_steamvr_battery"),
        # Device Routing is entirely about Intiface toy motor mapping, so hide
        # it when the user has turned Intiface off.
        "Device Routing":        ("feature_intiface",),
    }

    def _feature_allows_view(self, view_name: str) -> bool:
        reqs = self._FEATURE_VIEW_REQUIREMENTS.get(view_name)
        if not reqs:
            return True
        get = getattr(self.controller, "get_feature_enabled", None)
        if get is None:
            return True
        # SteamVR view needs either half on; other views need their single flag.
        if view_name == "SteamVR Device Comms":
            return any(bool(get(k)) for k in reqs)
        return all(bool(get(k)) for k in reqs)

    def apply_feature_visibility(self):
        """Re-evaluate sidebar visibility after a feature toggle changes."""
        # Hide the Intiface connect block when that feature is off.
        if self.intiface_sidebar_section is not None:
            get = getattr(self.controller, "get_feature_enabled", None)
            on = bool(get("feature_intiface")) if get else True
            self.intiface_sidebar_section.setVisible(on)
        self._apply_simple_mode_visibility()

    def _apply_simple_mode_visibility(self):
        on = bool(getattr(self.controller, "get_simple_mode", lambda: False)())
        for name, btn in self.nav_buttons.items():
            if name == "Simple Mode":
                # Only present in the sidebar while Simple Mode is on.
                # When off, the user re-enables it from Settings.
                btn.setVisible(on)
                continue
            # Feature-gated views disappear entirely when their toggle is off,
            # regardless of Simple Mode state.
            if not self._feature_allows_view(name):
                btn.setVisible(False)
                continue
            if name in self._SIMPLE_MODE_HIDDEN_VIEWS:
                btn.setVisible(not on)
            else:
                btn.setVisible(True)
        # If the currently-shown view just got hidden, fall back to Dashboard
        # (or Simple Mode when that's the only visible option).
        current = self.main_stack.currentWidget() if self.main_stack else None
        if current is not None:
            for name, page in self.views.items():
                if page is current and not self.nav_buttons.get(name, None) is None:
                    btn = self.nav_buttons.get(name)
                    if btn is not None and not btn.isVisible():
                        fallback = "Simple Mode" if on else "Dashboard"
                        self.select_view(fallback)
                    break

    def _make_battery_label(self, level: Optional[float]) -> QLabel:
        lbl = QLabel("")
        lbl.setMinimumWidth(60)
        self._apply_battery_text(lbl, level)
        return lbl

    def _apply_battery_text(self, lbl: QLabel, level: Optional[float]):
        if level is None:
            lbl.setText("🔋 --")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return
        try:
            pct = int(float(level) * 100)
        except (TypeError, ValueError):
            lbl.setText("🔋 --")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return
        if pct > 50:
            color = COLOR_SUCCESS
        elif pct > 20:
            color = COLOR_ALERT
        else:
            color = "#FF4444"
        lbl.setText(f"🔋 {pct}%")
        lbl.setStyleSheet(f"color: {color};")

    def _refresh_simple_mode_checklist(self, sources, toys) -> None:
        """Tick the getting-started rows off live; hide the card once the
        whole OSC -> zones -> toy chain is green. ``sources``/``toys`` are
        passed in by refresh_simple_mode_view so the parameter-store copy
        behind them happens once per tick, not twice. Change-gated — this
        rides the periodic UI tick, so identical states must cost nothing."""
        card = getattr(self, "_simple_mode_gs_card", None)
        steps = getattr(self, "_simple_mode_steps", None)
        if card is None or not steps:
            return
        try:
            osc_ok = bool((self.controller.get_osc_status_snapshot() or {})
                          .get("connected"))
        except Exception:
            osc_ok = False
        src = sources or {}
        zones_ok = bool(src.get("Orifices") or src.get("Penetrators")
                        or src.get("Touch"))
        toy_ok = bool(toys)
        state = {"osc": osc_ok, "zones": zones_ok, "toy": toy_ok}
        if state == getattr(self, "_simple_mode_gs_state", None):
            return
        self._simple_mode_gs_state = state
        for key, lbl in steps.items():
            ok = state[key]
            try:
                lbl.setText(("✓  " if ok else "○  ")
                            + self._simple_mode_step_text[key])
                lbl.setStyleSheet(f"color: {COLOR_SUCCESS};" if ok
                                  else f"color: {COLOR_TEXT_MUTED};")
            except RuntimeError:
                return
        card.setVisible(not all(state.values()))

    def refresh_simple_mode_view(self, force: bool = False):
        """Rebuild source + toy lists when the underlying data has changed.
        Called from the periodic UI tick and after key controller events."""
        if self.simple_mode_sources_layout is None or self.simple_mode_toys_layout is None:
            return
        ctl = self.controller

        # Fetched once and shared with the checklist below — the sources
        # getter copies the whole parameter store under the lock the OSC
        # ingest thread contends on, so it must not run twice per tick.
        sources = ctl.get_simple_mode_sources() if hasattr(ctl, "get_simple_mode_sources") else {}
        toys = ctl.get_simple_mode_toys() if hasattr(ctl, "get_simple_mode_toys") else []

        self._refresh_simple_mode_checklist(sources, toys)

        # Keep both mirror toggles in sync with the persisted flag.
        desired = bool(getattr(ctl, "get_simple_mode", lambda: False)())
        for cb in (self.simple_mode_toggle, self.simple_mode_settings_toggle):
            if cb is not None and cb.isChecked() != desired:
                cb.blockSignals(True)
                cb.setChecked(desired)
                cb.blockSignals(False)

        # ---- Status line ----
        if self.simple_mode_status_label is not None:
            if ctl.get_simple_mode():
                self.simple_mode_status_label.setText(
                    "Simple Mode is ON — per-motor Device Routing is bypassed "
                    "(the mode's master intensity still applies)."
                )
                self.simple_mode_status_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
            else:
                self.simple_mode_status_label.setText(
                    "Simple Mode is OFF — normal per-motor Device Routing is active."
                )
                self.simple_mode_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

        # ---- Sources ----
        orifices = tuple(sources.get("Orifices", []))
        penetrators = tuple(sources.get("Penetrators", []))
        touch = tuple(sources.get("Touch", []))
        sources_key = (orifices, penetrators, touch)
        if force or sources_key != self._simple_mode_last_sources:
            self._simple_mode_last_sources = sources_key
            _clear_layout(self.simple_mode_sources_layout)
            if not orifices and not penetrators and not touch:
                lbl = QLabel("No SPS sources detected. Load an avatar with OGB zones.")
                lbl.setProperty("muted", "true")
                self._repolish(lbl)
                self.simple_mode_sources_layout.addWidget(lbl)
            else:
                for heading, names in (("Orifices", orifices),
                                       ("Penetrators", penetrators),
                                       ("Touch zones", touch)):
                    if not names:
                        continue
                    h = QLabel(heading)
                    fh = h.font(); fh.setBold(True); h.setFont(fh)
                    self.simple_mode_sources_layout.addWidget(h)
                    for name in names:
                        self.simple_mode_sources_layout.addWidget(QLabel(f"  • {name}"))

        # ---- Toys ----
        toys_key = tuple((t["name"], t.get("motor_count", 0), t.get("connected", False)) for t in toys)
        if force or toys_key != self._simple_mode_last_toys:
            self._simple_mode_last_toys = toys_key
            _clear_layout(self.simple_mode_toys_layout)
            self.simple_mode_battery_labels.clear()
            if not toys:
                lbl = QLabel("No connected toys. Open Intiface and connect a device.")
                lbl.setProperty("muted", "true")
                self._repolish(lbl)
                self.simple_mode_toys_layout.addWidget(lbl)
            else:
                for toy in toys:
                    row = QFrame()
                    row.setObjectName("chip")
                    row_lay = _hbox(8, 8)
                    row.setLayout(row_lay)

                    name_lbl = QLabel(f"✓ {toy['name']}")
                    name_lbl.setProperty("role", "success")
                    self._repolish(name_lbl)
                    row_lay.addWidget(name_lbl, 1)

                    batt = self._make_battery_label(toy.get("battery"))
                    row_lay.addWidget(batt)
                    self.simple_mode_battery_labels[toy["name"]] = batt

                    test_btn = QPushButton("Test")
                    test_btn.setFixedHeight(BTN_HEIGHT_SMALL)
                    test_btn.setProperty("role", "secondary")
                    test_btn.clicked.connect(
                        lambda _=False, n=toy["name"]: self.controller.test_toy(n)
                    )
                    row_lay.addWidget(test_btn)

                    self.simple_mode_toys_layout.addWidget(row)
        else:
            # Refresh battery text on existing labels even if the toy list itself
            # is unchanged — battery_update messages may have moved values.
            for toy in toys:
                lbl = self.simple_mode_battery_labels.get(toy["name"])
                if lbl is not None:
                    self._apply_battery_text(lbl, toy.get("battery"))

    def update_simple_mode_battery(self, device_name: str, level: float):
        """Live battery push from the controller. No-op if the label hasn't
        been built yet (the next refresh tick will pick up the value from
        the controller's cache)."""
        lbl = self.simple_mode_battery_labels.get(device_name)
        if lbl is not None:
            self._apply_battery_text(lbl, level)

    # ----------------------------------------------------------
    # Device Routing view
    # ----------------------------------------------------------

    def _build_device_routing_view(self, parent_layout: QVBoxLayout):
        # Title row: centered title + Help Mode toggle on the right.
        title_row = QWidget()
        title_lay = _hbox(0, 8)
        title_row.setLayout(title_lay)
        title_lay.addStretch(1)
        title = QLabel("Device Routing")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        title_lay.addWidget(title)
        title_lay.addStretch(1)

        help_toggle = ToggleSwitch("Help Mode")
        self._register_help_mode_toggle(help_toggle)
        title_lay.addWidget(help_toggle)
        parent_layout.addWidget(title_row)

        # ---- Anti-stuck card (two-timer model; parity with SteamVR/bHaptics) ----
        # Safety cutoff for frozen SPS inputs on the toy path. VRChat only
        # sends OSC on parameter change, so a stuck proximity (avatar swap,
        # partner leaves) would otherwise drive a toy at its last value
        # forever. Global to Device Routing; persisted in app settings and
        # read fresh by the routing tick (controller._get_toy_antistuck).
        as_card = _Card()
        aslay = _vbox(14, 8)
        as_card.setLayout(aslay)
        as_hdr = QLabel("Anti-stuck")
        as_hdr.setObjectName("sectionTitle")
        aslay.addWidget(as_hdr)
        aslay.addWidget(self._muted_label(
            "VRChat only sends OSC on parameter change. If an SPS input stops "
            "updating (avatar swap, partner leaves, OSC routing loss), the last "
            "value would drive the toy forever. The active timeout cuts "
            "mid-range stuck values; the peaked timeout gives saturated (100%) "
            "values a longer fuse — they often mean a legitimate hold — then "
            "ramps them down."
        ))
        as_row = _hbox(0, 8)
        self.toy_antistuck_check = ToggleSwitch("Enabled")
        self.toy_antistuck_check.setChecked(
            bool(self.controller.get_app_setting("toy_antistuck_enabled", True))
        )
        as_row.addWidget(self.toy_antistuck_check)
        as_row.addSpacing(12)

        as_row.addWidget(QLabel("Active timeout (s)"))
        self.toy_antistuck_active_spin = QSpinBox()
        self.toy_antistuck_active_spin.setRange(1, 600)
        self.toy_antistuck_active_spin.setValue(
            int(self.controller.get_app_setting("toy_antistuck_active_s", 7))
        )
        as_row.addWidget(self.toy_antistuck_active_spin)

        as_row.addWidget(QLabel("Peaked timeout (s)"))
        self.toy_antistuck_peaked_spin = QSpinBox()
        self.toy_antistuck_peaked_spin.setRange(1, 600)
        self.toy_antistuck_peaked_spin.setValue(
            int(self.controller.get_app_setting("toy_antistuck_peaked_s", 15))
        )
        as_row.addWidget(self.toy_antistuck_peaked_spin)
        as_row.addStretch(1)
        aslay.addLayout(as_row)

        # Connect AFTER seeding values so the initial setValue/setChecked
        # calls above don't echo straight back into app settings.
        self.toy_antistuck_check.toggled.connect(self._on_toy_antistuck_changed)
        self.toy_antistuck_active_spin.valueChanged.connect(self._on_toy_antistuck_changed)
        self.toy_antistuck_peaked_spin.valueChanged.connect(self._on_toy_antistuck_changed)
        parent_layout.addWidget(as_card)

        self.devices_container_frame = _Card(dark_bg=True)
        container_lay = _vbox(10, 6)
        self.devices_container_frame.setLayout(container_lay)
        parent_layout.addWidget(self.devices_container_frame, 1)

        toys_hdr_row = QWidget()
        thl = _hbox(0, 6)
        toys_hdr_row.setLayout(thl)
        thl.addStretch(1)
        header = QLabel("Toys")
        f = header.font(); f.setBold(True); f.setPointSize(12)
        header.setFont(f)
        header.setAlignment(Qt.AlignHCenter)
        thl.addWidget(header)
        thl.addWidget(self._make_help_badge(
            "Toy cards",
            "Every connected or remembered toy gets a card. Click the bar "
            "to expand its per-motor signal chains (Input → Depth/Speed → "
            "Combine → Gate → Smoothing → Zero cut → Output — click any "
            "stage to edit it). <b>Mute</b> silences the toy without touching its "
            "config; <b>Test</b> pulses the motors; the mini bars mirror "
            "each motor's live output."
        ))
        thl.addStretch(1)
        container_lay.addWidget(toys_hdr_row)

        # Scrollable list of device cards.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        self.unified_devices_layout = _vbox(4, 8)
        self.unified_devices_layout.addStretch(1)
        inner.setLayout(self.unified_devices_layout)
        scroll.setWidget(inner)
        self.unified_devices_frame = inner
        container_lay.addWidget(scroll, 1)

    def _on_toy_antistuck_changed(self, *_):
        """Persist the Device Routing anti-stuck settings. The live routing
        tick reads them fresh each evaluation via the controller's
        `_get_toy_antistuck`, so the change takes effect on the next tick with
        no explicit recalc kick."""
        self.controller.set_app_setting(
            "toy_antistuck_enabled", bool(self.toy_antistuck_check.isChecked()))
        self.controller.set_app_setting(
            "toy_antistuck_active_s", int(self.toy_antistuck_active_spin.value()))
        self.controller.set_app_setting(
            "toy_antistuck_peaked_s", int(self.toy_antistuck_peaked_spin.value()))
