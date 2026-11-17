"""Render the user guide's screenshots from the real app.

Every picture in guide/docs/**/img/ is the actual main window, built
headless on tools/app_shots.py's demo data (its DemoController: no OSC, no
Bluetooth, no serial port, no network), then cropped to the part a guide
page talks about. Nothing is drawn by hand, so when a page of the app
changes, run this again and rebuild the guide (tools/build_guide.py):

    venv\\Scripts\\pythonw.exe tools\\make_guide_images.py            # all
    venv\\Scripts\\python.exe tools\\make_guide_images.py home shockers-hub
    venv\\Scripts\\python.exe tools\\make_guide_images.py --list

It never writes OGP's real settings: app_shots' guard refuses every write
under %APPDATA%\\OscGoesPurrr for the whole process, and this compares the
folder before and after like `app_shots.py --dump` does. The version shown
is version.py's VERSION without the branch suffix a checkout adds.

Each shot below: a name (the file, and what to pass to pick it), the guide
folder it goes into, the window size, what to do first (open a page, click
something, scroll) and what to keep (the window, the page beside the
sidebar, or one card / row / box found by its title -- a hover
explanation's title or what a label or button says, as app_shots finds
them).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "guide" / "docs"

# The plain release version in the window, not "0.15.1-<branch>(3) · b446":
# version.py takes a baked module first, as a built exe does
_VERSION = re.search(r'^VERSION = "([^"]+)"', (REPO / "src" / "version.py").read_text(
    encoding="utf-8"), re.M).group(1)
_baked = types.ModuleType("_version_baked")
_baked.VERSION, _baked.SHORT_HASH, _baked.BUILD = _VERSION, "", 0
sys.modules["_version_baked"] = _baked

sys.path.insert(0, str(REPO / "tools"))
import app_shots  # noqa: E402  (sets up Qt offscreen and the guard)

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from ui import theme as _theme  # noqa: E402

# the headline's tag as a release shows it, without the build number
_theme.title_tag = lambda version, _build: f"v{version}"
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QFrame, QWidget  # noqa: E402

# A whole-window shot is the app's own default window size. A card or row is
# cropped from a 1000 px wide window: about as wide as the guide's text
# column, so it shows at full size there (a wider one would shrink).
WINDOW = (1100, 740)
CROP_W = 1000
# Home's rows take one line from about this wide (device_frame._fit_toy_bar)
WIDE_ROW_W = 1300

# What counts as "the card" around a title: the app's card frames
CARDS = ("card", "cardDark", "paramCard", "paramCat", "toyFrame")


@dataclass
class Shot:
    name: str                   # file name (without .png); also picks it on the command line
    folder: str                 # under guide/docs/ ("" = guide/docs/img)
    page: str                   # the app page
    keep: object = "window"     # "window" | "page" | ("card", title[, names]) |
                                # ("widget", title) | ("sidebar", top, bottom)
    size: tuple = None          # None: WINDOW for a whole-window shot, else (CROP_W, 900)
    do: tuple = ()              # ("click", title) | ("scroll", title) | ("call", fn) | ("pump", ms)
    pad: int = 10               # around a card / widget
    note: str = ""              # what it shows (for --list)


def _click(shots, page, title):
    w = shots._find(page, title)
    if w is None:
        raise SystemExit(f"{page}: nothing titled {title!r} to click")
    QTest.mouseClick(w, Qt.LeftButton)
    shots.pump(250)


def _toy_open(shots, _page):
    """A demo toy's card on the Toys page with its chain opened."""
    shots.open_chain("Lovense Lush 3")


def _select(kind, sid_of):
    def go(shots, _page):
        ctl = shots.controller
        sid = sid_of(ctl)
        shots.ui._friends_select(kind, sid)
        shots.pump(300)
    return go


def _separate_limits(shots, _page):
    """Separate limits for friends on, the page redrawn with it."""
    shots.controller.set_pishock_separate_limits(True)
    shots.ui._pishock_cards_key = None
    shots.ui.refresh_pishock_status()
    shots.pump(200)


def _group_id(ctl):
    status = ctl.get_friends_status()
    groups = status.get("groups") or []
    if not groups:
        raise SystemExit("the demo has no friend group")
    return groups[0]["id"]


def _control_mode(shots, _page):
    shots.ui._set_friends_control(True)
    shots.pump(300)


def _openshock(live=False):
    """Nova's panel (three shockers, armed) with OpenShock's shocker buttons
    -- out of control mode; `live`: the first card's Live control, a finger
    moving on its pad."""
    def go(shots, _page):
        import friends_demo
        shots.ui._set_friends_control(False)
        shots.controller.set_shocker_layout("openshock")
        shots.ui._friends_select("friend", friends_demo._id(3))
        shots.pump(300)
        if live:
            card = shots.ui._panel_w["shockers"][0]
            card.live_tag.setChecked(True)
            shots.pump(150)
            pad = card.pad
            pad._dragging = True
            pad._start_trace()
            for y in (0.95, 0.85, 0.7, 0.55, 0.45, 0.5, 0.6, 0.5, 0.38, 0.3, 0.32, 0.35):
                pad._moved(y)
                shots.pump(170)
    return go


SHOTS = (
    # ---- getting started ---------------------------------------------------
    Shot("home", "", "Home", note="Home with two toys, the shocker hub, both suits, the headset"),
    Shot("features", "", "Settings", ("card", "Choose what you use"),
         note="Settings -> Features"),

    # ---- toys -----------------------------------------------------------------
    # Home's rows from a wider window: on one line, as Blise designed them
    # (2026-11-16); at the crops' 1000 px they'd take their narrower layout
    Shot("home-toy-row", "toys", "Home", ("card", "Lovense Lush 3"), size=(WIDE_ROW_W, 900), pad=3,
         note="one toy's row on Home: zones, the four chips, Sleep / Anti-stuck, battery, "
              "meters, Mute, Test"),
    Shot("home-device-rows", "toys", "Home", "page", size=(WIDE_ROW_W, 600),
         note="Home's device rows"),
    Shot("toys-page", "toys", "Toys", note="the Toys page"),
    Shot("toy-card", "toys", "Toys", ("card", "Lovense Lush 3"), size=(1000, 1000),
         do=(("call", _toy_open),),
         note="a toy's card with its chain opened"),
    Shot("sidebar-top", "toys", "Home", ("sidebar", 0, 290), note="modes, total strength, Off, Sleep"),
    Shot("toy-safety", "toys", "Settings", ("card", "Safety"), size=(1000, 1100),
         do=(("scroll", "Safety"),), note="Settings -> Safety (Toy Safety until 2026-11-17)"),
    Shot("toys-antistuck", "toys", "Toys", ("card", "Toys' anti-stuck"),
         note="the toys' anti-stuck under Toy server"),
    Shot("toy-server", "toys", "Toys", ("card", "Toy server"), note="the Toys page's Toy server line"),

    # ---- your avatar ------------------------------------------------------------
    Shot("vrchat-menu", "avatar", "Settings", ("card", "Get the menu prefabs"),
         do=(("scroll", "Get the menu prefabs"),), note="Settings -> VRChat menu"),
    Shot("connection-settings", "avatar", "Settings", ("card", "Connection Settings"),
         size=(1000, 1100), do=(("scroll", "Connection Settings"),),
         note="Settings -> Connection Settings"),

    # ---- shockers -----------------------------------------------------------------
    Shot("shockers-page", "shockers", "Shockers", note="the Shockers page"),
    Shot("hub", "shockers", "Shockers", ("card", "Hub"), note="the hub card"),
    Shot("shocker-card", "shockers", "Shockers", ("card", "Collar", ("paramCard",)),
         note="one shocker's card: Allowed, Limits, Tell VRChat, Test"),
    Shot("home-shocker-row", "shockers", "Home", ("card", "Shockers"), size=(WIDE_ROW_W, 900), pad=3,
         note="Home's shocker row: Arm shocks, Share with friends, On"),
    Shot("behaviours", "shockers", "Shockers", ("card", "Add behaviour", ("paramCat",)),
         size=(1000, 1300), do=(("scroll", "Add behaviour"),), note="the behaviours"),
    # last of the shockers: the switch stays on for the rest of the run
    Shot("friends-limits", "shockers", "Shockers", ("card", "Every shocker", ("paramCard",)),
         size=(1100, 1400), do=(("call", _separate_limits), ("scroll", "Every shocker")),
         note="the Every shocker card with Separate limits for friends on"),

    # ---- friends --------------------------------------------------------------------
    Shot("friends-page", "friends", "Friends", note="the Friends page"),
    Shot("friend-list", "friends", "Friends", ("card", "Read VRChat's log"), size=(1000, 1000),
         note="the list: you, friends, the instance, groups"),
    Shot("friend-panel", "friends", "Friends", ("card", "Control mode"), size=(1000, 2200),
         do=(("scroll", "Control mode"),), note="a friend's panel"),
    Shot("group-panel", "friends", "Friends", ("card", "Control mode"), size=(1000, 1500),
         do=(("call", _select("group", _group_id)), ("scroll", "Control mode")),
         note="a group's panel"),
    Shot("control-mode", "friends", "Friends", "page", size=(1000, 1100),
         do=(("call", _select("friend", lambda c: c.mika)), ("call", _control_mode)),
         note="Control mode"),

    # ---- avatar remote ------------------------------------------------------------
    Shot("avatar-remote", "avatar-remote", "My Avatar Remote", size=(1100, 760),
         note="My Avatar Remote"),
    Shot("height", "avatar-remote", "My Avatar Remote", ("card", "Height", ("paramCat",)),
         size=(1000, 1100), do=(("scroll", "Height"),), note="the Height box"),

    # ---- suits, PSVR2 ---------------------------------------------------------------
    Shot("suits", "suits", "Suits", size=(1100, 800), note="the Suits page"),
    Shot("suit-antistuck", "suits", "Suits", ("card", "bHaptics anti-stuck", ("paramCard",)),
         size=(1000, 2400), do=(("scroll", "bHaptics anti-stuck"),),
         note="the bHaptics suit's own anti-stuck card"),
    Shot("psvr2", "", "PSVR2", note="the PSVR2 page"),

    # ---- records ----------------------------------------------------------------------
    Shot("statistics", "records", "Statistics", note="Statistics"),
    Shot("from-whom", "records", "Statistics", ("card", "From whom"), size=(1000, 1100),
         do=(("scroll", "From whom"),), note="the From whom card"),
    Shot("log", "records", "Log", note="the Log page"),

    # ---- settings and tools ------------------------------------------------------------
    Shot("appearance", "settings", "Settings", ("card", "Appearance"), size=(1000, 1000),
         do=(("scroll", "Appearance"),), note="Settings -> Appearance"),
    Shot("help", "settings", "Help", note="the Help page"),

    # ---- last: they leave the Friends panel in OpenShock's layout ------------------------
    Shot("openshock-layout", "friends", "Friends", ("card", "Shocker buttons", ("friendSection",)),
         size=(1000, 1400), do=(("call", _openshock()), ("scroll", "Shocker buttons")),
         note="a friend's shockers with OpenShock's buttons"),
    Shot("live-control", "friends", "Friends", ("card", "Shocker buttons", ("friendSection",)),
         size=(1000, 1400), do=(("call", _openshock(live=True)), ("scroll", "Shocker buttons")),
         note="OpenShock's Live control"),
)


# ---- doing and keeping ------------------------------------------------------------

def _window_rect(shots, w: QWidget) -> QRect:
    return QRect(w.mapTo(shots.ui.window, QPoint(0, 0)), w.size())


def _card(shots, page, title, names=CARDS) -> QWidget:
    w = shots._find(page, title)
    if w is None:
        raise SystemExit(f"{page}: nothing titled {title!r}")
    while w is not None and not (isinstance(w, QFrame) and w.objectName() in names):
        w = w.parentWidget()
    if w is None:
        raise SystemExit(f"{page}: {title!r} sits in no card ({', '.join(names)})")
    return w


def _scroll_into_view(shots, page, w: QWidget) -> None:
    area = shots.ui.views[page]
    if not hasattr(area, "verticalScrollBar") or not area.isAncestorOf(w):
        return
    y = w.mapTo(area.widget(), QPoint(0, 0)).y() - 12
    area.verticalScrollBar().setValue(max(0, y))
    shots.pump(80)


def size_of(shot: Shot) -> tuple:
    return shot.size or (WINDOW if shot.keep == "window" else (CROP_W, 900))


def render(shots, shot: Shot):
    shots.ui.window.resize(*size_of(shot))
    shots.pump(120)
    page = shots.show(shot.page)
    shots.scroll_to(page, 0)
    for kind, arg in shot.do:
        if kind == "click":
            _click(shots, page, arg)
        elif kind == "scroll":
            shots.scroll_to(page, arg)
        elif kind == "call":
            arg(shots, page)
        elif kind == "pump":
            shots.pump(arg)
    keep = shot.keep
    if keep == "window":
        rect = shots.ui.window.rect()
    elif keep == "page":
        rect = _window_rect(shots, shots.ui.main_stack)
    elif keep[0] == "sidebar":
        side = _window_rect(shots, shots.ui.sidebar_frame)
        rect = QRect(side.x(), keep[1], side.width(), keep[2] - keep[1])
    elif keep[0] in ("card", "widget"):
        names = keep[2] if len(keep) > 2 else CARDS
        w = _card(shots, page, keep[1], names) if keep[0] == "card" else shots._find(page, keep[1])
        if w is None:
            raise SystemExit(f"{page}: nothing titled {keep[1]!r}")
        if shots._rect(w) is None or shots._rect(w).height() < w.height():
            _scroll_into_view(shots, page, w)
        rect = _window_rect(shots, w).adjusted(-shot.pad, -shot.pad, shot.pad, shot.pad)
        seen = shots._rect(w)
        if seen is None or seen.height() < w.height() - 1:
            raise SystemExit(f"{shot.name}: {keep[1]!r}'s card doesn't fit in "
                             "{}x{}: make the window taller".format(*size_of(shot)))
    else:
        raise SystemExit(f"{shot.name}: don't know how to keep {keep!r}")
    rect = rect.intersected(shots.ui.window.rect())
    return shots.ui.window.grab().toImage().copy(rect)


def out_path(shot: Shot) -> Path:
    return (DOCS / shot.folder / "img" if shot.folder else DOCS / "img") / f"{shot.name}.png"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*", help="only these shots (default: all)")
    ap.add_argument("--list", action="store_true", help="list the shots and stop")
    args = ap.parse_args(argv)
    if args.list:
        for s in SHOTS:
            print(f"{s.name:20} {out_path(s).relative_to(REPO).as_posix():48} {s.note}")
        return 0
    wanted = [s for s in SHOTS if not args.names or s.name in args.names]
    unknown = set(args.names) - {s.name for s in SHOTS}
    if unknown:
        print("no such shot:", ", ".join(sorted(unknown)))
        return 2

    before = app_shots.settings_mtimes()
    shots = app_shots.open_app(*WINDOW)
    failed = 0
    for shot in wanted:
        try:
            img = render(shots, shot)
            path = out_path(shot)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not img.save(str(path)):
                raise RuntimeError(f"could not save {path}")
            print(f"ok   {shot.name:20} {img.width()}x{img.height()}  "
                  f"{path.relative_to(REPO).as_posix()}", flush=True)
        except (Exception, SystemExit) as e:  # one bad shot doesn't stop the rest
            failed += 1
            print(f"FAIL {shot.name}: {e}", flush=True)
    changed = app_shots.mtime_changes(before, app_shots.settings_mtimes())
    if changed:
        print("OGP's settings folder changed during the run (a running OGP writes its logs;"
              " the guard refused this process nothing):" if not app_shots.BLOCKED else
              "OGP's settings folder changed:", *changed, sep="\n    ")
    print(f"\n{len(wanted) - failed} of {len(wanted)} shots, settings folder "
          f"{'CHANGED' if changed else 'unchanged'}", flush=True)
    sys.stdout.flush()
    os._exit(1 if failed else 0)    # skip Qt's teardown of a never-shown window


if __name__ == "__main__":
    main()
