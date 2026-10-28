"""Shockers view, the behaviours: what your avatar's contacts do -- Touch
zones (several contacts, each with its own shockers), Contact, Continuous
and Impact -- a card each in the Behaviours frame, saved as you edit them.
A behaviour drives the shockers dropped on it: drag a shocker card's ⠿
onto it (onto one zone, for Touch zones), or pick from its ＋. Part of
PiShockMixin (pishock.py)."""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QWidget

from settings.pishock import MAX_TIERS, MAX_ZONES, RULE_KINDS
from utilities import strip_param_prefix
from ui.layout_helpers import clear_layout, hbox as _hbox, vbox as _vbox
from ui.osc_variable_picker import open_osc_variable_picker
from ui.views.card_parts import segmented
from ui.views.param_cards import CARD_W
from ui.views.pishock_cards import (
    MIME_SHOCKER, SHOCK_HUE, ShockerDropZone, ValueSlider, category_frame, fmt_seconds,
    mini_button, name_edit, state_pill,
)
from ui.widgets import ToggleSwitch

BEHAVIOUR_HUE = "cyan"
BEHAVIOUR_W = 2 * CARD_W + 10        # two shocker cards wide
_OPS = (("Vibrate", "vibrate"), ("Shock", "shock"), ("Beep", "beep"))
_MODES = (("Pulse once", "pulse"), ("While touching", "hold"))

# kind: (pill, add button, what it does)
KINDS = {
    "zones": ("TOUCH ZONES", "Touch zones",
              "Several contacts, each driving its own shockers - the neck the collar, a "
              "thigh its shocker. Drop a shocker onto each contact's row."),
    "triggers": ("CONTACT", "Contact",
                 "One on/off contact at a fixed strength: a pulse each time it is "
                 "touched, or for as long as it is touched."),
    "continuous": ("CONTINUOUS", "Continuous",
                   "A value from your avatar - usually a proximity contact - runs the "
                   "shockers while it is above a threshold. The closer, the stronger."),
    "impacts": ("IMPACT", "Impact",
                "Several OnEnter contacts on one spot, each with a different Min "
                "Velocity on the avatar: the hardest hit that fired picks the strength."),
}


class _BehaviourCard(QFrame):
    """A behaviour's card. A shocker dropped anywhere on it goes into its
    drop zone (Touch zones: onto one zone's row only)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("paramCard")
        self.setProperty("hue", BEHAVIOUR_HUE)
        self.setMinimumWidth(BEHAVIOUR_W)       # two columns of the frame
        self.zone: Optional[ShockerDropZone] = None

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self.zone is not None and event.mimeData().hasFormat(MIME_SHOCKER):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        if self.zone is not None:
            self.zone.dropEvent(event)


class PiShockRulesMixin:

    # ((id, label), ...) the drop zones name the shockers by
    _pishock_shocker_choices: tuple = ()

    def _build_pishock_behaviours_frame(self) -> QFrame:
        frame, root, self._pishock_rule_flow, head = category_frame(
            "BEHAVIOURS", BEHAVIOUR_HUE)
        add = mini_button("＋ Add behaviour")
        head.addWidget(add)
        self._explain(add, "Add behaviour", "Touch zones, Contact, Continuous or Impact.")
        intro = self._muted_label(
            "What your avatar's contacts do. Drag a shocker card's ⠿ onto a behaviour "
            "(or press its ＋) to pick the shockers it drives; × takes one off. A new "
            "behaviour drives none until you do.")
        root.insertWidget(1, intro)
        # what ＋ Add behaviour opens: one button per kind, in the page
        self._pishock_add_row = QWidget()
        row = _hbox(0, 8)
        self._pishock_add_row.setLayout(row)
        for kind in RULE_KINDS:
            _pill, label, blurb = KINDS[kind]
            b = mini_button(f"＋ {label}", blurb)
            b.clicked.connect(lambda _=False, k=kind: self._on_pishock_add(k))
            row.addWidget(b)
        row.addStretch(1)
        self._pishock_add_row.hide()
        root.insertWidget(2, self._pishock_add_row)
        add.clicked.connect(lambda _=False: self._pishock_add_row.setVisible(
            not self._pishock_add_row.isVisible()))
        self._pishock_rules_hint = QLabel("No behaviours yet - ＋ Add behaviour")
        self._pishock_rules_hint.setObjectName("paramCatHint")
        self._pishock_rules_hint.setProperty("hue", BEHAVIOUR_HUE)
        self._pishock_rules_hint.setAlignment(Qt.AlignCenter)
        root.addWidget(self._pishock_rules_hint)
        self._pishock_behaviours: List[Dict[str, Any]] = []
        self._rebuild_pishock_rules()
        return frame

    def _rebuild_pishock_rules(self, kinds=None) -> None:
        flow = getattr(self, "_pishock_rule_flow", None)
        if flow is None:
            return
        self._is_updating_pishock = True
        try:
            clear_layout(flow)
            self._pishock_behaviours = []
            for kind in RULE_KINDS:
                try:
                    rules = self.controller.get_pishock_rules(kind)
                except Exception:
                    rules = []   # the shocker engine failed to start: an empty page, not a dead window
                for idx, rule in enumerate(rules):
                    card, w = self._build_pishock_behaviour(kind, idx, rule)
                    flow.addWidget(card)
                    self._pishock_behaviours.append(w)
            self._pishock_rules_hint.setVisible(not self._pishock_behaviours)
        finally:
            self._is_updating_pishock = False

    def _on_pishock_add(self, kind: str) -> None:
        self.controller.add_pishock_rule(kind)
        self._pishock_add_row.hide()
        self._rebuild_pishock_rules()

    def _on_pishock_delete(self, kind: str, idx: int) -> None:
        self.controller.delete_pishock_rule(kind, idx)
        self._rebuild_pishock_rules()

    # ---- one behaviour -----------------------------------------------

    def _build_pishock_behaviour(self, kind: str, idx: int, rule: Dict[str, Any]):
        card = _BehaviourCard()
        lay = _vbox(0, 6)
        lay.setContentsMargins(10, 8, 8, 10)
        card.setLayout(lay)
        w: Dict[str, Any] = {"kind": kind, "idx": idx, "card": card,
                             "shockers": rule.get("shockers", []),
                             "push": lambda: self._push_pishock_rule(kind, idx)}

        top = _hbox(0, 6)
        w["name"] = name_edit(rule.get("name", ""), KINDS[kind][1],
                              lambda _t: w["push"]())
        top.addWidget(w["name"], 1)
        w["live"] = QLabel("")
        w["live"].setProperty("muted", "true")
        top.addWidget(w["live"])
        self._explain(w["live"], "Live", "What this behaviour sees from your avatar right now.")
        top.addWidget(state_pill(KINDS[kind][0], "info"))
        w["enabled"] = ToggleSwitch("")
        w["enabled"].setChecked(bool(rule.get("enabled", True)))
        w["enabled"].toggled.connect(lambda _v: w["push"]())
        top.addWidget(w["enabled"])
        self._explain(w["enabled"], "On / off",
                      "Off stops this behaviour without losing its settings.")
        delete = QPushButton("×")
        delete.setProperty("role", "chipClose")
        delete.setToolTip("Delete this behaviour")
        delete.clicked.connect(lambda _=False: self._on_pishock_delete(kind, idx))
        top.addWidget(delete)
        lay.addLayout(top)
        card.setToolTip(KINDS[kind][2])

        if kind in ("triggers", "continuous"):
            w["param"] = self._pishock_param(lay, rule.get("param", ""), w,
                                             "Avatar parameter, e.g. Contact/Headpat")
        line = _hbox(0, 8)
        seg, w["op"] = segmented([t for t, _ in _OPS], SHOCK_HUE,
                                 lambda _i: w["push"]())
        w["op"].button([o for _, o in _OPS].index(rule.get("op", "vibrate"))).setChecked(True)
        self._explain(seg, "What it does",
                      "Vibrate, Shock or Beep. Shock goes out as a vibrate until shocks are "
                      "armed.")
        line.addWidget(seg)
        if kind in ("triggers", "zones"):
            mseg, w["mode"] = segmented([t for t, _ in _MODES], BEHAVIOUR_HUE,
                                        lambda _i: (self._pishock_mode_shown(w), w["push"]()))
            w["mode"].button([m for _, m in _MODES].index(rule.get("mode", "pulse"))
                             ).setChecked(True)
            self._explain(mseg, "Pulse once / While touching",
                          "<b>Pulse once</b>: one pulse of the set length each time the "
                          "contact turns on. <b>While touching</b>: runs for as long as it "
                          "stays on (up to the longest hold).")
            line.addWidget(mseg)
        line.addStretch(1)
        lay.addLayout(line)

        def slider(key, *args, **kw):
            s = ValueSlider(*args, on_change=lambda _v: w["push"](), **kw)
            w[key] = s
            lay.addWidget(s)
            return s

        strength = lambda v: f"{v:.0f}"          # noqa: E731
        if kind in ("triggers", "zones"):
            slider("intensity", "Strength", 1, 100, rule.get("intensity", 20), fmt=strength,
                   tip="Always this strength, 1-100 - never above a shocker's own max.")
            slider("duration_ms", "Length", 100, 15000, rule.get("duration_ms", 500), 100,
                   fmt=lambda v: fmt_seconds(v / 1000),
                   tip="How long one pulse lasts (Pulse once) - never past a shocker's "
                       "longest pulse.")
            self._pishock_mode_shown(w)
        elif kind == "continuous":
            slider("threshold", "Starts above", 0.0, 0.99, rule.get("threshold", 0.0), 0.01,
                   fmt=lambda v: f"{v:.2f}", hue=BEHAVIOUR_HUE,
                   tip="It runs while the value is above this. 0 = any contact at all.")
            slider("min_int", "Strength just past it", 1, 100, rule.get("min_int", 5),
                   fmt=strength)
            slider("max_int", "Strength at 1", 1, 100, rule.get("max_int", 30), fmt=strength,
                   tip="In between, the strength follows the value.")
        else:
            slider("duration_ms", "Length", 100, 15000, rule.get("duration_ms", 500), 100,
                   fmt=lambda v: fmt_seconds(v / 1000), tip="How long the pulse lasts.")
            self._pishock_tiers(lay, rule, w)

        if kind == "zones":
            self._pishock_zones(lay, rule, w)
        else:
            zone = ShockerDropZone(rule.get("shockers", []), self._pishock_shocker_choices,
                                   lambda t: (w.__setitem__("shockers", t), w["push"]()))
            card.zone = zone
            lay.addWidget(zone)
        return card, w

    def _pishock_mode_shown(self, w: Dict[str, Any]) -> None:
        if "duration_ms" in w and "mode" in w:
            w["duration_ms"].setVisible(w["mode"].checkedId() == 0)

    def _pishock_param(self, lay, value: str, w, placeholder: str) -> QLineEdit:
        row = _hbox(0, 6)
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(lambda: w["push"]())
        row.addWidget(edit, 1)
        pick = mini_button("Pick", "Choose from the parameters your avatar is sending now")
        pick.clicked.connect(lambda _=False: self._pick_pishock_param(edit, w))
        row.addWidget(pick)
        lay.addLayout(row)
        self._explain(edit, "Parameter",
                      "The avatar parameter it listens to - the contact receiver's "
                      "parameter name.")
        return edit

    def _pick_pishock_param(self, edit: QLineEdit, w) -> None:
        def on_pick(addr):
            cleaned = strip_param_prefix(addr)
            if cleaned:
                edit.setText(cleaned)
                w["push"]()
        open_osc_variable_picker(
            (getattr(self, "dialog_parent", None) or self.window), on_pick, allow_wildcards=False,
            subtitle="Pick the contact receiver's parameter (double-click) or "
                     "enter one manually.")

    def _pishock_tiers(self, lay, rule, w) -> None:
        w["tiers"] = []
        for t_idx, tier in enumerate(rule.get("tiers") or []):
            row = _hbox(0, 6)
            tag = QLabel(f"Tier {t_idx + 1}")
            tag.setProperty("muted", "true")
            row.addWidget(tag)
            edit = QLineEdit(tier.get("param", ""))
            edit.setPlaceholderText("OnEnter receiver parameter")
            edit.editingFinished.connect(lambda: w["push"]())
            row.addWidget(edit, 1)
            pick = mini_button("Pick")
            pick.clicked.connect(lambda _=False, e=edit: self._pick_pishock_param(e, w))
            row.addWidget(pick)
            strength = ValueSlider("Strength", 1, 100, tier.get("intensity", 20),
                                   fmt=lambda v: f"{v:.0f}", on_change=lambda _v: w["push"]())
            strength.setFixedWidth(130)
            row.addWidget(strength)
            remove = QPushButton("×")
            remove.setProperty("role", "chipClose")
            remove.setToolTip("Take this tier out")
            remove.clicked.connect(lambda _=False, i=t_idx: self._pishock_tier_remove(w, i))
            row.addWidget(remove)
            lay.addLayout(row)
            self._explain(edit, f"Tier {t_idx + 1}",
                          "An OnEnter contact receiver. Give each tier's receiver a different "
                          "Min Velocity on the avatar - the harder the hit, the more tiers "
                          "fire, and the strongest one that fired sets the strength.")
            w["tiers"].append({"param": edit, "intensity": strength})
        if len(w["tiers"]) < MAX_TIERS:
            add = mini_button("＋ Add tier", "One more velocity step (up to 8)")
            add.clicked.connect(lambda _=False: self._pishock_tier_add(w))
            lay.addWidget(add)

    def _pishock_tier_add(self, w) -> None:
        rule = self._gather_pishock_behaviour(w)
        last = rule["tiers"][-1]["intensity"] if rule["tiers"] else 10
        rule["tiers"].append({"param": "", "intensity": min(100, last + 15)})
        self.controller.set_pishock_rule(w["kind"], w["idx"], rule)
        self._rebuild_pishock_rules()

    def _pishock_tier_remove(self, w, t_idx: int) -> None:
        rule = self._gather_pishock_behaviour(w)
        if 0 <= t_idx < len(rule["tiers"]):
            rule["tiers"].pop(t_idx)
            self.controller.set_pishock_rule(w["kind"], w["idx"], rule)
            self._rebuild_pishock_rules()

    def _pishock_zones(self, lay, rule, w) -> None:
        """Touch zones: a row per contact, and the shockers it drives."""
        w["zones"] = []
        for z_idx, zone in enumerate(rule.get("zones") or []):
            row = _hbox(0, 6)
            edit = QLineEdit(zone.get("param", ""))
            edit.setPlaceholderText("Contact parameter")
            edit.setFixedWidth(150)
            edit.editingFinished.connect(lambda: w["push"]())
            row.addWidget(edit)
            pick = mini_button("Pick")
            pick.clicked.connect(lambda _=False, e=edit: self._pick_pishock_param(e, w))
            row.addWidget(pick)
            entry = {"param": edit, "shockers": zone.get("shockers", [])}
            drop = ShockerDropZone(entry["shockers"], self._pishock_shocker_choices,
                                   lambda t, e=entry: (e.__setitem__("shockers", t), w["push"]()))
            row.addWidget(drop, 1)
            remove = QPushButton("×")
            remove.setProperty("role", "chipClose")
            remove.setToolTip("Take this contact out")
            remove.clicked.connect(lambda _=False, i=z_idx: self._pishock_zone_remove(w, i))
            row.addWidget(remove)
            lay.addLayout(row)
            self._explain(edit, "Contact",
                          "An on/off contact receiver on your avatar. When it is touched, "
                          "the shockers on its row go.")
            w["zones"].append(entry)
        if len(w["zones"]) < MAX_ZONES:
            add = mini_button("＋ Add a contact")
            add.clicked.connect(lambda _=False: self._pishock_zone_add(w))
            lay.addWidget(add)

    def _pishock_zone_add(self, w) -> None:
        rule = self._gather_pishock_behaviour(w)
        rule["zones"].append({"param": "", "shockers": []})
        self.controller.set_pishock_rule(w["kind"], w["idx"], rule)
        self._rebuild_pishock_rules()

    def _pishock_zone_remove(self, w, z_idx: int) -> None:
        rule = self._gather_pishock_behaviour(w)
        if 0 <= z_idx < len(rule["zones"]):
            rule["zones"].pop(z_idx)
            self.controller.set_pishock_rule(w["kind"], w["idx"], rule)
            self._rebuild_pishock_rules()

    # ---- saving ------------------------------------------------------

    def _gather_pishock_behaviour(self, w: Dict[str, Any]) -> Dict[str, Any]:
        kind = w["kind"]
        rule: Dict[str, Any] = {
            "enabled": w["enabled"].isChecked(),
            "name": w["name"].text().strip(),
            "op": _OPS[max(0, w["op"].checkedId())][1],
        }
        if kind != "zones":
            rule["shockers"] = w["shockers"]
        if kind in ("triggers", "zones"):
            rule.update(mode=_MODES[max(0, w["mode"].checkedId())][1],
                        intensity=round(w["intensity"].value()),
                        duration_ms=round(w["duration_ms"].value()))
        if kind == "triggers":
            rule["param"] = w["param"].text().strip()
        elif kind == "continuous":
            rule.update(param=w["param"].text().strip(), threshold=w["threshold"].value(),
                        min_int=round(w["min_int"].value()),
                        max_int=round(w["max_int"].value()))
        elif kind == "impacts":
            rule.update(duration_ms=round(w["duration_ms"].value()),
                        tiers=[{"param": t["param"].text().strip(),
                                "intensity": round(t["intensity"].value())}
                               for t in w["tiers"]])
        elif kind == "zones":
            rule["zones"] = [{"param": z["param"].text().strip(), "shockers": z["shockers"]}
                             for z in w["zones"]]
        return rule

    def _push_pishock_rule(self, kind: str, idx: int) -> None:
        if self._is_updating_pishock:
            return
        w = next((b for b in getattr(self, "_pishock_behaviours", [])
                  if b["kind"] == kind and b["idx"] == idx), None)
        if w is not None:
            self.controller.set_pishock_rule(kind, idx, self._gather_pishock_behaviour(w))

    # ---- live --------------------------------------------------------

    def _refresh_pishock_rules_live(self, values: Dict[str, float]) -> None:
        def seen(param: str) -> Optional[float]:
            return values.get(strip_param_prefix(param)) if param else None

        for w in getattr(self, "_pishock_behaviours", []):
            kind = w["kind"]
            if kind == "continuous":
                v = seen(w["param"].text().strip())
                text = "—" if v is None else f"{v:.2f}"
            elif kind == "triggers":
                v = seen(w["param"].text().strip())
                text = "—" if v is None else ("touching" if v > 0 else "off")
            elif kind == "zones":
                on = [z["param"].text().strip() for z in w["zones"]
                      if (seen(z["param"].text().strip()) or 0) > 0]
                heard = sum(1 for z in w["zones"] if seen(z["param"].text().strip()) is not None)
                text = (", ".join(p.split("/")[-1] for p in on) if on
                        else f"{heard}/{len(w['zones'])} seen")
            else:
                heard = sum(1 for t in w["tiers"] if seen(t["param"].text().strip()) is not None)
                text = f"{heard}/{len(w['tiers'])} seen"
            if w["live"].text() != text:
                w["live"].setText(text)
