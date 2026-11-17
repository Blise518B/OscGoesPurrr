"""Shockers view, the behaviours: what your avatar's contacts do -- Touch
zones (several contacts, each with its own shockers), Contact, Continuous,
Impact and Pull (a PhysBone) -- a card each in the Behaviours frame, saved
as you edit them. One on a ShockOSC parameter wears a SHOCKOSC tag and a
"Rest after a shock": its values and the avatar's ShockOSC settings are
kept in step both ways (shockosc_sync.py).
A behaviour drives the shockers dropped on it: drag a shocker card's ⠿
onto it (onto one zone, for Touch zones), or pick from its ＋. Part of
PiShockMixin (pishock.py)."""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QPushButton, QWidget

import param_filters
import shockosc
from settings.pishock import (
    MAX_HOLD_MS, MAX_REST_MS, MAX_TIERS, MAX_ZONES, RULE_KINDS, physbone_name,
)
from utilities import strip_param_prefix
from ui.layout_helpers import clear_layout, hbox as _hbox, vbox as _vbox
from ui.osc_variable_picker import open_osc_variable_picker
from ui.views.card_parts import segmented
from ui.views.param_cards import CARD_W
from ui.views.pishock_cards import (
    MIME_SHOCKER, SHOCK_HUE, ShockerDropZone, ValueSlider, category_frame, fmt_seconds,
    fmt_short, mini_button, name_edit, state_pill,
)
from ui.widgets import ToggleSwitch

BEHAVIOUR_HUE = "cyan"
BEHAVIOUR_W = 2 * CARD_W + 10        # two shocker cards wide
_OPS = (("Vibrate", "vibrate"), ("Shock", "shock"), ("Beep", "beep"))
_HELD = (("Nothing", "none"), ("Vibrate", "vibrate"), ("Shock", "shock"), ("Beep", "beep"))
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
    "pulls": ("PULL", "Pull",
              "A PhysBone - a tail, an ear: something while it is held, and letting go "
              "after a stretch fires once, the harder the pull the stronger. ShockOSC's "
              "PhysBone works this way."),
}


def _hold_text(v: float) -> str:
    return "at once" if v < 1 else fmt_short(v)


def _strength_text(v: float) -> str:
    return "0 · nothing" if v < 1 else f"{v:.0f}"


def _rest_text(v: float) -> str:
    return "the shockers' own" if v < 1 else fmt_seconds(v / 1000)


def is_shockosc(kind: str, rule: Dict[str, Any]) -> bool:
    """Is a behaviour on one of ShockOSC's parameters (any of its contacts)?"""
    params = [rule.get("param", "")]
    params += [z.get("param", "") for z in rule.get("zones") or []]
    params += [t.get("param", "") for t in rule.get("tiers") or []]
    return any(shockosc.group_of_rule(p) is not None for p in params if p)


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
    # the shockers switched off on their card: grey chips, skipped
    _pishock_shockers_off: frozenset = frozenset()
    # each shocker's Shock / Vibrate / Beep switched off: a behaviour of that
    # op greys its chip there ({id: frozenset of ops})
    _pishock_ops_off: Dict[int, frozenset] = {}

    def _pishock_op_off_ids(self, op: str) -> List[int]:
        """The shockers with `op` switched off on their card."""
        return [sid for sid, ops in self._pishock_ops_off.items() if op in ops]

    def _build_pishock_behaviours_frame(self) -> QFrame:
        frame, root, self._pishock_rule_flow, head = category_frame(
            "BEHAVIOURS", BEHAVIOUR_HUE)
        add = mini_button("＋ Add behaviour")
        head.addWidget(add)
        self._explain(add, "Add behaviour", "Touch zones, Contact, Continuous, Impact or Pull.")
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

    def refresh_pishock_rules(self) -> None:
        """Controller facade: behaviours' values changed outside the page
        (the avatar's ShockOSC settings, kept in step) -- redraw them."""
        self._rebuild_pishock_rules()

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
                             "shockers": rule.get("shockers", []), "drops": [],
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
        if is_shockosc(kind, rule):
            tag = state_pill("SHOCKOSC", "idle")
            top.addWidget(tag)
            self._explain(tag, "ShockOSC",
                          "This behaviour listens to a ShockOSC parameter, and its values are "
                          "your avatar's ShockOSC settings too. Its strength, length, rest after "
                          "a shock, touch time and On / Off change when your avatar's menu "
                          "changes them, and changing them here changes your avatar's. A "
                          "shocker's limits still hold whatever either side says.")
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
        elif kind == "pulls":
            w["param"] = self._pishock_param(lay, rule.get("param", ""), w,
                                             "PhysBone parameter, e.g. ShockOsc/Tail",
                                             physbone=True)
        line = _hbox(0, 8)
        if kind == "pulls":
            let_go = QLabel("When let go")
            let_go.setProperty("muted", "true")
            line.addWidget(let_go)
        seg, w["op"] = segmented([t for t, _ in _OPS], SHOCK_HUE,
                                 lambda _i: (self._pishock_op_shown(w), w["push"]()))
        w["op"].button([o for _, o in _OPS].index(rule.get("op", "vibrate"))).setChecked(True)
        self._explain(seg, "When let go" if kind == "pulls" else "What it does",
                      ("What a let-go after a stretch fires: Vibrate, Shock or Beep. "
                       if kind == "pulls" else "Vibrate, Shock or Beep. ")
                      + "Shock goes out as a vibrate until shocks are armed. A shocker with "
                      "this switched off on its card is skipped (its chip greys).")
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
        if kind == "pulls":
            held_line = _hbox(0, 8)
            held_lbl = QLabel("While held")
            held_lbl.setProperty("muted", "true")
            held_line.addWidget(held_lbl)
            hseg, w["held_op"] = segmented([t for t, _ in _HELD], SHOCK_HUE,
                                           lambda _i: w["push"]())
            held = rule.get("held_op", "vibrate")
            w["held_op"].button([o for _, o in _HELD].index(
                held if held in [o for _, o in _HELD] else "vibrate")).setChecked(True)
            self._explain(hseg, "While held",
                          "What runs while the PhysBone is grabbed - a warning before the "
                          "let-go. Its strength follows the stretch too.")
            held_line.addWidget(hseg)
            held_line.addStretch(1)
            lay.addLayout(held_line)

        def slider(key, *args, **kw):
            s = ValueSlider(*args, on_change=lambda _v: w["push"](), **kw)
            w[key] = s
            lay.addWidget(s)
            return s

        strength = _strength_text
        if kind in ("triggers", "zones"):
            slider("intensity", "Strength", 0 if kind == "triggers" else 1, 100,
                   rule.get("intensity", 20), fmt=strength,
                   tip="Always this strength - never above a shocker's own max. 0 sends "
                       "nothing.")
            slider("duration_ms", "Length", 100, 15000, rule.get("duration_ms", 500), 100,
                   fmt=lambda v: fmt_seconds(v / 1000),
                   tip="How long one pulse lasts (Pulse once) - never past a shocker's "
                       "longest pulse.")
            if kind == "triggers":
                slider("hold_ms", "Touch for at least", 0, MAX_HOLD_MS,
                       rule.get("hold_ms", 0), 50, fmt=_hold_text, hue=BEHAVIOUR_HUE,
                       tip="How long the contact has to stay touched before the pulse - "
                           "a brush that's shorter does nothing. On a ShockOSC touch it is "
                           "your avatar's HoldTime.")
            self._pishock_mode_shown(w)
        elif kind == "continuous":
            slider("threshold", "Starts above", 0.0, 0.99, rule.get("threshold", 0.0), 0.01,
                   fmt=lambda v: f"{v:.2f}", hue=BEHAVIOUR_HUE,
                   tip="It runs while the value is above this. 0 = any contact at all.")
            slider("min_int", "Strength just past it", 0, 100, rule.get("min_int", 5),
                   fmt=strength)
            slider("max_int", "Strength at 1", 0, 100, rule.get("max_int", 30), fmt=strength,
                   tip="In between, the strength follows the value. 0 sends nothing.")
        elif kind == "pulls":
            slider("min_int", "Strength at a slight pull", 0, 100, rule.get("min_int", 5),
                   fmt=strength, tip="Let go after the smallest stretch: this strength.")
            slider("max_int", "Strength at full stretch", 0, 100, rule.get("max_int", 30),
                   fmt=strength, tip="In between, the strength follows the stretch at the "
                                     "moment it is let go - never above a shocker's own max.")
            slider("duration_ms", "Length", 100, 15000, rule.get("duration_ms", 500), 100,
                   fmt=lambda v: fmt_seconds(v / 1000),
                   tip="How long the let-go's pulse lasts - never past a shocker's longest "
                       "pulse.")
        else:
            slider("duration_ms", "Length", 100, 15000, rule.get("duration_ms", 500), 100,
                   fmt=lambda v: fmt_seconds(v / 1000), tip="How long the pulse lasts.")
            self._pishock_tiers(lay, rule, w)

        if kind in ("triggers", "continuous", "pulls") and is_shockosc(kind, rule):
            slider("rest_ms", "Rest after a shock", 0, MAX_REST_MS, rule.get("rest_ms", 0), 500,
                   fmt=_rest_text, hue=BEHAVIOUR_HUE,
                   tip="After a shock from this ShockOSC group, its behaviours wait this long - "
                       "your avatar's ShockOSC CooldownTime. The shockers' own rest after a "
                       "pulse always holds too.")

        if kind == "zones":
            self._pishock_zones(lay, rule, w)
        else:
            op = rule.get("op", "vibrate")
            zone = ShockerDropZone(rule.get("shockers", []), self._pishock_shocker_choices,
                                   lambda t: (w.__setitem__("shockers", t), w["push"]()),
                                   off=self._pishock_shockers_off,
                                   op_off=self._pishock_op_off_ids(op), op=op)
            card.zone = zone
            w["drops"].append(zone)
            lay.addWidget(zone)
        return card, w

    def _pishock_op_shown(self, w: Dict[str, Any]) -> None:
        """The behaviour's op changed: its chips grey for the shockers that
        have the new one switched off."""
        op = _OPS[max(0, w["op"].checkedId())][1]
        for zone in w.get("drops") or []:
            zone.set_op_off(self._pishock_op_off_ids(op), op)

    def _pishock_mode_shown(self, w: Dict[str, Any]) -> None:
        if "mode" in w:
            pulse = w["mode"].checkedId() == 0
            for key in ("duration_ms", "hold_ms"):
                if key in w:
                    w[key].setVisible(pulse)

    def _pishock_param(self, lay, value: str, w, placeholder: str,
                       physbone: bool = False) -> QLineEdit:
        row = _hbox(0, 6)
        edit = QLineEdit(value or "")
        edit.setPlaceholderText(placeholder)
        edit.editingFinished.connect(lambda: w["push"]())
        row.addWidget(edit, 1)
        pick = mini_button("Pick", "Choose from the parameters your avatar is sending now")
        pick.clicked.connect(lambda _=False: self._pick_pishock_param(edit, w, physbone))
        row.addWidget(pick)
        lay.addLayout(row)
        if physbone:
            self._explain(edit, "PhysBone",
                          "The PhysBone's Parameter on your avatar (VRChat adds _IsGrabbed and "
                          "_Stretch to it). Picking either of those takes the name before it.")
        else:
            self._explain(edit, "Parameter",
                          "The avatar parameter it listens to - the contact receiver's "
                          "parameter name.")
        return edit

    def _pick_pishock_param(self, edit: QLineEdit, w, physbone: bool = False) -> None:
        def on_pick(addr):
            cleaned = strip_param_prefix(addr)
            if physbone:
                cleaned = physbone_name(cleaned)
            if cleaned:
                edit.setText(cleaned)
                w["push"]()
        # PhysBone states stay listed here whatever the chips say: ShockOSC
        # and friends drive shocks from a PhysBone's _IsGrabbed / _Stretch.
        # ShockOSC's own parameters come first, under their own heading.
        open_osc_variable_picker(
            (getattr(self, "dialog_parent", None) or self.window), on_pick, allow_wildcards=False,
            subtitle="Pick the contact receiver's parameter (double-click) or "
                     "enter one manually.",
            mapped=[edit.text()], settings=self.controller, keep=(param_filters.PHYSBONES,),
            first=(param_filters.SHOCKOSC,))

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
            op = rule.get("op", "vibrate")
            drop = ShockerDropZone(entry["shockers"], self._pishock_shocker_choices,
                                   lambda t, e=entry: (e.__setitem__("shockers", t), w["push"]()),
                                   off=self._pishock_shockers_off,
                                   op_off=self._pishock_op_off_ids(op), op=op)
            w["drops"].append(drop)
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
            rule["hold_ms"] = round(w["hold_ms"].value())
        elif kind == "pulls":
            rule.update(param=physbone_name(w["param"].text().strip()),
                        held_op=_HELD[max(0, w["held_op"].checkedId())][1],
                        min_int=round(w["min_int"].value()),
                        max_int=round(w["max_int"].value()),
                        duration_ms=round(w["duration_ms"].value()))
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
        if "rest_ms" in w:                  # a ShockOSC behaviour's rest after a shock
            rule["rest_ms"] = round(w["rest_ms"].value())
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
            elif kind == "pulls":
                bone = physbone_name(w["param"].text().strip())
                held = seen(bone + "_IsGrabbed") if bone else None
                stretch = seen(bone + "_Stretch") if bone else None
                text = ("—" if held is None and stretch is None
                        else f"held · {stretch or 0:.2f}" if (held or 0) > 0 else "free")
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
