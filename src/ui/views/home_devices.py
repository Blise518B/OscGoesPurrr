"""Home's rows for what isn't an Intiface toy: the shocker hub (the
Shockers page) and each haptic suit (the Suits page). They sit in the toy
list itself, which places them (HomeMixin._toy_list_rows): one that is
switched on AND connected right under the connected toys -- toys, then
shockers, then suits -- and the rest at the bottom, greyed, under a small
"Shockers" / "Haptic suits" divider.

A row is the toy bar's sibling -- the same frame, the maker's logo in the
toy icon's slot, dot, name and muted summary, the same height, in the hue
of what it is -- and shows only while its feature is switched on. It says
where things stand; a click opens the page that sets it up. Its switches:
  * Arm shocks, the shocker row's only -- shocks are real; until then each
    goes out as a vibrate. Switching it on asks first, in its own place,
    and red words beside it say Shocks armed / Shocks not armed
    (shocker_switches.ArmSwitch, ARM_ASKS_FROM);
  * the sharing switch -- "Share with friends" for the shockers (one
    switch for every friend, on top of each friend's own; off, friends
    don't see them at all), "Also feel ...'s contacts" for a suit (the
    Suits page's own; shown while the other suit is switched on too);
  * On / Off at the end (its label says which) -- the device for
    everyone: Off holds it stopped (the page's Stop all), still connected,
    kept across restarts, and friends don't see the shockers either; every
    sharing setting stays as it was.
The shocker row's three are the very switches the Shockers page shows: one
setting each, redrawn in both places when either changes
(shocker_switches.py says how they stack).

The logos in Images/brand_icons/ are the makers' own site icons
(pishock.com, openshock.org, bhaptics.com, owogame.com), shrunk to 64 px,
there to say whose device a row is -- like the Lovense pictures. They are
their makers', not under our license: THIRD_PARTY_NOTICES.md says so
(tools/make_third_party_notices.py).

The words come from the pure functions shockers_row / bhaptics_row /
owo_row, so they are tested without a window."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QWidget

from ui import icons as _icons
from ui import theme as _theme
from ui.layout_helpers import hbox as _hbox, vbox as _vbox
from ui.motor_signal_chain import _ElidedLabel
from ui.views.shocker_switches import ArmSwitch
from ui.widgets import (
    OFFLINE_ICON_OPACITY, TOY_ICON_PX, TOY_ICON_SLOT_PX, ToggleSwitch, ToyFrame,
)

# More shocker names than this and the summary says "+2" instead.
_NAMES_SHOWN = 3

# A row's lines under the first start under the name, as a toy bar's do
# (device_frame._TOY_BAR_INDENT): past the logo, the dot and their gaps.
_INDENT = TOY_ICON_SLOT_PX + 8 + 12 + 8
# The summary gets at least this much of the first line before the
# switches move down -- or it would shrink to "Pi…" first.
_SUMMARY_ROOM = 150
# The gap after Arm shocks and after the sharing switch on one line.
_SWITCH_GAP = 10

BRAND_ICONS_DIR = Path(_theme.asset_dir()) / "brand_icons"
# Rows with no logo in brand_icons/ that show their identity icon instead
# (ui/icons.identity_icon): the PSVR2 headset, whose software side is a
# community project (PSVR2Toolkit) rather than the headset's maker -- and
# the headset's icon is the same everywhere it is named.
_DRAWN = frozenset({"psvr2"})


# ----------------------------------------------------------------------
# What a row says (pure)
# ----------------------------------------------------------------------
#
# Each returns {connected, enabled, up, summary, pill, share, armed, icon}:
# connected -- the device is there to use; enabled -- its On / Off;
# up -- both, so it sits with the connected toys in its hue; pill -- why
# it isn't connected; share -- the sharing switch, None hides it;
# armed -- Arm shocks (the shocker row's only, with its own red words for
# armed or not), None hides it.

def _row(connected: bool, enabled: bool, summary: str, pill: Optional[tuple],
         share: Optional[bool], icon: str, armed: Optional[bool] = None) -> Dict[str, Any]:
    return {"connected": connected, "enabled": enabled, "up": connected and enabled,
            "summary": summary, "pill": pill, "share": share, "armed": armed,
            "icon": icon}


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
    else:                   # armed or not: Arm's own red words say that
        pill = None
    # an OpenShock hub (or its list, while it's unplugged) wears OpenShock's logo
    kind = st.get("hub_kind") or ("openshock" if st.get("openshock_shockers") else "pishock")
    return _row(connected, enabled, summary, pill,
                bool(st.get("friends_may_use", True)) if friends_on else None,
                "openshock" if kind == "openshock" else "pishock",
                armed=bool(st.get("armed")))


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


def psvr2_row(st: Dict[str, Any]) -> Dict[str, Any]:
    """The PSVR2 headset's row from get_psvr2_status(). Connected = joined
    to the PSVR2Toolkit driver (SteamVR running with the toolkit). Whether
    the motor can move nobody can tell: a headset that isn't jailbroken
    takes the commands and stays still."""
    connected = bool(st.get("connected"))
    hz = (st.get("extras") or {}).get("rumble_hz")
    if connected:
        summary = (f"PSVR2Toolkit · rumbling at {int(hz)} Hz" if hz
                   else "Connected through PSVR2Toolkit")
    elif not st.get("available", True):
        summary = st.get("last_error") or "PSVR2Toolkit not found"
    elif st.get("auto_connect"):
        summary = st.get("last_error") or "Waiting for SteamVR…"
    else:
        summary = st.get("last_error") or "Not connected"
    return _row(connected, not st.get("paused"), summary,
                None if connected else ("OFFLINE", "idle"), None, "psvr2")


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
        if pm is None and self._kind in _DRAWN:
            # its identity icon (in its colour now), grey while not up
            icon = (_icons.identity_icon(self._kind, TOY_ICON_PX) if self._live
                    else _icons.drawn_icon(self._kind, _theme.hue("grey"), TOY_ICON_PX))
            pm = icon.pixmap(QSize(TOY_ICON_PX, TOY_ICON_PX), self.devicePixelRatioF())
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


class _FitWatch(QObject):
    """Calls back when the watched bar is resized or its contents ask for
    a new layout (Arm shocks' question, a switch shown) -- the row
    re-deciding which line its switches go on."""

    def __init__(self, target: QWidget, callback: Callable[[], None]):
        super().__init__(target)
        self._callback = callback
        target.installEventFilter(self)

    def eventFilter(self, _obj, event):  # noqa: N802 (Qt API)
        if event.type() in (QEvent.Resize, QEvent.LayoutRequest):
            self._callback()
        return False


def _layout_width(w: QWidget) -> int:
    return max(w.minimumWidth(), min(w.sizeHint().width(), w.maximumWidth()))


class HomeDeviceRow(ToyFrame):
    """One row: logo, dot, name, summary, a state pill, Arm (given one),
    the sharing switch, On / Off and a › that says a click goes somewhere.
    All on one line while they fit; in a narrower window Arm and the
    sharing switch move to a line under the name (and at the narrowest
    one line each), so the row never needs a sideways scrollbar -- as a
    toy bar's chips do (_fit).

    icon -- the logo it starts with (set_state may change it: a hub on
    OpenShock firmware); on_open() -- the bar was clicked; on_power(on) --
    the On / Off switch was flipped; on_share(on); arm -- the shocker row's
    shocker_switches.ArmSwitch (it reports itself); apply_dot(dot,
    connected) -- the toy bars' own connection dot."""

    def __init__(self, title: str, hue: str, icon: str, share_text: str,
                 on_open: Callable[[], None], on_power: Callable[[bool], None],
                 on_share: Callable[[bool], None],
                 apply_dot: Callable[[QFrame, bool], None],
                 arm: Optional[ArmSwitch] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("toyFrame")
        self._on_hue = hue
        self._apply_dot = apply_dot
        self._state: Optional[Dict[str, Any]] = None
        lay = _vbox(3, 0)
        self.setLayout(lay)

        bar = _RowBar()
        bar.clicked.connect(on_open)
        # its lines are arranged for the room it has (_fit): never wider
        # than its parent gives, or the page would scroll sideways instead
        bar.setMinimumWidth(1)
        outer = _vbox(0, 3)
        outer.setContentsMargins(8, 5, 8, 5)
        bar.setLayout(outer)
        self.bar = bar
        self.lines: List = []
        for i in range(3):
            line = _hbox(0, 8)
            if i:
                line.setContentsMargins(_INDENT, 0, 0, 0)
            outer.addLayout(line)
            self.lines.append(line)

        self.icon = _BrandIcon(icon, bar)
        self.dot = QFrame(bar)
        self.dot.setObjectName("connectDot")
        self.dot.setFixedSize(12, 12)
        self.name = QLabel(title, bar)
        self.name.setObjectName("deviceName")
        # takes what's left and ends in "…" rather than widening the window
        self.summary = _ElidedLabel("", bar)
        self.summary.setObjectName("toyZones")

        self.pill = QLabel("", bar)
        self.pill.setProperty("role", "pill")
        self.pill.setVisible(False)

        # Arm (its red words for armed or not included) after the pill, then
        # sharing, then On / Off -- the Shockers page's order
        self.arm = arm
        if arm is not None:
            arm.setParent(bar)

        self.share = ToggleSwitch(share_text, bar)
        self.share.toggled.connect(lambda on: on_share(bool(on)))

        # the device for everyone: On, or held stopped -- says which
        self.power = _PowerSwitch("Off", bar)
        self.power.toggled.connect(lambda on: on_power(bool(on)))

        caret = QLabel("›", bar)
        caret.setObjectName("expandCaret")
        caret.setFixedWidth(18)
        caret.setAlignment(Qt.AlignCenter)
        self.caret = caret
        lay.addWidget(bar)
        self._arranged: Optional[int] = None
        self._arrange(1)
        _FitWatch(bar, self._fit)

    # ---- which line each switch is on ----------------------------------
    def _row_lines(self, n: int) -> list:
        """The bar's three lines with `n` of them in use: widgets in order,
        an int for a gap, "stretch" for the line's slack. The summary is
        the first line's slack itself."""
        head = [self.icon, self.dot, self.name, self.summary, self.pill]
        tail = [self.power, self.caret]
        arm = [self.arm] if self.arm is not None else []
        if n == 1:
            return [head + (arm + [_SWITCH_GAP] if arm else []) + [self.share, _SWITCH_GAP]
                    + tail, [], []]
        if n == 2 or not arm:
            return [head + tail, arm + ([_SWITCH_GAP] if arm else []) + [self.share, "stretch"],
                    []]
        return [head + tail, arm + ["stretch"], [self.share, "stretch"]]

    def _arrange(self, n: int) -> None:
        """Put the widgets on their lines; only when that changed. Every
        widget stays the bar's child -- the lines are layouts inside its
        layout -- so nothing is re-parented or re-shown."""
        if self._arranged == n:
            return
        self._arranged = n
        for lay in self.lines:
            while lay.count():
                lay.takeAt(0)
        for lay, items in zip(self.lines, self._row_lines(n)):
            for it in items:
                if isinstance(it, int):
                    lay.addSpacing(it)
                elif it == "stretch":
                    lay.addStretch(1)
                elif it is self.summary:
                    lay.addWidget(it, 1)
                else:
                    lay.addWidget(it, 0, Qt.AlignVCenter)

    def _need(self, n: int) -> int:
        """How wide the widest of the bar's lines is with `n` in use."""
        need = 0
        for i, items in enumerate(self._row_lines(n)):
            width, shown = 0, 0
            for it in items:
                if isinstance(it, int):
                    width += it
                elif it != "stretch" and it.isVisibleTo(self.bar):
                    width += (min(_SUMMARY_ROOM, self.summary.fontMetrics().horizontalAdvance(
                        self.summary.full_text()) + 4) if it is self.summary
                        else _layout_width(it))
                    shown += 1
            if not shown:
                continue
            width += self.lines[0].spacing() * (shown - 1) + (_INDENT if i else 0)
            need = max(need, width)
        return need

    def _fit(self) -> None:
        """One line while everything fits, else the switches under the name
        (then one line each). A pure function of the bar's width."""
        try:
            m = self.bar.layout().contentsMargins()
            room = self.bar.width() - m.left() - m.right()
            for n in (1, 2, 3):
                if self._need(n) <= room:
                    break
            self._arrange(n)
        except RuntimeError:
            pass        # torn down meanwhile

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
        armed = s.get("armed")
        if self.arm is not None:
            self.arm.setVisible(armed is not None)
            if armed is not None:
                self.arm.set_armed(armed)
        for switch, on in ((self.share, s["share"]), (self.power, s["enabled"])):
            if on is not None and switch.isChecked() != on:
                switch.blockSignals(True)
                switch.setChecked(on)
                switch.blockSignals(False)
        word = "On" if s["enabled"] else "Off"
        if self.power.text() != word:
            self.power.setText(word)
