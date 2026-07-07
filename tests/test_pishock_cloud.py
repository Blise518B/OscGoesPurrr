"""Tests for the PiShock cloud transport (pishock_cloud.py).

The engine's caps were already pinned by test_pishock_engine_caps; these
tests cover the layer BELOW them, which used to be able to undo the caps:
duration seconds must floor (never round a clamped 1500 ms up to 2 s),
stale queued jobs must be dropped instead of delivered late in a burst,
and the API response body must be inspected (apioperate reports failures
inside an HTTP 200).

No network: `requests` is monkeypatched, and the worker thread is bypassed
by calling _process() directly / no-opping _ensure_worker.
"""

import queue
import time

import pytest

import pishock_cloud
from pishock_cloud import JOB_TTL_S, PiShockCloudConnection


class FakeResponse:
    def __init__(self, status_code=200, text="Operation Succeeded."):
        self.status_code = status_code
        self.text = text


class FakeRequests:
    def __init__(self, response=None):
        self.posts = []  # list of (url, json, timeout)
        self.response = response or FakeResponse()

    def post(self, url, json=None, timeout=None):
        self.posts.append((url, json, timeout))
        return self.response


@pytest.fixture
def conn(monkeypatch):
    c = PiShockCloudConnection(log=lambda m: c.logged.append(m))
    c.logged = []
    c.configure({"username": "u", "apikey": "k", "code": "c", "name": "n"})
    # Keep the worker thread out of unit tests — payloads are inspected on
    # the queue and _process() is driven inline.
    monkeypatch.setattr(c, "_ensure_worker", lambda: None)
    return c


def _queued_payload(c):
    ts, payload = c._jobs.get_nowait()
    return payload


class TestDurationConversion:
    @pytest.mark.parametrize("ms,expected_s", [
        (300, 1),     # API floor: sub-second becomes 1 s (unavoidable)
        (999, 1),
        (1000, 1),
        (1500, 1),    # regression: round() delivered 2 s (+33% over the cap)
        (1999, 1),
        (2400, 2),
        (15000, 15),
        (99999, 15),  # API ceiling
    ])
    def test_seconds_floor_never_exceed_cap(self, conn, ms, expected_s):
        conn.operate("shock", 50, ms)
        assert _queued_payload(conn)["Duration"] == expected_s

    def test_sub_second_floor_is_logged_once(self, conn):
        conn.operate("shock", 50, 300)
        conn.operate("shock", 50, 300)
        floor_logs = [m for m in conn.logged if "1 s" in m]
        assert len(floor_logs) == 1

    def test_intensity_clamped(self, conn):
        conn.operate("shock", 250, 1000)
        assert _queued_payload(conn)["Intensity"] == 100


class TestStaleJobDrop:
    def test_fresh_job_is_posted(self, conn, monkeypatch):
        fake = FakeRequests()
        monkeypatch.setattr(pishock_cloud, "requests", fake)
        assert conn._process((time.monotonic(), {"Op": 0})) is True
        assert len(fake.posts) == 1

    def test_stale_job_is_dropped_not_delivered(self, conn, monkeypatch):
        fake = FakeRequests()
        monkeypatch.setattr(pishock_cloud, "requests", fake)
        stale_ts = time.monotonic() - (JOB_TTL_S + 5.0)
        assert conn._process((stale_ts, {"Op": 0})) is False
        assert fake.posts == []            # the shock never went out
        assert any("stale" in m for m in conn.logged)


class TestResponseValidation:
    def test_error_body_is_logged(self, conn, monkeypatch):
        fake = FakeRequests(FakeResponse(200, "This code doesn't exist."))
        monkeypatch.setattr(pishock_cloud, "requests", fake)
        conn._process((time.monotonic(), {"Op": 0}))
        assert any("rejected" in m for m in conn.logged)

    def test_success_body_is_quiet(self, conn, monkeypatch):
        fake = FakeRequests(FakeResponse(200, "Operation Succeeded."))
        monkeypatch.setattr(pishock_cloud, "requests", fake)
        conn._process((time.monotonic(), {"Op": 0}))
        assert not any("rejected" in m for m in conn.logged)

    def test_non_200_is_logged(self, conn, monkeypatch):
        fake = FakeRequests(FakeResponse(403, "Forbidden"))
        monkeypatch.setattr(pishock_cloud, "requests", fake)
        conn._process((time.monotonic(), {"Op": 0}))
        assert any("rejected" in m for m in conn.logged)


class TestShutdownAndPrepare:
    def test_shutdown_drains_undelivered_jobs(self, conn):
        conn.operate("shock", 50, 1000)
        conn.operate("shock", 50, 1000)
        conn.shutdown()
        # Only the sentinel remains — no stale shock survives the session.
        assert conn._jobs.get_nowait() is None
        with pytest.raises(queue.Empty):
            conn._jobs.get_nowait()

    def test_prepare_drains_previous_session_backlog(self, conn):
        conn.operate("shock", 50, 1000)
        assert conn.prepare() is True
        with pytest.raises(queue.Empty):
            conn._jobs.get_nowait()

    def test_queue_full_drops_with_log(self, conn):
        for _ in range(pishock_cloud.QUEUE_MAX + 3):
            conn.operate("shock", 50, 1000)
        assert any("queue full" in m for m in conn.logged)
        assert conn._jobs.qsize() == pishock_cloud.QUEUE_MAX
