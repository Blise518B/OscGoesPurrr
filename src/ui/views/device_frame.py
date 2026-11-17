"""Per-device toy frames: each toy's card on the Toys page (its bar and
its motors' signal chains) and its row on Home (the same bar), the
variable picker.

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
    QButtonGroup, QStackedWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QComboBox, QSpinBox, QDoubleSpinBox, QToolButton,
    QGraphicsOpacityEffect,
)
import shiboken6

from ui import lovense_icons as _lovense_icons
import contact_filters as _contact

from constants import *
from utilities import strip_param_prefix
from motor_param_out import param_out_keys

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
    icon_no_battery as _icon_no_battery,
)
from ui.widgets import (
    ToggleSwitch,
    Invoker as _Invoker,
    MainWindow as _MainWindow,
    Card as _Card,
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    ToyFrame as _ToyFrame,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
    TOY_ICON_PX as _TOY_ICON_PX,
    TOY_ICON_SLOT_PX as _TOY_ICON_SLOT_PX,
    OFFLINE_ICON_OPACITY as _OFFLINE_ICON_OPACITY,
)
from ui.tooltips import explain as _explain_target
from ui import theme as _theme
from ui.motor_signal_chain import (
    MotorChainListWidget as _MotorChainListWidget,
    _get_chain_count,
    _get_chain_type,
)
from ui.osc_variable_picker import open_osc_variable_picker


# A motor's meter in a bar, and the gap between two of them. (The toy
# icon's size and offline fade live in ui/widgets.py: Home's shocker / suit
# rows share them.)
_METER_PX = 56
_METER_GAP_PX = 3


def _toy_bar_ground(bar: QWidget, card) -> str:
    """What lies behind a toy bar's mini meter right now: the bar's hover
    tint while the pointer is on it (theme.py, QWidget#toyBar:hover), else
    the toy frame's fill, else -- an offline toy's frame has none -- the
    window's ground."""
    if bar.underMouse():
        return _theme.CHROME["hover"]
    return card.ground() or _theme.CHROME["bg"]


# Home's contact chips: (pair, its row's caption, the chip's own word,
# the explanation's title, what it is in a sentence).
_CONTACT_CHIPS = (
    (_contact.TOUCH_SELF, "Touch", "Self", "Touch from yourself",
     "your own hands and body touching your avatar's zones"),
    (_contact.TOUCH_OTHERS, "Touch", "Others", "Touch from others",
     "other players' hands and bodies touching your avatar's zones"),
    (_contact.PEN_SELF, "Penetration", "Self", "Penetration from yourself",
     "your own plug in your own sockets"),
    (_contact.PEN_OTHERS, "Penetration", "Others", "Penetration from others",
     "other players penetrating you, or you them"),
)
_KIND_CHAIN_WORDS = {
    _contact.KIND_TOUCH: "Touch and Custom",
    _contact.KIND_PENETRATION: "Penetration and Custom",
}


# A toy bar's arrangements, widest first: _fit_toy_bar takes the first that
# fits the bar. (mode, the chips as two rows -- and Sleep over Anti-stuck)
_BAR_WIDE, _BAR_TWO, _BAR_THREE = "wide", "two", "three"
_BAR_ARRANGEMENTS = ((_BAR_WIDE, True), (_BAR_TWO, False), (_BAR_TWO, True),
                     (_BAR_THREE, False), (_BAR_THREE, True))


def _layout_width(w: QWidget) -> int:
    """How wide a layout makes `w`: its size hint, within its bounds."""
    return max(w.minimumWidth(), min(w.sizeHint().width(), w.maximumWidth()))


class _SwitchNameRow(QWidget):
    """`[switch] [parameter name] [Pick…]` on one line while it fits, else
    the name box and Pick… on a line under the switch -- so a card that
    holds it (a toy's on the Toys page, the Settings and Shockers cards)
    never needs a sideways scrollbar. Decided by the row's own width."""

    def __init__(self, toggle: QWidget, edit: QWidget, pick: QWidget,
                 edit_min: int = 160, parent=None, edit_max: int = 0):
        super().__init__(parent)
        self._parts = (toggle, edit, pick)
        self._edit_min = edit_min
        # edit_max: a compact row -- the name box this wide, the row's
        # slack after Pick… instead of in the box
        self._compact = bool(edit_max)
        if edit_max:
            edit.setFixedWidth(edit_max)
            self._edit_min = edit_max
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        self._one_line = None
        self._arrange(True)
        # no narrower than the two lines need: the switch, or the name box
        # (at 100, or its fixed width) with Pick… beside it
        self.setMinimumWidth(max(_layout_width(toggle),
                                 (edit_max or 100) + 8 + _layout_width(pick)))

    def _arrange(self, one_line: bool) -> None:
        if one_line == self._one_line:
            return
        self._one_line = one_line
        toggle, edit, pick = self._parts
        grid = self.layout()
        for w in self._parts:
            grid.removeWidget(w)
        left = Qt.AlignLeft | Qt.AlignVCenter
        if one_line:
            grid.addWidget(toggle, 0, 0)
            grid.addWidget(edit, 0, 1)
            if self._compact:
                grid.addWidget(pick, 0, 2, left)
            else:
                grid.addWidget(pick, 0, 2)
            stretch = (0, 0, 1) if self._compact else (0, 1, 0)
        else:
            grid.addWidget(toggle, 0, 0, 1, 2)
            grid.addWidget(edit, 1, 0)
            if self._compact:
                grid.addWidget(pick, 1, 1, left)
            else:
                grid.addWidget(pick, 1, 1)
            stretch = (0, 1, 0) if self._compact else (1, 0, 0)
        for col, s in enumerate(stretch):
            grid.setColumnStretch(col, s)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        toggle, _edit, pick = self._parts
        need = _layout_width(toggle) + 8 + self._edit_min + 8 + _layout_width(pick)
        self._arrange(self.width() >= need)


class _ResizeWatch(QObject):
    """Calls back whenever the watched widget is resized -- a toy bar
    re-deciding whether its chips fit on its first line."""

    def __init__(self, target: QWidget, callback: Callable[[], None]):
        super().__init__(target)
        self._callback = callback
        target.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 (Qt API)
        if event.type() == QEvent.Resize:
            self._callback()
        return False


class DeviceFrameMixin:

    # The toy bar's lines under the first start under the name: past the
    # icon, the dot and their gaps.
    _TOY_BAR_INDENT = _TOY_ICON_SLOT_PX + 8 + 12 + 8

    # ----------------------------------------------------------
    # Stored devices status
    # ----------------------------------------------------------

    def update_stored_devices_ui(self):
        connected_names = self.controller.get_connected_device_names()
        # Cache for the hot path: _set_motor_levels runs per changed motor
        # inside the routing tick and must not re-query the facade (a fresh
        # set built from the client's device map) every call. This 1 Hz
        # heartbeat + build_device_list_ui keep the cache current.
        self._connected_names_cache = frozenset(connected_names)
        for device_name, frame_data in self.stored_device_frames.items():
            status_label: Optional[QLabel] = frame_data.get("status_label")
            delete_button: Optional[QPushButton] = frame_data.get("delete_button")
            if status_label is None or delete_button is None:
                continue
            full_frame = self.device_ui_frames.get(device_name, {})
            is_connected = device_name in connected_names
            status_label.setText(device_name)
            self._apply_toy_connection(full_frame, is_connected)
            delete_button.setEnabled(True)
        self._reorder_device_frames()
        # Test all has nothing to buzz while no toy is connected.
        test_all = getattr(self, "_test_all_button", None)
        if test_all is not None:
            test_all.setEnabled(bool(connected_names))

    def _apply_toy_connection(self, frame_data: dict, is_connected: bool) -> None:
        """Paint one toy as live or offline -- its card on the Toys page and
        its row on Home alike. An offline toy -- one that is remembered but
        switched off or out of range -- keeps both (grey outline, see
        _reorder_device_frames) so its setup stays reachable, but drops
        everything that only means something live: the battery, the meters,
        Mute and Test. Change-gated: this rides the 1 Hz stored-devices
        heartbeat."""
        if not frame_data or frame_data.get("connected") == is_connected:
            return
        frame_data["connected"] = is_connected
        for bar in self._toy_bars(frame_data):
            self._paint_toy_bar_connection(bar, is_connected)

    @staticmethod
    def _toy_bars(frame_data: Optional[dict]) -> List[dict]:
        """A toy's bars: its card's on the Toys page (the frame data's own
        keys) and its row's on Home ("home"), where there is one."""
        if not frame_data:
            return []
        home = frame_data.get("home")
        return [frame_data, home] if home else [frame_data]

    def _paint_toy_bar_connection(self, bar: dict, is_connected: bool) -> None:
        dot = bar.get("connect_dot")
        if dot is not None:
            self._apply_connect_dot(dot, is_connected)
        name_label = bar.get("status_label")
        if name_label is not None:
            name_label.setProperty("role", "success" if is_connected else "")
            self._repolish(name_label)
        battery_label = bar.get("battery_label")
        if battery_label is not None and not is_connected:
            # Drop back to the no-battery glyph; the last-known level
            # can't be trusted once the device is gone.
            self._show_no_battery_glyph(battery_label)
        for key in ("battery_label", "mini_bar_strip", "mute_button",
                    "test_button"):
            w = bar.get(key)
            if w is not None:
                w.setVisible(is_connected)
        pill = bar.get("offline_pill")
        if pill is not None:
            pill.setVisible(not is_connected)
        icon = bar.get("icon_button")
        if icon is not None:
            effect = None
            if not is_connected:
                effect = QGraphicsOpacityEffect(icon)
                effect.setOpacity(_OFFLINE_ICON_OPACITY)
            icon.setGraphicsEffect(effect)
        # The first line just got shorter or longer: maybe the chips fit
        # there now, or no longer do.
        self._fit_toy_bar(bar)

    def update_battery_label(self, device_name: str, level: float):
        pct = int(level * 100)
        color = COLOR_SUCCESS if pct > 50 else COLOR_ALERT
        for bar in self._toy_bars(self.device_ui_frames.get(device_name)):
            battery_label: Optional[QLabel] = bar.get("battery_label")
            if battery_label is not None:
                battery_label.setText(f"🔋 {pct}%")
                battery_label.setStyleSheet(f"color: {color};")

    # ----------------------------------------------------------
    # Device card construction
    # ----------------------------------------------------------

    def _create_device_frame(self, device_name: str, is_connected: bool,
                             osc_addresses: dict, motor_count: int,
                             motor_kinds: Optional[List[str]] = None) -> dict:
        """One toy, in two places: its card on the Toys page -- a bar and
        a body, open by default, holding the per-motor signal chains
        (folded; the bar folds the body away) -- and its row on Home, the same bar on its
        own, which opens the card when clicked (open_toy_card). The bar is
        the toy's overview (connection, what drives it and who it hears,
        battery, a meter per motor, Mute/Test); both bars show the same
        live state. The frame data's own keys are the card's; "home" holds
        the row's (_toy_bars)."""

        # The toy is one thin frame outlined in its identity hue (assigned
        # by display position in _reorder_device_frames); the bar below is
        # unfilled, inset 3px so its hover tint sits inside the frame.
        card = _ToyFrame()
        card.setObjectName("toyFrame")
        card_lay = _vbox(3, 0)
        card.setLayout(card_lay)

        # ---- Collapsed bar (always visible) ----
        frame_data = self._build_toy_bar(device_name, motor_count, card)
        bar = frame_data["bar"]
        expand_caret = frame_data["caret"]
        card_lay.addWidget(bar)
        # The card's sections for the live colour sweep: the bar, each
        # motor's block and the rows under them. The frame around them is
        # painted (ToyFrame), so it needs none.
        self._style_root(bar)

        # ---- Body: the motors' chains, then one compact line ----
        # The chains own the card (Blise's ask, 2026-11-17); the avatar
        # parameters and Delete device are advanced, so they wait in one
        # small line at the very bottom (_build_toy_foot).
        body = QWidget()
        body.setObjectName("toyBody")
        body_lay = _vbox(0, 8)
        # 8 on top: room for the hairline the frame draws under the bar
        # (ToyFrame.set_head, below)
        body_lay.setContentsMargins(10, 8, 10, 6)
        body.setLayout(body_lay)
        body.setVisible(False)

        motor_vars: List[Dict[str, Any]] = []
        for motor_idx in range(motor_count):
            motor_kind = (motor_kinds[motor_idx]
                          if motor_kinds and motor_idx < len(motor_kinds) else None)
            motor_card, motor_var = self._build_motor_card(
                device_name, motor_idx, osc_addresses, motor_kind,
                heading=motor_count > 1,
            )
            body_lay.addWidget(motor_card)
            self._style_root(motor_card)
            motor_vars.append(motor_var)

        foot, foot_parts = self._build_toy_foot(device_name, motor_count)
        body_lay.addWidget(foot)
        self._style_root(foot)
        delete_button = foot_parts["delete_button"]

        card_lay.addWidget(body)
        # A hairline in the toy's hue under its bar while the card is open:
        # in a stack of tall cards, each plainly starts at its bar (Blise's
        # ask, 2026-11-17: "where one toy starts and stops")
        card.set_head(bar, body)

        # Click anywhere on the bar (except on its own buttons, which
        # consume their clicks) toggles the body. Buttons in the bar get
        # their events first via normal child-first dispatch; QLabels and
        # the bar background propagate up to this handler.
        def set_expanded(expanded: bool):
            body.setVisible(bool(expanded))
            expand_caret.setText("▾" if expanded else "▸")

        def toggle_expand():
            set_expanded(not body.isVisible())

        def on_bar_press(ev):
            if ev.button() == Qt.LeftButton:
                toggle_expand()
                ev.accept()
            else:
                QWidget.mousePressEvent(bar, ev)
        bar.mousePressEvent = on_bar_press
        # Open from the start (Blise's ask, 2026-11-16): the Toys page is
        # where a toy is set up precisely, so each card shows its motors'
        # chains -- folded, one bar each -- without a click. Home's row is
        # the compact overview.
        set_expanded(True)

        layout = getattr(self, "unified_devices_layout", None)
        if layout is not None:
            insert_pos = max(layout.count() - 1, 0)
            layout.insertWidget(insert_pos, card)

        frame_data.update({
            "frame": card,
            "body": body,
            "set_expanded": set_expanded,
            "delete_button": delete_button,
            "motors": motor_vars,
            "foot": foot,
        })
        frame_data.update(foot_parts)

        # ---- Its row on Home: the bar alone, a click opens the card ----
        home_lay = getattr(self, "home_list_layout", None)
        if home_lay is not None:
            row = _ToyFrame()
            row.setObjectName("toyFrame")
            row_lay = _vbox(3, 0)
            row.setLayout(row_lay)
            home = self._build_toy_bar(device_name, motor_count, row, on_home=True)
            home_bar = home["bar"]
            row_lay.addWidget(home_bar)
            self._style_root(home_bar)

            def on_row_press(ev, n=device_name, b=home_bar):
                if ev.button() == Qt.LeftButton:
                    opener = getattr(self, "open_toy_card", None)
                    if callable(opener):
                        opener(n)
                    ev.accept()
                else:
                    QWidget.mousePressEvent(b, ev)
            home_bar.mousePressEvent = on_row_press
            # As the shocker and suit rows say where a click goes
            self._explain(
                home_bar, device_name,
                "One of your toys at a glance: what drives it, who it hears, "
                "its battery and a live meter per motor. <b>Click the bar</b> "
                "to open it on the Toys page, where its signal chains are. "
                "The Touch / Penetration chips, Mute and Test work right here.")
            home["frame"] = row
            home_lay.insertWidget(max(home_lay.count() - 1, 0), row)
            frame_data["home"] = home

        self._refresh_contact_chips(device_name, frame_data)
        self._apply_toy_connection(frame_data, is_connected)
        for one in self._toy_bars(frame_data):
            self._fit_toy_bar(one)
            _ResizeWatch(one["bar"], lambda d=one: self._fit_toy_bar(d))
        return frame_data

    def _build_toy_bar(self, device_name: str, motor_count: int, card,
                       on_home: bool = False) -> dict:
        """A toy's bar -- its card's on the Toys page, or (`on_home`) its
        row on Home, which ends in a › instead of the card's ▸ / ▾: a
        click there goes to the card. Returns its widgets by name.

        Its widgets sit on up to three lines, arranged by the room the bar
        has (_fit_toy_bar, Blise's ask 2026-11-16: "only go up or down when
        the window gets smaller and the size is needed"): one line while it
        fits -- the name, then the Touch and Penetration chips as a block of
        two rows, then the battery, meters, Mute and Test, all centred on
        it -- then the name line with the chips under it, then at the
        narrowest the battery and meters on a line of their own. Every
        widget stays the bar's own child; only which line holds it changes."""
        bar = QWidget()
        bar.setObjectName("toyBar")
        bar.setCursor(Qt.PointingHandCursor)
        # Shrinkable to nothing: the bar's width must stay the parent's to
        # give, or it could never tell that its line no longer fits -- the
        # page would grow a sideways scrollbar instead.
        bar.setMinimumWidth(1)
        bar_outer = _vbox(0, 3)
        bar_outer.setContentsMargins(8, 5, 8, 5)
        bar.setLayout(bar_outer)
        lines = []
        for i in range(3):
            line = _hbox(0, 8)
            if i:
                line.setContentsMargins(self._TOY_BAR_INDENT, 0, 0, 0)  # under the name
            bar_outer.addLayout(line)
            lines.append(line)

        icon_button = QToolButton(bar)
        icon_button.setObjectName("lovenseIcon")
        icon_button.setAutoRaise(True)
        icon_button.setIconSize(QSize(_TOY_ICON_PX, _TOY_ICON_PX))
        icon_button.setFixedSize(QSize(_TOY_ICON_SLOT_PX, _TOY_ICON_SLOT_PX))
        icon_button.setCursor(Qt.PointingHandCursor)
        icon_button.clicked.connect(
            lambda _=False, n=device_name, b=icon_button: self._on_lovense_icon_clicked(n, b)
        )
        self._apply_lovense_icon(device_name, icon_button)

        # Filled green dot = connected, hollow grey ring = offline.
        connect_dot = QFrame(bar)
        connect_dot.setObjectName("connectDot")
        connect_dot.setFixedSize(12, 12)

        name_label = QLabel(device_name, bar)
        name_label.setObjectName("deviceName")

        # What drives this toy in the active mode ("All SPS", "3 zones")
        # and who it hears; both kept current by _refresh_toy_summaries.
        zones_label = QLabel(self._toy_zones_summary(device_name, motor_count), bar)
        zones_label.setObjectName("toyZones")
        self._explain(
            zones_label, "What drives this toy",
            "The avatar zones this toy listens to in the active mode, "
            "across all its motors and chains. "
            + ("Click the toy to open it on the Toys page, where a chain's "
               "Input stage changes them." if on_home else
               "Open a chain and click its Input stage to change them."))
        chips_box = QWidget(bar)
        chips_box.setObjectName("toyChips")
        contact_chips, captions = self._build_contact_chips(device_name, chips_box)
        # Sleep over Anti-stuck, beside the chips (Blise's ask, 2026-11-17)
        safety_box = QWidget(bar)
        safety_box.setObjectName("toySafety")
        safety_chips = self._build_safety_chips(device_name, safety_box)

        offline_pill = QLabel("OFFLINE", bar)
        offline_pill.setProperty("role", "pill")
        offline_pill.setProperty("tone", "idle")
        self._explain(
            offline_pill, "Offline",
            "Switched off or out of range. Everything you set up for it is "
            "kept, and it comes back to life the moment it reconnects.")

        # Battery defaults to the no-battery glyph; a real battery_update
        # event replaces it with "🔋 NN%" via update_battery_label.
        battery_label = QLabel("", bar)
        battery_label.setMinimumWidth(70)
        battery_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self._show_no_battery_glyph(battery_label)

        # One mini-bar per motor — glance-while-collapsed visibility. The
        # strip is as wide as two meters whatever the motor count (a lone
        # motor's meter fills it), so the battery column and the buttons
        # line up from one row to the next.
        mini_bar_strip = QWidget(bar)
        mini_strip_lay = _hbox(0, _METER_GAP_PX)
        mini_bar_strip.setLayout(mini_strip_lay)
        slots = max(2, motor_count)
        mini_bar_strip.setFixedSize(
            slots * _METER_PX + (slots - 1) * _METER_GAP_PX, 10)
        mini_bars: List = []
        for _ in range(motor_count):
            mb = _RainbowMeter(maximum=1000)
            mb.setFixedHeight(10)
            # These tick at the router's rate whenever the toy plays: each
            # paints its own ground (the bar's hover tint, else the toy
            # frame's), so the frame and the page behind it stay put.
            mb.set_ground(lambda b=bar, c=card: _toy_bar_ground(b, c), hover_of=bar)
            mini_strip_lay.addWidget(mb)
            mini_bars.append(_ProgressProxy(mb))

        # Mute = per-toy soft-mute, session-only. Engine target is forced
        # to 0 while held; the meter keeps showing real mixer output.
        mute_btn = QPushButton("Mute", bar)
        mute_btn.setCheckable(True)
        mute_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        mute_btn.setChecked(self.controller.is_device_muted(device_name))
        self._apply_mute_btn_style(mute_btn)

        def on_mute_toggled(checked, n=device_name, btn=mute_btn):
            self.controller.set_device_muted(n, bool(checked))
            self._apply_mute_btn_style(btn)
            self._show_muted(n, bool(checked))

        mute_btn.toggled.connect(on_mute_toggled)
        self._explain(
            mute_btn, "Mute",
            "Silences just this toy. Its meter keeps moving so you can see "
            "what it would be doing; press again to bring it back. Stays "
            "muted when you switch modes, but not across a restart.")

        # Test = fixed 0.3s @ 0.5 pulse on this toy's vibrate motors.
        test_btn = QPushButton("Test", bar)
        test_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        test_btn.setProperty("role", "secondary")
        test_btn.clicked.connect(
            lambda _=False, n=device_name: self.controller.test_device(n)
        )
        self._explain(
            test_btn, "Test",
            "A short buzz on this toy, so you can tell which toy is which. "
            "Only its vibrating motors take part — a stroker won't "
            "suddenly move.")

        # The card: ▸ closed, ▾ open -- the same as the chain bars and the
        # folds. Home's row: a › like the shocker and suit rows', because a
        # click goes to another page.
        expand_caret = QLabel("›" if on_home else "▸", bar)
        expand_caret.setObjectName("expandCaret")
        expand_caret.setFixedWidth(18)
        expand_caret.setAlignment(Qt.AlignCenter)

        data = {
            "bar": bar,
            "status_label": name_label,
            "name_label": name_label,
            "zones_label": zones_label,
            "battery_label": battery_label,
            "icon_button": icon_button,
            "connect_dot": connect_dot,
            "offline_pill": offline_pill,
            "mini_bar_strip": mini_bar_strip,
            "mini_bars": mini_bars,
            "mute_button": mute_btn,
            "test_button": test_btn,
            "contact_chips": contact_chips,
            "chip_captions": captions,
            "chips_box": chips_box,
            "safety_chips": safety_chips,
            "safety_box": safety_box,
            "caret": expand_caret,
            "bar_lines": lines,
            "bar_line1": lines[0],
            "bar_line2": lines[1],
            "bar_line3": lines[2],
        }
        self._arrange_toy_bar(data, _BAR_TWO, False)
        self._paint_safety_bar(device_name, data)
        return data

    def _show_muted(self, device_name: str, muted: bool) -> None:
        """Mute was pressed on one of a toy's bars: the other says so too."""
        for bar in self._toy_bars(self.device_ui_frames.get(device_name)):
            btn = bar.get("mute_button")
            if btn is None:
                continue
            try:
                if btn.isChecked() != muted:
                    btn.blockSignals(True)
                    btn.setChecked(muted)
                    btn.blockSignals(False)
                    self._apply_mute_btn_style(btn)
            except RuntimeError:
                pass

    # ----------------------------------------------------------
    # Toy-frame helpers
    # ----------------------------------------------------------

    def _style_root(self, widget) -> None:
        """Register a section with the live colour sweep (ui/live_theme.py)
        so a colour change reaches it in its own small slice. A no-op on a
        host without one (the test hosts)."""
        live = getattr(self, "live_theme", None)
        if live is not None:
            live.add_root(widget)

    def _apply_connect_dot(self, dot_widget: QFrame, is_connected: bool) -> None:
        """Style the small connection-state dot in the toy bar. Offline is
        a hollow grey ring, not red: a toy that is switched off is not an
        error."""
        if is_connected:
            dot_widget.setStyleSheet(
                f"background-color: {COLOR_SUCCESS}; border-radius: 6px;")
        else:
            dot_widget.setStyleSheet(
                "background-color: transparent; "
                f"border: 2px solid {COLOR_DIM}; border-radius: 6px;")

    def _toy_zones_summary(self, device_name: str, motor_count: int) -> str:
        """One short phrase for what drives a toy in the active mode: the
        union of the zones its chains listen to. Reads each chain's zones
        the way the Input stage and the router do -- the chain's own key,
        falling back to the motor's, then to All SPS."""
        get = self.controller.get_profile_config
        missing = object()
        zones = set()
        for motor in range(max(int(motor_count), 0)):
            try:
                chains = _get_chain_count(self.controller, device_name, motor)
            except Exception:
                chains = 1
            for chain in range(chains):
                raw = get(device_name, f"motor_{motor}_c{chain}_zones", missing)
                if raw is missing:
                    raw = get(device_name, f"motor_{motor}_zones", "All SPS")
                zones.update(z.strip() for z in str(raw or "").split(",")
                             if z.strip() and z.strip() != "None")
        if not motor_count:
            return ""
        if "All SPS" in zones:
            return "All SPS"
        if not zones:
            return "Custom OSC only"
        if len(zones) == 1:
            return next(iter(zones))
        return f"{len(zones)} zones"

    def _refresh_toy_summaries(self) -> None:
        """Bring every toy bar's zone summary and contact chips up to date.
        Both belong to the active mode and are edited two clicks away on
        the Toys page, so Home's and the Toys page's 2 Hz refresh re-read
        them -- both bars of a toy; unchanged text and chips are left
        alone."""
        for device_name, data in self.device_ui_frames.items():
            if data.get("zones_label") is None:
                continue
            try:
                text = self._toy_zones_summary(
                    device_name, len(data.get("motors", ())))
                for bar in self._toy_bars(data):
                    label = bar.get("zones_label")
                    if label is not None and label.text() != text:
                        label.setText(text)
                        self._fit_toy_bar(bar)
                self._refresh_contact_chips(device_name, data)
                self._paint_safety_chips(device_name, data)
            except RuntimeError:
                pass  # card rebuilt meanwhile (device list changed)

    # ----------------------------------------------------------
    # Who a toy hears: Touch / Penetration x Self / Others
    # ----------------------------------------------------------

    def _build_contact_chips(self, device_name: str, box: QWidget
                             ) -> "tuple[Dict[str, QPushButton], Dict[str, QLabel]]":
        """The toy bar's four contact chips, two after a "Touch" caption
        and two after "Penetration", in `box`'s grid -- as two rows or one
        (_arrange_contact_chips). A chip sets its pair on every chain of
        the toy that hears that kind, in the active mode
        (_on_contact_chip); _refresh_contact_chips paints them. Returns
        (the chips by pair, the captions by their word)."""
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        chips: Dict[str, QPushButton] = {}
        captions: Dict[str, QLabel] = {}
        for pair, kind_word, word, title, what in _CONTACT_CHIPS:
            if kind_word not in captions:
                cap = QLabel(kind_word, box)
                cap.setObjectName("contactCaption")
                captions[kind_word] = cap
            chip = QPushButton(word, box)
            chip.setObjectName("contactChip")
            chip.setProperty("state", "off")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda _=False, n=device_name, p=pair: self._on_contact_chip(n, p))
            chains = _KIND_CHAIN_WORDS[_contact.PAIR_KIND[pair]]
            self._explain(
                chip, title,
                f"Whether this toy feels {what}. One click sets it on every "
                f"{chains} chain of the toy, in the active mode.<br><br>"
                "<b>Half lit</b> while those chains disagree; a click then "
                "turns it on for all of them. <b>Greyed</b> when no chain of "
                "the toy hears this kind of contact. Each chain has the same "
                "four switches in its <b>Input</b> stage.")
            chips[pair] = chip
        return chips, captions

    def _chip_rows(self, data: dict) -> List[tuple]:
        """[(caption, Self chip, Others chip)] -- Touch, then Penetration."""
        caps, chips = data["chip_captions"], data["contact_chips"]
        rows = []
        for kind_word in ("Touch", "Penetration"):
            pairs = [p for p, k, *_ in _CONTACT_CHIPS if k == kind_word]
            rows.append((caps[kind_word], chips[pairs[0]], chips[pairs[1]]))
        return rows

    def _arrange_contact_chips(self, data: dict, two_rows: bool) -> None:
        """Touch above Penetration, the captions in a column of their own
        (two_rows), or all six on one line. Moves them inside their own
        grid, so none of them is re-parented."""
        grid = data["chips_box"].layout()
        rows = self._chip_rows(data)
        for row in rows:
            for w in row:
                grid.removeWidget(w)
        for r, row in enumerate(rows):
            for c, w in enumerate(row):
                at_r, at_c = (r, c) if two_rows else (0, 3 * r + c)
                grid.addWidget(w, at_r, at_c, Qt.AlignLeft | Qt.AlignVCenter)
        # the line's Penetration keeps a little more room from Touch's chips
        rows[1][0].setContentsMargins(0 if two_rows else 4, 0, 0, 0)
        self._arrange_safety_chips(data, two_rows)

    def _chips_width(self, data: dict, two_rows: bool) -> int:
        """How wide the chips' block is, as two rows or as one line."""
        sp = data["chips_box"].layout().horizontalSpacing()
        # without the gap the one-line arrangement gives a caption, so the
        # answer doesn't depend on the arrangement shown now (it would flip)
        rows = [[_layout_width(w) - w.contentsMargins().left() for w in row]
                for row in self._chip_rows(data)]
        if two_rows:
            return sum(max(col) for col in zip(*rows)) + 2 * sp
        return sum(sum(r) for r in rows) + 5 * sp + 4

    # ----------------------------------------------------------
    # A toy's own Sleep and Anti-stuck (Blise's ask, 2026-11-17)
    # ----------------------------------------------------------

    def _build_safety_chips(self, device_name: str, box: QWidget) -> Dict[str, QPushButton]:
        """The toy bar's Sleep and Anti-stuck chips, in `box`'s grid: Sleep
        over Anti-stuck beside the Touch / Penetration chips, side by side
        when those are on one line (_arrange_safety_chips).
        _paint_safety_chips paints them; a click switches the toy's own."""
        grid = QGridLayout(box)
        # a little more room from the contact chips than between them
        grid.setContentsMargins(6, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        chips: Dict[str, QPushButton] = {}
        for key, word in (("sleep", "Sleep"), ("antistuck", "Anti-stuck")):
            chip = QPushButton(word, box)
            chip.setObjectName("contactChip")
            chip.setProperty("state", "off")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda _=False, n=device_name, k=key: self._on_safety_chip(n, k))
            chips[key] = chip
        self._explain(
            chips["sleep"], "Sleep (this toy)",
            "Puts just this toy to sleep: nothing from your avatar's "
            "contacts plays on it until three full strokes land within six "
            "seconds, so a brush against a sleeping partner does nothing. "
            "After 45 seconds without a stroke it sleeps again. Your own "
            "Wake settings are untouched.<br><br>"
            "<b>Lit</b> while it sleeps. <b>Lit and greyed</b> while the "
            "sidebar's <b>Sleep</b> has every toy asleep. Not remembered when "
            "you restart OGP, like Mute. Friends' drives still reach it.")
        self._explain(
            chips["antistuck"], "Anti-stuck (this toy)",
            "Whether anti-stuck watches this toy. On by default: a contact "
            "that freezes (you swap avatar, your partner leaves, the link "
            "drops) stops it instead of keeping it going. Switch it off for "
            "a toy that should keep playing a value that sits still.<br><br>"
            "<b>Greyed</b> while anti-stuck is off for every toy (on the Toys "
            "page, under Toy server, with its timers). Remembered, the same "
            "in every mode.")
        return chips

    def _arrange_safety_chips(self, data: dict, two_rows: bool) -> None:
        """Sleep over Anti-stuck (two_rows), or side by side."""
        chips = data.get("safety_chips")
        if not chips:
            return
        grid = data["safety_box"].layout()
        for chip in chips.values():
            grid.removeWidget(chip)
        for i, chip in enumerate(chips.values()):
            row, col = (i, 0) if two_rows else (0, i)
            grid.addWidget(chip, row, col, Qt.AlignLeft | Qt.AlignVCenter)

    def _safety_width(self, data: dict, two_rows: bool) -> int:
        """How wide Sleep and Anti-stuck are, stacked or side by side --
        the same answer whichever is shown now."""
        chips = data.get("safety_chips") or {}
        box = data.get("safety_box")
        if not chips or box is None:
            return 0
        widths = [_layout_width(c) for c in chips.values()]
        lay = box.layout()
        left = lay.contentsMargins().left()
        if two_rows:
            return max(widths) + left
        return sum(widths) + lay.horizontalSpacing() * (len(widths) - 1) + left

    def _safety_looks(self, device_name: str) -> Optional[Dict[str, tuple]]:
        """{chip: (enabled, state)} for a toy's Sleep and Anti-stuck: Sleep
        lit while it sleeps, lit and greyed ("held") while the sidebar's
        Sleep has every toy asleep; Anti-stuck lit while on, greyed while
        the toys' anti-stuck is off. None without a controller for them."""
        c = self.controller
        try:
            everyone = bool(c.is_sleep_active())
            own_sleep = bool(c.is_toy_sleep_on(device_name))
            kind_on = bool(c.get_toys_antistuck().get("enabled", True))
            own_as = bool(c.is_toy_antistuck_on(device_name))
        except AttributeError:
            return None
        return {"sleep": (not everyone,
                          "held" if everyone else ("on" if own_sleep else "off")),
                "antistuck": (kind_on, "on" if (own_as and kind_on) else "off")}

    def _paint_safety_bar(self, device_name: str, bar: dict) -> None:
        looks = self._safety_looks(device_name)
        if looks is None:
            return
        for key, chip in (bar.get("safety_chips") or {}).items():
            enabled, state = looks[key]
            try:
                if chip.isEnabled() != enabled:
                    chip.setEnabled(enabled)
                if chip.property("state") != state:
                    chip.setProperty("state", state)
                    self._repolish(chip)
            except RuntimeError:
                pass                    # torn down meanwhile

    def _paint_safety_chips(self, device_name: str, data: Optional[dict] = None) -> None:
        """Paint a toy's Sleep and Anti-stuck chips on its card and its Home
        row. Change-gated (rides the pages' 2 Hz refresh)."""
        data = data if data is not None else self.device_ui_frames.get(device_name)
        for bar in self._toy_bars(data):
            self._paint_safety_bar(device_name, bar)

    def _refresh_safety_chips(self) -> None:
        """Every toy's Sleep and Anti-stuck chips, both bars (the sidebar's
        Sleep or the toys' anti-stuck just changed)."""
        for device_name, data in list(getattr(self, "device_ui_frames", {}).items()):
            self._paint_safety_chips(device_name, data)

    def _on_safety_chip(self, device_name: str, key: str) -> None:
        """A click on Sleep or Anti-stuck: the toy's own switch flips."""
        c = self.controller
        if key == "sleep":
            c.set_toy_sleep(device_name, not c.is_toy_sleep_on(device_name))
        else:
            c.set_toy_antistuck(device_name, not c.is_toy_antistuck_on(device_name))
        self._paint_safety_chips(device_name)

    def _toy_contact_values(self, device_name: str, motor_count: int
                            ) -> Dict[str, List[tuple]]:
        """For each pair: `(motor, chain, on)` for every chain of the toy
        that answers it, read the way the router reads it (the chain's own
        key, the motor's, the default). A typed chain answers only its own
        kind's pairs."""
        get = lambda key, default, n=device_name: \
            self.controller.get_profile_config(n, key, default)
        out: Dict[str, List[tuple]] = {p: [] for p in _contact.PAIRS}
        for motor in range(max(int(motor_count), 0)):
            try:
                chains = _get_chain_count(self.controller, device_name, motor)
            except Exception:
                chains = 1
            for chain in range(chains):
                ctype = _get_chain_type(self.controller, device_name, motor, chain)
                for pair in _contact.pairs_for_type(ctype):
                    out[pair].append(
                        (motor, chain,
                         _contact.resolve(get, motor, chain, pair)))
        return out

    def _refresh_contact_chips(self, device_name: str,
                               data: Optional[dict] = None) -> None:
        """Paint a toy's four chips -- on its card and on its Home row: on,
        off, half lit while its chains disagree, greyed when none answers.
        Change-gated (it rides the pages' 2 Hz refresh)."""
        data = data if data is not None else self.device_ui_frames.get(device_name)
        if not (data or {}).get("contact_chips"):
            return
        values = self._toy_contact_values(
            device_name, len(data.get("motors", ())))
        states = {pair: _contact.chip_state(on for _m, _c, on in values[pair])
                  for pair in values}
        for bar in self._toy_bars(data):
            for pair, chip in (bar.get("contact_chips") or {}).items():
                state = states.get(pair)
                enabled = state is not None
                if chip.isEnabled() != enabled:
                    chip.setEnabled(enabled)
                painted = state or "off"
                if chip.property("state") != painted:
                    chip.setProperty("state", painted)
                    self._repolish(chip)

    def _on_contact_chip(self, device_name: str, pair: str) -> None:
        """A chip click: every chain of the toy that answers this pair gets
        the same value in the active mode -- on, unless all of them already
        were (so a half-lit chip turns all on)."""
        data = self.device_ui_frames.get(device_name) or {}
        values = self._toy_contact_values(
            device_name, len(data.get("motors", ())))[pair]
        if not values:
            return
        state = _contact.chip_state(on for _m, _c, on in values)
        new = state != "on"
        for motor, chain, _on in values:
            self.controller.update_device_config(
                device_name, _contact.key(motor, chain, pair), new)
        self.controller.save_profiles()
        if hasattr(self.controller, "force_recalculate"):
            self.controller.force_recalculate()
        targets = {(m, c) for m, c, _on in values}
        for motor, chain, sw_pair, sw in self._live_contact_switches(device_name):
            if sw_pair == pair and (motor, chain) in targets \
                    and sw.isChecked() != new:
                sw.blockSignals(True)
                sw.setChecked(new)
                sw.blockSignals(False)
                sw.update()
        self._refresh_contact_chips(device_name)

    def _register_contact_switch(self, device_name: str, motor_idx: int,
                                 chain_idx, pair: str, switch) -> None:
        """Remember an Input stage's contact switch, so a chip click on the
        toy's bar moves it too while that stage is open."""
        live = self._live_contact_switches(device_name)
        live.append((motor_idx, chain_idx, pair, switch))
        self._contact_switch_reg[device_name] = live

    def _live_contact_switches(self, device_name: str) -> List[tuple]:
        """The registered switches of a toy that still exist (an Input
        stage's editor is rebuilt on every open; the old ones drop out)."""
        reg = getattr(self, "_contact_switch_reg", None)
        if reg is None:
            reg = self._contact_switch_reg = {}
        live = [e for e in reg.get(device_name, ()) if shiboken6.isValid(e[3])]
        reg[device_name] = live
        return live

    def _toy_bar_lines(self, data: dict, mode: str) -> tuple:
        """The widgets on each of the bar's three lines in `mode`, in
        order; None is the line's stretch."""
        icon, dot, name = data["icon_button"], data["connect_dot"], data["name_label"]
        zones, chips = data["zones_label"], data["chips_box"]
        safety = data.get("safety_box")
        chips = [chips, safety] if safety is not None else [chips]
        status = [data["offline_pill"], data["battery_label"], data["mini_bar_strip"]]
        acts = [data["mute_button"], data["test_button"], data["caret"]]
        if mode == _BAR_WIDE:
            return [icon, dot, name, zones] + chips + [None] + status + acts, [], []
        if mode == _BAR_TWO:
            return [icon, dot, name, None] + status + acts, [zones] + chips + [None], []
        return [icon, dot, name, None] + acts, status + [None], [zones] + chips + [None]

    def _arrange_toy_bar(self, data: dict, mode: str, two_rows: bool) -> None:
        """Put the bar's widgets on its lines for `mode` (and the chips in
        two rows or one). Every widget stays the bar's child -- the lines
        are layouts inside its layout -- so nothing is re-parented or
        re-shown; a layout is only touched when the arrangement changed."""
        if data.get("bar_mode") == (mode, two_rows):
            return
        data["bar_mode"] = (mode, two_rows)
        lines = data["bar_lines"]
        for lay in lines:
            while lay.count():
                lay.takeAt(0)
        for lay, items in zip(lines, self._toy_bar_lines(data, mode)):
            for w in items:
                if w is None:
                    lay.addStretch(1)
                else:
                    lay.addWidget(w, 0, Qt.AlignVCenter)
        self._arrange_contact_chips(data, two_rows)

    def _toy_bar_need(self, data: dict, mode: str, two_rows: bool) -> int:
        """How wide the bar's widest line is in `mode` -- the widgets shown
        (an offline toy has no battery, meters, Mute or Test), the gaps
        between them and the indent of the lines under the name."""
        bar = data["bar"]
        need = 0
        for i, items in enumerate(self._toy_bar_lines(data, mode)):
            shown = [w for w in items if w is not None and w.isVisibleTo(bar)]
            if not shown:
                continue
            width = sum(self._chips_width(data, two_rows) if w is data["chips_box"]
                        else self._safety_width(data, two_rows) if w is data.get("safety_box")
                        else _layout_width(w) for w in shown)
            width += data["bar_line1"].spacing() * (len(shown) - 1)
            if i:
                width += self._TOY_BAR_INDENT
            need = max(need, width)
        return need

    def _fit_toy_bar(self, data: dict) -> None:
        """Arrange the bar for the room it has: one line while everything
        fits there (the chips as two rows), else the name line with the
        chips under it (on one row, else two), else the battery and meters
        on a line of their own too (the chips in one line while that fits).
        Sleep and Anti-stuck go with the chips: stacked beside their two
        rows, side by side after their one. A pure function of the bar's
        width, so it never flips back and forth."""
        bar = data.get("bar")
        if bar is None or not data.get("bar_lines"):
            return
        try:
            margins = bar.layout().contentsMargins()
            room = bar.width() - margins.left() - margins.right()
            for mode, two_rows in _BAR_ARRANGEMENTS:
                if self._toy_bar_need(data, mode, two_rows) <= room:
                    break
            self._arrange_toy_bar(data, mode, two_rows)
        except RuntimeError:
            pass  # card torn down meanwhile

    def _apply_mute_btn_style(self, btn: QPushButton) -> None:
        """Reflect the button's checked state in its text + role."""
        muted = btn.isChecked()
        btn.setText("Muted" if muted else "Mute")
        btn.setProperty("role", "danger" if muted else "secondary")
        self._repolish(btn)

    def _show_no_battery_glyph(self, label: QLabel) -> None:
        """Reset a battery slot to the painted no-battery glyph."""
        label.setPixmap(_icon_no_battery().pixmap(20, 20))

    def _explain(self, target, title: str, text: str) -> None:
        """Hover explanation for a control, a row or a group -- see
        ui/tooltips.py. Resting the mouse on anything that has one shows
        it; help mode (F1, ui/help_mode.py) shows its title and first
        sentence when the control is pointed at."""
        _explain_target(target, title, text)

    def _build_motor_card(self, device_name: str, motor_idx: int,
                          osc_addresses: dict,
                          motor_kind: Optional[str],
                          heading: bool = False) -> "tuple[QFrame, dict]":
        """Build one motor card by instantiating MotorChainListWidget,
        which holds 1 or 2 MotorSignalChainWidget instances plus the
        +Add / Remove / Merge controls. Single-chain motors render
        the same way as Cut 1–4 (no visual change); two-chain motors
        gain a merge picker between the chain editors.

        The widget calls back into `self._build_listening_to_column`
        for the Input stage editor on each chain, so that mixin
        method stays load-bearing.

        Returns (card_widget, motor_var_dict). `motor_var["widget"]` is the
        chain widget itself (the live-meter target the rest of the UI drives
        via set_motor_value); the returned card wraps that chain widget plus
        the per-motor "mirror to VRChat parameter" output row beneath it."""
        chain_widget = _MotorChainListWidget(self, device_name, motor_idx, motor_kind,
                                             heading=heading)
        # Registry for the page-level simulator / overview bar: the top
        # bar fans one set of sim parameters out to every live wrapper,
        # and the overview target combo lists them. Pruned lazily —
        # consumers drop entries whose C++ widget is gone.
        if not hasattr(self, "_chain_wrappers"):
            self._chain_wrappers = []
        self._chain_wrappers.append((device_name, motor_idx, chain_widget))
        card = QWidget()
        card_lay = _vbox(0, 6)
        card.setLayout(card_lay)
        card_lay.addWidget(chain_widget)
        # (its "mirror to VRChat parameter" row waits in the card's
        # Avatar parameters fold, _build_toy_foot)
        return card, {"widget": chain_widget}

    # The name boxes in a toy card's Avatar parameters fold: no wider than
    # this -- a parameter name, not a sentence.
    _TOY_PARAM_EDIT_MAX = 240

    def _build_toy_foot(self, device_name: str, motor_count: int) -> tuple:
        """A toy card's last line: **Avatar parameters** -- a small fold,
        closed by default, saying how many are on -- and **Delete device**
        as words in the danger colour at its right end. The fold holds each
        motor's "Mirror to VRChat parameter" row (named by its motor when
        there are several) and "Tell VRChat while this toy is connected".
        Returns (the line's widget, its parts by name)."""
        foot = QWidget()
        foot.setObjectName("toyFoot")
        lay = _vbox(0, 6)
        foot.setLayout(lay)
        line = _hbox(0, 8)
        lay.addLayout(line)

        fold_btn = QPushButton("▸  Avatar parameters")
        fold_btn.setProperty("role", "ghost")
        fold_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        fold_btn.setCursor(Qt.PointingHandCursor)
        line.addWidget(fold_btn)
        count = QLabel("")
        count.setProperty("muted", "true")
        line.addWidget(count)
        line.addStretch(1)

        delete_button = QPushButton("Delete device")
        delete_button.setProperty("role", "dangerText")
        delete_button.setFixedHeight(BTN_HEIGHT_SMALL)
        delete_button.setCursor(Qt.PointingHandCursor)
        self._explain(
            delete_button, "Delete device",
            "Forgets this toy and everything set up for it, in every mode. "
            "If you switch it on again later it comes back as a new toy "
            "with default settings.")
        delete_button.clicked.connect(
            lambda _=False, n=device_name: self.controller.delete_stored_device(n)
        )
        line.addWidget(delete_button)

        fold = QWidget()
        fold.setObjectName("toyParams")
        fold_lay = _vbox(0, 6)
        fold_lay.setContentsMargins(12, 0, 0, 2)
        fold.setLayout(fold_lay)
        toggles = []
        for motor_idx in range(motor_count):
            row = self._build_motor_param_out_row(
                device_name, motor_idx,
                label=(f"Mirror motor {motor_idx} to VRChat parameter"
                       if motor_count > 1 else ""),
                edit_max=self._TOY_PARAM_EDIT_MAX)
            fold_lay.addWidget(row)
            toggles.append(row.findChild(ToggleSwitch))
        # This toy's own "I am connected" avatar parameter.
        getter = getattr(self.controller, "get_toy_connected_param", None)
        if callable(getter):
            enabled, param = getter(device_name)
            connected_row = self._build_connected_param_row(
                "Tell VRChat while this toy is connected", enabled, param,
                lambda on, name, n=device_name:
                    self.controller.set_toy_connected_param(n, on, name),
                "Tell VRChat while this toy is connected",
                "Sends a Bool avatar parameter that is <b>true while this "
                "toy is connected</b> and false while it isn't — so your "
                "avatar can light up, show an icon or switch something on "
                "for exactly this toy. Add a Bool with this name to your "
                "avatar's parameters; the name is yours to change, or "
                "<b>Pick…</b> one your avatar already sends.<br><br>"
                "It is the same in every mode. Two toys given the same name "
                "share the parameter: true while either is connected. "
                "Settings → Connection Settings has one more for "
                "\"any toy at all\".",
                edit_max=self._TOY_PARAM_EDIT_MAX)
            fold_lay.addWidget(connected_row)
            toggles.append(connected_row.findChild(ToggleSwitch))
        toggles = [t for t in toggles if t is not None]
        # the switches one width, so their name boxes line up
        widest = max((_layout_width(t) for t in toggles), default=0)
        for t in toggles:
            t.setMinimumWidth(widest)
        fold.setVisible(False)
        lay.addWidget(fold)

        def say_how_many(*_a) -> None:
            on = sum(1 for t in toggles if t.isChecked())
            count.setText(f"{on} on" if on else "none on")

        def set_open(is_open: bool) -> None:
            fold.setVisible(bool(is_open))
            fold_btn.setText(("▾" if is_open else "▸") + "  Avatar parameters")

        for t in toggles:
            t.toggled.connect(say_how_many)
        say_how_many()
        fold_btn.clicked.connect(lambda _=False: set_open(fold.isHidden()))
        self._explain(
            (fold_btn, count), "Avatar parameters",
            "What this toy tells your avatar - for a light, an icon or a "
            "meter on it. <b>Mirror to VRChat parameter</b> sends each "
            "motor's level as a Float; <b>Tell VRChat while this toy is "
            "connected</b> sends a Bool. Says how many are on; click to open "
            "or close.")
        return foot, {"delete_button": delete_button,
                      "params_fold": fold, "params_button": fold_btn,
                      "params_count": count, "params_open": set_open}

    def _build_motor_param_out_row(self, device_name: str,
                                   motor_idx: int, label: str = "",
                                   edit_max: int = 0) -> QWidget:
        """Compact 'mirror this motor's output to a VRChat avatar parameter'
        control. The motor's computed 0..1 value is sent back to VRChat (OSC
        out) so the same contact that drives the toy can also drive an avatar
        visual — a glow, a blendshape, a fill meter — in parallel with, or
        instead of, a physical toy. Persists the two per-motor profile keys the
        router reads via motor_param_out.resolve_param_out, mirroring the
        save + recalc pattern of the interaction-filter toggles."""
        enabled_key, address_key = param_out_keys(motor_idx)

        toggle = ToggleSwitch(label or "Mirror to VRChat parameter")
        toggle.setChecked(
            bool(self.controller.get_profile_config(device_name, enabled_key, False))
        )

        addr_edit = QLineEdit()
        addr_edit.setPlaceholderText("Avatar parameter name (e.g. TailWag)")
        addr_edit.setText(strip_param_prefix(
            self.controller.get_profile_config(device_name, address_key, "")
        ))
        addr_edit.setMinimumWidth(100)

        pick_btn = QPushButton("Pick…")
        pick_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        pick_btn.setProperty("role", "secondary")
        row = _SwitchNameRow(toggle, addr_edit, pick_btn, edit_max=edit_max)
        lay = row.layout()
        # After the whole row exists, so the toggle, the name field and
        # Pick all carry it.
        self._explain(lay,
            "Mirror to VRChat parameter",
            "Also send this motor's output value (0.0–1.0) back to VRChat as "
            "an avatar parameter, so the same contact that drives the toy can "
            "drive an avatar visual (glow, blendshape, fill meter). Works even "
            "with no toy connected. Enter the bare parameter name "
            "(e.g. <b>TailWag</b>) or <b>Pick…</b> one your avatar is "
            "sending; the /avatar/parameters/ prefix is added for you."
        )

        def persist_address():
            name = strip_param_prefix(addr_edit.text())
            if addr_edit.text() != name:
                addr_edit.blockSignals(True)
                addr_edit.setText(name)
                addr_edit.blockSignals(False)
            self.controller.update_device_config(device_name, address_key, name)
            self.controller.save_profiles()

        def on_toggle(checked):
            self.controller.update_device_config(
                device_name, enabled_key, bool(checked)
            )
            self.controller.save_profiles()
            if hasattr(self.controller, 'force_recalculate'):
                self.controller.force_recalculate()

        def on_pick(picked: str):
            addr_edit.setText(strip_param_prefix(picked))
            persist_address()

        toggle.toggled.connect(on_toggle)
        addr_edit.editingFinished.connect(persist_address)
        pick_btn.clicked.connect(
            lambda: self._open_variable_picker(on_pick, mapped=[addr_edit.text()]))

        return row

    def _build_connected_param_row(self, label: str, enabled: bool, name: str,
                                   on_change: Callable[[bool, str], None],
                                   tip_title: str, tip_text: str,
                                   stacked: bool = False,
                                   label_width: int = 0,
                                   edit_max: int = 0) -> QWidget:
        """`[switch] label   [parameter name] [Pick…]` -- one "tell VRChat
        while … is connected" setting, the same shape as the per-motor
        mirror row above. Used for each toy (its card), the whole-rig
        parameter (Settings), the suits' and their parts' (the Suits page)
        and the shockers' (the Shockers page: the hub card, each shocker's
        card). `stacked` puts the name and Pick… on a line under the switch,
        for a narrow card; `label_width` gives the switches of a card's rows
        one width, so their name boxes line up. `on_change(enabled, bare
        name)` fires on every committed change; the row never sends anything
        itself."""
        toggle = ToggleSwitch(label)
        toggle.setChecked(bool(enabled))
        if label_width:
            toggle.setMinimumWidth(label_width)

        edit = QLineEdit()
        edit.setPlaceholderText("Avatar parameter name")
        edit.setText(strip_param_prefix(name))
        edit.setMinimumWidth(100)

        pick_btn = QPushButton("Pick…")
        pick_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        pick_btn.setProperty("role", "secondary")
        if stacked:
            row = QWidget()
            lay = _vbox(0, 4)
            row.setLayout(lay)
            lay.addWidget(toggle)
            line = _hbox(0, 6)
            line.addWidget(edit, 1)
            line.addWidget(pick_btn)
            lay.addLayout(line)
        else:
            # one line while it fits, the name box under the switch when not
            row = _SwitchNameRow(toggle, edit, pick_btn, edit_max=edit_max)
            lay = row.layout()
        self._explain(lay, tip_title, tip_text)

        def commit(*_a) -> None:
            bare = strip_param_prefix(edit.text())
            if edit.text() != bare:
                edit.blockSignals(True)
                edit.setText(bare)
                edit.blockSignals(False)
            on_change(bool(toggle.isChecked()), bare)

        def on_pick(picked: str) -> None:
            edit.setText(strip_param_prefix(picked))
            commit()

        toggle.toggled.connect(commit)
        edit.editingFinished.connect(commit)
        pick_btn.clicked.connect(
            lambda: self._open_variable_picker(on_pick, mapped=[edit.text()]))
        return row

    def _build_listening_to_column(self, device_name: str, motor_idx: int,
                                   osc_addresses: dict,
                                   chain_idx=None,
                                   chain_type: str = "") -> QWidget:
        """Zone selector + collapsible zone panel, OSC address chips,
        interaction filter toggles.

        With `chain_idx` set, the zone selection and the interaction
        filters are read and written PER CHAIN (`motor_0_c1_zones`), so a
        Touch chain and a Penetration chain on one motor can watch
        different zones and different contact. Reads fall back to the
        motor-level key when the chain has no opinion yet, matching the
        router, so the panel shows what is actually in effect rather than
        a blank. `chain_type` greys the other kind's row of the contact
        2x2 for a typed chain, which hears only its own kind.

        Reads/writes the same profile keys
        as before."""
        col = QWidget()
        col_lay = _vbox(0, 8)
        col.setLayout(col_lay)

        header_row = QWidget()
        header_lay = _hbox(0, 6)
        header_row.setLayout(header_lay)
        header = QLabel("LISTENING TO")
        header.setObjectName("columnHeader")
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        header_lay.addWidget(header)
        self._explain(header_lay,
            "Listening To",
            "What this motor reacts to: detected zones, specific OSC "
            "parameter addresses, and who it hears (touch or penetration, "
            "from yourself or from others).<br><br>"
            "<b>This is the one part of the chain that belongs to the "
            "active mode.</b> Editing it re-wires this motor in that mode "
            "only — that's what makes a mode a routing. Everything else on "
            "the chain (the shaping stages and the output trim) is shared "
            "by every mode."
        )
        header_lay.addStretch(1)
        col_lay.addWidget(header_row)

        _MISSING = object()

        def chain_key(suffix: str) -> str:
            """The key a write lands on: per-chain when we have one."""
            if chain_idx is None:
                return f"motor_{motor_idx}_{suffix}"
            return f"motor_{motor_idx}_c{int(chain_idx)}_{suffix}"

        def chain_read(suffix: str, default):
            """Per-chain value, falling back to the motor's — the same
            resolution the router does, so the panel never shows a
            setting the chain isn't actually running on."""
            if chain_idx is not None:
                val = self.controller.get_profile_config(
                    device_name, chain_key(suffix), _MISSING)
                if val is not _MISSING:
                    return val
            return self.controller.get_profile_config(
                device_name, f"motor_{motor_idx}_{suffix}", default)

        current_zones = chain_read("zones", "All SPS")
        zones_state = {"value": current_zones, "expanded": False}

        def zone_btn_text(value: str) -> str:
            parts = [z.strip() for z in value.split(",") if z.strip() and z.strip() != "None"]
            all_sps = "All SPS" in parts
            count = len([z for z in parts if z != "All SPS"])
            if all_sps and count:
                return f"Select Zones (All SPS · {count} saved)"
            if all_sps:
                return "Select Zones (All SPS)"
            if count:
                return f"Select Zones ({count} enabled)"
            return "Select Zones..."

        zone_row = QWidget()
        zone_row_lay = _hbox(0, 6)
        zone_row.setLayout(zone_row_lay)
        zone_btn = QPushButton(zone_btn_text(zones_state["value"]))
        zone_btn.setProperty("role", "secondary")
        zone_row_lay.addWidget(zone_btn, 1)
        self._explain(zone_row_lay,
            "Zone selector",
            "Which OGB zones drive this motor. <b>All SPS</b> matches "
            "any detected zone; individual toggles bind to specific "
            "orifices, penetrators or touch zones."
        )
        col_lay.addWidget(zone_row)

        zone_panel = QFrame()
        zone_panel.setObjectName("zonePanel")
        zone_panel_lay = _vbox(8, 4)
        zone_panel.setLayout(zone_panel_lay)
        zone_panel.setVisible(False)
        # Named for the guided tour's "Pick your zones" (ui/tour_steps.py)
        # and help mode; its switches have no tip of their own, so theirs.
        self._explain(zone_panel,
            "Your SPS sources",
            "The parts of your avatar that drive this chain. <b>All SPS</b> "
            "hears every SPS zone your avatar has; or switch on just the ones "
            "you want - the zones VRChat reports for the avatar you wear, and "
            "the ones you built under SPS Sources below the toys.")
        col_lay.addWidget(zone_panel)

        def build_zone_panel(dn=device_name, midx=motor_idx, state=zones_state,
                             btn=zone_btn, panel=zone_panel, panel_lay=zone_panel_lay):
            _clear_layout(panel_lay)

            detected = self.controller.get_detected_zones()
            # Dedupe across the type buckets: the picker stores bare names,
            # so one name detected as two types must render ONE toggle (two
            # would desync — both write the same motor_N_zones entry).
            seen = set()
            fresh_zones = []
            for bucket in ("Orifices", "Penetrators", "Touch"):
                for name in detected.get(bucket, []):
                    if name not in seen:
                        seen.add(name)
                        fresh_zones.append(name)

            try:
                custom_sources = list(self.controller.get_sps_source_names_flat() or [])
            except Exception:
                custom_sources = []

            if not fresh_zones and not custom_sources:
                lbl = QLabel(
                    "No zones detected yet.\n"
                    "Make sure VRChat is running and avatar loaded.\n"
                    "(Or build your own under SPS Sources, below the toys.)"
                )
                lbl.setProperty("role", "alert")
                panel_lay.addWidget(lbl)
                return

            current_selected = [z.strip() for z in state["value"].split(",") if z.strip()]

            def persist(new_val: str):
                state["value"] = new_val
                self.controller.update_device_config(dn, chain_key("zones"), new_val)
                self.controller.save_profiles()
                if hasattr(self.controller, 'force_recalculate'):
                    self.controller.force_recalculate()
                btn.setText(zone_btn_text(new_val) + (" ▲" if state["expanded"] else ""))

            # All SPS is an additive override — toggling it on/off never
            # touches the individual zone selections.
            all_sps_cb = ToggleSwitch("All SPS (match any zone — overrides selections below)")
            all_sps_cb.setChecked("All SPS" in current_selected)

            def on_all_sps(checked):
                sel = [z.strip() for z in state["value"].split(",") if z.strip()]
                sel = [z for z in sel if z != "All SPS"]
                if checked:
                    sel.insert(0, "All SPS")
                persist(", ".join(sel))

            all_sps_cb.toggled.connect(on_all_sps)
            panel_lay.addWidget(all_sps_cb)

            def make_toggle(zone):
                def _toggle(checked):
                    sel = [z.strip() for z in state["value"].split(",") if z.strip()]
                    if checked:
                        if zone not in sel and zone != "None":
                            sel.append(zone)
                    else:
                        if zone in sel:
                            sel.remove(zone)
                    persist(", ".join(sel))
                return _toggle

            if fresh_zones:
                sep_lbl = QLabel("─── Detected Zones ───")
                sep_lbl.setProperty("muted", "true")
                sep_lbl.setAlignment(Qt.AlignHCenter)
                self._repolish(sep_lbl)
                panel_lay.addWidget(sep_lbl)

                for zone in fresh_zones:
                    if zone == "None":
                        continue
                    cb = ToggleSwitch(zone)
                    cb.setChecked(zone in current_selected)
                    cb.toggled.connect(make_toggle(zone))
                    panel_lay.addWidget(cb)

            # Synthetic SPS sources (built under SPS Sources on the Toys page). Selecting
            # one writes its name into motor_X_zones exactly like a detected
            # zone; the router resolves the name against the source map.
            if custom_sources:
                csep = QLabel("─── Custom Sources ───")
                csep.setProperty("muted", "true")
                csep.setAlignment(Qt.AlignHCenter)
                self._repolish(csep)
                panel_lay.addWidget(csep)

                for zone in custom_sources:
                    cb = ToggleSwitch(zone)
                    cb.setChecked(zone in current_selected)
                    cb.toggled.connect(make_toggle(zone))
                    panel_lay.addWidget(cb)

        def toggle_zone_panel(state=zones_state, btn=zone_btn, panel=zone_panel,
                              build=build_zone_panel):
            state["expanded"] = not state["expanded"]
            if state["expanded"]:
                build()
                panel.setVisible(True)
                btn.setText(zone_btn_text(state["value"]) + " ▲")
            else:
                panel.setVisible(False)
                btn.setText(zone_btn_text(state["value"]))

        zone_btn.clicked.connect(
            lambda _=False, tog=toggle_zone_panel: tog()
        )

        # Custom OSC addresses (chips + Add Variable).
        raw_entry = osc_addresses.get(str(motor_idx), [])
        if isinstance(raw_entry, str):
            addresses_list = [raw_entry] if raw_entry.strip() else []
        elif isinstance(raw_entry, list):
            addresses_list = [a for a in raw_entry if isinstance(a, str)]
        else:
            addresses_list = []
        self._setup_motor_address_row(col_lay, device_name, motor_idx, addresses_list)

        # Who it hears: the 2x2 -- Touch / Penetration x Self / Others
        # (contact_filters), the same four as the chips on the toy's bar.
        # A typed chain hears only its own kind, so the other row is
        # greyed: still stored (it takes over if the chain becomes
        # Custom), it plays no part.
        filter_row = QWidget()
        filter_row.setObjectName("contactFilters")
        grid = QGridLayout(filter_row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        kinds = _contact.kinds_for_type(chain_type)
        explained = [filter_row]

        def on_pair(checked, pair):
            self.controller.update_device_config(
                device_name, chain_key(pair), bool(checked))
            self.controller.save_profiles()
            if hasattr(self.controller, 'force_recalculate'):
                self.controller.force_recalculate()
            self._refresh_contact_chips(device_name)

        rows = ((_contact.KIND_TOUCH, "Touch"),
                (_contact.KIND_PENETRATION, "Penetration"))
        for r, (kind, label) in enumerate(rows):
            live = kind in kinds
            row_lbl = QLabel(label)
            if not live:
                row_lbl.setProperty("muted", "true")
                self._repolish(row_lbl)
            grid.addWidget(row_lbl, r, 0)
            explained.append(row_lbl)
            for c, pair in enumerate(_contact.KIND_PAIRS[kind]):
                sw = ToggleSwitch("Self" if c == 0 else "Others")
                sw.setObjectName(f"contact_{pair}")
                sw.setChecked(bool(chain_read(pair, _contact.DEFAULTS[pair])))
                sw.setEnabled(live)
                sw.toggled.connect(lambda checked, p=pair: on_pair(checked, p))
                grid.addWidget(sw, r, c + 1)
                explained.append(sw)
                self._register_contact_switch(
                    device_name, motor_idx, chain_idx, pair, sw)
        grid.setColumnStretch(3, 1)
        typed_note = ""
        if len(kinds) == 1:
            own = "Touch" if kinds[0] == _contact.KIND_TOUCH else "Penetration"
            other = "Penetration" if own == "Touch" else "Touch"
            typed_note = (
                f"<br><br>This is a <b>{own}</b> chain, so only its "
                f"{own} row counts; the {other} row is greyed and kept for "
                "if you make the chain Custom.")
        self._explain(
            explained, "Who it hears",
            "Which contact reaches this chain: touch or penetration, from "
            "yourself or from others. <b>Self</b> is your own body -- your "
            "hands, your own plug; <b>Others</b> is everyone else. Each of "
            "the four is its own switch, so a chain can take touch from you "
            "but penetration only from others.<br><br>"
            "The toy's bar - here and on Home - has the same four as chips, "
            "which set every chain of the toy at once. Like the zones, they "
            "belong to the active mode." + typed_note)
        col_lay.addWidget(filter_row)

        return col

    # Mix-column and linear-output-row builders removed in Cut 3 —
    # MotorSignalChainWidget now owns both surfaces. See
    # docs/MOTOR_SIGNAL_CHAIN.md § "Per-stage details" for the new layout.

    # ----------------------------------------------------------
    # Lovense product icon (auto-detect + manual override)
    # ----------------------------------------------------------

    def _apply_lovense_icon(self, device_name: str, button: "QToolButton") -> None:
        """Refresh the icon button to reflect current override / auto-detect state."""
        override = self.controller.get_profile_config(device_name, "icon_override", None)
        key = _lovense_icons.resolve_key(device_name, override)
        pixmap = _lovense_icons.load_pixmap(key, size=32, circular=True) if key else None
        if pixmap is not None:
            button.setIcon(QIcon(pixmap))
            button.setIconSize(QSize(_TOY_ICON_PX, _TOY_ICON_PX))
            tip = f"{_lovense_icons.display_name(key)} — click to change"
        else:
            button.setIcon(QIcon())
            button.setText("?")
            tip = "No icon — click to pick one"
        button.setToolTip(tip)

    def _on_lovense_icon_clicked(self, device_name: str, button: "QToolButton") -> None:
        current_override = self.controller.get_profile_config(
            device_name, "icon_override", None
        )
        result = _lovense_icons.pick_icon((getattr(self, "dialog_parent", None) or self.window), device_name, current_override)
        if result is _lovense_icons.PICK_CANCELLED:
            return
        # PICK_AUTO  -> None ; PICK_NONE -> "" ; "<key>" -> "<key>"
        self.controller.update_device_config(device_name, "icon_override", result)
        if hasattr(self.controller, "save_profiles"):
            self.controller.save_profiles()
        self._apply_lovense_icon(device_name, button)
        # its other bar (the card's, or Home's row) shows the new one too
        for bar in self._toy_bars(self.device_ui_frames.get(device_name)):
            other = bar.get("icon_button")
            if other is not None and other is not button:
                self._apply_lovense_icon(device_name, other)

    def _make_segmented(self, options: List[str], current: str,
                        on_change: Callable[[str], None]) -> QWidget:
        """Two-or-three-button segmented control."""
        host = QWidget()
        h = _hbox(0, 2)
        host.setLayout(h)
        group = QButtonGroup(host)
        group.setExclusive(True)

        def apply_styles():
            for btn in group.buttons():
                btn.setProperty("role", "segActive" if btn.isChecked() else "segIdle")
                self._repolish(btn)

        def on_clicked(btn):
            apply_styles()
            on_change(btn.text())

        for opt in options:
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setFixedHeight(24)
            b.setChecked(opt == current)
            group.addButton(b)
            h.addWidget(b)
        apply_styles()
        group.buttonClicked.connect(on_clicked)
        return host

    # The Phase 2 mix subcard and its helpers (_build_mix_subcard,
    # _build_mix_channel_card, _build_depth_more_knobs,
    # _build_speed_more_knobs, _get_mix_field, _update_mix_field,
    # _reset_mix_to_defaults) lived here. Cut 4 removed them — Device
    # Routing now embeds ui/motor_signal_chain.py's
    # MotorSignalChainWidget, which owns its own storage round-trip
    # against the chains-list schema from Cut 1.

    # ----------------------------------------------------------
    # Custom OSC address row (per motor)
    # ----------------------------------------------------------

    def _setup_motor_address_row(self, parent_layout: QVBoxLayout,
                                 device_name: str, motor_idx: int,
                                 addresses_list: list):
        container = QWidget()
        clay = _vbox(0, 4)
        container.setLayout(clay)

        chips_host = QWidget()
        chips_lay = _vbox(0, 2)
        chips_host.setLayout(chips_lay)
        clay.addWidget(chips_host)

        def persist():
            current = self.controller.get_profile_config(
                device_name, "osc_addresses", {}
            ) or {}
            if not isinstance(current, dict):
                current = {}
            current[str(motor_idx)] = list(addresses_list)
            self.controller.update_device_config(device_name, "osc_addresses", current)
            self.controller.save_profiles()
            if hasattr(self.controller, 'force_recalculate'):
                self.controller.force_recalculate()

        def render():
            _clear_layout(chips_lay)
            if not addresses_list:
                empty = QLabel(
                    "No addresses — click 'Add Variable' to map an OSC parameter."
                )
                empty.setProperty("muted", "true")
                self._repolish(empty)
                chips_lay.addWidget(empty)
                return
            for i, addr in enumerate(list(addresses_list)):
                chip = QFrame()
                chip.setObjectName("chip")
                ch_lay = _hbox(8, 4)
                chip.setLayout(ch_lay)
                lbl = QLabel(addr)
                ch_lay.addWidget(lbl, 1)
                rm = QPushButton("×")
                rm.setFixedSize(22, 20)
                rm.setProperty("role", "chipClose")
                rm.clicked.connect(
                    lambda _=False, idx=i: self._remove_motor_address(
                        addresses_list, idx, render, persist
                    )
                )
                ch_lay.addWidget(rm)
                chips_lay.addWidget(chip)

        def add_address(new_addr: str):
            cleaned = strip_param_prefix(new_addr)
            if not cleaned or cleaned in addresses_list:
                return
            addresses_list.append(cleaned)
            render()
            persist()

        add_btn = QPushButton("+ Add Variable")
        add_btn.setFixedHeight(BTN_HEIGHT_SMALL)
        add_btn.setProperty("role", "secondary")
        add_btn.clicked.connect(
            lambda: self._open_variable_picker(add_address, mapped=list(addresses_list)))
        clay.addWidget(add_btn)

        render()
        parent_layout.addWidget(container)

    @staticmethod
    def _remove_motor_address(lst, idx, render, persist):
        if 0 <= idx < len(lst):
            lst.pop(idx)
            render()
            persist()

    # ----------------------------------------------------------
    # Variable picker dialog
    # ----------------------------------------------------------

    def _open_variable_picker(self, on_pick: Callable[[str], None], mapped=()):
        """Thin wrapper over the shared OSC variable picker
        (ui/osc_variable_picker.py). `mapped`: what the row already maps,
        never hidden by the picker's filters."""
        open_osc_variable_picker((getattr(self, "dialog_parent", None) or self.window), on_pick,
                                 mapped=mapped, settings=self.controller)

    def _muted_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("muted", "true")
        # Word-wrap is critical — without it, long description blocks force
        # the page's minimum width to fit the full single-line text, which
        # prevents the window from shrinking and clips titles on narrow views.
        lbl.setWordWrap(True)
        self._repolish(lbl)
        return lbl

    # ----------------------------------------------------------
    # Stored / discovered device list builders
    # ----------------------------------------------------------

    def build_stored_devices_ui(self):
        controller = self.controller

        connected_names = controller.get_connected_device_names()
        # The controller returns the merged per-device map: the shared
        # wiring (toys, OSC addresses, zones, filters) overlaid with the
        # active mode's per-motor mix.
        active_profile = controller.get_active_profile_dict() or {}
        has_saved_devices = bool(active_profile)

        # If no saved devices and we already have frames (from build_device_list_ui),
        # don't clear — just refresh status.
        if not has_saved_devices and self.device_ui_frames:
            self.update_stored_devices_ui()
            return

        # Clear EVERYTHING from both lists -- the Toys page's cards and
        # Home's rows, widgets AND spacers -- then add back exactly one
        # trailing stretch each. Skipping spacers here leaked one stretch
        # per rebuild (mode switches rebuild constantly from the VR menu),
        # and since cards insert before the LAST spacer, the leaked ones
        # accumulated ABOVE the cards, sinking them toward the bottom of the
        # scroll area.
        lists = self._toy_list_layouts()
        # Rows another view keeps in Home's list (_reorder_device_frames)
        # are its own: taken out here, placed again below.
        extras = getattr(self, "_toy_list_extras", ())
        for lay in lists:
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget() if item is not None else None
                if w is not None:
                    # Hide before detaching: a still-visible child reparented
                    # to None briefly realises as a top-level window (a flash).
                    w.hide()
                    if w in extras:
                        continue
                    w.setParent(None)
                    w.deleteLater()
            lay.addStretch(1)

        self.stored_device_frames.clear()
        self.device_ui_frames.clear()

        if not has_saved_devices:
            for lay in lists:
                placeholder = QLabel(
                    "No toys yet — switch one on and it shows up here by "
                    "itself. It stays listed after that, even while it's off.")
                placeholder.setProperty("muted", "true")
                placeholder.setAlignment(Qt.AlignHCenter)
                self._repolish(placeholder)
                self._style_root(placeholder)
                lay.insertWidget(0, placeholder)
            self._reorder_device_frames()
            return

        device_motor_counts = controller.get_device_motor_counts()
        all_devices = list(active_profile.keys())
        all_devices.sort(key=lambda name: (name not in connected_names, name.lower()))

        for device_name in all_devices:
            config = active_profile[device_name]
            is_connected = device_name in connected_names

            stored_motor_count = device_motor_counts.get(
                device_name, config.get("motor_count", 1)
            )

            osc_addresses = config.get("osc_addresses", {})
            if not osc_addresses and config.get("osc_address"):
                osc_addresses["0"] = [config.get("osc_address")]

            stored_motor_kinds = config.get("motor_kinds")

            frame_data = self._create_device_frame(
                device_name=device_name,
                is_connected=is_connected,
                osc_addresses=osc_addresses,
                motor_count=stored_motor_count,
                motor_kinds=stored_motor_kinds,
            )
            self.device_ui_frames[device_name] = frame_data

            if hasattr(controller, 'update_device_target'):
                controller.update_device_target(device_name, 0.0, -1)

            self.stored_device_frames[device_name] = {
                "frame": frame_data["frame"],
                "status_label": frame_data["status_label"],
                "delete_button": frame_data["delete_button"],
            }
        self._reorder_device_frames()

    def build_device_list_ui(self, devices_dict: dict):
        # Device set changed — the wrapper registry the page-level
        # simulator/overview bar fans out to is about to be repopulated;
        # reset it so dead widgets don't linger, and refresh the overview
        # target combo afterwards (end of this method).
        self._chain_wrappers = []
        # Refresh the connected-name cache the motor
        # meters read on the routing tick.
        try:
            self._connected_names_cache = frozenset(
                self.controller.get_connected_device_names())
        except Exception:
            pass
        controller = self.controller
        if not devices_dict:
            return

        device_motor_counts = controller.get_device_motor_counts()

        for index, device_info in devices_dict.items():
            if isinstance(device_info, dict):
                device_name = device_info.get("name", f"Device_{index}")
                motor_count = device_info.get("motor_count", 1)
            else:
                device_name = str(device_info)
                motor_count = 1

            actual_motor_count = device_motor_counts.get(device_name, motor_count)

            if device_name not in self.device_ui_frames:
                osc_addresses = {}
                for i in range(actual_motor_count):
                    suffix = f"_{i}" if actual_motor_count > 1 else ""
                    osc_addresses[str(i)] = [f"{device_name.replace(' ', '_')}{suffix}"]

                controller.update_device_config(device_name, "motor_count", motor_count)

                motor_kinds = device_info.get("motor_kinds") if isinstance(device_info, dict) else None

                frame_data = self._create_device_frame(
                    device_name=device_name,
                    is_connected=True,
                    osc_addresses=osc_addresses,
                    motor_count=actual_motor_count,
                    motor_kinds=motor_kinds,
                )
                self.device_ui_frames[device_name] = frame_data

                if hasattr(controller, 'update_device_target'):
                    controller.update_device_target(device_name, 0.0, -1)

                self.stored_device_frames[device_name] = {
                    "frame": frame_data["frame"],
                    "status_label": frame_data["status_label"],
                    "delete_button": frame_data["delete_button"],
                }

        controller.log_message(f"Connected devices: {len(devices_dict)}")
        self._reorder_device_frames()
        # The signal graph's target picker lists targets from the wrapper
        # registry rebuilt above.
        if hasattr(self, "_refresh_signal_graph_targets"):
            self._refresh_signal_graph_targets()

    def _toy_list_layouts(self) -> list:
        """The two lists a toy is in: the Toys page's cards and Home's
        rows (either may not be built, on a test host)."""
        return [lay for lay in (getattr(self, "unified_devices_layout", None),
                                getattr(self, "home_list_layout", None))
                if lay is not None]

    @staticmethod
    def _place_in_order(lay, order: list, placed: set) -> None:
        """Put `order` in `lay` in that order, before its trailing stretch
        (if any) -- touching the layout only when the order changed.
        `placed`: every widget this owns there (the rest stays put above)."""
        current = []
        for i in range(lay.count()):
            item = lay.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None and w in placed:
                current.append(w)
        if current == order:
            return
        # Take every card and row out, then re-insert them in order
        # before the trailing stretch (if any).
        i = 0
        while i < lay.count():
            item = lay.itemAt(i)
            w = item.widget() if item is not None else None
            if w is not None and w in placed:
                lay.takeAt(i)
            else:
                i += 1
        at = next((j for j in range(lay.count())
                   if lay.itemAt(j) is not None
                   and lay.itemAt(j).spacerItem() is not None), lay.count())
        for w in order:
            lay.insertWidget(at, w)
            at += 1

    def _reorder_device_frames(self):
        """Put both toy lists in order -- the one place that does. The
        Toys page: the connected toys' cards, then the ones that aren't
        connected. Home: the connected toys' rows, the rows another view
        keeps right under them, the toys that aren't connected, then that
        view's rows for the bottom. The rows come from the view's
        `_toy_list_rows()` (Home's shocker / suit / headset rows,
        HomeMixin), looked up by name because this mixin comes first in the
        UI class. Anything else in a list (the "No toys yet" note) stays put
        above them. A layout is only touched when its order changed: the
        1 Hz heartbeat lands here."""
        # connected toys in the order they connected (a newcomer goes last,
        # so nobody's number or colour moves), then the offline ones by name
        get_order = getattr(self.controller, "get_connected_toys_in_order", None)
        got = get_order() if callable(get_order) else None
        live_order = (list(got) if got is not None
                      else sorted(self.controller.get_connected_device_names(), key=str.lower))
        rank = {n: i for i, n in enumerate(live_order)}
        connected_names = set(live_order)
        all_names = list(self.device_ui_frames.keys())
        all_names.sort(key=lambda name: (name not in connected_names, rank.get(name, 0),
                                         name.lower()))
        datas = [self.device_ui_frames[n] for n in all_names]
        frames = [d["frame"] for d in datas]
        live = sum(1 for n in all_names if n in connected_names)

        cards = getattr(self, "unified_devices_layout", None)
        if cards is not None:
            self._place_in_order(cards, frames, set(frames))

        home_lay = getattr(self, "home_list_layout", None)
        if home_lay is not None:
            rows = [(d.get("home") or {}).get("frame") for d in datas]
            live_rows = [r for r in rows[:live] if r is not None]
            other_rows = [r for r in rows[live:] if r is not None]
            rows_of = getattr(self, "_toy_list_rows", None)
            under_live, at_bottom = rows_of() if rows_of is not None else ((), ())
            extras = tuple(under_live) + tuple(at_bottom)
            dropped = [w for w in getattr(self, "_toy_list_extras", ()) if w not in extras]
            self._toy_list_extras = extras
            order = live_rows + list(under_live) + other_rows + list(at_bottom)
            self._place_in_order(home_lay, order, set(order).union(dropped))
            for w in dropped:
                w.hide()
            for w in extras:
                w.show()

        live_position = 0
        for name, data in zip(all_names, datas):
            # Identity hue by display position among the CONNECTED toys:
            # three stacked read as three, a fourth starts the cycle over.
            # An offline toy wears no hue at all -- a grey outline -- and
            # does not use one up. The bar carries the property too because
            # QSS attribute selectors match the widget they are on, not its
            # ancestors. Its card and its Home row wear the same.
            if name in connected_names:
                hue = _theme.toy_hue(live_position)
                live_position += 1
                number = live_position          # 1, 2, 3 ... in its corner
            else:
                hue = _theme.OFFLINE_HUE
                number = 0
            for bar_data in self._toy_bars(data):
                frame = bar_data.get("frame")
                if frame is None:
                    continue
                changed = False
                for w in (frame, bar_data.get("bar")):
                    if w is not None and w.property("hue") != hue:
                        w.setProperty("hue", hue)
                        self._repolish(w)
                        changed = True
                # the name's colour comes from the bar's hue (an ancestor
                # selector): Qt re-reads it only when the label itself is
                # polished again, so a name polished before the bar had its
                # hue kept the plain text colour
                name = bar_data.get("name_label")
                if changed and name is not None:
                    self._repolish(name)
                frame.set_hue(hue)      # the frame paints itself (ToyFrame)
                frame.set_number(number)

    # ----------------------------------------------------------
    # Programmatic value updates
    # ----------------------------------------------------------

    def _set_motor_levels(self, device_name: str, motor_idx: int, value: float):
        """Drive the per-motor MotorSignalChainWidget's vibe meter and
        the matching mini-bar in the collapsed toy bar.

        Phantom-update guard: the router still computes targets for
        every motor in the active profile, including stored-but-offline
        toys. The engine drops those values on the floor (the toy
        isn't there to receive them), but if the UI shows the meter
        moving anyway it reads as 'the toy is live' which is a lie.
        So when the device isn't currently connected, we force the
        displayed value to 0. Reads the event-refreshed cache — this
        runs per changed motor inside the routing tick, so it must not
        rebuild the connected-name set from the facade every call."""
        try:
            connected = getattr(self, "_connected_names_cache", None)
            if connected is None:
                connected = frozenset(
                    self.controller.get_connected_device_names())
                self._connected_names_cache = connected
            if device_name not in connected:
                value = 0.0
        except Exception:
            pass
        if device_name in self.device_ui_frames:
            frame_data = self.device_ui_frames[device_name]
            motors = frame_data.get("motors", [])
            mini_bars = frame_data.get("mini_bars", [])
            home = frame_data.get("home")
            home_bars = home["mini_bars"] if home else ()
            if 0 <= motor_idx < len(motors):
                widget = motors[motor_idx].get("widget")
                if widget is not None:
                    widget.set_motor_value(value)
                if 0 <= motor_idx < len(mini_bars):
                    mini_bars[motor_idx].set(value)
                if 0 <= motor_idx < len(home_bars):
                    home_bars[motor_idx].set(value)
            elif motor_idx == -1:
                for mv in motors:
                    widget = mv.get("widget")
                    if widget is not None:
                        widget.set_motor_value(value)
                for mb in mini_bars:
                    mb.set(value)
                for mb in home_bars:
                    mb.set(value)

    def update_device_visuals(self, device_name: str, motor_idx: int, value: float):
        """Programmatic motor-value update. With the legacy intensity
        slider gone this is identical to update_motor_vibe; kept distinct
        because only this path runs inside the controller's
        _is_updating_ui guard."""
        self._set_motor_levels(device_name, motor_idx, value)

    def update_motor_vibe(self, device_name: str, motor_idx: int, value: float):
        """Live mixer-output meter update — called by the router on every
        tick."""
        self._set_motor_levels(device_name, motor_idx, value)

    # --- Device frame management ---
    def remove_device_frame(self, device_name: str) -> None:
        frame_data = self.stored_device_frames.pop(device_name, None)
        home = (self.device_ui_frames.get(device_name) or {}).get("home") or {}
        for frame in ((frame_data or {}).get("frame"), home.get("frame")):
            if frame is not None:
                try:
                    frame.hide()
                    frame.setParent(None)
                    frame.deleteLater()
                except Exception:
                    pass
        self.device_ui_frames.pop(device_name, None)

    def clear_device_caches(self) -> None:
        # Also tear down the actual widgets so a fresh build_stored_devices_ui
        # call doesn't leave orphan cards (or Home rows) on screen.
        for data in list(self.device_ui_frames.values()):
            for frame in (data.get("frame"), (data.get("home") or {}).get("frame")):
                if frame is not None:
                    frame.hide()
                    frame.setParent(None)
                    frame.deleteLater()
        self.device_ui_frames.clear()
        self.stored_device_frames.clear()

    def get_known_device_names(self) -> list:
        return list(self.device_ui_frames.keys())
