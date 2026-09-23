"""CSV export for a benchmark run — raw samples, per-edge latencies, summary.

Plain stdlib ``csv``; consumes the numpy arrays from
:meth:`testbench.bench.BenchEngine.snapshot` and the latency list. Times are
the zero-based seconds the snapshot already produces.
"""

from __future__ import annotations

import csv
from typing import Dict, List, Optional

import numpy as np

_SUMMARY_KEYS = (
    "count", "min_ms", "mean_ms", "median_ms", "p95_ms", "max_ms", "jitter_ms",
)


def export_samples(path: str, in_arr: np.ndarray, out_arr: np.ndarray) -> None:
    """Long-format raw samples: ``t_s, channel, value`` (one row per sample)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "channel", "value"])
        for t, v in in_arr:
            w.writerow([f"{t:.6f}", "input", f"{v:.6f}"])
        for t, v in out_arr:
            w.writerow([f"{t:.6f}", "output", f"{v:.6f}"])


def export_latencies(path: str, latencies_ms: List[float]) -> None:
    """Per-edge latencies: ``index, latency_ms``."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["index", "latency_ms"])
        for i, lat in enumerate(latencies_ms):
            w.writerow([i, f"{lat:.3f}"])


def export_summary(
    path: str,
    stats: Dict[str, Optional[float]],
    misses: Optional[int] = None,
) -> None:
    """Summary stats: ``metric, value`` (one row per metric)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k in _SUMMARY_KEYS:
            w.writerow([k, stats.get(k)])
        if misses is not None:
            w.writerow(["misses", misses])


def export_all(
    base_path: str,
    in_arr: np.ndarray,
    out_arr: np.ndarray,
    latencies_ms: List[float],
    stats: Dict[str, Optional[float]],
    misses: Optional[int] = None,
) -> List[str]:
    """Write ``<base>_samples.csv`` / ``_latencies.csv`` / ``_summary.csv``.

    ``base_path`` is a path with any extension stripped. Returns the list of
    files written.
    """
    if base_path.lower().endswith(".csv"):
        base_path = base_path[:-4]
    samples = f"{base_path}_samples.csv"
    latencies = f"{base_path}_latencies.csv"
    summary = f"{base_path}_summary.csv"
    export_samples(samples, in_arr, out_arr)
    export_latencies(latencies, latencies_ms)
    export_summary(summary, stats, misses)
    return [samples, latencies, summary]
