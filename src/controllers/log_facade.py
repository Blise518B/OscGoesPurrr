"""Log facade mixin -- the log of who did what, and the Log page.

One store for the app (`self.event_log`, event_log.EventLog): the Friends
page's log card reads it (friends_facade.get_friends_log /
get_friends_log_people), the Log page filters it here, and Statistics will
count its events. Kept on this PC for `event_log.KEEP_DAYS` days, one JSON
Lines file per day in `EVENT_LOG_DIR`; never sent to anyone.

Entries come from `friends_facade._friends_note` (friends, Me, web remote
guests, groups, your own switches) and from the PiShock router, which
reports what your own avatar's behaviours fire (`_log_avatar_shock`, on the
router's thread). Adding never touches the disk: the log's own writer
thread does (event_log.py).

Assumes the host controller has `self.log_message` and (optionally)
`self.pishock_engine`.
"""

import time
from typing import Any, Dict, Iterable, List, Optional

import event_log
from event_log import AVATAR, AVATAR_NAME, IN, ROLE_AVATAR, SHOCK
from settings._paths import EVENT_LOG_DIR

LOG_DIR = EVENT_LOG_DIR          # tests point this at a temp folder (conftest)
PAGE_LIMIT = 1000                # the Log page lists at most this many rows
PEOPLE_RECENT = 25               # each person's recent history in "by person"

# The Log page's time filter: label -> seconds back (None: everything kept)
SPANS = {"Last hour": 3600, "Today": "today", "Last 7 days": 7 * 86400,
         f"Last {event_log.KEEP_DAYS} days": None}


class LogFacade:
    """Mixin: the log's store, the Log page's queries and Clear."""

    def _event_log_init(self) -> None:
        self.event_log = event_log.EventLog(LOG_DIR)
        self.event_log.start()

    def _event_log_shutdown(self) -> None:
        log = getattr(self, "event_log", None)
        if log is not None:
            log.close()

    # ------------------------------------------------------------------
    # The Log page
    # ------------------------------------------------------------------

    def get_log_version(self) -> int:
        """Changes whenever the log does: the views redraw only then."""
        log = getattr(self, "event_log", None)
        return log.version if log is not None else 0

    def get_log_spans(self) -> List[str]:
        """The time filter's choices, shortest first."""
        return list(SPANS)

    def get_log_kinds(self) -> List[Dict[str, str]]:
        """The kind filter's choices: [{key, label}]."""
        return [{"key": k, "label": event_log.KIND_LABELS[k]} for k in event_log.KINDS]

    def get_log_events(self, person: Optional[str] = None,
                       kinds: Optional[Iterable[str]] = None, span: str = "",
                       text: str = "", hide_avatar: bool = False,
                       limit: int = PAGE_LIMIT) -> Dict[str, Any]:
        """The Log page's list: {events (newest first, as dicts), total
        (how many pass the filters), shown, loaded (the files are read)}."""
        log = getattr(self, "event_log", None)
        if log is None:
            return {"events": [], "total": 0, "shown": 0, "loaded": True}
        hits, total = log.query(person, kinds, _since(span), text,
                                (AVATAR,) if hide_avatar else (), limit)
        return {"events": [e.as_dict() for e in hits], "total": total, "shown": len(hits),
                "loaded": log.loaded}

    def get_log_people(self, kinds: Optional[Iterable[str]] = None, span: str = "",
                       text: str = "", hide_avatar: bool = False) -> List[Dict[str, Any]]:
        """The Log page's people: a row per person within the other filters,
        the one active most recently first -- with counts and their recent
        history."""
        log = getattr(self, "event_log", None)
        if log is None:
            return []
        hits, _total = log.query(None, kinds, _since(span), text,
                                 (AVATAR,) if hide_avatar else ())
        now = time.time()
        return [p.as_dict(now) for p in event_log.by_person(hits, PEOPLE_RECENT)]

    def get_log_page(self, person: Optional[str] = None,
                     kinds: Optional[Iterable[str]] = None, span: str = "",
                     text: str = "", hide_avatar: bool = False,
                     limit: int = PAGE_LIMIT) -> Dict[str, Any]:
        """Everything the Log page shows, from one pass over the log (the
        Qt loop also runs the routing tick: no second pass): the list as
        get_log_events gives it, plus "people" as get_log_people does --
        every person within the other filters, whoever is picked."""
        log = getattr(self, "event_log", None)
        if log is None:
            return {"events": [], "total": 0, "shown": 0, "loaded": True, "people": []}
        everyone, _total = log.query(None, kinds, _since(span), text,
                                     (AVATAR,) if hide_avatar else ())
        hits = everyone if person is None else [e for e in everyone if e.who == person]
        now = time.time()
        return {"events": [e.as_dict() for e in hits[:limit]], "total": len(hits),
                "shown": min(len(hits), limit), "loaded": log.loaded,
                "people": [p.as_dict(now) for p in event_log.by_person(everyone, PEOPLE_RECENT)]}

    def clear_log(self) -> None:
        """The Log page's Clear: every entry, in memory and on disk."""
        log = getattr(self, "event_log", None)
        if log is not None:
            log.clear()
            self.log_message("The log was cleared")

    # ------------------------------------------------------------------
    # Your avatar's behaviours -- the PiShock router's thread
    # ------------------------------------------------------------------

    def _log_avatar_shock(self, what: str, sid: int, op: str, level: int,
                          ms: Optional[int], rule: str = "", sent: Any = None) -> None:
        """What your own avatar's behaviours (the Shockers page's rules) did
        to a shocker: a pulse that went out, a hold starting, a hold ending.
        `rule` names the behaviour (pishock_router.behaviour_name): it is the
        entry's `via` and goes in its line. `level` / `ms` are what the
        behaviour asked; for a pulse `sent` is what went out
        (pishock_engine.Sent). The line says what was asked, the record
        keeps what went out (Statistics count that) and why it differs.
        Called right after the sends; only builds the entry and adds it."""
        log = getattr(self, "event_log", None)
        eng = getattr(self, "pishock_engine", None)
        if log is None or eng is None:
            return
        name = next((str(s.get("name") or f"Shocker {sid}") for s in eng.shockers()
                     if s.get("id") == sid), f"Shocker {sid}")
        armed = bool(eng.is_armed)
        went = "vibrate" if op == "shock" and not armed else op
        asked_level, asked_ms = int(level), ms
        if what == "pulse" and sent is not None:
            went, level, ms = sent.op, sent.intensity, sent.duration_ms
        elif op != "beep":
            # the ceiling of what plays, as the engine applies it: an unarmed
            # shock is a vibrate, under the vibrate's ceiling
            caps = eng.limits_for(sid)
            level = min(int(level), int(caps["max_intensity"] if went == "shock"
                                        else caps.get("max_vibrate", caps["max_intensity"])))
        # A hold's `asked` is what it plays: an unarmed shock holds as the
        # vibrate it becomes (Statistics counts what reached the shocker).
        fixed = []
        if what != "let-go" and op != "beep" and level < asked_level:
            fixed.append(f"your {went} limit")
        if what == "pulse" and ms is not None and asked_ms is not None and ms < asked_ms:
            fixed.append("your longest pulse")
        if what == "let-go":
            # the hold's strongest level as it played (its start said what
            # was asked)
            asked_level = level
        what_text = event_log.shocker_text(op, asked_level, armed)
        if what == "pulse":
            text = f"{{who}}: {what_text} · {event_log.seconds_text(asked_ms)} on {name}"
            ev_op, asked = went, (op if went != op else "")
        elif what == "hold":
            text = f"{{who}} is holding {what_text} on {name}"
            ev_op, asked = "hold", went
        else:
            text = (f"{{who}} let go of {name} after {event_log.seconds_text(ms)}"
                    + (f" (up to {what_text})" if op != "beep" else ""))
            ev_op, asked = "let-go", went
        beep = op == "beep"
        who = f"{AVATAR_NAME} ({rule})" if rule else AVATAR_NAME
        log.add(event_log.Event(
            time.time(), text.replace("{who}", who), AVATAR, AVATAR_NAME, ROLE_AVATAR, SHOCK,
            ev_op, IN, None if beep else level, ms, (name,), "", asked, rule,
            asked_level=None if beep or asked_level == level else asked_level,
            asked_ms=asked_ms if what == "pulse" and asked_ms != ms else None,
            fixed=", ".join(fixed)))


def _since(span: str) -> Optional[float]:
    """The unix time a span of the time filter starts at (None: all)."""
    back = SPANS.get(span)
    now = time.time()
    if back == "today":
        lt = time.localtime(now)
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    if isinstance(back, (int, float)):
        return now - back
    return None
