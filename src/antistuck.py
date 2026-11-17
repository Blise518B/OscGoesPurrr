"""Anti-stuck's settings: one switch and two timers per kind of device.

VRChat only sends a contact when it changes, so a frozen sender (an avatar
swap, the other person leaving, OSC lost) would keep its last level playing.
Anti-stuck cuts a level that sits exactly still part-way for `active_s`
seconds and fades one held at the top after `peaked_s`. The rule itself
lives with each router (motor_router._antistuck_factor for the toys,
suits_router.stuck_factor for the suits, the trackers and the PSVR2); this
module only holds what is set.

Since 2026-11-17 (Blise's ask: "some of them may want different settings")
every kind has its own -- the toys (app settings' `toy_antistuck_*`, on the
Toys page), the bHaptics suit, the OWO suit, the haptic trackers (each a block
in suits_settings.json, on the Suits page) and the PSVR2 (psvr2_settings.json,
on its page) -- and each toy has its own on / off on its bar (the `antistuck`
key in its wiring, modes.json; a toy's off only counts while the toys' is on).
A kind's block that a settings file doesn't have yet starts as a copy of the
toys' values (`seed`), so an update changes nothing anyone had set.

Sealed and pure: no Qt, no I/O."""

import math
from typing import Any, Dict, Mapping

#: A fresh install's values, the same for every kind.
DEFAULTS: Dict[str, Any] = {"enabled": True, "active_s": 1, "peaked_s": 10}

#: What the timers may be set to (the spin boxes' range), in seconds.
SECONDS_MIN, SECONDS_MAX = 1, 600

#: A toy's own on / off (its bar's Anti-stuck chip): a key in its wiring
#: (modes.json), a rig fact shared by every mode. Missing = on; only False
#: switches it off, and only counts while the toys' anti-stuck is on.
TOY_KEY = "antistuck"

#: The app settings keys of the toys' block (kept from before 2026-11-17, so
#: an older OGP reading the file still finds them).
TOY_KEYS = {"enabled": "toy_antistuck_enabled",
            "active_s": "toy_antistuck_active_s",
            "peaked_s": "toy_antistuck_peaked_s"}


def _seconds(value: Any, default: int) -> int:
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(f):
        return default
    return max(SECONDS_MIN, min(SECONDS_MAX, int(round(f))))


def clean(block: Any, fallback: Mapping[str, Any] = DEFAULTS) -> Dict[str, Any]:
    """`{enabled, active_s, peaked_s}` from whatever a file holds: a missing
    or broken value takes `fallback`'s, a timer stays inside the range."""
    block = block if isinstance(block, dict) else {}
    fb = {**DEFAULTS, **(fallback or {})}
    enabled = block.get("enabled", fb["enabled"])
    return {"enabled": enabled if isinstance(enabled, bool) else bool(fb["enabled"]),
            "active_s": _seconds(block.get("active_s", fb["active_s"]),
                                 _seconds(fb["active_s"], DEFAULTS["active_s"])),
            "peaked_s": _seconds(block.get("peaked_s", fb["peaked_s"]),
                                 _seconds(fb["peaked_s"], DEFAULTS["peaked_s"]))}


def toy_on(device_config: Any) -> bool:
    """A toy's own switch, read from its wiring the way the router reads it."""
    return not (isinstance(device_config, dict) and device_config.get(TOY_KEY, True) is False)


def from_app(get: Any) -> Dict[str, Any]:
    """The toys' block from app settings (`get(key, default)`)."""
    return clean({k: get(key, DEFAULTS[k]) for k, key in TOY_KEYS.items()})


def changed(block: Mapping[str, Any], **changes: Any) -> Dict[str, Any]:
    """`block` with only the known fields of `changes` set, cleaned."""
    merged = dict(block or {})
    merged.update({k: v for k, v in changes.items() if k in DEFAULTS})
    return clean(merged, block or DEFAULTS)


def loosens(current: Any, target: Any) -> list:
    """What going from block `current` to block `target` loosens, in words
    ("switches it off", "waits longer ..."): an undo or redo that does it
    asks first (settings_history.py `history_asks`)."""
    a, b = clean(current), clean(target)
    out = []
    if a["enabled"] and not b["enabled"]:
        out.append("switches it off")
        return out
    if b["enabled"]:
        if b["active_s"] > a["active_s"]:
            out.append(f"lets a value frozen part-way play {b['active_s']} s")
        if b["peaked_s"] > a["peaked_s"]:
            out.append(f"lets a value held at 100% play {b['peaked_s']} s")
    return out
