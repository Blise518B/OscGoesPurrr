"""Synthetic SPS source evaluation (pure functions).

A *synthetic SPS source* is a user-defined virtual contact zone assembled
from raw VRChat contact-receiver parameters. Unlike OGB / SPS zones — which
`parameter_store` auto-detects from `OGB/...` parameter names — a synthetic
source is wired by hand from arbitrary contact params so the user can build
a "very specific spot" that the avatar doesn't expose as an OGB zone:

  * proximity  — one or more proximity receivers (float 0..1). Combined
                 max-wins (the loudest receiver wins).
  * activation — binary gate contacts that say "the penetrator is in this
                 specific spot". OR semantics: the proximity is only used
                 while at least one activation contact reads true. An empty
                 activation list means "no gate" (always pass) so a source
                 degrades cleanly to a plain capped proximity.
  * velocity   — binary on-enter contacts representing a thrust / speed
                 boost. A single shared `multiplier` is applied to the
                 output while ANY velocity contact reads true.
  * max_value  — ceiling clamp on the raw (post-combine, pre-multiply)
                 proximity, so a single source can't push past a chosen
                 level before the multiplier kicks in.

The result is a single 0..1 value the routers treat exactly like an OGB
zone contribution, so a synthetic source is selectable anywhere an SPS
zone is (the Device Routing per-motor picker and the bHaptics
Cross-Routing picker).

Pure functions only — `evaluate_sps_source` takes a definition dict and a
parameter snapshot and returns a primitive float. No I/O, no globals, no
Qt; trivially unit-testable and safe to call from any router thread.

Definition schema (persisted by SpsSourceManager in sps_sources.json):

    {
      "name": "G-Spot",
      "zone_type": "Orf",          # "Orf" | "Pen" — picker grouping only
      "proximity":  ["Contact/GSpotProx"],
      "activation": ["Contact/GSpotZone"],
      "velocity":   ["Contact/GSpotThrust"],
      "multiplier": 2.0,
      "max_value":  0.8,
      "enabled":    true
    }
"""

from typing import Any, Dict, List, Optional

from utilities import normalize_osc_value, strip_param_prefix

ZONE_TYPES = ("Orf", "Pen")
DEFAULT_MULTIPLIER = 1.0
DEFAULT_MAX_VALUE = 1.0


# ----------------------------------------------------------
# tiny param readers (mirror motor_router's _get_param/_get_bool so the
# evaluator stays self-contained and pure)
# ----------------------------------------------------------

def _get_bool(params: Dict[str, Any], name: str) -> bool:
    v = params.get(name)
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    try:
        return float(v) > 0.5
    except (TypeError, ValueError):
        return bool(v)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_unit(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _clean_contacts(value: Any) -> List[str]:
    """Normalise a contact-name field into a de-duped list of bare
    parameter names. Accepts a single string or a list; strips the
    `/avatar/parameters/` prefix so the stored form matches the
    parameter_store keys (same convention as custom OSC addresses)."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = strip_param_prefix(item)
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


# ----------------------------------------------------------
# evaluation
# ----------------------------------------------------------

def evaluate_sps_source(defn: Dict[str, Any], params: Dict[str, Any]) -> float:
    """Compute a synthetic source's 0..1 value from a parameter snapshot.

    Pipeline (see module docstring for the rationale of each step):
      1. Activation gate (OR). If activation contacts are configured and
         none read true, the source emits 0. No activation contacts =
         no gate.
      2. Proximity (max-wins) across the configured receivers. If no
         proximity contact is present in `params`, the source emits 0.
      3. Clamp the raw proximity to `max_value`.
      4. Shared velocity multiplier — while ANY velocity contact reads
         true, multiply by `multiplier` (negative multipliers floor at 0).
      5. Final clamp to [0, 1].

    Returns 0.0 for a malformed `defn` rather than raising — a bad
    on-disk record must never crash a router tick."""
    if not isinstance(defn, dict):
        return 0.0

    # 1. Activation gate (OR). Empty list => no gate.
    activation = defn.get("activation") or []
    if activation and not any(_get_bool(params, p) for p in activation if p):
        return 0.0

    # 2. Proximity, max-wins. A source with no readable proximity is silent.
    prox = 0.0
    seen = False
    for name in (defn.get("proximity") or []):
        if not name:
            continue
        raw = params.get(name)
        if raw is None:
            continue
        seen = True
        # RAW value in: normalize_osc_value needs the original type to give
        # int byte params (0-255) their rescale — a float() pre-cast would
        # saturate them to 1.0. It also absorbs garbage/non-finite as 0.0.
        nv = normalize_osc_value(raw)
        if nv > prox:
            prox = nv
    if not seen:
        return 0.0

    # 3. Clamp the raw proximity to the configured ceiling.
    max_value = _clamp_unit(_coerce_float(defn.get("max_value", DEFAULT_MAX_VALUE),
                                          DEFAULT_MAX_VALUE))
    if prox > max_value:
        prox = max_value

    # 4. Shared velocity multiplier — any firing contact applies it.
    velocity = defn.get("velocity") or []
    if velocity and any(_get_bool(params, p) for p in velocity if p):
        mult = _coerce_float(defn.get("multiplier", DEFAULT_MULTIPLIER),
                             DEFAULT_MULTIPLIER)
        if mult < 0.0:
            mult = 0.0
        prox *= mult

    # 5. Haptic outputs live in [0, 1]; the multiplier can overshoot.
    return _clamp_unit(prox)


def normalize_source_def(defn: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a raw / user-supplied dict into a clean, persistable source
    record: trimmed name, validated zone_type, prefix-stripped contact
    lists, clamped numerics. Garbage fields fall back to safe defaults.
    Shared by SpsSourceManager and the UI so persisted records always
    have a consistent shape."""
    src = defn if isinstance(defn, dict) else {}
    zone_type = str(src.get("zone_type", "Orf")).strip()
    if zone_type not in ZONE_TYPES:
        zone_type = "Orf"
    multiplier = _coerce_float(src.get("multiplier", DEFAULT_MULTIPLIER),
                               DEFAULT_MULTIPLIER)
    return {
        "name": str(src.get("name", "")).strip(),
        "zone_type": zone_type,
        "proximity": _clean_contacts(src.get("proximity")),
        "activation": _clean_contacts(src.get("activation")),
        "velocity": _clean_contacts(src.get("velocity")),
        "multiplier": multiplier if multiplier >= 0.0 else 0.0,
        "max_value": _clamp_unit(_coerce_float(src.get("max_value", DEFAULT_MAX_VALUE),
                                               DEFAULT_MAX_VALUE)),
        "enabled": bool(src.get("enabled", True)),
    }
