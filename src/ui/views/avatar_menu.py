"""Your avatar's menu: OGP's controls in the avatar's own expression menu,
from the VRCFury prefabs (docs/unity/, attached to every release under one
fixed name). The two links every place that offers it uses, and the
Settings card that says whether the avatar you're wearing has it.

Whether it has it comes from the parameters VRChat lists for the avatar
(controllers/friends_menu.get_avatar_menu): `self` is your own controls
(OGP/Strength), `friends` the Friends submenu (OGP/Friend/Level), `known`
that VRChat told us anything at all."""

from typing import Callable, Dict

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QPushButton

from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import Card

# releases/latest/download/<fixed name>: always the newest release's copy
PREFAB_URL = ("https://github.com/Blise518B/OscGoesPurrr/releases/latest/download/"
              "OscGoesPurrr-VRCFury.unitypackage")
GUIDE_URL = "https://github.com/Blise518B/OscGoesPurrr/blob/main/docs/VRCHAT_MENU.md"
_REFRESH_MS = 1000

# (key in get_avatar_menu, what it is, what it puts in the menu)
_PARTS = (
    ("self", "Your own controls", "Strength, Off, Sleep, Test and the modes"),
    ("friends", "Friends submenu", "drives whoever you picked on the Friends page"),
)


def links_html(color: str) -> str:
    """The two links, for a rich-text label: get it, and how."""
    style = f"color:{color}; text-decoration:none"
    return (f'<a style="{style}" href="{PREFAB_URL}">Get the menu prefabs</a> · '
            f'<a style="{style}" href="{GUIDE_URL}">How to add it</a>')


def has_menu(menu: Dict[str, bool]) -> bool:
    """The avatar carries some of OGP's menu (either part)."""
    return bool(menu.get("known") and (menu.get("self") or menu.get("friends")))


class AvatarMenuCard(Card):
    """Settings → VRChat menu: what the menu gives you, whether the avatar
    you're wearing has each part (live, while the card is on screen), and
    the prefab and the guide. `get_menu` is the controller's
    get_avatar_menu; `explain(widget, title, text)` the host's hover."""

    def __init__(self, get_menu: Callable[[], Dict[str, bool]], explain=None):
        super().__init__()
        self._get_menu = get_menu
        self._state = None
        lay = _vbox(20, 6)
        self.setLayout(lay)
        hdr = QLabel("VRChat menu")
        hdr.setObjectName("sectionTitle")
        lay.addWidget(hdr)
        lead = QLabel(
            "OGP's controls can be in your avatar's own menu too, so you never leave "
            "VRChat: drag one VRCFury prefab onto your avatar - your own controls, "
            "the Friends submenu, or both - and upload. Your avatar's own menu files "
            "aren't touched, and the parameters are unsynced (0 sync bits).")
        lead.setProperty("muted", "true")
        lead.setWordWrap(True)
        lay.addWidget(lead)
        self.rows = {}
        for key, title, what in _PARTS:
            row = _hbox(0, 6)
            mark = QLabel("")
            mark.setFixedWidth(14)
            row.addWidget(mark, 0, Qt.AlignTop)
            text = QLabel("")
            text.setWordWrap(True)
            text.setTextFormat(Qt.RichText)
            row.addWidget(text, 1)
            lay.addLayout(row)
            self.rows[key] = (mark, text, title, what)
        self.note = QLabel("")
        self.note.setProperty("muted", "true")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        btns = _hbox(0, 8)
        get = QPushButton("Get the menu prefabs")
        get.setProperty("role", "secondary")
        get.setCursor(Qt.PointingHandCursor)
        get.clicked.connect(lambda _=False: QDesktopServices.openUrl(QUrl(PREFAB_URL)))
        how = QPushButton("How to add it")
        how.setProperty("role", "secondary")
        how.setCursor(Qt.PointingHandCursor)
        how.clicked.connect(lambda _=False: QDesktopServices.openUrl(QUrl(GUIDE_URL)))
        btns.addWidget(get)
        btns.addWidget(how)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.get_btn, self.how_btn = get, how
        if explain is not None:
            explain(get, "Get the menu prefabs",
                    "Downloads OscGoesPurrr-VRCFury.unitypackage from the newest release. "
                    "Import it into your avatar's Unity project (it needs VRCFury), drag "
                    "one of its three prefabs onto your avatar and upload.")
            explain(how, "How to add it",
                    "The setup guide: the prefabs, a one-click installer for avatars "
                    "without VRCFury, the manual way, and every parameter.")
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.refresh(force=True)

    def showEvent(self, ev) -> None:  # noqa: N802
        self.refresh(force=True)
        super().showEvent(ev)

    def refresh(self, force: bool = False) -> None:
        """Only while on screen (or `force`); change-gated."""
        if not force and not self.isVisible():
            return
        try:
            menu = dict(self._get_menu() or {})
        except Exception:
            menu = {}
        self.set_state(menu)

    def set_state(self, menu: Dict[str, bool]) -> None:
        state = (bool(menu.get("known")), bool(menu.get("self")), bool(menu.get("friends")))
        if state == self._state:
            return
        self._state = state
        known = state[0]
        for key, (mark, text, title, what) in self.rows.items():
            on = known and bool(menu.get(key))
            mark.setText("✓" if on else "○")
            mark.setProperty("role", "success" if on else "")
            mark.setProperty("muted", "false" if on else "true")
            where = ("on the avatar you're wearing" if on else
                     "not on the avatar you're wearing" if known else "")
            text.setText(f"<b>{title}</b> - {what}" + (f" · <i>{where}</i>" if where else ""))
            mark.style().unpolish(mark)
            mark.style().polish(mark)
        self.note.setText(
            "" if known else "VRChat hasn't told OGP about an avatar yet - start VRChat with "
            "OSC on, and this says whether the avatar you're wearing has the menu.")
        self.note.setVisible(not known)
