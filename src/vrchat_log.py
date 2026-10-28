"""Who is in your VRChat instance — read from VRChat's own log (opt-in).

VRChat writes a log file per run, ``output_log_<date>_<time>.txt``, in
``%LOCALAPPDATA%Low\\VRChat\\VRChat`` (on Linux inside the Proton prefix).
The lines that matter, as VRChat writes them today::

    2026.10.07 11:33:12 Debug      -  User Authenticated: Name (usr_…)
    2026.10.07 11:33:16 Debug      -  [Behaviour] Joining wrld_…:27326~private(…)
    2026.10.07 11:33:27 Debug      -  [Behaviour] OnPlayerJoined Name (usr_…)
    2026.10.07 11:36:01 Debug      -  [Behaviour] OnPlayerLeft Name (usr_…)
    2026.10.07 11:42:16 Debug      -  [Behaviour] OnLeftRoom
    2026.10.06 21:09:47 Debug      -  [Behaviour] Initialized PlayerAPI "Name" is local

`InstanceTracker` turns those into the set of people in the current
instance (you included, VRChat logs your own join too). `LogWatcher` runs
it on a small background thread that follows the newest log file, so
reading a log of a few hundred MB at launch never stalls the GUI thread —
the routing tick lives there. Nothing is written anywhere; the only
consumer is the people facade, and only while the user has switched the
option on.

Older VRChat builds wrote ``OnPlayerJoined Name`` without the user id;
then the name is the key.
"""

import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# "2026.10.07 11:33:12" at the start of every line.
_TS_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) (\d{2}):(\d{2}):(\d{2})")
_PLAYER_RE = re.compile(
    r"\[Behaviour\] OnPlayer(Joined|Left) (.+?)(?: \((usr_[0-9a-fA-F-]+)\))?\s*$")
_AUTH_RE = re.compile(r"User Authenticated: (.+?) \((usr_[0-9a-fA-F-]+)\)")
_LOCAL_RE = re.compile(r'\[Behaviour\] Initialized PlayerAPI "(.+)" is local')
_ROOM_MARKERS = ("[Behaviour] Joining wrld_", "[Behaviour] OnLeftRoom")

_LOG_GLOB = "output_log_*.txt"

# Read at most this much per pass, then let other threads run.
_CHUNK_BYTES = 1 << 20

# How often the watcher looks for new lines, and for a newer log file.
_POLL_S = 1.0
_NEW_FILE_EVERY_S = 5.0


def _line_epoch(line: str) -> Optional[float]:
    m = _TS_RE.match(line)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    try:
        return time.mktime((y, mo, d, h, mi, s, 0, 0, -1))
    except (OverflowError, ValueError):
        return None


class InstanceTracker:
    """Who is in the instance, from the log lines fed in order.

    `players` maps a key (VRChat user id, or the name on old logs) to the
    display name; it includes you. `changed_at` is the log time of the last
    change to who is there (None until the first one)."""

    def __init__(self) -> None:
        self.local_id = ""
        self.local_name = ""
        self.players: Dict[str, str] = {}
        self.changed_at: Optional[float] = None
        self.in_room = False

    def feed(self, line: str) -> bool:
        """One log line. True when it changed who is there."""
        if "[Behaviour]" not in line and "User Authenticated" not in line:
            return False
        if "OnPlayer" in line:
            m = _PLAYER_RE.search(line)
            if not m:
                return False
            kind, name, uid = m.group(1), m.group(2).strip(), m.group(3) or ""
            key = uid or name
            if kind == "Joined":
                if self.players.get(key) == name:
                    return False
                self.players[key] = name
            else:
                if key not in self.players:
                    return False
                del self.players[key]
            self._stamp(line)
            return True
        if any(marker in line for marker in _ROOM_MARKERS):
            self.in_room = "Joining" in line
            had = bool(self.players)
            self.players = {}
            if had or self.in_room:
                self._stamp(line)
            return had
        m = _AUTH_RE.search(line)
        if m:
            self.local_name, self.local_id = m.group(1).strip(), m.group(2)
            return False
        m = _LOCAL_RE.search(line)
        if m:
            self.local_name = m.group(1).strip()
        return False

    def _stamp(self, line: str) -> None:
        t = _line_epoch(line)
        if t is not None:
            self.changed_at = t

    def _is_local(self, key: str, name: str) -> bool:
        if self.local_id:
            return key == self.local_id
        return bool(self.local_name) and name == self.local_name

    def others(self) -> List[Tuple[str, str]]:
        """Everyone in the instance but you: (key, name), by name."""
        return sorted(((k, n) for k, n in self.players.items()
                       if not self._is_local(k, n)),
                      key=lambda kn: kn[1].casefold())


def log_dirs() -> List[Path]:
    """Where VRChat keeps its logs on this system (candidates, may not
    exist)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            return []
        return [Path(base).parent / "LocalLow" / "VRChat" / "VRChat"]
    home = Path.home()
    tail = Path("steamapps/compatdata/438100/pfx/drive_c/users/steamuser/"
                "AppData/LocalLow/VRChat/VRChat")
    return [home / ".steam/steam" / tail,
            home / ".local/share/Steam" / tail,
            home / ".var/app/com.valvesoftware.Steam/.local/share/Steam" / tail]


def newest_log(dirs: Optional[List[Path]] = None) -> Optional[Path]:
    """The most recently written VRChat log file, or None."""
    best: Optional[Tuple[float, Path]] = None
    for d in (log_dirs() if dirs is None else dirs):
        try:
            for p in d.glob(_LOG_GLOB):
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if best is None or m > best[0]:
                    best = (m, p)
        except OSError:
            continue
    return best[1] if best else None


class LogWatcher:
    """Follows the newest VRChat log on a daemon thread and publishes who
    is in the instance. `snapshot()` is safe to call from any thread: it
    returns the last published dict, replaced whole on every change.

    Snapshot keys: ``state`` ("starting" / "no_log" / "reading" / "ok"),
    ``file`` (its name), ``others`` ([(key, name)] — everyone but you),
    ``since`` (log time of the last change), ``in_room``."""

    def __init__(self, dirs: Optional[List[Path]] = None,
                 poll_s: float = _POLL_S) -> None:
        self._dirs = dirs
        self._poll_s = float(poll_s)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._snap: Dict[str, Any] = {"state": "starting", "file": "",
                                      "others": [], "since": None,
                                      "in_room": False}

    def snapshot(self) -> Dict[str, Any]:
        return self._snap

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="vrchat-log",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)
        self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------

    def _publish(self, state: str, path: Optional[Path],
                 tracker: Optional[InstanceTracker]) -> None:
        snap = {"state": state, "file": path.name if path else "",
                "others": tracker.others() if tracker else [],
                "since": tracker.changed_at if tracker else None,
                "in_room": bool(tracker and tracker.in_room)}
        if snap != self._snap:
            self._snap = snap

    def _run(self) -> None:
        path: Optional[Path] = None
        tracker: Optional[InstanceTracker] = None
        pos = 0
        tail = b""
        last_scan = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if path is None or now - last_scan >= _NEW_FILE_EVERY_S:
                last_scan = now
                newest = newest_log(self._dirs)
                if newest is None:
                    path, tracker = None, None
                    self._publish("no_log", None, None)
                    self._stop.wait(_NEW_FILE_EVERY_S)
                    continue
                if newest != path:
                    # A new VRChat run: start over from its first line.
                    path, tracker, pos, tail = newest, InstanceTracker(), 0, b""
            caught_up = True
            try:
                with open(path, "rb") as f:
                    size = os.fstat(f.fileno()).st_size
                    if size < pos:
                        # Truncated or replaced: read it again.
                        tracker, pos, tail = InstanceTracker(), 0, b""
                    f.seek(pos)
                    data = f.read(_CHUNK_BYTES)
                    pos += len(data)
                    caught_up = pos >= size
            except OSError:
                data = b""
            if data:
                lines = (tail + data).split(b"\n")
                tail = lines.pop()
                for raw in lines:
                    # Almost every line is something else; skip those
                    # before paying for a decode.
                    if b"[Behaviour]" in raw or b"User Authenticated" in raw:
                        tracker.feed(raw.decode("utf-8", "replace").rstrip("\r"))
            self._publish("ok" if caught_up else "reading", path, tracker)
            if caught_up:
                self._stop.wait(self._poll_s)
            else:
                time.sleep(0)    # a long backlog: let the GUI thread in


def companion(snap: Dict[str, Any]) -> Optional[Tuple[str, str, Optional[float]]]:
    """(key, name, since) of the one other person when the log says you
    are alone with exactly one, else None."""
    if snap.get("state") != "ok":
        return None
    others = snap.get("others") or []
    if len(others) != 1:
        return None
    key, name = others[0]
    return key, name, snap.get("since")
