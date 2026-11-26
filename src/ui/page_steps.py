"""What you do on each page, in a few steps.

One short list per page, shared by everything that explains the app with
pictures: the VRChat group's gallery (tools/make_vrc_group_images.py rings
each step's control in a real screenshot and points at it), Help's
walk-through on the page itself, and the guided tour (ui/tour_steps.py
takes a page step as it is wherever it says the same). They all read this
list, so they never tell two stories.

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
    name ("Avatar Remote" / "My Avatar Remote"); none for a page without.
    Only those names: "System Log" is not "Log"."""
    if name in STEPS:
        return STEPS[name]
    return STEPS.get(_OTHER_NAMES.get(name, ""), ())


# A page's older or newer name -> the name its steps are under
_OTHER_NAMES = {"Avatar Remote": "My Avatar Remote"}


STEPS = {
    "Home": (
        Step("Switch your toy on", "It connects by itself.", "Toy on"),
        Step("Press Test all", "Every toy buzzes once.", "Test all"),
        Step("Choose who it feels", "Touch or penetration, yours or others'.",
             ("Touch from yourself", "Touch from others",
              "Penetration from yourself", "Penetration from others")),
        Step("Put one toy to sleep", "Three strokes wake it. Anti-stuck: on for each toy.",
             ("Sleep (this toy)", "Anti-stuck (this toy)")),
        Step("One strength for all", "Off silences everything.", "Total output strength"),
    ),
    "Toys": (
        Step("Switch your toy on", "Scan now looks at once.", "Scan now"),
        Step("Click a toy to tune it", "A signal chain for every contact.",
             ("Input", "Depth", "Punch", "Output")),
        Step("Build your own zones", "From any contact on your avatar.", "SPS Sources"),
        Step("Tune against a test stroke", "The simulator and the signal graph.",
             "Tuning tools"),
        Step("Stop a frozen contact", "Anti-stuck and its timers, for every toy.",
             "Toys' anti-stuck"),
    ),
    "Friends": (
        Step("Add a friend", "An invite link, one click in Discord.", "Add a friend"),
        Step("Choose what each may use", "Pause all stops everyone.",
             ("Toys", "Shockers", "Avatar Remote")),
        Step("Drive their toys", "Patterns, sliders, or all of it big.", "Control mode"),
        Step("Drive together", "Sync on: everyone driving you shares one set of cards.",
             "Sync with others"),
    ),
    "Shockers": (
        Step("Plug in your hub", "PiShock or OpenShock, over USB.", "Connect"),
        Step("Arm shocks", "It asks first. Red words: armed or not.",
             ("Arm shocks", "Shocks armed or not")),
        Step("Stop all", "Everything stops at once.", "Stop all / Resume"),
        Step("Drag shockers onto a behaviour", "Touch zones, headpats, impacts.",
             "Add behaviour"),
        Step("Separate limits for friends", "Off: one set for all. On: friends get their own.",
             "Separate limits for friends"),
    ),
    "Suits": (
        Step("Watch every touch land", "Both suits on one body.", "Body"),
        Step("Connect your bHaptics suit", "Bluetooth, no bHaptics Player.", "Connect"),
        Step("Feel both suits at once", "One touch, bHaptics and OWO.",
             "Also feel OWO's contacts"),
    ),
    "PSVR2": (
        Step("Start SteamVR with the toolkit", "PSVR2Toolkit, run once.", "Link"),
        Step("Pick your avatar's contact", "Its touch rumbles the headset.", "Contact"),
        Step("Feel it", "Silent? It needs a jailbreak.", "Feel it"),
        Step("Set the rumble band", "Slow thump to fast buzz.", ("Lowest", "Highest")),
    ),
    "My Avatar Remote": (
        Step("Wear your avatar", "Its board opens by itself.", "Avatar name"),
        Step("Build a board", "Toggles, buttons and sliders.", "Outfit"),
        Step("Put it in your avatar's menu", "Seven toggles, seven radials.",
             "Avatar menu slot"),
        Step("Change your height", "Grow glides, Right away jumps.", "Height"),
        Step("Friends can join in", "They see the avatar you wear.", "Friends looking"),
        Step("Bring your Relay boards", "One click import.", "Import"),
    ),
    "Log": (
        Step("See who did what", "A row per person, last thing first.", "A person in the log"),
        Step("Pick one person", "Or everyone but your avatar.", "Person"),
        Step("Only shocks, or toys", "Leave out what you don't need.", "Show shocks"),
        Step("Search a name or shocker", "Kept 30 days, on this PC only.", "Search the log"),
    ),
}
