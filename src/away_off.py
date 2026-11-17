"""Off while you're away: which avatar parameters hold everything off.

Three kinds of source, each a parameter VRChat sends over OSC:

* VRChat's own ``AFK`` -- true while you're away (the headset's
  proximity sensor, or the End key on desktop).
* GoGo Loco's AFK button. It has no parameter of its own: the toggle in
  its Locomotion menu sets ``VRCEmote`` to 101, and its animator's AFK
  states start on ``AFK`` or ``VRCEmote == 101`` (read off GoGo Loco
  1.8.6's ``GoMenuLoco`` menu and ``GoLocoAction`` controller).
* Parameters the user picks ("Also off while ..."): any of them true --
  a Bool that is true, a number above zero -- holds everything off. A
  parameter of your own in your avatar's menu is your own Off switch.

While any source is on, the controller holds the same Off as ``OGP/Off``
(``ModeManager.held_off``) without touching that switch, and lets go when
the last one clears. Pure functions over the app settings and a value
getter; the state lives in ``controllers/away_facade.py``.
"""

from typing import Any, Callable, Dict, Iterable, List, Tuple

from utilities import strip_param_prefix

VRCHAT_AFK_PARAMETER = "AFK"
GOGO_AFK_PARAMETER = "VRCEmote"
GOGO_AFK_VALUE = 101

#: What the status bar and the log call each built-in source.
VRCHAT_AFK_LABEL = "AFK"
GOGO_AFK_LABEL = "GoGo Loco AFK"

SETTING_ENABLED = "away_off_enabled"
SETTING_VRCHAT = "away_off_vrchat_afk"
SETTING_GOGO = "away_off_gogo_afk"
SETTING_PARAMS = "away_off_params"

#: A new install holds everything off while you're away (decided
#: 2026-11-14), from both built-in sources; the list starts empty.
DEFAULTS: Dict[str, Any] = {
    SETTING_ENABLED: True,
    SETTING_VRCHAT: True,
    SETTING_GOGO: True,
    SETTING_PARAMS: [],
}

#: (parameter, label, test(value) -> bool)
Source = Tuple[str, str, Callable[[Any], bool]]


def is_on(value: Any) -> bool:
    """A picked parameter holds everything off while it is on: a Bool
    that is true, or a number above zero (NaN never is)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return False


def _is_gogo_afk(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and value == GOGO_AFK_VALUE)


def clean_params(raw: Any) -> List[str]:
    """The picked list as the store names parameters: bare names (no
    ``/avatar/parameters/``), no blanks, no repeats, in the order picked."""
    out: List[str] = []
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        if not isinstance(item, str):
            continue
        name = strip_param_prefix(item)
        if name and name not in out:
            out.append(name)
    return out


def compile_sources(get_setting: Callable[[str, Any], Any]) -> Tuple[Source, ...]:
    """Every source that holds Off with these settings; none while the
    card's switch is off."""
    def setting(key: str) -> Any:
        return get_setting(key, DEFAULTS[key])

    if not setting(SETTING_ENABLED):
        return ()
    sources: List[Source] = []
    if setting(SETTING_VRCHAT):
        sources.append((VRCHAT_AFK_PARAMETER, VRCHAT_AFK_LABEL, is_on))
    if setting(SETTING_GOGO):
        sources.append((GOGO_AFK_PARAMETER, GOGO_AFK_LABEL, _is_gogo_afk))
    for name in clean_params(setting(SETTING_PARAMS)):
        sources.append((name, name, is_on))
    return tuple(sources)


def watched(sources: Iterable[Source]) -> frozenset:
    """The parameter names whose change can start or end a hold -- what
    the OSC thread looks each packet's address up in."""
    return frozenset(name for name, _label, _test in sources)


def holding(sources: Iterable[Source], values: Dict[str, Any]) -> Tuple[str, ...]:
    """The labels of the sources that hold Off now, each once, in the
    sources' order. `values` maps parameter names to their current
    values (a missing one is off)."""
    out: List[str] = []
    for name, label, test in sources:
        if name in values and test(values[name]) and label not in out:
            out.append(label)
    return tuple(out)


def status_text(reasons: Iterable[str]) -> str:
    """What the status bar says while a hold is on ("AFK: everything
    off"), or "" while none is."""
    reasons = list(reasons)
    return f"{', '.join(reasons)}: everything off" if reasons else ""
