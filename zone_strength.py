"""Shared OGB zone-strength evaluation (pure functions).

Every haptic backend ultimately needs the same primitive: *given an OGB / SPS
zone, a zone type, and a set of touch/pen filters, what is the current 0..1
contact strength?* The Buttplug path has its own richer mixer, but the
bHaptics SPS-mirror and the OWO / PiShock / Coyote routers all want exactly
this — so it lives here, once, instead of being re-implemented per backend.

Two shapes of "zone" are supported transparently:

  * **OGB zones** — strength is the max value across the enabled filters at
    ``OGB/<zone_type>/<zone_name>/<filter>``, honoring the per-filter
    ``<filter>Close`` gate (a contact whose Close key is present and false is
    skipped; an absent Close key means "assume open / live").
  * **Synthetic SPS sources** — when ``zone_name`` matches a key in the
    supplied ``sps_sources`` map, that source's own evaluation
    (``sps_source.evaluate_sps_source``) is returned directly. Synthetic
    sources carry their own gating, so the filters / zone_type don't apply.

Pure functions only: no globals, no I/O, no Qt. Safe to call from any router
thread and trivially unit-testable.
"""

import math
from typing import Any, Dict, List, Optional

from sps_source import evaluate_sps_source


def truthy(value: Any) -> bool:
    """Loose truthiness used for OGB Close-gate bools and bool-ish params.
    None -> False; real bools pass through; numbers are true above 0.5;
    anything non-numeric is False (never raises)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    try:
        return float(value) > 0.5
    except (TypeError, ValueError):
        return False


def zone_filter_strength(zone_name: Any,
                         zone_type: Any,
                         filters: List[str],
                         params: Dict[str, Any],
                         sps_sources: Optional[Dict[str, Any]] = None) -> float:
    """Return the 0..1 strength of an OGB zone (or synthetic source).

    Args:
      zone_name:   the OGB zone / source name (e.g. "Booty"). Blank -> 0.0.
      zone_type:   "Orf" | "Pen" — selects the OGB address prefix. Defaults
                   to "Orf" when blank.
      filters:     filter names to OR over (e.g. ["TouchSelf", "PenOthers"]).
                   Empty -> 0.0 (unless the name resolves to a synthetic source).
      params:      a parameter_store snapshot ({bare_address: value}).
      sps_sources: optional {name: source_def} map; when ``zone_name`` is a
                   key here, the synthetic source's evaluated value is
                   returned and ``filters``/``zone_type`` are ignored.

    Pure; returns 0.0 for any malformed input rather than raising — a bad
    config or param value must never crash a router tick.
    """
    zone_name = str(zone_name or "").strip()
    if not zone_name:
        return 0.0

    # Synthetic source short-circuit (carries its own gating).
    if sps_sources:
        defn = sps_sources.get(zone_name)
        if defn is not None:
            try:
                v = float(evaluate_sps_source(defn, params))
            except (TypeError, ValueError):
                return 0.0
            if not math.isfinite(v):
                return 0.0
            return min(max(v, 0.0), 1.0)

    if not filters:
        return 0.0

    zone_type = str(zone_type or "Orf").strip() or "Orf"
    prefix = f"OGB/{zone_type}/{zone_name}"
    best = 0.0
    for fname in filters:
        # Per-filter Close gate: present-and-false blocks; absent = assume open.
        close_key = f"{prefix}/{fname}Close"
        if close_key in params and not truthy(params.get(close_key)):
            continue
        val = params.get(f"{prefix}/{fname}")
        if val is None:
            continue
        try:
            f = float(val)
        except (TypeError, ValueError):
            continue
        # NaN must not survive: min(1.0, nan) returns 1.0 in CPython, which
        # would drive an e-stim/EMS backend to FULL power off one bad packet.
        if not math.isfinite(f):
            continue
        f = min(max(f, 0.0), 1.0)
        if f > best:
            best = f
    return best
