"""Params, part 2: the avatar menu's Avatar Remote submenu -- seven Toggles
(`OGP/Remote/Toggle1-7`) and seven Radials (`OGP/Remote/Radial1-7`), each
a slot that a control or a whole category of the worn avatar's board takes
on the Avatar Remote page (param_board's slots; Blise's ask, 2026-10-29).

The menu drives straight from the OSC thread (no queue hop): `_slot_map`
is a snapshot of what each slot drives, swapped whole by the GUI thread
whenever the board changes, and `_params_send` goes to VRChat from any
thread. A locked category is about friends -- your own menu drives it.

The page and the menu agree, OGP first (as for the Friends menu, Blise's
call 2026-10-28): the GUI tick puts a slot's own Toggle / Radial where its
controls are -- on while any of them is ON, the first one's place between
its min and max -- whenever that changed from the page, a friend or
VRChat's own menu. Never with a value the menu just sent us back (VRChat
echoes what OGP sets), never while you are still turning it, and after an
avatar load VRChat's replayed values are answered with OGP's.

Mixed into ParamsFacade (params_facade.py).
"""

import time
from typing import Any, Dict, List, Optional, Tuple

import param_board as pb
from constants import OGP_REMOTE_RADIAL_PARAMETERS, OGP_REMOTE_TOGGLE_PARAMETERS
from parameter_store import store

_PREFIX = "OGP/Remote/"
_PARAMS = {"toggle": OGP_REMOTE_TOGGLE_PARAMETERS, "radial": OGP_REMOTE_RADIAL_PARAMETERS}
_OSC_TYPE = {"toggle": "T", "radial": "f"}
_ECHO_S = 1.0           # what OGP set on the menu comes back this soon: not a hand
_HANDS_OFF_S = 1.5      # the menu isn't moved for you this long after you moved it
_SAME = 0.01


def _same(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < _SAME
    except (TypeError, ValueError):
        return False


class ParamsMenuMixin:
    """Mixin: the avatar menu's Avatar Remote slots."""

    def _params_menu_init(self) -> None:
        # menu parameter -> ("toggle" | "radial", [controls]): the worn board's
        # taken slots, swapped whole by the GUI thread
        self._slot_map: Dict[str, Tuple[str, List[Dict[str, Any]]]] = {}
        self._slot_heard: Dict[str, Any] = {}               # what the menu shows, as far as we know
        self._slot_sent: Dict[str, Tuple[Any, float]] = {}  # what OGP set on it, and when
        self._slot_hand_t: Dict[str, float] = {}            # when you last moved it

    def _params_menu_rebuild(self, board: Optional[Dict[str, Any]]) -> None:
        """GUI thread: what each slot of the worn board drives now."""
        slots = (board or {}).get("slots") or {}
        out = {}
        for menu, params in _PARAMS.items():
            taken = slots.get(menu) or []
            for i, param in enumerate(params):
                key = taken[i] if i < len(taken) else None
                controls = [dict(c) for c in pb.slot_controls(board or {}, menu, key)]
                if controls:
                    out[param] = (menu, controls)
        self._slot_map = out

    def _params_menu_forget(self) -> None:
        """Another avatar: its menu starts from its own defaults."""
        self._slot_heard, self._slot_sent, self._slot_hand_t = {}, {}, {}

    def _params_menu_on_osc(self, address: str, value: Any) -> None:
        """OSC thread: one of the menu's Toggles / Radials moved."""
        if not address.startswith(_PREFIX) or not hasattr(self, "_slot_map") \
                or not self._params_enabled():
            return
        now = time.monotonic()
        if now < getattr(self, "_ogp_mode_guard_until", 0.0):
            # an avatar just loaded: VRChat is replaying saved values, not a
            # hand -- OGP's own go back, as for your own controls
            self._params_menu_send(address)
            return
        self._slot_heard[address] = value
        sent = self._slot_sent.get(address)
        if sent is not None and now - sent[1] < _ECHO_S and _same(sent[0], value):
            return                                  # ours, coming back
        self._slot_hand_t[address] = now
        entry = self._slot_map.get(address)
        if entry is None:
            return                                  # a free slot does nothing
        menu, controls = entry
        for control in controls:
            out = pb.slot_send_value(menu, control, value)
            if out is not None:
                self._params_send(control["param"], control["ptype"], out)

    def _params_menu_follow(self) -> None:
        """GUI tick: each taken slot's Toggle / Radial goes where its
        controls are, when that changed."""
        if not self._slot_map or not self._params_enabled() \
                or time.monotonic() < getattr(self, "_ogp_mode_guard_until", 0.0):
            return
        self._params_menu_send(changed_only=True)

    def _params_menu_send(self, address: str = "", changed_only: bool = False) -> None:
        """Put OGP's state of the slots on the menu: all of them (OSC
        (re)connect, avatar load), the one VRChat just replayed, or only
        those that changed (the tick)."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False) \
                or not hasattr(self, "_slot_map") or not self._params_enabled():
            return
        slot_map = self._slot_map
        names = {c["param"] for _menu, controls in slot_map.values() for c in controls}
        values = store.get_values(names) if names else {}
        now = time.monotonic()
        for param, (menu, controls) in slot_map.items():
            if address and param != address:
                continue
            if changed_only and now - self._slot_hand_t.get(param, -_HANDS_OFF_S) < _HANDS_OFF_S:
                continue                            # you're still turning it
            want = pb.slot_state(menu, controls, values)
            if want is None:
                continue
            if changed_only and param in self._slot_heard and _same(self._slot_heard[param], want):
                continue
            try:
                osc.send_parameter("/avatar/parameters/" + param, want,
                                   ignore_rate_limit=True, force_type=_OSC_TYPE[menu])
            except Exception:
                continue
            self._slot_sent[param] = (want, now)
            self._slot_heard[param] = want
