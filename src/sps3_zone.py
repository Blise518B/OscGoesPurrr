"""SPS 3 zones: VRCFury's sockets and plugs since 1.1443.0 (Nov 2026).

VRCFury renamed its haptic zones -- a socket is now ``OGB/Socket/<id>/...``
and a plug ``OGB/Plug/<id>/...`` (they were ``OGB/Orf`` and ``OGB/Pen``) --
and measures depth with the extra values VRChat's contact receivers can
report. parameter_store renames the two categories on ingest (Socket -> Orf,
Plug -> Pen, see ``canon_zone_key``), so every zone list, picker and saved
selection keeps working; what differs is the contacts inside a zone, and
this module reads them.

An SPS 3 zone carries:

* ``TouchSelf`` / ``TouchOthers`` (and a plug's ``FrotOthers``): proximity
  with no ``...Close`` gate, plus ``<contact>_SenderVelocityMagnitude`` --
  how fast the touching hand (or plug) moves, in metres per second. Touch
  zones (``OGB/Touch/<id>/Self|Others``) carry the speed too.
* ``DepthSelf`` / ``DepthOthers``: the depth receiver, with
  ``<contact>_PointSeparation`` -- metres between the receiver's point and
  the other side's base. Depth = 1 - separation / plug length: 0 with the
  tip at the entrance, 1 all the way in.
* the plug length. A plug knows its own (``LengthMult1 x LengthMult2``). A
  socket reads the entering plug's: an SPS 3 plug states it in
  ``<contact>_SenderLossyScaleZ`` and marks itself with a true
  ``<contact>_CollisionTag_SPS/Plug/...``; an older plug says it only
  through the size of the sphere around its base, which the socket measures
  while the plug approaches and keeps while it is inside (that needs
  memory, so parameter_store does it on every packet -- ``SocketPlugLengths``
  -- and writes the result as ``<contact>_PlugLength``).
* ``DepthRadius`` (a socket's depth-receiver radius). Avatar-wide, VRCFury
  adds ``OGB/Enabled`` -- the touch receivers stay off until an app sets it
  true, which vrchat_osc's heartbeat does -- and ``OGB/HapticsDisabled``
  when the avatar was built with VRCFury's haptics switched off.

Written from VRCFury's parameter names and what they measure. OscGoesBrrr
reads the same names, but its code is GPL-3 since v2.1.34: nothing here is
taken from it.

Pure functions plus one small stateful helper; no Qt, no I/O.
"""

import math
from typing import Any, Dict, List, Optional, Set, Tuple

#: Wire categories VRCFury uses since SPS 3 -> the zone types OGP keeps.
ZONE_RENAMES = {"Socket": "Orf", "Plug": "Pen"}

#: Contacts only an SPS 3 zone has -- one of them present marks the zone.
#: DepthRadius / LengthMult2 are expression parameters with a default, so
#: OSCQuery lists them from the moment the avatar loads.
SPS3_CONTACTS = ("DepthRadius", "LengthMult2", "DepthSelf", "DepthOthers",
                 "LengthMult1")
DEPTH_CONTACTS = ("DepthSelf", "DepthOthers")

SPEED_SUFFIX = "_SenderVelocityMagnitude"
LENGTH_SUFFIX = "_PlugLength"
_SEPARATION = "_PointSeparation"
_SCALE_Z = "_SenderLossyScaleZ"
_NATIVE_TAG = "_CollisionTag_SPS/Plug/"

#: A hand moving this fast (m/s) is full speed. Same as OscGoesBrrr, so the
#: two apps feel alike; the chain's Speed gain and curve shape it from here.
SPEED_FULL_MPS = 1.0

#: An older plug's length is read off geometry; anything longer than this
#: is a misreading, not a plug.
MAX_PLUG_LENGTH_M = 3.0

#: True on an avatar built with VRCFury's Tools > VRCFury > Settings >
#: Enable SPS Haptics switched off: it has plugs and sockets but no contacts.
HAPTICS_DISABLED_PARAM = "OGB/HapticsDisabled"


def haptics_disabled(value: Any) -> bool:
    """Whether an ``OGB/HapticsDisabled`` value says haptics are off."""
    if value is True:
        return True
    f = _num(value)
    return f is not None and f > 0.5


def canon_zone_key(key: str) -> str:
    """``OGB/Socket/...`` -> ``OGB/Orf/...``, ``OGB/Plug/...`` ->
    ``OGB/Pen/...``; anything else unchanged."""
    if key.startswith("OGB/"):
        cut = key.find("/", 4)
        if cut > 4:
            renamed = ZONE_RENAMES.get(key[4:cut])
            if renamed is not None:
                return "OGB/" + renamed + key[cut:]
    return key


def _num(value: Any) -> Optional[float]:
    """A finite number, or None. Bools are not numbers here."""
    if value is None or isinstance(value, bool):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _unit(value: Any) -> float:
    f = _num(value)
    if f is None:
        return 1.0 if value is True else 0.0
    return min(max(f, 0.0), 1.0)


def is_sps3_zone(params: Dict[str, Any], prefix: str) -> bool:
    """Whether the zone at ``prefix`` (``OGB/<Orf|Pen>/<id>``) is SPS 3."""
    for contact in SPS3_CONTACTS:
        if f"{prefix}/{contact}" in params:
            return True
    return False


def depth(params: Dict[str, Any], prefix: str, zone_type: str,
          contact: str) -> float:
    """0..1 depth from an SPS 3 zone's ``DepthSelf`` / ``DepthOthers``.
    0 while nothing is in, or while the plug's length is still unknown."""
    prox = _num(params.get(f"{prefix}/{contact}"))
    sep = _num(params.get(f"{prefix}/{contact}{_SEPARATION}"))
    if prox is None or prox <= 0.0 or sep is None or sep < 0.0:
        return 0.0
    if zone_type == "Pen":
        a = _num(params.get(f"{prefix}/LengthMult1")) or 0.0
        b = _num(params.get(f"{prefix}/LengthMult2")) or 0.0
        length = a * b
    else:
        length = _num(params.get(f"{prefix}/{contact}{LENGTH_SUFFIX}")) or 0.0
    if not (length > 0.0) or not math.isfinite(length):
        return 0.0
    return min(max(1.0 - sep / length, 0.0), 1.0)


def touch_level(params: Dict[str, Any], key: str) -> float:
    """A touch contact's proximity, 0..1 (no Close gate in SPS 3)."""
    return _unit(params.get(key))


def touch_speed(params: Dict[str, Any], key: str) -> float:
    """How fast the sender touching ``key`` moves, 0..1 (SPEED_FULL_MPS is
    1). 0 when the contact reports no speed (older avatars) or nothing is
    in range -- VRChat's last speed lingers after a touch ends."""
    speed = _num(params.get(key + SPEED_SUFFIX))
    if speed is None or speed <= 0.0:
        return 0.0
    if not ((_num(params.get(key)) or 0.0) > 0.0):
        return 0.0
    return min(speed / SPEED_FULL_MPS, 1.0)


def _tag_on(value: Any) -> bool:
    if value is True:
        return True
    f = _num(value)
    return f is not None and f > 0.0


class SocketPlugLengths:
    """The length of the plug in each SPS 3 socket, kept up to date from
    every packet by parameter_store (under its lock).

    An SPS 3 plug states its length; an older plug's has to be measured:
    its base carries a sphere as big as the plug, so while it approaches,
    the socket's depth receiver reads ``separation - radius x (1 -
    proximity)`` = the sphere's radius = the plug's length. Once the tip is
    in, the proximity sits at 1 and the reading only gives a lower bound
    (the separation itself), so the lengths measured on the way in are kept
    until the plug leaves.

    VRChat sends the separation and the proximity as two messages, and a
    reading taken between them pairs one frame's separation with the
    previous frame's proximity -- at the entrance, a length well off the
    truth. So a reading is only taken once BOTH have arrived since the last
    one, within SAME_BURST_S of each other (one frame's messages arrive
    together; a frame that changes only one of them leaves the other's
    arrival old, and that half is dropped instead of paired). Whatever
    still slips through is outvoted: the last WINDOW readings are kept and
    the length is the one the two closest readings agree on (as the root /
    tip length detector in motor_router does)."""

    WINDOW = 8
    SAME_BURST_S = 0.005

    def __init__(self) -> None:
        # (zone prefix, contact) -> lengths measured on the way in, newest first
        self._readings: Dict[Tuple[str, str], List[float]] = {}
        # (zone prefix, contact) -> the best lower bound while pinned at 1
        self._floor: Dict[Tuple[str, str], float] = {}
        # (zone prefix, contact) -> {"p" proximity / "s" separation: arrival
        # time} for what arrived since the last reading
        self._fresh: Dict[Tuple[str, str], Dict[str, float]] = {}
        # (zone prefix, contact) -> the tag keys that currently read true
        self._native: Dict[Tuple[str, str], Set[str]] = {}

    def clear(self) -> None:
        self._readings.clear()
        self._floor.clear()
        self._fresh.clear()
        self._native.clear()

    def _forget(self, slot: Tuple[str, str]) -> None:
        self._readings.pop(slot, None)
        self._floor.pop(slot, None)

    @staticmethod
    def _split(key: str) -> Optional[Tuple[str, str]]:
        if not key.startswith("OGB/Orf/"):
            return None
        parts = key.split("/", 3)
        if len(parts) < 4 or not parts[2]:
            return None
        return "OGB/Orf/" + parts[2], parts[3]

    def on_write(self, key: str, value: Any, params: Dict[str, Any],
                 now: float) -> List[Tuple[str, float]]:
        """The ``<contact>_PlugLength`` writes that ``key`` changing to
        ``value`` (already in ``params``) at ``now`` (monotonic seconds)
        calls for. O(1); a key that is no socket's depth input returns []
        after a prefix check."""
        split = self._split(key)
        if split is None:
            return []
        prefix, rest = split
        part = None
        if rest == "DepthRadius":
            contacts: Tuple[str, ...] = DEPTH_CONTACTS
        else:
            contacts = ()
            for contact in DEPTH_CONTACTS:
                if rest == contact or (rest.startswith(contact + "_")
                                       and not rest.endswith(LENGTH_SUFFIX)):
                    contacts = (contact,)
                    break
            if not contacts:
                return []
            if rest == contacts[0]:
                part = "p"
            elif rest == contacts[0] + _SEPARATION:
                part = "s"
            else:
                tag_at = rest.find(_NATIVE_TAG)
                if tag_at > 0:
                    tags = self._native.setdefault((prefix, contacts[0]), set())
                    if _tag_on(value):
                        tags.add(rest)
                    else:
                        tags.discard(rest)
        return self._writes(params, prefix, contacts, part, now)

    def refresh_all(self, params: Dict[str, Any]) -> List[Tuple[str, float]]:
        """Start over from a whole parameter table (an OSCQuery snapshot:
        one moment, so every reading in it is a whole one)."""
        self.clear()
        slots = set()
        for key, value in params.items():
            split = self._split(key)
            if split is None:
                continue
            prefix, rest = split
            tag_at = rest.find(_NATIVE_TAG)
            if tag_at > 0 and _tag_on(value):
                self._native.setdefault((prefix, rest[:tag_at]),
                                        set()).add(rest)
            if rest in DEPTH_CONTACTS:
                slots.add((prefix, rest))
        out: List[Tuple[str, float]] = []
        for prefix, contact in sorted(slots):
            out.extend(self._writes(params, prefix, (contact,), "both", 0.0))
        return out

    def _writes(self, params: Dict[str, Any], prefix: str,
                contacts: Tuple[str, ...], part: Optional[str],
                now: float) -> List[Tuple[str, float]]:
        out: List[Tuple[str, float]] = []
        for contact in contacts:
            length = self._length(params, prefix, contact, part, now)
            value_out = length if length is not None else 0.0
            dkey = f"{prefix}/{contact}{LENGTH_SUFFIX}"
            if params.get(dkey) != value_out:
                out.append((dkey, value_out))
        return out

    def _length(self, params: Dict[str, Any], prefix: str, contact: str,
                part: Optional[str], now: float) -> Optional[float]:
        slot = (prefix, contact)
        whole = part == "both"
        if part in ("p", "s"):
            fresh = self._fresh.setdefault(slot, {})
            fresh[part] = now
            other = "s" if part == "p" else "p"
            arrived = fresh.get(other)
            if arrived is not None:
                if now - arrived <= self.SAME_BURST_S:
                    fresh.clear()
                    whole = True
                else:
                    del fresh[other]          # an earlier frame's half
        prox = _num(params.get(f"{prefix}/{contact}"))
        sep = _num(params.get(f"{prefix}/{contact}{_SEPARATION}"))
        if prox is None or prox <= 0.0 or sep is None or sep < 0.0:
            self._forget(slot)                # nothing in range
            return None
        if self._native.get(slot):
            self._forget(slot)
            stated = _num(params.get(f"{prefix}/{contact}{_SCALE_Z}"))
            return stated if stated is not None and stated > 0.0 else None
        if whole:
            if prox < 1.0:
                radius = _num(params.get(f"{prefix}/DepthRadius"))
                if radius is not None and radius > 0.0:
                    measured = sep - radius * (1.0 - prox)
                    if 0.0 < measured <= MAX_PLUG_LENGTH_M:
                        readings = self._readings.setdefault(slot, [])
                        readings.insert(0, measured)
                        del readings[self.WINDOW:]
            elif 0.0 < sep <= MAX_PLUG_LENGTH_M:
                self._floor[slot] = max(self._floor.get(slot, 0.0), sep)
        return self._best(slot)

    def _best(self, slot: Tuple[str, str]) -> Optional[float]:
        readings = self._readings.get(slot)
        if not readings:
            return self._floor.get(slot)
        if len(readings) == 1:
            return readings[0]
        ordered = sorted(readings)
        closest = min(range(1, len(ordered)),
                      key=lambda i: ordered[i] - ordered[i - 1])
        return ordered[closest]
