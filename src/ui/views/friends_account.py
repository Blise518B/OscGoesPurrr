"""Friends view: each friend linked to their VRChat account
(controllers/friends_vrchat.py) -- three places:

* in the list, under your friends: **In your VRChat instance**, its own
  switch (read who's there from VRChat's log, off by default) and the people
  there as chips -- drag one onto a friend's row to link them;
* on a linked friend's row, a second line under the nickname: their
  VRChat name, smaller and dimmer (decided 2026-11-14; the row grows a
  little for it), and "in your instance" while they are;
* in a friend's panel, **VRChat account**: who they're linked to, and Link /
  Change folding out a picker inside the window (never a popup): the people
  in your instance and your VRChat friends from VRCX (Import from VRCX),
  with a box to find a name.

**Only friends in my instance** (controllers/friends_instance.py) lives
here too: its switch under "Read VRChat's log", "not here" on the row of a
friend it refuses (an unlinked one's points to linking them), and a
friend's **Allow from anywhere** in their VRChat account box -- both shown
only while the option is on.

Me and the Web remote have no VRChat account; control mode and the
popped-out panel leave the field out (just the controls there). Part of
FriendsMixin (friends.py), through FriendsListMixin."""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLineEdit, QPushButton, QWidget,
)

from constants import *
from remote_protocol import display_name
from ui.layout_helpers import FlowLayout as _FlowLayout, clear_layout, hbox as _hbox, vbox as _vbox
from ui.motor_signal_chain import _ElidedLabel
from ui.theme import friend_hue
from ui.widgets import ToggleSwitch

MIME_VRC = "application/x-ogp-vrchat"     # someone in your instance, dragged onto a friend
ROW_H = 34                                # a friend's row without the second line (friends_list)
HERE = "in your instance"
NOT_HERE = "not here"
NOT_HERE_LINK = "not here · link their VRChat account"
FROM_ANYWHERE = "from anywhere"
_LOG_SWITCH = "Read VRChat's log"
_INSTANCE_SWITCH = "Only friends in my instance"
_ANYWHERE_SWITCH = "Allow from anywhere"
_NOT_HERE_TIP = ("Only friends in your VRChat instance can drive you right now, and "
                 "{nick} isn't in it - nothing they send reaches you.")
_LINK_TIP = ("Only friends in your VRChat instance can drive you right now, and OGP can "
             "only see {nick} there once their VRChat account is linked: click their row, "
             "then Link… under VRChat account - or drag them from In your VRChat "
             "instance onto their row.")
WEB_NOT_HERE_TIP = ("Only friends in your VRChat instance can drive you right now, and a "
                    "browser can't be in one - your web remote is blocked. Allow the web "
                    "remote anyway is on its panel.")
_ANYWHERE_TIP = ("Allowed from anywhere: {nick} can drive you even when they aren't in "
                 "your instance.")
_INSTANCE_LIMIT = 24                      # chips in the list; more say "+N more"
# What the list's line under the chips says, by the log's state
_STATE_TEXT = {
    "off": "Off. On, the people in your VRChat instance show up here and you drag one "
           "onto a friend to link them. Read from VRChat's log on this PC; nothing "
           "leaves it.",
    "starting": "Looking for VRChat's log…",
    "reading": "Reading VRChat's log…",
    "no_log": "No VRChat log on this PC yet - start VRChat once.",
    "no_vrchat": "VRChat isn't running (or its OSC is off).",
    "no_room": "You're not in an instance right now.",
    "empty": "Nobody else is in your instance.",
    "ok": "Drag someone onto a friend's row to link them to that VRChat account.",
}
# What Import from VRCX says after a click that found no list
_VRCX_TEXT = {
    "missing": "VRCX isn't on this PC",
    "busy": "VRCX is busy - try again",
    "none": "VRCX has no friend list yet",
    "error": "VRCX's file couldn't be read",
}
_OFF_IN_PICKER = ("Who's in your instance shows here once \"Read VRChat's log\" is on, "
                  "under your friends list on the left.")


def vrc_payload(uid: str, name: str) -> bytes:
    return f"{uid}\n{name}".encode()


def read_vrc_payload(data: bytes):
    uid, _sep, name = bytes(data).decode(errors="ignore").partition("\n")
    return uid.strip(), name.strip()


class _ChipDrag(QObject):
    """Someone in your instance, as a chip, dragged onto a friend's row or
    the friend's VRChat account box."""

    def __init__(self, chip: QPushButton, uid: str, name: str):
        super().__init__(chip)
        self._chip, self._payload = chip, vrc_payload(uid, name)
        self._press = None
        chip.installEventFilter(self)

    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._press = ev.position().toPoint()
        elif t == QEvent.MouseMove and self._press is not None and ev.buttons() & Qt.LeftButton:
            if (ev.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
                hot, self._press = self._press, None
                self._chip.setDown(False)
                mime = QMimeData()
                mime.setData(MIME_VRC, self._payload)
                drag = QDrag(self._chip)
                drag.setMimeData(mime)
                drag.setPixmap(self._chip.grab())
                drag.setHotSpot(hot)
                drag.exec(Qt.LinkAction | Qt.CopyAction)
                return True
        elif t == QEvent.MouseButtonRelease:
            self._press = None
        return False


class VrcDrop(QObject):
    """A friend's row (or their VRChat account box) takes someone dragged
    from your instance -- lit up while one is over it. Everything else
    dragged over it is left alone."""

    def __init__(self, target: QWidget, on_drop: Callable[[str, str], None], repolish):
        super().__init__(target)
        self._target, self._on_drop, self._repolish = target, on_drop, repolish
        target.setAcceptDrops(True)
        target.installEventFilter(self)

    def _lit(self, on: bool) -> None:
        value = "true" if on else "false"
        if self._target.property("drop") != value:
            self._target.setProperty("drop", value)
            self._repolish(self._target)

    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t in (QEvent.DragEnter, QEvent.DragMove):
            if ev.mimeData().hasFormat(MIME_VRC):
                ev.acceptProposedAction()
                self._lit(True)
                return True
            return False
        if t == QEvent.DragLeave:
            self._lit(False)
            return False
        if t == QEvent.Drop and ev.mimeData().hasFormat(MIME_VRC):
            ev.acceptProposedAction()
            self._lit(False)
            uid, name = read_vrc_payload(ev.mimeData().data(MIME_VRC))
            if uid:
                self._on_drop(uid, name)
            return True
        return False


class _FlowBox(QWidget):
    """Chips that wrap onto more rows -- as tall as its rows need at its
    width. (The page's columns size a widget by its hint, never asking its
    height for a width, so without this a second row would be drawn over
    whatever is under it.)"""

    def __init__(self):
        super().__init__()
        self.flow = _FlowLayout(margin=0, h_spacing=6, v_spacing=6)
        self.setLayout(self.flow)

    def fit(self) -> None:
        self.flow.invalidate()
        need = self.flow.heightForWidth(max(1, self.width())) if self.flow.count() else 0
        if self.minimumHeight() != need:
            self.setMinimumHeight(need)

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self.fit()


def _relayout(*boxes: "_FlowBox") -> None:
    for box in boxes:
        box.fit()


def row_tag(f: Dict[str, Any], instance_only: bool):
    """What a friend's row says about Only friends in my instance: (text,
    label role, tooltip with {nick}) -- ("", "", "") while it has nothing
    to say. In your instance is the row's own "in your instance"."""
    if f.get("not_here"):
        if not f.get("vrc"):
            return NOT_HERE_LINK, "warning", _LINK_TIP
        return NOT_HERE, "warning", _NOT_HERE_TIP
    if instance_only and f.get("anywhere") and not f.get("here"):
        return FROM_ANYWHERE, "", _ANYWHERE_TIP
    return "", "", ""


def instance_line(st: Dict[str, Any]) -> str:
    """The line under Only friends in my instance, while it's on: how many
    friends may drive you now -- or why none may."""
    friends = [f for f in st.get("friends") or [] if not f.get("me") and not f.get("demo")]
    may = sum(1 for f in friends if not f.get("not_here"))
    anywhere = sum(1 for f in friends if f.get("anywhere"))
    vrchat = st.get("vrchat") or {}
    if not vrchat.get("log"):
        why = "Read VRChat's log is off, so nobody is seen in your instance"
    elif vrchat.get("state") == "no_vrchat":
        why = "VRChat isn't running, so nobody is in your instance"
    elif not friends:
        return "Only friends in your instance can drive you."
    else:
        return (f"Only friends in your instance can drive you - {may} of {len(friends)} "
                "can right now.")
    if anywhere:
        who = "the friend" if anywhere == 1 else f"the {anywhere} friends"
        return f"{why}: only {who} allowed from anywhere can drive you."
    return f"{why}: no friend can drive you."


def _people_key(vrchat: Dict[str, Any]):
    return (vrchat.get("state"), vrchat.get("log"),
            tuple((p["id"], p["name"], p["friend"]) for p in vrchat.get("people") or ()))


class FriendsAccountMixin:

    # ---- the list: In your VRChat instance ---------------------

    def _build_friends_instance(self, lay) -> None:
        """Under the friends: the switch and the people in your instance."""
        lay.addSpacing(6)
        row = _hbox(0, 6)
        row.addWidget(self._friends_micro("IN YOUR VRCHAT INSTANCE"))
        row.addStretch(1)
        self._vrc_log_switch = ToggleSwitch(_LOG_SWITCH)
        self._vrc_log_switch.toggled.connect(
            lambda on: (self.controller.set_friends_vrc_log(bool(on)), self.refresh_friends()))
        row.addWidget(self._vrc_log_switch)
        lay.addLayout(row)
        self._explain(self._vrc_log_switch, "Read VRChat's log",
                      "On: OGP reads who's in your VRChat instance from VRChat's own log "
                      "on this PC, to link friends to their VRChat accounts. They show "
                      "up here as chips you drag onto a friend; a linked friend's row "
                      "then says when they're in your instance.<br><br>Nothing leaves "
                      "your PC, and no friend is ever told who's with you. Off by "
                      "default; People statistics has its own switch for the same log. "
                      "Switched off while Only friends in my instance is on, nobody can "
                      "be seen in your instance - so no friend can drive you.")
        # only friends in my instance (controllers/friends_instance.py)
        row = _hbox(0, 6)
        row.addStretch(1)
        self._inst_switch = ToggleSwitch(_INSTANCE_SWITCH)
        self._inst_switch.toggled.connect(
            lambda on: (self.controller.set_friends_instance_only(bool(on)),
                        self.refresh_friends()))
        row.addWidget(self._inst_switch)
        lay.addLayout(row)
        self._explain(self._inst_switch, _INSTANCE_SWITCH,
                      "On: only friends who are in your VRChat instance right now can drive "
                      "you. Everyone else shows \"not here\" on their row and nothing they "
                      "send reaches you - toys, shockers or your avatar - as with Pause all "
                      "friends; if one leaves, whatever they had going stops at "
                      "once.<br><br>Switching it on also switches on Read VRChat's log: OGP "
                      "needs it to see who's here, and sees a friend there once you've "
                      "linked their VRChat account (an unlinked friend counts as not here). "
                      "Only your own log decides: nothing new is sent to anyone, and where "
                      "you are never leaves your PC.<br><br>You (Me) can always drive "
                      "yourself, a friend's Allow from anywhere lets them in from anywhere, "
                      "and the web remote has its own switch on its panel - a browser can't "
                      "be in an instance. With the log off or VRChat closed, no friend is in "
                      "your instance. Off by default.")
        self._inst_lbl = QLabel("")
        self._inst_lbl.setProperty("hint", "true")
        self._inst_lbl.setWordWrap(True)
        self._inst_lbl.setVisible(False)
        lay.addWidget(self._inst_lbl)
        self._vrc_chips_box = _FlowBox()
        self._vrc_chips = self._vrc_chips_box.flow
        self._vrc_chips.setContentsMargins(0, 2, 0, 2)
        self._vrc_chips_box.setVisible(False)
        lay.addWidget(self._vrc_chips_box)
        self._vrc_state_lbl = QLabel("")
        self._vrc_state_lbl.setProperty("hint", "true")
        self._vrc_state_lbl.setWordWrap(True)
        lay.addWidget(self._vrc_state_lbl)
        self._vrc_people_key: Any = None

    def _update_friends_instance(self, st: Dict[str, Any]) -> None:
        if not hasattr(self, "_vrc_log_switch"):
            return
        vrchat = st.get("vrchat") or {}
        on = bool(vrchat.get("log"))
        if self._vrc_log_switch.isChecked() != on:
            self._vrc_log_switch.blockSignals(True)
            self._vrc_log_switch.setChecked(on)
            self._vrc_log_switch.blockSignals(False)
        self._update_instance_only(st)
        key = (_people_key(vrchat), tuple(f["id"] for f in st["friends"]))
        if key == self._vrc_people_key:
            return
        self._vrc_people_key = key
        people = vrchat.get("people") or []
        state = vrchat.get("state", "off" if not on else "starting")
        if state == "ok" and not people:
            state = "empty"
        text = _STATE_TEXT.get(state, "")
        if self._vrc_state_lbl.text() != text:
            self._vrc_state_lbl.setText(text)
        self._vrc_state_lbl.setVisible(bool(text))
        self._fill_instance_chips(people, st)

    def _update_instance_only(self, st: Dict[str, Any]) -> None:
        """Only friends in my instance: its switch, and the line under it
        saying how many friends may drive you now."""
        sw = getattr(self, "_inst_switch", None)
        if sw is None:
            return
        on = bool((st.get("instance") or {}).get("on"))
        if sw.isChecked() != on:
            sw.blockSignals(True)
            sw.setChecked(on)
            sw.blockSignals(False)
        text = instance_line(st) if on else ""
        if self._inst_lbl.text() != text:
            self._inst_lbl.setText(text)
        self._inst_lbl.setVisible(bool(text))

    @staticmethod
    def _vrc_friend_label(fid: str, st: Dict[str, Any]) -> str:
        f = next((x for x in st["friends"] if x["id"] == fid), None)
        return display_name(f["nick"], fid) if f is not None else ""

    def _fill_instance_chips(self, people: List[Dict[str, Any]], st: Dict[str, Any]) -> None:
        clear_layout(self._vrc_chips)
        index = {f["id"]: i for i, f in enumerate(st["friends"])}
        for p in people[:_INSTANCE_LIMIT]:
            chip = QPushButton(p["name"])
            chip.setProperty("role", "chip")
            chip.setCursor(Qt.OpenHandCursor)
            linked = p["friend"] in index
            if linked:
                # linked: in their row's colour, ticked
                chip.setProperty("hue", friend_hue(index[p["friend"]]))
                chip.setCheckable(True)
                chip.setChecked(True)
                chip.setToolTip(f"Linked to {self._vrc_friend_label(p['friend'], st)} - drag "
                                "onto another friend to move the link")
            else:
                chip.setToolTip("Drag onto a friend's row to link them to this VRChat account")
            # a click does nothing: dragging is the way (a click mustn't untick it)
            chip.clicked.connect(lambda _=False, c=chip, on=linked: c.setChecked(on))
            _ChipDrag(chip, p["id"], p["name"])
            self._vrc_chips.addWidget(chip)
        more = len(people) - _INSTANCE_LIMIT
        if more > 0:
            hint = QLabel(f"+{more} more - in a friend's VRChat account picker")
            hint.setProperty("hint", "true")
            self._vrc_chips.addWidget(hint)
        self._vrc_chips_box.setVisible(bool(people))
        _relayout(self._vrc_chips_box)

    # ---- a friend's row: their VRChat name, and "in your instance" ----

    def _friend_row_vrc_line(self, f: Dict[str, Any]) -> QWidget:
        """The row's second line, across the whole row under the name: their
        VRChat name (small, muted) and "in your instance" -- only shown while
        they're linked."""
        line = QWidget()
        h = _hbox(0, 6)
        h.setContentsMargins(28, 0, 0, 1)      # under the name, past the badge
        line.setLayout(h)
        # a long VRChat name gives way ("…") so "in your instance" always shows.
        # Smaller and less bright than the nickname: the theme's muted label
        # (Blise's call, 2026-11-14: below it, never next to it)
        name = _ElidedLabel("")
        name.setProperty("muted", "true")
        name.setTextFormat(Qt.PlainText)
        h.addWidget(name, 1)
        here = QLabel(HERE)
        here.setProperty("muted", "true")             # its size; the colour is success's
        here.setProperty("role", "success")
        here.setVisible(False)
        h.addWidget(here)
        # only friends in my instance: "not here" (an unlinked friend's says
        # to link them), or "from anywhere" for their exception
        tag = QLabel("")
        tag.setProperty("muted", "true")
        tag.setVisible(False)
        h.addWidget(tag)
        h.addStretch(1)
        line.vrc_name, line.vrc_here, line.vrc_tag = name, here, tag
        line.setVisible(False)
        return line

    def _update_friend_row_vrc(self, r: Dict[str, Any], f: Dict[str, Any],
                               instance_only: bool = False) -> None:
        line = r.get("vrc")
        if line is None:
            return
        shown = f.get("vrc_name", "") if f.get("vrc") else ""
        if line.vrc_name.full_text() != shown:
            line.vrc_name.set_full_text(shown)
            # never wider than the name: the rest of the line stays free (in
            # its own small font, so polished first)
            line.vrc_name.ensurePolished()
            line.vrc_name.setMaximumWidth(line.vrc_name.fontMetrics().horizontalAdvance(shown) + 6)
            line.vrc_name.setToolTip(f"Their VRChat account: {shown}" if shown else "")
        # no account: no name, so a "not here" line starts under the nickname
        line.vrc_name.setVisible(bool(shown))
        here = bool(f.get("here")) and bool(shown)
        line.vrc_here.setVisible(here)
        tag, role, tip = row_tag(f, instance_only)
        tip = tip.format(nick=display_name(f.get("nick", ""), f["id"]))
        if line.vrc_tag.text() != tag or (line.vrc_tag.property("role") or "") != role:
            line.vrc_tag.setText(tag)
            line.vrc_tag.setProperty("role", role)
            self._repolish(line.vrc_tag)
        if line.vrc_tag.toolTip() != tip:
            line.vrc_tag.setToolTip(tip)
        line.vrc_tag.setVisible(bool(tag))
        shows = bool(shown) or bool(tag)
        line.setVisible(shows)
        # the row grows by the line (its own minimum would squeeze the boxes)
        btn = r["btn"]
        tall = ROW_H + (line.sizeHint().height() - 6 if shows else 0)
        if btn.minimumHeight() != tall:
            btn.setMinimumHeight(tall)

    def _friend_row_vrc_drop(self, btn: QPushButton, fid: str) -> None:
        VrcDrop(btn, lambda uid, name, i=fid: self._on_vrc_link(i, uid, name), self._repolish)

    def _on_vrc_link(self, fid: str, uid: str, name: str) -> None:
        self.controller.link_friend_vrchat(fid, uid, name)
        if getattr(self, "_vrc_pick_for", None) == fid:
            self._vrc_pick_for = None            # the picker did its job
        self._friends_panel_key = None
        self.refresh_friends()

    # ---- a friend's panel: VRChat account ----------------------

    def _vrc_field_wanted(self, f: Dict[str, Any]) -> bool:
        return not (f.get("me") or f.get("demo") or self._friends_big
                    or getattr(self, "_friends_popped", False))

    def _build_friend_vrchat(self, f: Dict[str, Any]) -> None:
        """The friend's VRChat account: who they're linked to, Link / Change
        (a picker folding out in the panel) and Unlink."""
        w = self._panel_w
        if not self._vrc_field_wanted(f):
            return
        fid = f["id"]
        box = QFrame()
        box.setObjectName("vrcAccount")
        bl = _vbox(0, 6)
        box.setLayout(bl)
        row = _hbox(0, 8)
        row.addWidget(self._friends_micro("VRCHAT ACCOUNT"))
        name = QLabel("")
        name.setTextFormat(Qt.PlainText)
        row.addWidget(name)
        here = QLabel(HERE)
        here.setProperty("role", "success")
        here.setVisible(False)
        row.addWidget(here)
        not_here = QLabel(NOT_HERE)               # only friends in my instance
        not_here.setProperty("role", "warning")
        not_here.setVisible(False)
        row.addWidget(not_here)
        row.addStretch(1)
        pick = QPushButton("Link…")
        pick.setProperty("role", "ghost")
        pick.setCursor(Qt.PointingHandCursor)
        pick.clicked.connect(lambda _=False: self._toggle_vrc_picker(fid))
        row.addWidget(pick)
        unlink = QPushButton("Unlink")
        unlink.setProperty("role", "ghost")
        unlink.setProperty("muted", "true")
        unlink.setCursor(Qt.PointingHandCursor)
        unlink.clicked.connect(lambda _=False: (self.controller.unlink_friend_vrchat(fid),
                                                self.refresh_friends()))
        row.addWidget(unlink)
        bl.addLayout(row)
        # their exception while only friends in your instance may drive you:
        # shown only while that's on
        anywhere = ToggleSwitch(_ANYWHERE_SWITCH)
        anywhere.setChecked(bool(f.get("anywhere")))
        anywhere.toggled.connect(lambda on: (self.controller.set_friend_anywhere(fid, bool(on)),
                                             self.refresh_friends()))
        anywhere.setVisible(False)
        arow = _hbox(0, 8)
        arow.addWidget(anywhere)
        arow.addStretch(1)
        bl.addLayout(arow)
        self._explain(anywhere, _ANYWHERE_SWITCH,
                      "On: this friend can drive you even when they aren't in your VRChat "
                      "instance, while Only friends in my instance is on. Everything else "
                      "still holds - their switches, Pause all friends, Off, your strength "
                      "and every shocker limit. Off for a new friend.")
        self._explain(box, "VRChat account",
                      "Which VRChat account this friend is, so OGP can tell when they're "
                      "in your instance. Pick them from the people in your instance or "
                      "from your VRChat friends in VRCX - or drag them from In your "
                      "VRChat instance onto here or onto their row.<br><br>Kept on this "
                      "PC by their VRChat user id, so a new display name doesn't break "
                      "it. Never sent to them or anyone else.")
        self._explain(unlink, "Unlink",
                      "Forgets which VRChat account this friend is. They stay your friend.")
        picker = self._build_vrc_picker(fid)
        bl.addWidget(picker)
        VrcDrop(box, lambda uid, nm, i=fid: self._on_vrc_link(i, uid, nm), self._repolish)
        self._panel_lay.addWidget(box)
        w["vrc"] = {"fid": fid, "box": box, "name": name, "here": here, "pick": pick,
                    "unlink": unlink, "picker": picker, "key": None, "not_here": not_here,
                    "anywhere": anywhere}
        self._update_friend_vrchat(f, None)

    def _build_vrc_picker(self, fid: str) -> QFrame:
        fold = QFrame()
        fold.setObjectName("vrcPicker")
        fl = _vbox(0, 6)
        fl.setContentsMargins(12, 10, 12, 12)
        fold.setLayout(fl)
        row = _hbox(0, 6)
        search = QLineEdit(getattr(self, "_vrc_pick_query", ""))
        search.setPlaceholderText("find a name")
        search.setClearButtonEnabled(True)
        search.textChanged.connect(lambda text: self._on_vrc_search(text))
        row.addWidget(search, 1)
        vrcx = QPushButton("Import from VRCX")
        vrcx.setProperty("role", "secondary")
        vrcx.setMinimumHeight(BTN_HEIGHT_SMALL)
        vrcx.setCursor(Qt.PointingHandCursor)
        vrcx.clicked.connect(lambda _=False: self._on_vrcx_import())
        row.addWidget(vrcx)
        fl.addLayout(row)
        self._explain(vrcx, "Import from VRCX",
                      "Reads your VRChat friends' names from VRCX, the VRChat companion "
                      "app, so you can pick this friend among them. Only when you click, "
                      "read-only - VRCX's file is never changed - and kept only until "
                      "OGP closes.")
        fl.addWidget(self._friends_micro("IN YOUR INSTANCE"))
        here_box = _FlowBox()
        here_flow = here_box.flow
        fl.addWidget(here_box)
        here_hint = self._vrc_hint("")
        fl.addWidget(here_hint)
        vrcx_head = self._friends_micro("YOUR VRCHAT FRIENDS (VRCX)")
        fl.addWidget(vrcx_head)
        vrcx_box = _FlowBox()
        vrcx_flow = vrcx_box.flow
        fl.addWidget(vrcx_box)
        vrcx_hint = self._vrc_hint("")
        fl.addWidget(vrcx_hint)
        row = _hbox(0, 6)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("role", "ghost")
        cancel.clicked.connect(lambda _=False: self._toggle_vrc_picker(fid))
        row.addWidget(cancel)
        fl.addLayout(row)
        fold.search, fold.vrcx_btn = search, vrcx
        fold.here_flow, fold.vrcx_flow, fold.vrcx_head = here_flow, vrcx_flow, vrcx_head
        fold.here_box, fold.vrcx_box = here_box, vrcx_box
        fold.here_hint, fold.vrcx_hint = here_hint, vrcx_hint
        fold.setVisible(getattr(self, "_vrc_pick_for", None) == fid)
        return fold

    def _toggle_vrc_picker(self, fid: str) -> None:
        opening = getattr(self, "_vrc_pick_for", None) != fid
        self._vrc_pick_for = fid if opening else None
        v = self._panel_w.get("vrc")
        if v is None or v["fid"] != fid:
            return
        v["picker"].setVisible(opening)
        v["key"] = None
        if opening:
            self._fill_vrc_picker(v)
            v["picker"].search.setFocus()
        self._update_vrc_buttons(v, bool(v["unlink"].isVisible()))

    def _on_vrc_search(self, text: str) -> None:
        self._vrc_pick_query = text
        v = self._panel_w.get("vrc")
        if v is not None:
            v["key"] = None
            self._fill_vrc_picker(v)

    def _on_vrcx_import(self) -> None:
        got = self.controller.import_vrcx_friends() or {}
        v = self._panel_w.get("vrc")
        if v is None:
            return
        state = got.get("state", "")
        btn = v["picker"].vrcx_btn
        if state in _VRCX_TEXT and not got.get("count"):
            btn.setText(_VRCX_TEXT[state])
            btn.setEnabled(state == "busy")
        v["key"] = None
        self._fill_vrc_picker(v)

    def _vrc_choice_chip(self, fid: str, p: Dict[str, Any], flow) -> None:
        mine = p.get("friend") == fid
        other = "" if mine else getattr(self, "_vrc_nicks", {}).get(p.get("friend"), "")
        chip = QPushButton(f"{p['name']} ({other})" if other else p["name"])
        chip.setProperty("role", "chip")
        chip.setProperty("row", "main")
        chip.setCursor(Qt.PointingHandCursor)
        chip.setCheckable(True)
        chip.setChecked(mine)
        if mine:
            chip.setToolTip("Linked to this friend")
        elif p.get("friend"):
            chip.setToolTip(f"Linked to {other or 'another friend'} - picking it here moves "
                            "the link")
        else:
            chip.setToolTip("Link this friend to this VRChat account")
        chip.clicked.connect(lambda _=False, u=p["id"], n=p["name"]: self._on_vrc_link(fid, u, n))
        flow.addWidget(chip)

    def _fill_vrc_picker(self, v: Dict[str, Any]) -> None:
        picker = v["picker"]
        if getattr(self, "_vrc_pick_for", None) != v["fid"]:
            return
        got = self.controller.get_vrchat_choices(getattr(self, "_vrc_pick_query", "")) or {}
        key = (got.get("state"), got.get("vrcx_state"), got.get("vrcx_count"),
               tuple((p["id"], p["friend"]) for p in got.get("instance") or ()),
               tuple((p["id"], p["friend"]) for p in got.get("vrcx") or ()), got.get("vrcx_more"))
        if key == v["key"]:
            return
        v["key"] = key
        fid = v["fid"]
        for flow in (picker.here_flow, picker.vrcx_flow):
            clear_layout(flow)
        state = got.get("state", "off")
        here_text = ""
        if not got.get("log"):
            here_text = _OFF_IN_PICKER
        elif got.get("instance"):
            for p in got["instance"]:
                self._vrc_choice_chip(fid, p, picker.here_flow)
        else:
            here_text = _STATE_TEXT["empty"] if state == "ok" else _STATE_TEXT.get(state, "")
            if getattr(self, "_vrc_pick_query", "") and state == "ok":
                here_text = "Nobody in your instance by that name."
        picker.here_box.setVisible(bool(got.get("instance")) and bool(got.get("log")))
        picker.here_hint.setText(here_text)
        picker.here_hint.setVisible(bool(here_text))
        count = int(got.get("vrcx_count") or 0)
        picker.vrcx_head.setText(f"YOUR VRCHAT FRIENDS (VRCX, {count})" if count
                                 else "YOUR VRCHAT FRIENDS (VRCX)")
        btn = picker.vrcx_btn
        if count:
            btn.setText("Import again")
            btn.setEnabled(True)
        elif not got.get("vrcx_installed", True):
            btn.setText(_VRCX_TEXT["missing"])
            btn.setEnabled(False)
        more = int(got.get("vrcx_more") or 0)
        if got.get("vrcx"):
            for p in got["vrcx"]:
                self._vrc_choice_chip(fid, p, picker.vrcx_flow)
            vrcx_text = f"+{more} more - type part of a name to find them." if more else ""
        elif count:
            vrcx_text = "No VRChat friend by that name."
        elif not got.get("vrcx_installed", True):
            vrcx_text = "VRCX isn't on this PC. Pick them from your instance instead."
        else:
            vrcx_text = "Import from VRCX to pick from your VRChat friends."
        picker.vrcx_box.setVisible(bool(got.get("vrcx")))
        picker.vrcx_hint.setText(vrcx_text)
        picker.vrcx_hint.setVisible(bool(vrcx_text))
        _relayout(picker.here_box, picker.vrcx_box)

    @staticmethod
    def _vrc_hint(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("hint", "true")
        lbl.setWordWrap(True)
        return lbl

    def _update_vrc_buttons(self, v: Dict[str, Any], linked: bool) -> None:
        open_ = getattr(self, "_vrc_pick_for", None) == v["fid"]
        text = "Close" if open_ else ("Change…" if linked else "Link…")
        if v["pick"].text() != text:
            v["pick"].setText(text)
        v["unlink"].setVisible(linked and not open_)

    def _update_friend_vrchat(self, f: Dict[str, Any], st: Optional[Dict[str, Any]]) -> None:
        v = self._panel_w.get("vrc")
        if v is None or v["fid"] != f["id"]:
            return
        linked = bool(f.get("vrc"))
        text = (f.get("vrc_name", "") or "linked") if linked else "Not linked yet"
        if v["name"].text() != text:
            v["name"].setText(text)
            v["name"].setProperty("muted", "false" if linked else "true")
            self._repolish(v["name"])
        v["here"].setVisible(linked and bool(f.get("here")))
        v["not_here"].setVisible(bool(f.get("not_here")))
        if v["anywhere"].isChecked() != bool(f.get("anywhere")):
            v["anywhere"].blockSignals(True)
            v["anywhere"].setChecked(bool(f.get("anywhere")))
            v["anywhere"].blockSignals(False)
        self._update_vrc_buttons(v, linked)
        if st is not None:
            v["anywhere"].setVisible(bool((st.get("instance") or {}).get("on")))
            # whose a chip is, by the names the list shows
            self._vrc_nicks = {x["id"]: display_name(x["nick"], x["id"])
                               for x in st["friends"] if not x.get("me")}
            if getattr(self, "_vrc_pick_for", None) == f["id"]:
                self._fill_vrc_picker(v)
