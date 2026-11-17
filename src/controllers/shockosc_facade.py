"""ShockOSC on the Shockers page -- the controller side (shockosc.py has the
names; Blise's friends, 2026-11-14: an avatar already set up for ShockOSC
should need little setup).

  * The setup card: when the worn avatar has ``ShockOsc/`` parameters
    (VRChat's own list of them, vrchat_avatars.avatar_parameters, plus what
    it has sent), `get_shockosc_setup` says which groups it has and what
    each would become; `shockosc_set_up` adds the behaviours that aren't
    there yet -- nothing without that click, and a second click adds
    nothing (a behaviour of the same kind on the same parameter counts).
    They start with the values a new behaviour of their kind starts with
    on the page (settings.pishock.new_rule_values -- Blise's call,
    2026-11-16), and from then on their values and the avatar's ShockOSC
    settings are kept in step both ways (shockosc_sync.py).
  * The feedback: `shockosc_feedback` sends ShockOSC's feedback parameters
    from what the engine does. This side tells it which groups to send for
    (those with behaviours, and those the avatar shows) and which shockers
    each covers, and asks a re-send after an avatar change or an OSC
    reconnect (VRChat resets the values).

A mixin of PiShockFacade: `_pishock_init` / `_pishock_start` / `_pishock_stop`
call the lifecycle here. Assumes `self.pishock_settings`, `self.pishock_engine`,
`self.pishock_router`, `self.log_message` and (optionally) `self.osc_manager`,
`self.get_current_avatar_id` and `self.ui`.
"""

from typing import Any, Dict, List, Optional, Tuple

import shockosc
import vrchat_avatars
from parameter_store import store
from settings.pishock import new_rule_values
from shockosc_feedback import ShockOscFeedback

from .shockosc_sync import ShockOscSyncMixin

_PARAM_PREFIX = "/avatar/parameters/"


def _setup_defaults() -> Dict[str, Dict[str, Any]]:
    """What the setup's behaviours start with: a new behaviour's values."""
    return {kind: new_rule_values(kind) for kind in shockosc.SYNCED_KINDS}


class ShockOscFacade(ShockOscSyncMixin):

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _shockosc_init(self) -> None:
        self._shockosc_sync_init()
        self.shockosc_feedback = ShockOscFeedback(
            get_activity=self.pishock_engine.activity,
            get_in_use=self.pishock_engine.shocker_ids,
            send=self._shockosc_send,
            get_rests=self.pishock_router.shockosc_rests)
        self.pishock_engine.set_activity_callback(self.shockosc_feedback.wake)
        self._shockosc_follow()

    def _shockosc_start(self) -> None:
        feedback = getattr(self, "shockosc_feedback", None)
        if feedback is not None:
            self._shockosc_follow()
            feedback.start()

    def _shockosc_stop(self) -> None:
        """The feature off, or quitting: every value back to resting once,
        then nothing more."""
        feedback = getattr(self, "shockosc_feedback", None)
        if feedback is not None:
            feedback.stop()
            try:
                feedback.let_go()
            except Exception as e:
                print(f"[ShockOSC] letting go of the feedback failed: {e}")

    def shockosc_avatar_changed(self) -> None:
        """Main thread, after an avatar loads: its groups may differ, and
        VRChat reset every value -- send them again, OGP's ShockOSC settings
        first (shockosc_sync). The page's card too."""
        self._shockosc_follow()
        feedback = getattr(self, "shockosc_feedback", None)
        if feedback is not None:
            feedback.resend()
        self._shockosc_forget()
        self.shockosc_send_config(force=True)
        refresh = getattr(getattr(self, "ui", None), "refresh_pishock_shockosc", None)
        if callable(refresh):
            refresh()

    def shockosc_resend(self) -> None:
        """OSC (re)connected: VRChat knows none of the values."""
        feedback = getattr(self, "shockosc_feedback", None)
        if feedback is not None:
            feedback.resend()
        self.shockosc_send_config(force=True)

    def _shockosc_send(self, name: str, value: Any) -> bool:
        """One feedback parameter out; True when it went (the link is up)."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return False
        try:
            osc.send_parameter(_PARAM_PREFIX + name, value, ignore_rate_limit=True)
        except Exception:
            return False
        return True

    # ------------------------------------------------------------------
    # What the avatar has, what the behaviours are
    # ------------------------------------------------------------------

    def _shockosc_avatar_names(self) -> Tuple[Optional[set], str]:
        """(every parameter the worn avatar has -- VRChat's file plus what
        it sent -- or None while there's nothing to go by, and where that
        came from: "file", "osc" or "")."""
        params = store.get_all_parameters() or {}
        get_id = getattr(self, "get_current_avatar_id", None)
        try:
            listed = vrchat_avatars.avatar_parameters(get_id()) if callable(get_id) else None
        except Exception:
            listed = None
        if listed is None and not params:
            return None, ""
        return set(params) | set(listed or ()), "file" if listed is not None else "osc"

    def _shockosc_shocker_names(self) -> List[Tuple[int, str]]:
        """((id, name), ...) of the shockers the page has a card for."""
        eng, s = self.pishock_engine, self.pishock_settings
        openshock = s.get_openshock_shockers() or []
        if eng.hub_kind == "openshock" or (openshock and not eng.is_connected):
            return [(int(o["id"]), str(o.get("name") or "")) for o in openshock]
        if eng.is_connected:
            return [(int(x["id"]), str(x.get("name") or f"Shocker {x['id']}"))
                    for x in eng.all_shockers()]
        return []

    def _shockosc_rule_groups(self) -> Dict[str, Any]:
        """The ShockOSC groups the behaviours are on (name -> the shockers
        they drive: "all", or ids in the order first dropped)."""
        out: Dict[str, Any] = {}
        spelled: Dict[str, str] = {}
        for kind, rules in self.pishock_settings.get_all_rules().items():
            for r in rules:
                if not r.get("enabled", True):
                    continue
                pairs = ([(z.get("param", ""), z.get("shockers", [])) for z in r.get("zones") or []]
                         if kind == "zones" else
                         [(t.get("param", ""), r.get("shockers", [])) for t in r.get("tiers") or []]
                         if kind == "impacts" else [(r.get("param", ""), r.get("shockers", []))])
                for param_name, which in pairs:
                    group = shockosc.group_of_rule(param_name)
                    if group is None:
                        continue
                    name = spelled.setdefault(shockosc.group_key(group), group)
                    have = out.get(name, [])
                    if which == "all" or have == "all":
                        out[name] = "all"
                    else:
                        out[name] = have + [sid for sid in which if sid not in have]
        return out

    def _shockosc_follow(self) -> None:
        """Tell the feedback which groups to send for: those with
        behaviours, and those whose feedback the worn avatar has (a group
        with no behaviour covers the shocker with its name; ``_All`` every
        one). With the avatar's list known, only the parameters it has go
        out; with no ShockOSC anywhere, nothing does."""
        feedback = getattr(self, "shockosc_feedback", None)
        if feedback is None:
            return
        groups = self._shockosc_rule_groups()
        names, source = self._shockosc_avatar_names()
        if source != "file":
            # no list of the avatar's parameters (only what it sent, which
            # never includes feedback it hasn't been sent): the behaviours'
            # groups, every feedback parameter
            feedback.set_groups(groups, any_too=bool(groups))
            return
        only = {n for n in names if (shockosc.split(n) or ("", ""))[1] in shockosc.FEEDBACK}
        if not only:
            feedback.set_groups({}, any_too=False)      # nothing on it to light up
            return
        # the avatar's own list: just what it has, under its spelling; a
        # group it shows without a behaviour covers the shocker with its name
        spelled = {shockosc.group_key(shockosc.split(n)[0]): shockosc.split(n)[0] for n in only}
        groups = {spelled.get(shockosc.group_key(g), g): w for g, w in groups.items()}
        have = {shockosc.group_key(g) for g in groups}
        shockers = self._shockosc_shocker_names()
        for key, g in spelled.items():
            if key not in have and key != shockosc.group_key(shockosc.ANY):
                groups[g] = shockosc.suggested_shockers(g, shockers)
        feedback.set_groups(groups, any_too=True, only=only)

    # ------------------------------------------------------------------
    # The setup card (UI-facing, primitives only)
    # ------------------------------------------------------------------

    def get_shockosc_setup(self) -> Dict[str, Any]:
        """For the Shockers page's ShockOSC card: the worn avatar's groups,
        each with what it would become and how much of that is already
        there, whom it would drive (the shocker with its name, every one
        for ``_All``), and which of ShockOSC's settings the avatar has --
        the ones kept in step with the behaviours (`synced`)."""
        names, source = self._shockosc_avatar_names()
        out: Dict[str, Any] = {"groups": [], "source": source, "synced": []}
        if not names or not shockosc.has_shockosc(names):
            return out
        found = shockosc.groups_on_avatar(names)
        rules = self.pishock_settings.get_all_rules()
        shockers = self._shockosc_shocker_names()
        order = sorted(found, key=lambda g: (shockosc.group_key(g) == shockosc.group_key(shockosc.ALL),
                                             shockosc.group_key(g)))
        defaults = _setup_defaults()
        for g in order:
            plan = shockosc.planned_rules(g, found[g], [], defaults)
            if not plan:
                continue
            missing = shockosc.missing_rules(plan, rules)
            out["groups"].append({
                "name": g, "label": shockosc.label(g),
                "makes": [shockosc.describe(k, r) for k, r in plan],
                "total": len(plan), "missing": len(missing),
                "suggested": shockosc.suggested_shockers(g, shockers)})
        out["synced"] = shockosc.synced_settings(names)
        return out

    def shockosc_set_up(self, chosen: Optional[Dict[str, Any]] = None) -> int:
        """Add the behaviours the worn avatar's ShockOSC groups need and
        don't have yet; each group drives what `chosen` names for it ("all"
        or shocker ids -- dropped on the card), else its suggestion. Returns
        how many were added: a second call adds none."""
        names, _src = self._shockosc_avatar_names()
        if not names:
            return 0
        found = shockosc.groups_on_avatar(names)
        shockers = self._shockosc_shocker_names()
        chosen = {shockosc.group_key(k): v for k, v in (chosen or {}).items()}
        plan = []
        for g, inputs in found.items():
            which = chosen.get(shockosc.group_key(g))
            if which is None:
                which = shockosc.suggested_shockers(g, shockers)
            plan += shockosc.planned_rules(g, inputs, which, _setup_defaults())
        new = shockosc.missing_rules(plan, self.pishock_settings.get_all_rules())
        added = self.pishock_settings.add_rules(new)
        if added:
            self.pishock_router.rules_changed()
            self._shockosc_follow()
            self.shockosc_send_config()             # the avatar takes OGP's values
            groups = sorted({shockosc.label(shockosc.group_of_rule(r["param"])) for _k, r in new})
            self.log_message(f"Shockers: set up {added} behaviour{'s' * (added != 1)} from "
                             f"your avatar's ShockOSC parameters ({', '.join(groups)})")
        return added
