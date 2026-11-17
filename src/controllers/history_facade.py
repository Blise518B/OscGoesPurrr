"""History facade mixin -- Ctrl+Z / Ctrl+Y for the whole app (friends'
reviews, 2026-11-14; settings_history.py has the design).

Owns the one SettingsHistory: made and made the active one before any
settings store loads (`_history_init`, first thing in main.py), so every
store tracks itself as it loads; once every store exists, each gets its
re-apply hook (`_history_hooks`): after an undo or redo wrote old values
back into a store, the facade that owns it puts them into effect -- the
engine's caps, the router's rules, the link's permissions -- and the UI
redraws, the same as after a change by hand.

The UI's surface (ui/history_keys.py): `history_set_input` (who decides a
save was the user's, and names the control), `history_boundary`,
`history_undo` / `history_redo` (with the UI's way to ask and to replay a
control), `history_undo_action` (the Avatar Remote's own Undo strip).
Results come back as plain dicts: {"status", "text"}."""

from typing import Any, Callable, Dict, List, Optional

import settings_history
from event_log import SETTINGS
from settings.pishock import RULE_KINDS
from settings_history import Change, SettingsHistory


def _result(r: settings_history.Result) -> Dict[str, Any]:
    """`control` is the UI's own note of the control the step was made on,
    handed back so it can show the value the store got."""
    return {"status": r.status, "text": r.text,
            "control": r.step.control if r.step is not None else None}


def _heads(changes: List[Change]) -> set:
    return {str(c.path[0]) for c in changes if c.path}


class HistoryFacade:
    """Mixin: the app's Ctrl+Z history. Composed into OscGoesPurrrApp."""

    settings_history: Optional[SettingsHistory] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _history_init(self) -> None:
        """Before any store loads. Nothing is a step until the UI says who
        is at the keyboard (history_set_input): a migration's save at
        launch never is."""
        self.settings_history = SettingsHistory(gate=lambda: False)
        settings_history.activate(self.settings_history)

    def _history_hooks(self) -> None:
        """Every store exists: each gets the hook that puts an undo into
        effect. A store none of these name still undoes -- its values are
        written back and saved; only its own engine isn't told."""
        h = self.settings_history
        if h is None:
            return
        mm = self.mode_manager
        h.on_restored(mm, self._history_modes_restored)
        h.on_restored(mm.app_settings, self._history_app_restored)
        h.on_restored(mm.sps_sources, self._history_sps_restored)
        for attr, fn in (("pishock_settings", self._history_pishock_restored),
                         ("friends_settings", self._history_friends_restored),
                         ("params_settings", self._history_params_restored),
                         ("suits_settings", self._history_suits_restored),
                         ("psvr2_settings", self._history_psvr2_restored),
                         ("_session_settings", self._history_sessions_restored)):
            store = getattr(self, attr, None)
            if store is not None:
                h.on_restored(store, fn)

    # ------------------------------------------------------------------
    # The UI's surface
    # ------------------------------------------------------------------

    def history_set_input(self, gate: Callable[[], bool],
                          context: Callable[[], Dict[str, Any]]) -> None:
        """`gate()`: the user just did something in the app (a save now is
        theirs); `context()`: {"label", "control"} of what they did it on."""
        h = self.settings_history
        if h is not None:
            h.gate = gate
            h.context = context

    def history_boundary(self) -> None:
        h = self.settings_history
        if h is not None:
            h.boundary()

    def history_undo(self, ask: Optional[Callable] = None,
                     replay: Optional[Callable] = None) -> Dict[str, Any]:
        return self._history_go(True, ask, replay)

    def history_redo(self, ask: Optional[Callable] = None,
                     replay: Optional[Callable] = None) -> Dict[str, Any]:
        return self._history_go(False, ask, replay)

    def history_status(self) -> Dict[str, Any]:
        """What Ctrl+Z and Ctrl+Y would do now (labels, "" for nothing)."""
        h = self.settings_history
        if h is None:
            return {"undo": "", "redo": ""}
        undo, redo = h.steps(), h.redoable()
        return {"undo": h.label_of(undo[-1]) if undo else "",
                "redo": h.label_of(redo[-1]) if redo else ""}

    def history_undo_action(self, key: Any, ask: Optional[Callable] = None) -> Optional[Dict[str, Any]]:
        """The Avatar Remote's Undo strip: when the removal it offers is
        still the newest step, it is undone through the history (so Ctrl+Y
        brings the removal back); None when it isn't -- the strip puts it
        back itself."""
        h = self.settings_history
        steps = h.steps() if h is not None else []
        if not steps or steps[-1].action is None or steps[-1].action.key is not key:
            return None
        return self._history_go(True, ask, None)

    def _history_go(self, undo: bool, ask, replay) -> Dict[str, Any]:
        h = self.settings_history
        if h is None:
            return {"status": settings_history.NOTHING, "text": ""}

        def ask_wrap(asks, text, answer):
            return ask([{"kind": a.kind, "text": a.text} for a in asks], text,
                       lambda yes: _result(answer(bool(yes))))

        def replay_wrap(step, undo_):
            return replay(step.control, undo_)

        go = h.undo if undo else h.redo
        return _result(go(ask_wrap if ask is not None else None,
                          replay_wrap if replay is not None else None))

    # ------------------------------------------------------------------
    # Re-apply hooks: a store got old values back
    # ------------------------------------------------------------------

    def _history_modes_restored(self, changes: List[Change]) -> None:
        """Toys: chains, routing, modes, strength. What a mode switch and a
        strength change do -- the outputs re-dispatched now, the toy cards
        rebuilt (their editors read the config once, when built)."""
        heads = _heads(changes)
        reset = getattr(self, "_reset_output_caches", None)
        if reset is not None:
            reset()
        recalc = getattr(self, "force_recalculate", None)
        if callable(recalc):
            try:
                recalc(dispatch_direct=True)
            except TypeError:
                recalc()
        ui = getattr(self, "ui", None)
        if ui is not None and heads & {"wiring", "feel", "modes", "active_mode"}:
            def rebuild(u=ui):
                clear = getattr(u, "clear_device_caches", None)
                build = getattr(u, "build_stored_devices_ui", None)
                if clear is not None and build is not None:
                    clear()
                    build()
            schedule = getattr(ui, "schedule_callback", None)
            if schedule is not None:
                schedule(0, rebuild)
            else:
                rebuild()
        if heads & {"modes", "active_mode"}:
            self._refresh_mode_buttons_ui()
        if "active_mode" in heads:
            self._send_ogp_mode_out()
        if "strength" in heads:
            self._send_ogp_strength_out()
            self._refresh_strength_ui()

    def _history_app_restored(self, changes: List[Change]) -> None:
        """Settings: what each key's own switch does beyond saving it."""
        keys = _heads(changes)
        get = self.get_app_setting
        for key in sorted(keys):
            value = get(key)
            try:
                if key in getattr(self, "FEATURE_KEYS", ()):
                    self.set_feature_enabled(key, bool(value))
                elif key == "use_integrated_intiface":
                    self.set_intiface_integrated(bool(value))
                elif key == "intiface_address":
                    self.set_intiface_address(str(value or ""))
                elif key == "show_toys_in_steamvr":
                    self.set_steamvr_toys_enabled(bool(value))
                elif key == "hide_console":
                    self.apply_console_visibility()
                elif key == "auto_refresh":
                    self.auto_refresh_enabled = bool(value)
                elif key == "auto_connect":
                    self.auto_connect_enabled = bool(value)
                    if value:
                        self._ensure_auto_connect_running()
                elif key == "shocker_layout":
                    refresh = getattr(self, "_friends_refresh_ui", None)
                    if refresh is not None:
                        refresh()           # every panel takes the other buttons
                elif key.startswith("away_off"):
                    rebuild = getattr(self, "_away_rebuild", None)
                    if rebuild is not None:
                        rebuild()           # reads the settings again
            except Exception as e:
                print(f"[history] re-applying {key} failed: {e}")
        ui = getattr(self, "ui", None)
        resync = getattr(ui, "history_app_restored", None) if ui is not None else None
        if resync is not None:
            resync(sorted(keys))

    def _history_sps_restored(self, changes: List[Change]) -> None:
        self._sps_sources_changed()
        ui = getattr(self, "ui", None)
        rebuild = getattr(ui, "_rebuild_sps_sources_entries", None) if ui is not None else None
        if rebuild is not None:
            rebuild()

    def _history_pishock_restored(self, changes: List[Change]) -> None:
        """Shockers: the engine gets the settings again -- caps, shockers
        and their switches, names, arming, On / Off -- the router its rules,
        and the page and Home redraw. Taking something away from friends
        drops what they have going, as by hand."""
        s, eng = self.pishock_settings, self.pishock_engine
        heads = _heads(changes)
        self._pishock_push_config()
        armed = bool(s.get_armed())
        if armed != bool(eng.is_armed):
            eng.set_armed(armed)
            self.log_message("Shockers: shocks ARMED" if armed
                             else "Shockers: shocks disarmed — shock rules vibrate")
        enabled = bool(s.get_enabled())
        if enabled == bool(eng.is_paused):
            eng.set_paused(not enabled)
            if not enabled:
                self._pishock_drop_friend_shocks()
            self.log_message("Shockers on" if enabled else
                             "Shockers off — nothing reaches them until you switch them on")
        if "friends_may_use" in heads and not s.get_friends_may_use():
            self._pishock_drop_friend_shocks()
        self.pishock_router.rules_changed()
        self._pishock_presence_follow()
        # ShockOSC behaviours' values back as they were: the avatar too
        send = getattr(self, "shockosc_send_config", None)
        if callable(send):
            send()
        self._pishock_redraw()
        ui = getattr(self, "ui", None)
        rules = getattr(ui, "_rebuild_pishock_rules", None) if ui is not None else None
        if rules is not None and heads & set(RULE_KINDS):
            rules()

    def _history_friends_restored(self, changes: List[Change]) -> None:
        """Friends: permissions again; whatever a friend lost
        drops what they have going (as each switch does by hand); the
        Online switch, Pause all and the web remote's On take effect."""
        s = self.friends_settings
        heads = _heads(changes)
        before = dict(getattr(self, "_friend_perms", {}) or {})
        self._friends_rebuild_perms()
        after = getattr(self, "_friend_perms", {}) or {}
        drop_params = getattr(self, "_params_drop_friend", None)
        for peer, old in before.items():
            new = after.get(peer, (False, False, False))
            if old[0] and not new[0]:
                self._drop_drive(peer)
            if old[1] and not new[1]:
                self._drop_shocks(peer)
            if len(old) > 2 and old[2] and not new[2] and drop_params is not None:
                drop_params(peer)
        if "paused" in heads:
            self._needs_recalculation = True
            wake = getattr(self, "_wake_routing", None)
            if wake is not None:
                wake()
            release = getattr(self, "_params_release_all", None)
            if s.get_paused() and release is not None:
                release()
        if "sync" in heads:
            self._friends_sync_changed()
        if "online" in heads:
            if s.get_online():
                self._friends_maybe_start()
            else:
                self._friends_stop()
        if "nickname" in heads and self.friends_link.running:
            self.friends_link.set_nickname(s.get_nickname())
        if "web" in heads and not s.get_web()["on"]:
            let_go = getattr(self, "_web_let_go_all", None)
            if let_go is not None:
                import remote_link
                let_go(remote_link.WEB_CLOSED)
        self._history_instance_restored(changes)
        self._friends_refresh_ui()

    def _history_instance_restored(self, changes: List[Change]) -> None:
        """Only friends in my instance, a friend's Allow from anywhere, the
        web remote's Allow anyway: what their setters do once the value is
        in -- the log reading switched on when the switch is (it can't work
        without it), the Friends log told, and who is not here worked out
        again, so whoever just became so stops at once."""
        refresh = getattr(self, "_instance_refresh", None)
        if refresh is None:
            return
        touched = False
        s = self.friends_settings
        for ch in changes:
            path = ch.path
            if path == ("instance_only",):
                touched = True
                on = s.get_instance_only()
                if on and not self.get_friends_vrc_log():
                    self.set_friends_vrc_log(True)
                self._friends_note("Only friends in your VRChat instance may drive you now"
                                   if on else "Friends may drive you from anywhere again",
                                   kind=SETTINGS, op="instance-only" if on else "anywhere")
            elif len(path) == 3 and path[0] == "friends" and path[2] == "anywhere":
                touched = True
                f = s.get_friend(getattr(path[1], "id", "")) or {}
                if f:
                    on = bool(f.get("anywhere"))
                    self._friends_note("{who} may drive you from anywhere" if on else
                                       "{who} may drive you only from your VRChat instance",
                                       who=f["id"], kind=SETTINGS, op="allow" if on else "deny")
            elif path[:2] == ("web", "anyway") or (path == ("web",)):
                touched = True
            elif len(path) == 2 and path[0] == "friends":
                touched = True        # (a whole entry: its anywhere with it)
        if touched:
            refresh()

    def _history_params_restored(self, changes: List[Change]) -> None:
        """Avatar Remote: the open board is read from the store again, and
        friends and the page get it as after any edit."""
        self._params_book.reload()
        height = getattr(self, "_height", None)
        if height is not None and "height" in _heads(changes):
            # what height_set_option does once the box's settings are in
            new = self.params_settings.get_height()
            height.double_s = new["double_s"]
            if not new["on"] or new["locked"]:
                height.stop_friends()         # what a friend started stops there
        self._params_changed()

    def _history_suits_restored(self, changes: List[Change]) -> None:
        s = self.suits_settings
        self.bhaptics_engine.set_paused(not s.bhaptics()["enabled"])
        self.owo_engine.set_paused(not s.owo()["enabled"])
        self._owo_push_config()
        self._suits_push_config()
        sync = getattr(self, "presence_sync", None)
        if sync is not None:
            sync()
        ui = getattr(self, "ui", None)
        for name in ("_rebuild_suit_routes", "refresh_suits_status"):
            fn = getattr(ui, name, None) if ui is not None else None
            if fn is not None:
                fn()

    def _history_psvr2_restored(self, changes: List[Change]) -> None:
        s = self.psvr2_settings
        self.psvr2_engine.set_paused(not s.get_enabled())
        self.psvr2_router.configure()
        ui = getattr(self, "ui", None)
        fn = getattr(ui, "refresh_psvr2_status", None) if ui is not None else None
        if fn is not None:
            fn()

    def _history_sessions_restored(self, changes: List[Change]) -> None:
        self._session_raw_sync()
        ui = getattr(self, "ui", None)
        fn = getattr(ui, "_refresh_sessions_view", None) if ui is not None else None
        if fn is not None:
            fn()
