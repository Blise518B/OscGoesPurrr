"""Friends view — other OGP users you link with over the internet.

Mixin for ui_components.OscGoesPurrrUI, shown while `feature_friends` is on
(the default). Until you have a nickname the page is one card, Pick a
nickname: nothing goes online, and nothing else shows, before it. After:

  * requests — one card per ID asking to be your friend: Accept / Decline;
  * left, a fixed-width list (friends_list.py) —
      You:     your nickname, Online, Pause all friends, Invite link
               (once / a day / a week / no end, close them all, new ID),
               Copy ID;
      Friends: one row each (a letter badge, name, ping, a pink dot while
               they drive you) with two checkboxes: may they control your
               toys, may they control your shockers; after you, the Web
               remote row -- everyone on your web remote link, its panel in
               friends_web_panel.py;
      Add a friend (paste their ID or an invite link);
      Groups:  named sets of friends you control at once (+ Group);
  * right, at most `PANEL_MAX_W` wide — the control panel for what is
    picked in the list (one friend, or a group), which is also what the
    VRChat menu's Friends submenu acts on (friends_panel.py): a pink
    section with a card per toy and a yellow one with a small PiShock
    panel per shocker (toy_card.py, shocker_card.py), and for one friend
    the board of the avatar they wear (friends_board.py). Control mode
    makes it fill the window, everything big, for VR;
  * under it the log, and the VRChat menu tip (friends_vrc_tip.py).

Everything goes through the controller's Friends facade (Demeter rule);
these files only draw widgets and forward primitive values.
"""

import time
from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QFrame, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSlider, QVBoxLayout,
    QWidget,
)

from constants import *
from ui.layout_helpers import SIDE_GAP, SideBySide, clear_layout, vbox as _vbox, hbox as _hbox
from ui.text_helpers import html_escape
from ui.views.card_parts import CARD_MIN_W, WheelSafeSlider
from ui.views.friends_board import FriendsBoardMixin
from ui.views.friends_list import LIST_W, FriendsListMixin
from ui.views.friends_panel import PANEL_MAX_W, FriendsPanelMixin
from ui.views.friends_update import FriendsUpdateMixin
from ui.views.friends_vrc_tip import VrchatMenuTip
from ui.widgets import Card as _Card

VIEW_NAME = "Friends"


class FriendsMixin(FriendsListMixin, FriendsPanelMixin, FriendsBoardMixin, FriendsUpdateMixin):

    _friends_list_key: Any = None
    _friends_panel_key: Any = None
    _friends_log_shown: Any = None

    # ----------------------------------------------------------
    # View
    # ----------------------------------------------------------

    def _build_friends_view(self, parent_layout: QVBoxLayout):
        title = QLabel(VIEW_NAME)
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)
        intro = self._muted_label(
            "Link with other OGP users over the internet, no account needed. Tick "
            "what each friend may control here, pick a friend or a group on the "
            "left and control them on the right. Every friend you allow can act "
            "at the same time, and everything is logged.")
        parent_layout.addWidget(intro)
        self._friends_title, self._friends_intro = title, intro
        self._friends_big = False

        self._friends_gate = self._build_friends_gate_card()
        parent_layout.addWidget(self._friends_gate)

        self._friends_requests_box = QWidget()
        self._friends_requests_lay = _vbox(0, 8)
        self._friends_requests_box.setLayout(self._friends_requests_lay)
        parent_layout.addWidget(self._friends_requests_box)
        # a friend's OGP is newer than yours (friends_update.py)
        banner = self._build_friends_update_banner()
        banner.setMaximumWidth(LIST_W + SIDE_GAP + PANEL_MAX_W)
        parent_layout.addWidget(banner)

        self._friends_list_card = self._build_friends_list_column()
        right = QWidget()
        right.setMaximumWidth(PANEL_MAX_W)
        rl = _vbox(0, 12)
        right.setLayout(rl)
        self._panel_card = _Card()
        self._panel_lay = _vbox(20, 8)
        self._panel_card.setLayout(self._panel_lay)
        rl.addWidget(self._panel_card)
        self._friends_log_card = self._build_friends_log_card()
        rl.addWidget(self._friends_log_card)
        self._friends_vrc_tip = VrchatMenuTip()
        rl.addWidget(self._friends_vrc_tip)
        rl.addStretch(1)
        self._friends_right = right
        # Half a screen wide: the list goes on top, the panel under it.
        self._friends_main = SideBySide(self._friends_list_card, right,
                                        LIST_W + SIDE_GAP + 2 * CARD_MIN_W + 50,
                                        self._friends_stacked)
        parent_layout.addWidget(self._friends_main)
        parent_layout.addStretch(1)
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self._friends_main)
        esc.setContext(Qt.WindowShortcut)
        esc.activated.connect(lambda: self._set_friends_control(False))

        self._friend_rows, self._group_rows, self._panel_w = {}, {}, {}
        self._friends_live_timer = QTimer()
        self._friends_live_timer.setInterval(150)
        self._friends_live_timer.timeout.connect(self._refresh_friends_live)
        self._friends_live_timer.start()
        self.refresh_friends()

    # ---- small builders ----------------------------------------

    def _friends_card(self, heading: str):
        card = _Card()
        lay = _vbox(20, 8)
        card.setLayout(lay)
        hdr_row = _hbox(0, 8)
        hdr = QLabel(heading)
        hdr.setObjectName("sectionTitle")
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        lay.addLayout(hdr_row)
        return card, lay, hdr_row, hdr

    def _friends_pill(self, text: str = "", tone: str = "idle") -> QLabel:
        pill = QLabel(text)
        pill.setProperty("role", "pill")
        pill.setProperty("tone", tone)
        return pill

    def _friends_set_pill(self, pill: QLabel, text: str, tone: str) -> None:
        if pill.text() != text:
            pill.setText(text)
        if pill.property("tone") != tone:
            pill.setProperty("tone", tone)
            self._repolish(pill)

    def _friends_set_role(self, label: QLabel, role: str) -> None:
        if label.property("role") != role:
            label.setProperty("role", role)
            self._repolish(label)

    @staticmethod
    def _friends_micro(text: str, hue: str = "") -> QLabel:
        """A small section label; in the hue of what the section drives."""
        lbl = QLabel(text)
        lbl.setObjectName("friendsMicro")
        if hue:
            lbl.setProperty("hue", hue)
        return lbl

    @staticmethod
    def _friends_slider() -> QSlider:
        s = WheelSafeSlider(Qt.Horizontal)
        s.setRange(0, 1000)
        s.setSingleStep(10)
        s.setPageStep(100)
        s.setCursor(Qt.PointingHandCursor)
        return s

    # ---- Pick a nickname (before anything else) ----------------

    def _build_friends_gate_card(self) -> QFrame:
        card, lay, _hdr, _ = self._friends_card("Pick a nickname")
        lay.addWidget(self._muted_label(
            "Friends lets other OGP users drive your toys and fire your "
            "shockers over the internet - and you theirs. Everything a friend "
            "does here is logged, you can switch either off per friend, and "
            "shocks stay vibrates until you arm them on the Shockers page."))
        notice = QLabel(
            "First, give yourself a nickname: it is how your friends see you in "
            "their OGP. Nothing goes online until you do.")
        notice.setWordWrap(True)
        notice.setProperty("role", "warning")
        lay.addWidget(notice)
        self._friends_gate_invite = QLabel("")
        self._friends_gate_invite.setWordWrap(True)
        self._friends_gate_invite.setProperty("role", "success")
        self._friends_gate_invite.setVisible(False)
        lay.addWidget(self._friends_gate_invite)
        row = _hbox(0, 8)
        self._friends_gate_edit = QLineEdit()
        self._friends_gate_edit.setMaxLength(24)
        self._friends_gate_edit.setPlaceholderText("your nickname")
        self._friends_gate_edit.setMinimumWidth(240)
        self._friends_gate_edit.setMaximumWidth(300)
        self._friends_gate_edit.returnPressed.connect(self._on_friends_gate_done)
        row.addWidget(self._friends_gate_edit)
        go = QPushButton("Go online")
        go.setMinimumHeight(BTN_HEIGHT_SMALL)
        go.setProperty("role", "primary")
        go.clicked.connect(self._on_friends_gate_done)
        row.addWidget(go)
        row.addStretch(1)
        lay.addLayout(row)
        self._friends_gate_hint = self._muted_label(
            "Up to 24 characters. You can change it later; your friends see the "
            "new one.")
        lay.addWidget(self._friends_gate_hint)
        card.setMaximumWidth(LIST_W + SIDE_GAP + PANEL_MAX_W)
        return card

    def prompt_friends_invite(self, who: str, nickname: str, friends_off: bool) -> None:
        """A clicked invite and no nickname yet (or Friends switched off):
        one small window that asks for the nickname and links you."""
        old = getattr(self, "_friends_invite_dlg", None)
        if old is not None:
            old.close()
        dlg = QDialog(getattr(self, "dialog_parent", None) or self.window)
        dlg.setWindowTitle("Friend invite")
        dlg.setMinimumWidth(380)
        lay = _vbox(20, 10)
        dlg.setLayout(lay)
        title = QLabel(f"{who} invited you")
        title.setObjectName("sectionTitle")
        title.setTextFormat(Qt.PlainText)
        row = _hbox(0, 0)
        row.addWidget(title)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self._muted_label(
            "Pick the nickname your friends see you as."
            + (" This switches Friends on." if friends_off else "")))
        edit = QLineEdit(nickname)
        edit.setMaxLength(24)
        edit.setPlaceholderText("your nickname")
        lay.addWidget(edit)
        hint = QLabel("")
        hint.setProperty("role", "warning")
        hint.setVisible(False)
        lay.addWidget(hint)
        row = _hbox(0, 8)
        row.addStretch(1)
        later = QPushButton("Not now")
        later.setProperty("role", "secondary")
        later.clicked.connect(lambda _=False: dlg.reject())
        row.addWidget(later)
        go = QPushButton("Link up")
        go.setProperty("role", "primary")
        go.setDefault(True)
        row.addWidget(go)
        lay.addLayout(row)

        def link_up(_=False) -> None:
            why = self.controller.accept_friends_invite(edit.text())
            if why:
                hint.setText(why)
                hint.setVisible(True)
                return
            dlg.accept()
            self.refresh_friends()

        go.clicked.connect(link_up)
        edit.returnPressed.connect(link_up)
        self._friends_invite_dlg = dlg
        dlg.open()
        edit.setFocus()

    def _on_friends_gate_done(self) -> None:
        text = " ".join(self._friends_gate_edit.text().split())
        if not text:
            self._friends_gate_hint.setText("Type a nickname first.")
            self._friends_gate_hint.setProperty("muted", "false")
            self._friends_gate_hint.setProperty("role", "warning")
            self._repolish(self._friends_gate_hint)
            return
        self.controller.set_friends_nickname(text)
        self.refresh_friends()

    # ---- Log ---------------------------------------------------

    def _build_friends_log_card(self) -> QFrame:
        card, lay, _hdr, _ = self._friends_card("Log")
        self._friends_log_view = QPlainTextEdit()
        self._friends_log_view.setReadOnly(True)
        self._friends_log_view.setFixedHeight(130)
        self._friends_log_view.setPlaceholderText(
            "Who linked, who drove whose toys, every strength change and "
            "every shock - newest first.")
        lay.addWidget(self._friends_log_view)
        return card

    def _update_friends_log(self) -> None:
        try:
            entries = self.controller.get_friends_log()
        except Exception:
            return
        sig = (len(entries), entries[0]["t"] if entries else 0,
               entries[0]["text"] if entries else "")
        if sig == self._friends_log_shown:
            return
        self._friends_log_shown = sig
        self._friends_log_view.setPlainText("\n".join(
            f"{time.strftime('%H:%M:%S', time.localtime(e['t']))}  {e['text']}"
            for e in entries))

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def _refresh_friends_live(self) -> None:
        page = self.views.get(VIEW_NAME) if hasattr(self, "views") else None
        if page is None or not page.isVisible():
            if getattr(self, "_friends_big", False):
                self._set_friends_control(False)       # another page took over
            self._friends_watch(None)                 # nobody's board is open
            self._friends_levels_watch("")            # ... nor anyone's toy cards
            return
        self.refresh_friends()

    def _friends_stacked(self, stacked: bool, width: int) -> None:
        """Side by side: the list is a fixed column. Stacked: as wide as the
        panel under it."""
        w = min(max(LIST_W, width), PANEL_MAX_W) if stacked else LIST_W
        if self._friends_list_card.width() != w or self._friends_list_card.minimumWidth() != w:
            self._friends_list_card.setFixedWidth(w)

    def refresh_friends(self) -> None:
        if not hasattr(self, "_panel_lay"):
            return
        try:
            st = self.controller.get_friends_status()
        except Exception:
            return
        gated = not st["nickname"]
        self._friends_gate.setVisible(gated)
        self._friends_main.setVisible(not gated)
        self._update_friends_update_banner(None if gated else st.get("behind"))
        if gated:
            self._friends_requests_box.setVisible(False)
            who = st.get("pending_invite") or ""
            text = (f"{who} invited you - pick a nickname and you're linked." if who else "")
            if self._friends_gate_invite.text() != text:
                self._friends_gate_invite.setText(text)
            self._friends_gate_invite.setVisible(bool(text))
            return

        req_key = tuple(r["id"] for r in st["requests"])
        if req_key != getattr(self, "_friends_req_key", None):
            self._friends_req_key = req_key
            self._rebuild_friend_requests(st["requests"])
        list_key = (tuple((f["id"], f["nick"]) for f in st["friends"]),
                    tuple((g["id"], g["name"], len(g["members"])) for g in st["groups"]),
                    bool(st.get("params_on")), bool(st.get("web")))
        if list_key != self._friends_list_key:
            self._friends_list_key = list_key
            self._rebuild_friend_rows(st)
        panel_key = self._panel_key(st)
        if panel_key != self._friends_panel_key:
            self._friends_panel_key = panel_key
            self._rebuild_panel(st)

        self._update_friends_you(st)
        self._friends_vrc_tip.set_state(st.get("avatar_menu") or {})
        self._update_friend_rows(st)
        self._update_panel(st)
        self._update_friends_log()

    # ---- requests ----------------------------------------------

    def _rebuild_friend_requests(self, requests: List[Dict[str, str]]) -> None:
        clear_layout(self._friends_requests_lay)
        for r in requests:
            card = _Card()
            card.setMaximumWidth(LIST_W + SIDE_GAP + PANEL_MAX_W)
            cl = _hbox(16, 8)
            card.setLayout(cl)
            who = html_escape(r["nick"] or "Someone")    # a stranger's text, never markup
            msg = QLabel(f"<b>{who}</b> ({r['id'][:8]}…) wants to be your friend. "
                         "Accept only someone you know: a friend you accept can "
                         "drive your toys and fire your shockers right away - "
                         "shocks stay vibrates until you arm them on the "
                         "Shockers page. Both switch off in your list.")
            msg.setWordWrap(True)
            msg.setTextFormat(Qt.RichText)
            msg.setProperty("role", "warning")
            cl.addWidget(msg, 1)
            for label, ok in (("Accept", True), ("Decline", False)):
                b = QPushButton(label)
                b.setMinimumHeight(BTN_HEIGHT_SMALL)
                b.setProperty("role", "secondary")
                b.clicked.connect(lambda _=False, p=r["id"], a=ok: self.controller.friends_answer(p, a))
                cl.addWidget(b)
            self._friends_requests_lay.addWidget(card)
        self._friends_requests_box.setVisible(bool(requests))
