"""The PlayStation VR2 facade mixin -- the headset's rumble motor through
the user's own PSVR2Toolkit (ported from the full edition).

Behind `feature_psvr2`, off by default, and Windows only like the toolkit
(main.OscGoesPurrrApp.FEATURES_WINDOWS_ONLY hides it elsewhere). The UI
talks to the engine, the router and the persisted settings only through
these methods.

Assumes the host controller (OscGoesPurrrApp) has `self.thread_queue`,
`self.get_feature_enabled()`, `self.get_master_scale()` and
`self.log_message`; and, when there, `self.get_ogp_test_level()` and
`self._get_toy_antistuck()` (the toys' anti-stuck, which the headset's own
starts as, once). Owns `self.psvr2_settings`,
`self.psvr2_engine` and `self.psvr2_router`.
"""

from typing import Any, Dict, List

from parameter_store import store
from psvr2_engine import PSVR2Engine
from psvr2_router import PSVR2Router
from settings.psvr2 import PSVR2SettingsManager

FEATURE_PSVR2 = "feature_psvr2"


class PSVR2Facade:
    """Mixin: PSVR2-related controller methods. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Lifecycle -- main.py calls init in _setup_components, shutdown on quit
    # ------------------------------------------------------------------

    def _psvr2_new_engine(self, **kw) -> PSVR2Engine:
        """The engine on the real toolkit (tests hand in a fake CAPI)."""
        return PSVR2Engine(**kw)

    def _psvr2_init(self) -> None:
        self.psvr2_settings = PSVR2SettingsManager()
        toys = getattr(self, "_get_toy_antistuck", None)
        if callable(toys):
            # its own anti-stuck since 2026-11-17: it starts as the toys' was
            self.psvr2_settings.seed_antistuck(toys())
        self.psvr2_engine = self._psvr2_new_engine(
            get_output_config=self.psvr2_settings.get_output,
            log=lambda m: self.thread_queue.put(("ui_update", m)))
        self.psvr2_engine.set_auto_connect_getter(self.psvr2_settings.get_auto_connect)
        if not self.psvr2_settings.get_enabled():
            self.psvr2_engine.set_paused(True)        # switched off last time
        self.psvr2_router = PSVR2Router(
            self.psvr2_engine,
            get_contact_config=self.psvr2_settings.get_contact,
            get_master_scale=self.get_master_scale,
            get_test_level=getattr(self, "get_ogp_test_level", None),
            get_antistuck=self.psvr2_settings.get_antistuck)
        self.psvr2_router.configure()

        def state_changed() -> None:
            # engine threads: the router ticks at the new pace now, the UI
            # and the "connected" parameter hear it on the main thread
            self.psvr2_router.wake()
            self.thread_queue.put(("psvr2_state", None))
        self.psvr2_engine.set_state_callback(state_changed)
        if self.get_feature_enabled(FEATURE_PSVR2):
            self._psvr2_start()

    def _psvr2_start(self) -> None:
        self.psvr2_engine.start()
        self.psvr2_router.start()

    def _psvr2_shutdown(self) -> None:
        """Quit: the motor's last command is a 0 (the engine's _close)."""
        router = getattr(self, "psvr2_router", None)
        if router is not None:
            router.stop()
        eng = getattr(self, "psvr2_engine", None)
        if eng is not None:
            eng.stop()

    def _psvr2_feature_changed(self, enabled: bool) -> None:
        if enabled:
            self._psvr2_start()
        else:
            self.psvr2_router.stop()
            self.psvr2_engine.stop()
            self.log_message("PSVR2 off — headset motor stopped, toolkit let go")

    def _psvr2_on_osc(self, address: str) -> None:
        """OSC receive thread: wake the router for the headset's contact."""
        router = getattr(self, "psvr2_router", None)
        if router is not None:
            router.notify(address)

    # ------------------------------------------------------------------
    # UI-facing API
    # ------------------------------------------------------------------

    def get_psvr2_status(self) -> Dict[str, Any]:
        s = self.psvr2_settings
        eng = self.psvr2_engine
        return {
            "feature": self.get_feature_enabled(FEATURE_PSVR2),
            "available": eng.is_available,
            "connected": eng.is_connected,
            "paused": eng.is_paused,
            "last_error": eng.last_error,
            "auto_connect": s.get_auto_connect(),
            "output": s.get_output(),
            "contact": s.get_contact(),
            "antistuck": s.get_antistuck(),
            "extras": eng.get_status_extras(),
            "output_off": bool(self.get_master_scale() <= 0.0),
        }

    def set_psvr2_auto_connect(self, enabled: bool) -> None:
        self.psvr2_settings.set_auto_connect(bool(enabled))

    def set_psvr2_output(self, cfg: Dict[str, Any]) -> None:
        self.psvr2_settings.set_output(cfg)

    def set_psvr2_contact(self, cfg: Dict[str, Any]) -> None:
        """The contact receiver that drives the headset (enabled,
        parameter, threshold, gain); a partial dict changes only those."""
        merged = dict(self.psvr2_settings.get_contact())
        merged.update(cfg or {})
        self.psvr2_settings.set_contact(merged)
        self.psvr2_router.configure()

    def get_psvr2_antistuck(self) -> Dict[str, Any]:
        """The headset's own anti-stuck: `{enabled, active_s, peaked_s}`."""
        return self.psvr2_settings.get_antistuck()

    def set_psvr2_antistuck(self, **changes) -> None:
        """Change the headset's anti-stuck; the router reads it every tick."""
        self.psvr2_settings.set_antistuck(**changes)
        self.psvr2_router.wake()

    def get_psvr2_live(self) -> Dict[str, Any]:
        """For the page's routing card: the contact's live value (after
        its anti-stuck), the level sent and the frequency the motor holds."""
        live = self.psvr2_router.live()
        live["rumble_hz"] = self.psvr2_engine.get_status_extras().get("rumble_hz")
        return live

    def get_psvr2_contact_found(self) -> Any:
        """Whether the worn avatar has the headset's contact: True /
        False, or None while there's nothing to check against yet (VRChat's
        list of the avatar's parameters, plus what it has sent)."""
        name = self.psvr2_settings.get_contact().get("parameter", "")
        if not name:
            return None
        names = self._psvr2_avatar_names()
        return None if names is None else name in names

    def _psvr2_avatar_names(self):
        import vrchat_avatars
        params = store.get_all_parameters() or {}
        get_id = getattr(self, "get_current_avatar_id", None)
        listed = vrchat_avatars.avatar_parameters(get_id()) if get_id is not None else None
        if listed is None and not params:
            return None
        return set(params) | set(listed or ())

    def psvr2_connect_now(self) -> bool:
        """Blocking (init reaches into shared memory) -- the UI runs it off
        the Qt thread."""
        return self.psvr2_engine.manual_connect()

    def psvr2_test_pulse(self) -> bool:
        """Buzz the headset at the top of the band for a moment. The one way
        to confirm the whole chain -- toolkit, driver and the headset's
        jailbreak -- without an avatar. Held back while output is Off or the
        headset is switched off."""
        if self.get_master_scale() <= 0.0:
            self.log_message("PSVR2 test held back: output is Off.")
            return False
        ok = self.psvr2_engine.test_pulse()
        if not ok:
            self.log_message("PSVR2 test held back: the headset is switched "
                             "off or not connected.")
        return ok

    def psvr2_stop_all(self) -> None:
        """Home's switch to Off: the motor to 0 now, and held there --
        across restarts too -- until it is switched on."""
        self.psvr2_engine.set_paused(True)
        self.psvr2_settings.set_enabled(False)
        self.log_message("PSVR2 off — switch it on to feel it again")

    def psvr2_resume(self) -> None:
        self.psvr2_engine.set_paused(False)
        self.psvr2_settings.set_enabled(True)
        self.log_message("PSVR2 on")
