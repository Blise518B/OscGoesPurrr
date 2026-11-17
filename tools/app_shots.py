"""Real screenshots of OGP's pages -- the actual main window, sidebar and all,
on believable demo content -- for the VRChat group's pictures.

It builds the real `ui_components.OscGoesPurrrUI` offscreen on a
`DemoController` defined here: a plain class that answers the UI's facade
calls with data in the real getters' shapes (src/controllers/*_facade.py,
src/main.py, and the tests' fakes), so nothing opens OSC, a serial port,
Bluetooth, iroh or any socket, and no settings manager is ever built.

    from app_shots import open_app
    shots = open_app(1280, 800)
    img = shots.page("Friends")                 # QImage of the whole window
    img = shots.page("Friends", scroll="Pause all friends")   # scrolled to it
    rect = shots.anchor("Friends", "Pause all friends")   # QRect | None
    every = shots.anchors("Shockers")           # {title: QRect}
    shots.ui                                    # the OscGoesPurrrUI itself

    python tools/app_shots.py --dump <dir>      # a PNG + <page>.anchors.txt per page

Page names are the keys of `shots.ui.views` ("Home", "Toys", "Friends", "My
Avatar Remote", "Shockers", "Suits", "Statistics", ...); a unique part of one
works too ("Avatar Remote"). Anchors are the app's hover explanations
(src/ui/tooltips.py `tip_html`): a widget whose toolTip() starts with
"<b>Title</b>". Their rectangles are in window coordinates, the visible
part only, at the page's current scroll -- handy arrow targets.

Safety: an audit hook refuses every write, rename or delete under the
app's settings folder (%APPDATA%\\OscGoesPurrr), every socket connect /
bind / send and every child process except version.py's read-only git
queries, for the whole process; the window never shows on screen
(offscreen platform, WA_DontShowOnScreen) and modal dialogs return at
once. `--dump` also compares the settings folder's mtimes before and after
and says what changed. Run it with the venv's Python from anywhere.
"""

import argparse
import html
import math
import os
import random
import re
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

# ---- environment: before any Qt import ---------------------------------
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
os.environ["OGP_UI_ACCENT"] = "default"
os.environ["OGP_UI_MODE"] = "neon"
os.environ.pop(  # the app's own example friends come from here, not the env
    "OGP_FRIENDS_DEMO", None)
# Offscreen Qt on Windows sees no system font at all: every label would fall
# back to the one bundled face (Aldrich) and emoji / symbols (🔋 ▸ ＋ ↻)
# would vanish. The real app (the "windows" platform) has them all.
if sys.platform == "win32" and not os.environ.get("QT_QPA_FONTDIR"):
    _fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.isdir(_fonts):
        os.environ["QT_QPA_FONTDIR"] = _fonts
sys.dont_write_bytecode = True        # leave src/__pycache__ alone

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
if str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))


# ========================================================================
# The guard: no settings writes, no network, no child processes
# ========================================================================

def _settings_dirs():
    """Where OGP keeps its settings (src/settings/_paths.py, both OSes)."""
    home = Path.home()
    out = [home / "AppData" / "Roaming" / "OscGoesPurrr"]
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    out.append((Path(xdg) if xdg and os.path.isabs(xdg) else home / ".config") / "OscGoesPurrr")
    return [os.path.normcase(os.path.abspath(str(p))) for p in out]


_GUARDED = _settings_dirs()
BLOCKED = []                           # what the guard refused, in order

_WRITE_FLAGS = (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC)
_PATH_EVENTS = {"os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.utime",
                "os.chmod", "os.chown", "os.symlink", "os.link", "shutil.rmtree"}
_TWO_PATH_EVENTS = {"os.rename", "shutil.copyfile", "shutil.copytree", "shutil.move",
                    "shutil.copymode", "shutil.copystat"}
_NET_EVENTS = {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}
_PROC_EVENTS = {"subprocess.Popen", "os.system", "os.startfile", "os.spawn", "os.exec",
                "os.posix_spawn", "os.fork"}
# version.py asks git for the branch and the build number (the sidebar's
# "b<n>"): read-only, windowless (CREATE_NO_WINDOW), so let those through.
_GIT_READS = {"rev-parse", "rev-list"}


def _git_read(args) -> bool:
    cmd = args[1] if len(args) > 1 else None
    if isinstance(cmd, (str, bytes)):              # Windows hands over the command line
        cmd = os.fsdecode(cmd).split()
    if not isinstance(cmd, (list, tuple)) or len(cmd) < 2:
        return False
    exe = os.path.basename(os.fsdecode(cmd[0])).lower()
    return exe in ("git", "git.exe") and cmd[1] in _GIT_READS


def _guarded(path) -> bool:
    if path is None or isinstance(path, int):
        return False
    try:
        p = os.path.normcase(os.path.abspath(os.fsdecode(path)))
    except Exception:
        return False
    return any(p == d or p.startswith(d + os.sep) for d in _GUARDED)


def _refuse(what: str) -> None:
    BLOCKED.append(what)
    print(f"[app_shots] GUARD refused: {what}", flush=True)
    raise PermissionError(f"app_shots guard: {what}")


def _audit(event, args):
    if event == "open":
        path, mode, flags = (tuple(args) + (None, None, None))[:3]
        if isinstance(mode, str):
            writes = any(c in mode for c in "wax+")
        else:
            writes = bool(isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writes and _guarded(path):
            _refuse(f"open({path!r}, {mode or flags!r})")
    elif event in _PATH_EVENTS:
        if args and _guarded(args[0]):
            if event == "os.mkdir" and os.path.isdir(args[0]):
                # settings/_paths.py makes sure the folder exists: it does,
                # so answer what the OS would, and nothing is refused
                raise FileExistsError(17, "File exists", args[0])
            _refuse(f"{event}({args[0]!r})")
    elif event in _TWO_PATH_EVENTS:
        if any(_guarded(a) for a in args[:2]):
            _refuse(f"{event}{tuple(args[:2])!r}")
    elif event in _NET_EVENTS:
        _refuse(f"{event} {args[1:]!r}")
    elif event in _PROC_EVENTS:
        if not (event == "subprocess.Popen" and _git_read(args)):
            _refuse(f"{event} {args[:2]!r}")


sys.addaudithook(_audit)


def settings_mtimes() -> dict:
    """{path: mtime_ns} for every file in OGP's settings folder."""
    out = {}
    for d in _GUARDED:
        if not os.path.isdir(d):
            continue
        for root, _dirs, files in os.walk(d):
            for name in files:
                p = os.path.join(root, name)
                try:
                    out[p] = os.stat(p).st_mtime_ns
                except OSError:
                    pass
    return out


def mtime_changes(before: dict, after: dict) -> list:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


# ---- Qt, then the app (flat imports, like the app) ----------------------
from PySide6.QtCore import QEventLoop, QPoint, QRect, Qt          # noqa: E402
from PySide6.QtGui import QFont, QImage                          # noqa: E402
from PySide6.QtWidgets import (                                  # noqa: E402
    QAbstractButton, QApplication, QDialog, QFileDialog, QInputDialog, QLabel, QLineEdit,
    QMenu, QMessageBox, QWidget,
)


def _neutralise_modals() -> None:
    """Nothing may sit there waiting for a click."""
    QDialog.exec = lambda self, *a, **k: 0
    QMessageBox.exec = lambda self, *a, **k: 0
    for name, answer in (("question", QMessageBox.No), ("warning", QMessageBox.No),
                         ("information", QMessageBox.Ok), ("critical", QMessageBox.Ok)):
        setattr(QMessageBox, name, staticmethod(lambda *a, _r=answer, **k: _r))
    QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))
    QInputDialog.getInt = staticmethod(lambda *a, **k: (0, False))
    QInputDialog.getDouble = staticmethod(lambda *a, **k: (0.0, False))
    QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
    QMenu.exec = lambda self, *a, **k: None
    for name in ("getOpenFileName", "getSaveFileName", "getExistingDirectory"):
        setattr(QFileDialog, name, staticmethod(lambda *a, **k: ("", "")))


# ========================================================================
# Demo content
# ========================================================================

NICK = "Blise"
AVATAR_ID = "avtr_6a1f3c2e-4b7d-4e19-9c55-518c0ffee518"
MY_ID = "b115e518" + "7c" * 28
VRCHAT_PORT = 9001

# name: (motor count, connected, battery 0..1, live levels, zones per motor)
TOYS = {
    "Lovense Lush 3": (1, True, 0.86, (0.72,), ("Ring",)),
    "Lovense Edge 2": (2, True, 0.64, (0.58, 0.31), ("Hole", "Hole")),
    "We-Vibe Chorus": (1, False, None, (0.0,), (None,)),
}

SHOCKERS = [{"id": 24325, "name": "Collar"}, {"id": 24326, "name": "Thigh"}]

DETECTED_ZONES = {"Orifices": ["Ring", "Hole", "Mouth"],
                  "Penetrators": ["Tail"],
                  "Touch": ["Headpat", "Neck", "ThighL"]}

# Avatar Remote: the worn avatar's board -- (category id, name, colour, locked)
BOARD_CATS = [("outfit", "Outfit", "purple", False),
              ("toggles", "Toggles", "cyan", False),
              ("fun", "Fun", "amber", True)]


def _ctl(cid, param, kind, cat, ptype, label=None, **extra):
    return dict({"id": cid, "param": param, "kind": kind, "cat": cat, "ptype": ptype,
                 "label": label or param}, **extra)


BOARD_CONTROLS = [
    _ctl("k1", "Outfit", "toggle", "outfit", "Int", "Hoodie", on=1, off=0),
    _ctl("k2", "Outfit", "toggle", "outfit", "Int", "Kimono", on=2, off=0),
    _ctl("k3", "Outfit", "toggle", "outfit", "Int", "Swimsuit", on=3, off=0),
    _ctl("k4", "Glasses", "toggle", "toggles", "Bool"),
    _ctl("k5", "TailWag", "toggle", "toggles", "Bool", "Tail wag"),
    _ctl("k6", "EarsDown", "toggle", "toggles", "Bool", "Ears down"),
    _ctl("k7", "Blush", "slider", "toggles", "Float", min=0.0, max=1.0),
    _ctl("k8", "Emote", "button", "fun", "Int", "Wave", on=3, off=0),
    _ctl("k9", "HueShift", "slider", "fun", "Float", "Hue shift", min=0.0, max=1.0),
    _ctl("k10", "Particles", "int", "fun", "Int", min=0.0, max=8.0),
]

BOARD_VALUES = {"Outfit": 2, "Glasses": True, "TailWag": True, "EarsDown": False,
                "Blush": 0.45, "Emote": 0, "HueShift": 0.62, "Particles": 3,
                "VelocityX": 0.0, "Grounded": True, "AFK": False, "Seated": False,
                "MuteSelf": False, "EyeHeightAsMeters": 1.48, "OGP/Strength": 0.7,
                "TongueOut": False, "FaceShy": 0.0, "ScaleFactor": 1.0}

BOARD_TYPES = {"Outfit": "Int", "Glasses": "Bool", "TailWag": "Bool", "EarsDown": "Bool",
               "Blush": "Float", "Emote": "Int", "HueShift": "Float", "Particles": "Int",
               "TongueOut": "Bool", "FaceShy": "Float", "ScaleFactor": "Float",
               "OGP/Strength": "Float"}


class _MemoryBoards:
    """BoardBook's store (load / save / list_profiles) in memory only --
    never settings/param_boards.py's file."""

    def __init__(self):
        self.avatars = {}

    def load(self, avatar_id):
        return self.avatars.get(str(avatar_id))

    def save(self, profile):
        if profile.get("avatar_id"):
            self.avatars[profile["avatar_id"]] = profile

    def list_profiles(self):
        return sorted(({"avatar_id": a, "name": p.get("name") or a, "named": True}
                       for a, p in self.avatars.items()), key=lambda e: e["name"].lower())


class _Router:
    """motor_router as the UI sees it: subscriptions that never fire."""

    last_outputs = {}

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


def _local_ts(day: datetime, hour: int, minute: int) -> float:
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def _demo_stats(now: float) -> dict:
    """Sessions, hourly history and lifetime totals in the facade's shapes
    (controllers/stats_facade.py), made up but consistent with each other."""
    import stats_history as sh

    rng = random.Random(518)
    today = datetime.fromtimestamp(now)
    toy_names = list(TOYS)
    zone_keys = ["Orf/Ring", "Orf/Hole", "Orf/Mouth", "Touch/Headpat", "Pen/Tail"]
    friends = ["Mika", "Kiko", "Nova", "Rin", "Sam"]
    hours = {}
    rows = []

    def add_hours(start: float, dur: float, active: float, thrusts: int) -> None:
        t, end = start, start + dur
        while t < end:
            nxt = min(end, (math.floor(t / 3600) + 1) * 3600)
            share = (nxt - t) / dur
            key = sh.hour_key(t)
            a, n = hours.get(key, (0.0, 0))
            hours[key] = (a + active * share, n + int(round(thrusts * share)))
            t = nxt

    def spark(n: int = sh.SPARK_POINTS):
        out, v = [], rng.uniform(0.1, 0.4)
        for _ in range(n):
            v = max(0.0, min(1.0, v + rng.uniform(-0.18, 0.2)))
            out.append(round(v, 3))
        return out

    # ~10 weeks back, evenings, more at weekends
    for days_ago in range(70, 0, -1):
        day = today - timedelta(days=days_ago)
        if rng.random() > (0.62 if day.weekday() >= 4 else 0.34):
            continue
        start = _local_ts(day, rng.choice((19, 20, 21, 21, 22, 23)), rng.randrange(0, 60))
        dur = rng.uniform(35, 140) * 60
        active = dur * rng.uniform(0.35, 0.7)
        pace = rng.uniform(28, 46)
        thrusts = int(active / 60 * pace)
        add_hours(start, dur, active, thrusts)
        who = rng.sample(friends, rng.choice((0, 1, 1, 1, 2)))
        on = {n: round(active * rng.uniform(0.5, 1.0)) for n in rng.sample(toy_names, 2)}
        zones = {z: round(active * rng.uniform(0.2, 0.9)) for z in rng.sample(zone_keys, 3)}
        rows.append({"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(start)),
                     "kind": "timeline", "timeline": True, "started_ts": start,
                     "ended_ts": start + dur, "duration_s": dur, "active_s": active,
                     "thrusts": thrusts, "peak_pace": int(pace * 1.6), "recovered": False,
                     "spark": spark(), "toys": on, "zones": zones,
                     "people": who, "whole_people": who})

    # the running one
    start = now - 42 * 60
    live_active, live_thrusts = 21 * 60.0, 812
    add_hours(start, now - start, live_active, live_thrusts)
    live = {"id": time.strftime("%Y%m%d-%H%M%S", time.localtime(start)), "kind": "live",
            "timeline": True, "started_ts": start, "ended_ts": None,
            "duration_s": now - start, "active_s": live_active, "thrusts": live_thrusts,
            "peak_pace": 61, "recovered": False, "spark": spark(30),
            "toys": {"Lovense Lush 3": 1180.0, "Lovense Edge 2": 960.0},
            "zones": {"Orf/Ring": 840.0, "Touch/Headpat": 130.0},
            "people": ["Mika"], "whole_people": ["Mika"]}
    rows.append(live)
    rows.sort(key=lambda r: r["started_ts"], reverse=True)

    life_toys, life_zones = {}, {}
    for r in rows:
        for k, v in r["toys"].items():
            life_toys.setdefault(k, {"on_s": 0.0})["on_s"] += v
        for k, v in r["zones"].items():
            life_zones.setdefault(k, {"contact_s": 0.0})["contact_s"] += v
    lifetime = {"active_s": sum(r["active_s"] for r in rows),
                "thrusts": sum(int(r["thrusts"]) for r in rows),
                "sessions": len(rows), "toys": life_toys, "zones": life_zones}
    session = {"started_ts": start, "active_s": live_active, "thrusts": live_thrusts,
               "toys": {k: {"on_s": v} for k, v in live["toys"].items()},
               "zones": {k: {"contact_s": v} for k, v in live["zones"].items()}}

    people = {}
    for r in rows:
        for name in r["people"]:
            p = people.setdefault(name, {"name": name, "sessions": 0, "active_s": 0.0,
                                         "thrusts": 0, "peak_pace": 0, "last_ts": 0.0})
            p["sessions"] += 1
            p["active_s"] += r["active_s"]
            p["thrusts"] += int(r["thrusts"])
            p["peak_pace"] = max(p["peak_pace"], int(r["peak_pace"]))
            p["last_ts"] = max(p["last_ts"], r["started_ts"])
    table = sorted(people.values(), key=lambda p: -p["thrusts"])
    return {"hours": hours, "rows": rows, "lifetime": lifetime, "session": session,
            "people": table}


# ========================================================================
# The controller
# ========================================================================

def _demo_event_log(now: float):
    """The log's demo entries (event_log.Event), memory only: friends from
    friends_demo, a web remote guest, your avatar's shocker behaviours and
    a few switches of your own -- the Log page and Friends' By person."""
    import event_log as el
    import friends_demo
    ids = {f["nick"]: f["id"] for f in friends_demo._FRIENDS}
    rows = [
        # seconds ago, who, name, role, kind, op, dir, level, ms, on, held, text
        (2 * 86400, "you", "You", "you", el.LINK, "online", "", None, None, (), "",
         "You went online"),
        (26 * 3600, ids["Kiko"], "Kiko", "friend", el.SHOCK, "vibrate", el.IN, 20, 800,
         ("Collar",), "", "Kiko: vibrate 20 · 0.8 s on Collar"),
        (5 * 3600, "avatar", "Your avatar", "avatar", el.SHOCK, "shock", el.IN, 15, 300,
         ("Collar",), "", "Your avatar (Contact · Tap): shock 15 · 0.3 s on Collar",
         "Contact · Tap"),
        (4 * 3600, ids["Nova"], "Nova", "friend", el.PARAMS, "set", el.IN, None, None, (), "",
         "Nova turned your Tail wag on"),
        (2 * 3600, ids["Nova"], "Nova", "friend", el.SHOCK, "shock", el.IN, None, None, (),
         "your shockers aren't shared with friends",
         "Nova tried to shock you - held back: your shockers aren't shared with friends"),
        (3000, "web-sam", "Sam (web)", "web", el.LINK, "online", el.IN, None, None, (), "",
         "Sam opened your web remote"),
        (2400, "web-sam", "Sam (web)", "web", el.TOYS, "start", el.IN, None, None, (), "",
         "Sam (web) started driving your toys"),
        (1500, ids["Kiko"], "Kiko", "friend", el.LINK, "online", "", None, None, (), "",
         "Kiko is online"),
        (900, ids["Mika"], "Mika", "friend", el.LINK, "online", "", None, None, (), "",
         "Mika is online"),
        (600, ids["Mika"], "Mika", "friend", el.TOYS, "start", el.IN, None, None, (), "",
         "Mika started driving your toys"),
        (420, ids["Mika"], "Mika", "friend", el.TOYS, "strength", el.IN, 70, None, (), "",
         "Mika set your strength to 70 %"),
        (2100, "avatar", "Your avatar", "avatar", el.SHOCK, "vibrate", el.IN, 15, 500,
         ("Collar",), "", "Your avatar (Touch zones · Neck): vibrate 15 · 0.5 s on Collar",
         "Touch zones · Neck"),
        # asked for 2.0 s, sent Collar's longest pulse: the Log's muted line
        (1800, ids["Mika"], "Mika", "friend", el.SHOCK, "vibrate", el.IN, 30, 1000,
         ("Collar",), "", "Mika: vibrate 30 · 2.0 s on Collar", "", "",
         {"asked_ms": 2000, "fixed": "your longest pulse"}),
        (1320, "__me__", "You (Me)", "me", el.SHOCK, "shock", el.IN, 10, 300,
         ("Thigh",), "", "You (Me): shock 10 · 0.3 s on Thigh", el.VIA_MENU),
        (1200, "avatar", "Your avatar", "avatar", el.SHOCK, "vibrate", el.IN, 18, 500,
         ("Collar",), "", "Your avatar (Touch zones · Neck): vibrate 18 · 0.5 s on Collar",
         "Touch zones · Neck"),
        (300, "avatar", "Your avatar", "avatar", el.SHOCK, "hold", el.IN, 12, None,
         ("Collar",), "", "Your avatar (Continuous · Prox) is holding vibrate 12 on Collar",
         "Continuous · Prox", "vibrate"),
        (288, "avatar", "Your avatar", "avatar", el.SHOCK, "let-go", el.IN, 22, 12000,
         ("Collar",), "",
         "Your avatar (Continuous · Prox) let go of Collar after 12.0 s (up to vibrate 22)",
         "Continuous · Prox", "vibrate"),
        (180, ids["Mika"], "Mika", "friend", el.SHOCK, "shock", el.IN, 25, 500,
         ("Collar", "Thigh"), "", "Mika: shock 25 · 0.5 s on Collar, Thigh"),
        (95, ids["Mika"], "Mika", "friend", el.TOYS, "strength", el.OUT, 55, None, (), "",
         "You set Mika's strength to 55 %"),
        (40, ids["Kiko"], "Kiko", "friend", el.SHOCK, "beep", el.IN, None, None,
         ("Collar",), "", "Kiko: beep · 0.3 s on Collar"),
    ]
    log = el.EventLog(None)
    # oldest first, as the log keeps them (with your avatar's behaviour, the
    # menu or Party Mode -- and what a hold plays -- where a row says)
    for ago, who, name, role, kind, op, d, lvl, ms, on, held, text, *more in sorted(
            rows, key=lambda r: -r[0]):
        via, asked, extra = (list(more) + ["", "", {}][len(more):])[:3]
        log.add(el.Event(now - ago, text, who, name, role, kind, op, d, lvl, ms, on, held,
                         asked, via, **extra))
    return log


def _demo_whom(now: float, log, stats: dict):
    """From whom (stats_events.StatsEvents, memory only): the log's demo
    entries counted into the running session, on top of ten weeks of made-up
    older ones -- friends, your avatar's behaviours, you from your avatar
    menu and Party Mode, a web remote guest -- and the suits' on-time."""
    import event_log as el
    import friends_demo
    import stats_events as se
    store = se.StatsEvents(None)
    rng = random.Random(1518)
    ids = {f["nick"]: f["id"] for f in friends_demo._FRIENDS}
    live = next(r for r in stats["rows"] if r["kind"] == "live")
    olds = [r for r in stats["rows"] if r["kind"] != "live"]
    who = [(ids["Mika"], "Mika", el.ROLE_FRIEND, ""), (ids["Kiko"], "Kiko", el.ROLE_FRIEND, ""),
           (ids["Nova"], "Nova", el.ROLE_FRIEND, ""),
           ("avatar", "Your avatar", el.ROLE_AVATAR, "Touch zones · Neck"),
           ("avatar", "Your avatar", el.ROLE_AVATAR, "Contact · Tap"),
           ("avatar", "Your avatar", el.ROLE_AVATAR, "Impact · Butt"),
           ("__me__", "You (Me)", el.ROLE_ME, el.VIA_MENU),
           ("__me__", "You (Me)", el.ROLE_ME, el.VIA_PARTY),
           ("web-sam", "Sam (web)", el.ROLE_WEB, "")]
    weights = [9, 5, 3, 8, 4, 2, 2, 1, 2]
    for r in olds:
        t = r["started_ts"] + 60
        for _ in range(rng.randrange(0, 14)):
            peer, name, role, via = rng.choices(who, weights)[0]
            op = rng.choices(("shock", "vibrate", "beep"), (4, 7, 1))[0]
            lvl = None if op == "beep" else rng.randrange(8, 46)
            on = (rng.choice(("Collar", "Thigh")),)
            t += rng.uniform(20, 300)
            store.count(el.Event(t, "", peer, name, role, el.SHOCK, op, el.IN, lvl,
                                 rng.choice((300, 500, 800, 1000)), on, "", "", via),
                        r["id"], r["started_ts"])
        for peer, name in ((ids["Mika"], "Mika"), (ids["Kiko"], "Kiko")):
            if rng.random() < 0.4:
                t0 = r["started_ts"] + rng.uniform(60, 600)
                for op, at in (("start", t0), ("stop", t0 + rng.uniform(120, 1500))):
                    store.count(el.Event(at, "", peer, name, el.ROLE_FRIEND, el.TOYS, op,
                                         el.IN), r["id"], r["started_ts"])
        if rng.random() < 0.3:
            for _ in range(rng.randrange(1, 9)):
                store.count(el.Event(r["started_ts"] + 90, "", ids["Nova"], "Nova",
                                     el.ROLE_FRIEND, el.PARAMS, "set", el.IN),
                            r["id"], r["started_ts"])
        if rng.random() < 0.5:
            store.add_worn(r["id"], r["started_ts"], r["active_s"] * rng.uniform(0.2, 0.6),
                           ["bHaptics Vest"])
        if rng.random() < 0.25:
            store.add_worn(r["id"], r["started_ts"], r["active_s"] * 0.3, ["Tracker · Hips"])
    for ev in log.window(live["started_ts"]):
        store.count(ev, live["id"], live["started_ts"])
    for peer, name, role in ((ids["Mika"], "Mika", el.ROLE_FRIEND),
                             ("web-sam", "Sam (web)", el.ROLE_WEB)):
        store.count(el.Event(now - 60, "", peer, name, role, el.TOYS, "stop", el.IN),
                    live["id"], live["started_ts"])
    store.add_worn(live["id"], live["started_ts"], 640.0, ["bHaptics Vest"])
    return store


def _demo_live_detail(now: float, stats: dict, store, log):
    """The running session's page: a made-up timeline in the history's own
    shape (stats_history), with its counts and the log's marks."""
    import stats_events as se
    import stats_history as sh
    live = next(r for r in stats["rows"] if r["kind"] == "live")
    rng = random.Random(42)
    tl = {"id": live["id"], "started_ts": live["started_ts"], "ended_ts": None,
          "bucket_s": sh.BUCKET_S, "recovered": False, "gated": 1, "buckets": {}}
    n = int((now - live["started_ts"]) // sh.BUCKET_S)
    lush = edge = 0.3
    for i in range(6, n):
        if 120 <= i < 140:
            continue                               # a break
        lush = max(0.0, min(1.0, lush + rng.uniform(-0.12, 0.13)))
        edge = max(0.0, min(1.0, edge + rng.uniform(-0.1, 0.1)))
        tl["buckets"][i] = {"a": 10.0, "t": rng.randrange(0, 9),
                            "y": {"Lovense Lush 3": [10.0, 10.0 * lush],
                                  "Lovense Edge 2": [10.0, 10.0 * edge]},
                            "z": {"Orf/Ring": 10.0} if i % 7 < 4 else {}}
    out = sh.summarize(tl, now)
    out.update(kind="live", timeline=True, bucket_s=sh.BUCKET_S, dense=sh.dense(tl),
               analysis=sh.analyse(tl), tags=[])
    out["shocks"] = {"tally": store.session_view(live["id"]),
                     "marks": se.marks(log.window(live["started_ts"]))}
    return out


def _loud(cls):
    """Every public method prints its traceback before the UI's own
    try/except can swallow it -- no page fails silently."""
    for name, fn in list(vars(cls).items()):
        if name.startswith("_") or not callable(fn) or isinstance(fn, (staticmethod, classmethod)):
            continue

        def wrap(f=fn, n=name):
            def inner(self, *a, **k):
                try:
                    return f(self, *a, **k)
                except Exception:
                    print(f"[app_shots] DemoController.{n} raised:", flush=True)
                    traceback.print_exc()
                    raise
            inner.__name__ = n
            inner.__doc__ = f.__doc__
            return inner
        setattr(cls, name, wrap())
    return cls


# Made-up VRChat accounts: who's in your instance, and your VRCX friends
VRC_INSTANCE = [("usr_00000001-0000-4000-8000-000000000001", "MikaPaws"),
                ("usr_00000002-0000-4000-8000-000000000002", "Juno"),
                ("usr_00000003-0000-4000-8000-000000000003", "Pixelfox")]
VRC_VRCX = [(f"usr_{n:08x}-0000-4000-8000-{n:012x}", name) for n, name in enumerate(
    ("Kiko~", "NovaStar", "Rinny", "Ash", "Bea", "Calla", "Dax", "Echo", "Fern", "Gale",
     "Hex", "Ivy", "Jet", "Koi", "Lux", "Moss"), start=16)]


@_loud
class DemoController:
    """The controller facade the UI talks to, answered from demo data.

    Getters return the real facades' shapes; setters change the demo state
    in memory; anything not listed is a no-op (named once on stdout, so a
    page that wants a shape it doesn't get is easy to spot)."""

    is_debugging_osc = False
    FEATURE_KEYS = ("feature_osc_inspector", "feature_intiface", "feature_osc_router_518",
                    "feature_statistics", "feature_pishock", "feature_bhaptics",
                    "feature_owo", "feature_trackers", "feature_psvr2", "feature_friends",
                    "feature_params")

    def __init__(self):
        import body_map
        import friends_demo
        import param_board as pb
        from settings.suits import _clean_bhaptics, _clean_owo

        self.ui = None
        self._unknown = set()
        self.now = time.time()
        self.settings = {
            "home_setup_compact": True, "home_tuning_tools_open": False,
            "auto_refresh": True, "auto_connect": True, "auto_connect_osc": True,
            "use_integrated_intiface": True, "update_check_enabled": True,
            "bind_all_interfaces": True, "hide_console": True, "minimize_to_tray": False,
            "router_poll_rate_hz": 90, "toy_antistuck_enabled": True,
            "toy_antistuck_active_s": 1, "toy_antistuck_peaked_s": 10,
            # off, as on a new install: the gallery's Home has no headset row
            # (its page still renders: shots.page("PSVR2"))
            "feature_psvr2": False,
        }
        self.settings.update({k: True for k in self.FEATURE_KEYS})
        self.strength = 0.7
        self.output_off = False
        self.sleep = False

        # ---- toys ----
        self.profiles = {}
        for name, (motors, _on, _batt, _lv, zones) in TOYS.items():
            cfg = {"motor_count": motors}
            for i, z in enumerate(zones):
                if z:
                    cfg[f"motor_{i}_zones"] = z
            self.profiles[name] = cfg
        self.connected = {n for n, t in TOYS.items() if t[1]}

        # ---- modes: the real default names ----
        from config_manager import ModeManager
        self.modes = [dict(m) for m in ModeManager.DEFAULT_MODES]
        self.active_mode = 0
        self.motor_router = _Router()

        # ---- friends: the app's own examples ----
        self.friends_demo = friends_demo.FriendsDemo()
        # Mika is linked to her VRChat account and in your instance with Juno
        self.vrc_links = {self.friends_demo.entries({}, {})[0]["id"]: (VRC_INSTANCE[0][0], "MikaPaws")}
        self.vrcx_imported = False
        # Only friends in my instance (controllers/friends_instance.py): off,
        # as for a new install; a render switches it on to show it
        self.instance_only = False
        self.anywhere = set()
        self.mika = friends_demo._id(1)
        self.friends_demo.selected = {"kind": "friend", "id": self.mika}
        self.friends_paused = False
        self.friends_sync = True
        self.my_levels = {self.mika: {"Lovense Lush 3": 0.55}}

        # ---- shockers ----
        # Separate limits for friends: off, as a new install has it; the
        # friends' set is what the guide shows once it's on
        self.separate_limits = False
        self.friend_limits = {"max_intensity": 20, "max_vibrate": 50, "max_pulse_ms": 1000,
                              "cooldown_s": 1.0, "max_hold_s": 8.0, "hold_rest_s": 3.0}
        self.pishock_rules = {
            "zones": [{"enabled": True, "name": "Touch zones", "op": "vibrate",
                       "mode": "pulse", "intensity": 25, "duration_ms": 600,
                       "zones": [{"param": "Contact/Neck", "shockers": [24325]},
                                 {"param": "Contact/ThighL", "shockers": [24326]}]}],
            "triggers": [{"enabled": True, "name": "Headpat", "param": "Headpat",
                          "mode": "hold", "intensity": 15, "duration_ms": 500,
                          "op": "shock", "shockers": [24325, 24326]}],
            "continuous": [], "impacts": [], "pulls": []}

        # ---- suits ----
        self.bh_settings = _clean_bhaptics({"auto_connect": True})
        self.owo_settings = _clean_owo({})
        self.body_map = body_map

        # ---- avatar remote: a real BoardBook on an in-memory store ----
        self.boards = _MemoryBoards()
        self.boards.save(pb.normalize_profile({
            "name": "Kitsune", "params": dict(BOARD_TYPES),
            "presets": [{"id": "default", "name": "Default",
                         "categories": [{"id": c, "name": n, "color": col, "locked": lk}
                                        for c, n, col, lk in BOARD_CATS],
                         "controls": [dict(c) for c in BOARD_CONTROLS]},
                        {"id": "party", "name": "Party", "categories": [], "controls": []}],
            "active_preset": "default"}, AVATAR_ID))
        self.boards.save(pb.normalize_profile({"name": "Base V7"}, "avtr_0b5e07ee-0000-4000-8000-000000000007"))
        self.book = pb.BoardBook(self.boards, AVATAR_ID)
        self.book.avatar_changed(AVATAR_ID)
        self.book.sync_params(dict(BOARD_TYPES))
        self.param_values = dict(BOARD_VALUES)
        self.yolo = False
        # the Height box: VRChat says 1.42 m, the world allows it
        import avatar_height as ah
        self.height_settings = ah.clean_settings(None)
        self.height_now = 1.42

        # ---- statistics ----
        self.stats = _demo_stats(self.now)

    # ---- fallback --------------------------------------------------------
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def noop(*_a, **_k):
            if name not in self._unknown:
                self._unknown.add(name)
                print(f"[app_shots] controller.{name}() is not demoed - no-op", flush=True)
            return None
        return noop

    # ---- app settings, features ------------------------------------------
    def get_app_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_app_setting(self, key, value):
        self.settings[key] = value

    def get_feature_enabled(self, key):
        return bool(self.settings.get(key, True))

    def get_feature_flags(self):
        return {k: self.get_feature_enabled(k) for k in self.FEATURE_KEYS}

    def set_feature_enabled(self, key, enabled):
        self.settings[key] = bool(enabled)
        if self.ui is not None:
            self.ui.apply_feature_visibility()

    def log_message(self, message):
        if self.ui is not None:
            self.ui.log_message(message)

    # ---- Settings → Intiface Engine (controllers/intiface_facade.py) ------
    # Off the built-in engine, the demo is connected to a phone on the
    # network that announced itself.
    def get_intiface_link_status(self):
        st = {"built_in": bool(self.settings.get("use_integrated_intiface", True)),
              "connected": True, "found": [],
              "address": str(self.settings.get("intiface_address", "") or "")}
        if not st["built_in"]:
            phone = {"name": "Intiface Pixel", "host": "192.168.1.50", "port": 12345}
            st.update(auto=not st["address"], searching=not st["address"],
                      target=st["address"] or "192.168.1.50:12345",
                      target_name="" if st["address"] else phone["name"],
                      target_local=False, found=[phone])
        return st

    def set_intiface_integrated(self, enabled):
        self.settings["use_integrated_intiface"] = bool(enabled)

    def set_intiface_address(self, text):
        from intiface_external import normalize_address
        address = normalize_address(text)
        if address is None:
            return False, ("Not an address. Try 192.168.1.50, or leave it "
                           "empty.")
        self.settings["intiface_address"] = address
        return True, address

    def get_whats_new(self):
        return []

    def get_interests(self):
        return []

    # ---- sidebar: modes, strength, links -----------------------------------
    def get_modes_info(self):
        return [{"index": i, "name": m.get("name", f"Mode {i}"), "icon": m.get("icon", ""),
                 "active": i == self.active_mode} for i, m in enumerate(self.modes)]

    def switch_mode(self, index):
        self.active_mode = int(index)
        if self.ui is not None:
            self.ui._refresh_mode_buttons()

    def get_strength(self):
        return self.strength

    def set_strength(self, value, source="ui"):
        self.strength = max(0.0, min(1.0, float(value)))

    def is_output_off(self):
        return self.output_off

    def is_off_switch_on(self):
        return self.output_off

    # ---- Settings → Safety → Off while you're away (away_facade) ---------
    def get_away_settings(self):
        return {"enabled": bool(self.settings.get("away_off_enabled", True)),
                "vrchat_afk": bool(self.settings.get("away_off_vrchat_afk", True)),
                "gogo_afk": bool(self.settings.get("away_off_gogo_afk", True)),
                "params": self.get_away_params()}

    def set_away_switch(self, which, on):
        key = {"enabled": "away_off_enabled", "vrchat_afk": "away_off_vrchat_afk",
               "gogo_afk": "away_off_gogo_afk"}.get(which)
        if key:
            self.settings[key] = bool(on)

    def get_away_params(self):
        return list(self.settings.get("away_off_params", []))

    def add_away_param(self, name):
        params = self.get_away_params()
        if not name or name in params:
            return False
        self.settings["away_off_params"] = params + [name]
        return True

    def remove_away_param(self, name):
        self.settings["away_off_params"] = [p for p in self.get_away_params() if p != name]

    def get_away_reasons(self):
        return ()

    def get_away_status_text(self):
        return ""

    def is_sleep_active(self):
        return self.sleep

    # ---- a toy's own Sleep and anti-stuck; each kind's anti-stuck --------
    def is_toy_sleep_on(self, name):
        return name in self.__dict__.setdefault("toys_asleep", set())

    def set_toy_sleep(self, name, on):
        asleep = self.__dict__.setdefault("toys_asleep", set())
        (asleep.add if on else asleep.discard)(name)

    def get_toys_antistuck(self):
        import antistuck
        return antistuck.from_app(lambda k, d: self.settings.get(k, d))

    def set_toys_antistuck(self, **changes):
        import antistuck
        new = antistuck.changed(self.get_toys_antistuck(), **changes)
        for field, key in antistuck.TOY_KEYS.items():
            self.settings[key] = new[field]

    def is_toy_antistuck_on(self, name):
        import antistuck
        return antistuck.toy_on(self.profiles.get(name))

    def set_toy_antistuck(self, name, on):
        import antistuck
        self.profiles.setdefault(name, {})[antistuck.TOY_KEY] = bool(on)

    def get_suit_antistuck(self, kind):
        import antistuck
        return dict(self.__dict__.setdefault("suit_antistuck", {}).get(kind)
                    or antistuck.DEFAULTS)

    def set_suit_antistuck(self, kind, **changes):
        import antistuck
        blocks = self.__dict__.setdefault("suit_antistuck", {})
        blocks[kind] = antistuck.changed(self.get_suit_antistuck(kind), **changes)
        target = {"bhaptics": self.bh_settings, "owo": self.owo_settings}.get(kind)
        if target is not None:
            target["antistuck"] = dict(blocks[kind])

    def get_psvr2_antistuck(self):
        import antistuck
        return dict(self.__dict__.get("psvr2_antistuck") or antistuck.DEFAULTS)

    def set_psvr2_antistuck(self, **changes):
        import antistuck
        self.psvr2_antistuck = antistuck.changed(self.get_psvr2_antistuck(), **changes)

    def get_master_scale(self):
        return 0.0 if self.output_off else self.strength

    def get_osc_status_snapshot(self):
        return {"connected": True, "port": VRCHAT_PORT, "packets": 184_312,
                "link_state": "live"}

    def get_osc_link_state(self):
        return "live"

    def get_current_avatar_id(self):
        return AVATAR_ID

    def get_setup_status(self):
        return {"osc": True, "zones": True, "toy": bool(self.connected)}

    def get_detected_zones(self):
        return {k: list(v) for k, v in DETECTED_ZONES.items()}

    # ---- toys --------------------------------------------------------------
    def get_active_profile_dict(self):
        return self.profiles

    def get_profile_config(self, device, key, default=None):
        return self.profiles.get(device, {}).get(key, default)

    def update_device_config(self, device, key, value):
        self.profiles.setdefault(device, {})[key] = value

    def get_connected_device_names(self):
        return set(self.connected)

    def get_connected_toys_in_order(self):
        return [n for n in TOYS if n in self.connected]

    def get_device_motor_counts(self):
        return {n: TOYS[n][0] for n in self.connected if n in TOYS}

    def is_device_muted(self, _name):
        return False

    def get_toy_scan_status(self):
        return {"up": True, "auto": True, "scanning": False, "next_in": 24}

    def get_toy_scan_interval(self):
        return 5

    def get_toy_connected_param(self, device):
        return (True, f"OGP/{device.replace(' ', '')}Connected")

    def get_toy_presence_param(self):
        return (True, "OGP/ToyConnected")

    def get_device_connected_param(self, slot):
        """The suits' and shockers' (presence_facade): on, default names,
        shockers numbered like their cards."""
        from controllers import presence_facade as pf
        if slot.startswith("shocker:"):
            ids = [s["id"] for s in SHOCKERS]
            sid = int(slot.split(":", 1)[1])
            return (True, f"OGP/Shocker{ids.index(sid) + 1 if sid in ids else sid}Connected")
        return (True, pf._FIXED_DEFAULTS.get(slot, "OGP/DeviceConnected"))

    def set_device_connected_param(self, slot, enabled, name):
        pass

    def get_toy_sounds_enabled(self):
        return True

    def get_toy_sounds_volume(self):
        return 60

    def get_thrust_params_enabled(self):
        return False

    def get_steamvr_toys_status(self):
        return {"supported": True, "steamvr": True, "enabled": True, "installed": True,
                "connected": True}

    def live_levels(self):
        """(toy, motor, level) for Home's meters right now."""
        t = time.time()
        out = []
        for name, (_m, on, _b, levels, _z) in TOYS.items():
            for i, lv in enumerate(levels):
                wobble = 0.06 * math.sin(t * 1.7 + i)
                out.append((name, i, max(0.0, min(1.0, lv + wobble)) if on else 0.0))
        return out

    # ---- settings page odds and ends -----------------------------------------
    def get_settings_snapshots(self):
        return []

    def get_session_logging_status(self):
        return {"settings": {"enabled": False, "auto_start": False, "retention": 20},
                "active": None, "sessions_dir": ""}

    def list_logged_sessions(self):
        return []

    def get_replay_status(self):
        return {"active": False, "loading": False, "session_id": None, "position_ms": 0.0,
                "duration_ms": 0.0, "speed": 1.0}

    def get_sps_sources(self):
        return []

    def get_sps_source_names_flat(self):
        return []

    def get_sps_source_values(self):
        return {}

    def get_osc_diagnostics(self):
        return {}

    def get_osc_event_log(self):
        return []

    def get_osc_other_clients(self):
        return {}

    # ---- friends ---------------------------------------------------------------
    def _me_entry(self, selected):
        import remote_protocol as proto
        toys = [(n, TOYS[n][0]) for n in TOYS if TOYS[n][1]]
        outs = {n: lv for n, _i, lv in self.live_levels() if _i == 0 and n in dict(toys)}
        theirs = proto.read_status(proto.make_status(
            toys, outs, self.strength, False, self.friends_paused, True, True,
            [s["name"] for s in SHOCKERS], True, 40, 2000,
            batteries={n: TOYS[n][2] for n, _m in toys}))
        return {"id": "__me__", "nick": NICK, "me": True, "toys": True, "shock": True,
                "params": True, "added": 0.0, "linked": True, "path": "this PC", "rtt": None,
                "selected": selected == {"kind": "friend", "id": "__me__"},
                "theirs": theirs, "my_levels": {}, "driving_me": False, "others": []}

    def get_friends_status(self):
        demo = self.friends_demo
        selected = dict(demo.selected or {})
        friends = [self._me_entry(selected)] + demo.entries(self.my_levels, {})
        for f in friends:
            f["selected"] = selected == {"kind": "friend", "id": f["id"]}
            f.setdefault("my_override", set())
            f.setdefault("my_patterns", {})
            f.setdefault("my_holds", {})
            # these stand for real friends here (VRChat account field and all)
            f.pop("demo", None)
            vrc = self.vrc_links.get(f["id"])
            f.update(vrc=vrc[0] if vrc else "", vrc_name=vrc[1] if vrc else "",
                     here=bool(vrc) and any(p[0] == vrc[0] for p in VRC_INSTANCE))
            f.update(anywhere=f["id"] in self.anywhere,
                     not_here=(self.instance_only and not f.get("me") and not f["here"]
                               and f["id"] not in self.anywhere))
        owner = {v[0]: fid for fid, v in self.vrc_links.items()}
        return {
            "available": True, "enabled": True, "running": True, "online": True,
            "error": "", "my_id": MY_ID, "nickname": NICK, "paused": self.friends_paused,
            "sync_all": self.friends_sync,
            "requests": [], "asking": [], "friends": friends,
            "groups": [dict(g, members=list(g["members"])) for g in demo.groups],
            "selected": selected, "online_switch": True,
            "avatar_menu": {"known": True, "self": True, "friends": True},
            "elsewhere": False, "pending_invite": "",
            "invites": [{"kind": "week", "expires": self.now + 5 * 86400, "uses": 1}],
            "params_on": True, "behind": None,
            "shocker_layout": self.get_shocker_layout(),
            "vrchat": {"log": True, "state": "ok", "vrcx": "", "vrcx_count": 0,
                       "people": [{"id": u, "name": n, "friend": owner.get(u, "")}
                                  for u, n in VRC_INSTANCE]},
            "instance": {"on": self.instance_only, "web_anyway": False,
                         "web_blocked": self.instance_only},
        }

    # ---- whose shocker buttons (controllers/friends_control.py) ------------
    def get_shocker_layout(self):
        import shocker_layout
        return shocker_layout.clean(self.get_app_setting(shocker_layout.SETTING_KEY))

    def set_shocker_layout(self, name):
        import shocker_layout
        self.set_app_setting(shocker_layout.SETTING_KEY, shocker_layout.clean(name))
        if self.ui is not None:
            self.ui.refresh_friends()

    # ---- only friends in my instance (controllers/friends_instance.py) ----
    def set_friends_instance_only(self, on):
        self.instance_only = bool(on)

    def set_friend_anywhere(self, peer, on):
        (self.anywhere.add if on else self.anywhere.discard)(peer)

    # ---- a friend's VRChat account (controllers/friends_vrchat.py) ----------
    def get_vrchat_choices(self, query="", limit=40):
        q = " ".join(str(query or "").split()).casefold()
        owner = {v[0]: fid for fid, v in self.vrc_links.items()}
        here = [{"id": u, "name": n, "friend": owner.get(u, "")}
                for u, n in VRC_INSTANCE if q in n.casefold()]
        vrcx = [{"id": u, "name": n, "friend": owner.get(u, "")}
                for u, n in VRC_VRCX if q in n.casefold()] if self.vrcx_imported else []
        return {"log": True, "state": "ok", "instance": here, "vrcx": vrcx[:limit],
                "vrcx_more": max(0, len(vrcx) - limit),
                "vrcx_state": "ok" if self.vrcx_imported else "",
                "vrcx_count": len(VRC_VRCX) if self.vrcx_imported else 0,
                "vrcx_installed": True}

    def import_vrcx_friends(self):
        self.vrcx_imported = True
        return {"state": "ok", "count": len(VRC_VRCX)}

    def link_friend_vrchat(self, peer, user_id, name=""):
        for fid in [f for f, v in self.vrc_links.items() if v[0] == user_id]:
            del self.vrc_links[fid]
        self.vrc_links[peer] = (user_id, name)
        return True

    def unlink_friend_vrchat(self, peer):
        self.vrc_links.pop(peer, None)

    def get_friends_log(self):
        lines = [(40, "Mika is driving your toys"),
                 (95, "You set Mika's Lovense Lush 3 to 55 %"),
                 (180, "Sam started driving Mika's toys too"),
                 (420, "Nova turned your Tail wag on"),
                 (610, "Kiko linked (relay, 64 ms)"),
                 (900, "Mika linked (direct, 18 ms)")]
        return [{"t": self.now - s, "text": t} for s, t in lines]

    # --- the log (controllers/log_facade.py), from a memory-only demo log
    def _event_log(self):
        log = self.__dict__.get("_demo_log")      # (__getattr__ answers anything else)
        if log is None:
            log = self._demo_log = _demo_event_log(self.now)
        return log

    def get_friends_log_people(self):
        import event_log
        recent = self._event_log().recent(600, where=lambda e: e.role != event_log.ROLE_AVATAR)
        return [p.as_dict(self.now) for p in event_log.by_person(
            recent, skip_roles=(event_log.ROLE_YOU,))]

    def get_log_version(self):
        return self._event_log().version

    def get_log_spans(self):
        from controllers.log_facade import SPANS
        return list(SPANS)

    def get_log_kinds(self):
        import event_log
        return [{"key": k, "label": event_log.KIND_LABELS[k]} for k in event_log.KINDS]

    def get_log_events(self, person=None, kinds=None, span="", text="", hide_avatar=False,
                       limit=1000):
        import event_log
        from controllers.log_facade import _since
        hits, total = self._event_log().query(person, kinds, _since(span), text,
                                              (event_log.AVATAR,) if hide_avatar else (), limit)
        return {"events": [e.as_dict() for e in hits], "total": total, "shown": len(hits),
                "loaded": True}

    def get_log_people(self, kinds=None, span="", text="", hide_avatar=False):
        import event_log
        from controllers.log_facade import _since
        hits, _ = self._event_log().query(None, kinds, _since(span), text,
                                          (event_log.AVATAR,) if hide_avatar else ())
        return [p.as_dict(self.now) for p in event_log.by_person(hits, 25)]

    def get_log_page(self, person=None, kinds=None, span="", text="", hide_avatar=False,
                     limit=1000):
        got = self.get_log_events(person, kinds, span, text, hide_avatar, limit)
        return {**got, "people": self.get_log_people(kinds, span, text, hide_avatar)}

    def clear_log(self):
        self._event_log().clear()

    def set_friends_selected(self, kind, sid):
        self.friends_demo.selected = {"kind": kind, "id": sid}

    def get_friend_board(self, peer):
        return self.friends_demo.board(peer)

    def set_friends_paused(self, paused):
        self.friends_paused = bool(paused)

    def set_friends_sync(self, on):
        self.friends_sync = bool(on)

    def friends_invite_message(self, kind="once"):
        return "https://example.invalid/friend"

    # ---- shockers --------------------------------------------------------------
    def get_pishock_status(self):
        import pishock_limits
        limits = {k: d for k, (_lo, _hi, d) in pishock_limits.RANGES.items()}
        limits.update(max_intensity=40, max_vibrate=80)
        return {
            "available": True, "connected": True, "connecting": False, "last_error": "",
            "port": "COM7", "port_setting": "", "hub_kind": "pishock", "firmware": "3.1.2",
            "board": "PiShock Next", "shockers": [dict(s) for s in SHOCKERS],
            "openshock_shockers": [], "shocker_names": {str(s["id"]): s["name"] for s in SHOCKERS},
            "armed": True, "paused": False, "output_off": False, "auto_connect": True,
            "friends_may_use": True, "limits": limits,
            "shocker_limits": {"24325": {"max_intensity": 25, "max_vibrate": 60,
                                         "max_pulse_ms": 1000},
                               "24326": {"max_intensity": 40, "max_vibrate": 80,
                                         "max_pulse_ms": 2000}},
            "ranges": dict(pishock_limits.RANGES), "hub_name": "PiShock",
            "separate_limits": self.separate_limits, "friend_limits": dict(self.friend_limits),
        }

    def set_pishock_separate_limits(self, on):
        self.separate_limits = bool(on)

    def set_pishock_friend_limit(self, key, value):
        if key in self.friend_limits:
            self.friend_limits[key] = value

    def get_pishock_live(self):
        return {"values": {"Contact/Neck": 1.0, "Contact/ThighL": 0.0, "Headpat": 0.0},
                "outputs": {24325: {"kind": "pulse", "op": "vibrate", "intensity": 25}}}

    def list_pishock_ports(self):
        return [{"device": "COM7", "description": "USB-SERIAL CH340", "hub": True}]

    def get_pishock_rules(self, kind):
        return [dict(r) for r in self.pishock_rules.get(kind, [])]

    def set_pishock_rule(self, kind, index, rule):
        self.pishock_rules[kind][index] = dict(rule)

    def openshock_models(self):
        import openshock_serial
        return openshock_serial.MODELS

    # ---- suits -----------------------------------------------------------------
    def get_suits_status(self):
        return {"bhaptics": {"available": True, "wanted": True, "released": False,
                             "paused": False, "scanning": False, "error": "",
                             "devices": [{"address": "D4:9C:5A:18:51:8B", "name": "TactSuitPro",
                                          "label": "TactSuit Pro", "model": "pro",
                                          "positions": ["VestFront", "VestBack"],
                                          "battery": 87, "verified": True}],
                             "settings": self.bh_settings, "feature": True},
                "owo": {"connected": True, "host": "127.0.0.1", "wanted": True,
                        "paused": False, "error": "",
                        "active": {"Pectoral_L": 35, "Abdominal_L": 20}, "frequency": 50,
                        "settings": self.owo_settings, "feature": True},
                "trackers": dict(self._demo_trackers(),
                                 antistuck=self.get_suit_antistuck("trackers")),
                "output_off": False}

    # ---- PSVR2 headset -------------------------------------------------------
    def get_psvr2_status(self):
        return {"feature": self.get_feature_enabled("feature_psvr2"),
                "available": True, "connected": True, "paused": False,
                "last_error": None, "auto_connect": True, "output_off": False,
                "output": {"min_hz": 10.0, "max_hz": 25.0, "max_cmd_hz": 10.0,
                           "keepalive_s": 0.0},
                "contact": {"enabled": True, "parameter": "HapticHead",
                            "threshold": 0.05, "gain": 1.2},
                "antistuck": self.get_psvr2_antistuck(),
                "extras": {"driver_active": True, "level": 0.4, "rumble_hz": 16,
                           "rtt_ms": 9.0, "sends_per_min": 42, "slotless": False,
                           "paused": False, "dll_path": None}}

    def get_psvr2_live(self):
        return {"strength": 0.38, "level": 0.4, "rumble_hz": 16}

    def get_psvr2_contact_found(self):
        return True

    def _demo_trackers(self):
        """Two Vive Trackers with a Haptic Pancake placed by their SteamVR
        roles, a third not placed yet."""
        from settings.suits import _clean_trackers
        spots = _clean_trackers({})["spots"]
        def dev(serial, role, spot, battery):
            return {"serial": serial, "model": "VIVE Tracker 3.0 MV", "kind": "vive",
                    "battery": battery, "role": role, "role_spot": spot, "spot": spot,
                    "placed_by": "steamvr" if spot else None}
        hips = dev("LHR-6E1A20C4", "TrackerRole_Waist", "hips", 74)
        foot = dev("LHR-781FC61B", "TrackerRole_LeftFoot", "foot_l", 58)
        loose = dev("LHR-2B90D3F7", "TrackerRole_None", None, 91)
        return {"feature": True, "available": True, "alive": True, "paused": False,
                "devices": [hips, foot, loose], "all_spots": spots,
                "spots": {"hips": dict(spots["hips"], trackers=[hips], contacts=[1, 1]),
                          "foot_l": dict(spots["foot_l"], trackers=[foot], contacts=[1, 1])}}

    def get_suits_live(self):
        frame = self.body_map.empty_frame()
        lit = {"VestFront": {1: 0.9, 2: 0.55, 5: 0.7, 6: 1.0, 9: 0.35},
               "VestBack": {5: 0.45, 6: 0.8, 10: 0.3},
               "Head": {2: 0.6, 3: 0.6}}
        for pos, dots in lit.items():
            vals = list(frame.get(pos, ()))
            for i, v in dots.items():
                if i < len(vals):
                    vals[i] = v
            frame[pos] = tuple(vals)
        dots = {pos: tuple(int(round(v * 100)) for v in frame[pos])
                for pos in ("VestFront", "VestBack")}
        return {"frame": frame, "owo": {"Pectoral_L": 0.35, "Abdominal_L": 0.2},
                "dots": dots, "owo_sending": {"Pectoral_L": 35, "Abdominal_L": 20},
                "trackers": {"hips": 0.6}}

    def get_suits_detected(self):
        return {"positions": ["Head", "VestBack", "VestFront"],
                "owo": ["Abdominal_L", "Abdominal_R", "Pectoral_L", "Pectoral_R"]}

    def get_suit_routes(self):
        return []

    # ---- avatar remote ---------------------------------------------------------
    def get_params_status(self):
        book = self.book
        return {"enabled": True, "vrchat": True, "avatar_id": book.avatar_id,
                "avatar_name": book.avatar_name, "live_avatar_id": book.live_avatar_id,
                "is_live": book.is_live, "board": book.board,
                "presets": book.list_presets(), "yolo": self.yolo,
                "watchers": ["Mika"], "friends_on": True}

    def params_avatars(self):
        return self.book.list_avatars()

    def params_param_list(self):
        return self.book.params()

    def params_values(self, names=None):
        if names is None:
            names = self.book.params().keys()
        return {n: self.param_values[n] for n in names if n in self.param_values}

    def params_param_type(self, name):
        return self.book.param_type(name)

    def params_next_on_value(self, param, exclude=None):
        return self.book.next_on_value(param, exclude)

    def params_set_control(self, control_id, value):
        import param_board as pb
        control = pb.find_control(self.book.board, control_id)
        out = pb.send_value(control, value) if control else None
        if out is not None:
            self.param_values[control["param"]] = out
        return out is not None

    def get_height_status(self):
        return {**self.height_settings, "height": self.height_now, "own": 1.42,
                "allowed": True, "world_min": 0.2, "world_max": 5.0, "gliding": False,
                "target": None, "by": None, "version": 1, "vrchat": True}

    def height_go(self, height, mode="grow"):
        import avatar_height as ah
        s = self.height_settings
        self.height_now = ah.clamp(float(height), s["lo"], s["hi"])
        return True

    def height_reset(self):
        self.height_now = 1.42
        return True

    def height_set_option(self, key, value):
        import avatar_height as ah
        s = dict(self.height_settings)
        if key in ("lo", "hi"):
            s = ah.with_range(s, **{key: float(value)})
        else:
            s[key] = value
        self.height_settings = ah.clean_settings(s)
        return dict(self.height_settings)

    # ---- statistics ------------------------------------------------------------
    def get_stats_snapshot(self):
        return {"lifetime": self.stats["lifetime"], "session": self.stats["session"],
                "recent_sessions": []}

    def get_stats_sessions(self):
        return [dict(r) for r in self.stats["rows"]]

    def get_stats_session_detail(self, sid):
        live = next(r for r in self.stats["rows"] if r["kind"] == "live")
        if sid != live["id"]:
            return None
        return _demo_live_detail(self.now, self.stats, self._whom(), self._event_log())

    # --- From whom (controllers/stats_events_facade.py)
    def _whom(self):
        store = self.__dict__.get("_demo_whom")
        if store is None:
            store = self._demo_whom = _demo_whom(self.now, self._event_log(), self.stats)
        return store

    def get_stats_from_whom(self, span="lifetime"):
        import stats_events as se
        store = self._whom()
        live = next(r for r in self.stats["rows"] if r["kind"] == "live")
        if span == "session":
            out = store.session_view(live["id"]) or se.view(se.fresh_tally())
        else:
            out = store.lifetime_view()
        out.update(names=True, kept=store.has_names(), on=True)
        return out

    def get_stats_worn(self):
        store = self._whom()
        live = next(r for r in self.stats["rows"] if r["kind"] == "live")
        session = store.session_view(live["id"])
        return {"lifetime": store.lifetime_view()["worn"],
                "session": session["worn"] if session else []}

    def get_stats_friend_names(self):
        return True

    def forget_stats_friend_names(self):
        return False

    def get_stats_patterns(self, days=None):
        import stats_history as sh
        hours = self.stats["hours"]
        since = sh.hour_key(time.time() - days * 86400) if days else None
        out = sh.weekday_hour(hours, since)
        out["first_hour"] = min(hours) if hours else None
        out["estimated_until"] = 0.0
        return out

    def get_stats_month(self, year, month):
        import stats_history as sh
        return sh.month_days(self.stats["hours"], self.stats["rows"], int(year), int(month))

    def get_stats_fun_facts(self):
        import stats_history as sh
        return sh.fun_facts(self.stats["lifetime"], self.stats["rows"], self.stats["hours"])

    def get_people_table(self):
        return [dict(r) for r in self.stats["people"]]

    def get_people_names(self):
        return sorted(r["name"] for r in self.stats["people"])

    def get_people_autodetect_enabled(self):
        return True

    def get_people_autodetect_status(self):
        return {"state": "with", "name": "Mika"}


# ========================================================================
# The shots
# ========================================================================

# What select_view runs on arrival (ui_components.select_view), called
# again here without its swallowing try/except so a failure shows. Keyed by
# a widget the page owns, not by its name: page names change (Avatar Remote
# became "My Avatar Remote").
_ARRIVAL = (
    ("_setup_card", ("_refresh_setup_checklist", "_refresh_toy_summaries",
                     "_refresh_home_devices")),
    ("_toy_server_card", ("_refresh_toy_scan", "_refresh_toy_server",
                          "_refresh_toy_summaries", "_refresh_sps_summary")),
    ("_stats_active_tile", ("_refresh_statistics_view",)),
    ("_pishock_pill", ("refresh_pishock_status", "_refresh_pishock_live")),
    ("_bh_pill", ("refresh_suits_status", "_refresh_suits_live")),
    ("_panel_card", ("refresh_friends",)),
    ("_params_board", ("_params_rebuild", "refresh_params_live")),
)

_TITLE = re.compile(r"^<b>(.*?)</b>", re.S)


class Shots:
    """The built window, page by page. Page names are the keys of
    `ui.views`; a unique part of one works too ("Avatar Remote")."""

    def __init__(self, ui, app, controller, settle_ms=350):
        self.ui = ui
        self.app = app
        self.controller = controller
        self.settle_ms = settle_ms
        self.errors = []               # (page, traceback text)

    @property
    def pages(self):
        return list(self.ui.views)

    def resolve(self, name):
        """The `ui.views` key for `name`: itself, or the one page whose name
        ends with / contains it (case aside)."""
        views = self.ui.views
        if name in views:
            return name
        low = str(name).lower()
        for test in (lambda v: v.lower() == low, lambda v: v.lower().endswith(low),
                     lambda v: low in v.lower()):
            hits = [v for v in views if test(v)]
            if len(hits) == 1:
                return hits[0]
        raise KeyError(f"no page {name!r} (pages: {', '.join(views)})")

    def pump(self, ms=None):
        """Run the event loop for `ms` (default settle_ms): timers, deferred
        rebuilds and switch animations get done."""
        end = time.monotonic() + (self.settle_ms if ms is None else ms) / 1000.0
        while True:
            self.app.processEvents(QEventLoop.AllEvents, 20)
            if time.monotonic() >= end:
                break
            time.sleep(0.01)

    def sidebar_overflow(self) -> int:
        """How many pixels the sidebar is taller than its column (> 0: it
        shows a scrollbar, as the real app would at this window height)."""
        need = self.ui.sidebar_frame.sizeHint().height()
        return need - self.ui.sidebar_scroll.viewport().height()

    def _owns(self, name, attr):
        w = getattr(self.ui, attr, None)
        return isinstance(w, QWidget) and self.ui.views[name].isAncestorOf(w)

    def _push_live(self, name):
        """What the real controller pushes rather than the page pulling:
        the toys' motor meters and batteries (Home's rows, the Toys page's
        cards)."""
        if self._owns(name, "home_list_frame") or self._owns(name, "unified_devices_frame"):
            for toy, motor, level in self.controller.live_levels():
                self.ui.update_motor_vibe(toy, motor, level)
            for toy, (_m, on, batt, _lv, _z) in TOYS.items():
                if on and batt is not None:
                    self.ui.update_battery_label(toy, batt)

    def open_chain(self, toy, motor=0, chain=0):
        """`toy`'s card open on the Toys page with one of its chains
        unfolded -- how a toy is tuned. (A card opens by itself, on its
        motors' folded chains.)"""
        from PySide6.QtTest import QTest
        from ui.motor_signal_chain import _ChainFoldBar
        data = self.ui.device_ui_frames[toy]
        data["set_expanded"](True)
        self.pump(60)
        bar = next(b for b in data["body"].findChildren(_ChainFoldBar)
                   if b._motor_idx == motor and b._chain_idx == chain and b.isVisible())
        QTest.mouseClick(bar, Qt.LeftButton)
        self.pump(400)

    def show(self, name):
        """Bring a page up and let it fill (no grab; the scroll stays)."""
        name = self.resolve(name)
        self.ui.select_view(name)
        self.pump(30)
        fns = next((f for attr, f in _ARRIVAL if self._owns(name, attr)), ())
        for fn_name in fns:
            fn = getattr(self.ui, fn_name, None)
            if not callable(fn):
                continue
            try:
                fn()
            except Exception:
                text = traceback.format_exc()
                self.errors.append((name, text))
                print(f"[app_shots] {name}: {fn_name}() raised:\n{text}", flush=True)
        self.pump()
        self._push_live(name)
        self.pump(60)
        return name

    def page(self, name, scroll=None) -> QImage:
        """The whole window showing `name`, as a QImage. `scroll`: None for
        the top of the page, a number of pixels, or a title (a hover
        explanation's, or a label's / button's / name field's text) to
        bring to the top."""
        name = self.show(name)
        self.scroll_to(name, 0 if scroll is None else scroll)
        return self.ui.window.grab().toImage()

    def scroll_to(self, page, target) -> int:
        """Scroll `page` to `target` (pixels, or a title as in page());
        returns where it ended up."""
        page = self.resolve(page)
        area = self.ui.views[page]
        bar = area.verticalScrollBar()
        if isinstance(target, (int, float)):
            bar.setValue(int(target))
        else:
            w = self._find(page, str(target))
            if w is None:
                raise KeyError(f"nothing titled {target!r} on {page}")
            bar.setValue(max(0, w.mapTo(area.widget(), QPoint(0, 0)).y() - 12))
        self.pump(60)
        return bar.value()

    def _find(self, page, title):
        prefix = "<b>" + html.escape(title) + "</b>"
        widgets = [w for w in self.ui.views[page].findChildren(QWidget) if w.isVisible()]
        for w in widgets:
            if (w.toolTip() or "").startswith(prefix):
                return w
        for w in widgets:
            if (isinstance(w, (QLabel, QAbstractButton, QLineEdit))
                    and w.text().strip() == title):
                return w
        return None

    # ---- anchors -----------------------------------------------------------
    def _rect(self, w):
        """The visible part of `w` in window coordinates, or None."""
        if not w.isVisible():
            return None
        region = w.visibleRegion()
        if region.isEmpty():
            return None
        br = region.boundingRect()
        r = QRect(w.mapTo(self.ui.window, br.topLeft()), br.size())
        r = r.intersected(self.ui.window.rect())
        return r if r.isValid() and not r.isEmpty() else None

    def _widgets(self, page):
        """(widget, where): the page's widgets, then the rest of the window
        (sidebar, status bar) -- everything a shot of that page shows."""
        root = self.ui.views[page]
        mine = root.findChildren(QWidget)
        seen = set(id(w) for w in mine)
        rest = [w for w in self.ui.window.findChildren(QWidget) if id(w) not in seen]
        return [(w, "page") for w in mine] + [(w, "sidebar") for w in rest]

    def _current(self, page):
        page = self.resolve(page)
        if self.ui.main_stack.currentWidget() is not self.ui.views[page]:
            self.show(page)
        return page

    def anchor(self, page, title, where="any"):
        """Window rectangle (visible part) of the first visible widget on
        `page` whose hover explanation is titled `title` -- then, with
        where="any", the sidebar's -- or, failing both, of the first label,
        button or name field that says `title`; None when nothing does.
        where="page" / "sidebar" looks only there. Reflects the page's
        current scroll."""
        page = self._current(page)
        prefix = "<b>" + html.escape(str(title)) + "</b>"
        widgets = [(w, at) for w, at in self._widgets(page) if where in ("any", at)]
        for w, _at in widgets:
            if (w.toolTip() or "").startswith(prefix):
                r = self._rect(w)
                if r is not None:
                    return r
        for w, _at in widgets:
            if (isinstance(w, (QLabel, QAbstractButton, QLineEdit))
                    and w.text().strip() == title):
                r = self._rect(w)
                if r is not None:
                    return r
        return None

    def anchors(self, page, sidebar=True):
        """{title: window rectangle} of every visible hover explanation on
        `page` (the first widget for each title), then the sidebar's titles
        the page doesn't have (sidebar=False leaves them out)."""
        out = {}
        for title, r, at in self.anchor_list(page):
            if (at == "page" or sidebar) and title not in out:
                out[title] = r
        return out

    def anchor_list(self, page):
        """[(title, rect, "page" | "sidebar")]: each title once per side."""
        page = self._current(page)
        out, seen = [], set()
        for w, at in self._widgets(page):
            m = _TITLE.match(w.toolTip() or "")
            if not m:
                continue
            title = html.unescape(m.group(1))
            if (title, at) in seen:
                continue
            r = self._rect(w)
            if r is not None:
                seen.add((title, at))
                out.append((title, r, at))
        return out


def open_app(width=1280, height=800, settle_ms=350) -> Shots:
    """Build the real main window on the DemoController, offscreen."""
    app = QApplication.instance() or QApplication([sys.argv[0] if sys.argv else "app_shots"])
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 9))   # the windows platform's default
    _neutralise_modals()
    import ui_components

    controller = DemoController()
    ui = ui_components.OscGoesPurrrUI(controller)
    controller.ui = ui
    w = ui.window
    w.setAttribute(Qt.WA_DontShowOnScreen, True)
    w.resize(width, height)
    w.show()

    # what main.py does once the window is up
    ui.set_title("OscGoesPurrr")
    ui.build_stored_devices_ui()
    ui.update_connection_status(True, "Built-in engine")
    ui.update_osc_link_state("live", VRCHAT_PORT, listening=True)
    ui._refresh_mode_buttons()
    ui.refresh_output_controls()
    ui.apply_feature_visibility()
    for line in ("VRChat connected on port 9001 (OSCQuery)",
                 "Toy server up (built-in engine)",
                 "Lovense Lush 3 connected · battery 86 %",
                 "Lovense Edge 2 connected · battery 64 %",
                 "Shockers: PiShock hub on COM7 · Collar, Thigh",
                 "bHaptics: TactSuit Pro connected",
                 "Friends online as Blise · 3 friends linked"):
        ui.log_message(line)
    shots = Shots(ui, app, controller, settle_ms)
    shots.pump(200)
    ui.select_view("Home")
    shots.pump()
    return shots


# ========================================================================
# CLI
# ========================================================================

def _safe(name):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")


def dump(out_dir, width=1280, height=800, pages=None, settle_ms=350) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    before = settings_mtimes()
    failures = 0
    try:
        shots = open_app(width, height, settle_ms)
    except Exception:
        traceback.print_exc()
        return 2
    for name in (pages or shots.pages):
        try:
            name = shots.resolve(name)
            img = shots.page(name)
            png = out / f"{_safe(name)}.png"
            if not img.save(str(png)):
                raise RuntimeError(f"could not save {png}")
            found = shots.anchor_list(name)
            with open(out / f"{_safe(name)}.anchors.txt", "w", encoding="utf-8") as fh:
                fh.write(f"# {name}  {img.width()}x{img.height()}  "
                         "title<TAB>x,y,w,h<TAB>page|sidebar\n")
                for title, r, at in found:
                    fh.write(f"{title}\t{r.x()},{r.y()},{r.width()},{r.height()}\t{at}\n")
            print(f"ok   {name:17} {png}  "
                  f"({sum(1 for _t, _r, at in found if at == 'page')} page anchors)", flush=True)
        except Exception:
            failures += 1
            print(f"FAIL {name}", flush=True)
            traceback.print_exc()
    over = shots.sidebar_overflow()
    if over > 0:
        print(f"note: at {width}x{height} the sidebar is {over} px too tall and scrolls "
              f"(as the real app's would); --size {width}x{height + over} avoids that")
    after = settings_mtimes()
    changed = mtime_changes(before, after)
    errors = len(shots.errors)
    print(f"\npage errors: {errors}  failed pages: {failures}  guard refusals: {len(BLOCKED)}")
    if changed:
        who = ("not by this process: the guard refused nothing, so none of its writes "
               "went there - a running OGP writes its logs" if not BLOCKED
               else "see the guard refusals above")
        print(f"settings folder changed during the run ({who}):")
        for p in changed:
            print("   ", p)
    else:
        print(f"settings folder unchanged ({len(before)} files compared)")
    return 1 if failures or errors or BLOCKED else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dump", metavar="DIR", required=True,
                    help="save <page>.png and <page>.anchors.txt for every page here")
    ap.add_argument("--size", default="1280x800", help="window size, WxH (default 1280x800)")
    ap.add_argument("--pages", nargs="*", help="only these pages (default: all)")
    ap.add_argument("--settle-ms", type=int, default=350,
                    help="how long each page settles before the grab")
    args = ap.parse_args(argv)
    w, h = (int(v) for v in args.size.lower().split("x"))
    code = dump(args.dump, w, h, args.pages, args.settle_ms)
    sys.stdout.flush()
    os._exit(code)          # skip Qt's teardown of a never-shown window


if __name__ == "__main__":
    main()
