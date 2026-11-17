"""Statistics counted from the log -- controller mixin.

StatsFacade's companion (its base class): owns `self.stats_events`
(stats_events.StatsEvents) and feeds it

* **the log's entries.** `event_log.EventLog.on_add` calls
  `_stats_events_heard` on whatever thread logs -- the PiShock router's,
  the link's, the GUI's -- and it only appends to a deque. The 1 Hz
  statistics tick (`_stats_events_tick`, from StatsFacade._stats_sample_tick)
  counts what came in, into the lifetime totals and the running session's,
  so nothing is added to any routing or receive path. A shock that reached
  a shocker also makes sure the running session's timeline has that moment
  (stats_history.touch), so a session of only shocks is still filed.
* **the suits' and trackers' on-time**, sampled on the same tick from the
  engines' output snapshots.

The Statistics page reads it through `get_stats_from_whom`,
`get_stats_worn` and the session page's "shocks" (StatsFacade
.get_stats_session_detail). The timeline's marks come from the log itself
(event_log.EventLog.window) -- no second record of them is kept here.

Friends' names: kept unless the page's switch (`stats_friend_names`, on by
default) is off -- then a friend counts as "A friend" and a web remote guest
as "Web remote"; `forget_stats_friend_names` folds the names already kept.
It all stays on this PC like every statistic; nothing here is ever sent to
a friend or the web remote.
"""

import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import body_map
import stats_events
import tracker_spots
from event_log import ROLE_AVATAR, SHOCK
from settings import STATS_EVENTS_FILE

NAMES_KEY = "stats_friend_names"      # app setting: keep friends' names (default on)
_PENDING_MAX = 20000                  # entries waiting for the next tick, at most


class StatsEventsMixin:
    """Mixin: what Statistics counts from the log. Base of StatsFacade."""

    # ------------------------------------------------------------------
    # Wiring (StatsFacade calls these)
    # ------------------------------------------------------------------

    def _stats_events_init(self) -> None:
        """After the tracker and the history (StatsFacade._stats_init):
        the store, the sessions it may keep, and the log's listener (once
        per run -- statistics may be switched off and on again)."""
        self.stats_events = None
        if getattr(self, "_stats_events_pending", None) is None:
            self._stats_events_pending = deque(maxlen=_PENDING_MAX)
        self._stats_events_marks_cache: Tuple[Any, List[Dict[str, Any]]] = (None, [])
        try:
            self.stats_events = stats_events.StatsEvents(STATS_EVENTS_FILE)
        except Exception as e:
            print(f"[stats] counting from the log failed to start: {e}")
            return
        hist = getattr(self, "stats_history", None)
        if hist is not None:
            # The sessions whose timelines are still there (the rest were
            # pruned): their counts go with them, the lifetime keeps them.
            self.stats_events.keep_sessions([e["id"] for e in hist.index] + [hist.live["id"]])
        log = getattr(self, "event_log", None)
        if log is not None and not getattr(self, "_stats_events_listening", False):
            log.on_add(self._stats_events_heard)
            self._stats_events_listening = True

    def _stats_events_heard(self, ev) -> None:
        """The log's listener -- any thread, right after an entry is added:
        only appends; the 1 Hz tick counts."""
        if getattr(self, "stats_events", None) is not None:
            self._stats_events_pending.append(ev)

    def _stats_events_tick(self, dt: float) -> None:
        """1 Hz: count what the log heard since the last tick, and one
        sample of the suits and trackers."""
        store = getattr(self, "stats_events", None)
        if store is None:
            return
        self._stats_events_drain()
        try:
            worn = self._stats_worn_now()
        except Exception as e:
            print(f"[stats] reading the suits failed: {e}")
            worn = []
        if worn and dt > 0:
            sid, started = self._stats_events_session()
            store.add_worn(sid, started, dt, worn)

    def _stats_events_drain(self) -> None:
        store = getattr(self, "stats_events", None)
        pending = getattr(self, "_stats_events_pending", None)
        if store is None or not pending:
            return
        hist = getattr(self, "stats_history", None)
        sid, started = self._stats_events_session()
        names = self.get_stats_friend_names()
        # your avatar's and friends' own longest hold while they are separate
        caps = {g: self._stats_hold_caps(g) for g in ("avatar", "friends")}
        while True:
            try:
                ev = pending.popleft()
            except IndexError:
                break
            try:
                own = caps["avatar" if ev.role == ROLE_AVATAR else "friends"]
                if store.count(ev, sid, started, names, own) and stats_events.is_mark(ev):
                    if hist is not None:
                        hist.touch(ev.t)
            except Exception as e:
                print(f"[stats] counting a log entry failed: {e}")

    def _stats_events_session(self) -> Tuple[str, float]:
        hist = getattr(self, "stats_history", None)
        if hist is None:
            return "", 0.0
        return hist.live["id"], float(hist.live["started_ts"])

    def _stats_hold_caps(self, group: str = "avatar") -> Optional[Tuple[float, float]]:
        """The hub's longest hold and the rest after it, for how long a
        long hold actually ran (stats_events.held_on_time) -- `group`'s own
        while separate limits for friends are on."""
        eng = getattr(self, "pishock_engine", None)
        try:
            timing = getattr(eng, "timing_for", None)
            lim = (timing(group) if callable(timing) else eng.limits()) if eng is not None else None
            return (float(lim["max_hold_s"]), float(lim["hold_rest_s"])) if lim else None
        except Exception:
            return None

    def _stats_events_flush(self, force: bool = False) -> None:
        store = getattr(self, "stats_events", None)
        if store is not None:
            store.flush(force)

    def _stats_events_close(self, now: float) -> None:
        """The session closes (quit, statistics off): count what is left,
        end the holds and drives still open, write it -- before the history
        files the session, so its last shocks are on its timeline."""
        store = getattr(self, "stats_events", None)
        if store is None:
            return
        self._stats_events_drain()
        store.close_all(now, self._stats_hold_caps())
        store.flush(force=True)

    def _stats_events_reset(self) -> None:
        store = getattr(self, "stats_events", None)
        if store is not None:
            store.reset()
        pending = getattr(self, "_stats_events_pending", None)
        if pending is not None:
            pending.clear()

    # ------------------------------------------------------------------
    # The suits and trackers, once a second
    # ------------------------------------------------------------------

    def _stats_worn_now(self) -> List[str]:
        """What's buzzing on you right now, by name: each bHaptics part
        playing (on a connected device), the OWO suit sending, each haptic
        tracker's spot playing -- with its feature switched on."""
        feat = getattr(self, "get_feature_enabled", None)

        def on(key: str) -> bool:
            return bool(feat(key)) if feat is not None else True

        out: List[str] = []
        bh = getattr(self, "bhaptics_engine", None)
        if bh is not None and on("feature_bhaptics"):
            have = {p for d in bh.status_snapshot().get("devices") or ()
                    for p in d.get("positions") or ()}
            groups = {body_map.group_of(pos) or pos
                      for pos, dots in bh.output_snapshot().items()
                      if pos in have and any(dots)}
            names = {key: name for key, name, _p in body_map.PART_GROUPS}
            out += [f"bHaptics {names.get(g, g)}" for g in sorted(groups)]
        owo = getattr(self, "owo_engine", None)
        if owo is not None and on("feature_owo"):
            st = owo.status_snapshot()
            if st.get("connected") and any(st.get("active") or {}):
                out.append("OWO suit")
        trk = getattr(self, "tracker_engine", None)
        places = getattr(self, "_tracker_places", None)
        if trk is not None and places is not None and on("feature_trackers"):
            where = places()
            spots = {where.get(serial) for serial, v in trk.output_snapshot().items() if v > 0}
            out += [f"Tracker · {tracker_spots.SPOT_NAMES.get(s, s)}"
                    for s in sorted(s for s in spots if s)]
        return out

    # ------------------------------------------------------------------
    # Friends' names (the From whom card's switch)
    # ------------------------------------------------------------------

    def _stats_app_setting(self, key: str, default: Any) -> Any:
        get = getattr(self, "get_app_setting", None)
        if get is not None:
            return get(key, default)
        modes = getattr(self, "mode_manager", None)
        return modes.app_settings.get(key, default) if modes is not None else default

    def get_stats_friend_names(self) -> bool:
        """Statistics keep friends' names (on by default)."""
        return bool(self._stats_app_setting(NAMES_KEY, True))

    def set_stats_friend_names(self, on: bool) -> None:
        """Off: from now on a friend counts as "A friend" and a web remote
        guest as "Web remote". The names already kept stay until
        forget_stats_friend_names."""
        set_ = getattr(self, "set_app_setting", None)
        if set_ is not None:
            set_(NAMES_KEY, bool(on))
        elif getattr(self, "mode_manager", None) is not None:
            self.mode_manager.app_settings.set(NAMES_KEY, bool(on))

    def stats_friend_names_kept(self) -> bool:
        """Is any friend's (or web remote guest's) name in the statistics?"""
        store = getattr(self, "stats_events", None)
        return bool(store is not None and store.has_names())

    def forget_stats_friend_names(self) -> bool:
        """The From whom card's Forget names (it asked first): every
        friend's count goes under "A friend", every web remote guest's under
        "Web remote" -- lifetime and every session. The log keeps its own
        30 days (the Log page clears it)."""
        store = getattr(self, "stats_events", None)
        if store is None:
            return False
        self._stats_events_drain()
        changed = store.forget_names()
        store.flush(force=True)
        self._stats_events_marks_cache = (None, [])
        log = getattr(self, "log_message", None)
        if changed and log is not None:
            log("Statistics forgot friends' names")
        return changed

    # ------------------------------------------------------------------
    # What the page reads
    # ------------------------------------------------------------------

    def get_stats_from_whom(self, span: str = "lifetime") -> Dict[str, Any]:
        """The From whom card: stats_events.view of the lifetime totals or
        of this session ("session"), plus "names" (the switch) and "kept"
        (any name to forget). Counts what the log heard first."""
        store = getattr(self, "stats_events", None)
        if store is None:
            return {"any": False, "ops": stats_events.ops_view({}), "people": [],
                    "shockers": [], "worn": [], "names": self.get_stats_friend_names(),
                    "kept": False, "on": False}
        self._stats_events_drain()
        if span == "session":
            out = store.session_view(self._stats_events_session()[0]) or stats_events.view(
                stats_events.fresh_tally())
        else:
            out = store.lifetime_view()
        out.update(names=self.get_stats_friend_names(), kept=store.has_names(), on=True)
        return out

    def get_stats_worn(self) -> Dict[str, List[List[Any]]]:
        """The suits' and trackers' on-time: {"lifetime": [[name, s]],
        "session": [[name, s]]}, most first."""
        store = getattr(self, "stats_events", None)
        if store is None:
            return {"lifetime": [], "session": []}
        session = store.session_view(self._stats_events_session()[0])
        return {"lifetime": store.lifetime_view()["worn"],
                "session": session["worn"] if session else []}

    def _stats_session_shocks(self, sid: str, start: float,
                              end: Optional[float]) -> Dict[str, Any]:
        """One session's counts and its timeline's marks: {"tally" (a
        stats_events.view, or None), "marks" (from the log, while it still
        has them -- 30 days)}."""
        store = getattr(self, "stats_events", None)
        if store is not None:
            self._stats_events_drain()
        tally = store.session_view(sid) if store is not None else None
        return {"tally": tally, "marks": self._stats_marks(sid, start, end)}

    def _stats_marks(self, sid: str, start: float, end: Optional[float]) -> List[Dict[str, Any]]:
        log = getattr(self, "event_log", None)
        if log is None or not start:
            return []
        names = self.get_stats_friend_names()
        key = (sid, log.version, names, end)
        cached = getattr(self, "_stats_events_marks_cache", (None, []))
        if cached[0] == key:
            return cached[1]
        events = log.window(start, end, where=lambda e: e.kind == SHOCK)
        out = stats_events.marks(events, names)
        self._stats_events_marks_cache = (key, out)
        return out
