"""Home -- the landing page: every toy, live, and nothing you have to set
up first.

One page does what Overview and Device Routing used to split between
them. A toy's collapsed bar IS its overview (connection, battery, what
drives it, a meter per motor, Mute, Test); clicking the bar opens the
signal-chain editor in place. Toys that are remembered but switched off
stay listed in a grey outline.

Top to bottom:
- Getting started -- three ticks, hidden once all three are green; "Don't
                     show again" folds it for good to one slim line, a
                     light per step.
- Toys            -- the toy cards (ui/views/device_frame.py) + Test all,
                     and in the same list a row for the shocker hub and
                     each haptic suit while their feature is on
                     (ui/views/home_devices.py): switched on and
                     connected ones under the connected toys, the rest
                     greyed at the bottom under a small divider.
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

from ui import theme as _theme
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.motor_signal_chain import ChainOverviewPanel as _ChainOverviewPanel
from ui.views.home_devices import (
    HomeDeviceRow as _HomeDeviceRow, ListDivider as _ListDivider,
    bhaptics_row as _bhaptics_row, owo_row as _owo_row,
    shockers_row as _shockers_row,
)
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


class _ClickBar(QFrame):
    """A bar in the fold bars' look that does one thing when clicked.
    Reachable by Tab, pressed by Space/Return."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolsFoldBar")
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


class _FoldHeader(_ClickBar):
    """The clickable bar of a fold: caret, title, and a dim one-line
    summary of what is inside."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
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


class _SetupStrip(_ClickBar):
    """Getting started folded to one line (Blise's ask, 2026-10-28): a
    light and a few words per step -- "● Toy on  ● VRChat connected
    ● Avatar has SPS" -- and the card's name, dim, at the right. A click
    opens the card again."""

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        lay = _hbox(0, 6)
        lay.setContentsMargins(12, 5, 12, 5)
        self.setLayout(lay)
        self.lights: Dict[str, tuple] = {}
        for i, (key, text) in enumerate(steps):
            if i:
                lay.addSpacing(12)
            dot = QFrame()
            dot.setObjectName("connectDot")
            dot.setFixedSize(12, 12)
            lay.addWidget(dot, 0, Qt.AlignVCenter)
            name = QLabel(text)
            name.setObjectName("setupLight")
            lay.addWidget(name, 0, Qt.AlignVCenter)
            self.lights[key] = (dot, name)
        lay.addStretch(1)
        what = QLabel("Getting started")
        what.setProperty("hint", "true")
        lay.addWidget(what, 0, Qt.AlignVCenter)


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
        thl.addSpacing(8)
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
        thl.addWidget(scan_now)
        self._toy_scan_btn = scan_now
        self._toy_scan_lbl = QLabel("")
        self._toy_scan_lbl.setProperty("muted", "true")
        thl.addWidget(self._toy_scan_lbl)
        thl.addStretch(1)
        self._toy_scan_timer = QTimer(toys_hdr_row)
        self._toy_scan_timer.setInterval(500)
        self._toy_scan_timer.timeout.connect(self._refresh_toy_scan)
        self._toy_scan_timer.start()
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

        # ===== Shockers and suits =====
        self._build_home_devices(parent_layout)

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

    def _refresh_toy_scan(self) -> None:
        """"Next scan in 4 s" / "Scanning…" beside Scan now -- only while
        Home is the page shown."""
        stack = getattr(self, "main_stack", None)
        if stack is not None and stack.currentWidget() is not self.views.get("Home"):
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
        if self._toy_scan_lbl.text() != text:
            self._toy_scan_lbl.setText(text)
        self._toy_scan_btn.setEnabled(bool(st and st["up"]))

    def _on_scan_now(self) -> None:
        self.controller.scan_for_toys()
        self._toy_scan_lbl.setText("Scanning…")

    def _refresh_home_dynamic(self) -> None:
        """The checklist and the toy summaries. Skipped while the page is
        hidden (2 Hz of facade polling is pure cost elsewhere);
        select_view refreshes on arrival."""
        view = self.views.get("Home")
        if view is not None and not view.isVisible():
            return
        for refresh in (self._refresh_setup_checklist,
                        self._refresh_toy_summaries,
                        self._refresh_home_devices):
            try:
                refresh()
            except Exception:
                pass

    # ----------------------------------------------------------
    # Shockers and suits
    # ----------------------------------------------------------

    def _build_home_devices(self, parent_layout: QVBoxLayout) -> None:
        """A row for the shocker hub and one per suit. They live in the toy
        list, which places them (_toy_list_rows); each shows while its
        feature is on (_refresh_home_devices)."""
        c = self.controller
        inner = self.unified_devices_frame

        def after(fn):
            """Run a quick action, then show its result at once."""
            def run(*a):
                fn(*a)
                self._refresh_home_devices()
            return run

        shockers = _HomeDeviceRow(
            "Shockers", _theme.SHOCKERS_HUE, "pishock", "Share with friends",
            on_open=lambda: self.select_view("Shockers"),
            on_power=after(lambda on: c.pishock_resume() if on
                           else c.pishock_stop_all()),
            on_share=after(lambda on: c.set_pishock_friends_may_use(on)),
            apply_dot=self._apply_connect_dot, parent=inner)
        bhaptics = _HomeDeviceRow(
            "bHaptics", _theme.SUITS_HUE, "bhaptics", "Also feel OWO's contacts",
            on_open=lambda: self.select_view("Suits"),
            on_power=after(lambda on: c.bhaptics_resume() if on
                           else c.bhaptics_stop_all()),
            on_share=after(lambda on: c.set_bhaptics_option("follow_owo", on)),
            apply_dot=self._apply_connect_dot, parent=inner)
        owo = _HomeDeviceRow(
            "OWO", _theme.SUITS_HUE, "owo", "Also feel bHaptics' contacts",
            on_open=lambda: self.select_view("Suits"),
            on_power=after(lambda on: c.owo_resume() if on
                           else c.owo_stop_all()),
            on_share=after(lambda on: c.set_owo_option("follow_bhaptics", on)),
            apply_dot=self._apply_connect_dot, parent=inner)

        self._explain(shockers.bar, "Shockers",
            "Your shocker hub and the shockers it reports. Click the bar to "
            "open the Shockers page, where you connect, arm and set the "
            "limits. ARMED means shocks go out as shocks; otherwise they "
            "go out as vibrates.")
        self._explain(shockers.share, "Share with friends",
            "Sharing only, for all your friends at once: off, your friends "
            "don't see your shockers at all and nothing they send reaches "
            "them, whatever their own Shockers switch on the Friends page "
            "says. Your own rules and the Shockers page still work.")
        self._explain(shockers.power, "On / Off",
            "Your shockers, all of it. Off ends whatever they are doing now "
            "and keeps them quiet - your rules, friends, tests - until you "
            "switch them on again, even after a restart; friends don't see "
            "them meanwhile. The hub stays connected, and who may use them "
            "stays as you set it. The same as Stop all / Resume on the "
            "Shockers page.")
        for row, name in ((bhaptics, "bHaptics"), (owo, "OWO")):
            other = "OWO" if row is bhaptics else "bHaptics"
            self._explain(row.bar, name,
                f"Your {name} suit. Click the bar to open the Suits page, "
                "where you connect it and set what it feels.")
            self._explain(row.share, row.share.text(),
                f"The {name} suit also plays the touches that reach the "
                f"{other} suit's places on the body - the same switch as on "
                "the Suits page.")
            self._explain(row.power, "On / Off",
                f"Your {name} suit for everyone. Off sets it to zero now and "
                "keeps it there until you switch it on again, even after a "
                "restart. It stays connected, and its other settings stay as "
                "they are.")

        # The small dividers above the ones that aren't connected, at the
        # bottom of the list.
        self._home_shockers_divider = _ListDivider("Shockers", parent=inner)
        self._home_suits_divider = _ListDivider("Haptic suits", parent=inner)
        for w in (shockers, bhaptics, owo,
                  self._home_shockers_divider, self._home_suits_divider):
            w.setVisible(False)
            self._style_root(w)

        # With the toy server off the toy list steps aside for its note
        # (apply_feature_visibility); the rows go here instead.
        box = QWidget()
        self._home_devices_lay = _vbox(0, 8)
        self._home_devices_lay.addStretch(1)
        box.setLayout(self._home_devices_lay)
        box.setVisible(False)
        parent_layout.addWidget(box, 1)
        self._home_devices = box
        self._home_shockers_row = shockers
        self._home_bhaptics_row = bhaptics
        self._home_owo_row = owo
        self._home_rows_on = set()
        self._home_rows_key = None

    def _refresh_home_devices(self) -> None:
        c = self.controller
        on = c.get_feature_enabled
        rows_on = set()
        pishock = getattr(c, "get_pishock_status", None)
        if callable(pishock) and on("feature_pishock"):
            self._home_shockers_row.set_state(
                _shockers_row(pishock(), bool(on("feature_friends"))))
            rows_on.add(self._home_shockers_row)

        suits = getattr(c, "get_suits_status", None)
        bh_on = callable(suits) and bool(on("feature_bhaptics"))
        owo_on = callable(suits) and bool(on("feature_owo"))
        st = suits() if bh_on or owo_on else None
        if bh_on:
            self._home_bhaptics_row.set_state(_bhaptics_row(st["bhaptics"], owo_on))
            rows_on.add(self._home_bhaptics_row)
        if owo_on:
            self._home_owo_row.set_state(_owo_row(st["owo"], bh_on))
            rows_on.add(self._home_owo_row)
        self._home_rows_on = rows_on
        # Move rows only when one comes, goes or (dis)connects; the toy
        # list re-asks _toy_list_rows itself whenever it changes.
        if self._home_rows_state() != self._home_rows_key:
            self._place_home_devices()

    def _home_rows(self) -> tuple:
        return (self._home_shockers_row, self._home_bhaptics_row, self._home_owo_row)

    def _home_toys_on(self) -> bool:
        get = getattr(self.controller, "get_feature_enabled", None)
        return bool(get("feature_intiface")) if get else True

    def _home_rows_state(self) -> tuple:
        """What decides where the rows go: the toy server, and each row's
        (feature on, up)."""
        return (self._home_toys_on(),) + tuple(
            (r in self._home_rows_on, r.up) for r in self._home_rows())

    def _home_rows_split(self) -> tuple:
        """(the rows that are switched on and connected -- the shocker hub,
        then the suits; the rest with their dividers: a small "Shockers"
        one over the hub, a "Haptic suits" one over those suits)."""
        rows = self._home_rows()
        on = getattr(self, "_home_rows_on", ())
        up = [r for r in rows if r in on and r.up]
        bottom = []
        for divider, group in ((self._home_shockers_divider, rows[:1]),
                               (self._home_suits_divider, rows[1:])):
            offline = [r for r in group if r in on and not r.up]
            if offline:
                bottom += [divider] + offline
        return up, bottom

    def _toy_list_rows(self) -> tuple:
        """For the toy list, which places them (DeviceFrameMixin.
        _reorder_device_frames): (the rows right under the connected toys,
        the rows for the bottom). None while the toy server is off -- they
        are on Home's own box then (_place_home_devices)."""
        if getattr(self, "_home_shockers_row", None) is None or not self._home_toys_on():
            return (), ()
        return self._home_rows_split()

    def _place_home_devices(self) -> None:
        """Put the rows where they belong after one of them changed: in the
        toy list (it places them, _toy_list_rows) -- or, with the toy server
        off, the list steps aside for its note (apply_feature_visibility)
        and they go on Home's own box, in the same order."""
        if getattr(self, "_home_shockers_row", None) is None:
            return                      # Home isn't built yet
        widgets = self._home_rows() + (self._home_shockers_divider,
                                       self._home_suits_divider)
        box = self._home_devices_lay
        toys_on = self._home_toys_on()
        if toys_on:
            # out of the box first: a widget put in a second layout warns
            for w in widgets:
                i = box.indexOf(w)
                if i >= 0:
                    box.takeAt(i)
        self._reorder_device_frames()   # places them, or takes them out
        if toys_on:
            placed = getattr(self, "_toy_list_extras", ())
            for w in widgets:
                if w not in placed:
                    w.hide()
        else:
            up, bottom = self._home_rows_split()
            order = up + bottom
            current = [box.itemAt(i).widget() for i in range(box.count())
                       if box.itemAt(i).widget() in widgets]
            if current != order:
                for w in current:
                    box.takeAt(box.indexOf(w))
                for i, w in enumerate(order):
                    box.insertWidget(i, w)  # above the stretch
            for w in widgets:
                w.setVisible(w in order)
        self._home_devices.setVisible(not toys_on and bool(self._home_rows_on))
        self._home_rows_key = self._home_rows_state()

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
         "device at a time. And don't pair it in the system's Bluetooth "
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

    # The same three in a few words, for the folded line.
    _SETUP_SHORT = (("toy", "Toy on"), ("osc", "VRChat connected"),
                    ("zones", "Avatar has SPS"))
    # Set by "Don't show again"; the folded line's click clears it.
    _SETUP_COMPACT_KEY = "home_setup_compact"

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
        (VRChat closed, toy switched off).

        "Don't show again" (bottom right) folds it for good to one slim
        line at the same spot: a light per step, always there. Clicking
        that line opens the card again."""
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
        foot = _hbox(0, 12)
        foot.addWidget(self._muted_label(
            "Then press Test all below — every connected toy buzzes for a "
            "second. Feel it? You're set. Click a toy to choose which parts "
            "of your avatar drive it."), 1)
        hide = QPushButton("Don't show again")
        hide.setProperty("role", "secondary")
        hide.setFixedHeight(BTN_HEIGHT_SMALL)
        hide.setCursor(Qt.PointingHandCursor)
        hide.clicked.connect(lambda _=False: self._set_setup_compact(True))
        self._explain(hide, "Don't show again",
            "Folds Getting started to one line at the top of Home, for "
            "good: a light for each of the three steps - green when it's "
            "done. Click that line to see the steps again.")
        foot.addWidget(hide, 0, Qt.AlignBottom)
        lay.addLayout(foot)
        self._setup_hide_btn = hide

        strip = _SetupStrip(self._SETUP_SHORT)
        strip.clicked.connect(lambda: self._set_setup_compact(False))
        details = {k: d for k, _t, d in self._SETUP_STEPS}
        for key, (dot, name) in strip.lights.items():
            for w in (dot, name):
                self._explain(w, name.text(), details[key])
        self._explain(strip, "Getting started",
            "The three things that have to line up before a touch reaches a "
            "toy: a light for each, green when it's done. Click to see the "
            "steps again.")

        self._setup_card = card
        self._setup_strip = strip
        self._setup_state = None
        # The card opened from the folded line stays open this launch,
        # even with every step done (it would vanish under the click).
        self._setup_reopened = False
        parent_layout.addWidget(card)
        parent_layout.addWidget(strip)
        self._style_root(card)
        self._style_root(strip)
        self._refresh_setup_checklist()

    def _set_setup_compact(self, compact: bool) -> None:
        """"Don't show again" (True) / a click on the folded line (False)."""
        self.controller.set_app_setting(self._SETUP_COMPACT_KEY, bool(compact))
        self._setup_reopened = not compact
        self._setup_state = None        # show the change at once
        self._refresh_setup_checklist()

    def _refresh_setup_checklist(self) -> None:
        """Change-gated: rides the 2 Hz refresh, so an unchanged state
        costs one facade call, one setting read and a dict compare."""
        card = getattr(self, "_setup_card", None)
        if card is None:
            return
        try:
            state = dict(self.controller.get_setup_status())
            get = self.controller.get_app_setting
            state["built_in"] = bool(get("use_integrated_intiface", True))
            state["compact"] = bool(get(self._SETUP_COMPACT_KEY, False))
        except Exception:
            return
        if state == self._setup_state:
            return
        self._setup_state = state
        strip = getattr(self, "_setup_strip", None)
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
                if strip is not None:
                    dot, name = strip.lights[key]
                    self._apply_connect_dot(dot, ok)
                    name.setStyleSheet(
                        f"color: {COLOR_TEXT};" if ok
                        else f"color: {COLOR_TEXT_MUTED};")
        except RuntimeError:
            return
        done = all(bool(state.get(k)) for k, _t, _d in self._SETUP_STEPS)
        card.setVisible(not state["compact"]
                        and (not done or self._setup_reopened))
        if strip is not None:
            strip.setVisible(state["compact"])

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
