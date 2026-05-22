"""Overview view — unified read-only card-grid for every connected
or stored thing across all haptic backends.

Cut 1 scope: Toys section only. Each Toy tile shows:
- Lovense product icon (auto-detect or per-toy override, same as
  Device Routing)
- Connect dot (green = connected, red = stored-but-offline)
- Device name
- Battery glyph (no-battery painted glyph fallback) or '🔋 NN%'
- Aggregate vibe meter — the max across the device's motors
- Active-zones summary string

Strictly read-only — clicking a tile jumps to Device Routing for
editing; the tile itself never mutates profile or engine state. The
read-only contract is load-bearing for the Demeter rule: no UI ->
engine writes originate from this view.

Live updates piggyback on DeviceFrameMixin's existing update paths
via three small hook methods (_overview_set_motor_value /
_overview_set_battery / _overview_refresh_connection_states) that
DeviceFrameMixin calls with hasattr-guards. No new controller
facades needed.

Cut 2 will add SteamVR / bHaptics / Hardware Monitor / System tile
types. Cut 3 will add snap-grid resize (1x1 / 2x1 / 2x2) +
QPropertyAnimation + chip-filter row + per-tile size persistence."""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)

from constants import (
    BTN_HEIGHT_SMALL, COLOR_ALERT, COLOR_SUCCESS, COLOR_TEXT,
)

from ui import lovense_icons as _lovense_icons
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import RainbowMeter as _RainbowMeter, ProgressProxy as _ProgressProxy
from ui.icons import icon_no_battery as _icon_no_battery


# Fixed grid column count for Cut 1. Cut 3 swaps this for a true
# FlowLayout that wraps based on available width.
_OVERVIEW_GRID_COLS = 4

# Fixed tile size for Cut 1 (1x1 base unit). Cut 3 introduces 2x1
# and 2x2 variants on a snap grid.
_TILE_BASE_WIDTH = 220
_TILE_BASE_HEIGHT = 110


class OverviewMixin:

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_overview_view(self, parent_layout: QVBoxLayout):
        # Initialise the tile registry lazily so the first view build
        # creates the dict and subsequent rebuilds reuse the slot.
        self._overview_tiles: Dict[str, Dict[str, Any]] = {}
        # Per-(device, motor) cache of the latest motor target value,
        # used to compute the aggregate (max across motors) for each
        # device's tile.
        self._overview_motor_values: Dict[str, Dict[int, float]] = {}

        title = QLabel("Overview")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        subtitle = QLabel(
            "Read-only at-a-glance view. Click a tile to jump to its "
            "editor view for configuration."
        )
        subtitle.setProperty("muted", "true")
        subtitle.setAlignment(Qt.AlignHCenter)
        subtitle.setWordWrap(True)
        self._repolish(subtitle)
        parent_layout.addWidget(subtitle)

        # Toys section.
        toys_header = QLabel("Toys")
        thf = toys_header.font(); thf.setBold(True); thf.setPointSize(12)
        toys_header.setFont(thf)
        parent_layout.addWidget(toys_header)

        toys_container = QWidget()
        toys_container.setObjectName("overviewToysGrid")
        self._overview_toys_grid = QGridLayout()
        self._overview_toys_grid.setContentsMargins(0, 0, 0, 0)
        self._overview_toys_grid.setHorizontalSpacing(8)
        self._overview_toys_grid.setVerticalSpacing(8)
        toys_container.setLayout(self._overview_toys_grid)
        parent_layout.addWidget(toys_container)

        self._overview_toys_container = toys_container
        self._overview_toys_empty: Optional[QLabel] = None

        # Stretch at the bottom so tiles hug the top.
        parent_layout.addStretch(1)

        # Initial population — devices may already be known via the
        # active profile even before the user has connected anything.
        self.rebuild_overview()

    # ----------------------------------------------------------
    # Tile (re)builder
    # ----------------------------------------------------------

    def rebuild_overview(self) -> None:
        """Wipe and re-render the Toys grid from the active profile.
        Called on view build, profile switch, and known-device changes."""
        grid = getattr(self, "_overview_toys_grid", None)
        if grid is None:
            # View hasn't been built yet — nothing to do.
            return

        # Clear existing tiles.
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._overview_tiles.clear()
        self._overview_motor_values.clear()
        if self._overview_toys_empty is not None:
            self._overview_toys_empty.setParent(None)
            self._overview_toys_empty.deleteLater()
            self._overview_toys_empty = None

        profile = self.controller.get_active_profile_dict() or {}
        connected = set(self.controller.get_connected_device_names())
        device_names = sorted(profile.keys(), key=lambda s: (s not in connected, s.lower()))
        if not device_names:
            empty = QLabel(
                "No toys in the active profile yet. Connect a toy via "
                "Intiface Central, then it'll appear here automatically."
            )
            empty.setProperty("muted", "true")
            empty.setAlignment(Qt.AlignHCenter)
            empty.setWordWrap(True)
            self._repolish(empty)
            grid.addWidget(empty, 0, 0, 1, _OVERVIEW_GRID_COLS)
            self._overview_toys_empty = empty
            return

        for idx, name in enumerate(device_names):
            tile = self._build_overview_toy_tile(name, profile[name],
                                                 is_connected=(name in connected))
            row, col = divmod(idx, _OVERVIEW_GRID_COLS)
            grid.addWidget(tile["frame"], row, col)
            self._overview_tiles[name] = tile

    def _build_overview_toy_tile(self, device_name: str, config: Dict[str, Any],
                                 is_connected: bool) -> Dict[str, Any]:
        frame = QFrame()
        frame.setObjectName("overviewTile")
        frame.setFixedSize(QSize(_TILE_BASE_WIDTH, _TILE_BASE_HEIGHT))
        frame.setCursor(Qt.PointingHandCursor)
        frame.setProperty("connected", "true" if is_connected else "false")
        lay = _vbox(8, 4)
        frame.setLayout(lay)

        # Header row: icon + dot + name.
        head = QWidget()
        head_lay = _hbox(0, 6)
        head.setLayout(head_lay)

        icon_btn = QToolButton()
        icon_btn.setEnabled(False)  # purely decorative on the tile
        icon_btn.setObjectName("lovenseIcon")
        icon_btn.setAutoRaise(True)
        icon_btn.setFixedSize(QSize(28, 28))
        icon_btn.setIconSize(QSize(24, 24))
        self._apply_lovense_icon(device_name, icon_btn)
        head_lay.addWidget(icon_btn)

        dot = QFrame()
        dot.setObjectName("connectDot")
        dot.setFixedSize(10, 10)
        self._apply_connect_dot(dot, is_connected)
        head_lay.addWidget(dot, 0, Qt.AlignVCenter)

        name_label = QLabel(self._overview_truncate(device_name, 22))
        name_label.setObjectName("overviewTileName")
        nf = name_label.font(); nf.setBold(True)
        name_label.setFont(nf)
        name_label.setToolTip(device_name)
        head_lay.addWidget(name_label, 1)
        lay.addWidget(head)

        # Battery + active-zones row.
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

        # Aggregate vibe meter at the bottom.
        vibe = _RainbowMeter(maximum=1000)
        vibe.setFixedHeight(10)
        lay.addWidget(vibe)

        # Whole tile clickable -> jump to Device Routing.
        def on_press(ev):
            if ev.button() == Qt.LeftButton:
                self.select_view("Device Routing")
                ev.accept()
            else:
                QFrame.mousePressEvent(frame, ev)
        frame.mousePressEvent = on_press

        return {
            "frame": frame,
            "icon_btn": icon_btn,
            "dot": dot,
            "name_label": name_label,
            "battery_label": battery_label,
            "zones_label": zones_label,
            "vibe_meter": _ProgressProxy(vibe),
        }

    # ----------------------------------------------------------
    # Live-update hooks (called from DeviceFrameMixin's existing paths)
    # ----------------------------------------------------------

    def _overview_set_motor_value(self, device_name: str,
                                  motor_idx: int, value: float) -> None:
        """Update the aggregate vibe meter for this device. The tile
        shows max() across this device's motors."""
        if not getattr(self, "_overview_tiles", None):
            return
        tile = self._overview_tiles.get(device_name)
        if tile is None:
            return
        motors = self._overview_motor_values.setdefault(device_name, {})
        if motor_idx == -1:
            # The controller sometimes uses -1 to mean 'all motors'; treat
            # it as a wholesale set rather than tracking under a -1 key.
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
        battery_label: QLabel = tile["battery_label"]
        pct = int(level * 100)
        if pct > 50:
            color = COLOR_SUCCESS
        elif pct > 20:
            color = COLOR_ALERT
        else:
            color = "#FF4444"
        battery_label.setText(f"🔋 {pct}%")
        battery_label.setStyleSheet(f"color: {color};")

    def _overview_refresh_connection_states(self) -> None:
        """Update each tile's dot + name colour to reflect current
        connection state. Called when the controller's connected-device
        list changes."""
        if not getattr(self, "_overview_tiles", None):
            return
        connected = set(self.controller.get_connected_device_names())
        for name, tile in self._overview_tiles.items():
            is_conn = name in connected
            dot = tile.get("dot")
            if dot is not None:
                self._apply_connect_dot(dot, is_conn)
            frame: QFrame = tile["frame"]
            frame.setProperty("connected", "true" if is_conn else "false")
            self._repolish(frame)
            if not is_conn:
                # Reset battery to glyph; the last-known level isn't
                # trustworthy once the device is gone.
                bl = tile.get("battery_label")
                if bl is not None:
                    self._show_no_battery_glyph(bl)

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    def _overview_zones_summary(self, config: Dict[str, Any]) -> str:
        """Concise per-tile description of what zones this device is
        configured to listen to. Reads motor_0_zones as the primary
        signal; multi-motor devices append a count suffix when their
        configurations differ."""
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

        # If every motor has the same zone string, show one label.
        # Otherwise indicate the spread.
        if len(set(zones_strs)) == 1:
            return _label(zones_strs[0])
        return f"Motors differ ({motor_count})"

    @staticmethod
    def _overview_truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 1] + "…"
