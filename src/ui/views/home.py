"""Home -- the landing page: every toy, live, and nothing you have to set
up first.

One page does what Overview and Device Routing used to split between
them. A toy's collapsed bar IS its overview (connection, battery, what
drives it, a meter per motor, Mute, Test); clicking the bar opens the
signal-chain editor in place. Toys that are remembered but switched off
stay listed in a grey outline.

Top to bottom:
- Getting started -- three ticks, hidden once all three are green.
- Toys            -- the toy cards (ui/views/device_frame.py) + Test all.
- Tuning tools    -- the input simulator and the signal graph, folded away
                     until you tune (ui/views/dashboard.py builds the bar
                     itself).

The VRChat link, the active mode and the toy server are not repeated
here: the sidebar shows all three on every page.

Live updates: motor meters and batteries are pushed by DeviceFrameMixin.
A 2 Hz timer covers the two things without a push channel -- the
checklist and each toy's "what drives it" summary -- and only while the
page is on screen."""

from typing import Dict

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from constants import (
    BTN_HEIGHT_SMALL, COLOR_SUCCESS, COLOR_TEXT, COLOR_TEXT_MUTED,
)

from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.motor_signal_chain import ChainOverviewPanel as _ChainOverviewPanel
from ui.widgets import (
    Card as _Card,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


# Refresh cadence for the checklist and the toy summaries. 2 Hz reads as
# live for a tick mark and costs a few dict reads.
_HOME_REFRESH_MS = 500

# The toy list scrolls inside its card; below this height the page scrolls
# instead, so an open Tuning tools fold can never squeeze the list away.
_TOY_LIST_MIN_H = 200


class _FoldHeader(QFrame):
    """The clickable bar of a fold: caret, title, and a dim one-line
    summary of what is inside. Reachable by Tab, toggled by Space/Return."""

    clicked = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("toolsFoldBar")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        lay = _hbox(0, 8)
        lay.setContentsMargins(12, 7, 12, 7)
        self.setLayout(lay)
        self._caret = QLabel("▸")
        self._caret.setObjectName("expandCaret")
        self._caret.setFixedWidth(14)
        lay.addWidget(self._caret)
        name = QLabel(title)
        name.setObjectName("cardHeader")
        lay.addWidget(name)
        self.summary = QLabel("")
        self.summary.setProperty("hint", "true")
        self.summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.summary, 1)

    def set_open(self, is_open: bool) -> None:
        self._caret.setText("▾" if is_open else "▸")

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


class HomeMixin:

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_home_view(self, parent_layout: QVBoxLayout):
        # No page title of its own: the sidebar's Home entry says where
        # you are, and the Toys heading below doubles as the title.

        # ===== Getting started =====
        # The app's home page is also where a first-time user finds out
        # what still has to line up before a toy responds.
        self._build_setup_checklist(parent_layout)

        # Shown instead of the toy list while the toy server feature is off
        # (apply_feature_visibility swaps the two).
        self._home_toys_off_note = self._muted_label(
            "Toys are switched off. Turn the toy server back on in "
            "Settings → Features to see them here.")
        self._home_toys_off_note.setAlignment(Qt.AlignHCenter)
        self._home_toys_off_note.setVisible(False)
        parent_layout.addWidget(self._home_toys_off_note)
        self._style_root(self._home_toys_off_note)

        # ===== Toys =====
        # The list sits straight on the page -- no card around the cards.
        self.devices_container_frame = QWidget()
        container_lay = _vbox(0, 10)
        self.devices_container_frame.setLayout(container_lay)
        parent_layout.addWidget(self.devices_container_frame, 1)

        toys_hdr_row = QWidget()
        thl = _hbox(0, 6)
        toys_hdr_row.setLayout(thl)
        header = QLabel("Toys")
        header.setObjectName("homeTitle")
        thl.addWidget(header)
        thl.addStretch(1)
        self._explain(header,
            "Toys",
            "Every toy you have connected, plus the ones you've used before "
            "that are switched off right now (grey). The bar shows what "
            "drives the toy in the active mode, its battery and a live "
            "meter per motor.<br><br>"
            "<b>Click a bar</b> to set the toy up: its per-motor signal "
            "chains (Input → Depth/Speed/Punch → Combine → "
            "Wake → Envelope → Zero cut → Output — click "
            "any stage to edit it). <b>Mute</b> silences the toy without "
            "touching its setup; <b>Test</b> gives it a short buzz."
        )
        test_all = QPushButton("Test all")
        test_all.setProperty("role", "secondary")
        test_all.setFixedHeight(BTN_HEIGHT_SMALL)
        test_all.setCursor(Qt.PointingHandCursor)
        test_all.clicked.connect(
            lambda _=False: self.controller.trigger_purr_check())
        self._explain(
            test_all, "Test all",
            "Buzzes every connected toy gently for about a second, so you "
            "can tell at once which ones are really listening. Only "
            "vibrating motors take part — a stroker won't suddenly "
            "move.")
        thl.addWidget(test_all)
        # Enabled by update_stored_devices_ui while a toy is connected.
        self._test_all_button = test_all
        container_lay.addWidget(toys_hdr_row)
        # Home's sections for the live colour sweep are its pieces, not the
        # page: the page holds every toy, and a toy registers its own.
        self._style_root(toys_hdr_row)

        # Scrollable list of toy cards.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(_TOY_LIST_MIN_H)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        self.unified_devices_layout = _vbox(0, 8)
        self.unified_devices_layout.addStretch(1)
        inner.setLayout(self.unified_devices_layout)
        scroll.setWidget(inner)
        self.unified_devices_frame = inner
        container_lay.addWidget(scroll, 1)

        # ===== Tuning tools =====
        self._tuning_tools = self._build_tuning_tools()
        parent_layout.addWidget(self._tuning_tools)
        self._style_root(self._tuning_tools)

        # Refresh timer for what has no push channel.
        if getattr(self, "_home_refresh_timer", None) is None:
            t = QTimer(self.window)
            t.setInterval(_HOME_REFRESH_MS)
            t.timeout.connect(self._refresh_home_dynamic)
            t.start()
            self._home_refresh_timer = t

    def _refresh_home_dynamic(self) -> None:
        """The checklist and the toy summaries. Skipped while the page is
        hidden (2 Hz of facade polling is pure cost elsewhere);
        select_view refreshes on arrival."""
        view = self.views.get("Home")
        if view is not None and not view.isVisible():
            return
        for refresh in (self._refresh_setup_checklist,
                        self._refresh_toy_summaries):
            try:
                refresh()
            except Exception:
                pass

    # ----------------------------------------------------------
    # Getting-started checklist
    # ----------------------------------------------------------

    # (status key, what to do, what to know while it isn't done yet). In the
    # order a newcomer does them: the toy first -- Test all works without
    # VRChat -- then the game, then the avatar.
    _SETUP_STEPS = (
        ("toy", "Switch your toy on",
         "It's found by itself over Bluetooth, so this PC needs Bluetooth "
         "switched on — version 4.0 or newer, built in or a USB dongle. "
         "Close the toy's own phone app first: a toy only talks to one "
         "device at a time. And don't pair it in Windows' Bluetooth "
         "settings — most toys then refuse to connect (We-Vibe and "
         "Satisfyer are the exceptions)."),
        ("osc", "Start VRChat with OSC on",
         "In VRChat: Action menu → Options → OSC → Enabled. The app "
         "finds VRChat by itself — no IP or port to type — and it "
         "doesn't matter which of the two you start first."),
        ("zones", "Wear an avatar with SPS contacts",
         "SPS (or OGB) contacts are the sockets and plugs avatar creators "
         "add with VRCFury — they are what a touch triggers, so an avatar "
         "without them can't drive a toy. If yours has them and this stays "
         "unticked, use Options → OSC → Reset Config in VRChat and "
         "load the avatar again."),
    )

    _SETUP_LEAD_BUILT_IN = (
        "Nothing else to install — you don't need Intiface: the toy "
        "server is built in. Three things have to line up before a touch "
        "reaches a toy, and they tick off here as they happen.")
    _SETUP_LEAD_EXTERNAL = (
        "You've switched off the built-in toy server, so start Intiface "
        "Central yourself first (Settings → Intiface Engine turns the "
        "built-in one back on). Then three things have to line up, and "
        "they tick off here as they happen.")

    def _build_setup_checklist(self, parent_layout: QVBoxLayout) -> None:
        """What a first-time user needs to know and do, ticked off live:
        that nothing else has to be installed, then the three things that
        have to line up before you feel anything. Each step explains
        itself until it is done, then folds to its ticked title. The card
        hides itself once all three are green and comes back if one drops
        (VRChat closed, toy switched off)."""
        card = _Card()
        lay = _vbox(14, 7)
        card.setLayout(lay)
        hdr = QLabel("Getting started")
        hdr.setObjectName("cardHeader")
        lay.addWidget(hdr)
        self._setup_lead = self._muted_label(self._SETUP_LEAD_BUILT_IN)
        lay.addWidget(self._setup_lead)
        # Each step is a tick in its own fixed column and the text beside
        # it, so a wrapped line hangs under the text, not under the tick.
        self._setup_step_labels: Dict[str, tuple] = {}
        for key, title_text, detail_text in self._SETUP_STEPS:
            row = QWidget()
            row_lay = _hbox(0, 6)
            row.setLayout(row_lay)
            mark = QLabel("")
            mark.setFixedWidth(14)
            row_lay.addWidget(mark, 0, Qt.AlignTop)
            text_col = _vbox(0, 1)
            title = QLabel(title_text)
            title.setObjectName("setupStepTitle")
            text_col.addWidget(title)
            detail = self._muted_label(detail_text)
            text_col.addWidget(detail)
            row_lay.addLayout(text_col, 1)
            lay.addWidget(row)
            self._setup_step_labels[key] = (mark, title, detail)
        lay.addWidget(self._muted_label(
            "Then press Test all below — every connected toy buzzes for a "
            "second. Feel it? You're set. Click a toy to choose which parts "
            "of your avatar drive it."))
        self._setup_card = card
        self._setup_state = None
        parent_layout.addWidget(card)
        self._style_root(card)
        self._refresh_setup_checklist()

    def _refresh_setup_checklist(self) -> None:
        """Change-gated: rides the 2 Hz refresh, so an unchanged state
        costs one facade call, one setting read and a dict compare."""
        card = getattr(self, "_setup_card", None)
        if card is None:
            return
        try:
            state = dict(self.controller.get_setup_status())
            state["built_in"] = bool(self.controller.get_app_setting(
                "use_integrated_intiface", True))
        except Exception:
            return
        if state == self._setup_state:
            return
        self._setup_state = state
        try:
            self._setup_lead.setText(
                self._SETUP_LEAD_BUILT_IN if state["built_in"]
                else self._SETUP_LEAD_EXTERNAL)
            for key, _title, _detail in self._SETUP_STEPS:
                ok = bool(state.get(key))
                mark, title, detail = self._setup_step_labels[key]
                style = (f"color: {COLOR_SUCCESS};" if ok
                         else f"color: {COLOR_TEXT};")
                mark.setText("✓" if ok else "○")
                mark.setStyleSheet(
                    style if ok else f"color: {COLOR_TEXT_MUTED};")
                title.setStyleSheet(style)
                # A done step no longer needs its explanation.
                detail.setVisible(not ok)
        except RuntimeError:
            return
        card.setVisible(
            not all(bool(state.get(k)) for k, _t, _d in self._SETUP_STEPS))

    # ----------------------------------------------------------
    # Tuning tools fold
    # ----------------------------------------------------------

    def _build_tuning_tools(self) -> QWidget:
        """The simulator and the signal graph behind one bar. Neither is
        needed to play, so the landing page keeps them folded; the bar's
        right edge says what is switched on inside, so a playing simulator
        is never out of sight. Open/closed is remembered."""
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
