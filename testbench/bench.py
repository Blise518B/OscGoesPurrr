"""Measurement engine for the test bench — clock, sample buffers, edge
detection, and end-to-end latency pairing.

No Qt and no networking: this is a pure, thread-safe core so it can be unit
tested without hardware. The bench records two streams stamped with the SAME
``time.perf_counter`` clock in one process:

* **input**  — the value the bench sent to OGP (stamped at send time, on the
  UI thread that runs the signal driver).
* **output** — the level the virtual toy received back from OGP via Intiface
  (stamped at receive time, on the websocket worker thread).

Latency = (time the toy first moved) − (time the matching input edge was sent).
Because both stamps come from one clock there is no clock-sync error; the
number is the real round trip through OGP + Intiface.

Pairing: each input *rising* edge (value crosses ``input_threshold`` upward)
is queued; the first output *rising* edge (crosses ``output_threshold``
upward) after it, within ``max_window_s``, is paired with it. Input edges that
get no output within the window are counted as misses. A small hysteresis on
each detector prevents threshold chatter from spawning phantom edges.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Tuple

import numpy as np

# How many samples to retain per channel. At ~125 Hz input / ~62 Hz output
# this is ~a minute of history — enough for the scrolling plot, the recent
# correlation window, and a CSV dump of a benchmark run. Kept bounded so the
# per-frame snapshot/plot cost does not grow without limit as the bench runs.
_MAX_SAMPLES = 8000

# Cap on retained edge-paired latencies — live edge mode appends one per cycle
# forever otherwise; stats/histogram use the most recent ones.
_MAX_LATENCIES = 5000


def latency_stats(latencies_ms: List[float]) -> Dict[str, Optional[float]]:
    """Summary statistics for a list of latencies (ms).

    Returns count plus min/mean/median/p95/max and jitter (population stdev).
    Empty input yields ``count=0`` and ``None`` for every statistic.
    """
    n = len(latencies_ms)
    if n == 0:
        return {
            "count": 0, "min_ms": None, "mean_ms": None, "median_ms": None,
            "p95_ms": None, "max_ms": None, "jitter_ms": None,
        }
    arr = np.asarray(latencies_ms, dtype=float)
    return {
        "count": int(n),
        "min_ms": float(arr.min()),
        "mean_ms": float(arr.mean()),
        "median_ms": float(np.median(arr)),
        "p95_ms": float(np.percentile(arr, 95)),
        "max_ms": float(arr.max()),
        "jitter_ms": float(arr.std(ddof=0)),
    }


def _rising_midline_crossings(arr: np.ndarray, min_amp: float) -> List[float]:
    """Interpolated times at which the signal rises through its own midline
    (``(min + max) / 2`` over the window). Vectorised; O(n)."""
    if arr.shape[0] < 2:
        return []
    t = arr[:, 0]
    v = arr[:, 1]
    vmin = float(v.min())
    vmax = float(v.max())
    if vmax - vmin < min_amp:  # essentially flat — no usable transitions
        return []
    mid = 0.5 * (vmin + vmax)
    idx = np.nonzero((v[:-1] < mid) & (v[1:] >= mid))[0]
    if idx.size == 0:
        return []
    v0 = v[idx]
    v1 = v[idx + 1]
    denom = np.where(v1 != v0, v1 - v0, 1.0)
    frac = (mid - v0) / denom
    cross = t[idx] + frac * (t[idx + 1] - t[idx])
    return cross.tolist()


def crossing_latencies(
    in_arr: np.ndarray,
    out_arr: np.ndarray,
    max_lag_s: float = 0.3,
    min_amp: float = 0.05,
) -> List[float]:
    """Per-transition latency (ms) via midline rising-crossings.

    Each channel's midline is its own ``(min + max) / 2`` over the window, so
    the measure is amplitude- and offset-independent. A rising midline crossing
    sits at the signal's *steepest* point — a stable timing reference for any
    periodic waveform (sine, triangle, sawtooth, square) and for a one-shot
    step / pulse. This avoids the broad, jittery correlation peak that a
    narrowband sine produces. Each input rising crossing is paired with the next
    output rising crossing within ``max_lag_s``. O(n) over the (bounded)
    buffers, so cost stays constant.
    """
    in_cr = _rising_midline_crossings(in_arr, min_amp)
    out_cr = _rising_midline_crossings(out_arr, min_amp)
    if not in_cr or not out_cr:
        return []
    lats: List[float] = []
    j = 0
    for ti in in_cr:
        while j < len(out_cr) and out_cr[j] <= ti:
            j += 1
        if j < len(out_cr) and (out_cr[j] - ti) <= max_lag_s:
            lats.append((out_cr[j] - ti) * 1000.0)
    return lats


class EdgeDetector:
    """Incremental rising/falling threshold-crossing detector with hysteresis.

    Feed values in order via :meth:`update`; it returns ``"rising"`` the first
    time a value reaches ``threshold`` while armed, then stays disarmed until
    the value falls back below ``threshold - hysteresis`` (which returns
    ``"falling"`` and re-arms). This debounces noisy signals hovering near the
    threshold.
    """

    def __init__(self, threshold: float = 0.5, hysteresis: float = 0.05) -> None:
        self.threshold = float(threshold)
        self.hysteresis = float(hysteresis)
        self._armed = True  # ready to fire a rising edge

    def reset(self) -> None:
        self._armed = True

    def set_threshold(self, threshold: float) -> None:
        self.threshold = float(threshold)

    def update(self, value: float) -> Optional[str]:
        if self._armed:
            if value >= self.threshold:
                self._armed = False
                return "rising"
            return None
        # disarmed: wait for the value to clearly drop before re-arming
        if value <= self.threshold - self.hysteresis:
            self._armed = True
            return "falling"
        return None


class BenchEngine:
    """Records input/output samples on one clock and measures latency.

    Thread-safe: ``record_input`` runs on the UI thread, ``record_output`` on
    the websocket worker thread; everything is guarded by a single lock.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.perf_counter,
        input_threshold: float = 0.5,
        output_threshold: float = 0.05,
        max_window_s: float = 1.0,
    ) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._t0 = clock()

        self._in: Deque[Tuple[float, float]] = deque(maxlen=_MAX_SAMPLES)
        self._out: Deque[Tuple[float, float]] = deque(maxlen=_MAX_SAMPLES)

        self._in_edge = EdgeDetector(input_threshold)
        self._out_edge = EdgeDetector(output_threshold)

        self._pending_in: Deque[float] = deque()  # input rising-edge times
        self._latencies_ms: Deque[float] = deque(maxlen=_MAX_LATENCIES)
        self._misses = 0
        self._max_window_s = float(max_window_s)

    # -------------------------------------------------------------- clock
    def now(self) -> float:
        return self._clock()

    # -------------------------------------------------------------- config
    def set_input_threshold(self, thr: float) -> None:
        with self._lock:
            self._in_edge.set_threshold(thr)

    def set_output_threshold(self, thr: float) -> None:
        with self._lock:
            self._out_edge.set_threshold(thr)

    def set_max_window(self, seconds: float) -> None:
        with self._lock:
            self._max_window_s = float(seconds)

    # -------------------------------------------------------------- recording
    def record_input(self, t: float, value: float) -> None:
        with self._lock:
            self._in.append((t, value))
            if self._in_edge.update(value) == "rising":
                self._pending_in.append(t)
            self._expire(t)

    def record_output(self, t: float, value: float) -> None:
        with self._lock:
            self._out.append((t, value))
            if self._out_edge.update(value) == "rising":
                self._pair(t)
            self._expire(t)

    # -------------------------------------------------------------- pairing
    def _expire(self, now: float) -> None:
        """Drop pending input edges that aged out without an output (misses)."""
        while self._pending_in and (now - self._pending_in[0]) > self._max_window_s:
            self._pending_in.popleft()
            self._misses += 1

    def _pair(self, t_out: float) -> None:
        """Pair this output rising edge with the oldest in-window input edge."""
        while self._pending_in:
            t_in = self._pending_in[0]
            if t_out < t_in:
                return  # output edge precedes the oldest input edge — ignore
            if (t_out - t_in) <= self._max_window_s:
                self._pending_in.popleft()
                self._latencies_ms.append((t_out - t_in) * 1000.0)
                return
            # too old to be this edge's response — discard and try the next
            self._pending_in.popleft()
            self._misses += 1

    # -------------------------------------------------------------- readouts
    def latencies_ms(self) -> List[float]:
        with self._lock:
            return list(self._latencies_ms)

    def stats(self) -> Dict[str, Optional[float]]:
        return latency_stats(self.latencies_ms())

    def crossing_latencies(self, max_lag_s: float = 0.3) -> List[float]:
        """Midline-crossing latencies (ms) over the current buffers — the
        waveform-agnostic measure (stable for sine / triangle / saw, and also
        works for square / step)."""
        in_arr, out_arr = self.snapshot()
        return crossing_latencies(in_arr, out_arr, max_lag_s)

    def misses(self) -> int:
        with self._lock:
            return self._misses

    def snapshot(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return ``(input, output)`` as ``(N, 2)`` arrays of ``(t, value)``.

        Times are relative to the engine's creation/reset (``t0``) in seconds,
        so plot/CSV consumers get a stable zero-based timeline.
        """
        with self._lock:
            t0 = self._t0
            in_arr = (np.array(self._in, dtype=float)
                      if self._in else np.empty((0, 2), dtype=float))
            out_arr = (np.array(self._out, dtype=float)
                       if self._out else np.empty((0, 2), dtype=float))
        if in_arr.size:
            in_arr[:, 0] -= t0
        if out_arr.size:
            out_arr[:, 0] -= t0
        return in_arr, out_arr

    def reset(self) -> None:
        """Clear all buffers, edges, and measurements; re-zero the clock base."""
        with self._lock:
            self._t0 = self._clock()
            self._in.clear()
            self._out.clear()
            self._in_edge.reset()
            self._out_edge.reset()
            self._pending_in.clear()
            self._latencies_ms.clear()
            self._misses = 0
