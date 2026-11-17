"""ShockOSC's settings and the Shockers behaviours' own values, kept in
step both ways (Blise's call, 2026-11-16: "We should always have the same
values, and they should try to sync to each other as good as they can").

shockosc.py says which avatar parameter each value of a behaviour on a
ShockOSC parameter goes with (`address`; `_Config/_All/...` is the default
every group follows, as in ShockOSC) and how the units turn. Here:

  * **Avatar -> OGP.** A `ShockOsc/_Config/...` value from VRChat -- the
    avatar's menu, or a friend's Avatar Remote / YOLO set (params_facade's
    `_params_send` hands those over too) -- changes every behaviour that
    goes with that parameter: saved, and the page redraws. The global
    Paused is ShockOSC's kill switch: on, every ShockOSC behaviour goes
    Off. Nothing is sent back for it.
  * **OGP -> avatar.** A behaviour changed on the page changes the others
    that go with the same parameter (one value) and sends that parameter;
    an undo does too. On / Off sends Paused = all of them off.
  * **OGP first.** After an avatar loads (and when OSC comes back) OGP's
    values are sent, and VRChat's replay of the avatar's saved ones is
    answered with OGP's (`_ogp_mode_guard_until`, as for OGP's own menu).
  * Never an echo: a value OGP sent that comes back within `_ECHO_S` --
    the latest or one just before it -- is OGP's own, not a hand.
  * Paused stops them like Stop: the avatar's Paused going on switches its
    behaviours Off and ends at once whatever they are running, a pulse
    already playing included (PiShockRouter.stop_shockosc).

The values are the behaviours' own: every shocker's limits, arming, the
action switches and the rest still hold at the engine, whatever the avatar
says; a strength of 0 sends nothing (the router). A mixin of
ShockOscFacade; everything runs on the main thread except `_shockosc_on_osc`
(the OSC thread: a queue put).
"""

import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

import shockosc as so
from parameter_store import store

_PARAM_PREFIX = "/avatar/parameters/"
_CONFIG_ADDRESS = _PARAM_PREFIX + so.CONFIG_PREFIX
_ECHO_S = 1.0           # what OGP set comes back this soon: not a hand
Link = Tuple[str, int, str]     # (kind, index, value)


class ShockOscSyncMixin:

    def _shockosc_sync_init(self) -> None:
        self._sosc_sent: Dict[str, List[Tuple[Any, float]]] = {}  # what OGP set lately, and when
        self._sosc_heard: Dict[str, Any] = {}                # what the avatar holds, as far as we know

    # ------------------------------------------------------------------
    # Which behaviour goes with which avatar parameter
    # ------------------------------------------------------------------

    def _shockosc_has(self) -> Callable[[str], bool]:
        """Whether the worn avatar has a parameter (VRChat's list of them,
        plus what it sent)."""
        names, _source = self._shockosc_avatar_names()
        names = names or set()
        return lambda n: n in names

    @staticmethod
    def _shockosc_said() -> Dict[str, Any]:
        """The ShockOSC settings the avatar last sent (its modes, overrides)."""
        return {k: v for k, v in (store.get_all_parameters() or {}).items()
                if k.startswith(so.CONFIG_PREFIX)}

    def _shockosc_links(self, rules: Dict[str, List[Dict[str, Any]]],
                        has: Optional[Callable[[str], bool]] = None,
                        said: Optional[Dict[str, Any]] = None) -> Dict[str, List[Link]]:
        """avatar parameter -> the (kind, index, value) of every behaviour
        value that goes with it, in the page's order."""
        has = has or self._shockosc_has()
        said = self._shockosc_said() if said is None else said
        out: Dict[str, List[Link]] = {}
        for kind in so.SYNCED_KINDS:
            for i, rule in enumerate(rules.get(kind) or []):
                p = rule.get("param", "")
                fields = so.fields_of(kind, p)
                group = so.group_of_rule(p)
                for value in so.VALUE_ORDER:
                    if value in fields:
                        name = so.address(group, value, has, said)
                        if name:
                            out.setdefault(name, []).append((kind, i, value))
        return out

    @staticmethod
    def _shockosc_ogp_value(rules: Dict[str, List[Dict[str, Any]]], links: List[Link]) -> Any:
        """OGP's value for a parameter: its first behaviour's -- On / Off:
        on while any of them is on."""
        kind, i, value = links[0]
        if value == so.ON:
            return any(bool(rules[k][j].get("enabled", True)) for k, j, _v in links)
        return rules[kind][i].get(so.field_name(kind, value))

    # ------------------------------------------------------------------
    # OGP -> the avatar
    # ------------------------------------------------------------------

    def shockosc_send_config(self, force: bool = False,
                             only: Optional[Iterable[str]] = None) -> int:
        """Put OGP's values on the avatar's ShockOSC settings: those the
        avatar doesn't hold already (`force`: all of them -- an avatar
        loaded, OSC came back), or just `only` these. Returns how many went."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False) or not self._shockosc_on():
            return 0
        rules = self.pishock_settings.get_all_rules()
        said = self._shockosc_said()
        links = self._shockosc_links(rules, said=said)
        only = None if only is None else set(only)
        now, sent = time.monotonic(), 0
        for name, entries in links.items():
            if only is not None and name not in only:
                continue
            want = so.to_avatar(name, entries[0][2], self._shockosc_ogp_value(rules, entries))
            held = self._sosc_heard.get(name, said.get(name))
            if not force and held is not None and so.same(held, want):
                continue
            try:
                osc.send_parameter(_PARAM_PREFIX + name, want, ignore_rate_limit=True)
            except Exception:
                continue
            recent = [(v, t) for v, t in self._sosc_sent.get(name, []) if now - t < _ECHO_S]
            self._sosc_sent[name] = recent + [(want, now)]
            self._sosc_heard[name] = want
            sent += 1
        return sent

    def _shockosc_rule_edited(self, kind: str, index: int, old: Dict[str, Any],
                              new: Dict[str, Any]) -> None:
        """The page changed a behaviour: the others that go with the same
        avatar parameter take the same value, and the avatar hears it."""
        fields = so.fields_of(kind, new.get("param", ""))
        if not fields and not so.fields_of(kind, old.get("param", "")):
            return
        rules = self.pishock_settings.get_all_rules()
        links = self._shockosc_links(rules)
        touched: Set[str] = set()
        names: Set[str] = set()
        for name, entries in links.items():
            mine = [v for k, i, v in entries if (k, i) == (kind, index)]
            if not mine:
                continue
            names.add(name)
            value = mine[0]
            if value == so.ON:
                continue                    # each behaviour's own switch; Paused = all off
            fld = so.field_name(kind, value)
            if fld is None or old.get(fld) == new.get(fld):
                continue
            for k, i, v in entries:
                if (k, i) != (kind, index):
                    rule = rules[k][i]
                    if rule.get(so.field_name(k, v)) != new.get(fld):
                        rules[k][i] = so.with_value(k, rule, v, new.get(fld))
                        touched.add(k)
        if touched:
            self.pishock_settings.set_rules({k: rules[k] for k in touched})
            self.pishock_router.rules_changed()
            self._shockosc_redraw()
        if names:
            self.shockosc_send_config(only=names)

    # ------------------------------------------------------------------
    # The avatar -> OGP
    # ------------------------------------------------------------------

    def _shockosc_on_osc(self, address: str, value: Any) -> None:
        """OSC thread: a ShockOSC setting arrived -- to the main thread."""
        if address.startswith(_CONFIG_ADDRESS) or address == _PARAM_PREFIX + so.LEGACY_PAUSED:
            self.thread_queue.put(("shockosc_config", (address[len(_PARAM_PREFIX):], value)))

    def _shockosc_heard_set(self, name: str, value: Any) -> None:
        """Any thread: a friend's Avatar Remote / YOLO set of a ShockOSC
        setting (params_facade), taken like the avatar's own."""
        if name.startswith(so.CONFIG_PREFIX):
            self.thread_queue.put(("shockosc_config", (name, value)))

    def _shockosc_config_heard(self, name: str, value: Any) -> None:
        """Main thread: the avatar's ShockOSC setting `name` says `value`."""
        if not self._shockosc_on():
            return
        setting = so.config_setting(name)
        if setting is None:
            return
        now = time.monotonic()
        if now < getattr(self, "_ogp_mode_guard_until", 0.0):
            # an avatar just loaded: VRChat replays its saved values -- OGP's
            # go back instead (OGP first)
            self.shockosc_send_config(force=True, only=[name])
            return
        if any(now - t < _ECHO_S and so.same(v, value) for v, t in self._sosc_sent.get(name, [])):
            return                                  # ours, coming back (even a late one)
        self._sosc_heard[name] = value
        group, what = setting
        if what in (so.MODE_INTENSITY, so.MODE_DURATION, so.OVERRIDE_INTENSITY,
                    so.OVERRIDE_DURATION, so.OVERRIDE_COOLDOWN):
            # which parameter a value goes with may have moved: OGP's values
            # go where they now belong
            self.shockosc_send_config()
            return
        rules = self.pishock_settings.get_all_rules()
        links = self._shockosc_links(rules)
        entries = list(links.get(name, []))
        pausing = what == so.PAUSED and so.from_avatar(name, so.ON, value) is False
        kill = pausing and so.group_key(group) == so.group_key(so.ALL)
        if kill:
            # ShockOSC's kill switch: every ShockOSC behaviour off
            entries = [e for es in links.values() for e in es if e[2] == so.ON]
        touched: Set[str] = set()
        for kind, i, v in entries:
            new = so.from_avatar(name, v, value)
            if new is None:
                continue
            rule = rules[kind][i]
            if rule.get(so.field_name(kind, v)) != new:
                rules[kind][i] = so.with_value(kind, rule, v, new)
                touched.add(kind)
        if touched:
            self.pishock_settings.set_rules({k: rules[k] for k in touched})
            self.pishock_router.rules_changed()
            self._shockosc_follow()
            self._shockosc_redraw()
        if pausing and (kill or entries):
            # Paused stops them like Stop: what they are running now ends at
            # once, a pulse already playing too -- after the switch to Off
            # above, so their holds are gone from the same tick
            self.pishock_router.stop_shockosc(
                None if kill else {so.group_of_rule(rules[k][i].get("param", ""))
                                   for k, i, _v in entries})

    # ------------------------------------------------------------------

    def _shockosc_on(self) -> bool:
        get = getattr(self, "get_feature_enabled", None)
        try:
            return bool(get("feature_pishock")) if callable(get) else True
        except Exception:
            return False

    def _shockosc_redraw(self) -> None:
        """The page shows the new values (redrawn on the next event-loop
        turn, never inside the slider that is sending)."""
        try:
            self.thread_queue.put(("shockosc_rules", None))
        except Exception:
            pass

    def _shockosc_rules_changed(self) -> None:
        """Main thread, for a "shockosc_rules" on the queue."""
        refresh = getattr(getattr(self, "ui", None), "refresh_pishock_rules", None)
        if callable(refresh):
            refresh()

    def _shockosc_forget(self) -> None:
        """Another avatar: what its settings hold is unknown again."""
        self._sosc_sent, self._sosc_heard = {}, {}
