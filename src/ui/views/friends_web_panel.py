"""Friends view, the Web remote panel: your one web remote link -- Copy, New
link, On -- what everyone on it may do (Toys, Shockers, Avatar), who is on
it right now (a Kick each), and Remove. Part of FriendsMixin (friends.py); what it does is
controllers/friends_web.py."""

from typing import Any, Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget

from constants import BTN_HEIGHT_SMALL
from controllers.friends_common import WEB
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.theme import FRIENDS_HUE
from ui.views.friends_list import web_guests_tip
from ui.widgets import IdentityMark, ToggleSwitch

_COPY = "Copy link"
# The panel's three switches: (settings key, label, identity icon, explanation)
_SWITCHES = (
    ("toys", "Toys", "toys",
     "Everyone on your web remote may drive your toys - levels, auto modes, "
     "Override - and move your strength slider. Off: they stay on the link and "
     "see that it does nothing."),
    ("shock", "Shockers", "shock",
     "Everyone on your web remote gets PiShock's panel for your shockers. A shock "
     "is only a vibrate until you arm shocks on the Shockers page, and always "
     "inside each shocker's own caps."),
    ("params", "Avatar", "params",
     "Everyone on your web remote sees the board of the avatar you're wearing and "
     "can use it. A locked category stays look-only."),
)


class FriendsWebPanelMixin:

    def _build_web_panel(self, web: Dict[str, Any], params_on: bool = False) -> None:
        w = self._panel_w
        w["kind"], w["id"] = "web", WEB
        row, w["title"] = self._panel_header("Web remote")
        row.insertWidget(0, IdentityMark("web", 20))
        w["pill"] = self._friends_pill()
        row.addWidget(w["pill"])
        self._panel_lay.addWidget(self._muted_label(
            "Anyone with your web remote link gets a friend's panel in their browser - "
            "no OGP, no account: your toys, and your shockers and avatar's board if "
            "you tick them below. Everything a friend's must, holds: your strength, "
            "Off, Pause all, each toy's output band, arming and each shocker's caps, "
            "locked categories - and a browser that stops sending lets go within a "
            "second."))

        lay, head = self._friends_section("YOUR LINK", FRIENDS_HUE)
        w["on"] = ToggleSwitch("On")
        w["on"].setChecked(bool(web["on"]))
        w["on"].toggled.connect(lambda on: self.controller.set_friends_web_on(bool(on)))
        head.addWidget(w["on"])
        self._explain(w["on"], "Web remote on",
                      "Off: nobody gets in with your link, and everyone on it is let "
                      "go. The link works again when you switch it back on.")
        btns = _hbox(0, 8)
        w["copy"] = QPushButton(_COPY)
        w["copy"].setMinimumHeight(BTN_HEIGHT_SMALL)
        w["copy"].setProperty("role", "secondary")
        w["copy"].clicked.connect(lambda _=False: self._on_web_copy())
        btns.addWidget(w["copy"])
        new = QPushButton("New link…")
        new.setMinimumHeight(BTN_HEIGHT_SMALL)
        new.setProperty("role", "ghost")
        new.clicked.connect(lambda _=False: self._confirm_web_new_link())
        btns.addWidget(new)
        self._explain(new, "New link",
                      "Your link stops working and everyone on it is let go; the new "
                      "one only reaches whoever you give it to.")
        btns.addStretch(1)
        lay.addLayout(btns)
        lay.addWidget(self._muted_label(
            "It opens remote.html on OGP's website. Everything after the # stays "
            "in the browser - the website never learns who drives whom."))

        lay, head = self._friends_section("WHAT THEY MAY DO", FRIENDS_HUE)
        row = _hbox(0, 18)
        for what, label, mark, tip in _SWITCHES:
            if what == "params" and not params_on:
                continue
            cell = _hbox(0, 6)
            cell.addWidget(IdentityMark(mark, 16))
            sw = ToggleSwitch(label)
            sw.setChecked(bool(web[what]))
            sw.toggled.connect(lambda on, k=what:
                               self.controller.set_friends_web_permission(k, bool(on)))
            cell.addWidget(sw)
            row.addLayout(cell)
            self._explain(sw, label, tip)
            w[what] = sw
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self._muted_label(
            "For everyone on the link at once. Shockers and Avatar start off: anyone "
            "with the link gets what you tick here."))

        lay, head = self._friends_section("ON NOW", FRIENDS_HUE)
        box = QWidget()
        box_lay = _vbox(0, 4)
        box.setLayout(box_lay)
        w["guests"] = {}
        for g in web["guests"]:
            box_lay.addWidget(self._web_guest_row(g))
        if not web["guests"]:
            box_lay.addWidget(self._muted_label("Nobody right now."))
        lay.addWidget(box)

        foot = _hbox(0, 8)
        foot.addStretch(1)
        remove = QPushButton("Remove web remote…")
        remove.setProperty("role", "ghost")
        remove.setProperty("muted", "true")
        remove.clicked.connect(lambda _=False: self._confirm_web_remove())
        foot.addWidget(remove)
        self._panel_lay.addSpacing(6)
        self._panel_lay.addLayout(foot)

    def _web_guest_row(self, g: Dict[str, Any]) -> QWidget:
        row = QWidget()
        h = _hbox(0, 8)
        row.setLayout(h)
        name = QLabel(g["nick"])
        name.setTextFormat(Qt.PlainText)            # a stranger's text, never markup
        h.addWidget(name)
        driving = QLabel("●")
        driving.setProperty("role", "live")
        driving.setToolTip("Driving your toys right now")
        h.addWidget(driving)
        h.addStretch(1)
        rtt = QLabel("")
        rtt.setProperty("muted", "true")
        h.addWidget(rtt)
        kick = QPushButton("Kick")
        kick.setProperty("role", "ghost")
        kick.setCursor(Qt.PointingHandCursor)
        kick.setToolTip("Let this browser go - it can't come back with your link, "
                        "nor with a new one")
        kick.clicked.connect(lambda _=False, i=g["id"]: (self.controller.friends_web_kick(i),
                                                         self.refresh_friends()))
        h.addWidget(kick)
        self._panel_w["guests"][g["id"]] = {"driving": driving, "rtt": rtt}
        return row

    def _update_web_panel(self, st: Dict[str, Any]) -> None:
        w, web = self._panel_w, st.get("web")
        if not web:
            return
        n = len(web["guests"])
        if not web["on"]:
            self._friends_set_pill(w["pill"], "OFF", "idle")
        elif n:
            self._friends_set_pill(w["pill"], f"{n} ON NOW", "ok")
        else:
            self._friends_set_pill(w["pill"], "NOBODY ON", "idle")
        tip = web_guests_tip(web)
        if w["pill"].toolTip() != tip:
            w["pill"].setToolTip(tip)
        for key in ("on", "toys", "shock", "params"):
            if key in w and w[key].isChecked() != bool(web[key]):
                w[key].blockSignals(True)
                w[key].setChecked(bool(web[key]))
                w[key].blockSignals(False)
        for g in web["guests"]:
            r = w["guests"].get(g["id"])
            if r is None:
                continue
            r["driving"].setVisible(bool(g["driving"]))
            text = f"{g['rtt']:.0f} ms" if g.get("rtt") is not None else ""
            if r["rtt"].text() != text:
                r["rtt"].setText(text)

    def _on_web_copy(self) -> None:
        text = self.controller.friends_web_link_message()
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        btn = self._panel_w.get("copy")
        if btn is not None:
            btn.setText("Copied ✓")
            QTimer.singleShot(1500, lambda: btn.setText(_COPY) if btn is self._panel_w.get("copy")
                              else None)

    def _confirm_web_new_link(self) -> None:
        box = QMessageBox(
            QMessageBox.Question, "New web remote link",
            "Make a new web remote link?\n\nYour current link stops working and "
            "everyone on it is let go. Copy the new one to give it out.",
            QMessageBox.Yes | QMessageBox.No,
            getattr(self, "dialog_parent", None) or self.window,
        )
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self.controller.friends_web_new_link()
            self.refresh_friends()

    def _confirm_web_remove(self) -> None:
        box = QMessageBox(
            QMessageBox.Question, "Remove web remote",
            "Remove your web remote?\n\nIts link stops working, everyone on it is "
            "let go and its row leaves your list. Copy a web remote link again any "
            "time to get a new one.",
            QMessageBox.Yes | QMessageBox.No,
            getattr(self, "dialog_parent", None) or self.window,
        )
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self.controller.friends_web_remove()
            self.refresh_friends()
