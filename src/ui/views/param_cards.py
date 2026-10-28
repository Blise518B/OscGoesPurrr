"""The Avatar Remote page's board pieces -- VRC Parameter Relay's control
cards and category boxes in OGP's look: a category is a frame in its
colour with a filled header bar (drag it by its ⠿ to reorder, 🔒 makes it
look-only for friends, ⋯ for its colour, copy to another preset, delete),
a control is a card in it (drag it by its ⠿ to move it, ⋯ to edit or
remove). Drops show a see-through copy where they will land.

The same pieces draw a friend's board on the Friends page, with
`editable=False`: no grips, no menus, nothing to drop -- and a locked
category's controls greyed out.
"""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLayout, QLineEdit, QMenu, QPushButton, QSpinBox,
    QToolButton, QTreeWidget, QWidget, QWidgetItem,
)

import param_board as pb
from ui.layout_helpers import hbox, vbox
from ui.theme import PALETTE
from ui.views.card_parts import WheelSafeSlider

CARD_W = 210
CONTROL_H = 32
SLIDER_STEPS = 1000
MIME_CONTROL = "application/x-ogp-param-control"     # a card moved
MIME_PARAM = "application/x-ogp-param"               # a new control from the list
MIME_CATEGORY = "application/x-ogp-param-category"   # a category reordered

# While a drag runs, drop targets show a half-transparent copy of what is
# dragged where it would land. It travels through here (a drag never
# leaves the process).
_GHOST: Optional[QPixmap] = None


def register_drag_ghost(source: QPixmap) -> None:
    global _GHOST
    ghost = QPixmap(source.size())
    ghost.setDevicePixelRatio(source.devicePixelRatio())
    ghost.fill(Qt.transparent)
    painter = QPainter(ghost)
    painter.setOpacity(0.5)
    painter.drawPixmap(0, 0, source)
    painter.end()
    _GHOST = ghost


def clear_drag_ghost() -> None:
    global _GHOST
    _GHOST = None


def drag_ghost() -> Optional[QPixmap]:
    return _GHOST


def fmt_value(value: Any) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


class BoardFlow(QLayout):
    """Cards left to right, wrapping (the Qt flow layout example) -- a
    hidden card (one being dragged) takes no room, and a drop's ghost can
    be put in at a position."""

    def __init__(self, parent: Optional[QWidget] = None, margin: int = 2, spacing: int = 10):
        super().__init__(parent)
        self._items: List[QWidgetItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def insert_widget(self, index: int, widget: QWidget) -> None:
        self.addWidget(widget)
        self._items.insert(index, self._items.pop())
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._arrange(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._arrange(rect, dry=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            if not item.isEmpty():
                size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect: QRect, dry: bool) -> int:
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for item in self._items:
            if item.isEmpty():
                continue
            hint = item.sizeHint()
            if x + hint.width() > right and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._spacing
                line_h = 0
            if not dry:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line_h = max(line_h, hint.height())
        return y + line_h + m.bottom() - rect.y()


class NoWheelSpin(QSpinBox):
    """A stepper the page's scrolling can't change: the wheel only works on
    one you clicked first. Every step would go to VRChat."""

    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class ParamTree(QTreeWidget):
    """The avatar's parameter list; a row dragged onto a category makes a
    control there."""

    def startDrag(self, actions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        name = item.data(0, Qt.UserRole)
        ptype = item.data(1, Qt.UserRole) or "Float"
        preview = ParamCard({"id": "__ghost__", "param": name, "ptype": ptype,
                             "kind": pb.default_kind(ptype), "label": name.split("/")[-1]},
                            hue="green")
        pixmap = preview.grab()
        preview.deleteLater()
        register_drag_ghost(pixmap)
        mime = QMimeData()
        mime.setData(MIME_PARAM, f"{name}\n{ptype}".encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(20, 20))
        drag.exec(Qt.CopyAction)
        clear_drag_ghost()


class ParamCard(QFrame):
    """One control. `set_value(id, value)` for a toggle / slider / stepper,
    `hold(id, down)` for a hold button."""

    set_value = Signal(str, object)
    hold = Signal(str, bool)
    edit_requested = Signal(str)
    remove_requested = Signal(str)

    def __init__(self, control: Dict[str, Any], value: Any = None, hue: str = "green",
                 editable: bool = True) -> None:
        super().__init__()
        self.control = control
        self.setObjectName("paramCard")
        self.setProperty("hue", hue)
        self.setFixedWidth(CARD_W)
        self._editable = editable
        self._updating = False
        self._press_pos: Optional[QPoint] = None
        self.switch: Optional[QPushButton] = None
        self.slider = None
        self.spin = None

        root = vbox(0, 6)
        root.setContentsMargins(10, 8, 6, 10)
        self.setLayout(root)
        top = hbox(0, 4)
        if editable:
            grip = QLabel("⠿")
            grip.setObjectName("paramGrip")
            grip.setToolTip("Drag to another place or category")
            grip.setCursor(Qt.OpenHandCursor)
            top.addWidget(grip)
        self.label = QLabel(control.get("label") or control["param"])
        self.label.setObjectName("paramLabel")
        self.label.setTextFormat(Qt.PlainText)
        self.label.setToolTip(f'{control["param"]}  ({control["ptype"]})')
        top.addWidget(self.label, 1)
        if control.get("invert"):
            mark = QLabel("⇄")
            mark.setObjectName("paramMark")
            mark.setToolTip("Inverted - ON sends the parameter OFF")
            top.addWidget(mark)
        if pb.is_int_switch(control):
            on, off = pb.int_switch_values(control)
            mark = QLabel(f"={on}")
            mark.setObjectName("paramValue")
            toggle = control["kind"] == "toggle"
            mark.setToolTip(f'{"ON" if toggle else "Holding"} sets {control["param"]} to {on}, '
                            f'{"OFF" if toggle else "letting go"} sets it to {off}')
            top.addWidget(mark)
        if editable:
            menu_btn = QToolButton()
            menu_btn.setObjectName("paramMenu")
            menu_btn.setText("⋯")
            menu_btn.setCursor(Qt.PointingHandCursor)
            menu_btn.clicked.connect(self._show_menu)
            top.addWidget(menu_btn)
        root.addLayout(top)

        kind = control["kind"]
        if kind == "toggle":
            self._build_toggle(root)
        elif kind == "button":
            self._build_button(root)
        elif kind == "slider":
            self._build_slider(root)
        else:
            self._build_int(root)
        if value is not None:
            self.update_value(value)

    # -- the controls ----------------------------------------------------------

    def _build_toggle(self, root) -> None:
        self.switch = QPushButton("OFF")
        self.switch.setProperty("role", "paramSwitch")
        self.switch.setCheckable(True)
        self.switch.setCursor(Qt.PointingHandCursor)
        self.switch.setFixedHeight(CONTROL_H)
        self.switch.toggled.connect(self._on_toggle)
        root.addWidget(self.switch)

    def _on_toggle(self, checked: bool) -> None:
        self.switch.setText("ON" if checked else "OFF")
        if not self._updating:
            self.set_value.emit(self.control["id"], checked)

    def _build_button(self, root) -> None:
        btn = QPushButton("Hold")
        btn.setProperty("role", "paramHold")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFixedHeight(CONTROL_H)
        btn.pressed.connect(lambda: self.hold.emit(self.control["id"], True))
        btn.released.connect(lambda: self.hold.emit(self.control["id"], False))
        root.addWidget(btn)
        self.push = btn

    def _build_slider(self, root) -> None:
        self.vmin = float(self.control.get("min", 0))
        self.vmax = float(self.control.get("max", 1))
        self.slider = WheelSafeSlider(Qt.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setProperty("hue", self.property("hue"))
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setFixedHeight(CONTROL_H)
        self.value_label = QLabel("–")
        self.value_label.setObjectName("paramValue")
        self.value_label.setFixedWidth(36)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._throttle = QTimer(self, interval=60, singleShot=True)
        self._throttle.timeout.connect(self._send_slider)
        self.slider.valueChanged.connect(self._on_slider)
        self.slider.sliderReleased.connect(self._send_slider)
        row = hbox(0, 6)
        row.addWidget(self.slider, 1)
        row.addWidget(self.value_label)
        root.addLayout(row)

    def _slider_value(self) -> float:
        return self.vmin + (self.slider.value() / SLIDER_STEPS) * (self.vmax - self.vmin)

    def _on_slider(self) -> None:
        self.value_label.setText(f"{self._slider_value():.2f}")
        if not self._updating and not self._throttle.isActive():
            self._throttle.start()

    def _send_slider(self) -> None:
        if not self._updating:
            self.set_value.emit(self.control["id"], self._slider_value())

    def _build_int(self, root) -> None:
        self.spin = NoWheelSpin()
        self.spin.setRange(int(self.control.get("min", 0)), int(self.control.get("max", 255)))
        self.spin.setFixedHeight(CONTROL_H)
        self.spin.setProperty("hue", self.property("hue"))
        self._debounce = QTimer(self, interval=150, singleShot=True)
        self._debounce.timeout.connect(
            lambda: self.set_value.emit(self.control["id"], self.spin.value()))
        self.spin.valueChanged.connect(self._on_spin)
        root.addWidget(self.spin)

    def _on_spin(self) -> None:
        if not self._updating:
            self._debounce.start()

    # -- values coming in --------------------------------------------------------

    def update_value(self, value: Any) -> None:
        self._updating = True
        try:
            kind = self.control["kind"]
            if kind == "toggle":
                on = pb.shows_on(self.control, value)
                if self.switch.isChecked() != on:
                    self.switch.setChecked(on)
            elif kind == "slider" and value is not None:
                if not self.slider.isSliderDown():
                    span = (self.vmax - self.vmin) or 1
                    pos = round((float(value) - self.vmin) / span * SLIDER_STEPS)
                    if self.slider.value() != pos:
                        self.slider.setValue(pos)
                    self.value_label.setText(f"{float(value):.2f}")
            elif kind == "int" and value is not None:
                # Only hold off while your own change is still on its way
                # out (or half typed): a clicked stepper keeps focus, and
                # must still follow the avatar.
                typing = (self.spin.hasFocus()
                          and self.spin.text() != self.spin.textFromValue(self.spin.value()))
                if not self._debounce.isActive() and not typing:
                    v = int(round(float(value)))
                    if self.spin.value() != v:
                        self.spin.setValue(v)
        except (TypeError, ValueError):
            pass
        finally:
            self._updating = False

    # -- menu and dragging (the page only) -----------------------------------------

    def _show_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("Edit…", lambda: self.edit_requested.emit(self.control["id"]))
        menu.addSeparator()
        menu.addAction("Remove", lambda: self.remove_requested.emit(self.control["id"]))
        menu.exec(self.mapToGlobal(QPoint(self.width() - 10, 30)))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._editable and event.button() == Qt.LeftButton:
            self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (self._press_pos is not None
                and (event.position().toPoint() - self._press_pos).manhattanLength()
                >= QApplication.startDragDistance()):
            mime = QMimeData()
            mime.setData(MIME_CONTROL, self.control["id"].encode())
            pixmap = self.grab()
            register_drag_ghost(pixmap)
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(pixmap)
            drag.setHotSpot(self._press_pos)
            self._press_pos = None
            self.hide()                  # the ghost shows where it lands
            drag.exec(Qt.MoveAction)
            clear_drag_ghost()
            try:
                self.show()              # cancelled: put it back
            except RuntimeError:
                pass                     # dropped: the board was rebuilt
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press_pos = None
        super().mouseReleaseEvent(event)


class ParamCategory(QFrame):
    """A category: its name, colour and lock, its cards, a drop target."""

    renamed = Signal(str, str)
    lock_toggled = Signal(str, bool)
    delete_requested = Signal(str)
    control_dropped = Signal(str, str, int)        # control id, category id, index
    param_dropped = Signal(str, str, str, int)     # param, type, category id, index
    category_dropped = Signal(str, str)            # dragged id, target id
    category_drag_over = Signal(str, str)
    category_drag_done = Signal()
    copy_to_preset = Signal(str, str)              # category id, preset id
    color_changed = Signal(str, str)

    def __init__(self, category: Dict[str, Any], editable: bool = True) -> None:
        super().__init__()
        self.category = category
        self.setObjectName("paramCat")
        self.setProperty("hue", category.get("color") or "green")
        self._editable = editable
        self.setAcceptDrops(editable)
        self._cat_press: Optional[QPoint] = None
        self._ghost: Optional[QLabel] = None
        self._ghost_at = -1
        self._ghost_pos: Optional[QPoint] = None
        self._copy_targets: List[Tuple[str, str]] = []

        root = vbox(0, 8)
        root.setContentsMargins(8, 8, 8, 10)
        self.setLayout(root)
        header = QWidget()
        header.setObjectName("paramCatHead")
        header.setProperty("hue", self.property("hue"))
        hl = hbox(0, 4)
        hl.setContentsMargins(8, 4, 6, 4)
        header.setLayout(hl)
        locked = bool(category.get("locked"))
        if editable:
            self.grip = QLabel("⠿")
            self.grip.setObjectName("paramCatGrip")
            self.grip.setToolTip("Drag to reorder the categories")
            self.grip.setCursor(Qt.OpenHandCursor)
            self.grip.installEventFilter(self)
            hl.addWidget(self.grip)
            self.name_edit = QLineEdit(category.get("name") or "")
            self.name_edit.setObjectName("paramCatName")
            self.name_edit.setPlaceholderText("Category name")
            self.name_edit.editingFinished.connect(
                lambda: self.renamed.emit(self.category["id"], self.name_edit.text()))
            hl.addWidget(self.name_edit, 1)
            self.lock_btn = QToolButton()
            self.lock_btn.setObjectName("paramCatLock")
            self.lock_btn.setCheckable(True)
            self.lock_btn.setChecked(locked)
            self.lock_btn.setText("🔒" if locked else "🔓")
            self.lock_btn.setToolTip("Lock: friends can see these controls but not use them")
            self.lock_btn.setCursor(Qt.PointingHandCursor)
            self.lock_btn.toggled.connect(self._on_lock)
            hl.addWidget(self.lock_btn)
            menu_btn = QToolButton()
            menu_btn.setObjectName("paramMenu")
            menu_btn.setText("⋯")
            menu_btn.setCursor(Qt.PointingHandCursor)
            menu_btn.clicked.connect(self._show_menu)
            hl.addWidget(menu_btn)
        else:
            self._title = QLabel(category.get("name") or "")
            self._title.setObjectName("paramCatTitle")
            self._title.setTextFormat(Qt.PlainText)
            hl.addWidget(self._title, 1)
            self._lock_lbl = QLabel("🔒 look only")
            self._lock_lbl.setObjectName("paramCatTitle")
            self._lock_lbl.setToolTip("Locked - you can see these, not use them")
            hl.addWidget(self._lock_lbl)
            if not locked:
                self._lock_lbl.hide()
        root.addWidget(header)

        self.cards_host = QWidget()
        self.flow = BoardFlow(self.cards_host, margin=2, spacing=10)
        root.addWidget(self.cards_host)
        self.hint = QLabel("Drop controls here" if editable else "Nothing here yet")
        self.hint.setObjectName("paramCatHint")
        self.hint.setAlignment(Qt.AlignCenter)
        root.addWidget(self.hint)
        self._locked = locked

    def set_copy_targets(self, presets: List[Tuple[str, str]]) -> None:
        self._copy_targets = presets

    def add_card(self, card: ParamCard) -> None:
        self.flow.addWidget(card)

    def finalize(self, stopped: bool = False) -> None:
        """After the cards are in. `stopped`: a friend's board while they
        paused all friends -- nothing in it can be used."""
        self.hint.setVisible(self.flow.count() == 0)
        if not self._editable:
            self.cards_host.setDisabled(self._locked or stopped)

    def set_state(self, name: str, locked: bool, stopped: bool = False) -> None:
        """A friend's board: the category renamed or (un)locked, in place --
        rebuilding the board for that made it blink."""
        if self._editable:
            return
        self._locked = bool(locked)
        if self._title.text() != name:
            self._title.setText(name)
        self._lock_lbl.setVisible(self._locked)
        self.cards_host.setDisabled(self._locked or stopped)

    def _on_lock(self, checked: bool) -> None:
        self.lock_btn.setText("🔒" if checked else "🔓")
        self.lock_toggled.emit(self.category["id"], checked)

    def _show_menu(self) -> None:
        menu = QMenu(self)
        colours = menu.addMenu("Colour")
        current = self.category.get("color") or "green"
        for key in pb.CATEGORY_HUES:
            swatch = QPixmap(12, 12)
            swatch.fill(QColor(PALETTE[key][0]))
            action = colours.addAction(QIcon(swatch), pb.CATEGORY_HUE_LABELS[key])
            action.setCheckable(True)
            action.setChecked(key == current)
            action.triggered.connect(
                lambda _=False, k=key: self.color_changed.emit(self.category["id"], k))
        if self._copy_targets:
            copy_menu = menu.addMenu("Copy to preset")
            for preset_id, name in self._copy_targets:
                copy_menu.addAction(name, lambda pid=preset_id:
                                    self.copy_to_preset.emit(self.category["id"], pid))
        menu.addSeparator()
        menu.addAction("Delete category", lambda: self.delete_requested.emit(self.category["id"]))
        menu.exec(self.mapToGlobal(QPoint(self.width() - 10, 34)))

    # -- dragging the category by its grip ------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802
        if self._editable and obj is self.grip:
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._cat_press = event.position().toPoint()
            elif event.type() == QEvent.MouseMove and self._cat_press is not None:
                if ((event.position().toPoint() - self._cat_press).manhattanLength()
                        >= QApplication.startDragDistance()):
                    self._cat_press = None
                    mime = QMimeData()
                    mime.setData(MIME_CATEGORY, self.category["id"].encode())
                    pixmap = self.grab()
                    register_drag_ghost(pixmap)
                    drag = QDrag(self)
                    drag.setMimeData(mime)
                    drag.setPixmap(pixmap)
                    self.hide()
                    drag.exec(Qt.MoveAction)
                    clear_drag_ghost()
                    try:
                        self.show()
                        self.category_drag_done.emit()
                    except RuntimeError:
                        pass
                    return True
            elif event.type() == QEvent.MouseButtonRelease:
                self._cat_press = None
        return super().eventFilter(obj, event)

    # -- dropping onto it -------------------------------------------------------------

    def _accepts(self, event) -> bool:
        md = event.mimeData()
        return (md.hasFormat(MIME_CONTROL) or md.hasFormat(MIME_PARAM)
                or md.hasFormat(MIME_CATEGORY))

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._accepts(event):
            event.acceptProposedAction()
            self._drag_update(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._accepts(event):
            event.acceptProposedAction()
            self._drag_update(event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._remove_ghost()

    def _drag_update(self, event) -> None:
        md = event.mimeData()
        if md.hasFormat(MIME_CATEGORY):
            self.category_drag_over.emit(bytes(md.data(MIME_CATEGORY)).decode(),
                                         self.category["id"])
            return
        self._show_ghost(self.cards_host.mapFrom(self, event.position().toPoint()))

    def dropEvent(self, event) -> None:  # noqa: N802
        md = event.mimeData()
        self._remove_ghost()
        if md.hasFormat(MIME_CATEGORY):
            dragged = bytes(md.data(MIME_CATEGORY)).decode()
            event.acceptProposedAction()
            if dragged != self.category["id"]:
                self.category_dropped.emit(dragged, self.category["id"])
            return
        index = self._insert_index(self.cards_host.mapFrom(self, event.position().toPoint()))
        if md.hasFormat(MIME_CONTROL):
            event.acceptProposedAction()
            self.control_dropped.emit(bytes(md.data(MIME_CONTROL)).decode(),
                                      self.category["id"], index)
        elif md.hasFormat(MIME_PARAM):
            param, ptype = bytes(md.data(MIME_PARAM)).decode().split("\n", 1)
            event.acceptProposedAction()
            self.param_dropped.emit(param, ptype, self.category["id"], index)

    def _insert_index(self, pos: QPoint) -> int:
        """Where among the visible cards a drop at `pos` goes (the ghost
        and a card mid-drag don't count, so it matches the board's order)."""
        index = 0
        for i in range(self.flow.count()):
            widget = self.flow.itemAt(i).widget()
            if widget is self._ghost or not widget.isVisible():
                continue
            r = widget.geometry()
            if pos.y() < r.top():
                return index
            if pos.y() <= r.bottom() and pos.x() < r.center().x():
                return index
            index += 1
        return index

    def _show_ghost(self, pos: QPoint) -> None:
        pixmap = drag_ghost()
        if pixmap is None:
            return
        index = self._insert_index(pos)
        if self._ghost is not None:
            if index == self._ghost_at:
                return
            if self._ghost_pos is not None and (pos - self._ghost_pos).manhattanLength() < 10:
                return               # don't flip it about for tiny moves
        self._remove_ghost()
        label = QLabel()
        label.setPixmap(pixmap)
        at, seen = self.flow.count(), 0
        for i in range(self.flow.count()):
            widget = self.flow.itemAt(i).widget()
            if not widget.isVisible():
                continue
            if seen == index:
                at = i
                break
            seen += 1
        self.flow.insert_widget(at, label)
        self._ghost, self._ghost_at, self._ghost_pos = label, index, pos
        self.hint.setVisible(False)

    def _remove_ghost(self) -> None:
        if self._ghost is not None:
            self.flow.removeWidget(self._ghost)
            self._ghost.deleteLater()
            self._ghost, self._ghost_at, self._ghost_pos = None, -1, None
