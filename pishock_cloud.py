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
        self._jobs: "queue.Queue[Optional[dict]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop = threading.Event()

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
        self._ensure_worker()
        return True

    def operate(self, op: str, intensity: int, duration_ms: int) -> None:
        if not _REQUESTS_AVAILABLE:
            return
        self._ensure_worker()
        # Cloud needs whole-second duration (1-15) and 1-100 intensity.
        duration_s = max(1, min(15, round(int(duration_ms) / 1000.0)))
        intensity = max(1, min(100, int(intensity)))
        self._jobs.put({
            "Username": self._username,
            "Apikey": self._apikey,
            "Code": self._code,
            "Name": self._name,
            "Op": CLOUD_OP_CODES.get(op, CLOUD_OP_CODES[OP_SHOCK]),
            "Intensity": intensity,
            "Duration": duration_s,
        })

    def end(self) -> None:
        # The cloud API has no clean early-stop; the shock simply runs out its
        # (short, capped) duration. No-op rather than firing another request.
        return

    def shutdown(self) -> None:
        self._stop.set()
        self._jobs.put(None)  # unblock the worker

    # ---- worker ------------------------------------------------------
    def _ensure_worker(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="PiShockCloud")
        self._worker.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._jobs.get()
            if job is None:
                break
            try:
                requests.post(APIOPERATE_URL, json=job, timeout=HTTP_TIMEOUT_S)
            except Exception as e:
                self._log(f"PiShock cloud POST failed: {e}")
