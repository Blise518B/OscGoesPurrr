"""Suits facade mixin — the Suits page: a bHaptics suit over Bluetooth and an
OWO suit through the My OWO app, both reading one body (body_map.py).

Each suit sits behind its own switch (Settings → Features, both off by
default — this edition is toys-first, and someone without a suit never
meets the page). The UI talks to the engines, the router and the persisted
settings only through these methods.

Assumes the host controller (OscGoesPurrrApp) has `self.thread_queue`,
`self.get_feature_enabled()`, `self.get_master_scale()`,
`self._get_sps_source_map()`, `self.ui` and `self.log_message`. Owns
`self.suits_settings`, `self.bhaptics_engine`, `self.owo_engine` and
`self.suits_router`.
"""

from typing import Any, Dict, List

import body_map
from bhaptics_engine import BHapticsEngine
from owo_engine import OwoEngine
from parameter_store import store
from settings.suits import SuitsSettingsManager
from suits_router import SuitsRouter
import vrchat_avatars

FEATURE_BHAPTICS = "feature_bhaptics"
FEATURE_OWO = "feature_owo"

# What the page's bHaptics Test sends: a gentle buzz on every dot of one
# position, this long.
TEST_HOLD_S = 0.6
# The OWO Test button: one short pulse, capped again by the engine.
OWO_TEST_INTENSITY = 10


class SuitsFacade:
    """Mixin: Suits controller surface. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Lifecycle — main.py calls init in _setup_components, shutdown on quit
    # ------------------------------------------------------------------

    def _suits_init(self) -> None:
        self.suits_settings = SuitsSettingsManager()
        log = lambda m: self.thread_queue.put(("ui_update", m))  # noqa: E731
        state = lambda: self.thread_queue.put(("suits_state", None))  # noqa: E731
        self.bhaptics_engine = BHapticsEngine(log=log)
        self.bhaptics_engine.set_state_callback(state)
        self.owo_engine = OwoEngine(log=log)
        self.owo_engine.set_state_callback(state)
        # switched off last time (Home's On / Off): still off
        if not self.suits_settings.bhaptics()["enabled"]:
            self.bhaptics_engine.set_paused(True)
        if not self.suits_settings.owo()["enabled"]:
            self.owo_engine.set_paused(True)
        self._owo_push_config()
        self.suits_router = SuitsRouter(
            self.bhaptics_engine, self.owo_engine,
            get_master_scale=self.get_master_scale,
            get_sps_sources=getattr(self, "_get_sps_source_map", None))
        self._suits_push_config()
        if self.get_feature_enabled(FEATURE_BHAPTICS):
            self.bhaptics_engine.start(self.suits_settings.bhaptics()["auto_connect"])
        if self.get_feature_enabled(FEATURE_OWO):
            self.owo_engine.start(self.suits_settings.owo()["auto_connect"])
        self._suits_router_follow()

    def _suits_router_follow(self) -> None:
        """The router runs while either suit is switched on."""
        if (self.get_feature_enabled(FEATURE_BHAPTICS)
                or self.get_feature_enabled(FEATURE_OWO)):
            self.suits_router.start()
        else:
            self.suits_router.stop()

    def _suits_push_config(self) -> None:
        self.suits_router.configure(
            self.suits_settings.snapshot(),
            bhaptics_on=self.get_feature_enabled(FEATURE_BHAPTICS),
            owo_on=self.get_feature_enabled(FEATURE_OWO))

    def _owo_push_config(self) -> None:
        o = self.suits_settings.owo()
        self.owo_engine.set_host(o["host"])
        self.owo_engine.set_game_id(o["game_id"])
        self.owo_engine.set_caps({m: c["max"] for m, c in o["muscles"].items()},
                                 o["global_max"])

    def _suits_shutdown(self) -> None:
        if getattr(self, "suits_router", None) is None:
            return
        self.suits_router.stop()
        self.owo_engine.stop()
        self.bhaptics_engine.stop()

    def _bhaptics_feature_changed(self, enabled: bool) -> None:
        if enabled:
            self.bhaptics_engine.start(self.suits_settings.bhaptics()["auto_connect"])
        else:
            self.bhaptics_engine.stop()
            self.log_message("bHaptics off — suit let go")
        self._suits_push_config()
        self._suits_router_follow()

    def _owo_feature_changed(self, enabled: bool) -> None:
        if enabled:
            self._owo_push_config()
            self.owo_engine.start(self.suits_settings.owo()["auto_connect"])
        else:
            self.owo_engine.stop()
            self.log_message("OWO off — stopped and let go of My OWO")
        self._suits_push_config()
        self._suits_router_follow()

    def _suits_on_osc(self, address: str) -> None:
        """OSC receive thread: wake the router for a parameter the body reads."""
        router = getattr(self, "suits_router", None)
        if router is not None:
            router.notify(address)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_suits_status(self) -> Dict[str, Any]:
        """Each suit's engine state, with its saved settings under
        "settings" (the engine's "devices" / "host" are what's connected;
        the settings' are what the page edits)."""
        bh = self.bhaptics_engine.status_snapshot()
        bh["settings"] = self.suits_settings.bhaptics()
        bh["feature"] = self.get_feature_enabled(FEATURE_BHAPTICS)
        owo = self.owo_engine.status_snapshot()
        owo["settings"] = self.suits_settings.owo()
        owo["feature"] = self.get_feature_enabled(FEATURE_OWO)
        return {"bhaptics": bh, "owo": owo,
                "output_off": bool(self.get_master_scale() <= 0.0)}

    def get_suits_live(self) -> Dict[str, Any]:
        """For the page's body picture and level readouts."""
        live = self.suits_router.live()
        live["dots"] = self.bhaptics_engine.output_snapshot()
        live["owo_sending"] = self.owo_engine.status_snapshot()["active"]
        return live

    def get_suits_detected(self) -> Dict[str, Any]:
        """The worn avatar's suit contacts, for the page's check: every
        parameter VRChat's file lists for it (touched or not), plus what
        it has sent. "source" says where that came from: "file", "osc"
        (no file: only what was sent so far) or "" (nothing to check yet)."""
        params = store.get_all_parameters() or {}
        get_id = getattr(self, "get_current_avatar_id", None)
        listed = vrchat_avatars.avatar_parameters(get_id()) if get_id is not None else None
        names = set(params) | set(listed or ())
        return {"positions": sorted(body_map.detected_positions(dict.fromkeys(names))),
                "owo": sorted(body_map.detected_owo(dict.fromkeys(names))),
                "contacts": body_map.contacts_per_position(names),
                "source": "file" if listed is not None else ("osc" if params else "")}

    # ------------------------------------------------------------------
    # bHaptics
    # ------------------------------------------------------------------

    def bhaptics_connect(self) -> None:
        self.bhaptics_engine.connect()

    def bhaptics_release(self) -> None:
        self.bhaptics_engine.release()
        self.log_message("bHaptics let go — the bHaptics Player or a game can have it now")

    def set_bhaptics_option(self, key: str, value: Any) -> None:
        self.suits_settings.set_bhaptics_option(key, value)
        self._suits_push_config()

    def set_bhaptics_device(self, position: str, **changes) -> None:
        self.suits_settings.set_bhaptics_device(position, **changes)
        self._suits_push_config()

    def set_bhaptics_have(self, group: str, have: bool) -> None:
        """The page's You have: a part group (body_map.PART_GROUPS) you own
        or not. Only changes what the page shows."""
        current = self.suits_settings.bhaptics()["have"]
        wanted = (current + [group]) if have else [g for g in current if g != group]
        self.suits_settings.set_bhaptics_option("have", wanted)

    def _suits_note_connected(self) -> None:
        """A suit's state changed (UI thread): a part that just connected is
        one you have, so it shows on the page from now on. Only a new
        connection counts -- a part you took off You have while it stays
        connected isn't put back at its next battery reading."""
        if getattr(self, "suits_settings", None) is None:
            return
        positions = {p for d in (self.bhaptics_engine.status_snapshot().get("devices") or [])
                     for p in d.get("positions") or []}
        fresh = positions - getattr(self, "_suits_connected_seen", set())
        self._suits_connected_seen = positions
        added = self.suits_settings.add_bhaptics_have(fresh)
        if added:
            self.log_message(f"bHaptics: {', '.join(added)} connected — "
                             "now on the Suits page")

    def bhaptics_test(self, position: str) -> bool:
        if not self.bhaptics_engine.is_connected:
            self.log_message("bHaptics: connect the suit before testing.")
            return False
        if self.get_master_scale() <= 0.0:
            self.log_message("bHaptics test held back: output is Off.")
            return False
        self.suits_router.hold_position(position, TEST_HOLD_S)
        return True

    def bhaptics_stop_all(self) -> None:
        """Home's switch to Off: the suit to zero now, and held there --
        across restarts too -- until it is switched on."""
        self.bhaptics_engine.set_paused(True)
        self.suits_settings.set_bhaptics_enabled(False)
        self.log_message("bHaptics off — switch it on to feel it again")

    def bhaptics_resume(self) -> None:
        self.bhaptics_engine.set_paused(False)
        self.suits_settings.set_bhaptics_enabled(True)
        self.log_message("bHaptics on")

    def bhaptics_hold_dot(self, position: str, index: int, held: bool) -> None:
        """The body picture: press a dot to feel it, let go to stop."""
        self.suits_router.hold_dot(position, index, 5.0 if held else None)

    # ------------------------------------------------------------------
    # OWO
    # ------------------------------------------------------------------

    def owo_connect(self) -> None:
        self._owo_push_config()
        self.owo_engine.connect()

    def owo_disconnect(self) -> None:
        self.owo_engine.disconnect()

    def set_owo_option(self, key: str, value: Any) -> None:
        self.suits_settings.set_owo_option(key, value)
        self._owo_push_config()
        self._suits_push_config()

    def set_owo_muscle(self, muscle: str, **changes) -> None:
        self.suits_settings.set_owo_muscle(muscle, **changes)
        self._owo_push_config()
        self._suits_push_config()

    def owo_stop_all(self) -> None:
        """The page's Stop all, Home's switch to Off: end everything now
        and hold it stopped -- across restarts too -- until Resume / On."""
        self.owo_engine.set_paused(True)
        self.suits_settings.set_owo_enabled(False)
        self.log_message("OWO off — switch it on to feel it again")

    def owo_resume(self) -> None:
        self.owo_engine.set_paused(False)
        self.suits_settings.set_owo_enabled(True)
        self.log_message("OWO on")

    def owo_test(self, muscle: str) -> bool:
        eng = self.owo_engine
        if not eng.is_connected:
            self.log_message("OWO: connect to My OWO before testing.")
            return False
        if self.get_master_scale() <= 0.0:
            self.log_message("OWO test held back: output is Off.")
            return False
        ok = eng.test_pulse(muscle, OWO_TEST_INTENSITY)
        if ok:
            self.log_message(f"OWO test: {body_map.display_name(muscle)} at "
                             f"{OWO_TEST_INTENSITY} % (or its ceiling, if lower)")
        else:
            self.log_message("OWO test held back (stopped, or that muscle's ceiling is 0).")
        return ok

    # ------------------------------------------------------------------
    # Zone routes (shared by both suits)
    # ------------------------------------------------------------------

    def get_suit_routes(self) -> List[Dict[str, Any]]:
        return self.suits_settings.routes()

    def add_suit_route(self) -> int:
        idx = self.suits_settings.add_route()
        self._suits_push_config()
        return idx

    def set_suit_route(self, index: int, route: Dict[str, Any]) -> None:
        self.suits_settings.set_route(index, route)
        self._suits_push_config()

    def delete_suit_route(self, index: int) -> None:
        self.suits_settings.delete_route(index)
        self._suits_push_config()
