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


def cross_correlation_latencies(
    in_arr: np.ndarray,
    out_arr: np.ndarray,
    period_s: float,
    max_lag_s: float = 0.3,
    dt: float = 0.003,
    min_corr: float = 0.3,
    max_cycles: int = 20,
) -> List[float]:
    """Per-cycle cross-correlation latency (ms) for a periodic input.

    The waveform-agnostic alternative to edge pairing: resample input + output
    onto a uniform ``dt`` grid, then for each full period find the lag in
    ``[0, max_lag]`` that maximises the *normalised* correlation of the output
    against that cycle's input. Works for sine / triangle / sawtooth / square
    and is robust to the output being smoothed or amplitude-scaled. Returns one
    latency per usable cycle; cycles whose best correlation is below
    ``min_corr`` (the output isn't tracking) are skipped.
    """
    if period_s <= 0 or in_arr.shape[0] < 4 or out_arr.shape[0] < 4:
        return []
    t0 = max(float(in_arr[0, 0]), float(out_arr[0, 0]))
    t1 = min(float(in_arr[-1, 0]), float(out_arr[-1, 0]))
    if t1 - t0 < period_s:
        return []
    # Only analyse the most recent window so cost stays CONSTANT as the buffers
    # grow — otherwise each live refresh re-correlates the whole history and the
    # UI gets progressively laggier.
    window = (max_cycles + 1) * period_s
    if t1 - t0 > window:
        t0 = t1 - window
    grid = np.arange(t0, t1, dt)
    xi = np.interp(grid, in_arr[:, 0], in_arr[:, 1])
    xo = np.interp(grid, out_arr[:, 0], out_arr[:, 1])
    n_cycle = max(2, int(round(period_s / dt)))
    max_lag = min(max_lag_s, 0.45 * period_s)
    n_lag = max(1, int(round(max_lag / dt)))
    lats: List[float] = []
    k = 0
    while k < max_cycles:
        i0 = k * n_cycle
        i1 = i0 + n_cycle
        if i1 + n_lag > grid.size:
            break
        seg = xi[i0:i1] - xi[i0:i1].mean()
        sn = float(np.linalg.norm(seg))
        if sn < 1e-9:
            k += 1
            continue
        best_corr, best_lag = -2.0, 0
        for lag in range(n_lag + 1):
            ow = xo[i0 + lag:i1 + lag]
            ow = ow - ow.mean()
            on = float(np.linalg.norm(ow))
            if on < 1e-9:
                continue
            c = float(np.dot(seg, ow) / (sn * on))
            if c > best_corr:
                best_corr, best_lag = c, lag
        if best_corr >= min_corr:
            lats.append(best_lag * dt * 1000.0)
        k += 1
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

    def correlation_latencies(self, period_s: float, max_lag_s: float = 0.3) -> List[float]:
        """Per-cycle cross-correlation latencies (ms) over the current buffers —
        the waveform-agnostic alternative to edge pairing (good for sine etc.)."""
        in_arr, out_arr = self.snapshot()
        return cross_correlation_latencies(in_arr, out_arr, period_s, max_lag_s)

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
