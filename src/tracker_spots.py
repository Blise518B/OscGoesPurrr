# tracker_spots.py
# Where a haptic tracker can sit on the body, which avatar parameter each
# spot listens to by default, and how SteamVR's own tracker roles map onto
# the spots. Pure -- no OpenVR, no threads -- so it's testable on its own.
#
# The spots and their parameters are Haptic Pancake's (Blise's call,
# 2026-11-07): its guide tells people to name their avatar's contact
# receivers HapticHead, HapticChest, HapticHips, HapticElbowLeft, ... so an
# avatar set up for Pancake works here with no setup. Only the names are
# shared -- a naming convention, no code from that project.
#
# A tracker's spot comes from the role it has in SteamVR's Manage Trackers
# (saved in steamvr.vrsettings, section "trackers") unless the user placed
# it by hand on the Suits page.

import json
import os
import sys
from typing import Dict, Iterable, Optional, Tuple

# (key, name, default avatar parameter, SteamVR roles that put a tracker here)
SPOTS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("head", "Head", "HapticHead", ()),
    ("chest", "Chest", "HapticChest", ("TrackerRole_Chest",)),
    ("hips", "Hips", "HapticHips", ("TrackerRole_Waist",)),
    ("elbow_r", "Right elbow", "HapticElbowRight", ("TrackerRole_RightElbow",)),
    ("elbow_l", "Left elbow", "HapticElbowLeft", ("TrackerRole_LeftElbow",)),
    ("knee_r", "Right knee", "HapticKneeRight", ("TrackerRole_RightKnee",)),
    ("knee_l", "Left knee", "HapticKneeLeft", ("TrackerRole_LeftKnee",)),
    ("foot_r", "Right foot", "HapticFootRight",
     ("TrackerRole_RightFoot", "TrackerRole_RightAnkle")),
    ("foot_l", "Left foot", "HapticFootLeft",
     ("TrackerRole_LeftFoot", "TrackerRole_LeftAnkle")),
)
SPOT_KEYS: Tuple[str, ...] = tuple(k for k, _n, _p, _r in SPOTS)
SPOT_NAMES: Dict[str, str] = {k: n for k, n, _p, _r in SPOTS}
DEFAULT_PARAM: Dict[str, str] = {k: p for k, _n, p, _r in SPOTS}
_SPOT_OF_ROLE: Dict[str, str] = {role: k for k, _n, _p, roles in SPOTS for role in roles}

# SteamVR keeps a role for OGP's own toy devices too (the full edition's
# driver once made them trackers); they're never haptic trackers.
_OWN_DRIVER_PREFIX = "/devices/oscgoespurrr/"

MAX_PARAMS = 8          # avatar parameters one spot may follow
MAX_PARAM_LEN = 128


def spot_for_role(role: str) -> Optional[str]:
    """'TrackerRole_LeftFoot' (or 'TrackerRole_Handed,...') -> 'foot_l';
    a role no spot takes (None, Handed, Camera, Shoulder, Wrist ...) -> None."""
    first = str(role or "").split(",")[0].strip()
    return _SPOT_OF_ROLE.get(first)


def roles_from_settings(text: str) -> Dict[str, str]:
    """steamvr.vrsettings' text -> {device path: role}, OGP's own devices
    left out. Anything unreadable -> {}."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    section = data.get("trackers") if isinstance(data, dict) else None
    if not isinstance(section, dict):
        return {}
    return {str(path): str(role) for path, role in section.items()
            if isinstance(role, str) and not str(path).startswith(_OWN_DRIVER_PREFIX)}


def role_of(serial: str, roles: Dict[str, str]) -> str:
    """The role saved for a tracker: SteamVR keys it by a device path that
    ends in the serial ('/devices/htc/vive_trackerLHR-...',
    '/devices/lighthouse/LHR-...'). '' when it has none."""
    if not serial:
        return ""
    for path, role in roles.items():
        if path.endswith(serial):
            return role
    return ""


def clean_params(value, spot: str) -> list:
    """The avatar parameters a spot follows: bare names (a pasted
    /avatar/parameters/ is dropped), no blanks or repeats, at most
    MAX_PARAMS. Not a list -> the spot's default."""
    if not isinstance(value, (list, tuple)):
        return [DEFAULT_PARAM[spot]] if spot in DEFAULT_PARAM else []
    out = []
    for item in value:
        name = str(item or "").strip()
        if name.startswith("/avatar/parameters/"):
            name = name[len("/avatar/parameters/"):]
        name = name.strip().strip("/")[:MAX_PARAM_LEN]
        if name and name not in out:
            out.append(name)
        if len(out) >= MAX_PARAMS:
            break
    return out


def split_params(text: str) -> list:
    """What the page's field holds ("HapticChest, ChestExtra") -> names."""
    return [p for p in (s.strip() for s in str(text or "").replace(";", ",").split(","))
            if p]


def steamvr_settings_paths() -> Iterable[str]:
    """Where steamvr.vrsettings may be, most likely first."""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                steam = winreg.QueryValueEx(k, "SteamPath")[0]
            if steam:
                yield os.path.join(steam, "config", "steamvr.vrsettings")
        except OSError:
            pass
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
            if base:
                yield os.path.join(base, "Steam", "config", "steamvr.vrsettings")
    else:
        home = os.path.expanduser("~")
        for rel in (".steam/steam", ".local/share/Steam", ".var/app/com.valvesoftware.Steam/data/Steam"):
            yield os.path.join(home, rel, "config", "steamvr.vrsettings")
