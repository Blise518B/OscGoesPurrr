"""Who you play with — the controller side of the per-person statistics.

Two jobs:

* **Tags.** The Statistics page tags a session — the whole of it, or a
  stretch marked on its timeline — with one or more people, removes tags,
  and shows the People table. The store (`self.stats_people`, see
  stats_people) belongs to the stats facade: it creates it, deletes it with
  the rest of the statistics, and caches what the running session gives
  each person when the session is filed.
* **Tagging from VRChat's log (opt-in).** Statistics → People → "Tag who
  you're with from VRChat's log". A `vrchat_log.LogWatcher` follows
  VRChat's log on its own thread; while it says you are alone in an
  instance with exactly one other person, the running session carries a
  stretch with their name. The stretch ends when that changes (or the OSC
  link to VRChat drops), and one that held no activity is dropped again.
  A VRChat user keeps the name they were first tagged with, so a display
  name change doesn't split them in two.

Not a hot path: `_people_tick()` rides the 1 Hz heartbeat after the stats
sample, and the log is never read on the GUI thread.

Sealed-box rules: the UI calls these methods and passes primitives.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from stats_history import summarize
from stats_people import clean_names, credit, credit_from_totals, held_nothing
from vrchat_log import LogWatcher, companion

AUTODETECT_KEY = "people_autodetect"

# The same person back within this long (they rejoined, or the OSC link
# blinked) continues their stretch instead of starting a new one.
_REJOIN_S = 300.0


class PeopleFacade:
    """Mixin: session tags and the People table. Composed into
    OscGoesPurrrApp.

    Assumes the host has `self.mode_manager` (with `app_settings`),
    `self.osc_manager`, and the stats facade's `stats_people`,
    `stats_history` and `stats_tracker`.
    """

    # ------------------------------------------------------------------
    # Lifecycle (called from main.py)
    # ------------------------------------------------------------------

    def _people_init(self) -> None:
        self._people_watcher: Optional[LogWatcher] = None
        # The open stretch the log tagged: (session id, tag id, VRChat key),
        # and the last one it ended: (session id, tag id, key, end).
        self._people_auto: Optional[Tuple[str, int, str]] = None
        self._people_last_auto: Optional[Tuple[str, int, str, float]] = None
        if self.get_people_autodetect_enabled():
            self._people_start_watcher()

    def _people_start_watcher(self) -> None:
        if getattr(self, "_people_watcher", None) is None:
            self._people_watcher = self._people_make_watcher()
        self._people_watcher.start()

    def _people_make_watcher(self) -> LogWatcher:
        return LogWatcher()

    def _people_stop_watcher(self) -> None:
        watcher = getattr(self, "_people_watcher", None)
        self._people_watcher = None
        if watcher is not None:
            watcher.stop()

    def _people_shutdown(self) -> None:
        """Quit: stop following the log. The open stretch is ended with the
        session (stats facade)."""
        self._people_stop_watcher()

    # ------------------------------------------------------------------
    # 1 Hz: the VRChat-log stretch
    # ------------------------------------------------------------------

    def _people_osc_up(self) -> bool:
        osc = getattr(self, "osc_manager", None)
        return bool(osc is not None and getattr(osc, "is_connected", False))

    def _people_tick(self) -> None:
        """Open, keep or end the log-tagged stretch of the running session.
        Guarded: a bug here must not stop the heartbeat that hosts it."""
        try:
            self._people_follow_log(time.time())
        except Exception as e:
            print(f"[people] log tagging failed: {e}")

    def _people_follow_log(self, now: float) -> None:
        people = getattr(self, "stats_people", None)
        hist = getattr(self, "stats_history", None)
        watcher = getattr(self, "_people_watcher", None)
        cur = getattr(self, "_people_auto", None)
        if people is None or hist is None or watcher is None:
            if cur is not None:
                self._people_end_auto(cur, now)
            return
        sid, started = hist.live["id"], hist.live["started_ts"]
        if cur is not None and cur[0] != sid:
            # The statistics were reset: that stretch went with them.
            cur = self._people_auto = None
        snap = watcher.snapshot()
        link = self._people_osc_up()
        comp = companion(snap) if link else None
        key = comp[0] if comp else None
        if cur is not None and cur[2] == key:
            return
        # When who's-there changed, by the log's clock.
        since = snap.get("since")
        if cur is not None:
            # A change the log saw ends the stretch when it happened;
            # VRChat going away (or its log being read afresh) ends it now.
            end = now
            if link and snap.get("state") == "ok" and since and since <= now:
                tag = next((t for t in people.tags(sid) if t["id"] == cur[1]), None)
                if tag is not None and since > tag.get("start", now):
                    end = since
            self._people_end_auto(cur, end)
        if comp is None:
            return
        start = min(now, max(started, since)) if since else now
        last = getattr(self, "_people_last_auto", None)
        if last is not None and last[0] == sid and last[2] == key:
            if now - last[3] <= _REJOIN_S and people.reopen_stretch(sid, last[1]):
                self._people_auto = (sid, last[1], key)
                people.flush()
                return
            start = max(start, last[3])
        uid = key if key.startswith("usr_") else ""
        name = people.vrc_name(uid, comp[1])
        tag_id = people.add_stretch(sid, started, start, None, [name],
                                    auto=True, vrc=uid)
        self._people_auto = (sid, tag_id, key) if tag_id else None
        people.flush()

    def _people_end_auto(self, cur: Tuple[str, int, str], end: float) -> None:
        """End the log-tagged stretch at `end`; drop it if nothing happened
        in it."""
        self._people_auto = None
        people = getattr(self, "stats_people", None)
        hist = getattr(self, "stats_history", None)
        if people is None:
            return
        sid, tag_id, key = cur
        self._people_last_auto = (sid, tag_id, key, end)
        people.close_stretch(sid, tag_id, end)
        if hist is not None and hist.live["id"] == sid:
            tag = next((t for t in people.tags(sid) if t["id"] == tag_id), None)
            if tag is not None and held_nothing(hist.live, tag, end):
                people.remove_tag(sid, tag_id)
        people.flush()

    # ------------------------------------------------------------------
    # Credit
    # ------------------------------------------------------------------

    def _people_session_start(self, sid: str) -> Optional[float]:
        """A session's start time, or None if no such session is known."""
        if sid.startswith("summary:"):
            try:
                return float(sid.split(":", 1)[1])
            except ValueError:
                return None
        hist = getattr(self, "stats_history", None)
        tl = hist.timeline(sid) if hist is not None else None
        return float(tl["started_ts"]) if tl is not None else None

    def _people_summary_row(self, sid: str) -> Optional[Dict[str, Any]]:
        tracker = getattr(self, "stats_tracker", None)
        if tracker is None:
            return None
        start = self._people_session_start(sid)
        for s in tracker.recent_sessions:
            if start is not None and abs(float(s.get("started_ts", 0.0)) - start) < 0.01:
                return s
        return None

    def _people_fill_credit(self, sid: str) -> None:
        """Work out and cache what a finished session gives each person.
        The running session is left alone (it grows); a session whose data
        is gone keeps no cache and is skipped."""
        people = self.stats_people
        hist = getattr(self, "stats_history", None)
        if hist is not None and hist.is_live(sid):
            return
        tags = people.tags(sid)
        if sid.startswith("summary:"):
            row = self._people_summary_row(sid)
            if row is not None:
                people.set_credit(sid, credit_from_totals(
                    tags, row.get("active_s", 0.0), row.get("thrusts", 0)))
            return
        tl = hist.timeline(sid) if hist is not None else None
        if tl is None:
            return
        s = summarize(tl)
        people.set_credit(sid, credit(tl, tags, s["started_ts"] + s["duration_s"]))

    # ------------------------------------------------------------------
    # UI facade — the People card
    # ------------------------------------------------------------------

    def get_people_table(self) -> List[Dict[str, Any]]:
        """One row per person, most thrusts first: name, sessions,
        active_s, thrusts, peak_pace, last_ts. Includes the running
        session. Never raises."""
        try:
            people = getattr(self, "stats_people", None)
            if people is None:
                return []
            for sid in people.tagged_sessions():
                if people.needs_credit(sid):
                    self._people_fill_credit(sid)
            extra = {}
            hist = getattr(self, "stats_history", None)
            if hist is not None:
                tl = hist.live
                tags = people.tags(tl["id"])
                if tags and tl["buckets"]:
                    extra[tl["id"]] = (tl["started_ts"],
                                       credit(tl, tags, time.time()))
            people.flush()
            return people.table(extra)
        except Exception as e:
            print(f"[people] table failed: {e}")
            return []

    def get_people_names(self) -> List[str]:
        """Every name tagged so far, A to Z (for the name field's
        suggestions)."""
        people = getattr(self, "stats_people", None)
        try:
            return people.known_names() if people is not None else []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # UI facade — tagging a session
    # ------------------------------------------------------------------

    def _people_after_edit(self, sid: str) -> None:
        people = self.stats_people
        if sid.startswith("summary:") and people.tags(sid):
            # Its totals may fall off the recent list later: cache now.
            self._people_fill_credit(sid)
        people.flush()

    def tag_session(self, session_id: str, names: Any) -> bool:
        """Set who the whole session was with (a list, or names separated
        by commas). No names clears it. False if the session is unknown."""
        people = getattr(self, "stats_people", None)
        sid = str(session_id or "")
        started = self._people_session_start(sid) if people is not None else None
        if started is None:
            return False
        people.tag_whole(sid, started, clean_names(names))
        self._people_after_edit(sid)
        return True

    def tag_session_stretch(self, session_id: str, start_epoch: float,
                            end_epoch: float, names: Any) -> bool:
        """Tag a stretch of a session (it needs a timeline) with one or
        more people. False if nothing was tagged."""
        people = getattr(self, "stats_people", None)
        sid = str(session_id or "")
        if people is None or sid.startswith("summary:"):
            return False
        started = self._people_session_start(sid)
        if started is None:
            return False
        start, end = sorted((float(start_epoch), float(end_epoch)))
        ok = bool(people.add_stretch(sid, started, max(started, start), end,
                                     clean_names(names)))
        self._people_after_edit(sid)
        return ok

    def remove_session_tag(self, session_id: str, tag_id: int) -> bool:
        people = getattr(self, "stats_people", None)
        sid = str(session_id or "")
        if people is None:
            return False
        ok = people.remove_tag(sid, int(tag_id))
        self._people_after_edit(sid)
        return ok

    # ------------------------------------------------------------------
    # UI facade — the VRChat-log option
    # ------------------------------------------------------------------

    def get_people_autodetect_enabled(self) -> bool:
        return bool(self.mode_manager.app_settings.get(AUTODETECT_KEY, False))

    def set_people_autodetect(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self.mode_manager.app_settings.set(AUTODETECT_KEY, enabled)
        if enabled:
            self._people_start_watcher()
            return
        cur = getattr(self, "_people_auto", None)
        if cur is not None:
            self._people_end_auto(cur, time.time())
        self._people_stop_watcher()

    def get_people_autodetect_status(self) -> Dict[str, Any]:
        """What the option is doing, for its status line: `state` is one of
        off / no_stats / starting / no_log / reading / no_vrchat / alone /
        with / crowd; `name` is set for "with", `count` (people besides
        you) for "crowd"."""
        if not self.get_people_autodetect_enabled():
            return {"state": "off"}
        if getattr(self, "stats_people", None) is None:
            return {"state": "no_stats"}
        watcher = getattr(self, "_people_watcher", None)
        snap = watcher.snapshot() if watcher is not None else {"state": "starting"}
        state = snap.get("state", "starting")
        if state != "ok":
            return {"state": state}
        if not self._people_osc_up():
            return {"state": "no_vrchat"}
        others = snap.get("others") or []
        if not others:
            return {"state": "alone"}
        if len(others) == 1:
            people = self.stats_people
            key, name = others[0]
            shown = people.vrc_names.get(key, name) if key.startswith("usr_") else name
            return {"state": "with", "name": shown}
        return {"state": "crowd", "count": len(others)}
