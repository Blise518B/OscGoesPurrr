"""Overview view — unified read-only card-grid for every connected
or stored thing across all haptic backends.

Sections (Cut 1 + Cut 2):
- Toys      — per Buttplug device tile (Cut 1)
- Trackers  — per SteamVR tracker tile (Cut 2)
- Suit      — per bHaptics position tile (Cut 2)
- System    — OSC link + active profile + backend health (Cut 2)

A chip-filter row at the top toggles section visibility; the chosen
set persists in app_settings['overview_visible_sections'].

Strictly read-only. Clicking a tile jumps to the appropriate editor
view (Device Routing / SteamVR Device Comms / bHaptics / OSC
Inspector / Dashboard / Settings). The tile itself
never mutates profile or engine state — read-only is load-bearing
for the Demeter rule.

Live updates:
- Toys: piggyback on DeviceFrameMixin's existing update paths via
  three hook methods (_overview_set_motor_value / _overview_set_battery
  / _overview_refresh_connection_states).
- Trackers / Suit / System: refreshed by a 2 Hz QTimer that
  re-queries the controller facade snapshots. Cheap (~ms per tick).

Cut 3 will add snap-grid resize (1x1 / 2x1 / 2x2) + per-tile size
persistence + QPropertyAnimation transitions + true FlowLayout."""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QLabel, QPushButton, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from constants import (
    BTN_HEIGHT_SMALL, COLOR_ALERT, COLOR_SUCCESS, COLOR_TEXT,
)

from ui import lovense_icons as _lovense_icons
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import RainbowMeter as _RainbowMeter, ProgressProxy as _ProgressProxy
from ui.icons import icon_no_battery as _icon_no_battery
from ui.flow_layout import FlowLayout as _FlowLayout


# Snap-grid tile sizes. 1x1 is sized for "essentials at a glance" —
# small enough that 30+ tiles fit in a 1080p window. 2x1 doubles
# width; 2x2 doubles both axes.
_CELL_W = 196
_CELL_H = 78
_CELL_GAP = 6

_TILE_SIZES: Dict[str, Tuple[int, int]] = {
    "1x1": (_CELL_W, _CELL_H),
    "2x1": (_CELL_W * 2 + _CELL_GAP, _CELL_H),
    "2x2": (_CELL_W * 2 + _CELL_GAP, _CELL_H * 2 + _CELL_GAP),
}
_TILE_SIZE_CYCLE = ("1x1", "2x1", "2x2")
_DEFAULT_TILE_SIZE = "1x1"

# Animation duration when cycling sizes — long enough to read as a
# transition, short enough not to feel sluggish.
_RESIZE_ANIM_MS = 150

# Sections in display order. Each tuple is (section_id, label,
# editor_view_name) — the editor view is the sidebar entry clicked
# tiles in this section jump to (Trackers click goes to SteamVR
# Device Comms etc.).
_SECTIONS: List[Tuple[str, str, str]] = [
    ("toys",     "Toys",     "Device Routing"),
    ("trackers", "Trackers", "SteamVR Device Comms"),
    ("suit",     "Suit",     "bHaptics"),
    ("system",   "System",   "Dashboard"),
]

# Default visible sections — all on. Persisted in app_settings under
# `overview_visible_sections` (a list of section_id strings).
_DEFAULT_VISIBLE_SECTIONS = [sid for sid, _, _ in _SECTIONS]

# Refresh cadence for the dynamic re-query path (trackers / suit /
# stats / system). 500ms = 2 Hz — perceptually live for status pills
# and stats, cheap enough that the cost is invisible.
_OVERVIEW_REFRESH_MS = 500


class OverviewMixin:

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_overview_view(self, parent_layout: QVBoxLayout):
        # Tile registries, keyed by section id.
        # Each section has: header (QLabel), container (QWidget),
        # grid (QGridLayout), tiles (dict from item-id -> tile-dict),
        # empty (QLabel | None for the placeholder shown when the
        # section has no items).
        self._overview_sections: Dict[str, Dict[str, Any]] = {}
        # Per-device per-motor cache for the Toys aggregate vibe meter.
        self._overview_motor_values: Dict[str, Dict[int, float]] = {}
        # Back-compat alias used by Cut 1's update hooks. Always points
        # at the Toys section's tiles dict.
        self._overview_tiles: Dict[str, Dict[str, Any]] = {}

        # Tighten the page's own vertical rhythm so 30+ tiles can fit
        # in a 1080p window without scrolling.
        parent_layout.setSpacing(4)
        parent_layout.setContentsMargins(8, 4, 8, 4)

        title = QLabel("Overview")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        title.setToolTip(
            "Read-only at-a-glance view. Click a tile to jump to its "
            "editor view; click the ⤢ corner to resize."
        )
        parent_layout.addWidget(title)

        # Chip-filter row.
        visible = self._overview_load_visible_sections()
        chip_row = QWidget()
        chip_lay = _hbox(0, 6)
        chip_row.setLayout(chip_lay)
        self._overview_chip_buttons: Dict[str, QPushButton] = {}
        for sid, label, _editor in _SECTIONS:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(sid in visible)
            btn.setFixedHeight(BTN_HEIGHT_SMALL)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(
                lambda _checked=False, s=sid: self._overview_toggle_section(s)
            )
            self._overview_apply_chip_style(btn)
            chip_lay.addWidget(btn)
            self._overview_chip_buttons[sid] = btn
        chip_lay.addStretch(1)
        parent_layout.addWidget(chip_row)

        # Build each section's container + grid + header.
        for sid, label, _editor in _SECTIONS:
            section_widget = QWidget()
            section_lay = _vbox(0, 2)
            section_widget.setLayout(section_lay)

            header = QLabel(label)
            hf = header.font(); hf.setBold(True)
            header.setFont(hf)
            section_lay.addWidget(header)

            grid_host = QWidget()
            grid = _FlowLayout(margin=0, spacing=_CELL_GAP)
            grid_host.setLayout(grid)
            section_lay.addWidget(grid_host)

            parent_layout.addWidget(section_widget)
            self._overview_sections[sid] = {
                "widget": section_widget,
                "header": header,
                "grid_host": grid_host,
                "grid": grid,
                "tiles": {},
                "empty": None,
            }

        parent_layout.addStretch(1)

        # Apply chip visibility now that sections exist.
        self._overview_apply_section_visibility(visible)

        # Build initial content.
        self.rebuild_overview()

        # Dynamic refresh timer for sections that don't have a push
        # channel (trackers / suit / stats / system).
        if getattr(self, "_overview_refresh_timer", None) is None:
            t = QTimer(self.window)
            t.setInterval(_OVERVIEW_REFRESH_MS)
            t.timeout.connect(self._refresh_overview_dynamic)
            t.start()
            self._overview_refresh_timer = t

    # ----------------------------------------------------------
    # Top-level (re)build + dynamic refresh
    # ----------------------------------------------------------

    def rebuild_overview(self) -> None:
        """Rebuild every section from the current controller state.
        Called on view build, profile switch, and device-list changes."""
        self._build_toys_section()
        self._build_trackers_section()
        self._build_suit_section()
        self._build_system_section()

    def _refresh_overview_dynamic(self) -> None:
        """Re-query the controller facades and push fresh values into
        the dynamic sections (trackers / suit / stats / system). Toys
        get live updates via push hooks so we don't re-query them."""
        if not getattr(self, "_overview_sections", None):
            return
        try:
            self._refresh_trackers_values()
        except Exception:
            pass
        try:
            self._refresh_suit_values()
        except Exception:
            pass
        try:
            self._refresh_system_values()
        except Exception:
            pass

    # ----------------------------------------------------------
    # Section visibility (chip filter row)
    # ----------------------------------------------------------

    def _overview_load_visible_sections(self) -> List[str]:
        raw = self.controller.get_app_setting(
            "overview_visible_sections", _DEFAULT_VISIBLE_SECTIONS
        )
        if not isinstance(raw, list) or not raw:
            return list(_DEFAULT_VISIBLE_SECTIONS)
        valid = {sid for sid, *_ in _SECTIONS}
        return [s for s in raw if s in valid] or list(_DEFAULT_VISIBLE_SECTIONS)

    def _overview_save_visible_sections(self, visible: List[str]) -> None:
        self.controller.set_app_setting("overview_visible_sections", list(visible))

    def _overview_toggle_section(self, section_id: str) -> None:
        visible = self._overview_load_visible_sections()
        if section_id in visible:
            visible.remove(section_id)
        else:
            visible.append(section_id)
        # Preserve canonical order.
        order = [sid for sid, *_ in _SECTIONS]
        visible.sort(key=lambda s: order.index(s))
        self._overview_save_visible_sections(visible)
        self._overview_apply_section_visibility(visible)

    def _overview_apply_section_visibility(self, visible: List[str]) -> None:
        for sid, refs in self._overview_sections.items():
            on = sid in visible
            refs["widget"].setVisible(on)
            btn = self._overview_chip_buttons.get(sid)
            if btn is not None:
                btn.blockSignals(True)
                try:
                    btn.setChecked(on)
                    self._overview_apply_chip_style(btn)
                finally:
                    btn.blockSignals(False)

    def _overview_apply_chip_style(self, btn: QPushButton) -> None:
        """Style chips like the segmented controls used elsewhere
        (segActive / segIdle role properties picked up by GLOBAL_QSS)."""
        btn.setProperty(
            "role", "segActive" if btn.isChecked() else "segIdle"
        )
        self._repolish(btn)

    # ----------------------------------------------------------
    # Toys section
    # ----------------------------------------------------------

    def _build_toys_section(self) -> None:
        refs = self._overview_sections.get("toys")
        if refs is None:
            return
        self._overview_clear_section(refs)
        self._overview_motor_values.clear()
        self._overview_tiles.clear()

        profile = self.controller.get_active_profile_dict() or {}
        connected = sorted(
            self.controller.get_connected_device_names(), key=str.lower
        )
        if not connected:
            self._overview_set_empty(
                refs,
                "No toys connected. Connect via Intiface Central — "
                "stored-but-offline toys live in Device Routing."
            )
            return

        for idx, name in enumerate(connected):
            # Connected toys may not yet be in the active profile (the
            # seed runs at profile creation, not at hot-plug), so fall
            # back to an empty config dict for the zones summary.
            cfg = profile.get(name, {}) or {}
            tile = self._build_overview_toy_tile(name, cfg, is_connected=True)
            self._overview_grid_add(refs, tile["frame"], idx)
            refs["tiles"][name] = tile
            self._overview_tiles[name] = tile

    def _build_overview_toy_tile(self, device_name: str, config: Dict[str, Any],
                                 is_connected: bool) -> Dict[str, Any]:
        frame = self._overview_make_tile(
            self._navigate_to("Device Routing"),
            section="toys", tile_id=device_name,
        )
        frame.setProperty("connected", "true" if is_connected else "false")
        lay = frame.layout()

        # Header row: icon + dot + name.
        head = QWidget()
        head_lay = _hbox(0, 6)
        head.setLayout(head_lay)

        icon_btn = QToolButton()
        icon_btn.setEnabled(False)
        icon_btn.setObjectName("lovenseIcon")
        icon_btn.setAutoRaise(True)
        icon_btn.setFixedSize(QSize(22, 22))
        icon_btn.setIconSize(QSize(18, 18))
        self._apply_lovense_icon(device_name, icon_btn)
        head_lay.addWidget(icon_btn)

        dot = QFrame()
        dot.setObjectName("connectDot")
        dot.setFixedSize(8, 8)
        self._apply_connect_dot(dot, is_connected)
        head_lay.addWidget(dot, 0, Qt.AlignVCenter)

        name_label = QLabel(self._overview_truncate(device_name, 22))
        name_label.setObjectName("overviewTileName")
        nf = name_label.font(); nf.setBold(True)
        name_label.setFont(nf)
        name_label.setToolTip(device_name)
        head_lay.addWidget(name_label, 1)
        lay.addWidget(head)

        # Battery + zones row.
        meta = QWidget()
        meta_lay = _hbox(0, 8)
        meta.setLayout(meta_lay)
        battery_label = QLabel("")
        battery_label.setMinimumWidth(56)
        self._show_no_battery_glyph(battery_label)
        meta_lay.addWidget(battery_label)
        zones_label = QLabel(self._overview_zones_summary(config))
        zones_label.setProperty("muted", "true")
        zones_label.setToolTip(zones_label.text())
        self._repolish(zones_label)
        meta_lay.addWidget(zones_label, 1)
        lay.addWidget(meta)

        # Aggregate vibe meter (max across motors).
        vibe = _RainbowMeter(maximum=1000)
        vibe.setFixedHeight(8)
        lay.addWidget(vibe)

        return {
            "frame": frame,
            "icon_btn": icon_btn,
            "dot": dot,
            "name_label": name_label,
            "battery_label": battery_label,
            "zones_label": zones_label,
            "vibe_meter": _ProgressProxy(vibe),
        }

    # ----- Toys update hooks (called from DeviceFrameMixin) -----

    def _overview_set_motor_value(self, device_name: str,
                                  motor_idx: int, value: float) -> None:
        if not getattr(self, "_overview_tiles", None):
            return
        tile = self._overview_tiles.get(device_name)
        if tile is None:
            return
        motors = self._overview_motor_values.setdefault(device_name, {})
        if motor_idx == -1:
            for k in list(motors.keys()):
                motors[k] = float(value)
        else:
            motors[int(motor_idx)] = float(value)
        agg = max(motors.values()) if motors else 0.0
        tile["vibe_meter"].set(agg)

    def _overview_set_battery(self, device_name: str, level: float) -> None:
        if not getattr(self, "_overview_tiles", None):
            return
        tile = self._overview_tiles.get(device_name)
        if tile is None:
            return
        self._overview_set_battery_label(tile["battery_label"], level)

    def _overview_refresh_connection_states(self) -> None:
        if not getattr(self, "_overview_sections", None):
            return
        connected = set(self.controller.get_connected_device_names())
        current_tiles = set(self._overview_tiles.keys()) if getattr(
            self, "_overview_tiles", None
        ) else set()
        # Show-only-active: when the connected set differs from the
        # tile set, rebuild the Toys section so newly-connected toys
        # get tiles and disconnected ones go away.
        if connected != current_tiles:
            self._build_toys_section()
            return
        # Otherwise just refresh per-tile visuals (dots stay green
        # because the set didn't change, but the call is cheap).
        for name, tile in self._overview_tiles.items():
            dot = tile.get("dot")
            if dot is not None:
                self._apply_connect_dot(dot, True)
            frame: QFrame = tile["frame"]
            frame.setProperty("connected", "true")
            self._repolish(frame)

    # ----------------------------------------------------------
    # Trackers section (SteamVR)
    # ----------------------------------------------------------

    def _build_trackers_section(self) -> None:
        refs = self._overview_sections.get("trackers")
        if refs is None:
            return
        self._overview_clear_section(refs)

        if not hasattr(self.controller, "get_steamvr_status"):
            self._overview_set_empty(refs, "SteamVR backend not loaded.")
            return
        status = self.controller.get_steamvr_status() or {}
        if not status.get("alive"):
            self._overview_set_empty(
                refs, "SteamVR runtime not running."
            )
            return
        trackers = list(status.get("trackers") or [])
        if not trackers:
            self._overview_set_empty(refs, "No SteamVR trackers detected.")
            return

        for idx, t in enumerate(trackers):
            tile = self._build_overview_tracker_tile(t)
            self._overview_grid_add(refs, tile["frame"], idx)
            refs["tiles"][t.get("serial", f"tracker_{idx}")] = tile

    def _build_overview_tracker_tile(self, tracker: Dict[str, Any]) -> Dict[str, Any]:
        tile_id = str(tracker.get("serial") or tracker.get("model") or "tracker")
        frame = self._overview_make_tile(
            self._navigate_to("SteamVR Device Comms"),
            section="trackers", tile_id=tile_id,
        )
        lay = frame.layout()

        head = QWidget()
        head_lay = _hbox(0, 6)
        head.setLayout(head_lay)
        title = QLabel(self._overview_truncate(
            str(tracker.get("model") or tracker.get("serial") or "Tracker"), 22
        ))
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        title.setToolTip(str(tracker.get("serial", "")))
        head_lay.addWidget(title, 1)
        lay.addWidget(head)

        sub = QLabel(str(tracker.get("device_class") or "—"))
        sub.setProperty("muted", "true")
        self._repolish(sub)
        lay.addWidget(sub)

        meta = QWidget()
        meta_lay = _hbox(0, 8)
        meta.setLayout(meta_lay)
        battery_label = QLabel("")
        battery_label.setMinimumWidth(56)
        lvl = tracker.get("battery")
        if lvl is None:
            self._show_no_battery_glyph(battery_label)
        else:
            self._overview_set_battery_label(battery_label, float(lvl))
        meta_lay.addWidget(battery_label)
        haptic_pill = QLabel("Haptics" if tracker.get("supports_haptics") else "no haptics")
        haptic_pill.setProperty("muted",
                                "false" if tracker.get("supports_haptics") else "true")
        self._repolish(haptic_pill)
        meta_lay.addWidget(haptic_pill, 1)
        lay.addWidget(meta)

        lay.addStretch(1)
        return {
            "frame": frame,
            "battery_label": battery_label,
            "haptic_pill": haptic_pill,
            "title": title,
            "sub": sub,
        }

    def _refresh_trackers_values(self) -> None:
        refs = self._overview_sections.get("trackers")
        if refs is None or not refs["tiles"]:
            return
        if not hasattr(self.controller, "get_steamvr_status"):
            return
        status = self.controller.get_steamvr_status() or {}
        if not status.get("alive"):
            # Runtime dropped — rebuild the whole section so the
            # "not running" placeholder shows.
            self._build_trackers_section()
            return
        trackers_by_serial = {
            str(t.get("serial")): t for t in (status.get("trackers") or [])
        }
        if set(trackers_by_serial.keys()) != set(refs["tiles"].keys()):
            # Tracker set changed — rebuild.
            self._build_trackers_section()
            return
        for serial, tile in refs["tiles"].items():
            t = trackers_by_serial.get(serial)
            if t is None:
                continue
            lvl = t.get("battery")
            bl = tile.get("battery_label")
            if bl is not None:
                if lvl is None:
                    self._show_no_battery_glyph(bl)
                else:
                    self._overview_set_battery_label(bl, float(lvl))

    # ----------------------------------------------------------
    # Suit section (bHaptics positions)
    # ----------------------------------------------------------

    def _build_suit_section(self) -> None:
        refs = self._overview_sections.get("suit")
        if refs is None:
            return
        self._overview_clear_section(refs)
        if not hasattr(self.controller, "get_bhaptics_status"):
            self._overview_set_empty(refs, "bHaptics backend not loaded.")
            return
        status = self.controller.get_bhaptics_status() or {}
        if not status.get("available"):
            self._overview_set_empty(
                refs,
                "bHaptics Player not available. Enable it in Settings."
            )
            return
        connected_overall = bool(status.get("connected"))
        # Only show positions that VRChat has actually fired at least
        # once this session — the rest are configured-but-quiet and
        # belong in the bHaptics editor view, not the at-a-glance tile.
        devices = [d for d in (status.get("devices") or []) if d.get("detected")]
        if not devices:
            self._overview_set_empty(
                refs,
                "No bHaptics positions live. Stored positions live in "
                "the bHaptics editor view."
            )
            return
        for idx, dev in enumerate(devices):
            tile = self._build_overview_suit_tile(dev, connected_overall)
            self._overview_grid_add(refs, tile["frame"], idx)
            refs["tiles"][str(dev.get("position", f"pos_{idx}"))] = tile

    def _build_overview_suit_tile(self, dev: Dict[str, Any],
                                  connected_overall: bool) -> Dict[str, Any]:
        tile_id = str(dev.get("position") or "position")
        frame = self._overview_make_tile(
            self._navigate_to("bHaptics"),
            section="suit", tile_id=tile_id,
        )
        lay = frame.layout()

        head = QWidget()
        head_lay = _hbox(0, 6)
        head.setLayout(head_lay)
        dot = QFrame()
        dot.setObjectName("connectDot")
        dot.setFixedSize(8, 8)
        # A position is "live" only when the Player overall is
        # connected AND the position has been detected by an OSC
        # message in the current session.
        live = connected_overall and bool(dev.get("detected"))
        self._apply_connect_dot(dot, live)
        head_lay.addWidget(dot, 0, Qt.AlignVCenter)

        title = QLabel(self._overview_truncate(
            str(dev.get("display_name") or dev.get("position") or "Position"), 22
        ))
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        head_lay.addWidget(title, 1)
        lay.addWidget(head)

        node_count = int(dev.get("node_count", 0))
        grid = dev.get("grid") or (0, 0)
        try:
            cols, rows = int(grid[0]), int(grid[1])
        except (TypeError, ValueError, IndexError):
            cols, rows = 0, 0
        info = QLabel(f"{node_count} dots · {cols}×{rows}")
        info.setProperty("muted", "true")
        self._repolish(info)
        lay.addWidget(info)

        lay.addStretch(1)
        return {"frame": frame, "dot": dot, "title": title, "info": info}

    def _refresh_suit_values(self) -> None:
        refs = self._overview_sections.get("suit")
        if refs is None:
            return
        if not hasattr(self.controller, "get_bhaptics_status"):
            return
        status = self.controller.get_bhaptics_status() or {}
        if not status.get("available"):
            self._build_suit_section()
            return
        connected_overall = bool(status.get("connected"))
        # Show-only-active: rebuild the section if the detected set
        # changed since last refresh.
        detected_now = {
            str(d.get("position"))
            for d in (status.get("devices") or [])
            if d.get("detected")
        }
        if detected_now != set(refs["tiles"].keys()):
            self._build_suit_section()
            return
        for dev in (status.get("devices") or []):
            pos = str(dev.get("position", ""))
            tile = refs["tiles"].get(pos)
            if tile is None:
                continue
            live = connected_overall and bool(dev.get("detected"))
            dot = tile.get("dot")
            if dot is not None:
                self._apply_connect_dot(dot, live)

    # ----------------------------------------------------------
    # System section (OSC + profile + backend health)
    # ----------------------------------------------------------

    def _build_system_section(self) -> None:
        refs = self._overview_sections.get("system")
        if refs is None:
            return
        self._overview_clear_section(refs)

        idx = 0
        if hasattr(self.controller, "get_osc_status_snapshot"):
            tile = self._build_overview_osc_tile()
            self._overview_grid_add(refs, tile["frame"], idx)
            refs["tiles"]["osc"] = tile
            idx += 1
        if hasattr(self.controller, "get_active_profile_info"):
            tile = self._build_overview_profile_tile()
            self._overview_grid_add(refs, tile["frame"], idx)
            refs["tiles"]["profile"] = tile
            idx += 1
        # Backend-health tile aggregates Intiface / bHaptics / SteamVR
        # into one tile so the user gets a single "is anything broken
        # right now?" glance card.
        tile = self._build_overview_backends_tile()
        self._overview_grid_add(refs, tile["frame"], idx)
        refs["tiles"]["backends"] = tile

    def _build_overview_osc_tile(self) -> Dict[str, Any]:
        frame = self._overview_make_tile(
            self._navigate_to("OSC Inspector"),
            section="system", tile_id="osc",
        )
        lay = frame.layout()
        head = QWidget()
        head_lay = _hbox(0, 6)
        head.setLayout(head_lay)
        dot = QFrame()
        dot.setObjectName("connectDot")
        dot.setFixedSize(10, 10)
        head_lay.addWidget(dot, 0, Qt.AlignVCenter)
        title = QLabel("VRChat OSC")
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        head_lay.addWidget(title, 1)
        lay.addWidget(head)
        port_label = QLabel("Port: —")
        port_label.setProperty("muted", "true")
        self._repolish(port_label)
        lay.addWidget(port_label)
        packets_label = QLabel("Packets: 0")
        packets_label.setProperty("muted", "true")
        self._repolish(packets_label)
        lay.addWidget(packets_label)
        lay.addStretch(1)
        tile = {
            "frame": frame, "dot": dot,
            "port_label": port_label, "packets_label": packets_label,
            "_last_packets": 0,
        }
        self._refresh_osc_tile(tile)
        return tile

    def _refresh_osc_tile(self, tile: Dict[str, Any]) -> None:
        snap = self.controller.get_osc_status_snapshot() or {}
        is_conn = bool(snap.get("connected"))
        self._apply_connect_dot(tile["dot"], is_conn)
        port = snap.get("port")
        tile["port_label"].setText(f"Port: {port if port else '—'}")
        packets = int(snap.get("packets", 0))
        tile["packets_label"].setText(f"Packets: {packets:,}")
        tile["_last_packets"] = packets

    def _build_overview_profile_tile(self) -> Dict[str, Any]:
        frame = self._overview_make_tile(
            self._navigate_to("Dashboard"),
            section="system", tile_id="profile",
        )
        lay = frame.layout()
        title = QLabel("Active Profile")
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        lay.addWidget(title)
        name = QLabel("—")
        nf = name.font(); nf.setPointSize(max(nf.pointSize() + 2, 12))
        name.setFont(nf)
        lay.addWidget(name)
        sub = QLabel("")
        sub.setProperty("muted", "true")
        self._repolish(sub)
        lay.addWidget(sub)
        lay.addStretch(1)
        tile = {"frame": frame, "name": name, "sub": sub}
        self._refresh_profile_tile(tile)
        return tile

    def _refresh_profile_tile(self, tile: Dict[str, Any]) -> None:
        info = self.controller.get_active_profile_info() or {}
        name = str(info.get("name") or "—")
        kind = str(info.get("kind") or "")
        tile["name"].setText(self._overview_truncate(name, 22))
        tile["name"].setToolTip(name)
        if kind == "avatar":
            avid = ""
            try:
                avid = str(self.controller.get_current_avatar_id() or "")
            except Exception:
                pass
            tile["sub"].setText(
                f"Avatar profile — {self._overview_truncate(avid, 24) if avid else 'unbound'}"
            )
        else:
            tile["sub"].setText("Global profile")

    def _build_overview_backends_tile(self) -> Dict[str, Any]:
        frame = self._overview_make_tile(
            self._navigate_to("Settings"),
            section="system", tile_id="backends",
        )
        lay = frame.layout()
        title = QLabel("Backends")
        tf = title.font(); tf.setBold(True)
        title.setFont(tf)
        lay.addWidget(title)
        pills_row = QWidget()
        pills_lay = _hbox(0, 4)
        pills_row.setLayout(pills_lay)
        pills: Dict[str, QLabel] = {}
        for key, label in (("intiface", "Intiface"),
                           ("bhaptics", "bHaptics"),
                           ("steamvr",  "SteamVR")):
            pill = QLabel(label)
            pill.setProperty("role", "pill")
            pill.setProperty("tone", "warn")
            self._repolish(pill)
            pills_lay.addWidget(pill)
            pills[key] = pill
        pills_lay.addStretch(1)
        lay.addWidget(pills_row)
        lay.addStretch(1)
        tile = {"frame": frame, "pills": pills}
        self._refresh_backends_tile(tile)
        return tile

    def _refresh_backends_tile(self, tile: Dict[str, Any]) -> None:
        pills = tile.get("pills", {})
        # Intiface
        if "intiface" in pills:
            ok = bool((self.controller.get_intiface_status() or {}).get("connected"))
            self._overview_set_pill(pills["intiface"], ok)
        # bHaptics
        if "bhaptics" in pills:
            if hasattr(self.controller, "get_bhaptics_status"):
                ok = bool((self.controller.get_bhaptics_status() or {}).get("connected"))
            else:
                ok = False
            self._overview_set_pill(pills["bhaptics"], ok)
        # SteamVR
        if "steamvr" in pills:
            if hasattr(self.controller, "get_steamvr_status"):
                ok = bool((self.controller.get_steamvr_status() or {}).get("alive"))
            else:
                ok = False
            self._overview_set_pill(pills["steamvr"], ok)

    def _overview_set_pill(self, pill: QLabel, ok: bool) -> None:
        pill.setProperty("tone", "ok" if ok else "warn")
        self._repolish(pill)

    def _refresh_system_values(self) -> None:
        refs = self._overview_sections.get("system")
        if refs is None:
            return
        osc = refs["tiles"].get("osc")
        if osc is not None:
            self._refresh_osc_tile(osc)
        profile = refs["tiles"].get("profile")
        if profile is not None:
            self._refresh_profile_tile(profile)
        backends = refs["tiles"].get("backends")
        if backends is not None:
            self._refresh_backends_tile(backends)

    # ----------------------------------------------------------
    # Tile / section primitives
    # ----------------------------------------------------------

    def _overview_make_tile(self, on_click,
                            section: str, tile_id: str) -> QFrame:
        """Common tile shell. Sized via the persisted snap-grid size
        (1x1 / 2x1 / 2x2). Left-click on the body fires the navigate
        callback; click on the small ⤢ button in the top-right cycles
        through the size classes."""
        frame = QFrame()
        frame.setObjectName("overviewTile")
        frame.setCursor(Qt.PointingHandCursor)
        size_class = self._overview_get_tile_size(section, tile_id)
        w, h = _TILE_SIZES.get(size_class, _TILE_SIZES[_DEFAULT_TILE_SIZE])
        frame.setFixedSize(QSize(w, h))
        frame.setProperty("size_class", size_class)
        lay = _vbox(5, 2)
        frame.setLayout(lay)

        def on_press(ev):
            if ev.button() == Qt.LeftButton:
                try:
                    on_click()
                except Exception:
                    pass
                ev.accept()
            else:
                QFrame.mousePressEvent(frame, ev)
        frame.mousePressEvent = on_press

        # The expand button is created here so every tile (Toys,
        # Trackers, etc.) gets it without each builder needing to
        # remember. Sits in the top-right, sized small enough not to
        # crowd the tile content.
        expand_btn = QToolButton(frame)
        expand_btn.setObjectName("overviewExpand")
        expand_btn.setText("⤢")
        expand_btn.setCursor(Qt.PointingHandCursor)
        expand_btn.setToolTip("Resize tile  (1×1 → 2×1 → 2×2)")
        expand_btn.setFixedSize(14, 14)
        expand_btn.setAutoRaise(True)
        # Stop event propagation so clicking the button doesn't also
        # trigger the navigate-on-click body handler.
        expand_btn.clicked.connect(
            lambda _=False, s=section, t=tile_id: self._overview_cycle_tile_size(s, t)
        )
        # Position manually after the frame is given its size — Qt
        # widget children aren't laid out by the parent's QLayout
        # unless explicitly added, which is what we want here.
        expand_btn.move(w - expand_btn.width() - 4, 4)
        expand_btn.raise_()
        # Re-position the expand button whenever the frame resizes.
        # We attach a resize hook so animations keep the button in
        # the corner.
        def on_resize(ev, btn=expand_btn, f=frame):
            btn.move(f.width() - btn.width() - 4, 4)
            QFrame.resizeEvent(f, ev)
        frame.resizeEvent = on_resize

        return frame

    def _overview_grid_add(self, refs: Dict[str, Any], widget: QWidget,
                           _index: int = 0) -> None:
        # FlowLayout just appends — items are positioned by the layout
        # itself. The `_index` parameter is retained for call-site
        # compatibility but ignored.
        refs["grid"].addWidget(widget)

    # ----------------------------------------------------------
    # Snap-grid size persistence + resize
    # ----------------------------------------------------------

    def _overview_size_storage_key(self, section: str, tile_id: str) -> str:
        return f"{section}:{tile_id}"

    def _overview_get_tile_size(self, section: str, tile_id: str) -> str:
        sizes = self.controller.get_app_setting("dashboard_tile_sizes", {}) or {}
        if not isinstance(sizes, dict):
            return _DEFAULT_TILE_SIZE
        v = sizes.get(self._overview_size_storage_key(section, tile_id))
        if v in _TILE_SIZES:
            return v
        return _DEFAULT_TILE_SIZE

    def _overview_persist_tile_size(self, section: str, tile_id: str,
                                    size_class: str) -> None:
        sizes = self.controller.get_app_setting("dashboard_tile_sizes", {}) or {}
        if not isinstance(sizes, dict):
            sizes = {}
        sizes = dict(sizes)
        sizes[self._overview_size_storage_key(section, tile_id)] = size_class
        self.controller.set_app_setting("dashboard_tile_sizes", sizes)

    def _overview_cycle_tile_size(self, section: str, tile_id: str) -> None:
        """Called by the per-tile ⤢ button. Steps through the size
        cycle (1x1 → 2x1 → 2x2 → 1x1), persists the new size, and
        animates the tile to its new dimensions."""
        current = self._overview_get_tile_size(section, tile_id)
        try:
            idx = _TILE_SIZE_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_size = _TILE_SIZE_CYCLE[(idx + 1) % len(_TILE_SIZE_CYCLE)]
        self._overview_persist_tile_size(section, tile_id, next_size)
        # Find the tile frame and animate it.
        refs = self._overview_sections.get(section)
        if refs is None:
            return
        tile = refs["tiles"].get(tile_id)
        if tile is None:
            return
        frame: QFrame = tile.get("frame")
        if frame is None:
            return
        self._overview_animate_tile_to(frame, next_size)
        # FlowLayout reflows automatically when child sizeHints change,
        # but we nudge it so the new size takes effect immediately.
        host = refs.get("grid_host")
        if host is not None:
            host.updateGeometry()

    def _overview_animate_tile_to(self, frame: QFrame, size_class: str) -> None:
        """Animate the tile to the named size class. Uses a
        QPropertyAnimation on minimumSize + maximumSize together so
        the tile's fixed-size constraint stays consistent throughout
        the transition."""
        w, h = _TILE_SIZES.get(size_class, _TILE_SIZES[_DEFAULT_TILE_SIZE])
        target = QSize(w, h)
        frame.setProperty("size_class", size_class)

        anim_min = QPropertyAnimation(frame, b"minimumSize", frame)
        anim_min.setDuration(_RESIZE_ANIM_MS)
        anim_min.setEasingCurve(QEasingCurve.OutCubic)
        anim_min.setStartValue(frame.size())
        anim_min.setEndValue(target)

        anim_max = QPropertyAnimation(frame, b"maximumSize", frame)
        anim_max.setDuration(_RESIZE_ANIM_MS)
        anim_max.setEasingCurve(QEasingCurve.OutCubic)
        anim_max.setStartValue(frame.size())
        anim_max.setEndValue(target)

        anim_min.start(QPropertyAnimation.DeleteWhenStopped)
        anim_max.start(QPropertyAnimation.DeleteWhenStopped)

    def _overview_clear_section(self, refs: Dict[str, Any]) -> None:
        grid = refs["grid"]
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                # Hide before detaching: a still-visible child reparented to
                # None briefly realises as a top-level window (a flash).
                w.hide()
                w.setParent(None)
                w.deleteLater()
        refs["tiles"].clear()
        if refs.get("empty") is not None:
            refs["empty"].hide()
            refs["empty"].setParent(None)
            refs["empty"].deleteLater()
            refs["empty"] = None

    def _overview_set_empty(self, refs: Dict[str, Any], text: str) -> None:
        empty = QLabel(text)
        empty.setProperty("muted", "true")
        empty.setAlignment(Qt.AlignHCenter)
        empty.setWordWrap(True)
        self._repolish(empty)
        refs["grid"].addWidget(empty)
        refs["empty"] = empty

    def _overview_set_battery_label(self, label: QLabel, level: float) -> None:
        pct = int(level * 100)
        if pct > 50:
            color = COLOR_SUCCESS
        elif pct > 20:
            color = COLOR_ALERT
        else:
            color = "#FF4444"
        label.setText(f"🔋 {pct}%")
        label.setStyleSheet(f"color: {color};")

    def _navigate_to(self, view_name: str):
        """Return a zero-arg callable that selects `view_name`. Used as
        the click handler for tiles."""
        return lambda: self.select_view(view_name)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _overview_zones_summary(self, config: Dict[str, Any]) -> str:
        motor_count = int(config.get("motor_count", 1))
        if motor_count == 0:
            return "(no motors)"
        zones_strs: List[str] = []
        for i in range(motor_count):
            zs = str(config.get(f"motor_{i}_zones", "") or "").strip()
            zones_strs.append(zs)

        def _label(zs: str) -> str:
            if not zs:
                return "Custom OSC only"
            parts = [p.strip() for p in zs.split(",")
                     if p.strip() and p.strip() != "None"]
            if not parts:
                return "Custom OSC only"
            if "All SPS" in parts:
                return "All SPS"
            if len(parts) == 1:
                return parts[0]
            return f"{len(parts)} zones"

        if len(set(zones_strs)) == 1:
            return _label(zones_strs[0])
        return f"Motors differ ({motor_count})"

    @staticmethod
    def _overview_truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1] + "…"
