"""Off while you're away — the controller side.

While VRChat says you're AFK (its own ``AFK``, or GoGo Loco's AFK button),
or a parameter you picked is on, everything is held off: the same Off as
``OGP/Off`` -- toys, shockers, suits, haptic trackers, friends' drives --
through ``ModeManager.held_off``, so the user's own Off switch is never
touched. When the last source clears, the hold lets go and exactly the
state from before comes back. On by default (decided 2026-11-14);
Settings → Safety has the card. The sources are ``away_off.py``.

Event-driven, off every routing path: the OSC thread looks each packet's
address up in ``_away_watch`` (a frozenset the GUI thread swaps whole)
and, on a watched one, puts one ``away_check`` on the queue -- at most one
waiting at a time. The GUI thread then reads the sources' values from the
parameter store (written before the packet's callback, so it is never
older than the packet) and starts or ends the hold. The store's reload
after an avatar change (``SYS/OSCQuery_Status``) re-checks too, which is
what lets a picked parameter the new avatar doesn't have go.

**VRChat closing lets go (Blise's call, 2026-11-14: "It should just be
active if you're actually AFK within VR chat and no other time").** Every
source comes from the avatar, so none of them is still true once VRChat is
gone. The signal is the OSC layer's disconnect (``osc_status`` False, from
``VRChatOSCManager._handle_disconnect``: VRChat's OSCQuery mDNS record
removed, or its OSCQuery HTTP server failing two checks 5 s apart) or the
user's own Disconnect -- never the 10 s quiet monitor, which fires while
you stand still AFK because VRChat sends nothing then. The store keeps the
last session's values, so after ``_away_vrchat_gone`` only values VRChat
says anew count (``_away_fresh``): a watched packet, or the store's reload
from VRChat's live tree ("Loaded N total parameters") -- so the hold
comes back only if the returning VRChat says AFK again.

Assumes the host has `self.mode_manager` (with `app_settings`),
`self.thread_queue`, `self.log_message`, `self.ui`, and the modes facade's
`_apply_output_change` / `_refresh_strength_ui`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import away_off
from parameter_store import store

#: The OSC layer's notice that the store was (re)loaded or VRChat came or
#: went -- values may have changed without a packet of their own.
_STORE_STATUS_ADDRESS = "SYS/OSCQuery_Status"
#: How that notice starts when the store was rebuilt from VRChat's live
#: OSCQuery tree (vrchat_osc._do_fetch_all_parameters) -- every value in it
#: is VRChat's current one. Its other lines (the OSC log, "VRChat
#: disconnected", "Waiting for ...") say nothing about the values.
_STORE_LOADED_PREFIX = "Loaded "


class AwayFacade:
    """Mixin: Off while you're away. Composed into OscGoesPurrrApp."""

    # Declared on the class so the OSC thread's lookup works before init.
    _away_watch: frozenset = frozenset()
    _away_sources: tuple = ()
    _away_reasons: Tuple[str, ...] = ()
    _away_pending = False
    #: None while every value in the store counts. After VRChat went away,
    #: the set of watched parameters VRChat has sent anew since (the OSC
    #: thread adds to it, the GUI thread only tests membership); the
    #: store's next live reload puts it back to None.
    _away_fresh = None

    def _away_init(self) -> None:
        """Compile the sources from the settings (no hold at launch: the
        store is empty until VRChat speaks)."""
        self._away_rebuild()

    # ------------------------------------------------------------------
    # OSC thread
    # ------------------------------------------------------------------

    def _away_on_osc(self, address: str, value: Any = None) -> None:
        """OSC receive thread, every packet: one set lookup. A watched
        parameter (or a store reload) queues a check, unless one waits."""
        watch = self._away_watch
        fresh = self._away_fresh
        if fresh is not None:
            # VRChat went away: only what it says anew counts. Marked here,
            # before the check is queued, so the check always sees it.
            if address == _STORE_STATUS_ADDRESS:
                if isinstance(value, str) and value.startswith(_STORE_LOADED_PREFIX):
                    self._away_fresh = None
            elif address in watch:
                fresh.add(address)
        if not watch:
            return
        if address in watch or address == _STORE_STATUS_ADDRESS:
            if not self._away_pending:
                self._away_pending = True
                self.thread_queue.put(("away_check", None))

    # ------------------------------------------------------------------
    # GUI thread
    # ------------------------------------------------------------------

    def _away_rebuild(self) -> None:
        """Recompile the sources after a settings change and check them
        at once -- a picked parameter that is already on holds now."""
        sources = away_off.compile_sources(self._away_setting)
        self._away_sources = sources
        self._away_watch = away_off.watched(sources)
        self._away_check()

    def _away_vrchat_gone(self) -> None:
        """GUI thread: VRChat closed, crashed or was disconnected by the
        user (main's ``osc_status`` False, osc_facade's Disconnect). Every
        source is the avatar's, so nothing holds any more; the store's
        values from that session stop counting until VRChat says them
        anew (see the module docstring)."""
        self._away_fresh = set()
        self._away_check(why="VRChat is gone")

    def _away_check(self, why: str = "") -> None:
        """Start or end the hold from the sources' current values."""
        # Cleared before the read: a packet landing after it queues again.
        self._away_pending = False
        sources = self._away_sources
        values = store.get_values(away_off.watched(sources)) if sources else {}
        fresh = self._away_fresh
        if fresh is not None:
            # Membership tests only: the OSC thread may add to the set.
            values = {k: v for k, v in values.items() if k in fresh}
        reasons = away_off.holding(sources, values)
        if reasons == self._away_reasons:
            return
        before = self._away_reasons
        self._away_reasons = reasons
        if self.mode_manager.set_held_off(bool(reasons)):
            self._apply_output_change()
        if reasons:
            self.log_message(away_off.status_text(reasons))
        else:
            lead = f"{why}: " if why else ""
            self.log_message(f"{lead}{', '.join(before)} over — everything "
                             "is back as it was")
        self._away_show()

    def _away_show(self) -> None:
        ui = getattr(self, "ui", None)
        show = getattr(ui, "show_away_hold", None)
        if callable(show):
            show(self.get_away_status_text())
        self._refresh_strength_ui()

    def _away_setting(self, key: str, default: Any = None) -> Any:
        return self.mode_manager.app_settings.get(key, default)

    # ------------------------------------------------------------------
    # UI-facing
    # ------------------------------------------------------------------

    def get_away_reasons(self) -> Tuple[str, ...]:
        """What holds everything off right now ("AFK", "GoGo Loco AFK", a
        picked parameter's name); empty while nothing does."""
        return self._away_reasons

    def get_away_status_text(self) -> str:
        """The status bar's words while a hold is on ("AFK: everything
        off"), else ""."""
        return away_off.status_text(self._away_reasons)

    def get_away_settings(self) -> Dict[str, Any]:
        """The card's state: the switch, the two built-in sources and the
        picked list."""
        return {
            "enabled": bool(self._away_setting(
                away_off.SETTING_ENABLED, away_off.DEFAULTS[away_off.SETTING_ENABLED])),
            "vrchat_afk": bool(self._away_setting(
                away_off.SETTING_VRCHAT, away_off.DEFAULTS[away_off.SETTING_VRCHAT])),
            "gogo_afk": bool(self._away_setting(
                away_off.SETTING_GOGO, away_off.DEFAULTS[away_off.SETTING_GOGO])),
            "params": self.get_away_params(),
        }

    _AWAY_SWITCHES = {
        "enabled": away_off.SETTING_ENABLED,
        "vrchat_afk": away_off.SETTING_VRCHAT,
        "gogo_afk": away_off.SETTING_GOGO,
    }

    def set_away_switch(self, which: str, on: bool) -> None:
        """One of the card's switches: "enabled", "vrchat_afk" or
        "gogo_afk". Takes effect at once (a source that is on holds now,
        one switched off lets go)."""
        key = self._AWAY_SWITCHES.get(which)
        if key is None:
            return
        self.mode_manager.app_settings.set(key, bool(on))
        self._away_rebuild()

    def get_away_params(self) -> List[str]:
        """The "Also off while" list, in the order picked."""
        return away_off.clean_params(self._away_setting(
            away_off.SETTING_PARAMS, away_off.DEFAULTS[away_off.SETTING_PARAMS]))

    def add_away_param(self, name: str) -> bool:
        """Add a picked parameter to "Also off while". Returns True when
        it was added (not blank, not already there)."""
        params = self.get_away_params()
        cleaned = away_off.clean_params([name])
        if not cleaned or cleaned[0] in params:
            return False
        params.append(cleaned[0])
        self.mode_manager.app_settings.set(away_off.SETTING_PARAMS, params)
        self._away_rebuild()
        return True

    def remove_away_param(self, name: str) -> None:
        params = [p for p in self.get_away_params() if p != name]
        self.mode_manager.app_settings.set(away_off.SETTING_PARAMS, params)
        self._away_rebuild()
