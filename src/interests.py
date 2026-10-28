"""What are you here for? -- asked once, to pick the features someone uses.

A new install asks it at its first launch, and an install from before this
question asks it once at its first launch with it; after that, never again
by itself (Settings → Features opens it on request). Each choice is a
plain question about what someone has or wants, and each one is a feature
switch from Settings → Features: what is ticked comes on, what isn't goes
off. It starts from the switches as they are, so nobody loses a feature
they use by answering. The window is `ui/views/interests.py`, the launch
hook `controllers/interests_facade.py`.

Adding a feature: give it a `Choice` here too -- a test fails on a public
feature switch the question leaves out.

Pure data and one rule: no Qt, no settings, no I/O.
"""
from __future__ import annotations

from typing import Dict, NamedTuple, Tuple

# The app setting that remembers the question was answered (or skipped).
ASKED_KEY = "interests_asked"


class Choice(NamedTuple):
    feature: str        # the feature switch it sets
    title: str
    hint: str


class Group(NamedTuple):
    title: str
    choices: Tuple[Choice, ...]


GROUPS: Tuple[Group, ...] = (
    Group("WHAT YOU HAVE", (
        Choice("feature_intiface", "Toys",
               "Lovense and the others Buttplug.io knows, by Bluetooth or USB"),
        Choice("feature_pishock", "A shocker",
               "PiShock or OpenShock, on its USB hub"),
        Choice("feature_bhaptics", "A bHaptics suit or sleeves",
               "Over Bluetooth, without the bHaptics Player"),
        Choice("feature_owo", "An OWO suit",
               "Through the My OWO app"),
    )),
    Group("WHAT YOU WANT", (
        Choice("feature_friends", "Play with friends over the internet",
               "They drive your toys or shockers if you let them, you theirs"),
        Choice("feature_params", "An avatar remote friends can use too",
               "Buttons and sliders for your avatar's parameters"),
        Choice("feature_statistics", "Statistics of my sessions",
               "Charts and totals, kept only on this PC"),
        Choice("feature_osc_inspector", "OSC Inspector (for avatar makers)",
               "Every parameter your avatar sends, live"),
    )),
)


def features() -> Tuple[str, ...]:
    """Every feature switch the question sets, in its order."""
    return tuple(c.feature for g in GROUPS for c in g.choices)


def changes(current: Dict[str, bool], picked: Dict[str, bool]) -> Dict[str, bool]:
    """The switches an answer flips: the question's features whose ticked
    state differs from the switch as it is. A feature the answer leaves
    out stays as it is."""
    return {k: bool(picked[k]) for k in features()
            if k in picked and bool(picked[k]) != bool(current.get(k))}
