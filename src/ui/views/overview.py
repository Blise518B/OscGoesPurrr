"""Overview view — unified read-only card-grid for every connected
or stored toy.

Sections:
- Toys      — per Buttplug device tile
- System    — OSC link + active mode + backend health

A chip-filter row at the top toggles section visibility; the chosen
set persists in app_settings['overview_visible_sections'].

Strictly read-only. Clicking a tile jumps to the appropriate editor
view (Device Routing / OSC Inspector / Settings). The tile itself
never mutates mode or engine state — read-only is load-bearing
for the Demeter rule.

Live updates:
- Toys: piggyback on DeviceFrameMixin's existing update paths via
  three hook methods (_overview_set_motor_value / _overview_set_battery
  / _overview_refresh_connection_states).
- System: refreshed by a 2 Hz QTimer that
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
    COLOR_TEXT_MUTED, COLOR_WARNING,
)

from ui import lovense_icons as _lovense_icons
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import (
    Card as _Card, RainbowMeter as _RainbowMeter, ProgressProxy as _ProgressProxy,
)
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
# tiles in this section jump to.
_SECTIONS: List[Tuple[str, str, str]] = [
    ("toys",     "Toys",     "Device Routing"),
    ("system",   "System",   "Dashboard"),
]

# Default visible sections — all on. Persisted in app_settings under
# `overview_visible_sections` (a list of section_id strings).
_DEFAULT_VISIBLE_SECTIONS = [sid for sid, _, _ in _SECTIONS]

# Refresh cadence for the dynamic re-query path (stats / system). 500ms = 2 Hz — perceptually live for status pills
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
        parent_layout.addWidget(title)

        # ===== Getting started =====
        # The app's home page is also where a first-time user finds out
        # what still has to line up before a toy responds.
        self._build_setup_checklist(parent_layout)

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
        self._explain(chip_lay,
            "Overview",
            "Everything at a glance: one tile per connected toy with its "
            "live output and battery, plus the VRChat link and the active "
            "mode. Click a toy to open it in Device Routing. These buttons "
            "show or hide whole sections; the ⤢ corner of a tile "
            "resizes it."
        )
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
            if sid == "toys":
                head_row = QWidget()
                head_lay = _hbox(0, 10)
                head_row.setLayout(head_lay)
                head_lay.addWidget(header)
                test_all = QPushButton("Test all")
                test_all.setProperty("role", "secondary")
                test_all.setFixedHeight(BTN_HEIGHT_SMALL)
                test_all.setCursor(Qt.PointingHandCursor)
                test_all.clicked.connect(
                    lambda _=False: self.controller.trigger_purr_check())
                self._explain(
                    test_all, "Test all",
                    "Buzzes every connected toy gently for about a second, "
                    "so you can tell at once which ones are really "
                    "listening. Only vibrating motors take part \u2014 a "
                    "stroker won't suddenly move.")
                head_lay.addWidget(test_all)
                head_lay.addStretch(1)
                section_lay.addWidget(head_row)
            else:
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
        # channel (stats / system).
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
        Called on view build, mode switch, and device-list changes."""
        self._build_toys_section()
        self._build_system_section()

    def _refresh_overview_dynamic(self) -> None:
        """Re-query the controller facades and push fresh values into
        the dynamic sections (stats / system). Toys
        get live updates via push hooks so we don't re-query them.
        Skipped while the page is hidden (2 Hz of facade polling is
        pure cost elsewhere); select_view refreshes on arrival."""
        if not getattr(self, "_overview_sections", None):
            return
        view = self.views.get("Overview")
        if view is not None and not view.isVisible():
            return
        try:
            self._refresh_system_values()
        except Exception:
            pass
        try:
            self._refresh_setup_checklist()
        except Exception:
            pass

    # ----------------------------------------------------------
    # Getting-started checklist
    # ----------------------------------------------------------

    _SETUP_STEPS = (
        ("osc", "VRChat is sending data \u2014 VRChat must be running with "
                "OSC turned on (Action menu \u2192 Options \u2192 OSC). The "
                "sidebar's VRChat section connects on its own."),
        ("zones", "Your avatar has SPS contacts \u2014 load an avatar with "
                  "OGB / SPS sockets or plugs."),
        ("toy", "A toy is connected \u2014 switch it on; it's found "
                "automatically."),
    )

    def _build_setup_checklist(self, parent_layout: QVBoxLayout) -> None:
        """The three things that have to line up before you feel anything,
        ticked off live. The card hides itself once all three are green
        and comes back if one drops (VRChat closed, toy switched off)."""
        card = _Card()
        lay = _vbox(14, 6)
        card.setLayout(lay)
        hdr = QLabel("Getting started")
        hdr.setObjectName("sectionTitle")
        lay.addWidget(hdr)
        self._setup_step_labels: Dict[str, QLabel] = {}
        for key, _text in self._SETUP_STEPS:
            row = QLabel("")
            row.setWordWrap(True)
            lay.addWidget(row)
            self._setup_step_labels[key] = row
        lay.addWidget(self._muted_label(
            "Then press Test all below \u2014 if you feel it, you're set."))
        self._setup_card = card
        self._setup_state = None
        parent_layout.addWidget(card)
        self._refresh_setup_checklist()

    def _refresh_setup_checklist(self) -> None:
        """Change-gated: rides the Overview's 2 Hz refresh, so an unchanged
        state costs one facade call and a dict compare."""
        card = getattr(self, "_setup_card", None)
        if card is None:
            return
        try:
            state = dict(self.controller.get_setup_status())
        except Exception:
            return
        if state == self._setup_state:
            return
        self._setup_state = state
        for key, text in self._SETUP_STEPS:
            ok = bool(state.get(key))
            lbl = self._setup_step_labels[key]
            try:
                lbl.setText(("\u2713  " if ok else "\u25cb  ") + text)
                lbl.setStyleSheet(f"color: {COLOR_SUCCESS};" if ok
                                  else f"color: {COLOR_TEXT_MUTED};")
            except RuntimeError:
                return
        card.setVisible(not all(bool(state.get(k)) for k, _ in self._SETUP_STEPS))

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
                "No toys connected yet — switch one on and it appears "
                "here. Toys you've used before but that are off right now "
                "are listed in Device Routing."
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
            lambda n=device_name: self.focus_device(n),
            section="toys", tile_id=device_name,
        )
        self._explain(frame, device_name,
                      "Click to open this toy in Device Routing \u2014 which "
                      "zones drive it and how each motor responds.")
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
    # System section (OSC + mode + backend health)
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
        if hasattr(self.controller, "get_active_mode_info"):
            tile = self._build_overview_profile_tile()
            self._overview_grid_add(refs, tile["frame"], idx)
            refs["tiles"]["profile"] = tile
            idx += 1
        # Backend-health tile: a single "is anything broken right now?"
        # glance card.
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
        avatar_label = QLabel("Avatar: \u2014")
        avatar_label.setProperty("muted", "true")
        self._repolish(avatar_label)
        lay.addWidget(avatar_label)
        lay.addStretch(1)
        tile = {
            "frame": frame, "dot": dot,
            "port_label": port_label, "packets_label": packets_label,
            "avatar_label": avatar_label,
            "_last_packets": 0,
        }
        self._refresh_osc_tile(tile)
        return tile

    def _refresh_osc_tile(self, tile: Dict[str, Any]) -> None:
        snap = self.controller.get_osc_status_snapshot() or {}
        # Three-colour dot mirroring the main status pill: yellow is the
        # handshake-but-silent trap (osc_link_state), not a real connection.
        state = snap.get("link_state") or (
            "waiting" if snap.get("connected") else "disconnected")
        color = {"live": COLOR_SUCCESS, "live_router": COLOR_SUCCESS,
                 "waiting": COLOR_WARNING}.get(state, COLOR_ALERT)
        tile["dot"].setStyleSheet(
            f"background-color: {color}; border-radius: 6px;")
        port = snap.get("port")
        tile["port_label"].setText(f"Port: {port if port else '—'}")
        packets = int(snap.get("packets", 0))
        tile["packets_label"].setText(f"Packets: {packets:,}")
        tile["_last_packets"] = packets
        avatar = ""
        try:
            avatar = self.controller.get_current_avatar_id() or ""
        except Exception:
            pass
        label = tile.get("avatar_label")
        if label is not None:
            label.setText("Avatar: " + (self._overview_truncate(avatar, 16)
                                        if avatar else "\u2014"))
            label.setToolTip(avatar or "No avatar reported by VRChat yet")

    def _build_overview_profile_tile(self) -> Dict[str, Any]:
        # "Active Mode" tile. The internal ids keep the historical
        # "profile" name so persisted tile sizes (dashboard_tile_sizes)
        # survive the profiles → modes migration.
        frame = self._overview_make_tile(
            None, section="system", tile_id="profile",
        )
        self._explain(frame, "Active mode",
                      "The routing that is live right now. Switch modes "
                      "with the buttons at the top of the sidebar, or from "
                      "inside VRChat.")
        lay = frame.layout()
        title = QLabel("Active Mode")
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
        info = self.controller.get_active_mode_info() or {}
        name = str(info.get("name") or "—")
        icon = str(info.get("icon") or "")
        tile["name"].setText(
            self._overview_truncate(f"{icon} {name}".strip(), 22)
        )
        tile["name"].setToolTip(name)
        tile["sub"].setText("Switch in the sidebar")

    # Every backend gets a pill: (pill_key, label, feature_keys-any-of,
    # status getter, status field). Hidden while its feature is off, warn
    # while enabled-but-disconnected, ok while connected.
    _BACKEND_PILLS = (
        ("intiface", "Intiface", ("feature_intiface",),
         "get_intiface_status", "connected"),
    )

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
        pills: Dict[str, QLabel] = {}
        pills_row = QWidget()
        pills_lay = _hbox(0, 4)
        pills_row.setLayout(pills_lay)
        for pill_key, label, _feats, _getter, _field in self._BACKEND_PILLS:
            pill = QLabel(label)
            pill.setProperty("role", "pill")
            pill.setProperty("tone", "warn")
            self._repolish(pill)
            pills_lay.addWidget(pill)
            pills[pill_key] = pill
        pills_lay.addStretch(1)
        lay.addWidget(pills_row)
        lay.addStretch(1)
        tile = {"frame": frame, "pills": pills}
        self._refresh_backends_tile(tile)
        return tile

    def _refresh_backends_tile(self, tile: Dict[str, Any]) -> None:
        pills = tile.get("pills", {})
        for pill_key, _label, feature_keys, getter_name, field in self._BACKEND_PILLS:
            pill = pills.get(pill_key)
            if pill is None:
                continue
            try:
                enabled = any(self.controller.get_feature_enabled(k)
                              for k in feature_keys)
            except Exception:
                enabled = True
            pill.setVisible(enabled)
            if not enabled:
                continue
            getter = getattr(self.controller, getter_name, None)
            ok = False
            if callable(getter):
                try:
                    ok = bool((getter() or {}).get(field))
                except Exception:
                    ok = False
            self._overview_set_pill(pill, ok)

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
        if on_click is not None:
            frame.setCursor(Qt.PointingHandCursor)
        size_class = self._overview_get_tile_size(section, tile_id)
        w, h = _TILE_SIZES.get(size_class, _TILE_SIZES[_DEFAULT_TILE_SIZE])
        frame.setFixedSize(QSize(w, h))
        frame.setProperty("size_class", size_class)
        lay = _vbox(5, 2)
        frame.setLayout(lay)

        def on_press(ev):
            if ev.button() == Qt.LeftButton and on_click is not None:
                try:
                    on_click()
                except Exception:
                    pass
                ev.accept()
            else:
                QFrame.mousePressEvent(frame, ev)
        frame.mousePressEvent = on_press

        # Keyboard access: tiles are navigation targets, so they must be
        # reachable by Tab and activatable by Space/Return (the QSS
        # :focus rule draws the indicator). hasFocus() is load-bearing —
        # the ⤢ QToolButton ignore()s Return/Enter after handling focus,
        # and a bubbled key must not navigate away. Same pattern as
        # FoldCard.keyPressEvent.
        frame.setFocusPolicy(Qt.TabFocus)

        def on_key(ev):
            if (frame.hasFocus() and not ev.isAutoRepeat()
                    and ev.key() in (Qt.Key_Space, Qt.Key_Return,
                                     Qt.Key_Enter)):
                try:
                    on_click()
                except Exception:
                    pass
                ev.accept()
            else:
                QFrame.keyPressEvent(frame, ev)
        frame.keyPressEvent = on_key

        # The expand button is created here so every tile (Toys,
        # System, etc.) gets it without each builder needing to
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
            color = COLOR_ALERT
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
