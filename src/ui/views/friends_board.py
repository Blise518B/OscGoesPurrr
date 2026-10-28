"""Friends view: "Their avatar" -- the board a friend built on their
Avatar Remote page for the avatar they wear, under their toys and shockers in
the panel (one friend only: in a group everyone wears something else).

Their categories and cards as they have them (param_cards.py, without
grips or menus); a locked category is look-only. With their ⚡ YOLO on, a
list of every parameter follows, filterable. While the panel shows them
the page tells the controller it is watching (only then does their OGP
send the board and its values); looking away says so too. Part of
FriendsMixin (friends.py)."""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QWidget

from ui.layout_helpers import clear_layout, hbox as _hbox, vbox as _vbox
from ui.views.card_parts import WheelSafeSlider
from ui.views.param_cards import NoWheelSpin, ParamCard, ParamCategory

_HUE = "accent"
_YOLO_ROWS = 60           # the every-parameter list shows this many at once


def _shape(board: Optional[Dict[str, Any]]):
    """What a friend's board is made of, without the categories' names and
    locks (those change in place)."""
    if board is None:
        return None
    return (tuple((c["id"], c["color"]) for c in board["categories"]),
            tuple(tuple(sorted(c.items())) for c in board["controls"]),
            None if board.get("all") is None else tuple(board["all"]))


class FriendsBoardMixin:

    _watching_board: Optional[str] = None

    def _friends_watch(self, peer: Optional[str], yolo_open: bool = False) -> None:
        key = (peer, yolo_open)
        if key != getattr(self, "_friends_watch_key", None):
            self._friends_watch_key = key
            self.controller.set_friend_params_watch(peer, yolo_open)

    def _build_friend_board(self, fid: str) -> None:
        lay, head = self._friends_section("THEIR AVATAR", _HUE)
        frame = lay.parentWidget()
        note = QLabel("")
        note.setProperty("muted", "true")
        note.setTextFormat(Qt.PlainText)
        head.addWidget(note)
        self._explain(frame, "Their avatar",
                      "The board they built on their Avatar Remote page for the avatar "
                      "they're wearing: toggles, hold buttons, sliders, steppers. A "
                      "locked category is for looking only. Everything you do here is "
                      "logged on both sides.")
        body = QWidget()
        body_lay = _vbox(0, 10)
        body.setLayout(body_lay)
        lay.addWidget(body)
        frame.setVisible(False)
        self._panel_w["board"] = {"fid": fid, "frame": frame, "note": note, "lay": body_lay,
                                  "key": None, "cards": {}, "boxes": {}, "yolo_open": False,
                                  "yolo_rows": {}, "yolo_filter": "", "yolo_all": False}

    def _update_friend_board(self) -> None:
        b = self._panel_w.get("board")
        if b is None:
            self._friends_watch(None)
            return
        c, fid = self.controller, b["fid"]
        theirs = c.get_friend_board(fid)
        b["frame"].setVisible(theirs is not None)
        page = self.views.get("Friends") if hasattr(self, "views") else None
        if theirs is None or page is None or not page.isVisible():
            self._friends_watch(None)            # only while you can see it
            if theirs is None:
                return
        else:
            self._friends_watch(fid, b["yolo_open"])
        prm, board = theirs["prm"], theirs["board"]
        # Rebuilt only when what is ON the board changes: a category locked
        # or renamed is set in place (a rebuild for it made the board
        # blink), and a new version waits for the board itself to arrive.
        key = (bool(prm["ver"]), prm["stop"], prm["yolo"], _shape(board), b["yolo_open"])
        if key != b["key"]:
            b["key"] = key
            self._rebuild_friend_board(b, theirs)
        elif board is not None:
            for cat in board["categories"]:
                box = b["boxes"].get(cat["id"])
                if box is not None:
                    box.set_state(cat["name"], cat["locked"], prm["stop"])
        note = (board["name"] if board and board["name"] else "")
        if prm["stop"]:
            note = (note + " · " if note else "") + "paused - they paused all friends"
        if b["note"].text() != note:
            b["note"].setText(note)
        values = theirs["values"]
        for card in b["cards"].values():
            name = card.control["param"]
            if name in values:
                card.update_value(values[name])
        for name, set_value in b["yolo_rows"].items():
            if name in values:
                set_value(values[name])

    def _rebuild_friend_board(self, b: Dict[str, Any], theirs: Dict[str, Any]) -> None:
        clear_layout(b["lay"])
        b["cards"], b["yolo_rows"], b["boxes"] = {}, {}, {}
        prm, board = theirs["prm"], theirs["board"]
        if not prm["ver"]:
            b["lay"].addWidget(self._muted_label(
                "They aren't wearing an avatar right now (VRChat isn't running on "
                "their side)."))
            return
        if board is None:
            b["lay"].addWidget(self._muted_label("Getting their board…"))
            return
        c, fid = self.controller, b["fid"]
        if not board["controls"] and board.get("all") is None:
            b["lay"].addWidget(self._muted_label(
                "Nothing on this avatar's board yet - they add controls on their "
                "Avatar Remote page."))
        for cat in board["categories"]:
            controls = [x for x in board["controls"] if x["cat"] == cat["id"]]
            if not controls:
                continue
            box = ParamCategory(cat, editable=False)
            box.hint.setProperty("hue", cat["color"])
            for control in controls:
                card = ParamCard(control, theirs["values"].get(control["param"]),
                                 hue=cat["color"], editable=False)
                card.set_value.connect(lambda cid, v: c.friend_param_set(fid, cid, v))
                card.hold.connect(lambda cid, down: c.friend_param_hold(fid, cid, down))
                box.add_card(card)
                b["cards"][control["id"]] = card
            box.finalize(stopped=prm["stop"])
            b["boxes"][cat["id"]] = box
            b["lay"].addWidget(box)
        if board.get("all") is not None:
            self._friend_board_yolo(b, board, theirs, prm["stop"])

    # ---- ⚡ YOLO: every parameter --------------------------------

    def _friend_board_yolo(self, b, board, theirs, stopped: bool) -> None:
        fid = b["fid"]
        toggle = QPushButton(("⚡ Every parameter ▾" if b["yolo_open"] else
                              f"⚡ Every parameter ({len(board['all'])}) ▸"))
        toggle.setProperty("role", "yolo")
        toggle.setCursor(Qt.PointingHandCursor)
        self._explain(toggle, "⚡ YOLO",
                      "They turned YOLO on: every parameter of their avatar is yours "
                      "to set, locks or not (VRChat's own, like Viseme, aside).")

        def fold() -> None:
            b["yolo_open"] = not b["yolo_open"]
            b["yolo_all"] = False           # folded: next time the first ones again
            b["key"] = None                 # rebuilt on the next refresh
        toggle.clicked.connect(lambda _=False: fold())
        row = _hbox(0, 8)
        row.addWidget(toggle)
        row.addStretch(1)
        b["lay"].addLayout(row)
        if not b["yolo_open"]:
            return
        filt = QLineEdit(b["yolo_filter"])
        filt.setPlaceholderText("Filter parameters…")
        b["lay"].addWidget(filt)
        rows = QWidget()
        rows_lay = _vbox(0, 2)
        rows.setLayout(rows_lay)
        b["lay"].addWidget(rows)
        # the first _YOLO_ROWS, then "N more" and Show all (every one, as
        # long as it takes to build -- their values are coming anyway)
        more_row = QWidget()
        more_lay = _hbox(0, 8)
        more_row.setLayout(more_lay)
        more = self._muted_label("")
        more_lay.addWidget(more)
        show_all = QPushButton("")
        show_all.setProperty("role", "secondary")
        show_all.setCursor(Qt.PointingHandCursor)
        more_lay.addWidget(show_all)
        more_lay.addStretch(1)
        b["lay"].addWidget(more_row)

        def fill() -> None:
            clear_layout(rows_lay)
            b["yolo_rows"] = {}
            needle = b["yolo_filter"].lower()
            match = [(n, p) for n, p in board["all"] if not needle or needle in n.lower()]
            shown = len(match) if b["yolo_all"] else _YOLO_ROWS
            for name, ptype in match[:shown]:
                rows_lay.addWidget(self._yolo_row(fid, name, ptype,
                                                  theirs["values"].get(name), b, stopped))
            extra = len(match) - shown
            more.setText(f"{extra} more - type to find them, or" if extra > 0 else "")
            show_all.setText(f"Show all {len(match)}")
            more_row.setVisible(extra > 0)

        def everything() -> None:
            b["yolo_all"] = True
            fill()
        show_all.clicked.connect(lambda _=False: everything())

        timer = QTimer(rows)
        timer.setSingleShot(True)
        timer.setInterval(200)
        timer.timeout.connect(fill)

        def typed(text: str) -> None:
            b["yolo_filter"] = text.strip()
            timer.start()
        filt.textChanged.connect(typed)
        fill()

    def _yolo_row(self, fid: str, name: str, ptype: str, value: Any, b, stopped: bool) -> QWidget:
        c = self.controller
        row_w = QWidget()
        row = _hbox(0, 8)
        row_w.setLayout(row)
        label = QLabel(name)
        label.setTextFormat(Qt.PlainText)
        label.setToolTip(f"{name} ({ptype})")
        row.addWidget(label, 1)
        if ptype == "Bool":
            sw = QPushButton("OFF")
            sw.setCheckable(True)
            sw.setProperty("role", "seg")
            sw.setProperty("hue", "accent")
            sw.setProperty("pos", "first")
            sw.setFixedWidth(56)
            busy = {"on": False}

            def show(v) -> None:
                busy["on"] = True
                sw.setChecked(bool(v))
                sw.setText("ON" if v else "OFF")
                busy["on"] = False

            def clicked(on: bool) -> None:
                sw.setText("ON" if on else "OFF")
                if not busy["on"]:
                    c.friend_param_set_any(fid, name, on)
            sw.toggled.connect(clicked)
            row.addWidget(sw)
        elif ptype == "Int":
            sw = NoWheelSpin()
            sw.setRange(0, 255)
            sw.setFixedWidth(90)
            timer = QTimer(sw)
            timer.setSingleShot(True)
            timer.setInterval(150)
            timer.timeout.connect(lambda: c.friend_param_set_any(fid, name, sw.value()))
            busy = {"on": False}

            def show(v) -> None:
                if timer.isActive() or sw.hasFocus():
                    return
                busy["on"] = True
                sw.setValue(int(v))
                busy["on"] = False
            sw.valueChanged.connect(lambda _v: None if busy["on"] else timer.start())
            row.addWidget(sw)
        else:
            sw = WheelSafeSlider(Qt.Horizontal)
            sw.setRange(-100, 100)
            sw.setFixedWidth(180)
            val = QLabel("–")
            val.setProperty("muted", "true")
            val.setFixedWidth(40)
            timer = QTimer(sw)
            timer.setSingleShot(True)
            timer.setInterval(60)
            timer.timeout.connect(lambda: c.friend_param_set_any(fid, name, sw.value() / 100))
            busy = {"on": False}

            def show(v) -> None:
                if sw.isSliderDown():
                    return
                busy["on"] = True
                sw.setValue(round(float(v) * 100))
                val.setText(f"{float(v):.2f}")
                busy["on"] = False

            def moved(x: int) -> None:
                val.setText(f"{x / 100:.2f}")
                if not busy["on"] and not timer.isActive():
                    timer.start()
            sw.valueChanged.connect(moved)
            sw.sliderReleased.connect(lambda: c.friend_param_set_any(fid, name, sw.value() / 100))
            row.addWidget(sw)
            row.addWidget(val)
        if value is not None:
            show(value)
        row_w.setDisabled(stopped)
        b["yolo_rows"][name] = lambda v, s=show: s(v) if v is not None else None
        return row_w
