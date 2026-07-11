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


def compute_handy_level(cfg: Dict[str, Any], strength01: float,
                        scale: float = 1.0) -> float:
    """Shape a 0..1 zone strength into the routed 0..1 level using the
    zone's threshold / gain, quantized to LEVEL_STEP. `scale` is the mode
    master scale (0..1); applied pre-quantization so attenuation keeps full
    resolution, and scale=0 guarantees 0. Pure + testable."""
    if not cfg or not cfg.get("enabled", False):
        return 0.0
    try:
        threshold = float(cfg.get("threshold", 0.0))
        gain = float(cfg.get("gain", 1.0))
    except (TypeError, ValueError):
        threshold, gain = 0.0, 1.0
    if strength01 <= threshold:
        return 0.0
    shaped = max(0.0, min(1.0, (strength01 - threshold) * gain * scale))
    return round(round(shaped / LEVEL_STEP) * LEVEL_STEP, 4)


class HandyRouter(PollingRouter):
    def __init__(self,
                 engine,
                 get_zone_config: Callable[[], Dict[str, Any]],
                 get_sps_sources: Optional[Callable[[], Dict[str, Any]]] = None,
                 poll_rate_s: float = 0.016,
                 get_master_scale: Optional[Callable[[], float]] = None,
                 get_test_level: Optional[Callable[[], float]] = None):
        super().__init__("HandyRouter", engine, poll_rate_s=poll_rate_s)
        self.get_zone_config = get_zone_config
        self.get_sps_sources = get_sps_sources or (lambda: None)
        # Mode master scale (0..1) and VR-menu test floor, both supplied by
        # ModesFacade. The test floor only applies while the zone config is
        # enabled — see compute_targets.
        self.get_master_scale = get_master_scale or (lambda: 1.0)
        self.get_test_level = get_test_level or (lambda: 0.0)

    def _engine_ready(self) -> bool:
        return self.engine.is_connected

    def compute_targets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self.get_zone_config() or {}
        try:
            sps_sources = self.get_sps_sources()
        except Exception:
            sps_sources = None
        try:
            scale = float(self.get_master_scale())
        except Exception:
            scale = 1.0
        try:
            test = float(self.get_test_level())
        except Exception:
            test = 0.0
        strength01 = zone_filter_strength(
            cfg.get("ogb_zone"), cfg.get("zone_type", "Orf"),
            cfg.get("filters") or [], params, sps_sources)
        level = compute_handy_level(cfg, strength01, scale)
        # Test floor gated on the zone being enabled: a Handy with no
        # configured zone is a physical stroking machine someone may be
        # wearing unconfigured, so the connectivity pulse must not move it.
        # Quantized to LEVEL_STEP like the routed level so debounce still
        # compares like with like.
        if test > 0.0 and cfg.get("enabled"):
            test_q = round(round(test / LEVEL_STEP) * LEVEL_STEP, 4)
            level = max(level, test_q)
        return {"_handy": level}

    def dispatch(self, key: str, value) -> None:
        self.engine.set_level(float(value))
