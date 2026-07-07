# handy_router.py
# Maps one OGB zone onto The Handy's single output level. The device is a
# single-feature stroker, so unlike OWO's 10 muscles there is exactly one
# routed value: zone strength → threshold/gain shaping → 0-1 level. The
# engine decides what that level means (HAMP velocity or HDSP position) —
# the router stays a pure calculator. Inherits the ~60 Hz poll + debounce
# from PollingRouter; the shaped level is quantized so a noisy analog
# contact doesn't spam the engine's (cloud-rate-capped) send loop.

from typing import Any, Callable, Dict, Optional

from router_base import PollingRouter
from zone_strength import zone_filter_strength

# Debounce granularity for the routed level: 50 steps is below what the
# stroker can express but well above the engine's own quantization, so the
# router never starves the engine of a perceptible change.
LEVEL_STEP = 0.02


def compute_handy_level(cfg: Dict[str, Any], strength01: float) -> float:
    """Shape a 0..1 zone strength into the routed 0..1 level using the
    zone's threshold / gain, quantized to LEVEL_STEP. Pure + testable."""
    if not cfg or not cfg.get("enabled", False):
        return 0.0
    try:
        threshold = float(cfg.get("threshold", 0.0))
        gain = float(cfg.get("gain", 1.0))
    except (TypeError, ValueError):
        threshold, gain = 0.0, 1.0
    if strength01 <= threshold:
        return 0.0
    shaped = max(0.0, min(1.0, (strength01 - threshold) * gain))
    return round(round(shaped / LEVEL_STEP) * LEVEL_STEP, 4)


class HandyRouter(PollingRouter):
    def __init__(self,
                 engine,
                 get_zone_config: Callable[[], Dict[str, Any]],
                 get_sps_sources: Optional[Callable[[], Dict[str, Any]]] = None,
                 poll_rate_s: float = 0.016):
        super().__init__("HandyRouter", engine, poll_rate_s=poll_rate_s)
        self.get_zone_config = get_zone_config
        self.get_sps_sources = get_sps_sources or (lambda: None)

    def _engine_ready(self) -> bool:
        return self.engine.is_connected

    def compute_targets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.get_zone_config() or {}
        try:
            sps_sources = self.get_sps_sources()
        except Exception:
            sps_sources = None
        strength01 = zone_filter_strength(
            cfg.get("ogb_zone"), cfg.get("zone_type", "Orf"),
            cfg.get("filters") or [], params, sps_sources)
        return {"_handy": compute_handy_level(cfg, strength01)}

    def dispatch(self, key: str, value) -> None:
        self.engine.set_level(float(value))
