# OscGoesPurrr - Per-feature send gating for the Buttplug dispatch loop
"""FeatureSendGate — the pure decision core of HapticEngine.async_worker.

The engine loop ticks fast (HAPTIC_POLL_RATE) for low latency, but no
single motor may be commanded faster than its cap, out of order, or
redundantly. Those rules used to live inline in the loop's three dispatch
branches (legacy device-wide vibrate, linear, continuous), each hand-rolling
the same check-then-record bookkeeping across three dicts. This class owns
that state and the decisions over it, so the invariants are testable
without a connection, a loop, or the buttplug package:

* **In-flight guard** — at most one fire-and-forget send per feature; while
  one is pending the loop holds the newest value for a later tick
  (latest-wins, naturally coalesced).
* **Rate cap** — fire-and-forget removed the natural backpressure of
  awaiting each ack, so consecutive sends per feature are spaced by an
  explicit interval (HAPTIC_MAX_SEND_HZ by default; linear actuators pass
  their lower LINEAR_MAX_SEND_HZ cadence). The first send after a quiet
  gap is never delayed — step/edge latency is untouched.
* **Change / delta gate** — continuous outputs only send when the routed
  value differs from what was last *sent*; linear positions only when the
  sleeve would move at least `min_delta` from the last sent position, so a
  held or resting stroke goes quiet instead of re-commanding the same spot.
* **Record-on-grant** — a granted send records the value and timestamp
  atomically; a denial leaves state untouched so the newest value is
  retried on the next tick. The loop never updates the books by hand.

Pure Python: no asyncio, no I/O, no Qt. Single-threaded by contract — the
engine only touches it from its own event loop.
"""

from typing import Dict, Optional, Tuple

from haptic_actuators import compute_send_duration_ms

# (device_name, motor_idx); motor_idx -1 is the legacy device-wide slot.
FeatureKey = Tuple[str, int]


class FeatureSendGate:
    """Send bookkeeping + decision rules for one engine's features."""

    def __init__(self, default_interval_ms: float) -> None:
        self.default_interval_ms = float(default_interval_ms)
        # Last value actually sent (0-1 level or stroke position).
        self.last_sent: Dict[FeatureKey, float] = {}
        # Last send time (ms, caller's clock — time.monotonic()*1000).
        self.last_send_ms: Dict[FeatureKey, float] = {}
        # "A fire-and-forget send is in flight" flags.
        self.inflight: Dict[FeatureKey, bool] = {}

    # ------------------------------------------------------------ decisions
    def can_send(self, key: FeatureKey, now_ms: float,
                 min_interval_ms: Optional[float] = None) -> bool:
        """True only when no send is in flight for this feature AND its rate
        cap has elapsed since the last send. Never blocks a first send."""
        if self.inflight.get(key):
            return False
        gap = (self.default_interval_ms if min_interval_ms is None
               else min_interval_ms)
        last = self.last_send_ms.get(key)
        return last is None or (now_ms - last) >= gap

    def try_continuous(self, key: FeatureKey, target: float,
                       now_ms: float) -> bool:
        """Grant a continuous-output send (vibrate/rotate/led/…) when the
        target changed since the last send and the feature is free. Records
        the send on grant. A never-sent feature counts as last-sent 0.0 —
        the server starts devices at rest, so commanding 0 again is noise."""
        if target == self.last_sent.get(key, 0.0):
            return False
        if not self.can_send(key, now_ms):
            return False
        self.last_sent[key] = target
        self.last_send_ms[key] = now_ms
        return True

    def try_linear(self, key: FeatureKey, position: float, now_ms: float,
                   min_interval_ms: float, min_delta: float,
                   duration_overlap: float,
                   max_interval_ms: float) -> Optional[int]:
        """Grant a linear (stroker) send: returns the commanded interpolation
        duration in ms, or None to hold this tick.

        Grants only when the feature is free at the linear cadence AND the
        position moved at least `min_delta` from the last *sent* position
        (a never-sent feature always passes — the resting seed must reach
        the device). The duration OVERSHOOTS the real gap since our last
        send (clamped, scaled by `duration_overlap`) so the device is still
        travelling when the next position lands — an undershoot is exactly
        what made slow motion "step". Self-adapts to the device's actual
        cadence (BLE jitter, in-flight stalls) because it is sized from the
        measured gap, not the nominal cap."""
        if not self.can_send(key, now_ms, min_interval_ms):
            return None
        last_pos = self.last_sent.get(key)
        if last_pos is not None and abs(position - last_pos) < min_delta:
            return None
        last_send = self.last_send_ms.get(key)
        interval = (now_ms - last_send if last_send is not None
                    else min_interval_ms)
        duration = compute_send_duration_ms(
            interval, duration_overlap, min_interval_ms, max_interval_ms)
        self.last_sent[key] = position
        self.last_send_ms[key] = now_ms
        return duration

    # ------------------------------------------------------------ in-flight
    def set_inflight(self, key: FeatureKey, flag: bool) -> None:
        self.inflight[key] = bool(flag)

    # ------------------------------------------------------------ lifecycle
    def clear(self) -> None:
        """Forget everything — used on (re)connect and disconnect. The server
        stops devices when a session ends, so a routed target unchanged
        across the outage must be re-sent: keeping the old `last_sent` cache
        would leave the change gate suppressing it and the toy silent until
        the value next moved."""
        self.last_sent.clear()
        self.last_send_ms.clear()
        self.inflight.clear()

    def forget_device(self, device_name: str) -> None:
        """Drop all state for one device (unplugged / powered off) so a key
        reused by a later reconnect starts from a clean slate."""
        for d in (self.last_sent, self.last_send_ms, self.inflight):
            for k in [k for k in d if k[0] == device_name]:
                d.pop(k, None)
