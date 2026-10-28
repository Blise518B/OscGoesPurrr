"""Avatar Remote view — VRC Parameter Relay's board inside OGP: controls for
your avatar's parameters, per avatar, that friends can use too.

Mixin for ui_components.OscGoesPurrrUI, shown while `feature_params` is on
(off by default). Top to bottom:

  * the avatar: its name (naming one keeps it in the ▾ list, for editing
    while you wear something else), ● LIVE / ✎ OFFLINE, its id, the preset
    (a board of its own; ⋯ adds, renames, deletes) and which friends are
    looking at your board right now;
  * a bar: ＋ Category, ⚡ YOLO (friends get every parameter, locks don't
    hold), Import from VRC Parameter Relay, and the parameter list's switch
    (who may use the board: each friend's AVATAR switch, Pause all friends);
  * the board -- categories in two columns (one when narrow), their cards
    (param_cards.py) -- beside the avatar's parameter list: live values,
    a filter, double-click or drag one into a category to make a control.
    The bar between them drags the list wider for long parameter names
    (kept, app setting `params_dock_w`).

What friends see is your *worn* avatar's preset, whatever is open here.
Everything goes through the controller's Params facade (Demeter rule).
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHeaderView, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import param_board as pb
from ui.layout_helpers import clear_layout, hbox as _hbox, vbox as _vbox
from ui.views.param_cards import (
    CARD_W, ParamCard, ParamCategory, ParamTree, drag_ghost, fmt_value,
)
from ui.views.param_dialogs import ControlDialog
from ui.widgets import Card as _Card

VIEW_NAME = "My Avatar Remote"
DOCK_W = 330                  # the parameter list's width at first ...
DOCK_MIN_W = 260              # ... and the narrowest the bar drags it to
# one category column needs two cards side by side; two columns twice that
_TWO_COLUMNS_FROM = 2 * (2 * CARD_W + 10 + 24) + 12
_LIST_EVERY = 3               # the parameter list's values: every third live tick


class _Dock(_Card):
    """The parameter list: as wide as last dragged (the splitter asks)."""

    def __init__(self, width: int):
        super().__init__()
        self.want_w = width
        self.setMinimumWidth(DOCK_MIN_W)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.want_w, super().sizeHint().height())


class _Board(QWidget):
    """The board's two columns -- one once two don't fit."""

    def __init__(self, on_width):
        super().__init__()
        self._on_width = on_width

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._on_width(self.width())


class ParamsMixin:

    _params_built = False

    # ----------------------------------------------------------
    # View
    # ----------------------------------------------------------

    def _build_params_view(self, parent_layout: QVBoxLayout):
        title = QLabel(VIEW_NAME)
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)
        # This page is your own avatar's remote; a friend's is on Friends
        # (Blise's ask, 2026-10-28: "Avatar Remote" alone read as the place
        # to control other people's avatars).
        intro = _hbox(0, 12)
        intro.addWidget(self._muted_label(
            "The remote for your own avatar: build a board of controls for its "
            "parameters - toggles, hold buttons, sliders, steppers - per avatar. "
            "Friends you allow (Friends page, the third box) see the board of the "
            "avatar you're wearing and can use it; everything they do is logged "
            "there. A friend's avatar you use from Friends, in their panel."), 1)
        to_friends = QPushButton("Friends ▸")
        to_friends.setProperty("role", "secondary")
        to_friends.setCursor(Qt.PointingHandCursor)
        to_friends.clicked.connect(lambda _=False: self.select_view("Friends"))
        self._explain(to_friends, "Friends",
            "Open the Friends page: pick a friend there to use their avatar's "
            "remote, and choose who may use yours (the third box).")
        intro.addWidget(to_friends, 0, Qt.AlignVCenter)
        # Hidden with the Friends page (apply_feature_visibility)
        self._params_friends_btn = to_friends
        parent_layout.addLayout(intro)
        parent_layout.addWidget(self._build_params_header())
        parent_layout.addLayout(self._build_params_toolbar())

        self._params_board = _Board(self._params_board_width)
        board_lay = _hbox(0, 12)
        self._params_board.setLayout(board_lay)
        self._params_cols: List[QVBoxLayout] = []
        for _ in range(2):
            col = _vbox(0, 12)
            col.setAlignment(Qt.AlignTop)
            board_lay.addLayout(col, 1)
            self._params_cols.append(col)
        self._params_ncols = 2
        left = _vbox(0, 8)
        left.addWidget(self._params_board)
        self._params_empty = self._muted_label(
            "Waiting for VRChat...\n\nStart VRChat with OSC on (Action Menu → Options → OSC) "
            "and load into an avatar. A saved avatar's board can be edited any time: "
            "▾ next to the name.")
        self._params_empty.setAlignment(Qt.AlignCenter)
        left.addWidget(self._params_empty)
        left.addStretch(1)
        left_box = QWidget()
        left_box.setLayout(left)
        # The board, a bar, the parameter list: drag the bar to make the list
        # wider (long parameter names) -- the board goes to one column when
        # it gets narrow. The width is kept.
        split = QSplitter(Qt.Horizontal)
        split.setObjectName("paramsSplit")
        split.setChildrenCollapsible(False)
        split.setHandleWidth(8)
        split.addWidget(left_box)
        self._params_dock = self._build_params_dock()
        split.addWidget(self._params_dock)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.handle(1).setToolTip("Drag to make the parameter list wider or narrower")
        split.handle(1).setCursor(Qt.SplitHCursor)
        self._params_split = split
        self._params_dock_save = QTimer(split)
        self._params_dock_save.setSingleShot(True)
        self._params_dock_save.setInterval(400)
        self._params_dock_save.timeout.connect(self._params_keep_dock_width)
        split.splitterMoved.connect(lambda *_a: self._params_dock_save.start())
        parent_layout.addWidget(split)
        parent_layout.addStretch(1)

        self._params_cards: Dict[str, ParamCard] = {}
        self._params_boxes: Dict[str, ParamCategory] = {}
        self._params_items: Dict[str, QTreeWidgetItem] = {}
        self._params_cat_ghost: Optional[QLabel] = None
        self._params_last_cat: Optional[str] = None
        self._params_live_n = 0
        self._params_rebuild_due = False
        self._params_built = True
        self.refresh_params(rebuild=True, params=True)

    def _build_params_header(self) -> QWidget:
        card = _Card()
        lay = _vbox(16, 4)
        card.setLayout(lay)
        row = _hbox(0, 6)
        self._params_name = QLineEdit()
        self._params_name.setObjectName("paramAvatarName")
        self._params_name.setPlaceholderText("Avatar name")
        self._params_name.setMaximumWidth(360)
        self._params_name.editingFinished.connect(
            lambda: self.controller.params_edit("rename_avatar", self._params_name.text()))
        self._explain(self._params_name, "Avatar name",
                      "Name this avatar and it is kept in the ▾ list: its board can "
                      "then be edited while you wear something else.")
        row.addWidget(self._params_name, 1)
        pick = self._params_small("▾")
        pick.setCursor(Qt.PointingHandCursor)
        pick.setToolTip("Open a saved avatar (● = the one you're wearing)")
        pick.clicked.connect(lambda _=False: self._params_avatar_menu(pick))
        row.addWidget(pick)
        self._params_live = QLabel("")
        self._params_live.setProperty("role", "pill")
        row.addWidget(self._params_live)
        row.addStretch(1)
        self._params_preset = QComboBox()
        self._params_preset.setMinimumWidth(130)
        self._params_preset.activated.connect(self._params_preset_chosen)
        self._explain(self._params_preset, "Preset",
                      "A separate board for this avatar. Friends get the one picked "
                      "here (of the avatar you're wearing).")
        row.addWidget(self._params_preset)
        more = self._params_small("⋯")
        more.setCursor(Qt.PointingHandCursor)
        more.setToolTip("Add, rename or delete presets")
        more.clicked.connect(lambda _=False: self._params_preset_menu(more))
        row.addWidget(more)
        lay.addLayout(row)
        row2 = _hbox(0, 8)
        self._params_id = QLabel("")
        self._params_id.setObjectName("paramAvatarId")
        self._params_id.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row2.addWidget(self._params_id, 1)
        self._params_watching = QLabel("")
        self._params_watching.setProperty("role", "pill")
        self._explain(self._params_watching, "Friends looking",
                      "Friends who have your board open on their Friends page right "
                      "now. They get the board of the avatar you're wearing.")
        row2.addWidget(self._params_watching)
        lay.addLayout(row2)
        return card

    @staticmethod
    def _params_small(text: str) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("role", "mini")
        b.setProperty("wide", "true")
        b.setFixedSize(30, 28)
        return b

    def _build_params_toolbar(self):
        bar = _hbox(0, 8)
        add = QPushButton("＋ Category")
        add.clicked.connect(lambda _=False: self.controller.params_edit("add_category"))
        bar.addWidget(add)
        self._params_yolo = QPushButton("⚡ YOLO")
        self._params_yolo.setProperty("role", "yolo")
        self._params_yolo.setCheckable(True)
        self._params_yolo.setCursor(Qt.PointingHandCursor)
        self._params_yolo.toggled.connect(self._params_yolo_toggled)
        self._explain(self._params_yolo, "⚡ YOLO",
                      "Friends get the full parameter list of the avatar you're wearing "
                      "and can set anything, ignoring category locks (values stay in "
                      "VRChat's ranges; VRChat's own parameters like Viseme are left "
                      "out). Stays on until you turn it off, even after restarts.")
        bar.addWidget(self._params_yolo)
        bar.addStretch(1)
        imp = QPushButton("Import from VRC Parameter Relay…")
        imp.setProperty("role", "ghost")
        imp.clicked.connect(lambda _=False: self._params_import())
        self._explain(imp, "Import",
                      "Copies the boards you built in VRC Parameter Relay "
                      "(%APPDATA%\\VRCParameterRelay) - every avatar, preset, category "
                      "and control. The Relay's own files stay as they are.")
        bar.addWidget(imp)
        self._params_dock_btn = QPushButton("Avatar parameters ◂")
        self._params_dock_btn.setProperty("role", "ghost")
        self._params_dock_btn.clicked.connect(lambda _=False: self._params_toggle_dock())
        bar.addWidget(self._params_dock_btn)
        return bar

    def _build_params_dock(self) -> QWidget:
        try:
            width = int(self.controller.get_app_setting("params_dock_w", DOCK_W))
        except (TypeError, ValueError):
            width = DOCK_W
        card = _Dock(max(DOCK_MIN_W, min(1600, width)))
        lay = _vbox(14, 8)
        card.setLayout(lay)
        head = _hbox(0, 8)
        hdr = QLabel("Avatar parameters")
        hdr.setObjectName("sectionTitle")
        head.addWidget(hdr, 1)
        sync = QPushButton("⟳ Resync")
        sync.setToolTip("Fetch the avatar and its parameters from VRChat again")
        sync.clicked.connect(lambda _=False: self.controller.params_resync())
        head.addWidget(sync)
        lay.addLayout(head)
        self._params_filter = QLineEdit()
        self._params_filter.setPlaceholderText("Filter parameters…")
        self._params_filter.textChanged.connect(lambda _t: self._params_apply_filter())
        lay.addWidget(self._params_filter)
        tree = ParamTree()
        tree.setObjectName("paramTree")
        tree.setHeaderLabels(["Parameter", "Type", "Value"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        # a long name keeps its end -- usually the part that tells two apart
        tree.setTextElideMode(Qt.ElideMiddle)
        tree.setDragEnabled(True)
        tree.setDragDropMode(QTreeWidget.DragOnly)
        tree.setMinimumHeight(420)
        hh = tree.header()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        tree.setColumnWidth(1, 48)
        tree.setColumnWidth(2, 70)
        tree.itemDoubleClicked.connect(self._params_add_from_item)
        lay.addWidget(tree, 1)
        self._params_tree = tree
        lay.addWidget(self._muted_label("Double-click a parameter, or drag it into a "
                                        "category, to make a control."))
        self._params_list_note = self._muted_label("")
        lay.addWidget(self._params_list_note)
        return card

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def refresh_params(self, rebuild: bool = False, params: bool = False) -> None:
        """The controller changed something. A rebuild waits for the event
        loop: it is often asked for from inside a card's own signal."""
        if not self._params_built:
            return
        if params:
            self._params_refresh_list()
        if rebuild and not self._params_rebuild_due:
            self._params_rebuild_due = True
            QTimer.singleShot(0, self._params_rebuild)
        self._params_refresh_header()

    def refresh_params_live(self) -> None:
        """Values, ten times a second -- only while the page is shown."""
        if not self._params_built or not self._params_page_shown():
            return
        c = self.controller
        names = {card.control["param"] for card in self._params_cards.values()}
        self._params_live_n += 1
        listed = self._params_live_n % _LIST_EVERY == 0 and self._params_dock.isVisible()
        if listed:
            names |= set(self._params_items)
        values = c.params_values(names) if names else {}
        for card in self._params_cards.values():
            name = card.control["param"]
            if name in values:
                card.update_value(values[name])
        if listed:
            for name, item in self._params_items.items():
                text = fmt_value(values.get(name))
                if item.text(2) != text:
                    item.setText(2, text)
        if self._params_live_n % 10 == 0:
            self._params_refresh_header()

    def _params_page_shown(self) -> bool:
        stack = getattr(self, "main_stack", None)
        page = getattr(self, "views", {}).get(VIEW_NAME)
        return stack is None or page is None or stack.currentWidget() is page

    def _params_refresh_header(self) -> None:
        st = self.controller.get_params_status()
        if not self._params_name.hasFocus() and self._params_name.text() != st["avatar_name"]:
            self._params_name.setText(st["avatar_name"])
        has = st["avatar_id"] is not None
        self._params_live.setVisible(has)
        if has:
            live = st["is_live"]
            self._params_set_pill(self._params_live, "● LIVE" if live else "✎ OFFLINE",
                                  "ok" if live else "warn")
            self._params_live.setToolTip(
                "You're wearing this avatar in VRChat - the controls are live" if live else
                "Only editing - you're not wearing this avatar, nothing is sent to VRChat. "
                "Friends get the board of the avatar you ARE wearing.")
        aid = st["avatar_id"] or ("waiting for VRChat…" if not st["vrchat"] else "")
        if self._params_id.text() != aid:
            self._params_id.setText(aid)
        presets = [(p["id"], p["name"]) for p in st["presets"]]
        current = [(self._params_preset.itemData(i), self._params_preset.itemText(i))
                   for i in range(self._params_preset.count())]
        if presets != current:
            self._params_preset.blockSignals(True)
            self._params_preset.clear()
            for pid, name in presets:
                self._params_preset.addItem(name, pid)
            self._params_preset.blockSignals(False)
        idx = self._params_preset.findData(st["board"].get("id"))
        if idx >= 0 and self._params_preset.currentIndex() != idx:
            self._params_preset.setCurrentIndex(idx)
        self._params_preset.setEnabled(has)
        if self._params_yolo.isChecked() != st["yolo"]:
            self._params_yolo.blockSignals(True)
            self._params_yolo.setChecked(st["yolo"])
            self._params_yolo.blockSignals(False)
        if not st["friends_on"]:
            self._params_set_pill(self._params_watching, "FRIENDS IS OFF", "idle")
        elif st["watchers"]:
            self._params_set_pill(self._params_watching,
                                  "LOOKING: " + ", ".join(st["watchers"]), "info")
        else:
            self._params_set_pill(self._params_watching, "NO FRIEND LOOKING", "idle")

    def _params_set_pill(self, pill: QLabel, text: str, tone: str) -> None:
        if pill.text() != text:
            pill.setText(text)
        if pill.property("tone") != tone:
            pill.setProperty("tone", tone)
            self._repolish(pill)

    # ----------------------------------------------------------
    # The board
    # ----------------------------------------------------------

    def _params_board_width(self, width: int) -> None:
        cols = 2 if width >= _TWO_COLUMNS_FROM else 1
        if cols != self._params_ncols:
            self._params_ncols = cols
            self.refresh_params(rebuild=True)

    def _params_rebuild(self) -> None:
        self._params_rebuild_due = False
        c = self.controller
        st = c.get_params_status()
        board = st["board"]
        self._params_cat_ghost = None
        for col in self._params_cols:
            clear_layout(col)
        self._params_cards, self._params_boxes = {}, {}
        has = st["avatar_id"] is not None
        self._params_empty.setVisible(not has)
        self._params_board.setVisible(has)
        if not has:
            return
        others = [(p["id"], p["name"]) for p in st["presets"] if p["id"] != board.get("id")]
        values = c.params_values({ctl["param"] for ctl in board["controls"]})
        for i, cat in enumerate(board["categories"]):
            box = ParamCategory(cat)
            box.hint.setProperty("hue", cat["color"])
            # the box already shows a new name or lock: saved, no rebuild
            box.renamed.connect(lambda cid, name: c.params_edit_quiet("rename_category", cid, name))
            box.lock_toggled.connect(
                lambda cid, on: c.params_edit_quiet("set_category_locked", cid, on))
            box.delete_requested.connect(self._params_delete_category)
            box.control_dropped.connect(lambda k, cid, at: c.params_edit("move_control", k, cid, at))
            box.param_dropped.connect(self._params_param_dropped)
            box.category_dropped.connect(lambda a, b: c.params_edit("move_category", a, b))
            box.category_drag_over.connect(self._params_show_cat_ghost)
            box.category_drag_done.connect(self._params_clear_cat_ghost)
            box.set_copy_targets(others)
            box.copy_to_preset.connect(
                lambda cid, pid: c.params_edit("copy_category_to_preset", cid, pid))
            box.color_changed.connect(lambda cid, hue: c.params_edit("set_category_color", cid, hue))
            for control in board["controls"]:
                if control.get("cat") != cat["id"]:
                    continue
                card = ParamCard(control, values.get(control["param"]), hue=cat["color"])
                card.set_value.connect(c.params_set_control)
                card.hold.connect(c.params_set_control)
                card.edit_requested.connect(self._params_edit_control)
                card.remove_requested.connect(lambda k: c.params_edit("remove_control", k))
                box.add_card(card)
                self._params_cards[control["id"]] = card
            box.finalize()
            self._params_boxes[cat["id"]] = box
            self._params_cols[i % self._params_ncols].addWidget(box)
        # one column: the empty second one must not take half the width
        self._params_board.layout().setStretch(1, 1 if self._params_ncols == 2 else 0)

    def _params_refresh_list(self) -> None:
        params = self.controller.params_param_list()
        live = self.controller.get_params_status()["is_live"]
        self._params_tree.clear()
        self._params_items = {}
        values = self.controller.params_values(params.keys()) if live else {}
        for name in sorted(params, key=str.lower):
            item = QTreeWidgetItem([name, params[name], fmt_value(values.get(name))])
            item.setToolTip(0, name)
            item.setData(0, Qt.UserRole, name)
            item.setData(1, Qt.UserRole, params[name])
            self._params_tree.addTopLevelItem(item)
            self._params_items[name] = item
        self._params_apply_filter()
        self._params_list_note.setText(
            "Values update live from VRChat." if live else
            "The list this avatar had when you last wore it (no live values).")

    def _params_apply_filter(self) -> None:
        needle = self._params_filter.text().lower().strip()
        for name, item in self._params_items.items():
            item.setHidden(bool(needle) and needle not in name.lower())

    def _params_keep_dock_width(self) -> None:
        """The bar was dragged (a moment ago -- not every pixel): keep it."""
        width = self._params_dock.width()
        if self._params_dock.isVisible() and width >= DOCK_MIN_W:
            self._params_dock.want_w = width
            self.controller.set_app_setting("params_dock_w", width)

    def _params_toggle_dock(self) -> None:
        show = not self._params_dock.isVisible()
        self._params_dock.setVisible(show)
        self._params_dock_btn.setText("Avatar parameters ◂" if show else "Avatar parameters ▸")

    # ---- category ghost (where a dragged category lands) --------

    def _params_show_cat_ghost(self, dragged_id: str, target_id: str) -> None:
        if dragged_id == target_id:
            self._params_clear_cat_ghost()
            return
        pixmap = drag_ghost()
        target = self._params_boxes.get(target_id)
        if pixmap is None or target is None:
            return
        # move_category lands it AFTER the target coming from an earlier
        # place, BEFORE it otherwise -- the ghost shows exactly that
        cats = self.controller.get_params_status()["board"]["categories"]
        src = next((i for i, c in enumerate(cats) if c["id"] == dragged_id), None)
        dst = next((i for i, c in enumerate(cats) if c["id"] == target_id), None)
        after = src is not None and dst is not None and src < dst
        for col in self._params_cols:
            i = col.indexOf(target)
            if i == -1:
                continue
            ghost = self._params_cat_ghost
            if ghost is not None:
                at = col.indexOf(ghost)
                if at != -1 and at == (i + 1 if after else i - 1):
                    return
            self._params_clear_cat_ghost()
            i = col.indexOf(target)
            label = QLabel()
            label.setPixmap(pixmap)
            col.insertWidget(i + 1 if after else i, label)
            self._params_cat_ghost = label
            return

    def _params_clear_cat_ghost(self) -> None:
        if self._params_cat_ghost is not None:
            try:
                self._params_cat_ghost.setParent(None)
                self._params_cat_ghost.deleteLater()
            except RuntimeError:
                pass
            self._params_cat_ghost = None

    # ----------------------------------------------------------
    # Actions
    # ----------------------------------------------------------

    def _params_avatar_menu(self, anchor) -> None:
        st = self.controller.get_params_status()
        menu = QMenu(anchor)
        for entry in self.controller.params_avatars():
            live = entry["avatar_id"] == st["live_avatar_id"]
            action = menu.addAction(("● " if live else "   ") + entry["name"])
            action.setCheckable(True)
            action.setChecked(entry["avatar_id"] == st["avatar_id"])
            action.triggered.connect(
                lambda _=False, aid=entry["avatar_id"]: self.controller.params_open_avatar(aid))
        if menu.isEmpty():
            menu.addAction("No saved avatars yet").setEnabled(False)
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _params_preset_chosen(self, index: int) -> None:
        pid = self._params_preset.itemData(index)
        if pid:
            self.controller.params_edit("switch_preset", pid)

    def _params_preset_menu(self, anchor) -> None:
        st = self.controller.get_params_status()
        if st["avatar_id"] is None:
            return
        board = st["board"]
        menu = QMenu(anchor)
        menu.addAction("＋ New preset", lambda: self.controller.params_edit("add_preset"))
        menu.addAction("Rename preset…", lambda: self._params_rename_preset(board))
        menu.addSeparator()
        menu.addAction("Delete preset", lambda: self._params_delete_preset(board, st["presets"]))
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _params_rename_preset(self, board: Dict[str, Any]) -> None:
        name, ok = QInputDialog.getText(self.window, "Rename preset", "Preset name:",
                                        text=board.get("name", ""))
        if ok and name.strip():
            self.controller.params_edit("rename_preset", board["id"], name.strip())

    def _params_delete_preset(self, board: Dict[str, Any], presets: List[Dict[str, str]]) -> None:
        if len(presets) <= 1:
            QMessageBox.information(self.window, "Can't delete",
                                    "The avatar needs at least one preset.")
            return
        answer = QMessageBox.question(
            self.window, "Delete preset",
            f"Delete the preset “{board.get('name')}” and everything on it?")
        if answer == QMessageBox.Yes:
            self.controller.params_edit("remove_preset", board["id"])

    def _params_delete_category(self, cat_id: str) -> None:
        board = self.controller.get_params_status()["board"]
        if any(c.get("cat") == cat_id for c in board["controls"]):
            answer = QMessageBox.question(
                self.window, "Delete category",
                "This category still has controls - they move to the first category. "
                "Delete it?")
            if answer != QMessageBox.Yes:
                return
        if not self.controller.params_edit("remove_category", cat_id):
            QMessageBox.information(self.window, "Can't delete",
                                    "The board needs at least one category.")

    def _params_edit_control(self, control_id: str) -> None:
        board = self.controller.get_params_status()["board"]
        control = pb.find_control(board, control_id)
        if control is None:
            return
        # what fits the parameter as VRChat has it NOW -- an avatar update
        # may have turned a Bool into an Int since the card was made
        ptype = self.controller.params_param_type(control["param"]) or control["ptype"]
        dlg = ControlDialog(self.window, control["param"], ptype, existing=control,
                            suggested_on=self.controller.params_next_on_value(control["param"],
                                                                              control_id))
        if dlg.exec() == QDialog.Accepted:
            self.controller.params_edit("update_control", control_id, **dlg.result_dict())

    def _params_add_from_item(self, item: QTreeWidgetItem) -> None:
        """Double-click: added at once with the defaults, into the category
        used last (Edit fine-tunes it)."""
        if self.controller.get_params_status()["avatar_id"] is None:
            return
        ptype = item.data(1, Qt.UserRole) or "Float"
        self.controller.params_edit("add_control", item.data(0, Qt.UserRole),
                                    pb.default_kind(ptype), category=self._params_last_category())

    def _params_param_dropped(self, param: str, ptype: str, cat_id: str, index: int) -> None:
        self._params_last_cat = cat_id
        self.controller.params_edit("add_control", param, pb.default_kind(ptype),
                                    category=cat_id, index=index)

    def _params_last_category(self) -> Optional[str]:
        cats = self.controller.get_params_status()["board"]["categories"]
        ids = {c["id"] for c in cats}
        return self._params_last_cat if self._params_last_cat in ids else cats[0]["id"]

    def _params_yolo_toggled(self, on: bool) -> None:
        if on:
            answer = QMessageBox.warning(
                self.window, "Turn on YOLO?",
                "Every friend allowed your board will be able to see and change EVERY "
                "parameter of the avatar you're wearing - not just your board, and "
                "category locks won't hold for them.\n\nIt stays on until you turn it "
                "off, even after restarting OGP. Turn it on?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                self._params_yolo.blockSignals(True)
                self._params_yolo.setChecked(False)
                self._params_yolo.blockSignals(False)
                return
        self.controller.params_set_yolo(on)

    def _params_import(self) -> None:
        found, here = self.controller.params_relay_import_preview()
        if not found:
            QMessageBox.information(
                self.window, "Import from VRC Parameter Relay",
                "No boards found - VRC Parameter Relay keeps them in "
                "%APPDATA%\\VRCParameterRelay\\avatars, and that folder is empty or "
                "missing on this PC.")
            return
        box = QMessageBox(self.window)
        box.setWindowTitle("Import from VRC Parameter Relay")
        text = f"VRC Parameter Relay has boards for {found} avatar{'' if found == 1 else 's'}."
        if here:
            text += (f"\n\n{here} of them already have a board here. Keep those, or "
                     "replace them with the Relay's?")
            keep = box.addButton("Import, keep mine", QMessageBox.AcceptRole)
            replace = box.addButton("Import and replace", QMessageBox.DestructiveRole)
        else:
            keep = box.addButton("Import", QMessageBox.AcceptRole)
            replace = None
        box.addButton(QMessageBox.Cancel)
        box.setText(text + "\n\nThe Relay's own files stay as they are.")
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (keep, replace) or clicked is None:
            return
        added, replaced, kept = self.controller.params_relay_import(replace=clicked is replace)
        QMessageBox.information(
            self.window, "Imported",
            f"{added + replaced} board{'' if added + replaced == 1 else 's'} imported"
            + (f", {kept} kept as you had them" if kept else "")
            + ". Open them with ▾ next to the avatar's name.")
