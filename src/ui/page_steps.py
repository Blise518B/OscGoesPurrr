"""What you do on each page, in a few steps.

One short list per page, shared by everything that explains the app with
pictures: the VRChat group's gallery (tools/make_vrc_group_images.py rings
each step's control in a real screenshot and points at it) and Help's
walk-through on the page itself. Both read this list, so they never tell
two stories.

A step finds its control by the title of the control's hover explanation
(ui/tooltips.py) -- or, for a control without one, by what it says -- so
it follows the control wherever a redesign moves it; the gallery generator
stops when a target is no longer on its page. A tuple of targets rings
them together.

Keep it short -- a few words a step, a few more in its hint. The hover
explanations already say the rest.
"""

from typing import NamedTuple, Tuple, Union


class Step(NamedTuple):
    label: str                              # what you do, a few words
    hint: str                               # one short line more
    target: Union[str, Tuple[str, ...]]     # the control(s) it is about


def for_page(name: str) -> Tuple[Step, ...]:
    """The steps of the page called `name` -- also under its older or newer
    name ("Avatar Remote" / "My Avatar Remote"); none for a page without."""
    if name in STEPS:
        return STEPS[name]
    for key, steps in STEPS.items():
        if name and (key.endswith(name) or name.endswith(key)):
            return steps
    return ()


STEPS = {
    "Home": (
        Step("Switch your toy on", "It connects by itself.", "Toy on"),
        Step("Press Test all", "Every toy buzzes once.", "Test all"),
        Step("Click a toy to tune it", "A signal chain for every contact.",
             ("Input", "Depth", "Punch", "Output")),
        Step("One strength for all", "Off silences everything.", "Total output strength"),
    ),
    "Friends": (
        Step("Add a friend", "An invite link, one click in Discord.", "Add a friend"),
        Step("Choose what each may use", "Pause all stops everyone.",
             ("Toys", "Shockers", "Avatar Remote")),
        Step("Drive their toys", "Patterns, sliders, or all of it big.", "Control mode"),
        Step("Drive together", "Several friends, one set of cards.", "Sync with others"),
    ),
    "Shockers": (
        Step("Plug in your hub", "PiShock or OpenShock, over USB.", "Connect"),
        Step("Arm shocks", "Until then a shock is a vibrate.", "Arm shocks"),
        Step("Stop all", "Everything stops at once.", "Stop all / Resume"),
        Step("Drag shockers onto a behaviour", "Touch zones, headpats, impacts.",
             "Add behaviour"),
    ),
    "Suits": (
        Step("Watch every touch land", "Both suits on one body.", "Body"),
        Step("Connect your bHaptics suit", "Bluetooth, no bHaptics Player.", "Connect"),
        Step("Feel both suits at once", "One touch, bHaptics and OWO.",
             "Also feel OWO's contacts"),
    ),
    "My Avatar Remote": (
        Step("Wear your avatar", "Its board opens by itself.", "Avatar name"),
        Step("Build a board", "Toggles, buttons and sliders.", "Outfit"),
        Step("Friends can join in", "They see the avatar you wear.", "Friends looking"),
        Step("Bring your Relay boards", "One click import.", "Import"),
    ),
}
