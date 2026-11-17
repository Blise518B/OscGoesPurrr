"""Which contact a chain hears: Touch / Penetration x Self / Others.

Four switches per chain (friends' reviews, 2026-11-14): touch from
yourself, touch from others, penetration from yourself, penetration from
others. They replace two independent pairs -- Touch / Penetration and Self
/ Others -- which could not say "touch from myself, but penetration only
from others".

Keys, per mode like every routing key: `motor_<m>_c<k>_<pair>` for a
chain, falling back to the motor's `motor_<m>_<pair>`, then to `DEFAULTS`
-- the same resolution as `MotorRouter._chain_routing_value`.

A typed chain hears only its own kind: a Touch chain answers the two touch
pairs, a Penetration chain the two penetration pairs, a custom chain all
four. The other kind's switches are still stored (they take over if the
chain's type changes), they just play no part.

`migrate_routing` turns the old pairs into the 2x2 once, at load, without
changing what any chain hears: touch-self = touch AND self, and so on, so
the router reads only the four keys and does no more per tick than before.

Pure: no Qt, no I/O -- used by config_manager, motor_router and the UI.
"""

import re
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Tuple

TOUCH_SELF = "touch_self"
TOUCH_OTHERS = "touch_others"
PEN_SELF = "pen_self"
PEN_OTHERS = "pen_others"

#: The four, in the order the UI shows them.
PAIRS: Tuple[str, ...] = (TOUCH_SELF, TOUCH_OTHERS, PEN_SELF, PEN_OTHERS)

#: What a chain nobody has set hears: everyone else's touch and
#: penetration, never your own -- the old Self off / Others on, Touch and
#: Penetration both on.
DEFAULTS: Dict[str, bool] = {
    TOUCH_SELF: False, TOUCH_OTHERS: True,
    PEN_SELF: False, PEN_OTHERS: True,
}

KIND_TOUCH = "touch"
KIND_PENETRATION = "penetration"

#: The two pairs of each kind of contact.
KIND_PAIRS: Dict[str, Tuple[str, str]] = {
    KIND_TOUCH: (TOUCH_SELF, TOUCH_OTHERS),
    KIND_PENETRATION: (PEN_SELF, PEN_OTHERS),
}
PAIR_KIND: Dict[str, str] = {p: k for k, ps in KIND_PAIRS.items() for p in ps}

# The old two pairs, and what each meant when absent.
_LEGACY_DEFAULTS: Dict[str, bool] = {
    "touch": True, "pen": True, "self": False, "others": True,
}
_LEGACY_KEY = re.compile(r"^motor_(\d+)(?:_c(\d+))?_(touch|pen|self|others)$")
_MISSING = object()


def kinds_for_type(chain_type: Any) -> Tuple[str, ...]:
    """The kinds of contact a chain of this type hears. Anything that is not
    a known type reads as custom (both), as in the router."""
    t = str(chain_type or "")
    if t == KIND_TOUCH:
        return (KIND_TOUCH,)
    if t == KIND_PENETRATION:
        return (KIND_PENETRATION,)
    return (KIND_TOUCH, KIND_PENETRATION)


def pairs_for_type(chain_type: Any) -> Tuple[str, ...]:
    """The pairs a chain of this type answers, in `PAIRS` order."""
    kinds = kinds_for_type(chain_type)
    return tuple(p for p in PAIRS if PAIR_KIND[p] in kinds)


def key(motor_idx: int, chain_idx: Optional[int], pair: str) -> str:
    """The routing key a pair is stored under: per chain, or the motor's
    fallback when `chain_idx` is None."""
    if chain_idx is None:
        return f"motor_{int(motor_idx)}_{pair}"
    return f"motor_{int(motor_idx)}_c{int(chain_idx)}_{pair}"


def resolve(get: Callable[[str, Any], Any], motor_idx: int,
            chain_idx: Optional[int], pair: str) -> bool:
    """One pair as a chain runs it: its own key, else the motor's, else the
    default. `get(key, missing)` returns `missing` for an absent key."""
    missing = _MISSING
    if chain_idx is not None:
        v = get(key(motor_idx, chain_idx, pair), missing)
        if v is not missing:
            return bool(v)
    v = get(key(motor_idx, None, pair), missing)
    if v is not missing:
        return bool(v)
    return DEFAULTS[pair]


def pairs_from_legacy(touch: Any, pen: Any, self_: Any,
                      others: Any) -> Dict[str, bool]:
    """The 2x2 the old two pairs meant: a pair is on when both its kind and
    its source were."""
    t, p, s, o = bool(touch), bool(pen), bool(self_), bool(others)
    return {TOUCH_SELF: t and s, TOUCH_OTHERS: t and o,
            PEN_SELF: p and s, PEN_OTHERS: p and o}


def _has_pairs(per_dev: Mapping[str, Any], motor_idx: int,
               chain_idx: Optional[int]) -> bool:
    return any(key(motor_idx, chain_idx, p) in per_dev for p in PAIRS)


def migrate_routing(per_dev: Dict[str, Any],
                    chain_types: Optional[Mapping[int, Sequence[Any]]] = None
                    ) -> bool:
    """Turn one device's routing block from the old Touch / Penetration and
    Self / Others pairs into the 2x2, in place. Returns True when anything
    changed. Idempotent: a block with no old keys is left alone.

    `chain_types` is `{motor_idx: [type of chain 0, chain 1, ...]}` from the
    shared feel, so every chain keeps hearing exactly what it heard:

    * The motor's own old keys become the motor's 2x2 (products, absent =
      the old default), still the fallback for any chain without keys.
    * Each chain resolves its old values the old way (its key, the motor's,
      the default) and gets its own 2x2 when that differs from what it would
      fall back to.
    * A typed chain used to take its own kind from its type and ignore the
      stored switch, so its own kind counts as on: a Touch chain whose
      Touch switch was stored off kept hearing touch, and still does.

    A scope (the motor, or one chain) that already holds 2x2 keys keeps
    them; its old keys are dropped either way."""
    if not isinstance(per_dev, dict):
        return False
    old: Dict[Tuple[int, Optional[int]], Dict[str, Any]] = {}
    old_keys = []
    for k in per_dev:
        m = _LEGACY_KEY.match(k) if isinstance(k, str) else None
        if m is None:
            continue
        scope = (int(m.group(1)),
                 None if m.group(2) is None else int(m.group(2)))
        old.setdefault(scope, {})[m.group(3)] = per_dev[k]
        old_keys.append(k)
    if not old_keys:
        return False
    chain_types = chain_types or {}
    for motor in sorted({mi for mi, _ci in old}):
        motor_old = old.get((motor, None), {})
        if motor_old and not _has_pairs(per_dev, motor, None):
            eff = {s: motor_old.get(s, d) for s, d in _LEGACY_DEFAULTS.items()}
            for pair, v in pairs_from_legacy(
                    eff["touch"], eff["pen"], eff["self"], eff["others"]).items():
                per_dev[key(motor, None, pair)] = v
        types = list(chain_types.get(motor, ()) or ())
        chains = set(range(len(types)))
        chains.update(ci for mi, ci in old if mi == motor and ci is not None)
        fallback = {p: bool(per_dev.get(key(motor, None, p), DEFAULTS[p]))
                    for p in PAIRS}
        for chain in sorted(chains):
            if _has_pairs(per_dev, motor, chain):
                continue
            chain_old = old.get((motor, chain), {})
            eff = {}
            for s, d in _LEGACY_DEFAULTS.items():
                if s in chain_old:
                    eff[s] = chain_old[s]
                elif s in motor_old:
                    eff[s] = motor_old[s]
                else:
                    eff[s] = d
            ctype = types[chain] if chain < len(types) else ""
            kinds = kinds_for_type(ctype)
            if len(kinds) == 1:
                eff["touch" if kinds[0] == KIND_TOUCH else "pen"] = True
            pairs = pairs_from_legacy(
                eff["touch"], eff["pen"], eff["self"], eff["others"])
            if pairs != fallback:
                for pair, v in pairs.items():
                    per_dev[key(motor, chain, pair)] = v
    for k in old_keys:
        del per_dev[k]
    return True


def chain_types_from_feel(per_device_feel: Any) -> Dict[int, list]:
    """`{motor_idx: [chain types]}` out of one device's shared feel
    (`{motor_idx_str: {"chains": [...]}}`), for `migrate_routing`."""
    out: Dict[int, list] = {}
    if not isinstance(per_device_feel, dict):
        return out
    for motor_str, mix in per_device_feel.items():
        try:
            motor = int(motor_str)
        except (TypeError, ValueError):
            continue
        chains = mix.get("chains") if isinstance(mix, dict) else None
        if isinstance(chains, list):
            out[motor] = [c.get("type", "") if isinstance(c, dict) else ""
                          for c in chains]
    return out


def chip_state(values: Iterable[bool]) -> Optional[str]:
    """One Home chip from the chains that answer it: "on" when every one
    has the pair on, "off" when none does, "half" while they disagree, and
    None when no chain answers it (a touch-only toy's penetration chips)."""
    seen_on = seen_off = False
    for v in values:
        if v:
            seen_on = True
        else:
            seen_off = True
    if not (seen_on or seen_off):
        return None
    if seen_on and seen_off:
        return "half"
    return "on" if seen_on else "off"
