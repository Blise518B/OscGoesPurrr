"""Tests for the bench measurement core and signal math.

Pure Python — no Qt event loop, no networking, no hardware. Covers the
waveform sampler, the edge detector's hysteresis, the latency-pairing logic,
and the summary statistics.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from testbench import csv_export
from testbench.bench import BenchEngine, EdgeDetector, latency_stats
from testbench.generators import WAVEFORMS, clamp01, sample_pattern


# ----------------------------------------------------------------- generators

def test_clamp01_bounds():
    assert clamp01(-1.0) == 0.0
    assert clamp01(0.4) == pytest.approx(0.4)
    assert clamp01(2.0) == 1.0


def test_sample_pattern_zero_or_unknown():
    assert sample_pattern("sine", 0.0, 1.0, 0.3) == 0.0      # freq <= 0
    assert sample_pattern("sine", -1.0, 1.0, 0.3) == 0.0
    assert sample_pattern("bogus", 1.0, 1.0, 0.3) == 0.0     # unknown shape


def test_sample_pattern_square_edges():
    # 1 Hz square: high in the first half of each cycle, low in the second.
    assert sample_pattern("square", 1.0, 1.0, 0.0) == 1.0
    assert sample_pattern("square", 1.0, 1.0, 0.25) == 1.0
    assert sample_pattern("square", 1.0, 1.0, 0.5) == 0.0
    assert sample_pattern("square", 1.0, 0.7, 0.1) == pytest.approx(0.7)


def test_sample_pattern_shapes_in_range():
    for wf in WAVEFORMS:
        for i in range(101):
            t = i / 50.0
            v = sample_pattern(wf, 1.3, 1.0, t)
            assert -1e-9 <= v <= 1.0 + 1e-9


def test_sample_pattern_sine_known_points():
    assert sample_pattern("sine", 1.0, 1.0, 0.0) == pytest.approx(0.5)   # phase 0
    assert sample_pattern("sine", 1.0, 1.0, 0.25) == pytest.approx(1.0)  # peak
    assert sample_pattern("sine", 1.0, 1.0, 0.75) == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------- edge detector

def test_edge_detector_rising_then_falling_with_hysteresis():
    ed = EdgeDetector(threshold=0.5, hysteresis=0.1)
    assert ed.update(0.0) is None
    assert ed.update(0.6) == "rising"      # crosses up
    assert ed.update(0.7) is None          # stays high — no repeat
    assert ed.update(0.45) is None         # within hysteresis band — no re-arm
    assert ed.update(0.39) == "falling"    # drops below thr - hys -> re-arm
    assert ed.update(0.6) == "rising"      # next genuine edge


# ----------------------------------------------------------------- bench engine

def test_bench_single_latency():
    be = BenchEngine(input_threshold=0.5, output_threshold=0.05, max_window_s=1.0)
    be.record_input(0.00, 0.0)
    be.record_input(0.10, 1.0)   # input rising edge @ 0.10
    be.record_output(0.12, 0.0)  # below output threshold — not an edge yet
    be.record_output(0.13, 0.5)  # output rising edge @ 0.13 -> pair
    assert be.latencies_ms() == pytest.approx([30.0])
    assert be.misses() == 0


def test_bench_multiple_cycles_pair_in_order():
    be = BenchEngine(input_threshold=0.5, output_threshold=0.05, max_window_s=1.0)
    be.record_input(0.00, 0.0)
    be.record_input(0.10, 1.0)   # edge 1 @ 0.10
    be.record_output(0.15, 0.8)  # -> 50 ms
    be.record_input(0.50, 0.0)   # input falls (re-arm)
    be.record_output(0.60, 0.0)  # output falls (re-arm)
    be.record_input(1.10, 1.0)   # edge 2 @ 1.10
    be.record_output(1.18, 0.8)  # -> 80 ms
    assert be.latencies_ms() == pytest.approx([50.0, 80.0])
    assert be.misses() == 0


def test_bench_miss_when_output_too_late():
    be = BenchEngine(input_threshold=0.5, output_threshold=0.05, max_window_s=1.0)
    be.record_input(0.0, 0.0)
    be.record_input(0.1, 1.0)    # edge, pending
    be.record_output(2.0, 0.8)   # 1.9 s later — beyond the window -> miss
    assert be.latencies_ms() == []
    assert be.misses() == 1


def test_bench_snapshot_is_zero_based_and_shaped():
    be = BenchEngine()
    be.record_input(be.now() + 0.0, 0.2)
    be.record_output(be.now() + 0.0, 0.4)
    in_arr, out_arr = be.snapshot()
    assert in_arr.shape[1] == 2 and out_arr.shape[1] == 2
    assert in_arr.shape[0] == 1 and out_arr.shape[0] == 1
    # times are relative to t0, so they are small and non-negative
    assert in_arr[0, 0] >= 0.0


def test_bench_reset_clears_everything():
    be = BenchEngine()
    be.record_input(0.0, 0.0)
    be.record_input(0.1, 1.0)
    be.record_output(0.13, 1.0)
    assert be.latencies_ms()
    be.reset()
    assert be.latencies_ms() == []
    assert be.misses() == 0
    in_arr, out_arr = be.snapshot()
    assert in_arr.shape[0] == 0 and out_arr.shape[0] == 0


# -------------------------------------------------------------------- stats

def test_latency_stats_empty():
    s = latency_stats([])
    assert s["count"] == 0
    assert s["mean_ms"] is None and s["p95_ms"] is None


def test_latency_stats_known_values():
    s = latency_stats([10.0, 20.0, 30.0])
    assert s["count"] == 3
    assert s["min_ms"] == pytest.approx(10.0)
    assert s["max_ms"] == pytest.approx(30.0)
    assert s["mean_ms"] == pytest.approx(20.0)
    assert s["median_ms"] == pytest.approx(20.0)
    # population stdev of [10,20,30] = sqrt(200/3)
    assert s["jitter_ms"] == pytest.approx(math.sqrt(200.0 / 3.0))
    assert 20.0 <= s["p95_ms"] <= 30.0


# -------------------------------------------------------------------- csv export

def test_export_all_writes_three_files(tmp_path):
    in_arr = np.array([[0.0, 0.0], [0.1, 1.0]], dtype=float)
    out_arr = np.array([[0.13, 1.0]], dtype=float)
    lat = [30.0, 31.5]
    stats = latency_stats(lat)
    base = str(tmp_path / "run")
    files = csv_export.export_all(base, in_arr, out_arr, lat, stats, misses=0)
    assert len(files) == 3
    for f in files:
        assert f.endswith(".csv")
        assert Path(f).read_text(encoding="utf-8")  # non-empty
    # samples file has a header + 3 data rows (2 input + 1 output)
    samples = Path(files[0]).read_text(encoding="utf-8").strip().splitlines()
    assert samples[0] == "t_s,channel,value"
    assert len(samples) == 1 + 3


def test_export_handles_empty(tmp_path):
    empty = np.empty((0, 2), dtype=float)
    files = csv_export.export_all(str(tmp_path / "e"), empty, empty, [], latency_stats([]))
    assert len(files) == 3  # still writes headers, no crash
