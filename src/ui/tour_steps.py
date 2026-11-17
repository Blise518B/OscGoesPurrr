"""The guided tour's steps: the first launch walked through for real.

The tour (ui/tour.py) lights one control at a time on help mode's drawing
and moves on when the real thing happens -- a toy connects, its card
opens, a zone is picked -- never by itself changing a setting. These are
its steps, in order: the toy path first, then a short branch for each
feature picked in "What are you here for?".

It tells the same story as ui/page_steps.py (Help's walk-through and the
VRChat gallery): where a page step already says it, the tour step *is*
that step (`from_page`), so the words can't drift apart. A step finds its
control the same way -- by the title of the control's hover explanation,
or by what it says -- and the tests fail when one is gone, as for
page_steps.

Pure data: no Qt, no settings, no I/O. The window answers the `waits`
keys (ui/views/tour.py `TourMixin`): a step is done when its key says so.
"""

from typing import NamedTuple, Tuple, Union

from ui import page_steps

Target = Union[str, Tuple[str, ...]]

# What moves a step on -- answered by the window (TourMixin._tour_waiter):
WAITS = (
    "toy",            # a toy is connected
    "toy_card_open",  # the tour's toy's card is open on the Toys page
    "input_open",     # its Input stage is open (Select Zones shows)
    "zones_open",     # its zone list is open
    "zone_picked",    # one of its zones was switched
    "chips",          # one of its four contact chips was clicked
    "click",          # the lit control was clicked (the tour sees the click)
    "strength",       # total output strength moved
    "next",           # only the strip's button: a look, nothing to do
)

# Where a step looks for its control: "" = its page, then the whole window
# (the sidebar); "toy" = the tour's toy's card on the Toys page; "toy_row" =
# its row on Home.
SCOPES = ("", "toy", "toy_row")

# Stands for the tour's toy's name in a target (its row is titled with it).
TOY = "{toy}"
# A folded chain's bar (ui/motor_signal_chain.CHAIN_FOLD_TITLE).
CHAIN = "Signal chain"


class TourStep(NamedTuple):
    key: str                    # unique, for tests and the window's answers
    page: str                   # the page it happens on ("" = any: the sidebar)
    label: str                  # what you do, a few words
    hint: str                   # one short line more
    targets: Tuple[Target, ...]  # the control(s) lit: the first one found of these
    waits: str                  # what moves it on (WAITS)
    waiting: str                # what it waits for, in words, on the bubble
    button: str = ""            # the strip's button ("" = "Skip this step")
    more: str = ""              # a longer word under the hint (what to check)
    scope: str = ""             # where to look (SCOPES)
    needs: str = ""             # "toy", or a feature switch it needs ("" = always)
    branch: str = ""            # the feature branch it opens (its first step)


def from_page(key: str, page: str, label: str, waits: str = "next",
              waiting: str = "Next moves on", needs: str = "", button: str = "Next",
              **more) -> TourStep:
    """The page step labelled `label` on `page` (ui/page_steps.py) as a tour
    step: the same words and control, so Help and the tour say one thing."""
    step = next(s for s in page_steps.for_page(page) if s.label == label)
    return TourStep(key, page, step.label, step.hint, (step.target,), waits, waiting,
                    button=button, needs=needs, **more)


_TOY_CHECKS = (
    "Nothing yet? Check that the toy is switched on and closed in its own "
    "phone app (a toy talks to one thing at a time), that this PC's Bluetooth "
    "is on - and if your Intiface runs on a phone, Settings → Intiface Engine "
    "has its address.")


TOUR: Tuple[TourStep, ...] = (
    # ---- your toy -------------------------------------------------------
    TourStep("connect", "Home", "Switch your toy on", "It connects by itself, over Bluetooth.",
             ("Switch your toy on", "Toy on"), "toy", "Waiting for a toy to connect",
             button="Continue without a toy", more=_TOY_CHECKS, needs="feature_intiface"),
    TourStep("toy", "Home", "Here's your toy", "Lit up as it connects. Click it to open it.",
             (TOY,), "toy_card_open", "Waiting for a click on your toy",
             scope="toy_row", needs="toy"),
    # Its card opens on the motors' folded chains (2026-11-16): while the
    # chain is folded the step lights it, then its Input.
    TourStep("input", "Toys", "Open its Input",
             "Open its chain, then Input - where its signal comes from.",
             ("Input", CHAIN), "input_open", "Waiting for a click on Input",
             scope="toy", needs="toy"),
    TourStep("zones", "Toys", "Select Zones: your SPS sources",
             "The parts of your avatar that drive this toy.",
             ("Zone selector",), "zones_open", "Waiting for a click on Select Zones",
             scope="toy", needs="toy"),
    TourStep("pick", "Toys", "Pick your zones", "All SPS hears every zone; or pick a few.",
             ("Your SPS sources",), "zone_picked",
             "Waiting for a zone to be switched - Next keeps these",
             button="Next", scope="toy", needs="toy"),
    from_page("chips", "Home", "Choose who it feels", waits="chips",
              waiting="Waiting for a chip - Next keeps them", needs="toy",
              scope="toy")._replace(page="Toys"),
    TourStep("test", "Toys", "Press Test", "Your toy buzzes for a second.",
             ("Test",), "click", "Waiting for a click on Test", scope="toy", needs="toy"),
    from_page("strength", "Home", "One strength for all", waits="strength",
              waiting="Waiting for the slider - Next keeps it",
              needs="feature_intiface")._replace(page=""),
    TourStep("menu", "Settings", "Optional: OGP's menu in your avatar",
             "Strength, Off and the modes right in VRChat: one VRCFury prefab.",
             ("Get the menu prefabs",), "next", "Optional - Next moves on", button="Next"),

    # ---- a short branch for each feature picked -------------------------
    from_page("shockers", "Shockers", "Plug in your hub", needs="feature_pishock",
              branch="Shockers"),
    from_page("arm", "Shockers", "Arm shocks", needs="feature_pishock")._replace(
        targets=(("Arm shocks", "Shocks armed or not"), "Arm shocks?")),
    TourStep("limits", "Shockers", "Your limits", "Every shock and vibrate stays under them.",
             ("Limits",), "next", "Next moves on", button="Next", needs="feature_pishock"),
    from_page("separate", "Shockers", "Separate limits for friends", needs="feature_pishock"),

    from_page("suits", "Suits", "Watch every touch land", needs="suits", branch="Suits"),
    from_page("suit_connect", "Suits", "Connect your bHaptics suit", needs="feature_bhaptics"),

    from_page("psvr2", "PSVR2", "Start SteamVR with the toolkit", needs="feature_psvr2",
              branch="PSVR2"),
    from_page("psvr2_feel", "PSVR2", "Feel it", needs="feature_psvr2"),

    TourStep("friends", "Friends", "Pick a nickname", "Nothing goes online until you do.",
             ("Your nickname",), "next", "Next moves on", button="Next",
             needs="feature_friends", branch="Friends"),
    from_page("friends_add", "Friends", "Add a friend", needs="feature_friends"),

    from_page("remote", "My Avatar Remote", "Wear your avatar", needs="feature_params",
              branch="Avatar Remote"),
    # the page step rings a category of the gallery's demo board; a new
    # board starts at ＋ Category
    from_page("remote_board", "My Avatar Remote", "Build a board",
              needs="feature_params")._replace(targets=("＋ Category",)),

    # ---- the end ----------------------------------------------------------
    TourStep("done", "", "That's the tour", "Take it again any time from Help or "
             "Getting started.", ("Help",), "next", "Finish ends it", button="Finish"),
)


def step(key: str) -> TourStep:
    return next(s for s in TOUR if s.key == key)
