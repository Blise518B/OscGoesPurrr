"""What changed -- told once, to someone who just updated.

After an update the app opens a small "What's new" window at launch: a few
lines per release, and where a change has a home in the app, a "Take me
there" button that opens it. This module is the content and the rule for
when it shows; the window is `ui/views/whats_new.py` and the launch hook
`controllers/whats_new_facade.py`.

Adding a release: put a new entry at the TOP of `RELEASES`, under the
version it ships as (`VERSION` in version.py). Keep it to what a user
would notice -- tools/RELEASE_NOTES.md is the place for the full list. A
release with nothing to show simply has no entry. An item's `target` names
a place the window can open (`ui/views/whats_new.py`'s `PLACES`); a test
fails on one that does not exist.

Pure data and one rule: no Qt, no settings, no I/O.
"""
from __future__ import annotations

from typing import List, NamedTuple, Tuple

from update_checker import compare_versions

# The app setting that remembers the newest version whose notes were shown.
SEEN_KEY = "whats_new_seen_version"
# Someone who skipped several updates gets the newest few, not a scroll.
MAX_RELEASES_SHOWN = 2


class Item(NamedTuple):
    title: str
    text: str
    target: str = ""        # "" = nothing to open


class Release(NamedTuple):
    version: str
    items: Tuple[Item, ...]


RELEASES: Tuple[Release, ...] = (
    Release("0.13.0", (
        Item("Now on Linux too",
             "OscGoesPurrr has a Linux version: one AppImage on the "
             "releases page, with the toy server built in, just like here. "
             "Handy if a friend plays VRChat on Linux."),
    )),
    Release("0.12.0", (
        Item("Any colour you like",
             "Not a green person? Pick a colour in Settings and the whole "
             "app turns to it while you watch. There is a Vibrant and a "
             "Darker look to choose from, too.",
             "appearance"),
        Item("One Home page",
             "Overview and Device Routing are now a single page. Every toy "
             "is a row: click it to open its signal chains right there. "
             "Toys that are switched off stay listed, in grey.",
             "home"),
        Item("Tell your avatar a toy is connected",
             "The app can set an avatar parameter while any toy is "
             "connected, and one per toy — for an icon on your avatar "
             "that lights up with the toy.",
             "toy_presence"),
        Item("Toys are found by themselves",
             "While a toy is missing the app looks for it every few "
             "seconds, so the Refresh and Disconnect buttons are gone."),
        Item("Anti-stuck has a home",
             "The safety cutoff that stops a toy when a contact freezes is "
             "on by default and now lives in Settings, under Toy Safety.",
             "toy_safety"),
    )),
)


def _is_after(a: str, b: str) -> bool:
    """`a` is a later version than `b`. Something that is not a version
    counts as "before everything" on the right and never as later on the
    left."""
    order = compare_versions(a, b)
    if order is not None:
        return order > 0
    return compare_versions(a, a) is not None      # a is a version, b is not


def releases_for(current: str) -> List[Release]:
    """The newest releases this build contains, newest first -- what the
    "What's new" button shows. A build never shows notes for a version
    later than itself."""
    out = [r for r in RELEASES if not _is_after(r.version, current)]
    return out[:MAX_RELEASES_SHOWN]


def unseen_releases(seen: str, current: str) -> List[Release]:
    """What to show at launch: the releases later than the last one whose
    notes were shown (`seen`, "" for never) and not later than this build,
    newest first. Empty when there is nothing new to tell."""
    return [r for r in releases_for(current) if _is_after(r.version, seen)]


def as_plain(releases) -> list:
    """Releases as plain lists and tuples, for the UI facade."""
    return [(r.version, [(i.title, i.text, i.target) for i in r.items])
            for r in releases]
