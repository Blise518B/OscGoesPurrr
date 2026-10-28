"""Friends view, the left column: you (nickname, Online, Pause all), Add a
friend -- one button that folds out an invite link (pick how long it works,
Copy), your ID with its own Copy and a box for their link or ID -- and under
it Copy web remote link, for someone without OGP; your friends with their
toys / shocks / avatar boxes (you
always first, then the Web remote row once you have its link), and groups
(drag a friend onto one to add them; right-click to rename or delete it).
Part of FriendsMixin (friends.py)."""

from typing import Any, Callable, Dict

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt, QTimer
from PySide6.QtGui import QDrag, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
    QPushButton, QWidget,
)

from constants import *
from remote_protocol import display_name
from ui.layout_helpers import clear_layout, vbox as _vbox, hbox as _hbox
from controllers.friends_common import WEB
from ui.theme import FRIEND_SHOCK_HUE as _SHOCK, FRIEND_TOYS_HUE as _TOYS, FRIENDS_HUE, friend_hue
from ui.motor_signal_chain import _ElidedLabel
from ui.views.card_parts import segmented
from ui.widgets import Card as _Card, IdentityMark, ToggleSwitch

LIST_W = 350         # the left column (room for the permission columns)
MONO = "font-family: 'Cascadia Mono', Consolas, monospace;"
# How long an invite link works (settings.friends.INVITE_KINDS): its
# choice, and what it means
_INVITE_KINDS = (
    ("once", "Once", "Works once - the first friend who clicks it, within a day."),
    ("day", "1 day", "Anyone who clicks it within a day becomes your friend."),
    ("week", "1 week", "Anyone who clicks it within a week becomes your friend."),
    ("forever", "No end", "Anyone who clicks it becomes your friend, until you close "
                          "your links (⋯)."),
)
MIME_FRIEND = "application/x-ogp-friend"     # a friend's row, dragged onto a group
_COPY_LINK = "Copy invite link"
# The two ways in, one under the other, each saying who needs OGP
_ADD_FRIEND = "Add a friend (they need OGP too)"
_COPY_WEB = "Copy web remote link (no OGP needed)"
_COPY_ID = "Copy"
_ADD_HINT = "An invite link links you at once; with a bare ID they click Accept in their OGP."
# The Web remote row's boxes: (hue, what the box lets everyone on the link do)
_WEB_BOXES = {
    "toys": (_TOYS, "Everyone on your web remote may drive your toys and move your "
                    "strength slider"),
    "shock": (_SHOCK, "Everyone on your web remote may fire your shockers (a vibrate "
                      "until you arm shocks on the Shockers page)"),
    "params": ("accent", "Everyone on your web remote may see and use the board of the "
                         "avatar you're wearing"),
}


# The three permission columns (toys / shocks / avatar): the same width in
# the header and on every row, each box centred under its label.
PERM_COL_W = 46
_ROW_MARGIN = 4               # a row's margin + border + the box's own inset, mirrored by the header


def web_guests_tip(web: Dict[str, Any]) -> str:
    """Who is on your web remote, by name -- the row's and the panel's hover."""
    names = [g["nick"] for g in web.get("guests") or []]
    if not web.get("on"):
        return "Your web remote is off - nobody gets in"
    return ("On your web remote now: " + ", ".join(names)) if names else \
        "Nobody is on your web remote right now"


class _ColumnHead(QLabel):
    """A column's icon (toys / shock / params) that, clicked, sets that
    column for every friend."""

    def __init__(self, what: str, on_click: Callable[[], None]):
        super().__init__()
        self._on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        lay = _hbox(0, 0)
        lay.addWidget(IdentityMark(what, 16), 0, Qt.AlignCenter)
        self.setLayout(lay)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._on_click()
            ev.accept()
        else:
            super().mousePressEvent(ev)


class _FriendDrag(QObject):
    """A friend's row can be dragged (onto a group); a plain click still
    picks the friend."""

    def __init__(self, row: QPushButton, fid: str):
        super().__init__(row)
        self._row, self._fid = row, fid
        self._press = None
        row.installEventFilter(self)

    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t == QEvent.MouseButtonPress and ev.button() == Qt.LeftButton:
            self._press = ev.position().toPoint()
        elif t == QEvent.MouseMove and self._press is not None and ev.buttons() & Qt.LeftButton:
            if (ev.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance():
                hot, self._press = self._press, None
                self._row.setDown(False)
                mime = QMimeData()
                mime.setData(MIME_FRIEND, self._fid.encode())
                drag = QDrag(self._row)
                drag.setMimeData(mime)
                drag.setPixmap(self._row.grab())
                drag.setHotSpot(hot)
                drag.exec(Qt.CopyAction)
                return True
        elif t == QEvent.MouseButtonRelease:
            self._press = None
        return False


class _GroupDrop(QObject):
    """A group's row takes a friend dropped on it -- lit up while one is
    over it."""

    def __init__(self, row: QPushButton, on_drop: Callable[[str], None], repolish):
        super().__init__(row)
        self._row, self._on_drop, self._repolish = row, on_drop, repolish
        row.setAcceptDrops(True)
        row.installEventFilter(self)

    def _lit(self, on: bool) -> None:
        value = "true" if on else "false"
        if self._row.property("drop") != value:
            self._row.setProperty("drop", value)
            self._repolish(self._row)

    def eventFilter(self, obj, ev):  # noqa: N802
        t = ev.type()
        if t in (QEvent.DragEnter, QEvent.DragMove) and ev.mimeData().hasFormat(MIME_FRIEND):
            ev.acceptProposedAction()
            self._lit(True)
            return True
        if t == QEvent.DragLeave:
            self._lit(False)
            return True
        if t == QEvent.Drop and ev.mimeData().hasFormat(MIME_FRIEND):
            ev.acceptProposedAction()
            self._lit(False)
            self._on_drop(bytes(ev.mimeData().data(MIME_FRIEND)).decode())
            return True
        return False


class FriendsListMixin:

    _friend_rows: Dict[str, Dict[str, Any]] = {}
    _group_rows: Dict[str, QPushButton] = {}

    def _build_friends_list_column(self) -> QFrame:
        card = _Card()
        card.setFixedWidth(LIST_W)
        lay = _vbox(14, 6)
        card.setLayout(lay)

        # You
        row = _hbox(0, 6)
        self._friends_nick_edit = QLineEdit()
        self._friends_nick_edit.setMaxLength(24)
        self._friends_nick_edit.setPlaceholderText("your nickname")
        self._friends_nick_edit.editingFinished.connect(self._on_friends_nick_done)
        row.addWidget(self._friends_nick_edit, 1)
        self._friends_state_pill = self._friends_pill()
        row.addWidget(self._friends_state_pill)
        lay.addLayout(row)
        self._explain(self._friends_nick_edit, "Your nickname",
                      "What your friends see you as. Change it any time - they "
                      "see the new one.")
        row = _hbox(0, 8)
        self._friends_online = ToggleSwitch("Online")
        self._friends_online.toggled.connect(
            lambda on: self.controller.set_friends_online(bool(on)))
        row.addWidget(self._friends_online)
        self._explain(self._friends_online, "Online",
                      "Off: Friends uses no network at all - nobody can reach "
                      "you and you reach nobody. On: you link with friends who "
                      "have OGP open; nothing is sent while nobody does "
                      "anything except a tiny keepalive.")
        row.addStretch(1)
        self._friends_pause = ToggleSwitch("Pause all")
        self._friends_pause.toggled.connect(
            lambda on: self.controller.set_friends_paused(bool(on)))
        row.addWidget(self._friends_pause)
        self._explain(self._friends_pause, "Pause all friends",
                      "While on, nothing any friend sends reaches your toys, "
                      "your strength slider or your shockers. They stay linked "
                      "and see that you paused. Off (top left) silences friends "
                      "too.")
        lay.addLayout(row)
        # Add a friend: one button; the invite link, your ID and the box for
        # theirs fold out under it (open by itself while you have no friends)
        lay.addSpacing(4)
        self._friends_add_toggle = QPushButton()
        self._friends_add_toggle.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._friends_add_toggle.setProperty("role", "secondary")
        self._friends_add_toggle.setCursor(Qt.PointingHandCursor)
        self._friends_add_toggle.clicked.connect(
            lambda _=False: self._set_friends_add_open(not self._friends_add_open))
        lay.addWidget(self._friends_add_toggle)
        self._explain(self._friends_add_toggle, "Add a friend",
                      "For a friend who has OGP too: send an invite link, copy your "
                      "ID, or paste theirs. Folds away again once you have a friend.")
        fold = QFrame()
        fold.setObjectName("moreSection")
        fl = _vbox(0, 6)
        fold.setLayout(fl)
        self._friends_add_fold = fold
        fl.addWidget(self._friends_micro("SEND AN INVITE LINK"))
        self._friends_invite_kind = "once"
        kinds, self._friends_invite_group = segmented(
            [label for _k, label, _t in _INVITE_KINDS], "accent", self._on_friends_invite_kind)
        self._explain(kinds, "How long the link works",
                      "Once: the first friend who clicks it, within a day. 1 day / "
                      "1 week: anyone who clicks it in that time. No end: anyone, "
                      "until you close your links (⋯). Whoever comes with a live "
                      "link is your friend at once - nobody clicks Accept.")
        fl.addWidget(kinds)
        self._friends_invite_note = self._muted_label(_INVITE_KINDS[0][2])
        fl.addWidget(self._friends_invite_note)
        row = _hbox(0, 6)
        self._friends_invite_btn = QPushButton(_COPY_LINK)
        self._friends_invite_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._friends_invite_btn.setProperty("role", "secondary")
        self._friends_invite_btn.clicked.connect(lambda _=False: self._on_friends_invite())
        row.addWidget(self._friends_invite_btn, 1)
        self._explain(self._friends_invite_btn, "Copy invite link",
                      "Copies a link to paste into Discord. Your friend clicks "
                      "it, OGP opens on their PC and you're friends.")
        more = QPushButton("⋯")
        more.setProperty("role", "mini")
        more.setProperty("wide", "true")
        more.setFixedSize(30, 28)
        more.setToolTip("Close your invite links, or get a new ID")
        self._friends_invite_menu = self._build_invite_menu(more)
        more.clicked.connect(lambda _=False: self._friends_invite_menu.exec(
            more.mapToGlobal(more.rect().bottomLeft())))
        row.addWidget(more)
        fl.addLayout(row)
        # ... and the bare ID, for pasting into a friend's box
        row = _hbox(0, 6)
        self._friends_id_lbl = QLabel("")
        self._friends_id_lbl.setProperty("muted", "true")
        self._friends_id_lbl.setStyleSheet(MONO)
        row.addWidget(self._friends_id_lbl, 1)
        self._friends_copy_btn = QPushButton(_COPY_ID)
        self._friends_copy_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._friends_copy_btn.setProperty("role", "ghost")
        self._friends_copy_btn.clicked.connect(self._on_friends_copy)
        row.addWidget(self._friends_copy_btn)
        self._explain(self._friends_id_lbl, "Your ID",
                      "Your bare ID, for a friend to paste under Add a friend; "
                      "you click Accept when they ask. It stays the same every "
                      "time you open OGP and is not a password: someone who has "
                      "it can only ask to be your friend.")
        fl.addLayout(row)
        self._friends_my_id = ""
        # ... or theirs, pasted here
        fl.addSpacing(4)
        fl.addWidget(self._friends_micro("GOT THEIR LINK OR ID?"))
        row = _hbox(0, 6)
        self._friends_add_edit = QLineEdit()
        self._friends_add_edit.setPlaceholderText("invite link or ID")
        self._friends_add_edit.setStyleSheet(MONO)
        self._friends_add_edit.returnPressed.connect(self._on_friends_add)
        row.addWidget(self._friends_add_edit, 1)
        self._friends_add_btn = QPushButton("Add")
        self._friends_add_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._friends_add_btn.setProperty("role", "primary")
        self._friends_add_btn.clicked.connect(self._on_friends_add)
        row.addWidget(self._friends_add_btn)
        fl.addLayout(row)
        self._friends_add_hint = self._muted_label(_ADD_HINT)
        fl.addWidget(self._friends_add_hint)
        fl.addSpacing(8)                    # the web remote below isn't part of it
        lay.addWidget(fold)
        self._friends_add_open = False
        self._set_friends_add_open(False)
        # ... and under it, for someone without OGP: the web remote
        # (controllers/friends_web.py) -- a thing of its own, so never inside
        # the fold (Blise's call, 2026-10-28)
        self._friends_web_btn = QPushButton(_COPY_WEB)
        self._friends_web_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._friends_web_btn.setProperty("role", "secondary")
        self._friends_web_btn.setCursor(Qt.PointingHandCursor)
        self._friends_web_btn.clicked.connect(lambda _=False: self._on_friends_web_copy())
        lay.addWidget(self._friends_web_btn)
        self._explain(self._friends_web_btn, "Web remote",
                      "A link anyone can open in a browser to drive your toys - no "
                      "OGP, no account. Your shockers and your avatar only once you "
                      "tick them on the Web remote row in your list, where you also "
                      "see who is on it, kick someone, or switch it off.")
        self._friends_fold_n = None         # real friends when last rebuilt (None: not yet)
        self._friends_asking_lbl = QLabel("")
        self._friends_asking_lbl.setWordWrap(True)
        self._friends_asking_lbl.setProperty("role", "warning")
        lay.addWidget(self._friends_asking_lbl)

        # Friends
        lay.addSpacing(6)
        row = _hbox(0, 6)
        row.addWidget(self._friends_micro("FRIENDS"))
        row.addStretch(1)
        # the column labels, each centred over its column of boxes; a click
        # sets that column for everyone (off first while any has it)
        heads = QWidget()
        hl = _hbox(0, 0)
        hl.setContentsMargins(0, 0, _ROW_MARGIN, 0)
        heads.setLayout(hl)
        self._friends_heads = {}
        # each icon explains its own column (Blise's ask, 2026-10-28: one
        # text for all three read the same on every icon)
        every = ("<br><br>Click the icon to set it for every friend at once: off "
                 "while anyone has it, on again with the next click.")
        explains = {
            "toys": ("Toys",
                     "The box under the toy lets that friend drive your toys and move "
                     "your strength slider - never past your strength, Off or each "
                     "toy's own output band."),
            "shock": ("Shockers",
                      "The box under the bolt lets that friend fire your shockers - "
                      "only a vibrate until you arm shocks on the Shockers page, and "
                      "always within each shocker's own limits."),
            "params": ("Avatar Remote",
                       "With Avatar Remote on, the box under the remote lets that "
                       "friend see and use the board of the avatar you're wearing. A "
                       "locked category stays look-only."),
        }
        for what in ("toys", "shock", "params"):
            head = _ColumnHead(what, lambda w=what: self._on_friends_column(w))
            head.setFixedSize(PERM_COL_W, 20)
            hl.addWidget(head)
            self._friends_heads[what] = head
            title, text = explains[what]
            self._explain(head, title, text + every)
        self._friends_avatar_head = self._friends_heads["params"]
        row.addWidget(heads)
        lay.addLayout(row)
        self._friends_rows_box = QWidget()
        self._friends_rows_lay = _vbox(0, 1)
        self._friends_rows_box.setLayout(self._friends_rows_lay)
        lay.addWidget(self._friends_rows_box)
        self._friends_none = self._muted_label("No friends yet - ＋ Add a friend above.")
        lay.addWidget(self._friends_none)

        # Groups
        lay.addSpacing(6)
        row = _hbox(0, 6)
        row.addWidget(self._friends_micro("GROUPS"))
        row.addStretch(1)
        add_group = QPushButton("+ Group")
        add_group.setProperty("role", "ghost")
        add_group.clicked.connect(self._on_friends_add_group)
        row.addWidget(add_group)
        self._explain(add_group, "New group",
                      "A named set of friends you control at once - one slider, "
                      "one Shock for all of them. A friend can be in several "
                      "groups.")
        lay.addLayout(row)
        self._groups_rows_box = QWidget()
        self._groups_rows_lay = _vbox(0, 1)
        self._groups_rows_box.setLayout(self._groups_rows_lay)
        lay.addWidget(self._groups_rows_box)
        self._groups_none = self._muted_label(
            "Make a group to control several friends at once.")
        lay.addWidget(self._groups_none)
        return card

    def _update_friends_you(self, st: Dict[str, Any]) -> None:
        if not self._friends_nick_edit.hasFocus() and self._friends_nick_edit.text() != st["nickname"]:
            self._friends_nick_edit.setText(st["nickname"])
        if not st["available"]:
            self._friends_set_pill(self._friends_state_pill, "UNAVAILABLE", "err")
        elif not st["enabled"]:
            self._friends_set_pill(self._friends_state_pill, "OFF", "idle")
        elif not st.get("online_switch", True):
            self._friends_set_pill(self._friends_state_pill, "OFFLINE", "idle")
        elif st.get("elsewhere"):
            # another OGP window has the Friends ID online
            self._friends_set_pill(self._friends_state_pill, "OTHER WINDOW", "warn")
        elif st.get("error") and not st.get("running"):
            self._friends_set_pill(self._friends_state_pill, "LINK ERROR", "err")
        elif not st["online"]:
            self._friends_set_pill(self._friends_state_pill, "STARTING", "run")
        elif st["paused"]:
            self._friends_set_pill(self._friends_state_pill, "PAUSED", "warn")
        else:
            self._friends_set_pill(self._friends_state_pill, "ONLINE", "ok")
        self._friends_my_id = st["my_id"]
        shown = f"Your ID: {st['my_id'][:8]}…" if st["my_id"] else "Your ID: (when online)"
        if self._friends_id_lbl.text() != shown:
            self._friends_id_lbl.setText(shown)
        self._friends_copy_btn.setEnabled(bool(st["my_id"]))
        self._friends_invite_btn.setEnabled(bool(st["my_id"]) and st["online"])
        self._friends_web_btn.setEnabled(bool(st["my_id"]) and st["online"])
        n = len(st.get("invites") or [])
        self._friends_close_links.setText(
            f"Close all invite links ({n} open)" if n else "Close all invite links")
        self._friends_close_links.setEnabled(bool(n))
        self._friends_pause.blockSignals(True)
        self._friends_pause.setChecked(bool(st["paused"]))
        self._friends_pause.blockSignals(False)
        self._friends_online.blockSignals(True)
        self._friends_online.setChecked(bool(st.get("online_switch", True)))
        self._friends_online.blockSignals(False)
        lines = []
        if st.get("error") and not st.get("running") and st["enabled"]:
            lines.append(f"The Friends link stopped: {st['error']}. Switch Online off and "
                         "on to try again.")
        for a in st["asking"]:
            who = display_name(a["nick"], a["id"])
            if a["declined"]:
                lines.append(f"{who} declined.")
            elif a["waiting"]:
                lines.append(f"Asked {who} - waiting for them to click Accept.")
            else:
                lines.append(f"Looking for {who} - they need OGP open.")
        text = "\n".join(lines)
        if self._friends_asking_lbl.text() != text:
            self._friends_asking_lbl.setText(text)
        self._friends_asking_lbl.setVisible(bool(text))

    # ---- what its buttons do -----------------------------------

    def _set_friends_add_open(self, on: bool) -> None:
        self._friends_add_open = bool(on)
        self._friends_add_fold.setVisible(self._friends_add_open)
        self._friends_add_toggle.setText(("▾ " if on else "＋ ") + _ADD_FRIEND)

    def _on_friends_nick_done(self) -> None:
        text = " ".join(self._friends_nick_edit.text().split())
        try:
            current = self.controller.get_friends_status().get("nickname", "")
        except Exception:
            return
        if not text:
            # A nickname can be changed, never taken away.
            self._friends_nick_edit.setText(current)
        elif text != current:
            self.controller.set_friends_nickname(text)

    def _on_friends_copy(self) -> None:
        QGuiApplication.clipboard().setText(self._friends_my_id)
        self._friends_copy_btn.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: self._friends_copy_btn.setText(_COPY_ID))

    def _on_friends_invite_kind(self, i: int) -> None:
        self._friends_invite_kind = _INVITE_KINDS[i][0]
        self._friends_invite_note.setText(_INVITE_KINDS[i][2])

    def _build_invite_menu(self, anchor: QWidget) -> QMenu:
        menu = QMenu(anchor)
        menu.setToolTipsVisible(True)
        self._friends_close_links = menu.addAction("Close all invite links")
        self._friends_close_links.setToolTip(
            "Every invite link you sent stops working. Your friends stay.")
        self._friends_close_links.triggered.connect(
            lambda _=False: self.controller.friends_close_invites())
        reset = menu.addAction("New ID - unfriend everyone\u2026")
        reset.setToolTip("For a link that got out of hand: every friend is "
                         "unlinked and every link and your old ID stop working.")
        reset.triggered.connect(lambda _=False: self._on_friends_reset_id())
        return menu

    def _on_friends_web_copy(self) -> None:
        try:
            first = not self.controller.get_friends_status().get("web")
        except Exception:
            first = False
        text = self.controller.friends_web_link_message()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self._friends_web_btn.setText("Copied ✓ - paste it anywhere")
        QTimer.singleShot(2000, lambda: self._friends_web_btn.setText(_COPY_WEB))
        if first:
            self._friends_select("web", WEB)    # its panel says what it is
        else:
            self.refresh_friends()

    def _on_friends_invite(self) -> None:
        text = self.controller.friends_invite_message(self._friends_invite_kind)
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self._friends_invite_btn.setText("Copied ✓ - paste it in Discord")
        QTimer.singleShot(2000, lambda: self._friends_invite_btn.setText(_COPY_LINK))

    def _friend_row_menu(self, fid: str, nick: str, anchor: QWidget, pos,
                         me: bool = False) -> None:
        if me:
            return                      # you're always on your own list
        menu = QMenu(anchor)
        menu.addAction(f"Unfriend {nick}\u2026").triggered.connect(
            lambda _=False: self._confirm_unfriend(fid, nick))
        menu.exec(anchor.mapToGlobal(pos))

    def _on_friends_column(self, what: str) -> None:
        self.controller.set_friend_permission_all(what)
        self.refresh_friends()

    def _group_row_menu(self, gid: str, name: str, anchor: QWidget, pos) -> None:
        menu = QMenu(anchor)
        menu.addAction("Rename…").triggered.connect(
            lambda _=False: self._rename_group(gid, name))
        menu.addAction(f"Delete {name}…").triggered.connect(
            lambda _=False: self._confirm_delete_group(gid, name))
        menu.exec(anchor.mapToGlobal(pos))

    def _rename_group(self, gid: str, name: str) -> None:
        new, ok = QInputDialog.getText(getattr(self, "dialog_parent", None) or self.window,
                                       "Rename group", "Group name:", text=name)
        if ok and new.strip():
            self.controller.friends_rename_group(gid, new.strip())
            self.refresh_friends()

    def _confirm_delete_group(self, gid: str, name: str) -> None:
        box = QMessageBox(
            QMessageBox.Question, "Delete group",
            f"Delete the group {name}?\n\nYour friends stay - only the group goes.",
            QMessageBox.Yes | QMessageBox.No,
            getattr(self, "dialog_parent", None) or self.window,
        )
        box.setTextFormat(Qt.PlainText)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self.controller.friends_delete_group(gid)
            self.refresh_friends()

    def _friend_dropped_on_group(self, gid: str, fid: str) -> None:
        st = self.controller.get_friends_status()
        g = next((x for x in st["groups"] if x["id"] == gid), None)
        if g is not None and fid not in g["members"]:
            self.controller.set_group_member(gid, fid, True)
            self.refresh_friends()

    def _confirm_unfriend(self, fid: str, nick: str) -> None:
        box = QMessageBox(
            QMessageBox.Question, "Unfriend",
            f"Unfriend {nick}?\n\nYou're unlinked, they leave your list and "
            "groups, and their OGP takes you off theirs - they can't reach your "
            "toys or shockers any more.\n\nTo link again, one of you sends a "
            "new invite link or pastes the other's ID.",
            QMessageBox.Yes | QMessageBox.No,
            getattr(self, "dialog_parent", None) or self.window,
        )
        box.setTextFormat(Qt.PlainText)            # their nickname, never markup
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self.controller.friends_remove(fid)

    def _on_friends_reset_id(self) -> None:
        resp = QMessageBox.question(
            (getattr(self, "dialog_parent", None) or self.window), "New Friends ID",
            "Get a new ID?\n\nEvery friend is unlinked and taken off your list, "
            "your groups go, and your old ID and every invite link you sent stop "
            "working - nobody who has them can reach you any more.\n\nTo link "
            "with someone again, send them a new invite link. Your nickname stays.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp == QMessageBox.Yes:
            self.controller.friends_reset_id()

    def _on_friends_add(self) -> None:
        text = self._friends_add_edit.text()
        if not text.strip():
            return
        why = self.controller.friends_add(text)
        if why:
            self._friends_add_hint.setText(why)
            self._friends_add_hint.setProperty("muted", "false")
            self._friends_add_hint.setProperty("role", "warning")
        else:
            # sent: the fold closes, the line under it says how it goes
            self._friends_add_edit.clear()
            self._friends_add_hint.setText(_ADD_HINT)
            self._friends_add_hint.setProperty("role", "")
            self._friends_add_hint.setProperty("muted", "true")
            self._set_friends_add_open(False)
        self._repolish(self._friends_add_hint)

    def _on_friends_add_group(self) -> None:
        try:
            n = len(self.controller.get_friends_status()["groups"]) + 1
        except Exception:
            n = 1
        self.controller.friends_add_group(f"Group {n}")
        self.refresh_friends()

    def _friends_select(self, kind: str, sid: str) -> None:
        self.controller.set_friends_selected(kind, sid)
        self.refresh_friends()

    # ---- the rows ----------------------------------------------

    def _rebuild_friend_rows(self, st: Dict[str, Any]) -> None:
        clear_layout(self._friends_rows_lay)
        self._friend_rows = {}
        self._friends_avatar_head.setVisible(bool(st.get("params_on")))
        # Add a friend is open by itself while you have none, and folds
        # away when the first one arrives
        n = sum(1 for f in st["friends"] if not f.get("me"))
        if self._friends_fold_n is None or (n and not self._friends_fold_n):
            self._set_friends_add_open(not n)
        self._friends_fold_n = n
        self._web_row = None
        web_due = bool(st.get("web"))
        for index, f in enumerate(st["friends"]):
            if web_due and not f.get("me"):
                self._add_web_row(st)          # right after you
                web_due = False
            fid = f["id"]
            btn = QPushButton()
            btn.setProperty("role", "friendRow")
            btn.setProperty("hue", friend_hue(index))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _=False, i=fid: self._friends_select("friend", i))
            me = bool(f.get("me"))
            nick = display_name(f["nick"], fid) + (" (you)" if me else "")
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, i=fid, n=nick, b=btn, m=me: self._friend_row_menu(i, n, b, pos, m))
            h = _hbox(2, 6)
            btn.setLayout(h)
            badge = self._friends_avatar(nick)
            h.addWidget(badge)
            # a long name ends in "…" rather than pushing the columns over
            name = _ElidedLabel(nick)
            name.setObjectName("friendName")
            name.setTextFormat(Qt.PlainText)
            name.setToolTip(nick)
            h.addWidget(name, 1)
            # their OGP is older than yours (controllers/friends_versions.py)
            old = QLabel("OLD")
            old.setProperty("role", "pill")
            old.setProperty("tone", "warn")
            old.setVisible(False)
            h.addWidget(old)
            ping = QLabel("")
            ping.setProperty("muted", "true")
            h.addWidget(ping)
            driving = QLabel("●")
            driving.setProperty("role", "live")
            driving.setToolTip("Driving your toys right now")
            h.addWidget(driving)
            boxes = {}
            kinds = [("toys", _TOYS, "May drive your toys and move your strength slider"),
                     ("shock", _SHOCK, "May fire your shockers (a vibrate until you arm "
                                       "shocks on the Shockers page)")]
            if st.get("params_on"):
                kinds.append(("params", "accent", "May see and use the board of the "
                                                  "avatar you're wearing (My Avatar Remote page)"))
            cells = QWidget()
            cells_lay = _hbox(0, 0)
            cells.setLayout(cells_lay)
            for what, hue, tip in kinds:
                cell = QWidget()
                cell.setFixedWidth(PERM_COL_W)
                cell_lay = _hbox(0, 0)
                cell.setLayout(cell_lay)
                cells_lay.addWidget(cell)
                if me:
                    continue                    # you always allow yourself
                cb = QCheckBox()
                cb.setProperty("hue", hue)
                cb.setToolTip(tip)
                cb.setChecked(bool(f[what]))
                cb.toggled.connect(lambda on, i=fid, k=what:
                                   self.controller.set_friend_permission(i, k, bool(on)))
                cell_lay.addWidget(cb, 0, Qt.AlignCenter)
                boxes[what] = cb
            h.addWidget(cells)
            self._friends_rows_lay.addWidget(btn)
            if not me:
                _FriendDrag(btn, fid)
            self._friend_rows[fid] = {"btn": btn, "name": name, "ping": ping,
                                      "driving": driving, "old": old, **boxes}
        if web_due:
            self._add_web_row(st)
        self._friends_none.setVisible(not n)
        clear_layout(self._groups_rows_lay)
        self._group_rows = {}
        for g in st["groups"]:
            btn = QPushButton()
            btn.setProperty("role", "friendRow")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _=False, i=g["id"]: self._friends_select("group", i))
            h = _hbox(2, 6)
            btn.setLayout(h)
            h.addWidget(self._friends_avatar(g["name"]))
            name = QLabel(g["name"])
            name.setObjectName("friendName")
            h.addWidget(name)
            count = QLabel(f"{len(g['members'])} friend{'s' if len(g['members']) != 1 else ''}")
            count.setProperty("muted", "true")
            h.addWidget(count)
            h.addStretch(1)
            self._groups_rows_lay.addWidget(btn)
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, i=g["id"], n=g["name"], b=btn: self._group_row_menu(i, n, b, pos))
            btn.setToolTip("Drag a friend here to add them; right-click to rename or delete")
            _GroupDrop(btn, lambda fid, i=g["id"]: self._friend_dropped_on_group(i, fid),
                       self._repolish)
            self._group_rows[g["id"]] = btn
        self._groups_none.setVisible(not st["groups"])

    def _add_web_row(self, st: Dict[str, Any]) -> None:
        """Everyone on your web remote link, one row (friends_web.py): a
        Toys box under the toy, nothing under the bolt or the remote."""
        btn = QPushButton()
        btn.setProperty("role", "friendRow")
        btn.setProperty("hue", FRIENDS_HUE)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(34)
        btn.clicked.connect(lambda _=False: self._friends_select("web", WEB))
        btn.setContextMenuPolicy(Qt.CustomContextMenu)
        btn.customContextMenuRequested.connect(lambda pos, b=btn: self._web_row_menu(b, pos))
        h = _hbox(2, 6)
        btn.setLayout(h)
        badge = QWidget()
        badge.setFixedSize(22, 22)
        bl = _hbox(0, 0)
        badge.setLayout(bl)
        bl.addWidget(IdentityMark("web", 18), 0, Qt.AlignCenter)
        h.addWidget(badge)
        name = QLabel("Web remote")
        name.setObjectName("friendName")
        h.addWidget(name, 1)
        ping = QLabel("")
        ping.setProperty("muted", "true")
        h.addWidget(ping)
        driving = QLabel("●")
        driving.setProperty("role", "live")
        driving.setToolTip("Someone on your web remote drives your toys right now")
        h.addWidget(driving)
        cells = QWidget()
        cells_lay = _hbox(0, 0)
        cells.setLayout(cells_lay)
        boxes = {}
        for what in ("toys", "shock") + (("params",) if st.get("params_on") else ()):
            cell = QWidget()
            cell.setFixedWidth(PERM_COL_W)
            cell_lay = _hbox(0, 0)
            cell.setLayout(cell_lay)
            cells_lay.addWidget(cell)
            cb = QCheckBox()
            cb.setProperty("hue", _WEB_BOXES[what][0])
            cb.setToolTip(_WEB_BOXES[what][1])
            cb.setChecked(bool(st["web"][what]))
            cb.toggled.connect(lambda on, k=what:
                               self.controller.set_friends_web_permission(k, bool(on)))
            cell_lay.addWidget(cb, 0, Qt.AlignCenter)
            boxes[what] = cb
        h.addWidget(cells)
        self._friends_rows_lay.addWidget(btn)
        self._web_row = {"btn": btn, "ping": ping, "driving": driving, **boxes}

    def _web_row_menu(self, anchor: QWidget, pos) -> None:
        menu = QMenu(anchor)
        menu.addAction("Remove web remote…").triggered.connect(
            lambda _=False: self._confirm_web_remove())
        menu.exec(anchor.mapToGlobal(pos))

    def _update_web_row(self, st: Dict[str, Any]) -> None:
        r, web = getattr(self, "_web_row", None), st.get("web")
        if r is None or not web:
            return
        n = len(web["guests"])
        text = "off" if not web["on"] else (f"{n} on" if n else "nobody on")
        if r["ping"].text() != text:
            r["ping"].setText(text)
        tip = web_guests_tip(web)
        if r["ping"].toolTip() != tip:
            r["ping"].setToolTip(tip)
            r["btn"].setToolTip(tip)
        state = "on" if n and web["on"] else "off"
        if r["ping"].property("state") != state:
            r["ping"].setProperty("state", state)
            r["ping"].setProperty("role", "success" if state == "on" else "")
            r["ping"].setProperty("muted", "false" if state == "on" else "true")
            self._repolish(r["ping"])
        r["driving"].setVisible(bool(web["driving"]))
        for what in _WEB_BOXES:
            if what in r and r[what].isChecked() != bool(web[what]):
                r[what].blockSignals(True)
                r[what].setChecked(bool(web[what]))
                r[what].blockSignals(False)
        self._friends_set_active(r["btn"], st["selected"] == {"kind": "web", "id": WEB})

    def _update_friend_rows(self, st: Dict[str, Any]) -> None:
        self._update_web_row(st)
        sel = st["selected"]
        for f in st["friends"]:
            r = self._friend_rows.get(f["id"])
            if r is None:
                continue
            ping = (f"{f['rtt']:.0f} ms" if f["rtt"] is not None else "online") if f["linked"] else "offline"
            if f.get("me"):
                ping = "this PC"
            if r["ping"].text() != ping:
                r["ping"].setText(ping)
            state = "on" if f["linked"] else "off"
            if r["ping"].property("state") != state:
                r["ping"].setProperty("state", state)
                r["ping"].setProperty("role", "success" if f["linked"] else "")
                r["ping"].setProperty("muted", "false" if f["linked"] else "true")
                self._repolish(r["ping"])
            r["driving"].setVisible(bool(f["driving_me"]))
            older = f.get("version") == "older"
            if older:
                tip = (f"Their OGP is {('v' + f['app']) if f.get('app') else 'from before version checks'}"
                       ", older than yours - what's new in yours may not reach them until "
                       "they update.")
                if r["old"].toolTip() != tip:
                    r["old"].setToolTip(tip)
            r["old"].setVisible(older)
            for what in ("toys", "shock", "params"):
                if what not in r:
                    continue
                if r[what].isChecked() != bool(f.get(what)):
                    r[what].blockSignals(True)
                    r[what].setChecked(bool(f[what]))
                    r[what].blockSignals(False)
            self._friends_set_active(r["btn"], sel == {"kind": "friend", "id": f["id"]})
        for g in st["groups"]:
            btn = self._group_rows.get(g["id"])
            if btn is not None:
                self._friends_set_active(btn, sel == {"kind": "group", "id": g["id"]})

    @staticmethod
    def _friends_avatar(name: str) -> QLabel:
        """A round badge with the first letter, in its row's hue."""
        a = QLabel((name.strip()[:1] or "?").upper())
        a.setObjectName("friendAvatar")
        a.setFixedSize(22, 22)
        a.setAlignment(Qt.AlignCenter)
        return a

    def _friends_set_active(self, btn: QPushButton, on: bool) -> None:
        value = "true" if on else "false"
        if btn.property("active") != value:
            btn.setProperty("active", value)
            self._repolish(btn)
