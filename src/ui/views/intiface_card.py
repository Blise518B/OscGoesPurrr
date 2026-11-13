"""Settings → Intiface Engine: the built-in toy server, or an Intiface
Central you run yourself -- on this PC or on a phone on the same network
(intiface_external.py). Off the built-in one, the card says where OGP is
connecting and how to set up a phone, live while it's on screen.

Talks to the controller only through the callables it is given
(get_intiface_link_status, set_intiface_integrated, set_intiface_address)."""

import time
from typing import Any, Callable, Dict, Optional, Tuple

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QWidget

from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import Card, ToggleSwitch
from ui.frame_clock import when_on_screen

_REFRESH_MS = 1000

# On screen only what's needed (Blise's ask, 2026-11-03: no walls of text);
# the details live in the hover explanations.
LEAD = "OGP runs Intiface for you. Off: use your own Intiface Central, on this PC or a phone."

PHONE_HOWTO = (
    "On a phone, turn on Intiface Central's <b>Listen on all network "
    "interfaces</b> and <b>Broadcast Server Info via mDNS</b>.")

TOGGLE_EXPLAIN = (
    "On (recommended): OGP runs its own toy server, nothing else to install "
    "or start. Off: connect to an Intiface Central you start yourself, on this "
    "PC or on a phone on the same network. Switching reconnects on its "
    "own.")

ADDRESS_EXPLAIN = (
    "Empty: OGP finds Intiface Central by itself, on this PC or on your "
    "network, and keeps trying until one answers. Or type a phone's address, "
    "like <b>192.168.1.50</b> (add <b>:port</b> if you changed Intiface's "
    "Server Port).<br><br>"
    "On the phone: <b>Listen on all network interfaces</b> lets OGP reach "
    "it; <b>Broadcast Server Info via mDNS</b> (under Show "
    "Advanced/Experimental Settings) lets OGP find it without an address. "
    "Keep Intiface Central open while you play. Needs Intiface Central 3.0 "
    "or newer; finding a phone by itself, 3.1.")


def status_text(st: Dict[str, Any]) -> Tuple[str, str]:
    """(text, role) for the live line under the address box: "success" once
    connected, "" (muted) while looking."""
    target = str(st.get("target") or "")
    name = str(st.get("target_name") or "")
    address = str(st.get("address") or "")
    if st.get("connected") and target:
        if st.get("target_local"):
            return "✓ Connected, on this PC", "success"
        return f"✓ Connected to {name or 'Intiface'} at {target}", "success"
    if st.get("connected"):
        return "✓ Connected", "success"
    if st.get("too_old"):
        return (f"The Intiface at {target or address} is older than 3.0. "
                "Update Intiface Central there, then start its server again.", "warning")
    if address:
        return f"Trying {address} …", ""
    found = list(st.get("found") or [])
    if found:
        first = found[0]
        more = f" (+{len(found) - 1})" if len(found) > 1 else ""
        return (f"Found {first.get('name')} at {first.get('host')}:{first.get('port')}"
                f"{more}, connecting…"), ""
    return "Looking on this PC and your network…", ""


def sidebar_lines(st: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """The sidebar's Intiface section off the built-in engine (Blise's ask,
    2026-11-03: see the address, and whether an Intiface is found there):
    (address, what is there, accent "ok" / "warn" / ""). "" for the address
    while there is none to show yet. None with the built-in engine on --
    the sidebar keeps its one line then."""
    if st.get("built_in", True):
        return None
    target = str(st.get("target") or "")
    name = str(st.get("target_name") or "")
    address = str(st.get("address") or "")
    found = list(st.get("found") or [])
    if st.get("connected"):
        if st.get("target_local"):
            return target or "127.0.0.1:12345", "✓ Intiface on this PC", "ok"
        return target or address, f"✓ {name or 'Intiface'} found", "ok"
    if st.get("too_old"):
        # It answered, but speaks an older Buttplug than OGP (intiface_facade).
        return target or address, "Intiface there is too old: update it to 3.0+", "warn"
    if address:
        # A typed address is only "found" once it answers: nothing knocks
        # to find out sooner (intiface_external.py).
        return address, "No Intiface found there yet", "warn"
    if found:
        first = found[0]
        return (f"{first.get('host')}:{first.get('port')}",
                f"✓ {first.get('name')} found, connecting…", "ok")
    return "", "Looking on this PC and your network…", ""


# The sidebar offers its own address box only after this long without
# finding anything (a phone usually answers within a second, so it
# doesn't flash up at every launch).
ENTER_GRACE_S = 8.0
# As tall as the sidebar's own link buttons (ui_components._SIDEBAR_LINK_BTN_H).
_SIDE_BTN_H = 26


class _AddressBox(QLineEdit):
    """The sidebar's address box: Esc closes it."""

    def __init__(self, on_escape: Callable[[], None]):
        super().__init__()
        self._on_escape = on_escape

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self._on_escape()
            return
        super().keyPressEvent(ev)


class IntifaceSidebarInfo(QWidget):
    """Under the sidebar's Intiface row while the built-in engine is off:
    the address OGP connects to and what it found there. Hidden with the
    built-in engine on. A click opens Settings → Intiface Engine
    (`on_click`). Polls `get_status` (the controller's
    get_intiface_link_status) once a second -- it has to see the switch
    being turned off, so it can't stop while hidden; the call is cheap.

    When the search finds nothing for ENTER_GRACE_S -- nothing announces
    itself, or a typed address doesn't answer -- an **Enter address**
    button appears (Blise's call, 2026-11-03: a fallback once the automatic
    part has failed, one button that unfolds, not a box always there). It
    opens a box right here, filled with the address in use; Enter applies
    it through `set_address` (the controller's set_intiface_address), Esc
    closes it. Once something is found or connected, button and box go."""

    def __init__(self, get_status: Callable[[], Dict[str, Any]],
                 on_click: Optional[Callable[[], None]] = None,
                 on_change: Optional[Callable[[], None]] = None,
                 set_address: Optional[Callable[[str], Tuple[bool, str]]] = None,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self._get_status = get_status
        self._on_click = on_click
        # Called after any change, so the host can re-face the row's pill
        # (SEARCHING while OGP looks by itself) and its buttons.
        self._on_change = on_change
        self._set_address = set_address
        self._clock = clock
        self._state = None
        self._stuck_since: Optional[float] = None
        self._address_now = ""
        lay = _vbox(0, 1)
        lay.setContentsMargins(2, 0, 0, 2)
        self.setLayout(lay)
        self.address = QLabel("")
        self.address.setObjectName("sidebarLinkAddr")
        self.address.setWordWrap(True)
        self.address.setTextInteractionFlags(Qt.NoTextInteraction)
        lay.addWidget(self.address)
        self.found = QLabel("")
        self.found.setObjectName("sidebarLinkSub")
        self.found.setWordWrap(True)
        lay.addWidget(self.found)

        self.enter_btn = QPushButton("Enter address")
        self.enter_btn.setProperty("role", "sideSmall")
        self.enter_btn.setFixedHeight(_SIDE_BTN_H)
        self.enter_btn.setCursor(Qt.PointingHandCursor)
        self.enter_btn.clicked.connect(self.open_box)
        self.enter_btn.setVisible(False)
        lay.addSpacing(3)
        lay.addWidget(self.enter_btn)
        self.box = _AddressBox(self.close_box)
        self.box.setPlaceholderText("e.g. 192.168.1.50")
        self.box.setMinimumWidth(0)
        self.box.returnPressed.connect(self._apply)
        self.box.setVisible(False)
        lay.addWidget(self.box)
        self.box_error = QLabel("")
        self.box_error.setObjectName("sidebarLinkSub")
        self.box_error.setProperty("accent", "warn")
        self.box_error.setWordWrap(True)
        self.box_error.setVisible(False)
        lay.addWidget(self.box_error)

        if on_click is not None:
            self.setCursor(Qt.PointingHandCursor)
        self.setVisible(False)
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(when_on_screen(self, self.refresh))
        self._timer.start()
        self.refresh()

    # ---- the Enter address fold ----------------------------------------
    @staticmethod
    def _stuck(st: Dict[str, Any]) -> bool:
        """OGP keeps looking and has nothing: no announcement on the
        network (and no address typed), or a typed address that doesn't
        answer."""
        if not st.get("looking") or st.get("connected"):
            return False
        return bool(st.get("address")) or not st.get("found")

    def _offer_box(self, st: Dict[str, Any]) -> bool:
        if self._set_address is None or not self._stuck(st):
            self._stuck_since = None
            return False
        now = self._clock()
        if self._stuck_since is None:
            self._stuck_since = now
        return now - self._stuck_since >= ENTER_GRACE_S

    def open_box(self, _=False) -> None:
        self.box.setText(self._address_now)
        self.box_error.setVisible(False)
        self.enter_btn.setVisible(False)
        self.box.setVisible(True)
        self.box.setFocus()
        self.box.selectAll()

    def close_box(self) -> None:
        self.box.setVisible(False)
        self.box_error.setVisible(False)
        self._state = None              # the button comes back if still stuck
        self.refresh()

    def _apply(self) -> None:
        if self._set_address is None:
            return
        try:
            ok, value = self._set_address(self.box.text())
        except Exception as e:
            ok, value = False, str(e)
        if not ok:
            self.box_error.setText(value)
            self.box_error.setVisible(True)
            return
        # A new address gets the whole grace before the button comes back.
        self._stuck_since = self._clock()
        self.close_box()

    # ---- refresh -----------------------------------------------------------
    def refresh(self) -> None:
        """Change-gated."""
        try:
            st = dict(self._get_status() or {})
        except Exception:
            st = {}
        self._address_now = str(st.get("address") or "")
        lines = sidebar_lines(st)
        offer = lines is not None and self._offer_box(st)
        box_open = self.box.isVisibleTo(self)
        if box_open and (lines is None or not self._stuck(st)):
            # found, connected or the switch back on: the box has done its job
            self.box.setVisible(False)
            self.box_error.setVisible(False)
            box_open = False
        state = (lines, bool(st.get("looking")), bool(st.get("connected")), offer, box_open)
        if state == self._state:
            return
        self._state = state
        self.enter_btn.setVisible(offer and not box_open)
        if lines is None:
            self.setVisible(False)
        else:
            address, found, accent = lines
            self.address.setText(address)
            self.address.setVisible(bool(address))
            self.found.setText(found)
            self.found.setProperty("accent", accent)
            self.found.style().unpolish(self.found)
            self.found.style().polish(self.found)
            self.setVisible(True)
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                pass

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        # Not while the box is open: a click beside it isn't a trip to
        # Settings.
        if (self._on_click is not None and ev.button() == Qt.LeftButton
                and not self.box.isVisibleTo(self)):
            self._on_click()
        super().mouseReleaseEvent(ev)


class IntifaceEngineCard(Card):
    """`get_status()` is the controller's get_intiface_link_status;
    `set_built_in(bool)` its set_intiface_integrated; `set_address(text)`
    its set_intiface_address, (ok, stored form or why not);
    `explain(widget, title, text)` the host's hover."""

    def __init__(self, get_status: Callable[[], Dict[str, Any]],
                 set_built_in: Callable[[bool], None],
                 set_address: Callable[[str], Tuple[bool, str]],
                 explain: Optional[Callable] = None):
        super().__init__()
        self._get_status = get_status
        self._set_built_in = set_built_in
        self._set_address = set_address
        self._state = None
        st = self._status()

        lay = _vbox(20, 6)
        self.setLayout(lay)
        hdr = QLabel("Intiface Engine")
        hdr.setObjectName("sectionTitle")
        lay.addWidget(hdr)
        lead = QLabel(LEAD)
        lead.setProperty("muted", "true")
        lead.setWordWrap(True)
        lay.addWidget(lead)

        self.toggle = ToggleSwitch("Use built-in Intiface engine")
        self.toggle.setChecked(bool(st.get("built_in", True)))
        self.toggle.toggled.connect(self._on_toggled)
        lay.addWidget(self.toggle)

        # Only while the built-in one is off: where the user's own runs.
        self.external = QWidget()
        ext = _vbox(0, 6)
        self.external.setLayout(ext)
        row = _hbox(0, 8)
        label = QLabel("Address")
        row.addWidget(label)
        self.address_edit = QLineEdit(str(st.get("address") or ""))
        self.address_edit.setPlaceholderText(
            "found by itself — or a phone's, like 192.168.1.50")
        self.address_edit.setClearButtonEnabled(True)
        self.address_edit.editingFinished.connect(self._on_address)
        row.addWidget(self.address_edit, 1)
        ext.addLayout(row)
        self.error = QLabel("")
        self.error.setProperty("role", "warning")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        ext.addWidget(self.error)
        self.state_label = QLabel("")
        self.state_label.setWordWrap(True)
        ext.addWidget(self.state_label)
        self.phone = QLabel(PHONE_HOWTO)
        self.phone.setProperty("muted", "true")
        self.phone.setWordWrap(True)
        self.phone.setTextFormat(Qt.RichText)
        ext.addWidget(self.phone)
        lay.addWidget(self.external)
        self.external.setVisible(not self.toggle.isChecked())

        if explain is not None:
            explain(self.toggle, "Built-in Intiface engine", TOGGLE_EXPLAIN)
            explain(row, "Where Intiface runs", ADDRESS_EXPLAIN)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(when_on_screen(self, self.refresh))
        self._timer.start()
        self.refresh(force=True)

    def _status(self) -> Dict[str, Any]:
        try:
            return dict(self._get_status() or {})
        except Exception:
            return {}

    def _on_toggled(self, checked: bool) -> None:
        self._set_built_in(bool(checked))
        self.external.setVisible(not checked)
        self.refresh(force=True)

    def _on_address(self) -> None:
        try:
            ok, value = self._set_address(self.address_edit.text())
        except Exception as e:
            ok, value = False, str(e)
        if ok:
            if self.address_edit.text() != value:
                self.address_edit.setText(value)
            self.error.setVisible(False)
        else:
            self.error.setText(value)
            self.error.setVisible(True)
        self.refresh(force=True)

    def showEvent(self, ev) -> None:  # noqa: N802
        self.refresh(force=True)
        super().showEvent(ev)

    def refresh(self, force: bool = False) -> None:
        """Only while on screen (or `force`); change-gated."""
        if not force and not self.isVisible():
            return
        if self.toggle.isChecked():
            return
        st = self._status()
        # The sidebar's box can change the address too: show the one in use
        # (never under the user's fingers, or over a refused one shown in red).
        stored = str(st.get("address") or "")
        if (not self.address_edit.hasFocus() and self.error.isHidden()
                and self.address_edit.text() != stored and "address" in st):
            self.address_edit.setText(stored)
        text, role = status_text(st)
        if (text, role) == self._state:
            return
        self._state = (text, role)
        self.state_label.setText(text)
        self.state_label.setProperty("role", role)
        self.state_label.setProperty("muted", "false" if role else "true")
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)
