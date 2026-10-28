"""Friends view: when a friend's OGP is newer than yours (Blise's ask,
2026-10-27). The controller decides (controllers/friends_versions.py);
this draws the window it opens once a launch -- "Your OGP is older than
Mika's", with Update now (the usual update window) when the launch update
check already found a release this copy can install, else the release
page -- and the amber
banner on the Friends page while you're behind, whose button opens the
window again. Part of FriendsMixin (friends.py)."""

from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QFrame, QLabel, QPushButton

from constants import *
from ui.layout_helpers import hbox as _hbox, vbox as _vbox
from ui.text_helpers import html_escape


class FriendsUpdateMixin:

    def _build_friends_update_banner(self) -> QFrame:
        banner = QFrame()
        banner.setObjectName("friendUpdateBanner")
        row = _hbox(14, 12)
        banner.setLayout(row)
        self._friends_update_lbl = QLabel("")
        self._friends_update_lbl.setWordWrap(True)
        self._friends_update_lbl.setTextFormat(Qt.PlainText)    # their nickname, never markup
        row.addWidget(self._friends_update_lbl, 1)
        go = QPushButton("Update…")
        go.setMinimumHeight(BTN_HEIGHT_SMALL)
        go.setProperty("role", "primary")
        go.clicked.connect(lambda _=False: self.controller.show_friends_update())
        row.addWidget(go)
        banner.setVisible(False)
        self._friends_update_banner = banner
        return banner

    def _update_friends_update_banner(self, behind: Optional[Dict[str, Any]]) -> None:
        text = ""
        if behind:
            who = ", ".join(behind["who"])
            text = (f"Your OGP is out of date: {who} {'has' if len(behind['who']) == 1 else 'have'} "
                    f"v{behind['version']}, you have v{behind['mine']}. Update so everything "
                    "they do works for you.")
        if self._friends_update_lbl.text() != text:
            self._friends_update_lbl.setText(text)
        self._friends_update_banner.setVisible(bool(text))

    def show_friend_update_warning(self, nick: str, theirs: str, mine: str,
                                   offer: Optional[Tuple[str, str]], releases_url: str) -> None:
        """Controller facade: you're behind `nick`. `offer` is (version,
        release page) when Install now can get it from here."""
        if any(getattr(self, name, None) is not None for name in
               ("_friend_update_dialog", "_update_popup", "_whats_new_dialog",
                "_interests_dialog")):
            return          # one window at a time; the Friends banner stays
        dlg = QDialog(getattr(self, "dialog_parent", None) or self.window)
        dlg.setWindowTitle("Your OGP is out of date")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumWidth(480)
        lay = _vbox(20, 12)
        dlg.setLayout(lay)

        head = QLabel(f"Your OGP is older than {nick}'s")
        head.setObjectName("friendUpdateHead")       # loud, in the warning amber
        head.setTextFormat(Qt.PlainText)
        head.setWordWrap(True)
        lay.addWidget(head)
        who = html_escape(nick)
        if offer:
            how = (f"<b>Update now</b> gets v{html_escape(offer[0])}, checks it and "
                   "restarts the app - your settings stay as they are.")
        else:
            how = (f"Get it from the release page. If it isn't there yet, ask {who} "
                   "where they got theirs.")
        body = QLabel(f"{who} has OscGoesPurrr v{html_escape(theirs)}, you have "
                      f"v{html_escape(mine)}. Some of what they do - on your toys, "
                      f"shockers or avatar - may not work until you update.<br><br>{how}")
        body.setWordWrap(True)
        body.setTextFormat(Qt.RichText)
        lay.addWidget(body)

        row = _hbox(0, 8)
        row.addStretch(1)
        later = QPushButton("Later")
        later.setProperty("role", "secondary")
        later.clicked.connect(lambda _=False: dlg.reject())
        row.addWidget(later)
        url = offer[1] if offer else releases_url
        page = QPushButton("Release page" if offer else "Open release page")
        page.setProperty("role", "secondary" if offer else "primary")

        def open_page(_=False) -> None:
            QDesktopServices.openUrl(QUrl(url))
            dlg.accept()
        page.clicked.connect(open_page)
        row.addWidget(page)
        if offer:
            install = QPushButton("Update now…")
            install.setProperty("role", "primary")
            install.setDefault(True)

            def update_now(_=False) -> None:
                dlg.accept()
                # the usual update window: Install now, its progress, the restart
                self.show_update_popup(offer[0], mine, offer[1], True)
            install.clicked.connect(update_now)
            row.addWidget(install)
        else:
            page.setDefault(True)
        lay.addLayout(row)

        def closed(_result) -> None:
            self._friend_update_dialog = None
        dlg.finished.connect(closed)
        self._friend_update_dialog = dlg
        dlg.open()          # not exec(): this runs from the queue pump
