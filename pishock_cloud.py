# pishock_cloud.py
# PiShock cloud HTTP transport (works anywhere; needs a pishock.com account +
# share code + internet). Coarser than serial: duration is whole seconds 1-15
# and the endpoint is rate-limited.
#
#   POST https://do.pishock.com/api/apioperate/
#   {"Username","Apikey","Code","Name","Op"(0/1/2),"Intensity"(1-100),
#    "Duration"(1-15 seconds)}
#
# POSTs run on a single worker thread so the network round-trip never blocks
# the engine/router (latency budget: never await a device ack on the hot loop).

import queue
import threading
import time
from typing import Callable, Optional

from pishock_connection import CLOUD_OP_CODES, MODE_CLOUD, OP_SHOCK

try:
    import requests
    _REQUESTS_AVAILABLE = True
except Exception:
    requests = None  # type: ignore
    _REQUESTS_AVAILABLE = False

APIOPERATE_URL = "https://do.pishock.com/api/apioperate/"
HTTP_TIMEOUT_S = 10.0
# A queued shock older than this is dropped, not delivered: after a network
# stall the person must NOT receive a burst of stale shocks for contacts
# from many seconds ago (delivered back-to-back at HTTP RTT spacing, far
# under the engine's min-interval floor). Deliberately small: on a link so
# slow that most events expire behind an in-flight POST, delivering shocks
# many seconds late would be worse than dropping them — for this device,
# timeliness IS the safety property. (Age is measured at dequeue; the POST
# itself can still add up to one RTT on top.)
JOB_TTL_S = 3.0
QUEUE_MAX = 8
# apioperate reports failures in a 200-response body; success looks like
# "Operation Succeeded." (or "Operation Attempted." for a paused shocker).
_SUCCESS_MARKERS = ("Operation Succeeded", "Operation Attempted")


class PiShockCloudConnection:
    """Cloud apioperate transport. Serializes operations onto one worker thread
    so the engine never blocks on HTTP. Safety clamping is done upstream in
    PiShockEngine; this layer additionally coerces values into the cloud API's
    accepted ranges (1-100 intensity, 1-15 s duration)."""

    mode = MODE_CLOUD

    def __init__(self, log: Optional[Callable[[str], None]] = None):
        self._log = log or (lambda _m: None)
        self._username = ""
        self._apikey = ""
        self._code = ""
        self._name = "OscGoesPurrr"
        # Items are (enqueue_monotonic, payload) tuples, or None (sentinel).
        self._jobs: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=QUEUE_MAX)
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._warned_duration_floor = False

    @property
    def status_label(self) -> str:
        return "PiShock (cloud)"

    @property
    def is_available(self) -> bool:
        return _REQUESTS_AVAILABLE

    def configure(self, config: dict) -> None:
        c = config or {}
        self._username = str(c.get("username", "") or "").strip()
        self._apikey = str(c.get("apikey", "") or "").strip()
        self._code = str(c.get("code", "") or "").strip()
        self._name = str(c.get("name", "") or "OscGoesPurrr").strip() or "OscGoesPurrr"

    def prepare(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            self._log("PiShock cloud: requests not installed")
            return False
        if not (self._username and self._apikey and self._code):
            self._log("PiShock cloud: username / API key / share code not set")
            return False
        # Never carry a previous session's undelivered shocks into this one.
        self._drain()
        # prepare() is the ONLY legitimate re-arm point after shutdown().
        self._stop.clear()
        self._ensure_worker()
        return True

    def operate(self, op: str, intensity: int, duration_ms: int) -> None:
        if not _REQUESTS_AVAILABLE:
            return
        if self._stop.is_set():
            # shutdown() already ran: never enqueue (or resurrect a worker
            # for) a shock after the session ended. prepare() re-arms.
            return
        self._ensure_worker()
        # Cloud needs whole-second duration (1-15) and 1-100 intensity.
        # FLOOR the seconds so the delivered duration never exceeds the
        # engine-clamped value (1500 ms must not become 2 s); the API's own
        # 1 s minimum is the only unavoidable inflation, and we tell the
        # user about it once.
        duration_ms = int(duration_ms)
        duration_s = max(1, min(15, duration_ms // 1000))
        if duration_ms < 1000 and not self._warned_duration_floor:
            self._warned_duration_floor = True
            self._log("PiShock cloud: durations under 1 s are delivered as "
                      "1 s (cloud API minimum)")
        intensity = max(1, min(100, int(intensity)))
        payload = {
            "Username": self._username,
            "Apikey": self._apikey,
            "Code": self._code,
            "Name": self._name,
            "Op": CLOUD_OP_CODES.get(op, CLOUD_OP_CODES[OP_SHOCK]),
            "Intensity": intensity,
            "Duration": duration_s,
        }
        try:
            self._jobs.put_nowait((time.monotonic(), payload))
        except queue.Full:
            self._log("PiShock cloud: queue full (network backlog) — "
                      "dropping this event")

    def end(self) -> None:
        # The cloud API has no clean early-stop; the shock simply runs out its
        # (short, capped) duration. No-op rather than firing another request.
        return

    def shutdown(self) -> None:
        self._stop.set()
        # Drop everything undelivered — a stale shock must never survive
        # into (or fire during) the next connect.
        self._drain()
        try:
            self._jobs.put_nowait(None)  # unblock the worker
        except queue.Full:
            pass

    # ---- worker ------------------------------------------------------
    def _drain(self) -> None:
        try:
            while True:
                self._jobs.get_nowait()
        except queue.Empty:
            pass

    def _ensure_worker(self) -> None:
        if self._stop.is_set():
            return  # shut down; only prepare() may re-arm
        if self._worker is not None and self._worker.is_alive():
            return
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="PiShockCloud")
        self._worker.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._jobs.get()
            if item is None:
                break
            self._process(item)

    def _process(self, item: tuple) -> bool:
        """POST one queued job unless it has gone stale or the transport was
        shut down. Returns True when the request was actually attempted."""
        if self._stop.is_set():
            return False
        enqueued_ts, payload = item
        age = time.monotonic() - enqueued_ts
        if age > JOB_TTL_S:
            self._log(f"PiShock cloud: dropped a {age:.1f}s-old queued event "
                      "(network backlog) — stale shocks are not delivered")
            return False
        try:
            resp = requests.post(APIOPERATE_URL, json=payload,
                                 timeout=HTTP_TIMEOUT_S)
            body = (resp.text or "").strip()
            if resp.status_code != 200 or not any(
                    m in body for m in _SUCCESS_MARKERS):
                self._log("PiShock cloud: operation rejected "
                          f"(HTTP {resp.status_code}: {body[:120]})")
        except Exception as e:
            self._log(f"PiShock cloud POST failed: {e}")
        return True
