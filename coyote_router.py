# coyote_router.py
# Continuous-level router for the Coyote A/B channels. Each channel maps one
# OGB zone (+ filters) to a 0-200 strength via the shared zone_strength path,
# shaped by a per-channel threshold/gain and scaled to the channel's max
# strength. Inherits the ~60 Hz poll + debounce from PollingRouter; the engine
# owns the 100 ms B0 cadence, so the router just pushes debounced strength
# targets and the engine coalesces them into frames.

from typing import Any, Callable, Dict, Optional

from router_base import PollingRouter
from zone_strength import zone_filter_strength

STRENGTH_MAX = 200


def compute_channel_strength(cfg: Dict[str, Any], strength01: float,
                             scale: float = 1.0) -> int:
    """Shape a 0..1 zone strength into a 0-200 channel strength using the
    channel's threshold / gain / max_strength. `scale` is the mode master
    scale (0..1); applied pre-quantization so attenuation keeps full
    resolution, and scale=0 guarantees 0. Pure + testable."""
    if not cfg or not cfg.get("enabled", True):
        return 0
    try:
        threshold = float(cfg.get("threshold", 0.0))
        gain = float(cfg.get("gain", 1.0))
        max_strength = int(cfg.get("max_strength", 100))
    except (TypeError, ValueError):
        threshold, gain, max_strength = 0.0, 1.0, 100
    if strength01 <= threshold:
        return 0
    shaped = (strength01 - threshold) * gain
    shaped *= scale
    shaped = max(0.0, min(1.0, shaped))
    val = int(round(shaped * max(0, min(STRENGTH_MAX, max_strength))))
    return max(0, min(STRENGTH_MAX, val))


class CoyoteRouter(PollingRouter):
    """Maps two configured channels (A/B) to Coyote strengths each tick."""

    def __init__(self,
                 engine,
                 get_channel_configs: Callable[[], Dict[str, Dict[str, Any]]],
                 get_sps_sources: Optional[Callable[[], Dict[str, Any]]] = None,
                 poll_rate_s: float = 0.016,
                 get_master_scale: Optional[Callable[[], float]] = None):
        super().__init__("CoyoteRouter", engine, poll_rate_s=poll_rate_s)
        self.get_channel_configs = get_channel_configs
        self.get_sps_sources = get_sps_sources or (lambda: None)
        # Mode master scale (0..1); no test-level hook here — e-stim is
        # deliberately excluded from the connectivity pulse (see constants.py
        # OGP_TEST_LEVEL).
        self.get_master_scale = get_master_scale or (lambda: 1.0)

    def _engine_ready(self) -> bool:
        return self.engine.is_connected

    def compute_targets(self, params: Dict[str, Any]) -> Dict[str, int]:
        cfgs = self.get_channel_configs() or {}
        try:
            sps_sources = self.get_sps_sources()
        except Exception:
            sps_sources = None
        try:
            scale = float(self.get_master_scale())
        except Exception:
            scale = 1.0
        out: Dict[str, int] = {}
        for ch in ("A", "B"):
            cfg = cfgs.get(ch)
            if not isinstance(cfg, dict):
                continue
            # A disabled channel still emits 0 so it actively silences (an
            # e-stim channel must not latch at its last value when turned off).
            strength01 = zone_filter_strength(
                cfg.get("ogb_zone"), cfg.get("zone_type", "Orf"),
                cfg.get("filters") or [], params, sps_sources)
            out[ch] = compute_channel_strength(cfg, strength01, scale)
        return out

    def dispatch(self, channel: str, target: int) -> None:
        self.engine.set_channel_strength(channel, target)
