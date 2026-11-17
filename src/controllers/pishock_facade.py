"""Shocker facade mixin — the Shockers page: a PiShock or OpenShock hub on
USB.

Behind the `feature_pishock` switch (Settings → Features, off by default —
this edition is toys-first, and a stranger who has no shocker never sees
the page). The UI talks to the engine, the router and the persisted
settings only through these methods.

Assumes the host controller (OscGoesPurrrApp) has `self.thread_queue`,
`self.is_output_off()`, `self.get_feature_enabled()`, `self.ui` and
`self.log_message`. Owns `self.pishock_settings`, `self.pishock_engine`
and `self.pishock_router`.
"""

from typing import Any, Dict, List, Optional

import openshock_serial
import pishock_serial
from pishock_engine import PiShockEngine
from pishock_limits import RANGES
from pishock_router import PiShockRouter
from settings.pishock import PiShockSettingsManager

from .shockosc_facade import ShockOscFacade

FEATURE_KEY = "feature_pishock"

# What the page's test buttons send: gentle and short, whatever the rules say.
TEST_INTENSITY = 10
TEST_DURATION_MS = 500


class PiShockFacade(ShockOscFacade):
    """Mixin: PiShock controller surface. Composed into OscGoesPurrrApp.
    ShockOSC's setup and feedback ride along (shockosc_facade.py)."""

    # ------------------------------------------------------------------
    # Lifecycle — main.py calls init in _setup_components, shutdown on quit
    # ------------------------------------------------------------------

    def _pishock_init(self) -> None:
        self.pishock_settings = PiShockSettingsManager()
        self.pishock_engine = PiShockEngine(
            log=lambda m: self.thread_queue.put(("ui_update", m)))
        self.pishock_engine.set_state_callback(
            lambda: self.thread_queue.put(("pishock_state", None)))
        if not self.pishock_settings.get_enabled():
            self.pishock_engine.set_paused(True)     # switched off last time
        self._pishock_push_config()
        # Arm shocks is remembered (Blise's call, 2026-10-28)
        self.pishock_engine.set_armed(self.pishock_settings.get_armed())
        self.pishock_router = PiShockRouter(
            self.pishock_engine,
            get_rules=self.pishock_settings.get_all_rules,
            is_output_off=self.is_output_off,
            report=getattr(self, "_log_avatar_shock", None))   # the log (LogFacade)
        self._shockosc_init()
        if self.get_feature_enabled(FEATURE_KEY):
            self._pishock_start()

    def _pishock_start(self) -> None:
        self.pishock_router.start()
        self.pishock_engine.start(self.pishock_settings.get_auto_connect())
        self._shockosc_start()

    def _pishock_stop(self) -> None:
        self.pishock_router.stop()
        self.pishock_engine.stop()
        self._shockosc_stop()

    def _pishock_shutdown(self) -> None:
        if getattr(self, "pishock_engine", None) is not None:
            self._pishock_stop()

    def _pishock_feature_changed(self, enabled: bool) -> None:
        if enabled:
            self._pishock_start()
        else:
            self._pishock_stop()
            self.log_message("Shockers off — hub let go")

    def _pishock_on_osc(self, address: str) -> None:
        """OSC receive thread: wake the router for a watched parameter."""
        router = getattr(self, "pishock_router", None)
        if router is not None:
            router.notify(address)

    def _pishock_push_config(self) -> None:
        s = self.pishock_settings
        self.pishock_engine.set_port(s.get_port())
        self.pishock_engine.set_limits(**s.get_limits())
        self.pishock_engine.set_separate_limits(s.get_separate_limits(), s.get_friend_limits())
        self.pishock_engine.set_shocker_limits(s.get_shocker_limits())
        self.pishock_engine.set_openshock_shockers(s.get_openshock_shockers())
        self.pishock_engine.set_shockers_off(s.get_shockers_off())
        self.pishock_engine.set_ops_off(s.get_shocker_ops_off())
        self.pishock_engine.set_shocker_names(s.get_shocker_names())

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_pishock_status(self) -> Dict[str, Any]:
        eng = self.pishock_engine
        s = self.pishock_settings
        return {
            "available": eng.is_available,
            "connected": eng.is_connected,
            "connecting": eng.is_connecting,
            "last_error": eng.last_error or "",
            "port": eng.port,
            "port_setting": s.get_port(),
            "hub_kind": eng.hub_kind,
            "firmware": eng.firmware,
            "board": eng.board,
            "shockers": eng.shockers(),          # in use: Home, friends
            "all_shockers": eng.all_shockers(),  # the page: switched-off ones too
            "shockers_off": s.get_shockers_off(),
            # each shocker's Shock / Vibrate / Beep switched off, by id
            "ops_off": s.get_shocker_ops_off(),
            "openshock_shockers": s.get_openshock_shockers(),
            "shocker_names": s.get_shocker_names(),
            "armed": eng.is_armed,
            "paused": eng.is_paused,
            "output_off": bool(self.is_output_off()),
            "auto_connect": s.get_auto_connect(),
            "friends_may_use": s.get_friends_may_use(),
            "limits": s.get_limits(),
            # Separate limits for friends: on, friends keep to their own
            # rest, longest hold and forced break (the Limits box's second set)
            "separate_limits": s.get_separate_limits(),
            "friend_limits": s.get_friend_limits(),
            # each shocker's caps as they apply (its own, else the hub's), by
            # id -- the hub's shockers and the OpenShock list alike
            "shocker_limits": {str(sid): s.shocker_limits_for(sid) for sid in
                               {*(x["id"] for x in eng.all_shockers()),
                                *(o["id"] for o in s.get_openshock_shockers())}},
            "ranges": dict(RANGES),          # every limit's (lowest, highest, default)
            "hub_name": pishock_serial.HUB_NAMES.get(eng.hub_kind, ""),
        }

    def get_pishock_live(self) -> Dict[str, Any]:
        """For the page's live readouts: the watched parameters' current
        values and what each shocker is doing right now."""
        return {
            "values": self.pishock_router.live_values(),
            "outputs": self.pishock_engine.output_snapshot(),
        }

    def list_pishock_ports(self) -> List[Dict[str, Any]]:
        return pishock_serial.list_ports()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def pishock_connect(self) -> None:
        self._pishock_push_config()
        self.pishock_engine.connect()

    def pishock_disconnect(self) -> None:
        self.pishock_engine.disconnect()

    def set_pishock_port(self, port: str) -> None:
        self.pishock_settings.set_port(port)
        self._pishock_push_config()

    def set_pishock_auto_connect(self, enabled: bool) -> None:
        self.pishock_settings.set_auto_connect(bool(enabled))

    # ------------------------------------------------------------------
    # OpenShock shockers (an OpenShock hub keeps no list of its own)
    # ------------------------------------------------------------------

    @staticmethod
    def openshock_models() -> tuple:
        return openshock_serial.MODELS

    def get_openshock_shockers(self) -> List[Dict[str, Any]]:
        return self.pishock_settings.get_openshock_shockers()

    def add_openshock_shocker(self) -> int:
        idx = self.pishock_settings.add_openshock_shocker()
        self._pishock_push_config()
        self._pishock_presence_follow()
        return idx

    def set_openshock_shocker(self, index: int, shocker: Dict[str, Any]) -> None:
        self.pishock_settings.set_openshock_shocker(index, shocker)
        self._pishock_push_config()
        self._pishock_presence_follow()

    def delete_openshock_shocker(self, index: int) -> None:
        self.pishock_settings.delete_openshock_shocker(index)
        self._pishock_push_config()
        self._pishock_presence_follow()

    def _pishock_presence_follow(self) -> None:
        """The page's OpenShock list changed: its shockers' "connected"
        avatar parameters follow (presence_facade) -- also while the hub is
        unplugged, when no state change would say so."""
        sync = getattr(self, "presence_sync", None)
        if sync is not None:
            sync()

    def set_pishock_shocker_name(self, shocker_id, name: str) -> None:
        """Your name for a shocker the hub reports by id: on this page, in
        the rules and for friends (their panel shows it)."""
        self.pishock_settings.set_shocker_name(shocker_id, name)
        self.pishock_engine.set_shocker_names(self.pishock_settings.get_shocker_names())

    def set_pishock_shocker_on(self, shocker_id, on: bool) -> None:
        """A shocker's own On / Off (its card): off, it is stopped, the
        engine sends it nothing, and behaviours, friends and Home leave it
        out -- remembered across launches."""
        self.pishock_settings.set_shocker_on(shocker_id, on)
        self.pishock_engine.set_shockers_off(self.pishock_settings.get_shockers_off())
        name = self.pishock_settings.get_shocker_names().get(str(shocker_id)) or f"Shocker {shocker_id}"
        self.log_message(f"Shockers: {name} {'in use again' if on else 'switched off - not in use'}")
        self._pishock_redraw()

    def set_pishock_shocker_op(self, shocker_id, op: str, on: bool) -> None:
        """One shocker's Shock, Vibrate or Beep switch (its card): off, the
        engine refuses that op on it whoever sends it -- behaviours, friends,
        the web remote, the menu -- and stops one that is running. Friends'
        panels grey that button. Remembered across launches."""
        if op not in ("shock", "vibrate", "beep"):
            return
        self.pishock_settings.set_shocker_op(shocker_id, op, on)
        self.pishock_engine.set_ops_off(self.pishock_settings.get_shocker_ops_off())
        name = self.pishock_settings.get_shocker_names().get(str(shocker_id)) or f"Shocker {shocker_id}"
        self.log_message(f"Shockers: {name} - {op} {'on' if on else 'switched off'}")
        self._pishock_redraw()

    def _pishock_redraw(self) -> None:
        """A setting the page and Home both show changed: both redraw on
        the main thread (_pishock_state_changed) -- whichever of them it
        was changed on."""
        try:
            self.thread_queue.put(("pishock_state", None))
        except Exception:
            pass

    def _pishock_state_changed(self) -> None:
        """Main thread, for a "pishock_state" on the queue: the hub, its
        shocker list or one of the switches changed. The Shockers page and
        Home's shocker row redraw from get_pishock_status() -- the one
        place the switches are kept."""
        ui = getattr(self, "ui", None)
        for name in ("refresh_pishock_status", "refresh_home_devices"):
            refresh = getattr(ui, name, None)
            if callable(refresh):
                refresh()
        # a shocker's name or the hub changed: which shocker a ShockOSC
        # group without a behaviour lights up may have too
        self._shockosc_follow()

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def set_pishock_limit(self, key: str, value) -> None:
        """A hub-wide limit: the shared timing, or a cap every shocker
        without its own takes."""
        self.pishock_settings.set_limit(key, value)
        self._pishock_push_config()

    def set_pishock_separate_limits(self, on: bool) -> None:
        """Separate limits for friends: on, friends (Me and the web remote
        too) keep to a timing of their own -- the rest after a pulse, the
        longest hold and the forced break -- counted apart from your
        avatar's, and to their own max shock, max vibrate and longest pulse,
        which only lower each shocker's own for them; off, one set and one
        count for everyone. Arming and the switches stay shared either way."""
        self.pishock_settings.set_separate_limits(bool(on))
        self._pishock_push_config()
        self.log_message("Shockers: separate limits for friends " + ("on" if on else "off"))
        self._pishock_redraw()

    def set_pishock_friend_limit(self, key: str, value) -> None:
        """One of the friends' own limits (while separate): a cap or the
        timing."""
        self.pishock_settings.set_friend_limit(key, value)
        self._pishock_push_config()

    def set_pishock_shocker_limit(self, shocker_id, key: str, value) -> None:
        """One shocker's own max shock, max vibrate or longest pulse."""
        self.pishock_settings.set_shocker_limit(shocker_id, key, value)
        self._pishock_push_config()

    def set_pishock_armed(self, armed: bool) -> None:
        """Arm shocks -- the Shockers page's switch and Home's are this one
        setting (ui/views/shocker_switches.py)."""
        self.pishock_engine.set_armed(bool(armed))
        self.pishock_settings.set_armed(bool(armed))      # remembered
        self.log_message("Shockers: shocks ARMED" if armed
                         else "Shockers: shocks disarmed — shock rules vibrate")
        self._pishock_redraw()

    def pishock_stop_all(self) -> None:
        """The page's Stop all, Home's switch to Off: end everything now
        and hold it stopped -- across restarts too -- until Resume / On.
        Friends stop seeing your shockers too."""
        self.pishock_engine.set_paused(True)
        self.pishock_settings.set_enabled(False)
        self._pishock_drop_friend_shocks()
        self.log_message("Shockers off — nothing reaches them until you switch them on")
        self._pishock_redraw()

    def _pishock_drop_friend_shocks(self) -> None:
        """What friends already sent (a warned shock, a hold) never comes."""
        drop = getattr(self, "_drop_shocks", None)
        if drop is None:
            return
        for peer in list(getattr(self, "_friend_perms", {}) or {}):
            drop(peer)

    def pishock_resume(self) -> None:
        self.pishock_engine.set_paused(False)
        self.pishock_settings.set_enabled(True)
        self.log_message("Shockers on")
        self._pishock_redraw()

    def set_pishock_friends_may_use(self, value: bool) -> None:
        """"Share with friends" (Home's shocker row and the Shockers page):
        one switch for every friend, on top of each friend's own Shockers
        switch -- off, friends don't see your shockers at all. Off also
        drops what a friend has already sent (a warned shock never comes)."""
        value = bool(value)
        if value == self.pishock_settings.get_friends_may_use():
            return
        self.pishock_settings.set_friends_may_use(value)
        if not value:
            self._pishock_drop_friend_shocks()
        self._pishock_redraw()
        note = getattr(self, "_friends_note", None)
        if note is not None:
            note("Friends may use your shockers again" if value
                 else "Your shockers are no longer shared with friends", kind="settings",
                 op="allow" if value else "deny")

    def pishock_test(self, op: str, shocker: Optional[int] = None) -> bool:
        """One gentle, short test op on every shocker, or on one (the
        OpenShock list's Beep, which is also how a collar in pairing mode
        learns its id). Goes through every engine rule (arming, cooldown,
        pause) like any other send."""
        eng = self.pishock_engine
        if not eng.is_connected:
            self.log_message("Shockers: connect the hub before testing.")
            return False
        ids = eng.shocker_ids() if shocker is None else [
            sid for sid in eng.shocker_ids() if sid == shocker]
        switched = [sid for sid in ids if not eng.op_allowed(sid, op)]
        if ids and len(switched) == len(ids):
            self.log_message(f"Shocker test: {op} is switched off on "
                             f"{'that shocker' if shocker is not None else 'every shocker'}.")
            return False
        fired = [sid for sid in ids if sid not in switched
                 if eng.pulse(sid, op, TEST_INTENSITY, TEST_DURATION_MS)]
        if fired:
            sent = op if op != "shock" or eng.is_armed else "vibrate (shocks not armed)"
            self.log_message(f"Shocker test: {sent} at {TEST_INTENSITY} "
                             f"on {', '.join(str(s) for s in fired)}")
        elif shocker is not None and not ids:
            self.log_message(f"Shocker test: {shocker} isn't on the connected hub.")
        else:
            self.log_message("Shocker test held back (stopped, or cooling down).")
        return bool(fired)

    # ------------------------------------------------------------------
    # Rules
    # ------------------------------------------------------------------

    def get_pishock_rules(self, kind: str) -> List[Dict[str, Any]]:
        return self.pishock_settings.get_rules(kind)

    def add_pishock_rule(self, kind: str) -> int:
        idx = self.pishock_settings.add_rule(kind)
        self.pishock_router.rules_changed()
        self._shockosc_follow()
        return idx

    def set_pishock_rule(self, kind: str, index: int, rule: Dict[str, Any]) -> None:
        before = self.pishock_settings.get_rules(kind)
        old = before[index] if 0 <= index < len(before) else {}
        self.pishock_settings.set_rule(kind, index, rule)
        self.pishock_router.rules_changed()
        self._shockosc_follow()
        # a ShockOSC behaviour's value: the others with the same avatar
        # parameter follow, and the avatar hears it (shockosc_sync)
        after = self.pishock_settings.get_rules(kind)
        if old and 0 <= index < len(after):
            self._shockosc_rule_edited(kind, index, old, after[index])

    def delete_pishock_rule(self, kind: str, index: int) -> None:
        self.pishock_settings.delete_rule(kind, index)
        self.pishock_router.rules_changed()
        self._shockosc_follow()
