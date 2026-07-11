# owo_router.py
# Maps OGB zones to OWO muscle-group intensities. Each of the 10 muscles binds
# one zone (+ filters); strength → 0-100 intensity via threshold/gain. Inherits
# the ~60 Hz poll + debounce from PollingRouter, but coalesces the whole active
# set into a single debounce key — the engine wants the full muscle map (and
# owns the re-send cadence), so we push it only when the map or frequency
# actually changes.

from typing import Any, Callable, Dict, Optional

from router_base import PollingRouter
from zone_strength import zone_filter_strength


def compute_muscle_intensity(cfg: Dict[str, Any], strength01: float,
                             scale: float = 1.0) -> int:
    """Shape a 0..1 zone strength into a 0-100 OWO muscle intensity using the
    muscle's threshold / gain / max_intensity. `scale` is the mode master
    scale (0..1); applied pre-quantization so attenuation keeps full
    resolution, and scale=0 guarantees 0. Pure + testable."""
    if not cfg or not cfg.get("enabled", False):
        return 0
    try:
        threshold = float(cfg.get("threshold", 0.0))
        gain = float(cfg.get("gain", 1.0))
        max_intensity = int(cfg.get("max_intensity", 100))
    except (TypeError, ValueError):
        threshold, gain, max_intensity = 0.0, 1.0, 100
    if strength01 <= threshold:
        return 0
    shaped = max(0.0, min(1.0, (strength01 - threshold) * gain * scale))
    val = int(round(shaped * max(0, min(100, max_intensity))))
    return max(0, min(100, val))


class OwoRouter(PollingRouter):
    def __init__(self,
                 engine,
                 get_muscle_configs: Callable[[], Dict[str, Dict[str, Any]]],
                 get_frequency: Callable[[], int],
                 get_sps_sources: Optional[Callable[[], Dict[str, Any]]] = None,
                 poll_rate_s: float = 0.016,
                 get_master_scale: Optional[Callable[[], float]] = None):
        super().__init__("OwoRouter", engine, poll_rate_s=poll_rate_s)
        self.get_muscle_configs = get_muscle_configs
        self.get_frequency = get_frequency
        self.get_sps_sources = get_sps_sources or (lambda: None)
        # Mode master scale (0..1); no test-level hook here — EMS is
        # deliberately excluded from the connectivity pulse (see constants.py
        # OGP_TEST_LEVEL).
        self.get_master_scale = get_master_scale or (lambda: 1.0)

    def _engine_ready(self) -> bool:
        return self.engine.is_connected

    def compute_targets(self, params: Dict[str, Any]) -> Dict[str, Any]:
        cfgs = self.get_muscle_configs() or {}
        try:
            sps_sources = self.get_sps_sources()
        except Exception:
            sps_sources = None
        try:
            scale = float(self.get_master_scale())
        except Exception:
            scale = 1.0
        active: Dict[str, int] = {}
        for name, cfg in cfgs.items():
            if not isinstance(cfg, dict):
                continue
            strength01 = zone_filter_strength(
                cfg.get("ogb_zone"), cfg.get("zone_type", "Orf"),
                cfg.get("filters") or [], params, sps_sources)
            intensity = compute_muscle_intensity(cfg, strength01, scale)
            if intensity > 0:
                active[name] = intensity
        try:
            freq = int(self.get_frequency())
        except (TypeError, ValueError):
            freq = 100
        # One debounce key carrying the full map + frequency. frozenset compares
        # by value, so an unchanged set of muscles adds no traffic.
        return {"_owo": (frozenset(active.items()), freq)}

    def dispatch(self, key: str, value) -> None:
        active_items, freq = value
        self.engine.set_active(dict(active_items), freq)
