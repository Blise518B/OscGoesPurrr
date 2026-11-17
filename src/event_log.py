"""The log: who did what, as one record per event.

Everything the Friends page logs -- a friend's shock, your strength drag on
a friend, a web remote guest opening the page, a link going down -- and
what your own avatar's behaviours fire on your shockers, is an `Event`:
when, who (a friend, Me, a web remote guest, a group, your avatar, or you
on the page), what (toys, a shock / vibrate / beep with its level and
shockers, an Avatar Remote set, the link coming and going, a switch) and
why, if it was held back. The line a person reads is written from it.

A value OGP corrected on its way out -- a level above a limit, a pulse cut
to the longest one, a warning stretched to the shortest -- keeps both: the
line says what was asked (`asked_level` / `asked_ms` too), `level` / `ms`
are what went out (Statistics count those) and `fixed` says why. The views
show the asked line with `correction` muted under it ("Cut to 1.2 s: their
longest pulse").

One record, built once, for everything that reads it: the Friends page's
log card (as it happens, or a row per person), the Log page (filters by
person, kind, time and words) and -- later -- Statistics, which counts
these same events instead of keeping a record of its own.

`EventLog` keeps the newest events in memory and the last `KEEP_DAYS` days
on disk, one JSON Lines file per day (`2026-11-14.jsonl`) in its own
folder -- never a `.json`: settings backups copy every top-level `.json`.
It's never sent to anyone.

Threads: `add` is called from the link's thread, the PiShock router's and
the GUI thread; it only appends under a lock -- no disk I/O on any routing
or receive path. A writer thread of its own (`start`) loads the history,
writes what was added every `FLUSH_S` and drops days past `KEEP_DAYS`.
"""

import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

KEEP_DAYS = 30
COALESCE_S = 2.0          # a slider drag is one entry, not fifty
FLUSH_S = 2.0             # the writer writes what came in this often
MAX_MEMORY = 20000        # events kept in memory (the files keep the rest)

# What an event is about -- the Log page's kind filter, in this order
TOYS, SHOCK, PARAMS, LINK, SETTINGS = "toys", "shock", "params", "link", "settings"
KINDS = (TOYS, SHOCK, PARAMS, LINK, SETTINGS)
KIND_LABELS = {TOYS: "Toys", SHOCK: "Shocks", PARAMS: "Avatar Remote",
               LINK: "Link", SETTINGS: "Switches"}

# Who: a friend's or a web remote guest's ID, Me's, "g:<id>" for a group,
# or one of these two
YOU = "you"               # you yourself, on the page (not as Me)
AVATAR = "avatar"         # your own avatar's behaviours (the Shockers page)
YOU_NAME = "You"
AVATAR_NAME = "Your avatar"
GROUP_PREFIX = "g:"

ROLE_FRIEND, ROLE_ME, ROLE_WEB, ROLE_GROUP, ROLE_YOU, ROLE_AVATAR = (
    "friend", "me", "web", "group", "you", "avatar")

# Which way it went: they did it to you, or you did it to them
IN, OUT = "in", "out"

# The shocker operations that reach a shocker
SHOCKER_OPS = ("shock", "vibrate", "beep")

# What an action came through, where this PC knows it (`Event.via`): your
# avatar menu or Party Mode -- or, for your avatar's own behaviours, the
# behaviour's name (pishock_router.behaviour_name). A friend's own menu or
# Party Mode isn't said over the link, so theirs stays "".
VIA_MENU, VIA_PARTY = "menu", "party"
VIA_LABELS = {VIA_MENU: "Avatar menu", VIA_PARTY: "Party Mode"}

_DAY_FILE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.jsonl$")


@dataclass(frozen=True)
class Event:
    """One thing that happened. `text` is the line as people read it."""
    t: float                          # unix seconds
    text: str
    who: str = YOU
    name: str = YOU_NAME              # how they were called right then
    role: str = ROLE_YOU
    kind: str = LINK
    op: str = ""                      # shock / vibrate / beep / hold / stop / start / strength / set ...
    dir: str = ""                     # IN: to you; OUT: by you, to them; "": neither
    level: Optional[int] = None       # a shock's level, a strength in %
    ms: Optional[int] = None          # how long
    on: Tuple[str, ...] = ()          # the shockers (or toys) it went to
    held: str = ""                    # why it was held back; "" = it went through
    # The operation asked for, where `op` doesn't say it: a shock that went
    # out as a vibrate (op vibrate), what a hold holds (op hold), what a
    # warning warns of (op warning).
    asked: str = ""
    via: str = ""                     # VIA_MENU / VIA_PARTY / your avatar's behaviour
    # Corrected on the way out: the level / length asked (None: as sent) and
    # why it went out otherwise ("their longest pulse"); `level` / `ms` are
    # what went out.
    asked_level: Optional[int] = None
    asked_ms: Optional[int] = None
    fixed: str = ""

    @property
    def correction(self) -> str:
        """The muted line under the entry: what went out instead of what was
        asked, and why ("Cut to 1.2 s: their longest pulse"); "" when it went
        as asked."""
        return correction_text(self.asked_level, self.level, self.asked_ms, self.ms,
                               self.fixed)

    # ---- what the views ask -------------------------------------------
    @property
    def stands_out(self) -> bool:
        """A shock that reached a shocker (or a hold of one): the views
        make it stand out."""
        return (self.kind == SHOCK and not self.held
                and (self.op == "shock" or (self.op == "hold" and self.asked == "shock")))

    @property
    def shocker_op(self) -> bool:
        """A shock, vibrate or beep -- or a hold of one -- that reached a
        shocker."""
        return self.kind == SHOCK and not self.held and (self.op in SHOCKER_OPS
                                                         or self.op == "hold")

    # ---- the file ------------------------------------------------------
    def to_json(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"t": round(self.t, 3), "who": self.who, "name": self.name,
                               "role": self.role, "kind": self.kind}
        for key, value, empty in (("op", self.op, ""), ("dir", self.dir, ""),
                                  ("lvl", self.level, None), ("ms", self.ms, None),
                                  ("on", list(self.on), []), ("held", self.held, ""),
                                  ("asked", self.asked, ""), ("via", self.via, ""),
                                  ("alvl", self.asked_level, None),
                                  ("ams", self.asked_ms, None), ("fix", self.fixed, "")):
            if value != empty:
                out[key] = value
        out["text"] = self.text
        return out

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> Optional["Event"]:
        """None for a line that isn't one (a damaged file loses that line)."""
        try:
            t = float(d["t"])
            text = str(d["text"])
        except (KeyError, TypeError, ValueError):
            return None
        kind = str(d.get("kind") or LINK)
        return cls(t=t, text=text, who=str(d.get("who") or YOU),
                   name=str(d.get("name") or YOU_NAME), role=str(d.get("role") or ROLE_YOU),
                   kind=kind if kind in KINDS else LINK, op=str(d.get("op") or ""),
                   dir=str(d.get("dir") or ""), level=_int_or_none(d.get("lvl")),
                   ms=_int_or_none(d.get("ms")),
                   on=tuple(str(x) for x in d.get("on") or () if isinstance(x, str)),
                   held=str(d.get("held") or ""), asked=str(d.get("asked") or ""),
                   via=str(d.get("via") or ""), asked_level=_int_or_none(d.get("alvl")),
                   asked_ms=_int_or_none(d.get("ams")), fixed=str(d.get("fix") or ""))

    def as_dict(self) -> Dict[str, Any]:
        """For the UI (primitive values only)."""
        return {"t": self.t, "text": self.text, "who": self.who, "name": self.name,
                "role": self.role, "kind": self.kind, "op": self.op, "dir": self.dir,
                "level": self.level, "ms": self.ms, "on": list(self.on), "held": self.held,
                "via": self.via, "stands_out": self.stands_out, "shocker_op": self.shocker_op,
                "asked_level": self.asked_level, "asked_ms": self.asked_ms,
                "correction": self.correction}


def _int_or_none(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def group_key(gid: str) -> str:
    return GROUP_PREFIX + str(gid)


def shocker_text(op: str, level: Optional[int], armed: bool = True, whose: str = "") -> str:
    """How an operation reads: "beep", "shock 30" -- or, for a shock
    nobody armed, the vibrate it turns into."""
    if op == "beep":
        return "beep"
    if op == "shock" and not armed:
        return f"vibrate {level} ({whose}shocks aren't armed)"
    return f"{op} {level}" if level is not None else op


def seconds_text(ms: Optional[int]) -> str:
    return f"{(ms or 0) / 1000:.1f} s"


def correction_text(asked_level: Optional[int], level: Optional[int],
                    asked_ms: Optional[int], ms: Optional[int], why: str = "") -> str:
    """What went out instead of what was asked, and why: "Lowered to 30",
    "cut to 1.2 s" (or "Raised" / "stretched"), joined, then ": why". With
    nothing changed in the numbers, `why` alone (a full sentence); "" when
    there is nothing to say."""
    parts = []
    if asked_level is not None and level is not None and level != asked_level:
        parts.append(f"{'lowered' if level < asked_level else 'raised'} to {level}")
    if asked_ms is not None and ms is not None and ms != asked_ms:
        parts.append(f"{'cut' if ms < asked_ms else 'stretched'} to {seconds_text(ms)}")
    if not parts:
        return why[:1].upper() + why[1:]
    head = " and ".join(parts)
    head = head[:1].upper() + head[1:]
    return f"{head}: {why}" if why else head


# ---------------------------------------------------------------------------
# Reading the log: filters, people, how long ago
# ---------------------------------------------------------------------------

def matches(ev: Event, person: Optional[str] = None, kinds: Optional[Iterable[str]] = None,
            since: Optional[float] = None, text: str = "",
            hide: Iterable[str] = ()) -> bool:
    """The Log page's filters: one person (None: everyone), some kinds
    (None: all), nothing older than `since`, the words in `text` (in the
    line or the name, any case) -- and nobody in `hide` (your avatar, when
    "Everyone but your avatar" is picked)."""
    if person is not None and ev.who != person:
        return False
    if ev.who in hide and person is None:
        return False
    if kinds is not None and ev.kind not in kinds:
        return False
    if since is not None and ev.t < since:
        return False
    if text:
        hay = f"{ev.name}\n{ev.text}".casefold()
        if not all(word in hay for word in text.casefold().split()):
            return False
    return True


@dataclass
class Person:
    """One row of "by person": who, their newest name, what they did last
    and their recent history (newest first)."""
    who: str
    name: str
    role: str
    last: Event
    count: int = 0
    shocks: int = 0                    # shocks that reached a shocker
    shocker_ops: int = 0               # ...and vibrates and beeps
    recent: List[Event] = field(default_factory=list)

    def as_dict(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = time.time() if now is None else now
        return {"who": self.who, "name": self.name, "role": self.role,
                "last": self.last.as_dict(), "ago": ago(now - self.last.t),
                "count": self.count, "shocks": self.shocks, "shocker_ops": self.shocker_ops,
                "recent": [e.as_dict() for e in self.recent]}


def by_person(events: Sequence[Event], recent_each: int = 20,
              skip_roles: Iterable[str] = ()) -> List[Person]:
    """A row per person, the one active most recently first. `events` come
    newest first; each person keeps up to `recent_each` of theirs."""
    skip = set(skip_roles)
    rows: Dict[str, Person] = {}
    for ev in events:
        if ev.role in skip:
            continue
        p = rows.get(ev.who)
        if p is None:
            p = rows[ev.who] = Person(ev.who, ev.name, ev.role, ev)
        p.count += 1
        p.shocks += ev.stands_out
        p.shocker_ops += ev.shocker_op
        if len(p.recent) < recent_each:
            p.recent.append(ev)
    return list(rows.values())        # dicts keep insertion order: newest first


def ago(seconds: float) -> str:
    """How long ago, the way a person says it."""
    s = max(0.0, float(seconds))
    if s < 10:
        return "just now"
    if s < 60:
        return f"{int(s)} s ago"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    days = int(s // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def when(t: float, now: Optional[float] = None) -> str:
    """The Log page's time column: the clock for today, the day before it
    for older."""
    now = time.time() if now is None else now
    lt = time.localtime(t)
    if time.strftime("%Y-%m-%d", lt) == time.strftime("%Y-%m-%d", time.localtime(now)):
        return time.strftime("%H:%M:%S", lt)
    return f"{lt.tm_mday} {time.strftime('%b %H:%M', lt)}"


def day_name(t: float) -> str:
    """The file an event goes to: its local day."""
    return time.strftime("%Y-%m-%d", time.localtime(t)) + ".jsonl"


def _file_day(name: str) -> Optional[Tuple[int, int, int]]:
    m = _DAY_FILE.match(name)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _oldest_kept(now: float, keep_days: int) -> Tuple[int, int, int]:
    """The first day still kept: today and the `keep_days - 1` before it."""
    lt = time.localtime(now)
    first = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday - (keep_days - 1), 12, 0, 0, 0, 0, -1))
    f = time.localtime(first)
    return (f.tm_year, f.tm_mon, f.tm_mday)


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

class EventLog:
    """The newest events in memory, the last `keep_days` days in `folder`
    (None: memory only, for a host without the files -- tests, a demo)."""

    def __init__(self, folder: Optional[os.PathLike] = None, keep_days: int = KEEP_DAYS,
                 max_memory: int = MAX_MEMORY, clock: Callable[[], float] = time.time):
        self.folder = Path(folder) if folder else None
        self.keep_days = max(1, int(keep_days))
        self._clock = clock
        self._lock = threading.Lock()          # the events and what waits for the disk
        self._io_lock = threading.Lock()       # the files
        self._events: deque = deque(maxlen=max(1, int(max_memory)))
        self._last_key: Any = None
        self._pending: List[Event] = []
        self._clear_files = False
        self._listeners: List[Callable[[Event], None]] = []
        self.version = 0                       # changes with every add / clear
        self.loaded = self.folder is None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._rotated_day = ""

    # ---- adding ---------------------------------------------------------
    def add(self, ev: Event, key: Any = None) -> bool:
        """Log `ev`. With the same `key` as the entry before it within
        COALESCE_S it replaces that entry (a slider drag is one). True for
        a new entry, False when it replaced one. Never touches the disk."""
        with self._lock:
            last = self._events[-1] if self._events else None
            if (key is not None and last is not None and key == self._last_key
                    and ev.t - last.t < COALESCE_S):
                self._events[-1] = ev
                if self.folder is not None:
                    if self._pending and self._pending[-1] is last:
                        self._pending[-1] = ev
                    else:
                        self._pending.append(ev)      # the drag's start is on disk already
                self.version += 1
                return False
            self._events.append(ev)
            self._last_key = key
            if self.folder is not None:
                self._pending.append(ev)
            self.version += 1
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(ev)
            except Exception:
                pass
        return True

    def on_add(self, fn: Callable[[Event], None]) -> None:
        """Call `fn(event)` for every new entry (not a coalesced one), on
        whatever thread adds it -- it must be quick and never block."""
        with self._lock:
            self._listeners.append(fn)

    # ---- reading --------------------------------------------------------
    def recent(self, n: Optional[int] = None,
               where: Optional[Callable[[Event], bool]] = None) -> List[Event]:
        """Newest first: up to `n` events (all with None) that pass `where`."""
        out: List[Event] = []
        with self._lock:
            for ev in reversed(self._events):
                if where is None or where(ev):
                    out.append(ev)
                    if n is not None and len(out) >= n:
                        break
        return out

    def window(self, start: float, end: Optional[float] = None,
               where: Optional[Callable[[Event], bool]] = None) -> List[Event]:
        """Oldest first: the events from `start` to `end` (None: now) that
        pass `where`. Walks back from the newest and stops at the first one
        older than `start`, so a session's stretch costs what it holds, not
        the whole log (the events are kept in time order)."""
        out: List[Event] = []
        with self._lock:
            for ev in reversed(self._events):
                if ev.t < start:
                    break
                if (end is None or ev.t <= end) and (where is None or where(ev)):
                    out.append(ev)
        out.reverse()
        return out

    def query(self, person: Optional[str] = None, kinds: Optional[Iterable[str]] = None,
              since: Optional[float] = None, text: str = "", hide: Iterable[str] = (),
              limit: Optional[int] = None) -> Tuple[List[Event], int]:
        """The Log page: the events that pass the filters (newest first, at
        most `limit`) and how many passed in all."""
        kinds = None if kinds is None else frozenset(kinds)
        hide = frozenset(hide)
        with self._lock:
            snapshot = list(self._events)
        hits = [ev for ev in reversed(snapshot)
                if matches(ev, person, kinds, since, text, hide)]
        return (hits if limit is None else hits[:limit]), len(hits)

    def clear(self) -> None:
        """Forget everything: memory now, the files on the writer's next
        pass (or the next flush)."""
        with self._lock:
            self._events.clear()
            self._pending = []
            self._last_key = None
            self._clear_files = self.folder is not None
            self.version += 1
        self._wake.set()

    # ---- the files --------------------------------------------------------
    def start(self) -> None:
        """The writer thread: loads the history, then writes and rotates."""
        if self.folder is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="event-log-writer", daemon=True)
        self._thread.start()

    def close(self, timeout: float = 2.0) -> None:
        """Write what's left and stop the writer (at quit)."""
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
        self.flush(force=True)

    def _run(self) -> None:
        try:
            self.rotate()
            self.load()
        except Exception as e:
            print(f"[log] couldn't read the log: {e}")
            self.loaded = True
        while not self._stop.is_set():
            self._wake.wait(FLUSH_S)
            self._wake.clear()
            try:
                self.flush()
                today = time.strftime("%Y-%m-%d", time.localtime(self._clock()))
                if today != self._rotated_day:
                    self.rotate()
            except Exception as e:
                print(f"[log] couldn't write the log: {e}")

    def flush(self, force: bool = False) -> int:
        """Append what came in to the day files. The newest entry waits
        while it may still be coalesced (a drag going on), unless `force`.
        Returns how many lines went out."""
        if self.folder is None:
            return 0
        now = self._clock()
        with self._lock:
            clear, self._clear_files = self._clear_files, False
            take = self._pending
            keep: List[Event] = []
            if (not force and take and self._last_key is not None and self._events
                    and take[-1] is self._events[-1] and now - take[-1].t < COALESCE_S):
                keep = [take.pop()]
            self._pending = keep
        with self._io_lock:
            if clear:
                self._delete_all()
            if not take:
                return 0
            by_day: Dict[str, List[str]] = {}
            for ev in take:
                by_day.setdefault(day_name(ev.t), []).append(
                    json.dumps(ev.to_json(), ensure_ascii=False, separators=(",", ":")))
            try:
                self.folder.mkdir(parents=True, exist_ok=True)
                for name, lines in by_day.items():
                    with open(self.folder / name, "a", encoding="utf-8", newline="\n") as f:
                        f.write("\n".join(lines) + "\n")
            except OSError as e:
                print(f"[log] couldn't write {self.folder}: {e}")
                return 0
        return len(take)

    def rotate(self, now: Optional[float] = None) -> int:
        """Drop the day files older than `keep_days` (and their events in
        memory). Returns how many files went."""
        if self.folder is None:
            return 0
        now = self._clock() if now is None else now
        first = _oldest_kept(now, self.keep_days)
        gone = 0
        with self._io_lock:
            for path in self._day_files():
                day = _file_day(path.name)
                if day is not None and day < first:
                    try:
                        path.unlink()
                        gone += 1
                    except OSError:
                        pass
        cutoff = time.mktime((first[0], first[1], first[2], 0, 0, 0, 0, 0, -1))
        with self._lock:
            if self._events and self._events[0].t < cutoff:
                self._events = deque((e for e in self._events if e.t >= cutoff),
                                     maxlen=self._events.maxlen)
                self.version += 1
        self._rotated_day = time.strftime("%Y-%m-%d", time.localtime(now))
        return gone

    def load(self) -> int:
        """Read the kept days into memory, older than anything added since
        the start. Returns how many events it read."""
        if self.folder is None:
            return 0
        cap = self._events.maxlen or MAX_MEMORY
        first = _oldest_kept(self._clock(), self.keep_days)
        read: List[Event] = []
        with self._io_lock:
            files = sorted(self._day_files(), key=lambda p: p.name, reverse=True)
            for path in files:
                day = _file_day(path.name)
                if day is None or day < first:
                    continue
                events = _read_file(path)
                read = events + read
                if len(read) >= cap:
                    break
        read.sort(key=lambda e: e.t)
        with self._lock:
            self._events = deque(read + list(self._events), maxlen=self._events.maxlen)
            self.loaded = True
            self.version += 1
        return len(read)

    def _day_files(self) -> List[Path]:
        try:
            return [p for p in self.folder.iterdir()
                    if p.is_file() and _file_day(p.name) is not None]
        except OSError:
            return []

    def _delete_all(self) -> None:
        for path in self._day_files():
            try:
                path.unlink()
            except OSError:
                pass


def _read_file(path: Path) -> List[Event]:
    out: List[Event] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    ev = Event.from_json(d)
                    if ev is not None:
                        out.append(ev)
    except OSError:
        pass
    return out
