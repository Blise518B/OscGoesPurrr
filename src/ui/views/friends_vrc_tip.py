"""The tip at the foot of the Friends page: the same controls are in the
avatar's menu -- and whether the avatar you're wearing has it. Hovering
lists the menu; the links get the prefabs."""

from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ui.theme import PALETTE

_PREFAB_URL = ("https://github.com/Blise518B/OscGoesPurrr/raw/main/docs/unity/"
               "OscGoesPurrr-VRCFury.unitypackage")
_MENU_GUIDE_URL = "https://github.com/Blise518B/OscGoesPurrr/blob/main/docs/VRCHAT_MENU.md"
# The avatar menu's Friends part (docs/unity/OGP_MenuInstaller.cs builds
# it): (name, kind, what it does, children).
_VRC_FRIENDS_MENU = (
    ("Toys", "menu", "", (
        ("Level", "radial", "direct control - their card switches to Direct control", ()),
        ("Auto mode", "menu", "Sine, Square, Triangle, Saw, Random, Heartbeat, "
                              "Build-up, Oscillate", ()),
        ("Speed", "radial", "how fast the auto mode runs", ()),
        ("Range", "radial", "how high it goes (Oscillate: how deep it swings)", ()),
        ("Override", "toggle", "your level replaces their own output", ()),
        ("Which toys", "menu", "Toy 1-4, all on", ()),
        ("Stop toys", "button", "level 0, auto mode off", ()),
    )),
    ("Shockers", "menu", "", (
        ("Shock, Vibrate, Beep, Stop", "buttons", "", ()),
        ("Strength", "radial", "part of their own caps", ()),
        ("Length", "radial", "part of their longest pulse", ()),
        ("Warning", "toggle", "1-3 s of vibration before each shock", ()),
        ("Which shockers", "menu", "Shocker 1-4, all on", ()),
    )),
    ("Both of us", "menu", "the same on them and on you", (
        ("Level, Speed", "radials", "", ()),
        ("Auto mode", "menu", "the same eight", ()),
        ("Stop, Shock, Vibrate", "buttons", "", ()),
        ("Strength, Length", "radials", "part of each one's own caps", ()),
    )),
    ("Their strength", "radial", "their own strength slider", ()),
)


def _menu_html() -> str:
    def items(nodes) -> str:
        out = []
        for name, kind, what, children in nodes:
            line = f"<b>{name}</b> <i>{kind}</i>" + (f" - {what}" if what else "")
            out.append(f"<li>{line}{items(children) if children else ''}</li>")
        return "<ul style='margin:2px 0 2px -18px'>" + "".join(out) + "</ul>"
    return ("<b>OscGoesPurrr ▸ Friends</b> in your avatar's menu"
            + items(_VRC_FRIENDS_MENU)
            + "Everything acts on whoever is picked on this page.")


class VrchatMenuTip(QLabel):
    """The tip; `set_state(menu)` with the controller's get_avatar_menu()."""

    def __init__(self):
        super().__init__()
        self.setObjectName("friendsVrcTip")
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setOpenExternalLinks(True)
        self.setToolTip(_menu_html())
        self._state = None
        self.set_state({})

    def set_state(self, menu: Dict[str, bool]) -> None:
        """Says whether the avatar you're wearing has the menu."""
        state = ("on" if menu.get("friends") else "off") if menu.get("known") else "unknown"
        if state == self._state:
            return
        self._state = state
        link = f"color:{PALETTE['cyan'][0]}; text-decoration:none"
        links = (f'<a style="{link}" href="{_PREFAB_URL}">Get the menu prefabs</a> · '
                 f'<a style="{link}" href="{_MENU_GUIDE_URL}">How to add it</a>')
        if state == "on":
            text = ("✓ Your avatar has the OGP Friends menu - control from VRChat is on: "
                    "<b>OscGoesPurrr ▸ Friends</b> acts on the friend or group picked here. "
                    "Hover to see the menus")
            role, muted = "success", "false"
        elif state == "off":
            text = ("This avatar has no OGP Friends menu - add it to control friends from "
                    f"VRChat. Hover to see what it has · {links}")
            role, muted = "", "true"
        else:
            text = ("These controls are in your VRChat menu too - <b>OscGoesPurrr ▸ Friends</b> "
                    f"acts on the friend or group picked here. Hover to see them · {links}")
            role, muted = "", "true"
        self.setText(text)
        self.setProperty("role", role)
        self.setProperty("muted", muted)
        self.style().unpolish(self)
        self.style().polish(self)
