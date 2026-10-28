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
fails on one that does not exist. Its `icon` is the app's icon for what it
is about, the same one as in the sidebar -- "toys", "shock", "params",
"friends", "suits", "stats", "settings", ... (`ui/icons.ICON_NAMES`) -- or
"" for a change that is about none of them.

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
    icon: str = ""          # ui/icons.ICON_NAMES; "" = none


class Release(NamedTuple):
    version: str
    items: Tuple[Item, ...]


RELEASES: Tuple[Release, ...] = (
    # The whole of 0.14.0 for someone coming from 0.13.0 (and the testers
    # coming from an alpha). The suits are not in it: they stay hidden
    # until a release of their own (main.FEATURES_NOT_YET).
    Release("0.14.0", (
        Item("Friends",
             "Link with other OGP users over the internet: send an invite link "
             "in Discord and you're linked. Friends you allow drive your toys "
             "and shockers, and you theirs - your strength, Off and limits "
             "always hold, and everything is logged. Several can drive you at "
             "once.",
             "friends", icon="friends"),
        Item("Web remote",
             "No OGP on their side? Copy your web remote link, right under + Add "
             "a friend: whoever opens it drives your toys from a browser - no "
             "install, no account. Your shockers and avatar only once you tick "
             "them.",
             "friends", icon="web"),
        Item("Shockers",
             "A PiShock or OpenShock hub over USB. Each shocker gets its own "
             "limits, and you drag it onto what should drive it - a contact, a "
             "touch zone. A shock stays a vibrate until you arm shocks, and "
             "friends get PiShock's own panel, Party Mode included.",
             "features", icon="shock"),
        Item("Avatar Remote",
             "VRC Parameter Relay's board, built in: buttons and sliders for "
             "your avatar's parameters, per avatar. Friends you allow can use "
             "the board of the avatar you're wearing. Relay boards import with "
             "one click.",
             "features", icon="params"),
        Item("Pick what you use",
             "OGP asks once what you have and want, and shows only those pages. "
             "Choose what you use… in Settings → Features asks again.",
             "features", icon="settings"),
        Item("Show me around",
             "Press F1 on any page: it shows what the page is for, and whatever "
             "you point at explains itself. Clicks change nothing while it's on.",
             icon="help"),
        Item("Scrolling never changes a setting",
             "The mouse wheel - or scrolling from VR - passing over a slider, box "
             "or dropdown leaves it alone; the page scrolls on.",
             icon="settings"),
    )),
    Release("0.14.0-alpha.11", (
        Item("Shockers like PiShock's",
             "A friend's shockers now look and work like PiShock's own panel: "
             "Operate, Duration and Warning, Use Mode, STOP and Beep, Random "
             "intensity. The warning works in Remote and Continuous too, and "
             "Party Mode drives several shockers at once, at random or in turn.",
             "friends", icon="shock"),
        Item("Friends check versions",
             "A friend on a newer OGP gets you a note with the way to update; "
             "one on an older OGP gets an OLD tag. Adding friends now folds out "
             "of one + Add a friend button, and you're always on your own list.",
             "friends", icon="friends"),
    )),
    Release("0.14.0-alpha.10", (
        Item("Pick what you use",
             "OGP asks once what you have and want, and shows those pages. "
             "Changed your mind? Choose what you use… in Settings → Features "
             "asks again - Features is now the first thing in Settings.",
             "features", icon="settings"),
    )),
    Release("0.14.0-alpha.9", (
        Item("Add myself",
             "Under your friends list: puts you on it, and your panel is what a "
             "friend sees - working, on your own toys, shockers and avatar, with "
             "every rule a friend's has. Right-click your row to take it off.",
             "friends", icon="friends"),
        Item("Everyone at once",
             "Click TOYS, SHOCKS or AVATAR above the list to switch that for "
             "every friend: off first, on with the next click. The labels now sit "
             "right over their boxes.",
             "friends", icon="friends"),
    )),
    Release("0.14.0-alpha.8", (
        Item("Scrolling never changes a setting",
             "Scroll a page with the mouse wheel or from VR and the pointer "
             "passing over a slider, box or dropdown leaves it alone - the "
             "page scrolls on. Click, drag or type to change a value.",
             icon="settings"),
    )),
    Release("0.14.0-alpha.7", (
        Item("Your shockers, your say",
             "On Home: Share with friends is sharing only, the On / Off switch "
             "next to it is everything. Either off and your friends don't see "
             "your shockers at all.",
             "home", icon="shock"),
        Item("Every parameter, all of it",
             "A friend's ⚡ Every parameter list has Show all at the bottom. Its "
             "values refresh about once a second, so a big list stays light on "
             "the connection.",
             "friends", icon="params"),
    )),
    Release("0.14.0-alpha.6", (
        Item("Room for long parameter names",
             "Avatar Remote: drag the thin bar beside the parameter list to "
             "make it wider - it keeps its width. A name that still doesn't "
             "fit keeps its end: VF246_Acce…ow_Enabled.",
             "features", icon="params"),
        Item("A friend's new avatar, at once",
             "When a friend changes avatar, their board on your Friends page "
             "never shows the old avatar's controls: it says it's getting the "
             "new one and asks again until it's there. Both of you need this "
             "version.",
             "friends", icon="params"),
        Item("No more STOP on Avatar Remote",
             "Each friend's AVATAR switch decides who may use your board, and "
             "Pause all friends on the Friends page stops everyone at once.",
             "friends", icon="params"),
    )),
    Release("0.14.0-alpha.5", (
        Item("Several friends on one person",
             "When others drive the same friend, their panel says +1 OTHER - "
             "hover for who. With Sync with others on (the default) you all "
             "share one set of toy cards: what one of you picks shows up for "
             "everyone and plays once. Everyone needs this version for it.",
             "friends", icon="friends"),
        Item("Drop-outs you can see",
             "When a friend's control drops out for a moment, the Friends log "
             "says so and how long it lasted, instead of stopped / started.",
             "friends", icon="friends"),
        Item("Home keeps its order",
             "Toys, shockers and suits stay in their places on Home: a toy "
             "that comes back sits where it belongs at once.",
             "home", icon="toys"),
    )),
    Release("0.14.0-alpha.4", (
        Item("Shockers and suits in the toy list",
             "One list now: switched on and connected ones right under your "
             "connected toys, the rest grey at the bottom. Each has an On / Off "
             "switch - Off stops it, even after a restart, and leaves who may "
             "use it as it was - and its maker's logo.",
             "home", icon="shock"),
        Item("Only real toys",
             "The built-in toy server no longer takes Bluetooth serial gadgets "
             "- MeshCore radios, ESP32 boards, some watches - for Lovense toys, "
             "so it stops trying to connect to them.",
             icon="toys"),
    )),
    Release("0.14.0-alpha.3", (
        Item("Shockers and suits on Home",
             "Below your toys: a row for the shocker hub and one per suit - "
             "how they are, Stop / Resume, and their sharing switch (Friends "
             "may use them; a suit's contacts from the other suit). Click a "
             "row to open its page.",
             "home", icon="shock"),
        Item("Your testing, fixed",
             "Opening OGP a second time asks whether to switch to the open "
             "window; a second window says so in red. Shocker cards fold for "
             "a narrow window, and a card that grows in Control mode leaves "
             "its neighbour as it was.",
             "friends"),
    )),
    Release("0.14.0-alpha.2", (
        Item("Your testing, fixed",
             "Shocker cards no longer break in a narrow window, the friend "
             "panel stays in line when a toy starts, no little window flashes "
             "when you pick a group, and Darker mode keeps the new panels "
             "dark.",
             "friends"),
        Item("Friends, easier",
             "Drag a friend onto a group to add them; right-click a group to "
             "rename or delete it. Invite links: pick how long it works, then "
             "Copy. You see your friends' toy batteries, and Higher / "
             "Override are always there.",
             "friends", icon="friends"),
        Item("Name your shockers",
             "On the Shockers page - friends see the names too.",
             icon="shock"),
        Item("Toys found faster",
             "While no toy is connected the app looks every 5 seconds "
             "(Settings changes how often), and Home says when it looks next, "
             "with a Scan now button.",
             "home", icon="toys"),
        Item("Statistics off keeps them",
             "Switching statistics off only stops recording. Delete "
             "statistics… right below the switch is what deletes them.",
             "features", icon="stats"),
    )),
    Release("0.14.0-alpha.1", (
        Item("Friends",
             "Link with other OGP users over the internet - send an invite "
             "link in Discord and you're linked. Friends you allow can drive "
             "your toys and shockers, and you theirs, all logged. Your "
             "strength, Off and limits always hold.",
             "friends", icon="friends"),
        Item("Avatar Remote",
             "Boards of controls for your avatar's parameters, per avatar - "
             "VRC Parameter Relay's board, built in. Friends you allow can "
             "use the board of the avatar you wear. Boards from the Relay "
             "import with one click. Switch it on in Settings, under "
             "Features.",
             "features", icon="params"),
        Item("Shockers and suits",
             "A PiShock or OpenShock hub over USB, a bHaptics suit straight "
             "over Bluetooth and an OWO suit through My OWO - each behind its "
             "own switch in Settings, under Features.",
             "features", icon="shock"),
        Item("This is an alpha",
             "A test build of everything new. Something will break - tell us "
             "on GitHub. When the finished 0.14.0 is out, this copy offers it "
             "to you by itself."),
    )),
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
             "appearance", icon="settings"),
        Item("One Home page",
             "Overview and Device Routing are now a single page. Every toy "
             "is a row: click it to open its signal chains right there. "
             "Toys that are switched off stay listed, in grey.",
             "home", icon="toys"),
        Item("Tell your avatar a toy is connected",
             "The app can set an avatar parameter while any toy is "
             "connected, and one per toy — for an icon on your avatar "
             "that lights up with the toy.",
             "toy_presence", icon="toys"),
        Item("Toys are found by themselves",
             "While a toy is missing the app looks for it every few "
             "seconds, so the Refresh and Disconnect buttons are gone.",
             icon="toys"),
        Item("Anti-stuck has a home",
             "The safety cutoff that stops a toy when a contact freezes is "
             "on by default and now lives in Settings, under Toy Safety.",
             "toy_safety", icon="toys"),
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
    later than itself, and a final release's notes stand in for its
    pre-releases' (those were for the testers; "0.14.0" tells the whole
    story, so nobody gets "0.14.0-alpha.11" after it)."""
    out = [r for r in RELEASES if not _is_after(r.version, current)]
    finals = {r.version for r in out if "-" not in r.version}
    out = [r for r in out if "-" not in r.version or r.version.split("-", 1)[0] not in finals]
    return out[:MAX_RELEASES_SHOWN]


def unseen_releases(seen: str, current: str) -> List[Release]:
    """What to show at launch: the releases later than the last one whose
    notes were shown (`seen`, "" for never) and not later than this build,
    newest first. Empty when there is nothing new to tell."""
    return [r for r in releases_for(current) if _is_after(r.version, seen)]


def as_plain(releases) -> list:
    """Releases as plain lists and tuples, for the UI facade."""
    return [(r.version, [(i.title, i.text, i.target, i.icon) for i in r.items])
            for r in releases]
