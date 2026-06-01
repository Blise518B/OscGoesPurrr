"""VR session logger — records router intermediates, OGB SPS inputs,
and bHaptics dot outputs to per-session JSONL files for later analysis.

Design lock: see docs/SESSION_LOGGING.md. The short version:

* Sealed engine — `SessionLogger` takes/returns primitives only. The
  controller facade ferries data in and out; nothing Qt or routing-
  specific lives in here.
* The hot path (router tick) calls `log_motor`, `log_ogb`,
  `log_bhaptics` from the routing thread. These just append to an
  in-memory queue; a dedicated worker thread serialises to JSON and
  writes to disk. The router never blocks on I/O.
* OGB change-diff happens *inside* the worker (single-threaded
  access to the diff state), so callers always pass the full current
  OGB snapshot — they don't track previous state.
* Back-pressure: if the queue grows past `_QUEUE_HIGH_WATER` the
  logger drops the oldest events in a batch and emits a `dropped`
  marker. Better than OOM if disk can't keep up at 90 Hz.
"""

import json
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# Module-level tunables — exposed for tests to override.
FLUSH_INTERVAL_S = 1.0
QUEUE_HIGH_WATER = 10000          # ~110 ms of 90 Hz × ~10 motors
DROP_BATCH_SIZE = 1000            # how many to drop at once when over high-water
OGB_SNAPSHOT_INTERVAL_S = 30.0    # periodic full snapshot for replay correctness
FLOAT_DECIMALS = 4
WORKER_JOIN_TIMEOUT_S = 5.0
SESSION_FILE_PREFIX = "session_"
SESSION_FILE_SUFFIX = ".jsonl"


# Sentinel for "key not present in previous snapshot". A dedicated object
# (not None) so it can't collide with an OGB value that's legitimately
# None or False.
_MISSING = object()


def _values_differ(a: Any, b: Any) -> bool:
    """True if `a` and `b` represent meaningfully-different OGB values.

    Floats compare with a tiny tolerance so the change-diff doesn't
    spam events on imperceptible float jitter from VRChat's
    contact-receiver values. Booleans + strings compare exactly."""
    if a is _MISSING:
        return True
    if isinstance(a, float) and isinstance(b, (float, int)):
        try:
            return abs(float(a) - float(b)) > 1e-4
        except (TypeError, ValueError):
            return True
    if isinstance(b, float) and isinstance(a, (float, int)):
        try:
            return abs(float(a) - float(b)) > 1e-4
        except (TypeError, ValueError):
            return True
    return a != b


def ogb_diff(prev: Dict[str, Any], curr: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function: return only the keys whose values differ from
    `prev`. Keys missing from `curr` are not reported as deleted —
    there's no representation for that in the schema, and OGB keys
    don't typically vanish mid-session."""
    out: Dict[str, Any] = {}
    for k, v in curr.items():
        old = prev.get(k, _MISSING)
        if _values_differ(old, v):
            out[k] = v
    return out


class SessionLogger:
    """Append-only JSONL session writer. One instance per app process;
    `start()` opens a new session file, `stop()` closes it. Multiple
    sessions over the lifetime of one process is supported."""

    def __init__(self, sessions_dir):
        self._dir = Path(sessions_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        # Transition lock (only held during start / stop). Hot-path
        # log_* methods read `_running` without locking — see class
        # docstring for race-condition analysis.
        self._lock = threading.Lock()
        self._queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop_signal = threading.Event()
        self._file = None
        self._session_id: Optional[str] = None
        self._session_path: Optional[Path] = None
        self._started_at_unix: Optional[float] = None
        # Hot-path-readable; set under lock by start/stop. A stale True
        # read just causes one extra enqueue (drained on stop); a stale
        # False read just drops one event. Both are harmless.
        self._running = False
        # Counters owned by the worker thread.
        self._event_count = 0
        self._dropped_count = 0
        # OGB change-diff state — only the worker thread touches these.
        self._ogb_prev: Dict[str, Any] = {}
        self._ogb_last_full_snapshot_t_ms: float = -1e18

    # ---- properties ----

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_session(self) -> Optional[Dict[str, Any]]:
        """Live state for the UI. Returns None when no session is open."""
        if not self._running or self._session_id is None:
            return None
        try:
            size = os.path.getsize(self._session_path) if self._session_path else 0
        except OSError:
            size = 0
        started = self._started_at_unix or time.time()
        return {
            "id": self._session_id,
            "path": str(self._session_path) if self._session_path else "",
            "started_at_unix": started,
            "duration_s": max(0.0, time.time() - started),
            "event_count": self._event_count,
            "dropped_count": self._dropped_count,
            "file_size_bytes": size,
        }

    # ---- lifecycle ----

    def start(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Open a new session file, write the header, spawn the worker.
        Returns the session id (filename stem, no extension).

        Raises RuntimeError if a session is already running. The caller
        is expected to `stop()` before starting another."""
        with self._lock:
            if self._running:
                raise RuntimeError("Session already running — call stop() first")
            now = datetime.now()
            base_id = SESSION_FILE_PREFIX + now.strftime("%Y-%m-%d_%H-%M-%S")
            session_id = base_id
            file_path = self._dir / (session_id + SESSION_FILE_SUFFIX)
            # Same-second restart collision: bump a numeric suffix until
            # we find a free name. The wall-clock format gives 1 s
            # resolution so a quick app restart can otherwise collide.
            suffix = 1
            while file_path.exists():
                session_id = f"{base_id}_{suffix}"
                file_path = self._dir / (session_id + SESSION_FILE_SUFFIX)
                suffix += 1
            self._file = open(file_path, "w", encoding="utf-8")
            self._session_id = session_id
            self._session_path = file_path
            self._started_at_unix = time.time()
            self._event_count = 0
            self._dropped_count = 0
            self._ogb_prev = {}
            self._ogb_last_full_snapshot_t_ms = -1e18
            # Drain any stale events left over from a prior session
            # (shouldn't happen in normal flow, defensive against
            # crash-recovery scenarios).
            self._drain_queue_silently()
            header = {
                "type": "header",
                "schema": 1,
                "started_at": now.isoformat(timespec="seconds"),
                "started_at_unix": self._started_at_unix,
            }
            if metadata:
                # Merge metadata onto the header. Defensive copy so the
                # caller's dict can't mutate our written record.
                for k, v in metadata.items():
                    if k not in ("type", "schema", "started_at", "started_at_unix"):
                        header[k] = v
            self._write_line(header)
            self._file.flush()
            self._stop_signal.clear()
            self._worker = threading.Thread(
                target=self._worker_loop, daemon=True, name="SessionLoggerWriter"
            )
            self._running = True
            self._worker.start()
            return session_id

    def stop(self) -> None:
        """Signal the worker to drain, wait for it, write the footer,
        close the file. Idempotent — calling twice is a no-op."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            worker = self._worker
            self._stop_signal.set()
        # Outside the lock: wait for worker to drain everything queued
        # before stop() was called.
        if worker is not None:
            worker.join(timeout=WORKER_JOIN_TIMEOUT_S)
        # Footer + close happen after the worker has stopped so we
        # know nothing else is writing to the file.
        with self._lock:
            try:
                footer = {
                    "type": "footer",
                    "ended_at": datetime.now().isoformat(timespec="seconds"),
                    "ended_at_unix": time.time(),
                    "duration_s": (
                        time.time() - self._started_at_unix
                        if self._started_at_unix else 0.0
                    ),
                    "event_count": self._event_count,
                    "dropped_count": self._dropped_count,
                }
                if self._file is not None:
                    self._file.write(json.dumps(footer) + "\n")
                    self._file.flush()
                    self._file.close()
            except Exception:
                pass
            self._file = None
            self._worker = None
            self._session_id = None
            self._session_path = None
            self._started_at_unix = None

    # ---- hot-path log_* methods ----

    def log_motor(self, t_ms: float, device: str, motor: int,
                  d_raw: float, s_raw: float,
                  d_shaped: float, s_shaped: float,
                  mixed: float, out: float) -> None:
        if not self._running:
            return
        event = {
            "type":     "motor",
            "t_ms":     round(float(t_ms), 1),
            "device":   str(device),
            "motor":    int(motor),
            "d_raw":    round(float(d_raw),    FLOAT_DECIMALS),
            "s_raw":    round(float(s_raw),    FLOAT_DECIMALS),
            "d_shaped": round(float(d_shaped), FLOAT_DECIMALS),
            "s_shaped": round(float(s_shaped), FLOAT_DECIMALS),
            "mixed":    round(float(mixed),    FLOAT_DECIMALS),
            "out":      round(float(out),      FLOAT_DECIMALS),
        }
        self._enqueue(event)

    def log_ogb(self, t_ms: float, current_ogb_snapshot: Dict[str, Any]) -> None:
        """Pass the *full current OGB-param snapshot*; the logger does
        change-diff internally so callers don't track previous state."""
        if not self._running or not current_ogb_snapshot:
            return
        # Wrap in an internal-type envelope so the worker can route it
        # through the diff machinery before writing.
        self._enqueue({
            "_internal_type": "ogb_raw_snapshot",
            "t_ms":           round(float(t_ms), 1),
            "snapshot":       dict(current_ogb_snapshot),
        })

    def log_bhaptics(self, t_ms: float,
                     position_snapshot: Dict[str, List[int]]) -> None:
        """Emit one event per position that has any non-zero dot. Positions
        whose dots are all zero are dropped — keeps file size sane when
        the suit is idle."""
        if not self._running or not position_snapshot:
            return
        t_ms = round(float(t_ms), 1)
        for position, values in position_snapshot.items():
            if not values:
                continue
            # Build dot dict keyed by 0-based index, skipping zeros.
            dots: Dict[str, int] = {}
            for i, v in enumerate(values):
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                if iv:
                    dots[str(i)] = iv
            if not dots:
                continue
            self._enqueue({
                "type":     "bhaptics",
                "t_ms":     t_ms,
                "position": str(position),
                "dots":     dots,
            })

    # ---- internal ----

    def _enqueue(self, event: Dict[str, Any]) -> None:
        """Back-pressure aware enqueue. If the queue is above the
        high-water mark, drop a batch of oldest events and record a
        `dropped` marker so the user can see the loss in the file."""
        if self._queue.qsize() > QUEUE_HIGH_WATER:
            dropped = 0
            try:
                for _ in range(DROP_BATCH_SIZE):
                    self._queue.get_nowait()
                    dropped += 1
            except queue.Empty:
                pass
            if dropped:
                self._queue.put_nowait({
                    "_internal_type": "dropped_marker",
                    "count":          dropped,
                })
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # The default Queue is unbounded so this can't happen in
            # practice; left explicit for defensiveness.
            pass

    def _drain_queue_silently(self) -> None:
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            return

    def _worker_loop(self) -> None:
        """Single-threaded drain loop. Owns all writes to self._file
        and all mutations of _ogb_prev / _event_count / _dropped_count."""
        last_flush = time.time()
        while True:
            try:
                event = self._queue.get(timeout=0.1)
            except queue.Empty:
                event = None
            if event is not None:
                self._process_event(event)
            now = time.time()
            if now - last_flush >= FLUSH_INTERVAL_S:
                try:
                    if self._file is not None:
                        self._file.flush()
                except OSError:
                    pass
                last_flush = now
            if self._stop_signal.is_set() and self._queue.empty():
                # Final flush before exit so the footer write in stop()
                # has clean state to land into.
                try:
                    if self._file is not None:
                        self._file.flush()
                except OSError:
                    pass
                return

    def _process_event(self, event: Dict[str, Any]) -> None:
        internal = event.pop("_internal_type", None)
        if internal == "ogb_raw_snapshot":
            self._handle_ogb_raw(event["t_ms"], event["snapshot"])
            return
        if internal == "dropped_marker":
            self._dropped_count += int(event.get("count", 0))
            self._write_line({
                "type":  "dropped",
                "count": int(event.get("count", 0)),
            })
            return
        self._write_line(event)

    def _handle_ogb_raw(self, t_ms: float, snapshot: Dict[str, Any]) -> None:
        # Periodic full snapshot so a viewer can seek to any time-point
        # without replaying every delta from session start.
        elapsed_ms_since_full = t_ms - self._ogb_last_full_snapshot_t_ms
        if elapsed_ms_since_full >= (OGB_SNAPSHOT_INTERVAL_S * 1000.0):
            self._ogb_last_full_snapshot_t_ms = t_ms
            self._ogb_prev = dict(snapshot)
            self._write_line({
                "type":   "ogb_snapshot",
                "t_ms":   t_ms,
                "params": dict(snapshot),
            })
            return
        diff = ogb_diff(self._ogb_prev, snapshot)
        if diff:
            # Update prev only with the changed keys' new values —
            # missing-from-curr keys stay as-is in prev so a transient
            # OGB dropout doesn't trigger a "change" event when the
            # key reappears.
            for k, v in diff.items():
                self._ogb_prev[k] = v
            self._write_line({
                "type":   "ogb",
                "t_ms":   t_ms,
                "params": diff,
            })

    def _write_line(self, event: Dict[str, Any]) -> None:
        if self._file is None:
            return
        try:
            self._file.write(json.dumps(event) + "\n")
            self._event_count += 1
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Static library — no engine state needed, just disk operations.
    # ------------------------------------------------------------------

    @staticmethod
    def list_sessions(sessions_dir) -> List[Dict[str, Any]]:
        """Return one dict per session file in `sessions_dir`, newest
        first. Each dict has id / path / size_bytes / mtime_unix plus
        whatever header + footer fields are parseable from the file
        (started_at, duration_s, event_count, profile, etc.)."""
        d = Path(sessions_dir)
        if not d.is_dir():
            return []
        out: List[Dict[str, Any]] = []
        for f in d.glob(f"{SESSION_FILE_PREFIX}*{SESSION_FILE_SUFFIX}"):
            try:
                stat = f.stat()
            except OSError:
                continue
            entry: Dict[str, Any] = {
                "id":         f.stem,
                "path":       str(f),
                "size_bytes": stat.st_size,
                "mtime_unix": stat.st_mtime,
            }
            entry.update(SessionLogger._parse_session_metadata(f))
            out.append(entry)
        out.sort(key=lambda e: e.get("mtime_unix", 0.0), reverse=True)
        return out

    @staticmethod
    def _parse_session_metadata(path: Path) -> Dict[str, Any]:
        """Pull header + footer fields from a JSONL session file. Header
        is the first line (cheap); footer is the last line (we tail the
        file from the end to avoid reading the whole motor stream just
        to display a file list)."""
        meta: Dict[str, Any] = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                first = f.readline()
                if first:
                    try:
                        h = json.loads(first)
                        if isinstance(h, dict) and h.get("type") == "header":
                            for k in ("started_at", "started_at_unix",
                                       "profile", "avatar_name", "router_hz"):
                                if k in h:
                                    meta[k] = h[k]
                    except json.JSONDecodeError:
                        pass
            # Tail the file for the footer. 4KB is plenty for one JSON line.
            try:
                size = path.stat().st_size
                with open(path, "rb") as f:
                    f.seek(max(0, size - 4096))
                    tail = f.read().decode("utf-8", errors="ignore")
                last_nonempty = ""
                for line in tail.splitlines():
                    if line.strip():
                        last_nonempty = line
                if last_nonempty:
                    try:
                        footer = json.loads(last_nonempty)
                        if isinstance(footer, dict) and footer.get("type") == "footer":
                            for k in ("ended_at", "ended_at_unix",
                                       "duration_s", "event_count",
                                       "dropped_count"):
                                if k in footer:
                                    meta[k] = footer[k]
                    except json.JSONDecodeError:
                        pass
            except OSError:
                pass
        except OSError:
            pass
        return meta

    @staticmethod
    def delete_session(sessions_dir, session_id: str) -> bool:
        """Remove a single session file by id. Returns True if a file
        was deleted, False if no matching file existed."""
        path = Path(sessions_dir) / (str(session_id) + SESSION_FILE_SUFFIX)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    @staticmethod
    def delete_all_sessions(sessions_dir) -> int:
        """Remove every session file. Returns the number deleted."""
        d = Path(sessions_dir)
        if not d.is_dir():
            return 0
        n = 0
        for f in d.glob(f"{SESSION_FILE_PREFIX}*{SESSION_FILE_SUFFIX}"):
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
        return n

    @staticmethod
    def prune(sessions_dir, keep_n: int) -> int:
        """Keep the `keep_n` newest session files (by mtime); delete the
        rest. Returns the number deleted. No-op when fewer files exist
        than the limit."""
        d = Path(sessions_dir)
        if not d.is_dir() or keep_n < 0:
            return 0
        try:
            files = list(d.glob(f"{SESSION_FILE_PREFIX}*{SESSION_FILE_SUFFIX}"))
        except OSError:
            return 0
        if len(files) <= keep_n:
            return 0
        try:
            files.sort(key=lambda p: p.stat().st_mtime)
        except OSError:
            return 0
        to_delete = files[: len(files) - keep_n]
        n = 0
        for f in to_delete:
            try:
                f.unlink()
                n += 1
            except OSError:
                pass
        return n
