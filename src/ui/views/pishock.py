"""Shockers view — the USB hub (PiShock or OpenShock firmware), a card per
shocker with its own limits, and the behaviours that turn your avatar's
contacts into shocks. Laid out in Avatar Remote's card design (Blise's
ask, 2026-10-28):

  * Hub        — the link (port, Connect, connect when the app starts),
                 Arm shocks (remembered across launches) and Stop all;
  * Shockers   — a card per shocker: its name, what it is doing right
                 now, its own max shock / max vibrate / longest pulse and
                 Beep / Vibrate / Shock to test it; on OpenShock firmware
                 also its model and transmitter id (＋ Add shocker), since
                 that firmware keeps no list of its own. Beside them, the
                 timing every shocker shares (pishock_cards.py);
  * Behaviours — Touch zones, Contact, Continuous and Impact cards
                 (pishock_rules.py): drag a shocker card onto one and it
                 drives that shocker.

Mixin for ui_components.OscGoesPurrrUI, shown only while the shocker
feature (`feature_pishock`) is on (Settings → Features). Everything goes
through the controller's PiShock facade (Demeter rule); this file only
draws widgets and forwards primitive values.
"""

from typing import Any, Dict, List, Tuple

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFrame, QLabel, QPushButton, QStyle, QStyleOptionSpinBox, QVBoxLayout,
    QWidget,
)

from constants import *
from ui.layout_helpers import FlowLayout as _FlowLayout, clear_layout, vbox as _vbox, hbox as _hbox
from ui.views.pishock_cards import (
    SHOCK_HUE, SharedTimingCard, ShockerSetupCard, category_frame, mini_button, state_pill,
)
from ui.views.pishock_rules import PiShockRulesMixin
from ui.widgets import ToggleSwitch, Card as _Card

VIEW_NAME = "Shockers"


class PiShockMixin(PiShockRulesMixin):

    _is_updating_pishock = False
    _pishock_cards_key: tuple = ()

    # ----------------------------------------------------------
    # View
    # ----------------------------------------------------------

    def _build_pishock_view(self, parent_layout: QVBoxLayout):
        title = QLabel(VIEW_NAME)
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)
        parent_layout.addWidget(self._muted_label(
            "Your PiShock or OpenShock hub over its USB cable — no account, no "
            "internet, straight from your avatar's contacts to the shockers. Connect "
            "the hub, set each shocker's limits, then drag the shockers onto the "
            "behaviours below."))

        parent_layout.addWidget(self._build_pishock_hub_card())
        parent_layout.addWidget(self._build_pishock_shockers_frame())
        parent_layout.addWidget(self._build_pishock_behaviours_frame())
        parent_layout.addStretch(1)

        self._pishock_live_timer = QTimer()
        self._pishock_live_timer.setInterval(150)
        self._pishock_live_timer.timeout.connect(self._refresh_pishock_live)
        self._pishock_live_timer.start()

        self.refresh_pishock_status()

    @staticmethod
    def _pishock_fit(box) -> None:
        """Just wide enough for the box's widest value, suffix and arrows.
        The style says how much its padding, border and arrow column take
        (49 px under the Neon sheet — a guessed 36 cut "2.0 s" to "2.(");
        the edit inside adds a few pixels of margin and the cursor."""
        box.ensurePolished()
        opt = QStyleOptionSpinBox()
        box.initStyleOption(opt)
        opt.rect = QRect(0, 0, 200, 30)
        edit = box.style().subControlRect(
            QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxEditField, box)
        text = box.textFromValue(box.maximum()) + box.suffix()
        box.setFixedWidth(box.fontMetrics().horizontalAdvance(text)
                          + opt.rect.width() - edit.width() + 6)

    def _pishock_flow(self, groups) -> QWidget:
        """A row of control groups that wraps instead of widening the page
        (the Suits page builds its rows with it too). Each group (a widget,
        or a tuple of widgets / int spacings) stays on one line."""
        box = QWidget()
        flow = _FlowLayout(margin=0, h_spacing=14, v_spacing=6)
        box.setLayout(flow)
        for group in groups:
            if isinstance(group, QWidget):
                flow.addWidget(group)
                continue
            g = QWidget()
            gl = _hbox(0, 6)
            g.setLayout(gl)
            for part in group:
                if isinstance(part, int):
                    gl.addSpacing(part)
                else:
                    gl.addWidget(part)
            flow.addWidget(g)
        return box

    # ---- the hub -------------------------------------------------

    def _build_pishock_hub_card(self) -> QFrame:
        card = _Card()
        lay = _vbox(20, 8)
        card.setLayout(lay)
        hdr = QLabel("Hub")
        hdr.setObjectName("sectionTitle")
        self._pishock_pill = state_pill("Not connected", "off")
        self._explain(self._pishock_pill, "Link",
                      "Whether the app is talking to your hub over USB right now, which "
                      "firmware it runs (PiShock's own, or OpenShock) and its version.")
        self._pishock_port_combo = QComboBox()
        self._pishock_port_combo.setMinimumWidth(190)
        self._pishock_port_combo.currentIndexChanged.connect(self._on_pishock_port_picked)
        self._explain(self._pishock_port_combo, "Port",
                      "<b>Find automatically</b> looks for the hub by its USB chip and checks "
                      "it answers like a PiShock or OpenShock hub. Pick a COM port yourself "
                      "only if you have several hubs, or it isn't found.")
        rescan = QPushButton("↻")
        rescan.setFixedHeight(BTN_HEIGHT_SMALL)
        rescan.setProperty("role", "secondary")
        rescan.clicked.connect(self._fill_pishock_ports)
        self._explain(rescan, "Rescan ports",
                      "Look again for serial ports — after plugging the hub in.")
        self._pishock_connect_btn = QPushButton("Connect")
        self._pishock_connect_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._pishock_connect_btn.setProperty("role", "primary")
        self._pishock_connect_btn.clicked.connect(self._on_pishock_connect_clicked)
        self._explain(self._pishock_connect_btn, "Connect",
                      "Open the USB link to the hub. While it's wanted, the app reconnects "
                      "by itself if the cable comes out.")
        # two rows of groups that wrap in a narrow window
        lay.addWidget(self._pishock_flow([
            (hdr, self._pishock_pill),
            (self._pishock_port_combo, rescan, self._pishock_connect_btn)]))

        self._pishock_auto = ToggleSwitch("Connect when the app starts")
        self._pishock_auto.toggled.connect(
            lambda on: None if self._is_updating_pishock
            else self.controller.set_pishock_auto_connect(bool(on)))
        self._explain(self._pishock_auto, "Connect when the app starts",
                      "Off by default: a shocker never connects unless you ask.")
        self._pishock_arm = ToggleSwitch("Arm shocks")
        self._pishock_arm.toggled.connect(
            lambda on: None if self._is_updating_pishock
            else self.controller.set_pishock_armed(bool(on)))
        self._explain(self._pishock_arm, "Arm shocks",
                      "Until this is on, every shock — a behaviour's, a friend's, a test — "
                      "goes out as a vibrate instead. It stays as you leave it, across "
                      "restarts too.")
        self._pishock_armed_pill = state_pill("", "warn")
        self._pishock_stop_btn = QPushButton("Stop all")
        self._pishock_stop_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._pishock_stop_btn.setProperty("role", "danger")
        self._pishock_stop_btn.clicked.connect(self._on_pishock_stop_clicked)
        self._explain(self._pishock_stop_btn, "Stop all / Resume",
                      "Ends whatever every shocker is doing right now and keeps them quiet "
                      "until you press Resume - even after a restart. The same as the "
                      "Shockers switch on Home. The sidebar's Off silences the shockers "
                      "too, along with the toys.")
        # the switches centred on Stop all's height (a flow tops its line)
        self._pishock_stop_btn.ensurePolished()        # its styled height
        tall = self._pishock_stop_btn.sizeHint().height()
        lay.addWidget(self._pishock_flow([
            self._pishock_centred([self._pishock_auto], tall),
            self._pishock_centred([self._pishock_arm, self._pishock_armed_pill], tall),
            self._pishock_stop_btn]))

        self._pishock_info = self._muted_label("")
        lay.addWidget(self._pishock_info)
        self._fill_pishock_ports()
        return card

    @staticmethod
    def _pishock_centred(widgets, height: int) -> QWidget:
        box = QWidget()
        box.setMinimumHeight(height)
        row = _hbox(0, 6)
        box.setLayout(row)
        for w in widgets:
            row.addWidget(w, 0, Qt.AlignVCenter)
        return box

    def _fill_pishock_ports(self) -> None:
        combo = getattr(self, "_pishock_port_combo", None)
        if combo is None:
            return
        try:
            ports = self.controller.list_pishock_ports()
            wanted = self.controller.get_pishock_status().get("port_setting", "")
        except Exception:
            ports, wanted = [], ""
        self._is_updating_pishock = True
        try:
            combo.clear()
            combo.addItem("Find automatically", "")
            for p in ports:
                tag = " — hub?" if p.get("hub") else ""
                combo.addItem(f"{p['device']}  {p.get('description', '')}{tag}".strip(),
                              p["device"])
            if wanted and combo.findData(wanted) < 0:
                combo.addItem(f"{wanted}  (not plugged in)", wanted)
            idx = combo.findData(wanted)
            combo.setCurrentIndex(max(0, idx))
        finally:
            self._is_updating_pishock = False

    def _on_pishock_port_picked(self, _idx: int) -> None:
        if self._is_updating_pishock:
            return
        self.controller.set_pishock_port(self._pishock_port_combo.currentData() or "")

    def _on_pishock_connect_clicked(self) -> None:
        st = self.controller.get_pishock_status()
        if st.get("connected") or st.get("connecting"):
            self.controller.pishock_disconnect()
        else:
            self.controller.pishock_connect()
        self.refresh_pishock_status()

    def _on_pishock_stop_clicked(self) -> None:
        if self.controller.get_pishock_status().get("paused"):
            self.controller.pishock_resume()
        else:
            self.controller.pishock_stop_all()
        self.refresh_pishock_status()

    # ---- the shockers --------------------------------------------

    def _build_pishock_shockers_frame(self) -> QFrame:
        frame, root, self._pishock_cards_flow, head = category_frame(
            "SHOCKERS", SHOCK_HUE, icon="shock")
        self._pishock_add_btn = mini_button("＋ Add shocker")
        self._pishock_add_btn.clicked.connect(self._on_openshock_add)
        self._pishock_add_btn.hide()
        head.addWidget(self._pishock_add_btn)
        self._explain(self._pishock_add_btn, "Add shocker",
                      "OpenShock firmware keeps no shocker list of its own, so add each "
                      "shocker here: a new card with a fresh random ID. To pair a collar, "
                      "hold its power button until the light blinks fast, then press its "
                      "card's Beep - it learns that ID. A PiShock shocker counts as "
                      "CaiXianlin.")
        self._pishock_cards_hint = QLabel("")
        self._pishock_cards_hint.setObjectName("paramCatHint")
        self._pishock_cards_hint.setProperty("hue", SHOCK_HUE)
        self._pishock_cards_hint.setAlignment(Qt.AlignCenter)
        root.addWidget(self._pishock_cards_hint)
        self._pishock_cards: Dict[int, ShockerSetupCard] = {}
        self._pishock_shared_card = None
        return frame

    def _pishock_listed(self, st: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], bool]:
        """The shockers to show a card for, and whether they are the
        OpenShock list (kept here) rather than the hub's own."""
        openshock = st.get("openshock_shockers") or []
        if st.get("hub_kind") == "openshock" or (openshock and not st.get("connected")):
            return [dict(s) for s in openshock], True
        if st.get("connected"):
            # the page shows the switched-off ones too: it's where they come back
            return list(st.get("all_shockers") or st.get("shockers") or []), False
        return [], False

    def _rebuild_pishock_cards(self, st: Dict[str, Any]) -> None:
        listed, openshock = self._pishock_listed(st)
        clear_layout(self._pishock_cards_flow)
        self._pishock_cards = {}
        ranges = st.get("ranges") or {}
        models = self.controller.openshock_models() if openshock else ()
        own = st.get("shocker_limits") or {}
        hub = st.get("limits") or {}
        off = set(st.get("shockers_off") or [])
        for idx, s in enumerate(listed):
            sid = int(s["id"])
            limits = own.get(str(sid)) or {k: hub.get(k) for k in
                                           ("max_intensity", "max_vibrate", "max_pulse_ms")}
            card = ShockerSetupCard(
                dict(s, off=sid in off), limits, ranges,
                on_name=lambda text, i=idx, x=sid: self._pishock_named(i, x, text),
                on_limit=lambda key, v, x=sid: self.controller.set_pishock_shocker_limit(
                    x, key, v),
                on_test=lambda op, x=sid: self.controller.pishock_test(op, x),
                openshock=({"models": [(m, label) for m, label in models],
                            "model": s.get("model")} if openshock else None),
                on_use=lambda on, x=sid: self._pishock_use(x, on))
            if openshock:
                card.model.currentIndexChanged.connect(
                    lambda _v, i=idx: self._push_openshock(i))
                card.rf_id.valueChanged.connect(lambda _v, i=idx: self._push_openshock(i))
                card.delete.clicked.connect(lambda _=False, i=idx: self._on_openshock_delete(i))
            self._pishock_cards_flow.addWidget(card)
            self._pishock_cards[sid] = card
        self._pishock_shared_card = SharedTimingCard(
            hub, ranges, on_limit=lambda key, v: self.controller.set_pishock_limit(key, v))
        self._pishock_cards_flow.addWidget(self._pishock_shared_card)
        self._pishock_add_btn.setVisible(openshock or st.get("hub_kind") == "openshock")
        if listed:
            self._pishock_cards_hint.hide()
        else:
            self._pishock_cards_hint.setText(
                "Press ＋ Add shocker for each of your collars" if openshock
                or st.get("hub_kind") == "openshock"
                else "Connect the hub to see its shockers here")
            self._pishock_cards_hint.show()

    def _pishock_use(self, sid: int, on: bool) -> None:
        """A card's On / Off: greyed at once, then everything that reads the
        list (behaviours' chips, Home, friends) follows."""
        card = self._pishock_cards.get(sid)
        if card is not None:
            card.set_on(on)
        self.controller.set_pishock_shocker_on(sid, on)
        self.refresh_pishock_status()

    def _pishock_named(self, idx: int, sid: int, text: str) -> None:
        st = self.controller.get_pishock_status()
        if self._pishock_listed(st)[1]:
            self._push_openshock(idx)
        else:
            self.controller.set_pishock_shocker_name(sid, text)
        self.refresh_pishock_status()

    # ---- OpenShock's own list ----------------------------------------

    def _on_openshock_add(self) -> None:
        self.controller.add_openshock_shocker()
        self.refresh_pishock_status()

    def _on_openshock_delete(self, idx: int) -> None:
        self.controller.delete_openshock_shocker(idx)
        self.refresh_pishock_status()

    def _push_openshock(self, idx: int) -> None:
        if self._is_updating_pishock:
            return
        st = self.controller.get_pishock_status()
        listed, openshock = self._pishock_listed(st)
        if not openshock or not 0 <= idx < len(listed):
            return
        card = self._pishock_cards.get(int(listed[idx]["id"]))
        if card is None:
            return
        self.controller.set_openshock_shocker(idx, {
            "name": card.name.text().strip(),
            "model": card.model.currentData(),
            "id": card.rf_id.value(),
        })
        # an id another entry has is refused: the card snaps back to it
        self._pishock_cards_key = ()
        self.refresh_pishock_status()

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def refresh_pishock_status(self) -> None:
        """Controller facade: the link, shocker list, arming or pause
        changed (also called on arrival and after the page's own clicks)."""
        pill = getattr(self, "_pishock_pill", None)
        if pill is None:
            return
        try:
            st = self.controller.get_pishock_status()
        except Exception:
            return
        hub = st.get("hub_name") or ""
        if not st.get("available"):
            text, tone = "pyserial missing", "err"
        elif st.get("connected"):
            fw = ".".join((st.get("firmware") or "").split(".")[:3])
            text, tone = (f"CONNECTED · {st.get('port')} · {st.get('board') or hub}"
                          + (f" · fw {fw}" if fw else ""), "ok")
        elif st.get("connecting"):
            text, tone = "CONNECTING…", "run"
        else:
            text, tone = "NOT CONNECTED", "off"
        pill.setText(text)
        if pill.property("tone") != tone:
            pill.setProperty("tone", tone)
            self._repolish(pill)
        self._pishock_connect_btn.setText(
            "Disconnect" if st.get("connected") or st.get("connecting") else "Connect")
        self._pishock_info.setText(
            "" if st.get("connected") else
            (st.get("last_error") or "Plug the hub in by USB and press Connect."))
        self._pishock_info.setVisible(bool(self._pishock_info.text()))

        self._is_updating_pishock = True
        try:
            self._pishock_auto.setChecked(bool(st.get("auto_connect")))
            self._pishock_arm.setChecked(bool(st.get("armed")))
        finally:
            self._is_updating_pishock = False
        self._pishock_armed_pill.setText("ARMED · shocks are real")
        self._pishock_armed_pill.setVisible(bool(st.get("armed")))
        self._pishock_stop_btn.setText("Resume" if st.get("paused") else "Stop all")

        listed, openshock = self._pishock_listed(st)
        key = (openshock, bool(st.get("connected")), st.get("hub_kind"),
               tuple((s["id"], s.get("name") or "", s.get("model")) for s in listed))
        if key != self._pishock_cards_key:
            self._pishock_cards_key = key
            self._rebuild_pishock_cards(st)
        else:
            own = st.get("shocker_limits") or {}
            off = set(st.get("shockers_off") or [])
            for sid, card in self._pishock_cards.items():
                if str(sid) in own:
                    card.set_limits(own[str(sid)])
                card.set_on(sid not in off)
            if self._pishock_shared_card is not None:
                self._pishock_shared_card.set_limits(st.get("limits") or {})

        # what the behaviours' drop zones call the shockers
        choices = tuple((int(s["id"]), self._pishock_shocker_label(s)) for s in listed)
        off = frozenset(int(x) for x in st.get("shockers_off") or [])
        if choices != self._pishock_shocker_choices or off != self._pishock_shockers_off:
            self._pishock_shocker_choices = choices
            self._pishock_shockers_off = off
            self._rebuild_pishock_rules()
        self._refresh_pishock_live()

    @staticmethod
    def _pishock_shocker_label(s: Dict[str, Any]) -> str:
        return s.get("name") or f"Shocker {s['id']}"

    def _refresh_pishock_live(self) -> None:
        try:
            if (getattr(self, "main_stack", None) is not None
                    and self.main_stack.currentWidget() is not self.views.get(VIEW_NAME)):
                return
            live = self.controller.get_pishock_live()
            st = self.controller.get_pishock_status()
        except Exception:
            return
        outputs = live.get("outputs", {})
        paused_ids = {int(s["id"]) for s in st.get("all_shockers") or st.get("shockers") or []
                      if s.get("paused")}
        off = set(st.get("shockers_off") or [])
        for sid, card in getattr(self, "_pishock_cards", {}).items():
            o = outputs.get(sid)
            if sid in off:
                card.set_state("OFF", "idle")
            elif o and o.get("kind") == "rest":
                card.set_state("BREAK", "warn")
            elif o:
                # in the colour of what it does: a shock in the shockers' yellow
                card.set_state(f"{o['op'].upper()} {o['intensity']}",
                               {"shock": "shock", "vibrate": "live"}.get(o["op"], "info"))
            elif not st.get("connected"):
                card.set_state("OFFLINE", "idle")
            elif sid in paused_ids:
                card.set_state("PAUSED IN PISHOCK", "idle")
            elif st.get("paused"):
                card.set_state("STOPPED", "idle")
            else:
                card.set_state("READY", "ok")
        self._refresh_pishock_rules_live(live.get("values", {}))
