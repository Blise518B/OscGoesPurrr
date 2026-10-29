"""Friends, part 3: the VRChat menu's Friends submenu (`OGP/Friend/*`) and
its Both of us (`OGP/Both/*`), from your own avatar. Acts on whoever is
picked on the Friends page -- a friend, or a group's members -- and Both of
us on you as well, straight from the OSC receive thread (no queue hop):
every write path it uses is thread-safe. The menu's own state is a
`MenuState`, touched by the OSC thread only.

Mixed into FriendsFacade; see friends_facade.py for what the host has.
"""

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import friend_patterns
import remote_protocol as proto
from constants import (
    OGP_BOTH_LENGTH_PARAMETER, OGP_BOTH_LEVEL_PARAMETER, OGP_BOTH_MODE_PARAMETER,
    OGP_BOTH_SHOCK_PARAMETER, OGP_BOTH_SPEED_PARAMETER, OGP_BOTH_STOP_PARAMETER,
    OGP_BOTH_STRENGTH_PARAMETER, OGP_BOTH_VIBRATE_PARAMETER,
    OGP_FRIEND_BEEP_PARAMETER, OGP_FRIEND_LEVEL_PARAMETER, OGP_FRIEND_MODE_PARAMETER,
    OGP_FRIEND_OVERRIDE_PARAMETER, OGP_FRIEND_RANGE_PARAMETER,
    OGP_FRIEND_SHOCK_LENGTH_PARAMETER, OGP_FRIEND_SHOCK_PARAMETER,
    OGP_FRIEND_SHOCK_STRENGTH_PARAMETER, OGP_FRIEND_SHOCKER_PARAMETERS,
    OGP_FRIEND_SPEED_PARAMETER, OGP_FRIEND_STOP_SHOCK_PARAMETER,
    OGP_FRIEND_STOP_TOYS_PARAMETER, OGP_FRIEND_STRENGTH_PARAMETER, OGP_FRIEND_TOY_PARAMETERS,
    OGP_FRIEND_VIBRATE_PARAMETER, OGP_FRIEND_WARNING_PARAMETER, OGP_STRENGTH_PARAMETER,
)
from controllers.friends_common import FEATURE_KEY, SELF, Drive, unit
from parameter_store import store

_MENU_PREFIXES = ("OGP/Friend/", "OGP/Both/")
_BOTH_RANGE = 1.0           # Both of us has no Range radial: the full range
_MENU_OPS = {OGP_FRIEND_SHOCK_PARAMETER: "shock", OGP_FRIEND_VIBRATE_PARAMETER: "vibrate",
             OGP_FRIEND_BEEP_PARAMETER: "beep"}


@dataclass
class BothMenu:
    """Both of us ▸, as last heard (the defaults are the prefab's)."""
    level: float = 0.0
    mode: int = 0
    speed: float = 0.5
    strength: float = 0.25
    length: float = 0.1


@dataclass
class MenuState:
    """The avatar menu's Friends part, as last heard from your avatar (the
    defaults are the prefab's)."""
    level: float = 0.0
    toys: List[bool] = field(default_factory=lambda: [True] * 4)
    mode: int = 0
    speed: float = 0.5
    range: float = 1.0
    override: bool = False
    shock_int: float = 0.25
    shock_len: float = 0.1
    warning: bool = False
    shockers: List[bool] = field(default_factory=lambda: [True] * 4)
    pressed: set = field(default_factory=set)      # buttons held down right now
    both: BothMenu = field(default_factory=BothMenu)


class FriendsMenuMixin:
    """Mixin: the avatar menu's Friends submenu."""

    def _friends_on_osc(self, address: str, value: Any) -> None:
        """OGP/Friend/* and OGP/Both/* from your own avatar. Acts on whoever
        is picked on the Friends page (a friend, or a group's members) --
        "Both of us" on you as well -- straight from the OSC thread (no
        queue hop): every write path here is thread-safe."""
        if (not address.startswith(_MENU_PREFIXES) or not hasattr(self, "friends_settings")
                or not self.get_feature_enabled(FEATURE_KEY)):
            return
        if time.monotonic() < getattr(self, "_ogp_mode_guard_until", 0.0):
            # an avatar just loaded: VRChat is replaying saved values, not a
            # hand -- OGP's own go back, as for your own controls
            self._menu_send(address)
            return
        m = self._friend_menu
        b = m.both
        peers = self._friends_targets()
        slots = [i for i, on in enumerate(m.shockers) if on]
        # Toys ▸
        if address == OGP_FRIEND_LEVEL_PARAMETER:
            m.level = unit(value)
            if m.mode and _menu_wave(m.mode) != "osc":
                # the Level radial is direct control: an auto mode ends
                m.mode = 0
                self._menu_echo(OGP_FRIEND_MODE_PARAMETER, 0, "i")
            for peer in peers:
                self._menu_apply(peer)
        elif address in OGP_FRIEND_TOY_PARAMETERS:
            i, on = OGP_FRIEND_TOY_PARAMETERS.index(address), bool(value)
            if m.toys[i] != on:
                for peer in peers:
                    self._menu_apply(peer, clear=True)
                m.toys[i] = on
                for peer in peers:
                    self._menu_apply(peer)
        elif address == OGP_FRIEND_MODE_PARAMETER:
            m.mode = _menu_mode(value)
            for peer in peers:
                self._menu_apply(peer)
        elif address in (OGP_FRIEND_SPEED_PARAMETER, OGP_FRIEND_RANGE_PARAMETER):
            setattr(m, "speed" if address == OGP_FRIEND_SPEED_PARAMETER else "range", unit(value))
            if m.mode:
                for peer in peers:
                    self._menu_apply(peer)
        elif address == OGP_FRIEND_OVERRIDE_PARAMETER:
            m.override = bool(value)
            for peer in peers:
                self._menu_apply(peer)
        elif address == OGP_FRIEND_STOP_TOYS_PARAMETER:
            if self._menu_pressed(address, value):
                for peer in peers:
                    self._menu_apply(peer, clear=True)
                m.level, m.mode = 0.0, 0
                self._menu_echo(OGP_FRIEND_LEVEL_PARAMETER, 0.0, "f")
                self._menu_echo(OGP_FRIEND_MODE_PARAMETER, 0, "i")
        elif address == OGP_FRIEND_STRENGTH_PARAMETER:
            for peer in peers:
                self.set_friend_strength(peer, unit(value), source="menu")
        # Shockers ▸
        elif address == OGP_FRIEND_SHOCK_STRENGTH_PARAMETER:
            m.shock_int = unit(value)
        elif address == OGP_FRIEND_SHOCK_LENGTH_PARAMETER:
            m.shock_len = unit(value)
        elif address == OGP_FRIEND_WARNING_PARAMETER:
            m.warning = bool(value)
        elif address in OGP_FRIEND_SHOCKER_PARAMETERS:
            m.shockers[OGP_FRIEND_SHOCKER_PARAMETERS.index(address)] = bool(value)
        elif address in _MENU_OPS:
            if self._menu_pressed(address, value):
                op = _MENU_OPS[address]
                self.targets_shock(slots, m.shock_int, m.shock_len, op,
                                   self._menu_warning(op), m.shock_int)
        elif address == OGP_FRIEND_STOP_SHOCK_PARAMETER:
            if self._menu_pressed(address, value):
                self.targets_stop(list(range(proto.MAX_SHOCKERS)))
        # Both of us ▸
        elif address == OGP_BOTH_LEVEL_PARAMETER:
            b.level = unit(value)
            if b.mode and _menu_wave(b.mode) != "osc":
                b.mode = 0
                self._menu_echo(OGP_BOTH_MODE_PARAMETER, 0, "i")
            self._menu_both()
        elif address == OGP_BOTH_MODE_PARAMETER:
            b.mode = _menu_mode(value)
            self._menu_both()
        elif address == OGP_BOTH_SPEED_PARAMETER:
            b.speed = unit(value)
            if b.mode:
                self._menu_both()
        elif address == OGP_BOTH_STOP_PARAMETER:
            if self._menu_pressed(address, value):
                b.level, b.mode = 0.0, 0
                self._menu_both(clear=True)
                self._menu_echo(OGP_BOTH_LEVEL_PARAMETER, 0.0, "f")
                self._menu_echo(OGP_BOTH_MODE_PARAMETER, 0, "i")
        elif address == OGP_BOTH_STRENGTH_PARAMETER:
            b.strength = unit(value)
        elif address == OGP_BOTH_LENGTH_PARAMETER:
            b.length = unit(value)
        elif address in (OGP_BOTH_SHOCK_PARAMETER, OGP_BOTH_VIBRATE_PARAMETER):
            if self._menu_pressed(address, value):
                op = "shock" if address == OGP_BOTH_SHOCK_PARAMETER else "vibrate"
                warn = self._menu_warning(op)
                self.targets_shock(slots, b.strength, b.length, op, warn, b.strength)
                self._self_shock(op, b.strength, b.length, warn, b.strength)

    # --- the menu's helpers
    def _menu_pressed(self, address: str, value: Any) -> bool:
        """A Button's press (not its release, not a repeat)."""
        held = self._friend_menu.pressed
        was, now = address in held, bool(value)
        (held.add if now else held.discard)(address)
        return now and not was

    def _menu_warning(self, op: str) -> int:
        """The Warning toggle: PiShock's Small warning (1-3 s) before a shock."""
        return random.randint(1000, 3000) if op == "shock" and self._friend_menu.warning else 0

    def _menu_echo(self, param: str, value: Any, kind: str) -> None:
        """Set one of the menu's own parameters back on the avatar (an
        auto mode the app ended: its toggle goes off)."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return
        try:
            osc.send_parameter("/avatar/parameters/" + param, value,
                               ignore_rate_limit=True, force_type=kind)
        except Exception:
            pass

    # --- the page and the menu agree; OGP first (Blise's call, 2026-10-28)
    def _menu_follow(self, peer: str, toy: str) -> None:
        """You changed the picked friend's All their toys card on the page:
        the menu's own Toys radials and toggles follow, so VRChat shows
        what OGP does. Only the All card (the one the menu drives while
        all four Which toys are on) and only for whoever is picked."""
        m = self._friend_menu
        if toy != proto.ALL_TOYS or not all(m.toys) or peer not in self._friends_targets():
            return
        level = (self._my_levels.get(peer) or {}).get(proto.ALL_TOYS, 0.0)
        pat = (self._my_patterns.get(peer) or {}).get(proto.ALL_TOYS)
        override = proto.ALL_TOYS in (self._my_override.get(peer) or ())
        mode, speed, rng = 0, m.speed, m.range
        if pat:
            wave, period, lo, hi = pat
            mode = friend_patterns.WAVES.index(wave) + 1
            speed = friend_patterns.menu_speed(wave, period)
            level, rng = ((lo + hi) / 2, hi - lo) if wave == "osc" else (m.level, hi)
        sends = []
        if abs(level - m.level) > 1e-3:
            m.level = level
            sends.append((OGP_FRIEND_LEVEL_PARAMETER, level, "f"))
        if mode != m.mode:
            m.mode = mode
            sends.append((OGP_FRIEND_MODE_PARAMETER, mode, "i"))
        if abs(speed - m.speed) > 1e-3:
            m.speed = speed
            sends.append((OGP_FRIEND_SPEED_PARAMETER, speed, "f"))
        if abs(rng - m.range) > 1e-3:
            m.range = rng
            sends.append((OGP_FRIEND_RANGE_PARAMETER, rng, "f"))
        if override != m.override:
            m.override = override
            sends.append((OGP_FRIEND_OVERRIDE_PARAMETER, override, "T"))
        for param, value, kind in sends:
            self._menu_echo(param, value, kind)

    def _menu_follow_strength(self, peer: str, value: float) -> None:
        """You moved the picked friend's strength slider: the menu's Their
        strength follows."""
        if peer in self._friends_targets():
            self._menu_echo(OGP_FRIEND_STRENGTH_PARAMETER, unit(value), "f")

    def _menu_values(self) -> List[tuple]:
        """Every one of the menu's own radials and toggles as OGP has them,
        as (parameter, value, OSC type)."""
        m = self._friend_menu
        b = m.both
        out = [(OGP_FRIEND_LEVEL_PARAMETER, m.level, "f"), (OGP_FRIEND_MODE_PARAMETER, m.mode, "i"),
               (OGP_FRIEND_SPEED_PARAMETER, m.speed, "f"), (OGP_FRIEND_RANGE_PARAMETER, m.range, "f"),
               (OGP_FRIEND_OVERRIDE_PARAMETER, m.override, "T"),
               (OGP_FRIEND_SHOCK_STRENGTH_PARAMETER, m.shock_int, "f"),
               (OGP_FRIEND_SHOCK_LENGTH_PARAMETER, m.shock_len, "f"),
               (OGP_FRIEND_WARNING_PARAMETER, m.warning, "T"),
               (OGP_BOTH_LEVEL_PARAMETER, b.level, "f"), (OGP_BOTH_MODE_PARAMETER, b.mode, "i"),
               (OGP_BOTH_SPEED_PARAMETER, b.speed, "f"), (OGP_BOTH_STRENGTH_PARAMETER, b.strength, "f"),
               (OGP_BOTH_LENGTH_PARAMETER, b.length, "f")]
        out += [(p, on, "T") for p, on in zip(OGP_FRIEND_TOY_PARAMETERS, m.toys)]
        out += [(p, on, "T") for p, on in zip(OGP_FRIEND_SHOCKER_PARAMETERS, m.shockers)]
        targets = self._friends_targets()
        mine = self._my_strength.get(targets[0]) if targets else None
        if mine is not None:
            out.append((OGP_FRIEND_STRENGTH_PARAMETER, mine[1], "f"))
        return out

    def _menu_send(self, address: str = "") -> None:
        """Put OGP's values back on the avatar: all of them (OSC reconnect,
        avatar load), or the one VRChat just replayed."""
        if not hasattr(self, "friends_settings") or not self.get_feature_enabled(FEATURE_KEY):
            return
        for param, value, kind in self._menu_values():
            if not address or param == address:
                self._menu_echo(param, value, kind)

    def _status_of(self, peer: str) -> Dict[str, Any]:
        """A friend's last status (an example friend's made up), or {}."""
        st = self._friend_status.get(peer)
        demo = self._demo_of("friend", peer)
        if st is None and demo is not None:
            st = demo.status(peer)
        return st or {}

    def _menu_keys(self, peer: str) -> List[str]:
        """The toys the Which toys toggles pick: all of them (every toy they
        have, a fifth one too) while all four are on, else their toys 1-4
        by the order their page lists them."""
        toys = self._friend_menu.toys
        if all(toys):
            return [proto.ALL_TOYS]
        names = [n for n, _m in self._status_of(peer).get("toys") or []]
        return [names[i] for i, on in enumerate(toys) if on and i < len(names)]

    def _menu_apply(self, peer: str, clear: bool = False) -> None:
        """Bring a friend's toys in line with the Toys menu: Level (direct
        control) or the auto mode, and Override, on the toys it picks."""
        if not peer:
            return
        m = self._friend_menu
        self._menu_drive(peer, m.level, m.mode, m.speed, m.range, clear)
        for key in ([] if clear else self._menu_keys(peer)):
            if (key in self._my_override.get(peer, ())) != m.override:
                self.set_friend_override(peer, key, m.override, source="menu")

    def _menu_drive(self, peer: str, level: float, mode: int, speed: float,
                    rng: float, clear: bool = False) -> None:
        keys = self._menu_keys(peer)
        pat = None if clear else _menu_pattern(mode, speed, rng, level)
        if not clear and pat is None:
            # direct control: no auto mode left on those toys
            for key in list(self._my_patterns.get(peer) or {}):
                if proto.ALL_TOYS in keys or key in keys or key == proto.ALL_TOYS:
                    self.set_friend_pattern(peer, key, "", source="menu")
        for key in keys:
            if clear:
                self.set_friend_pattern(peer, key, "", source="menu")
                self.set_friend_level(peer, key, 0.0, source="menu")
            elif pat is not None:
                self.set_friend_level(peer, key, 0.0, source="menu")
                self.set_friend_pattern(peer, key, *pat, source="menu")
            else:
                self.set_friend_level(peer, key, level, source="menu")

    def _menu_both(self, clear: bool = False) -> None:
        """Both of us: the picked friend's toys (the Which toys toggles) and
        all of yours, the same level or auto mode."""
        b = self._friend_menu.both
        for peer in self._friends_targets():
            self._menu_drive(peer, b.level, b.mode, b.speed, _BOTH_RANGE, clear)
        pat = None if clear else _menu_pattern(b.mode, b.speed, _BOTH_RANGE, b.level)
        level = 0.0 if clear or pat is not None else b.level
        old = self._self_drive.pat.get(proto.ALL_TOYS) if self._self_drive else None
        pats = ({proto.ALL_TOYS: friend_patterns.anchor(pat, old, time.monotonic())}
                if pat is not None else {})
        self._self_drive = Drive({proto.ALL_TOYS: level} if level > 0 else {}, 0.0, frozenset(), pats)
        self._needs_recalculation = True

    def _self_shock(self, op: str, intensity: float, length: float,
                    warn_ms: int, warn_intensity: float) -> None:
        """Both of us on your own shockers: through your own engine, inside
        your own caps and arming, a warning first like a friend's."""
        eng = getattr(self, "pishock_engine", None)
        why = self._shock_blocked(SELF, eng)
        if why:
            self._friends_note(f"Both of us: not on you - {why}")
            return
        msg = proto.make_shock(proto.new_id(), list(range(proto.MAX_SHOCKERS)), intensity,
                               length, op, "vibrate" if warn_ms > 0 else "", warn_intensity,
                               warn_ms or proto.WARN_MS)
        self._friend_shock_in(SELF, msg)

    def _menu_retarget(self, change) -> None:
        """Apply a change to what is selected, moving the menu's level off
        friends who drop out and onto friends who come in."""
        before = set(self.friends_settings.targets())
        change()
        after = set(self.friends_settings.targets())
        for peer in before - after:
            self._menu_apply(peer, clear=True)
        for peer in after - before:
            self._menu_apply(peer)

    # ------------------------------------------------------------------
    # Whether the avatar you're wearing has the menu
    # ------------------------------------------------------------------

    def get_avatar_menu(self) -> Dict[str, bool]:
        """Which parts of OGP's avatar menu the current avatar carries, from
        the parameters VRChat lists for it: `known` (VRChat told us
        anything), `self` (OGP/Strength -- your own controls) and `friends`
        (OGP/Friend/Level -- the Friends menu)."""
        own, friends = store.has_parameters(OGP_STRENGTH_PARAMETER, OGP_FRIEND_LEVEL_PARAMETER)
        return {"known": store.parameter_count() > 0, "self": own, "friends": friends}

    def _note_avatar_menu(self) -> None:
        """Say so in the log when the avatar starts (or stops) carrying the
        Friends menu -- on every avatar change VRChat lists the new one's
        parameters."""
        menu = self.get_avatar_menu()
        if not menu["known"]:
            return
        has = menu["friends"]
        if has != getattr(self, "_avatar_has_friends_menu", None):
            if has:
                self._friends_note("Your avatar has the OGP Friends menu - you can control "
                                   "friends from VRChat")
            elif getattr(self, "_avatar_has_friends_menu", None) is not None:
                self._friends_note("This avatar has no OGP Friends menu")
            self._avatar_has_friends_menu = has


def _menu_mode(value: Any) -> int:
    try:
        return max(0, min(len(friend_patterns.WAVES), int(value)))
    except (TypeError, ValueError):
        return 0


def _menu_wave(mode: int) -> str:
    return friend_patterns.WAVES[mode - 1] if mode else ""


def _menu_pattern(mode: int, speed: float, rng: float, level: float) -> Optional[tuple]:
    """The auto mode a menu's Mode / Speed / Range ask for: up to Range
    (from 0), or for Oscillate a swing of Range around the Level radial."""
    if not mode:
        return None
    wave = _menu_wave(mode)
    if wave == "osc":
        lo, hi = level - rng / 2, level + rng / 2
    else:
        lo, hi = 0.0, rng
    return friend_patterns.clean(wave, friend_patterns.menu_period(wave, speed),
                                 max(0.0, lo), min(1.0, hi))
