"""PSVR2 view — the PlayStation VR2 headset's rumble motor, driven by one
contact on your avatar through PSVR2Toolkit (github.com/BnuuySolutions/
PSVR2Toolkit, its experimental builds), which needs a jailbroken headset:
on a stock one the commands succeed and the motor never moves.

Ported from the full edition's page and restyled to this edition's cards
(Avatar Remote's design, like the Suits page's OWO frame): every value is a
slider with the number written out, never a spin box. Mixin for
ui_components.OscGoesPurrrUI, shown while `feature_psvr2` is on (Settings →
Features; Windows only). Top to bottom, in the headset's frame:

  * Link        — whether OGP is joined to the toolkit's driver (SteamVR
                  running with PSVR2Toolkit), Connect, Feel it, Stop /
                  Resume (Home's On / Off) and Connect whenever SteamVR runs;
  * Rumble      — the frequency band a touch maps onto (the headset has no
                  other knob), the command cap and the keepalive;
  * Contact     — the avatar's contact receiver that drives it, picked from
                  the live parameters, with threshold and gain, and whether
                  the worn avatar has it;
  * Tell VRChat — OGP/PSVR2Connected.

The source is a raw VRChat contact receiver picked from the live parameter
list (the shared ui/osc_variable_picker), not an OGB zone. Everything goes
through the controller's PSVR2 facade (Demeter rule); this file only draws
widgets and forwards primitive values.
"""

import threading
from typing import Any, Dict

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from constants import BTN_HEIGHT_SMALL
from ui.frame_clock import when_on_screen
from ui.layout_helpers import hbox as _hbox, vbox as _vbox
from ui.osc_variable_picker import open_osc_variable_picker
from ui.theme import PSVR2_HUE
from ui.views.antistuck_box import AntiStuckBox
from ui.views.param_cards import CARD_W
from ui.views.pishock_cards import ValueSlider, category_frame, mini_button, state_pill
from ui.widgets import ToggleSwitch
from utilities import strip_param_prefix

VIEW_NAME = "PSVR2"


def _hz(v: float) -> str:
    return f"{v:.0f} Hz"


def link_text(st: Dict[str, Any]):
    """(pill text, tone, the line under it) from get_psvr2_status(). Pure."""
    extras = st.get("extras") or {}
    if not st.get("available", True):
        return ("PSVR2Toolkit not found", "err",
                st.get("last_error") or "Install PSVR2Toolkit and run it once.")
    if st.get("connected"):
        parts = []
        hz = extras.get("rumble_hz")
        if hz:
            parts.append(f"Rumbling at {int(hz)} Hz")
        rtt = extras.get("rtt_ms")
        if rtt is not None:
            # the one number that tells a healthy (if silent, not jailbroken)
            # headset from a wedged driver
            parts.append(f"driver answers in ~{int(rtt)} ms, "
                         f"{int(extras.get('sends_per_min') or 0)} changes a minute")
        if extras.get("slotless"):
            parts.append("every toolkit slot is taken by other apps - the "
                         "rumble needs none")
        line = " · ".join(parts) or ("Connected. Silent on Feel it? The headset "
                                     "needs a jailbreak for its motor to move.")
        if st.get("paused"):
            return "Stopped", "warn", "Stopped: press Resume to feel it again."
        return "Connected", "ok", line
    if st.get("auto_connect"):
        return ("Waiting for SteamVR", "run",
                st.get("last_error") or "Start SteamVR with PSVR2Toolkit installed.")
    return ("Not connected", "off",
            st.get("last_error") or "Start SteamVR with PSVR2Toolkit, then press Connect.")


class PSVR2Mixin:

    _is_updating_psvr2 = False

    def _build_psvr2_view(self, parent_layout: QVBoxLayout):
        title = QLabel(VIEW_NAME)
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)
        parent_layout.addWidget(self._muted_label(
            "Your PlayStation VR2 headset's rumble motor, from a contact on your "
            "avatar, through PSVR2Toolkit. It needs a jailbroken headset: on a "
            "stock one the motor never moves."))

        self._psvr2_connecting = None        # the Connect thread while it runs
        frame, _root, flow, _head = category_frame("PlayStation VR2", PSVR2_HUE,
                                                   icon="psvr2")
        flow.addWidget(self._build_psvr2_link_card())
        flow.addWidget(self._build_psvr2_rumble_card())
        flow.addWidget(self._build_psvr2_contact_card())
        tell = self._build_psvr2_presence_card()
        if tell is not None:
            flow.addWidget(tell)
        parent_layout.addWidget(frame)
        parent_layout.addStretch(1)

        self._psvr2_status_timer = QTimer()
        self._psvr2_status_timer.setInterval(1000)
        self._psvr2_status_timer.timeout.connect(when_on_screen(self, self._psvr2_tick_status))
        self._psvr2_status_timer.start()
        self._psvr2_live_timer = QTimer()
        self._psvr2_live_timer.setInterval(150)
        self._psvr2_live_timer.timeout.connect(when_on_screen(self, self._refresh_psvr2_live))
        self._psvr2_live_timer.start()
        self.refresh_psvr2_status()

    # ---- cards ---------------------------------------------------------

    @staticmethod
    def _psvr2_card(title: str, min_w: int = CARD_W):
        """Avatar Remote's card in the headset's frame: a title, then rows."""
        from PySide6.QtWidgets import QFrame
        card = QFrame()
        card.setObjectName("paramCard")
        card.setProperty("hue", PSVR2_HUE)
        card.setMinimumWidth(min_w)
        lay = _vbox(0, 8)
        lay.setContentsMargins(12, 10, 10, 12)
        card.setLayout(lay)
        head = QLabel(title)
        head.setObjectName("paramLabel")
        lay.addWidget(head)
        return card, lay

    @staticmethod
    def _psvr2_wrap(text: str = "") -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("muted", "true")
        lbl.setWordWrap(True)
        return lbl

    def _build_psvr2_link_card(self):
        card, lay = self._psvr2_card("Link", 2 * CARD_W + 10)
        row = _hbox(0, 8)
        self._psvr2_pill = state_pill("Not connected", "off")
        row.addWidget(self._psvr2_pill)
        self._explain(self._psvr2_pill, "Link",
                      "Whether OGP is talking to the headset through "
                      "PSVR2Toolkit's driver. That needs SteamVR running with "
                      "PSVR2Toolkit installed - one of its experimental builds, "
                      "run once so OGP can find it.")
        row.addStretch(1)
        self._psvr2_connect_btn = mini_button("Connect", role="primary")
        self._psvr2_connect_btn.clicked.connect(self._on_psvr2_connect)
        row.addWidget(self._psvr2_connect_btn)
        self._explain(self._psvr2_connect_btn, "Connect",
                      "Join PSVR2Toolkit's driver now, instead of waiting for "
                      "the next try.")
        self._psvr2_test_btn = mini_button("Feel it")
        self._psvr2_test_btn.clicked.connect(self._on_psvr2_test)
        row.addWidget(self._psvr2_test_btn)
        self._explain(self._psvr2_test_btn, "Feel it",
                      "A short rumble at the top of the band. The quickest way "
                      "to tell a working jailbreak from a silent one: on a "
                      "stock headset the command goes through and nothing "
                      "moves.")
        self._psvr2_stop_btn = mini_button("Stop", role="danger")
        self._psvr2_stop_btn.clicked.connect(self._on_psvr2_stop)
        row.addWidget(self._psvr2_stop_btn)
        self._explain(self._psvr2_stop_btn, "Stop / Resume",
                      "Stops the headset's motor now and keeps it still until "
                      "you press Resume - even after a restart. The same as the "
                      "PSVR2 switch on Home. The sidebar's Off stops it too.")
        lay.addLayout(row)
        self._psvr2_info = self._psvr2_wrap()
        lay.addWidget(self._psvr2_info)
        self._psvr2_auto = ToggleSwitch("Connect whenever SteamVR runs")
        self._psvr2_auto.toggled.connect(
            lambda on: None if self._is_updating_psvr2
            else self.controller.set_psvr2_auto_connect(bool(on)))
        lay.addWidget(self._psvr2_auto)
        self._explain(self._psvr2_auto, "Connect whenever SteamVR runs",
                      "On: OGP joins the headset by itself whenever SteamVR runs "
                      "with PSVR2Toolkit. Off: only when you press Connect.")
        return card

    def _build_psvr2_rumble_card(self):
        card, lay = self._psvr2_card("Rumble")
        set_out = self.controller.set_psvr2_output

        def out(key):
            def send(v):
                set_out({key: float(v)})
                self.refresh_psvr2_status()   # an inverted band comes back ordered
            return send
        self._psvr2_min = ValueSlider("Lowest", 1, 25, 10, 1, _hz, hue=PSVR2_HUE,
                                      on_change=out("min_hz"))
        lay.addWidget(self._psvr2_min)
        self._explain(self._psvr2_min, "Lowest",
                      "The rumble at the lightest touch. The headset has one knob, "
                      "how fast it rumbles - no separate strength - so a light "
                      "touch is a slow thump and a full one a fast buzz. It "
                      "really does 10-25 Hz: lower settings feel like 10.")
        self._psvr2_max = ValueSlider("Highest", 1, 25, 25, 1, _hz, hue=PSVR2_HUE,
                                      on_change=out("max_hz"))
        lay.addWidget(self._psvr2_max)
        self._explain(self._psvr2_max, "Highest",
                      "The rumble at a full touch, and Feel it's. Nothing goes "
                      "faster than this.")
        self._psvr2_rate = ValueSlider("Changes per second", 1, 30, 10, 1,
                                       lambda v: f"{v:.0f} /s", hue=PSVR2_HUE,
                                       on_change=out("max_cmd_hz"))
        lay.addWidget(self._psvr2_rate)
        self._explain(self._psvr2_rate, "Changes per second",
                      "How often the rumble may change. Each change is a USB "
                      "command the headset must answer, and PSVR2Toolkit's "
                      "command queue is shared with every other app using it, "
                      "so this protects the headset rather than being a taste.")
        self._psvr2_keep = ValueSlider("Keepalive", 0, 10, 0, 0.5,
                                       lambda v: "off" if v <= 0 else f"{v:g} s",
                                       hue=PSVR2_HUE, on_change=out("keepalive_s"))
        lay.addWidget(self._psvr2_keep)
        self._explain(self._psvr2_keep, "Keepalive",
                      "Sends a held rumble again on a timer. Leave it off: the "
                      "headset keeps a rumble until told otherwise. Only raise it "
                      "if a held touch fades out by itself.")
        return card

    def _build_psvr2_contact_card(self):
        card, lay = self._psvr2_card("Contact")
        self._psvr2_on = ToggleSwitch("On")
        self._psvr2_on.toggled.connect(
            lambda on: None if self._is_updating_psvr2
            else self.controller.set_psvr2_contact({"enabled": bool(on)}))
        lay.addWidget(self._psvr2_on)
        self._explain(self._psvr2_on, "On",
                      "Whether the contact below drives the headset. Off: only "
                      "Feel it rumbles it.")
        self._psvr2_check = state_pill("", "idle")
        self._psvr2_check.hide()
        lay.addWidget(self._psvr2_check, 0, Qt.AlignLeft)
        prow = QWidget()
        pl = _hbox(0, 6)
        prow.setLayout(pl)
        self._psvr2_param = QLineEdit()
        self._psvr2_param.setPlaceholderText("e.g. HapticHead")
        # editingFinished, not textChanged: a half-typed name isn't saved
        self._psvr2_param.editingFinished.connect(self._on_psvr2_param_edited)
        pl.addWidget(self._psvr2_param, 1)
        pick = QPushButton("Pick…")
        pick.setFixedHeight(BTN_HEIGHT_SMALL)
        pick.setProperty("role", "secondary")
        pick.clicked.connect(self._pick_psvr2_parameter)
        pl.addWidget(pick)
        lay.addWidget(prow)
        self._explain(prow, "Contact",
                      "The contact receiver on your avatar that makes the headset "
                      "rumble. Pick… lists what your avatar sends right now, with "
                      "live values - touch the spot and watch which one moves - "
                      "or type a name. A Haptic Pancake avatar has HapticHead.")
        self._psvr2_threshold = ValueSlider(
            "Threshold", 0, 1, 0, 0.05, lambda v: f"{v:.2f}", hue=PSVR2_HUE,
            on_change=lambda v: self.controller.set_psvr2_contact({"threshold": float(v)}))
        lay.addWidget(self._psvr2_threshold)
        self._explain(self._psvr2_threshold, "Threshold",
                      "Below this the contact does nothing. Use it to ignore the "
                      "far edge of the receiver's reach.")
        self._psvr2_gain = ValueSlider(
            "Gain", 0, 5, 1, 0.1, lambda v: f"× {v:.1f}", hue=PSVR2_HUE,
            on_change=lambda v: self.controller.set_psvr2_contact({"gain": float(v)}))
        lay.addWidget(self._psvr2_gain)
        self._explain(self._psvr2_gain, "Gain",
                      "How fast the rumble climbs through the band once past the "
                      "threshold: (value - threshold) × gain.")
        self._psvr2_live = QLabel("")
        self._psvr2_live.setObjectName("cardValue")
        lay.addWidget(self._psvr2_live)
        self._explain(self._psvr2_live, "Right now",
                      "What the contact reads and the rumble it asks for, live. "
                      "Its anti-stuck cuts a contact that freezes, Off and the "
                      "sidebar's strength hold it back.")
        # the headset's own anti-stuck (antistuck.py)
        self._psvr2_antistuck = None
        # (filled from get_psvr2_status in refresh_psvr2_status)
        self._psvr2_antistuck = AntiStuckBox(
            "PSVR2 anti-stuck", "the headset rumbling", get=None,
            set_=lambda **ch: self.controller.set_psvr2_antistuck(**ch),
            explain=self._explain, hue=PSVR2_HUE, stacked=True)
        lay.addWidget(self._psvr2_antistuck)
        return card

    def _build_psvr2_presence_card(self):
        getter = getattr(self.controller, "get_device_connected_param", None)
        if not callable(getter):
            return None
        card, lay = self._psvr2_card("Tell VRChat", 2 * CARD_W + 10)
        lay.addWidget(self._psvr2_wrap(
            "A Bool on your avatar that is true while the headset is connected."))
        tip = ("Sends a Bool avatar parameter that is <b>true while OGP is "
               "connected to the headset through PSVR2Toolkit</b> and false while "
               "it isn't - so your avatar can show that its rumble is live.<br><br>"
               "It is on by default under this name, so an avatar asset made for "
               "OGP can use it. Add a Bool with the name to your avatar's "
               "parameters; the name is yours to change, or <b>Pick…</b> one "
               "your avatar already sends. It is sent again whenever you change "
               "avatar, and goes false when you close the app.")
        enabled, name = getter("psvr2")
        lay.addWidget(self._build_connected_param_row(
            "PSVR2 headset", enabled, name,
            lambda on, n: self.controller.set_device_connected_param("psvr2", on, n),
            "Tell VRChat while the headset is connected", tip, label_width=118))
        self._explain(card, "Tell VRChat while the headset is connected", tip)
        return card

    # ---- refresh -------------------------------------------------------

    def _psvr2_page_shown(self) -> bool:
        view = getattr(self, "views", {}).get(VIEW_NAME)
        return view is None or view.isVisible()

    def _psvr2_tick_status(self) -> None:
        if self._psvr2_page_shown():
            self.refresh_psvr2_status()

    def refresh_psvr2_status(self) -> None:
        if getattr(self, "_psvr2_pill", None) is None:
            return
        get = getattr(self.controller, "get_psvr2_status", None)
        if not callable(get):
            return
        st = get()
        if not st:
            return
        text, tone, line = link_text(st)
        connecting = self._psvr2_connecting is not None and self._psvr2_connecting.is_alive()
        if connecting:
            text, tone = "Connecting…", "run"
        self._psvr2_pill.setText(text)
        self._psvr2_pill.setProperty("tone", tone)
        self._repolish(self._psvr2_pill)
        self._psvr2_info.setText(line)
        self._psvr2_info.setVisible(bool(line))
        connected = bool(st.get("connected"))
        self._psvr2_connect_btn.setVisible(not connected and bool(st.get("available", True)))
        self._psvr2_connect_btn.setEnabled(not connecting)
        self._psvr2_test_btn.setEnabled(connected and not st.get("paused"))
        self._psvr2_stop_btn.setText("Resume" if st.get("paused") else "Stop")
        out = st.get("output") or {}
        c = st.get("contact") or {}
        if getattr(self, "_psvr2_antistuck", None) is not None and st.get("antistuck"):
            self._psvr2_antistuck.refresh(st["antistuck"])
        self._is_updating_psvr2 = True
        try:
            self._psvr2_auto.setChecked(bool(st.get("auto_connect")))
            self._psvr2_min.set_value(float(out.get("min_hz", 10.0)))
            self._psvr2_max.set_value(float(out.get("max_hz", 25.0)))
            self._psvr2_rate.set_value(float(out.get("max_cmd_hz", 10.0)))
            self._psvr2_keep.set_value(float(out.get("keepalive_s", 0.0)))
            self._psvr2_on.setChecked(bool(c.get("enabled")))
            if not self._psvr2_param.hasFocus():
                self._psvr2_param.setText(str(c.get("parameter", "")))
            self._psvr2_threshold.set_value(float(c.get("threshold", 0.0)))
            self._psvr2_gain.set_value(float(c.get("gain", 1.0)))
        finally:
            self._is_updating_psvr2 = False
        for w in (self._psvr2_threshold, self._psvr2_gain):
            w.setEnabled(bool(c.get("enabled")))
        found = None
        check = getattr(self.controller, "get_psvr2_contact_found", None)
        if callable(check):
            found = check()
        if found is None:
            self._psvr2_check.hide()
        else:
            self._psvr2_check.setText("On your avatar" if found else "Not on your avatar")
            self._psvr2_check.setProperty("tone", "ok" if found else "err")
            self._repolish(self._psvr2_check)
            self._psvr2_check.show()

    def _refresh_psvr2_live(self) -> None:
        if getattr(self, "_psvr2_live", None) is None or not self._psvr2_page_shown():
            return
        get = getattr(self.controller, "get_psvr2_live", None)
        if not callable(get):
            return
        live = get() or {}
        hz = live.get("rumble_hz")
        self._psvr2_live.setText(
            f"Contact {float(live.get('strength') or 0.0):.2f}  ·  "
            + (f"{int(hz)} Hz" if hz else "motor still"))

    # ---- handlers ------------------------------------------------------

    def _on_psvr2_connect(self) -> None:
        """Off the Qt thread: init() reaches into shared memory and can wait
        on the toolkit's mutexes."""
        if self._psvr2_connecting is not None and self._psvr2_connecting.is_alive():
            return
        t = threading.Thread(target=self.controller.psvr2_connect_now,
                             daemon=True, name="PSVR2Connect")
        self._psvr2_connecting = t
        t.start()
        self.refresh_psvr2_status()

    def _on_psvr2_test(self) -> None:
        self.controller.psvr2_test_pulse()

    def _on_psvr2_stop(self) -> None:
        if self.controller.get_psvr2_status().get("paused"):
            self.controller.psvr2_resume()
        else:
            self.controller.psvr2_stop_all()
        self.refresh_psvr2_status()

    def _on_psvr2_param_edited(self) -> None:
        if self._is_updating_psvr2:
            return
        bare = strip_param_prefix(self._psvr2_param.text().strip())
        self.controller.set_psvr2_contact({"parameter": bare})
        self.refresh_psvr2_status()

    def _pick_psvr2_parameter(self) -> None:
        """The shared live-parameter picker. Wildcards are off: the router
        looks the name up exactly, so a pattern would never match."""
        def on_pick(addr):
            bare = strip_param_prefix(addr)
            if not bare:
                return
            self.controller.set_psvr2_contact({"parameter": bare, "enabled": True})
            self.refresh_psvr2_status()

        open_osc_variable_picker(
            (getattr(self, "dialog_parent", None) or self.window), on_pick,
            allow_wildcards=False, title="Pick the headset's contact",
            subtitle="Pick the contact receiver that should rumble the headset "
                     "(double-click to choose) or type one. Values update live - "
                     "touch the spot to find it.")
