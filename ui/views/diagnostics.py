"""Network debug, OSC diagnostics, system log, and OSC debugger UI.

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
)
from ui import lovense_icons as _lovense_icons

from constants import *
from parameter_store import store
from utilities import strip_param_prefix

from ui.geometry import parse_tk_geometry as _parse_tk_geometry
from ui.geometry import format_tk_geometry as _format_tk_geometry
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout as _clear_layout
from ui.text_helpers import truncate as _truncate
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


class _ReflowTable(QTableWidget):
    """QTableWidget that fires a callback whenever its geometry changes, so
    the OSC Inspector can re-pack its rows into more (or fewer) side-by-side
    Parameter/Value column-groups as the window is resized."""

    def __init__(self, *args, on_reflow: Optional[Callable[[], None]] = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._on_reflow = on_reflow

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._on_reflow is not None:
            self._on_reflow()


class DiagnosticsMixin:

    # ----------------------------------------------------------
    # OSC Inspector view
    # ----------------------------------------------------------

    def _build_network_debug_view(self, parent_layout: QVBoxLayout):
        title = QLabel("OSC Inspector")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # --- SPS Zones ---
        sps_card = _Card()
        sps_lay = _vbox(14, 6)
        sps_card.setLayout(sps_lay)

        sps_hdr_row = _hbox(0, 6)
        sps_header = QLabel("Active Avatar SPS Zones")
        sps_header.setObjectName("cardHeader")
        sps_hdr_row.addWidget(sps_header)
        sps_hdr_row.addWidget(self._make_help_badge(
            "SPS zones",
            "Orifices and penetrators auto-detected from the current "
            "avatar's OGB/SPS parameters. These are the zones the zone "
            "pickers across the app offer. Empty? The avatar isn't "
            "broadcasting SPS parameters, or VRChat OSC isn't connected."
        ))
        sps_hdr_row.addStretch(1)
        sps_lay.addLayout(sps_hdr_row)

        self.sps_status_label = QLabel("Waiting for VRChat...")
        self.sps_status_label.setWordWrap(True)
        sps_lay.addWidget(self.sps_status_label)
        parent_layout.addWidget(sps_card)

        # --- OSC Inspector ---
        dbg_title = QLabel("Real-Time OSC Inspector")
        dbg_title.setObjectName("sectionTitle")
        dbg_title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(dbg_title)

        # Container for the inspector
        inspector_card = _Card(dark_bg=True)
        inspector_lay = _vbox(10, 6)
        inspector_card.setLayout(inspector_lay)

        search_row = _hbox(0, 6)
        self.osc_search_entry = QLineEdit()
        self.osc_search_entry.setPlaceholderText(
            "Search parameters (e.g., Orifice, Touch, Float)..."
        )
        search_row.addWidget(self.osc_search_entry, 1)
        search_row.addWidget(self._make_help_badge(
            "OSC Inspector",
            "Every avatar parameter currently in the parameter store, "
            "updating live as VRChat sends OSC. Type to filter by "
            "substring. Great for finding the exact contact-receiver "
            "names to use in SPS Sources or custom address routing."
        ))
        inspector_lay.addLayout(search_row)

        # Rows are re-packed into 1-3 side-by-side Parameter/Value
        # column-groups depending on how much horizontal room the table
        # has, so a wide window doesn't leave the Value column stretched
        # across empty space. _ReflowTable calls back on resize.
        self.debugger_table = _ReflowTable(
            0, 2, on_reflow=self._reflow_debugger_table
        )
        self.debugger_table.verticalHeader().setVisible(False)
        self.debugger_table.verticalHeader().setDefaultSectionSize(18)
        self.debugger_table.setShowGrid(False)
        self.debugger_table.setAlternatingRowColors(True)
        self.debugger_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.debugger_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.debugger_table.setFocusPolicy(Qt.NoFocus)
        self.debugger_table.horizontalHeader().setCursor(Qt.SplitHCursor)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.debugger_table.setFont(font)

        # Live data + current group count, used by the resize/render path.
        self._debugger_rows: List[tuple] = []
        self._debugger_groups = 0
        self._apply_debugger_columns(1)

        inspector_lay.addWidget(self.debugger_table, 1)

        parent_layout.addWidget(inspector_card, 1)

    # ----------------------------------------------------------
    # OSC Diagnostics view
    #
    # One-stop debug page for the "VRChat says connected but no
    # parameters arrive" failure mode. Shows live packet rate, all
    # port/socket bindings, every non-VRChat OSCQuery client we've seen
    # (the prime suspect when this happens), and a scrollable feed of
    # recent OSC events from the manager's ring buffer.
    # ----------------------------------------------------------

    def _build_osc_diagnostics_view(self, parent_layout: QVBoxLayout):
        title = QLabel("OSC Diagnostics")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        intro = QLabel(
            "Live OSC connection diagnostics. If VRChat says we're connected "
            "but parameters are not updating, this page will tell you why. "
            "The most common cause is another OSC app (VRCOSC, OscGoesBrrr, "
            "etc.) that VRChat is routing to instead — those clients show up "
            "in the 'Other OSCQuery clients seen' card below."
        )
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        parent_layout.addWidget(intro)

        # --- Top row: live status + packet counters -------------------
        top_card = _Card()
        top_lay = _vbox(14, 8)
        top_card.setLayout(top_lay)

        header = QLabel("Live status")
        header.setObjectName("cardHeader")
        top_lay.addWidget(header)

        # Big status banner: green when packets are flowing, yellow when
        # connected but silent (the failure mode), red when disconnected.
        self.diag_status_banner = QLabel("—")
        font = self.diag_status_banner.font()
        font.setPointSize(16)
        font.setBold(True)
        self.diag_status_banner.setFont(font)
        self.diag_status_banner.setAlignment(Qt.AlignHCenter)
        top_lay.addWidget(self.diag_status_banner)

        # Grid of labelled counters. Stored on `self` so the refresh tick
        # can update each one in place without rebuilding the page.
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(6)

        def add_row(row: int, label_text: str, attr: str) -> None:
            lbl = QLabel(label_text)
            lbl.setProperty("muted", True)
            grid.addWidget(lbl, row, 0, Qt.AlignRight)
            value = QLabel("—")
            value_font = QFont("Consolas")
            value_font.setStyleHint(QFont.Monospace)
            value.setFont(value_font)
            grid.addWidget(value, row, 1, Qt.AlignLeft)
            setattr(self, attr, value)

        add_row(0, "Connection:", "diag_connection_lbl")
        add_row(1, "Session age:", "diag_session_age_lbl")
        add_row(2, "Packets handled:", "diag_packets_lbl")
        add_row(3, "Time since last packet:", "diag_last_pkt_lbl")
        add_row(4, "Phonebook GETs received:", "diag_phonebook_lbl")
        add_row(5, "Handler exceptions:", "diag_handler_exc_lbl")
        add_row(6, "Last handler error:", "diag_last_err_lbl")
        add_row(7, "mDNS service name:", "diag_mdns_name_lbl")
        add_row(8, "mDNS re-publishes:", "diag_mdns_rereg_lbl")
        add_row(9, "HTTP raw connections:", "diag_http_raw_lbl")
        top_lay.addLayout(grid)

        # Action buttons.
        btn_row = _hbox(0, 8)
        dump_btn = QPushButton("Dump diagnostics to log")
        dump_btn.setToolTip(
            "Write the full diagnostic dict to the System Log (sidebar) "
            "and the persistent file log."
        )
        dump_btn.clicked.connect(self.controller.log_osc_diagnostics)
        btn_row.addWidget(dump_btn)

        rehandshake_btn = QPushButton("Force re-handshake")
        rehandshake_btn.setProperty("role", "secondary")
        rehandshake_btn.setToolTip(
            "Re-poll VRChat's OSCQuery endpoint and resend our handshake "
            "ping. Try this FIRST when packets stop flowing."
        )
        rehandshake_btn.clicked.connect(self.controller.force_osc_rehandshake)
        btn_row.addWidget(rehandshake_btn)

        rereg_btn = QPushButton("Re-publish mDNS")
        rereg_btn.setProperty("role", "secondary")
        rereg_btn.setToolTip(
            "Unregister our mDNS advertisement and re-advertise under a fresh "
            "unique name. Forces VRChat to treat us as a brand-new OSC client. "
            "Try this if 'Force re-handshake' doesn't help."
        )
        rereg_btn.clicked.connect(self.controller.force_osc_reregister_mdns)
        btn_row.addWidget(rereg_btn)

        open_log_btn = QPushButton("Open log folder")
        open_log_btn.setProperty("role", "secondary")
        open_log_btn.setToolTip(
            "Open %APPDATA%/OscGoesPurrr in Explorer. The persistent OSC "
            "diagnostics log lives here as osc_diagnostics.log."
        )
        open_log_btn.clicked.connect(self.controller.open_osc_log_folder)
        btn_row.addWidget(open_log_btn)

        btn_row.addStretch(1)
        top_lay.addLayout(btn_row)

        parent_layout.addWidget(top_card)

        # --- Ports + socket binding ------------------------------------
        ports_card = _Card()
        ports_lay = _vbox(14, 6)
        ports_card.setLayout(ports_lay)
        ports_header = QLabel("Ports & sockets")
        ports_header.setObjectName("cardHeader")
        ports_lay.addWidget(ports_header)

        ports_grid = QGridLayout()
        ports_grid.setHorizontalSpacing(20)
        ports_grid.setVerticalSpacing(4)

        def add_port_row(row: int, label_text: str, attr: str) -> None:
            lbl = QLabel(label_text)
            lbl.setProperty("muted", True)
            ports_grid.addWidget(lbl, row, 0, Qt.AlignRight)
            value = QLabel("—")
            value_font = QFont("Consolas")
            value_font.setStyleHint(QFont.Monospace)
            value.setFont(value_font)
            ports_grid.addWidget(value, row, 1, Qt.AlignLeft)
            setattr(self, attr, value)

        add_port_row(0, "Our UDP listen port:", "diag_our_listen_lbl")
        add_port_row(1, "Our UDP socket bound to:", "diag_udp_bound_lbl")
        add_port_row(2, "Our HTTP phonebook port:", "diag_our_http_lbl")
        add_port_row(3, "VRChat OSC port:", "diag_vrc_osc_lbl")
        add_port_row(4, "VRChat OSCQuery HTTP port:", "diag_vrc_http_lbl")
        add_port_row(5, "VRChat IP:", "diag_vrc_ip_lbl")
        ports_lay.addLayout(ports_grid)

        parent_layout.addWidget(ports_card)

        # --- Other OSCQuery clients ------------------------------------
        clients_card = _Card()
        clients_lay = _vbox(14, 6)
        clients_card.setLayout(clients_lay)
        clients_header = QLabel("Other OSCQuery clients seen")
        clients_header.setObjectName("cardHeader")
        clients_lay.addWidget(clients_header)

        clients_note = QLabel(
            "Apps that advertised themselves on mDNS. VRChat may be sending "
            "your parameters to one of these instead of us. Close them and "
            "reconnect, or use VRChat → Settings → OSC → Reset."
        )
        clients_note.setWordWrap(True)
        clients_note.setProperty("muted", True)
        clients_lay.addWidget(clients_note)

        self.diag_clients_text = QPlainTextEdit()
        self.diag_clients_text.setReadOnly(True)
        clients_font = QFont("Consolas")
        clients_font.setStyleHint(QFont.Monospace)
        clients_font.setPointSize(10)
        self.diag_clients_text.setFont(clients_font)
        self.diag_clients_text.setMaximumHeight(140)
        self.diag_clients_text.setPlainText("(none seen yet)")
        clients_lay.addWidget(self.diag_clients_text)

        parent_layout.addWidget(clients_card)

        # --- Event log -------------------------------------------------
        events_card = _Card()
        events_lay = _vbox(14, 6)
        events_card.setLayout(events_lay)
        events_header = QLabel("Recent OSC events")
        events_header.setObjectName("cardHeader")
        events_lay.addWidget(events_header)

        events_note = QLabel(
            "Last 200 OSC manager events: mDNS state changes, handshake, "
            "health-check failures, silent-connection warnings."
        )
        events_note.setWordWrap(True)
        events_note.setProperty("muted", True)
        events_lay.addWidget(events_note)

        self.diag_events_text = QPlainTextEdit()
        self.diag_events_text.setReadOnly(True)
        events_font = QFont("Consolas")
        events_font.setStyleHint(QFont.Monospace)
        events_font.setPointSize(10)
        self.diag_events_text.setFont(events_font)
        events_lay.addWidget(self.diag_events_text, 1)

        parent_layout.addWidget(events_card, 1)

        # Track how many events we last rendered so the refresh tick
        # only redraws when new ones have arrived (cheap text equality
        # check would scan the whole buffer otherwise).
        self._diag_last_event_count = 0
        self._diag_last_clients_signature = None

    def refresh_osc_diagnostics_view(self) -> None:
        """Pulled by the main UI refresh tick. Idempotent — safe to call
        even when the panel hasn't been built yet (no-op if labels missing)."""
        if not getattr(self, "diag_status_banner", None):
            return

        # Only refresh the labels when the user is actually looking at
        # the page. Saves a controller call every 100 ms otherwise.
        current = self.main_stack.currentWidget() if self.main_stack else None
        if current is not self.views.get("OSC Diagnostics"):
            return

        diag = self.controller.get_osc_diagnostics() or {}
        if not diag:
            self.diag_status_banner.setText("OSC manager not running")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return

        is_conn = bool(diag.get("is_connected"))
        last_age = diag.get("last_packet_age_s")
        session_age = diag.get("session_age_s")
        pkts = int(diag.get("packets_handled", 0) or 0)
        phonebook = int(diag.get("phonebook_GETs", 0) or 0)
        handler_exc = int(diag.get("handler_exceptions", 0) or 0)

        # --- Banner ---------------------------------------------------
        if not is_conn:
            self.diag_status_banner.setText("✕  DISCONNECTED")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_ALERT};")
        elif last_age is None and pkts == 0:
            self.diag_status_banner.setText("⏳  CONNECTED — waiting for first packet…")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_TEXT};")
        elif last_age is not None and last_age > 15.0:
            self.diag_status_banner.setText(
                f"⚠  CONNECTED but SILENT for {last_age:.1f}s — VRChat is not sending us packets"
            )
            self.diag_status_banner.setStyleSheet("color: #FFB73D;")
        else:
            self.diag_status_banner.setText("✓  CONNECTED — packets flowing")
            self.diag_status_banner.setStyleSheet(f"color: {COLOR_SUCCESS};")

        # --- Live counters --------------------------------------------
        self.diag_connection_lbl.setText("connected" if is_conn else "disconnected")
        self.diag_session_age_lbl.setText(
            f"{session_age:.1f} s" if session_age is not None else "—"
        )
        self.diag_packets_lbl.setText(str(pkts))
        if last_age is None:
            self.diag_last_pkt_lbl.setText("never received any")
        else:
            self.diag_last_pkt_lbl.setText(f"{last_age:.1f} s")
        self.diag_phonebook_lbl.setText(str(phonebook))
        self.diag_handler_exc_lbl.setText(str(handler_exc))
        last_err = diag.get("last_handler_error") or "(none)"
        self.diag_last_err_lbl.setText(str(last_err))
        self.diag_mdns_name_lbl.setText(str(diag.get("mdns_service_name") or "—"))
        self.diag_mdns_rereg_lbl.setText(str(diag.get("mdns_rereg_count", 0)))
        self.diag_http_raw_lbl.setText(str(diag.get("http_raw_connections", 0)))

        # --- Ports ----------------------------------------------------
        self.diag_our_listen_lbl.setText(str(diag.get("our_listen_port") or "—"))
        bound = diag.get("udp_socket_bound")
        self.diag_udp_bound_lbl.setText(
            f"{bound[0]}:{bound[1]}" if bound else "—"
        )
        self.diag_our_http_lbl.setText(str(diag.get("our_http_phonebook_port") or "—"))
        self.diag_vrc_osc_lbl.setText(str(diag.get("vrc_osc_port") or "—"))
        self.diag_vrc_http_lbl.setText(str(diag.get("vrc_http_port") or "—"))
        self.diag_vrc_ip_lbl.setText(str(diag.get("vrc_ip") or "—"))

        # --- Other clients --------------------------------------------
        clients = self.controller.get_osc_other_clients() or {}
        signature = tuple(sorted(
            (k, v.get("present"), v.get("port")) for k, v in clients.items()
        ))
        if signature != self._diag_last_clients_signature:
            self._diag_last_clients_signature = signature
            if not clients:
                self.diag_clients_text.setPlainText("(none seen yet)")
            else:
                lines = []
                for name, info in clients.items():
                    state = "ACTIVE" if info.get("present") else "gone"
                    port = info.get("port")
                    lines.append(f"[{state:>6}]  {name}  port={port}")
                self.diag_clients_text.setPlainText("\n".join(lines))

        # --- Event log ------------------------------------------------
        events = self.controller.get_osc_event_log() or []
        if len(events) != self._diag_last_event_count:
            self._diag_last_event_count = len(events)
            self.diag_events_text.setPlainText("\n".join(events))
            # Keep the view scrolled to the bottom so the newest event is
            # always visible — like a live tail.
            scrollbar = self.diag_events_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    # ----------------------------------------------------------
    # System Log view
    # ----------------------------------------------------------

    def _build_system_log_view(self, parent_layout: QVBoxLayout):
        title = QLabel("System Log")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        font = QFont("Courier New")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(10)
        self.log_text.setFont(font)
        parent_layout.addWidget(self.log_text, 1)

    # ----------------------------------------------------------
    # OSC debugger display
    # ----------------------------------------------------------

    def update_osc_debugger_button(self, is_running: bool):
        if self.osc_debugger_button is None:
            return
        if is_running:
            self.osc_debugger_button.setText("Stop OSC Debugger")
            self.osc_debugger_button.setProperty("role", "danger")
        else:
            self.osc_debugger_button.setText("Start OSC Debugger")
            self.osc_debugger_button.setProperty("role", "")
        self._repolish(self.osc_debugger_button)

    def update_debugger_display(self, data):
        self._update_debugger_table(data)

    # --- multi-column layout helpers -------------------------------------
    #
    # The inspector packs its rows into one or more Parameter/Value
    # column-groups laid out side by side. Parameters fill row-major
    # (left-to-right, then wrap to the next row) so alphabetical order
    # still reads naturally and scrolls continuously.

    # A group needs ~280px for the parameter name plus room for the value;
    # below this we'd rather have fewer, wider groups than cramped ones.
    _DEBUGGER_GROUP_MIN_W = 440
    _DEBUGGER_MAX_GROUPS = 3

    def _compute_debugger_groups(self) -> int:
        """How many Parameter/Value column-groups fit at the current width.

        Uses the table's full width (not the viewport) so that the vertical
        scrollbar appearing/disappearing can't make the count oscillate."""
        tbl = self.debugger_table
        if tbl is None:
            return 1
        w = tbl.width()
        groups = max(1, w // self._DEBUGGER_GROUP_MIN_W)
        return min(int(groups), self._DEBUGGER_MAX_GROUPS)

    def _apply_debugger_columns(self, groups: int) -> None:
        """Configure the table for `groups` Parameter/Value pairs."""
        tbl = self.debugger_table
        if tbl is None:
            return
        tbl.setColumnCount(groups * 2)
        labels = []
        for _ in range(groups):
            labels.extend(["Parameter", "Value"])
        tbl.setHorizontalHeaderLabels(labels)
        hdr = tbl.horizontalHeader()
        for g in range(groups):
            pcol = g * 2
            vcol = pcol + 1
            hdr.setSectionResizeMode(pcol, QHeaderView.Interactive)
            hdr.setSectionResizeMode(vcol, QHeaderView.Stretch)
            tbl.setColumnWidth(pcol, 280)
        self._debugger_groups = groups

    def _reflow_debugger_table(self) -> None:
        """Resize callback — re-pack the rows if the column-group count
        changed. When it hasn't, the Stretch value columns resize on their
        own and there's nothing to do."""
        # resizeEvent can fire before the build method finishes wiring up
        # these attributes; bail out until they exist.
        if getattr(self, "debugger_table", None) is None:
            return
        if getattr(self, "_debugger_groups", None) is None:
            return
        if self._compute_debugger_groups() != self._debugger_groups:
            self._render_debugger_table()

    def _update_debugger_table(self, data):
        tbl = self.debugger_table
        if tbl is None:
            return

        if not isinstance(data, list):
            self._debugger_rows = []
            if self._debugger_groups != 1:
                self._apply_debugger_columns(1)
            tbl.setRowCount(1)
            placeholder = QTableWidgetItem(str(data))
            placeholder.setForeground(QColor(COLOR_TEXT_MUTED))
            tbl.setItem(0, 0, placeholder)
            for c in range(1, tbl.columnCount()):
                tbl.setItem(0, c, QTableWidgetItem(""))
            return

        rows = []
        for entry in data:
            if not isinstance(entry, tuple):
                continue
            if len(entry) == 3:
                addr, val_str, color = entry
            else:
                addr, color = entry
                val_str = ""
            # Address was padded with ljust+ " : " for the old text view; strip
            # that trailing decoration so the table column owns its own layout.
            addr_clean = addr.rstrip()
            if addr_clean.endswith(":"):
                addr_clean = addr_clean[:-1].rstrip()
            rows.append((addr_clean, val_str, color))

        self._debugger_rows = rows
        self._render_debugger_table()

    def _render_debugger_table(self):
        tbl = self.debugger_table
        if tbl is None:
            return

        rows = self._debugger_rows
        groups = self._compute_debugger_groups()
        if groups != self._debugger_groups:
            self._apply_debugger_columns(groups)

        n = len(rows)
        table_rows = (n + groups - 1) // groups if n else 0

        # Preserve the vertical scroll position across a re-pack.
        vbar = tbl.verticalScrollBar()
        scroll_val = vbar.value()

        tbl.setUpdatesEnabled(False)
        # In-place update: resize row count, then overwrite text on existing
        # cells. We never call clear()/setHtml(), so the horizontal scrollbar
        # range and value are preserved by Qt itself.
        if tbl.rowCount() != table_rows:
            tbl.setRowCount(table_rows)
        muted = QColor(COLOR_TEXT_MUTED)
        for r in range(table_rows):
            for g in range(groups):
                idx = r * groups + g  # row-major fill
                pcol = g * 2
                vcol = pcol + 1
                if idx < n:
                    addr, val_str, color = rows[idx]
                else:
                    addr, val_str, color = "", "", None

                addr_item = tbl.item(r, pcol)
                if addr_item is None:
                    addr_item = QTableWidgetItem()
                    addr_item.setForeground(muted)
                    tbl.setItem(r, pcol, addr_item)
                if addr_item.text() != addr:
                    addr_item.setText(addr)

                val_item = tbl.item(r, vcol)
                if val_item is None:
                    val_item = QTableWidgetItem()
                    tbl.setItem(r, vcol, val_item)
                if val_item.text() != val_str:
                    val_item.setText(val_str)
                if color is not None:
                    val_item.setForeground(QColor(color))
        tbl.setUpdatesEnabled(True)
        vbar.setValue(scroll_val)
