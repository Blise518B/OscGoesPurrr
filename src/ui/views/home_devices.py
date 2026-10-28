"""Home's rows for what isn't an Intiface toy: the shocker hub (the
Shockers page) and each haptic suit (the Suits page). They sit in the toy
list itself, which places them (HomeMixin._toy_list_rows): one that is
switched on AND connected right under the connected toys -- toys, then
shockers, then suits -- and the rest at the bottom, greyed, under a small
"Shockers" / "Haptic suits" divider.

A row is the toy bar's sibling -- the same frame, the maker's logo in the
toy icon's slot, dot, name and muted summary, the same height, in the hue
of what it is -- and shows only while its feature is switched on. It says
where things stand; a click opens the page that sets it up. Two switches
sit on it:
  * the sharing switch -- "Share with friends" for the shockers (one
    switch for every friend, on top of each friend's own; off, friends
    don't see them at all), "Also feel ...'s contacts" for a suit (the
    Suits page's own; shown while the other suit is switched on too);
  * On / Off at the end (its label says which) -- the device for
    everyone: Off holds it stopped (the page's Stop all), still connected,
    kept across restarts, and friends don't see the shockers either; every
    sharing setting stays as it was.

The logos in Images/brand_icons/ are the makers' own site icons
(pishock.com, openshock.org, bhaptics.com, owogame.com), shrunk to 64 px,
there to say whose device a row is -- like the Lovense pictures. They are
their makers', not under our license: THIRD_PARTY_NOTICES.md says so
(tools/make_third_party_notices.py).

The words come from the pure functions shockers_row / bhaptics_row /
owo_row, so they are tested without a window."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QWidget

from ui import theme as _theme
from ui.layout_helpers import hbox as _hbox, vbox as _vbox
from ui.motor_signal_chain import _ElidedLabel
from ui.widgets import (
    OFFLINE_ICON_OPACITY, TOY_ICON_PX, TOY_ICON_SLOT_PX, ToggleSwitch, ToyFrame,
)

# More shocker names than this and the summary says "+2" instead.
_NAMES_SHOWN = 3

BRAND_ICONS_DIR = Path(_theme.asset_dir()) / "brand_icons"


# ----------------------------------------------------------------------
# What a row says (pure)
# ----------------------------------------------------------------------
#
# Each returns {connected, enabled, up, summary, pill, share, icon}:
# connected -- the device is there to use; enabled -- its On / Off;
# up -- both, so it sits with the connected toys in its hue; pill -- why
# it isn't connected (or ARMED); share -- the sharing switch, None hides it.

def _row(connected: bool, enabled: bool, summary: str, pill: Optional[tuple],
         share: Optional[bool], icon: str) -> Dict[str, Any]:
    return {"connected": connected, "enabled": enabled, "up": connected and enabled,
            "summary": summary, "pill": pill, "share": share, "icon": icon}


def shockers_row(st: Dict[str, Any], friends_on: bool) -> Dict[str, Any]:
    """The shocker hub's row from get_pishock_status(). It counts as
    connected only while the hub is connected AND has a shocker it can use:
    one paired to it (PiShock) or on the page's list (OpenShock) that isn't
    paused on pishock.com. Whether that shocker is switched on nobody can
    tell: the hub's radio only sends."""
    hub_up = bool(st.get("connected"))
    enabled = not st.get("paused")
    shockers = st.get("shockers") or []
    usable = [s for s in shockers if not s.get("paused")]
    connected = hub_up and bool(usable)
    hub = st.get("hub_name") or "Hub"
    if hub_up and shockers:
        names = [str(s.get("name") or f"Shocker {s.get('id')}") for s in shockers]
        shown = ", ".join(names[:_NAMES_SHOWN])
        if len(names) > _NAMES_SHOWN:
            shown += f" +{len(names) - _NAMES_SHOWN}"
        summary = f"{hub} · {shown}"
    elif hub_up:
        summary = f"{hub} connected · no shocker paired yet"
    elif st.get("connecting"):
        summary = "Connecting to the hub…"
    else:
        summary = st.get("last_error") or "Hub not connected"
    if not hub_up:
        pill = ("OFFLINE", "idle")
    elif not shockers:
        pill = ("NO SHOCKER", "idle")
    elif not usable:
        pill = ("PAUSED IN PISHOCK", "idle")
    elif enabled and st.get("armed"):
        pill = ("ARMED", "err")
    else:
        pill = None
    # an OpenShock hub (or its list, while it's unplugged) wears OpenShock's logo
    kind = st.get("hub_kind") or ("openshock" if st.get("openshock_shockers") else "pishock")
    return _row(connected, enabled, summary, pill,
                bool(st.get("friends_may_use", True)) if friends_on else None,
                "openshock" if kind == "openshock" else "pishock")


def bhaptics_row(st: Dict[str, Any], owo_on: bool) -> Dict[str, Any]:
    """The bHaptics suit's row from get_suits_status()["bhaptics"]."""
    devices: List[Dict[str, Any]] = st.get("devices") or []
    connected = bool(devices)
    if connected:
        summary = ", ".join(str(d.get("label") or d.get("name") or "bHaptics")
                            for d in devices)
        batteries = [d["battery"] for d in devices if d.get("battery") is not None]
        if batteries:
            summary += f" · 🔋 {min(batteries)} %"
    elif not st.get("available", True):
        summary = st.get("error") or "Bluetooth unavailable"
    elif st.get("released"):
        summary = "Let go - the bHaptics Player can have it"
    elif st.get("scanning"):
        summary = "Looking for the suit…"
    else:
        summary = st.get("error") or "Not connected"
    settings = st.get("settings") or {}
    return _row(connected, not st.get("paused"), summary,
                None if connected else ("OFFLINE", "idle"),
                bool(settings.get("follow_owo")) if owo_on else None, "bhaptics")


def owo_row(st: Dict[str, Any], bhaptics_on: bool) -> Dict[str, Any]:
    """The OWO suit's row from get_suits_status()["owo"]."""
    connected = bool(st.get("connected"))
    if connected:
        summary = "Connected through My OWO"
    elif st.get("error"):
        summary = st["error"]
    elif st.get("wanted"):
        summary = "Looking for My OWO…"
    else:
        summary = "My OWO not connected"
    settings = st.get("settings") or {}
    return _row(connected, not st.get("paused"), summary,
                None if connected else ("OFFLINE", "idle"),
                bool(settings.get("follow_bhaptics")) if bhaptics_on else None, "owo")


# ----------------------------------------------------------------------
# The row
# ----------------------------------------------------------------------

_pixmaps: Dict[tuple, Optional[QPixmap]] = {}


def brand_pixmap(kind: str, grey: bool = False) -> Optional[QPixmap]:
    """A maker's logo, 64 px (None when its file is missing); grey = the
    same in shades of grey, its transparency kept."""
    key = (kind, grey)
    if key not in _pixmaps:
        pm = QPixmap(str(BRAND_ICONS_DIR / f"{kind}.png"))
        if pm.isNull():
            _pixmaps[key] = None
        elif grey:
            img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
            out = img.convertToFormat(QImage.Format_Grayscale8).convertToFormat(
                QImage.Format_ARGB32)
            out.setAlphaChannel(img.convertToFormat(QImage.Format_Alpha8))
            _pixmaps[key] = QPixmap.fromImage(out)
        else:
            _pixmaps[key] = pm
    return _pixmaps[key]


class _BrandIcon(QWidget):
    """The maker's logo in the toy icon's slot -- the same size as a toy
    bar's, so a row lines up with the toys and is as tall as they are: in
    colour while the row is up, grey and faded like an offline toy's icon
    while it isn't."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._live = False
        self.setFixedSize(TOY_ICON_SLOT_PX, TOY_ICON_SLOT_PX)

    def set_look(self, kind: str, live: bool) -> None:
        if (kind, live) != (self._kind, self._live):
            self._kind, self._live = kind, live
            self.update()

    def paintEvent(self, _ev) -> None:  # noqa: N802
        pm = brand_pixmap(self._kind, grey=not self._live)
        if pm is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if not self._live:
            p.setOpacity(OFFLINE_ICON_OPACITY)
        off = (TOY_ICON_SLOT_PX - TOY_ICON_PX) / 2
        p.drawPixmap(QRectF(off, off, TOY_ICON_PX, TOY_ICON_PX), pm, QRectF(pm.rect()))
        p.end()


class ListDivider(QWidget):
    """The small divider above the offline shockers or suits at the bottom
    of the toy list: a dim caption and a hairline."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        lay = _hbox(0, 8)
        lay.setContentsMargins(4, 8, 0, 0)
        self.setLayout(lay)
        caption = QLabel(title.upper())
        caption.setObjectName("listDivider")
        lay.addWidget(caption)
        line = QFrame()
        line.setObjectName("listDividerLine")
        line.setFixedHeight(1)
        lay.addWidget(line, 1, Qt.AlignVCenter)


class _PowerSwitch(ToggleSwitch):
    """On / Off, saying which -- as wide for either word (measured in the
    font it has), so the switch beside it never moves."""

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = self.fontMetrics()
        words = max(fm.horizontalAdvance("On"), fm.horizontalAdvance("Off"))
        return QSize(self._TRACK_W + self._LABEL_SPACING + words + 2,
                     super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()


class _RowBar(QWidget):
    """The clickable bar: a click (or Space / Return) opens the page. The
    buttons and the switch on it take their own clicks."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toyBar")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if (not ev.isAutoRepeat()
                and ev.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter)):
            self.clicked.emit()
            ev.accept()
        else:
            super().keyPressEvent(ev)


class HomeDeviceRow(ToyFrame):
    """One row: logo, dot, name, summary, a state pill, the sharing
    switch, On / Off and a › that says a click goes somewhere.

    icon -- the logo it starts with (set_state may change it: a hub on
    OpenShock firmware); on_open() -- the bar was clicked; on_power(on) --
    the On / Off switch was flipped; on_share(on); apply_dot(dot,
    connected) -- the toy bars' own connection dot."""

    def __init__(self, title: str, hue: str, icon: str, share_text: str,
                 on_open: Callable[[], None], on_power: Callable[[bool], None],
                 on_share: Callable[[bool], None],
                 apply_dot: Callable[[QFrame, bool], None], parent=None):
        super().__init__(parent)
        self.setObjectName("toyFrame")
        self._on_hue = hue
        self._apply_dot = apply_dot
        self._state: Optional[Dict[str, Any]] = None
        lay = _vbox(3, 0)
        self.setLayout(lay)

        bar = _RowBar()
        bar.clicked.connect(on_open)
        bl = _hbox(0, 8)
        bl.setContentsMargins(8, 5, 8, 5)
        bar.setLayout(bl)
        self.bar = bar

        self.icon = _BrandIcon(icon)
        bl.addWidget(self.icon)
        self.dot = QFrame()
        self.dot.setObjectName("connectDot")
        self.dot.setFixedSize(12, 12)
        bl.addWidget(self.dot, 0, Qt.AlignVCenter)
        self.name = QLabel(title)
        self.name.setObjectName("deviceName")
        bl.addWidget(self.name)
        # takes what's left and ends in "…" rather than widening the window
        self.summary = _ElidedLabel("")
        self.summary.setObjectName("toyZones")
        bl.addWidget(self.summary, 1)

        self.pill = QLabel("")
        self.pill.setProperty("role", "pill")
        self.pill.setVisible(False)
        bl.addWidget(self.pill, 0, Qt.AlignVCenter)

        self.share = ToggleSwitch(share_text)
        self.share.toggled.connect(lambda on: on_share(bool(on)))
        bl.addWidget(self.share)
        bl.addSpacing(10)

        # the device for everyone: On, or held stopped -- says which
        self.power = _PowerSwitch("Off")
        self.power.toggled.connect(lambda on: on_power(bool(on)))
        bl.addWidget(self.power)

        caret = QLabel("›")
        caret.setObjectName("expandCaret")
        caret.setFixedWidth(18)
        caret.setAlignment(Qt.AlignCenter)
        bl.addWidget(caret)
        lay.addWidget(bar)

    @property
    def up(self) -> bool:
        """Switched on and connected: it sits with the connected toys."""
        return bool(self._state and self._state["up"])

    def set_state(self, s: Dict[str, Any]) -> None:
        """What shockers_row / bhaptics_row / owo_row worked out."""
        old, self._state = self._state, s
        self.icon.set_look(s["icon"], s["up"])
        hue = self._on_hue if s["up"] else _theme.OFFLINE_HUE
        if self.bar.property("hue") != hue:
            for w in (self, self.bar, self.name, self.summary):
                w.setProperty("hue", hue)
                w.style().unpolish(w)
                w.style().polish(w)
            self.set_hue(hue)
        if old is None or old["connected"] != s["connected"]:
            self._apply_dot(self.dot, s["connected"])
        self.summary.set_full_text(s["summary"])
        pill = s["pill"]
        self.pill.setVisible(pill is not None)
        if pill is not None and (self.pill.text(), self.pill.property("tone")) != pill:
            self.pill.setText(pill[0])
            self.pill.setProperty("tone", pill[1])
            self.pill.style().unpolish(self.pill)
            self.pill.style().polish(self.pill)
        self.share.setVisible(s["share"] is not None)
        for switch, on in ((self.share, s["share"]), (self.power, s["enabled"])):
            if on is not None and switch.isChecked() != on:
                switch.blockSignals(True)
                switch.setChecked(on)
                switch.blockSignals(False)
        word = "On" if s["enabled"] else "Off"
        if self.power.text() != word:
            self.power.setText(word)
