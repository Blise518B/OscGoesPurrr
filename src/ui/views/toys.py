"""Toys -- every toy and how it responds, on a page of its own.

Home became the overview for everything (Blise's call, 2026-11-14: "the
detailed settings will move somewhere else"); a toy's row there is its
bar alone, and a click on it opens the toy here, at its card.

Top to bottom:
- Toys + Scan now -- the heading, a button to look for toys right now and
                     when the app looks next by itself.
- Toy server      -- the Intiface link: connected / searching, where (built
                     in, or your own Intiface Central and what was found
                     there), Connect while it is down and nothing brings it
                     up by itself, and the way to Settings → Intiface Engine.
                     The sidebar keeps its own pill, on every page.
- the toy cards   -- ui/views/device_frame.py: each toy's bar (the same as
                     its row on Home), folded to that one row until it is
                     clicked, opening into its signal chains.
                     Toys that are remembered but switched off stay listed
                     in a grey outline.
- SPS Sources     -- your own zones built from raw contacts
                     (ui/views/sps_sources.py), folded.
- Tuning tools    -- the input simulator and the signal graph, folded
                     until you tune (ui/views/dashboard.py builds the bar).

The active mode -- the one a toy's zones and Touch / Penetration chips
edit -- is the sidebar's, on every page; this page has no copy of it.

Live updates: motor meters and batteries are pushed by DeviceFrameMixin.
A 2 Hz timer covers what has no push channel -- each toy's "what drives
it" summary and chips, the scan countdown, the toy server line -- and only
while the page is on screen."""

from typing import Any, Dict, Tuple

import shiboken6
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from constants import BTN_HEIGHT_SMALL

from ui.frame_clock import when_on_screen
from ui.layout_helpers import hbox as _hbox, vbox as _vbox
from ui.theme import FRIEND_TOYS_HUE
from ui.views.antistuck_box import AntiStuckBox
from ui.motor_signal_chain import ChainOverviewPanel as _ChainOverviewPanel
from ui.views.click_bars import FoldHeader as _FoldHeader
from ui.views.intiface_card import status_text as _intiface_status_text
from ui.widgets import (
    Card as _Card,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


# The page's name in the sidebar and in ui.views.
TOYS_PAGE = "Toys"

# Refresh cadence for the summaries, the scan countdown and the toy server
# line: reads as live for a countdown and costs a few dict reads.
_TOYS_REFRESH_MS = 500

# The card list scrolls inside its own box; below this height the page
# scrolls instead, so an open fold can never squeeze the list away.
_TOY_LIST_MIN_H = 200

# Between two toy cards: more than the 8 px between the parts of one card.
_TOY_GAP_PX = 14

# A jump from Home waits this long for the page to lay itself out, so the
# card it opened has a place to scroll to.
_SETTLE_MS = 30
# The opened card lands this far below the top of the list.
_CARD_TOP_PX = 4


def server_line(st: Dict[str, Any], connected: bool) -> Tuple[str, str]:
    """(what the toy server line says, its accent "ok" / "warn" / "") from
    the controller's get_intiface_link_status() and whether the toy server
    is connected. Built in: where it runs; your own Intiface Central: the
    same words as Settings → Intiface Engine."""
    if st.get("built_in", True):
        if connected:
            return "✓ Built in, on this PC", "ok"
        return "Built in, not connected", ""
    text, role = _intiface_status_text(st)
    return text, {"success": "ok", "warning": "warn"}.get(role, "")


def server_pill(connected: bool, looking: bool) -> Tuple[str, str]:
    """The toy server's pill, as the sidebar's (ui_components._face_toy_pill):
    CONNECTED, SEARCHING (looking for your own Intiface by itself) or
    DISCONNECTED -- (text, tone)."""
    if connected:
        return "CONNECTED", "ok"
    if looking:
        return "SEARCHING", "off"
    return "DISCONNECTED", "off"


class ToysMixin:

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_toys_view(self, parent_layout: QVBoxLayout):
        # ===== Heading: Toys, Scan now =====
        head = QWidget()
        hl = _hbox(0, 6)
        head.setLayout(hl)
        title = QLabel("Toys")
        title.setObjectName("homeTitle")
        hl.addWidget(title)
        hl.addSpacing(8)
        self._explain(title,
            "Toys",
            "Every toy you have connected, plus the ones you've used before "
            "that are switched off right now (grey). The bar shows what "
            "drives the toy in the active mode, who it hears, its battery "
            "and a live meter per motor - the same as its row on Home.<br><br>"
            "Each toy starts folded to its bar. <b>Click the bar</b> to open "
            "it on each motor's <b>signal chains</b>, folded - click one to "
            "set it up (Input → Depth/Speed/Punch → "
            "Combine → Wake → Envelope → Zero cut → "
            "Output — click any stage to edit it). Another click on the bar "
            "folds the toy away. <b>Mute</b> silences the toy without "
            "touching its setup; <b>Test</b> gives it a short buzz.")
        # Right beside the heading (Blise's ask, 2026-10-28): a button to
        # look now, and when the app looks by itself next
        scan_now = QPushButton("Scan now")
        scan_now.setProperty("role", "secondary")
        scan_now.setFixedHeight(BTN_HEIGHT_SMALL)
        scan_now.setCursor(Qt.PointingHandCursor)
        scan_now.clicked.connect(lambda _=False: self._on_scan_now())
        self._explain(
            scan_now, "Scan now",
            "Look for toys right now - for a toy you just switched on. The "
            "app also looks by itself: every few seconds while no toy is "
            "connected (Settings → Connection Settings sets how often), "
            "every 30 seconds while one is.")
        hl.addWidget(scan_now)
        self._toy_scan_btn = scan_now
        self._toy_scan_lbl = QLabel("")
        self._toy_scan_lbl.setProperty("muted", "true")
        hl.addWidget(self._toy_scan_lbl)
        hl.addStretch(1)
        parent_layout.addWidget(head)
        self._style_root(head)

        # ===== Toy server =====
        server = self._build_toy_server_card()
        parent_layout.addWidget(server)
        self._style_root(server)

        # ===== Anti-stuck, the toys' own (antistuck.py) =====
        stuck = self._build_toys_antistuck_card()
        parent_layout.addWidget(stuck)
        self._style_root(stuck)

        # ===== The toy cards =====
        # Straight on the page -- no card around the cards -- in a box of
        # their own that scrolls, so the folds stay under them.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(_TOY_LIST_MIN_H)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        # A little more room between toys than inside one, so a card's end
        # reads as its end (Blise's ask, 2026-11-17); each card's bar has a
        # hairline under it too (ToyFrame.set_head).
        self.unified_devices_layout = _vbox(0, _TOY_GAP_PX)
        self.unified_devices_layout.addStretch(1)
        inner.setLayout(self.unified_devices_layout)
        scroll.setWidget(inner)
        self.unified_devices_frame = inner
        self._toys_list_scroll = scroll
        parent_layout.addWidget(scroll, 1)

        # ===== SPS Sources =====
        self._sps_fold = self._build_sps_fold()
        parent_layout.addWidget(self._sps_fold)
        self._style_root(self._sps_fold)

        # ===== Tuning tools =====
        self._tuning_tools = self._build_tuning_tools()
        parent_layout.addWidget(self._tuning_tools)
        self._style_root(self._tuning_tools)

        if getattr(self, "_toys_refresh_timer", None) is None:
            t = QTimer(self.window)
            t.setInterval(_TOYS_REFRESH_MS)
            t.timeout.connect(when_on_screen(self, self._refresh_toys_dynamic))
            t.start()
            self._toys_refresh_timer = t
        self._refresh_toy_server()

    def _toys_page_shown(self) -> bool:
        """The Toys page is the one on screen (True on a host without a page
        stack, the tests')."""
        stack = getattr(self, "main_stack", None)
        page = (getattr(self, "views", None) or {}).get(TOYS_PAGE)
        return stack is None or page is None or stack.currentWidget() is page

    def _refresh_toys_dynamic(self) -> None:
        """What has no push channel. Skipped while the page is hidden;
        select_view refreshes on arrival."""
        if not self._toys_page_shown():
            return
        for refresh in (self._refresh_toy_scan, self._refresh_toy_server,
                        self._refresh_toy_summaries, self._refresh_sps_summary,
                        self._toys_antistuck.refresh):
            try:
                refresh()
            except Exception:
                pass

    # ----------------------------------------------------------
    # Scan now
    # ----------------------------------------------------------

    def _refresh_toy_scan(self) -> None:
        """"Next scan in 4 s" / "Scanning…" beside Scan now."""
        lbl = getattr(self, "_toy_scan_lbl", None)
        if lbl is None:
            return
        get = getattr(self.controller, "get_toy_scan_status", None)
        st = get() if callable(get) else None
        if not st or not st["up"]:
            text = ""
        elif st["scanning"]:
            text = "Scanning…"
        elif st["next_in"] is not None:
            text = f"Next scan in {st['next_in']} s"
        else:
            text = "" if st["auto"] else "Looking for toys is off"
        if lbl.text() != text:
            lbl.setText(text)
        self._toy_scan_btn.setEnabled(bool(st and st["up"]))

    def _on_scan_now(self) -> None:
        self.controller.scan_for_toys()
        self._toy_scan_lbl.setText("Scanning…")

    # ----------------------------------------------------------
    # Toy server
    # ----------------------------------------------------------

    def _build_toy_server_card(self) -> QWidget:
        """One slim line: "Toy server [CONNECTED] ✓ Built in, on this PC",
        Connect while it is down and nothing brings it up by itself, and
        Intiface settings."""
        card = _Card()
        lay = _hbox(0, 8)
        lay.setContentsMargins(12, 6, 12, 6)
        card.setLayout(lay)
        name = QLabel("Toy server")
        name.setObjectName("cardHeader")
        lay.addWidget(name)
        pill = QLabel("DISCONNECTED")
        pill.setProperty("role", "pill")
        pill.setProperty("tone", "off")
        pill.setAlignment(Qt.AlignCenter)
        lay.addWidget(pill, 0, Qt.AlignVCenter)
        where = QLabel("")
        where.setObjectName("sidebarLinkSub")
        where.setWordWrap(True)
        lay.addWidget(where, 1)
        connect = QPushButton("Connect")
        connect.setProperty("role", "secondary")
        connect.setFixedHeight(BTN_HEIGHT_SMALL)
        connect.setCursor(Qt.PointingHandCursor)
        connect.clicked.connect(lambda _=False: self.controller.connect_to_intiface())
        connect.setVisible(False)
        lay.addWidget(connect)
        settings = QPushButton("Intiface settings")
        settings.setProperty("role", "secondary")
        settings.setFixedHeight(BTN_HEIGHT_SMALL)
        settings.setCursor(Qt.PointingHandCursor)
        settings.clicked.connect(lambda _=False: self._open_intiface_settings())
        lay.addWidget(settings)

        self._explain((name, pill, where), "Toy server",
            "The Buttplug.io server that talks to your Bluetooth toys. OGP "
            "runs its own copy, so there is nothing else to start, and it "
            "connects and reconnects by itself. With the built-in engine "
            "switched off, this says where your own Intiface Central is - on "
            "this PC or a phone - and whether it was found.")
        self._explain(connect, "Connect to the toy server",
            "Normally automatic: the app starts its toy server and connects "
            "on launch, and reconnects if the link drops. You only see this "
            "with \"Auto Connect (Intiface)\" switched off in Settings, or "
            "after a failed start.")
        self._explain(settings, "Intiface settings",
            "Opens Settings → Intiface Engine: the built-in toy server, or "
            "your own Intiface Central, on this PC or on a phone on the same "
            "network.")
        self._toy_server_card = card
        self._toy_server_pill = pill
        self._toy_server_where = where
        self._toy_server_connect = connect
        return card

    # ----------------------------------------------------------
    # Anti-stuck for the toys
    # ----------------------------------------------------------

    def _build_toys_antistuck_card(self) -> QWidget:
        """The toys' anti-stuck -- its switch and timers, for every toy --
        on a slim card under Toy server; each toy's bar has its own on /
        off beside the Touch / Penetration chips."""
        card = _Card()
        lay = _vbox(0, 6)
        lay.setContentsMargins(12, 8, 12, 8)
        card.setLayout(lay)
        self._toys_antistuck = AntiStuckBox(
            "Toys' anti-stuck", "a toy going",
            get=lambda: self.controller.get_toys_antistuck(),
            set_=self._on_toys_antistuck,
            explain=self._explain, hue=FRIEND_TOYS_HUE,
            extra="Each toy's bar has an <b>Anti-stuck</b> of its own too, "
                  "to leave one toy out.")
        lay.addWidget(self._toys_antistuck)
        self._toys_antistuck_card = card
        return card

    def _on_toys_antistuck(self, **changes) -> None:
        set_ = getattr(self.controller, "set_toys_antistuck", None)
        if callable(set_):
            set_(**changes)
        refresh = getattr(self, "_refresh_safety_chips", None)
        if callable(refresh):
            refresh()                   # the toys' chips grey or light with it

    def _open_intiface_settings(self) -> None:
        reveal = getattr(self, "reveal", None)
        if callable(reveal) and reveal("intiface"):
            return
        self.select_view("Settings")

    def _refresh_toy_server(self) -> None:
        """The pill, the line and Connect, as the sidebar's Intiface row
        shows them. Change-gated; also run when the sidebar's row changes
        (ui_components._face_toy_pill / refresh_link_buttons)."""
        pill = getattr(self, "_toy_server_pill", None)
        if pill is None:
            return
        connected = bool(getattr(self, "_toy_server_connected", False))
        get = getattr(self.controller, "get_intiface_link_status", None)
        try:
            st = dict(get() or {}) if callable(get) else {}
        except Exception:
            st = {}
        looking = bool(st.get("looking"))
        text, tone = server_pill(connected, looking)
        line, accent = server_line(st, connected)
        state = (text, tone, line, accent, not connected and not looking)
        if state == getattr(self, "_toy_server_state", None):
            return
        self._toy_server_state = state
        try:
            pill.setText(text)
            pill.setProperty("tone", tone)
            self._repolish(pill)
            where = self._toy_server_where
            where.setText(line)
            where.setProperty("accent", accent)
            self._repolish(where)
            self._toy_server_connect.setVisible(state[-1])
        except RuntimeError:
            pass

    # ----------------------------------------------------------
    # Home's row -> the toy's card here
    # ----------------------------------------------------------

    def open_toy_card(self, device_name: str) -> None:
        """A click on a toy's row on Home: this page, the toy's card open
        and scrolled to the top of the list."""
        data = self.device_ui_frames.get(device_name)
        if not data:
            return
        if TOYS_PAGE in (getattr(self, "views", None) or {}):
            self.select_view(TOYS_PAGE)
        expand = data.get("set_expanded")
        if callable(expand):
            expand(True)
        QTimer.singleShot(_SETTLE_MS, lambda n=device_name: self._scroll_to_toy(n))

    def _scroll_to_toy(self, device_name: str) -> None:
        data = self.device_ui_frames.get(device_name) or {}
        card = data.get("frame")
        scroll = getattr(self, "_toys_list_scroll", None)
        if card is None or scroll is None or not shiboken6.isValid(card):
            return
        inner = scroll.widget()
        if inner is None or not inner.isAncestorOf(card):
            return
        top = card.mapTo(inner, QPoint(0, 0)).y()
        scroll.verticalScrollBar().setValue(max(0, top - _CARD_TOP_PX))

    # ----------------------------------------------------------
    # SPS Sources fold
    # ----------------------------------------------------------

    def _build_sps_fold(self) -> QWidget:
        """SPS Sources (ui/views/sps_sources.py) behind one bar: you build
        a source once and pick it in a toy's Input stage from then on, so
        it stays folded until opened. The bar says how many there are."""
        host = QWidget()
        lay = _vbox(0, 6)
        host.setLayout(lay)
        head = _FoldHeader("SPS Sources")
        self._explain(head,
            "SPS Sources",
            "Your own zones, built from raw VRChat contact receivers - for "
            "spots the standard SPS zones don't cover, or an avatar without "
            "them. Each source becomes a zone you can pick in any toy's "
            "Input stage, like the ones your avatar's SPS provides. Click to "
            "open or close.")
        lay.addWidget(head)
        body = QWidget()
        body_lay = _vbox(0, 8)
        body.setLayout(body_lay)
        build = getattr(self, "_build_sps_sources_view", None)
        if callable(build):
            build(body_lay)
        body.setVisible(False)
        lay.addWidget(body)

        def set_open(is_open: bool) -> None:
            body.setVisible(bool(is_open))
            head.set_open(bool(is_open))
            if is_open:
                self._refresh_sps_source_values_now()

        head.clicked.connect(lambda: set_open(body.isHidden()))
        self._sps_head = head
        self._sps_body = body
        self._refresh_sps_summary()
        return host

    def _refresh_sps_source_values_now(self) -> None:
        refresh = getattr(self, "_refresh_sps_source_values", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass

    def _refresh_sps_summary(self) -> None:
        head = getattr(self, "_sps_head", None)
        get = getattr(self.controller, "get_sps_sources", None)
        if head is None or not callable(get):
            return
        try:
            n = len(get() or ())
        except Exception:
            return
        text = (f"{n} source" if n == 1 else f"{n} sources") if n \
            else "Your own zones from any contact"
        if head.summary.text() != text:
            head.summary.setText(text)

    # ----------------------------------------------------------
    # Tuning tools fold
    # ----------------------------------------------------------

    def _build_tuning_tools(self) -> QWidget:
        """The simulator and the signal graph behind one bar. Neither is
        needed to play, so they stay folded; the bar's right edge says what
        is switched on inside, so a playing simulator is never out of
        sight. Open/closed is remembered (under its old name,
        home_tuning_tools_open: it was Home's)."""
        host = QWidget()
        lay = _vbox(0, 6)
        host.setLayout(lay)

        head = _FoldHeader("Tuning tools")
        self._explain(head,
            "Tuning tools",
            "For when you are shaping how a toy responds: the <b>input "
            "simulator</b> (a synthetic stroke to tune against without a "
            "partner) and the <b>signal graph</b> of one chain. Click to "
            "open or close."
        )
        lay.addWidget(head)

        body = QWidget()
        body_lay = _vbox(0, 6)
        body.setLayout(body_lay)
        body_lay.addWidget(self._build_routing_top_bar())
        # The graph lives directly under the bar, framed like it, and only
        # exists on screen while its toggle is on.
        self._signal_graph_panel = _ChainOverviewPanel(self.controller)
        self._signal_graph_panel.setObjectName("card")
        self._signal_graph_panel.setVisible(False)
        body_lay.addWidget(self._signal_graph_panel)
        lay.addWidget(body)

        self._tuning_head = head
        self._tuning_body = body

        def set_open(is_open: bool, persist: bool = True) -> None:
            body.setVisible(bool(is_open))
            head.set_open(bool(is_open))
            if persist:
                self.controller.set_app_setting(
                    "home_tuning_tools_open", bool(is_open))

        # isHidden, not isVisible: the fold's own state, whatever the page
        # around it is doing.
        head.clicked.connect(lambda: set_open(body.isHidden()))
        set_open(bool(self.controller.get_app_setting(
            "home_tuning_tools_open", False)), persist=False)

        for signal in (self._sim_play_btn.toggled,
                       self._signal_graph_toggle.toggled):
            signal.connect(self._refresh_tuning_summary)
        self._refresh_tuning_summary()
        return host

    def _refresh_tuning_summary(self, *_a) -> None:
        """What is running inside the fold; while nothing is, what it
        holds."""
        head = getattr(self, "_tuning_head", None)
        if head is None:
            return
        parts = []
        if self._sim_play_btn.isChecked():
            parts.append("Simulator playing")
        if self._signal_graph_toggle.isChecked():
            parts.append("signal graph on" if parts else "Signal graph on")
        try:
            head.summary.setText(" · ".join(parts)
                                 or "Simulator · signal graph")
        except RuntimeError:
            pass
