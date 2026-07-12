"""Usage-statistics controller facade.

Mixin: owns the `StatsTracker` (lifetime totals + per-session
summaries) and adapts the app's live state into its 1 Hz samples.

Wiring contract:

* `main._setup_components()` calls `_stats_init()` once, after the
  motor router exists.
* `main.run()`'s 1 Hz `refresh_device_states` heartbeat calls
  `_stats_sample_tick()` — that's the whole sampling cadence; no
  timer or thread of its own, and nothing touches a routing hot path
  beyond the router's O(1) `consume_thrusts()` drain.
* `quit_app()` calls `_stats_shutdown()` before engine teardown so
  the session summary + final flush land on disk.

Host attributes assumed: `self.motor_router`, `self.haptic_engine`,
`self._muted_devices`, and the modes facade's `get_master_scale()`.
"""

import time
from typing import Any, Dict, List, Tuple

from parameter_store import store
from router_base import StaleSignalMonitor
from settings import STATS_FILE
from stats_tracker import StatsTracker
from zone_strength import zone_filter_strength


# parameter_store.get_detected_zones() bucket -> OGB zone-type prefix.
_ZONE_BUCKETS: Tuple[Tuple[str, str], ...] = (
    ("Orifices", "Orf"),
    ("Penetrators", "Pen"),
    ("Touch", "Touch"),
)

# Every filter zone_strength can resolve for a zone type. Contact for
# statistics means "any signal at all", so this is the union of what
# the routers select from per type: Orf/Pen carry the four
# touch/pen filters plus FrotOthers (zone_filter_strength applies the
# generic <filter>Close gate, absent = open, so FrotOthers works on
# both sides); Touch zones only ever expose Self/Others proximity.
_CONTACT_FILTERS: Dict[str, List[str]] = {
    # PenetratingSelf/Others are the legacy parameter names older
    # avatars emit — the motor router falls back to them, so contact
    # statistics must see them too or those zones read 0 forever.
    "Orf": ["TouchSelf", "TouchOthers", "PenSelf", "PenOthers",
            "FrotOthers", "PenetratingSelf", "PenetratingOthers"],
    "Pen": ["TouchSelf", "TouchOthers", "PenSelf", "PenOthers",
            "FrotOthers", "PenetratingSelf", "PenetratingOthers"],
    "Touch": ["TouchSelf", "TouchOthers"],
}

# Cap on a single sample's dt. The heartbeat runs at 1 Hz, so anything
# much larger means the process was suspended (laptop sleep, debugger
# pause) — hours nobody was being touched must not count as on-time.
_MAX_SAMPLE_DT_S = 5.0

# Flush the stats file roughly once a minute of sampling. Losing up to
# a minute of lifetime totals on a hard crash is fine; the session
# summary lands via finalize at clean shutdown.
_FLUSH_EVERY_SAMPLES = 60


class StatsFacade:
    """Mixin: usage statistics. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Init / shutdown wiring (called from main.py)
    # ------------------------------------------------------------------

    def _stats_init(self) -> None:
        """Build the tracker and open this app run's session. Called
        from _setup_components after the motor router exists. Guarded:
        statistics must never be able to break app boot — the tracker
        self-heals corrupt files, but if anything still raises, the
        feature stays dead for the session and everything else runs."""
        self.stats_tracker = None
        try:
            self.stats_tracker = StatsTracker(STATS_FILE)
            self.stats_tracker.start_session(time.time())
        except Exception as e:
            print(f"[stats] init failed, statistics disabled: {e}")
        # Monotonic timestamp of the previous sample; None = no sample
        # yet (the first heartbeat only anchors the clock).
        self._stats_last_sample_t = None
        self._stats_samples_since_flush = 0
        # parameter_store retains values forever; if VRChat dies with a
        # contact latched high, zone "contact" would accrue off the
        # frozen snapshot indefinitely. Same primitive the routers use.
        self._stats_stale_monitor = StaleSignalMonitor()

    def _stats_shutdown(self) -> None:
        """Finalize the session (records it if it saw activity) and
        flush. Called from quit_app before engine teardown."""
        try:
            self.stats_tracker.finalize_session(time.time())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 1 Hz sampling (called from main.py's device-state heartbeat)
    # ------------------------------------------------------------------

    def _stats_sample_tick(self) -> None:
        """Gather one usage sample and hand it to the tracker. The
        whole body is guarded — a stats bug must never break the
        heartbeat that hosts it."""
        try:
            if self.stats_tracker is None:
                return
            now = time.monotonic()
            last = self._stats_last_sample_t
            self._stats_last_sample_t = now
            if last is None:
                return
            dt = min(max(0.0, now - last), _MAX_SAMPLE_DT_S)

            # Toys currently driven — meaning ACTUALLY driven. The
            # router's last_outputs covers every stored toy (wiring is
            # remembered for offline devices) and is computed upstream
            # of every silencing layer, so it alone would book on-time
            # against toys in a drawer, muted toys, the Off mode, and
            # simulator-suppressed motors. Apply the same gates
            # update_device_target applies before anything reaches
            # hardware. Keys are (device, motor) tuples; this read and
            # the router's writes share the GUI thread.
            on_toys: List[str] = []
            engine = getattr(self, "haptic_engine", None)
            if (engine is not None and engine.is_connected
                    and self.get_master_scale() > 0.0):
                try:
                    connected = set(
                        engine.list_connected_device_names() or ())
                except Exception:
                    connected = set()
                muted = getattr(self, "_muted_devices", set())
                router = self.motor_router
                on_toys = sorted({
                    key[0] for key, val in router.last_outputs.items()
                    if val > 0.0
                    and key[0] in connected
                    and key[0] not in muted
                    and router.should_send_to_toy(key[0], key[1])
                })

            # Zones currently in contact: every detected zone whose
            # full filter set resolves to a non-zero strength — but only
            # while OSC is demonstrably alive. The store retains values
            # forever, so a crash mid-contact would otherwise read as
            # "in contact" for hours.
            contact_zones: List[Tuple[str, str]] = []
            if not self._stats_stale_monitor.is_stale():
                detected = store.get_detected_zones() or {}
                params = store.get_all_parameters() or {}
                for bucket, ztype in _ZONE_BUCKETS:
                    filters = _CONTACT_FILTERS[ztype]
                    for zone_name in detected.get(bucket, ()):
                        strength = zone_filter_strength(
                            zone_name, ztype, filters, params, None)
                        if strength > 0.0:
                            contact_zones.append(
                                (f"{ztype}/{zone_name}", ztype))

            thrusts = self.motor_router.consume_thrusts()
            self.stats_tracker.sample(dt, on_toys, contact_zones, thrusts)

            self._stats_samples_since_flush += 1
            if self._stats_samples_since_flush >= _FLUSH_EVERY_SAMPLES:
                self._stats_samples_since_flush = 0
                self.stats_tracker.flush()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI facade
    # ------------------------------------------------------------------

    def get_stats_snapshot(self) -> Dict[str, Any]:
        """Deep-copied {"lifetime", "session", "recent_sessions"} for
        the Statistics view. Defensive: never raises into the UI."""
        try:
            return self.stats_tracker.snapshot()
        except Exception:
            return {}

    def reset_stats(self) -> None:
        """Zero ALL lifetime statistics (including recent sessions) and
        start a fresh session anchored now."""
        try:
            self.stats_tracker.reset_lifetime()
            self.stats_tracker.start_session(time.time())
        except Exception:
            pass
