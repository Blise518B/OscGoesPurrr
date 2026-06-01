# Session Logging — design lock

VR sessions are recorded to disk so the user can analyze them later
and tune profile parameters with confidence ("did Speed actually
fire on that contact?", "is my Depth curve clipping at low input?").

This document locks the decisions for that feature. It exists so
future-you can reason about the on-disk format and the data flow
without re-reading the engine code.

## Scope

What gets logged, per the user's call:

* **Router intermediates** — per motor, per router tick: the same six
  values the Tune view streams (`d_raw`, `s_raw`, `d_shaped`,
  `s_shaped`, `mixed`, `out`).
* **OGB SPS inputs** — the raw `OGB/Orf/...` and `OGB/Pen/...`
  parameters from `parameter_store`. With change-diff to avoid
  re-logging every unchanged key every tick.
* **bHaptics dot outputs** — per-position dot intensities after
  anti-stuck / overrides (the same dict the debug grid reads).

Not in scope (v1):

* Per-toy commands actually sent over Buttplug. The router's `out`
  is what becomes the toy command after the per-toy intensity %
  multiplier in the engine; the engine layer's quantization is
  hardware-specific. Recording the engine boundary is a fine
  follow-up but isn't needed for parameter tuning.
* Mic / camera / world state. None of it crosses the OSC boundary
  this app cares about.
* Anything sensitive that isn't already in `parameter_store` or
  the router. The logger is a read-only observer of state we
  already have in memory.

## Rate

Logger writes at the **router tick rate** — currently 90 Hz default,
configurable via `router_poll_rate_hz`. No separate `log_hz`
setting; the logger inherits whatever cadence the user picked for
routing. This gives the highest possible resolution at no extra
sample-aliasing cost (the values were freshly computed for that
tick anyway).

Implication: a 2-hour session with 4 active motors and a full vest
loaded weighs in around **~875 MB** raw JSONL. That's accepted as
fine for dev-style use; retention pruning + manual deletion keep
disk usage bounded.

If file size becomes a problem in practice, the cheapest follow-up
is gzip-rotation on session stop (`.jsonl` → `.jsonl.gz`). Both
Python and pandas read gzipped JSONL transparently. Out of scope
for v1.

## File format

One JSONL file per session, line-delimited JSON. Append-only,
human-readable, opens in any text editor, trivially loaded by
`pandas.read_json(path, lines=True)`.

Filename: `session_YYYY-MM-DD_HH-MM-SS.jsonl`. The timestamp is
local wall-clock time at session start (matches the user's intuition
when scanning a folder list).

Event types, in encounter order:

### `header` — first line, written at start

```jsonc
{
  "type":              "header",
  "schema":            1,
  "started_at":        "2026-05-23T14:30:00",
  "started_at_unix":   1747834200.123,
  "avatar_id":         "avtr_xxx",          // null if unknown
  "avatar_name":       "...",                // null if unknown
  "profile":           "Default",
  "router_hz":         90,
  "toys": [
    {"name": "Lovense Hush", "motor_count": 1, "motor_kinds": ["vibrate"]}
  ],
  "bhaptics_devices":  ["VestFront", "VestBack"]
}
```

### `motor` — per router tick, one event per active motor

```jsonc
{
  "type":     "motor",
  "t_ms":     1234,                    // ms since session start
  "device":   "Lovense Hush",
  "motor":    0,
  "d_raw":    0.7,
  "s_raw":    0.0,
  "d_shaped": 0.7,
  "s_shaped": 0.0,
  "mixed":    0.7,
  "out":      0.65
}
```

Floats rounded to 4 decimals to keep file size bounded without
losing useful precision (mixer inputs are 0-1, three decimals is the
toy's quantization step, the fourth is safety margin).

### `ogb` — per tick, only changed keys since last log

```jsonc
{
  "type":   "ogb",
  "t_ms":   1234,
  "params": {
    "OGB/Orf/Boob/TouchSelf":      0.6,
    "OGB/Orf/Boob/TouchSelfClose": true
  }
}
```

Most OGB params are mostly unchanged across ticks. Logging only the
delta keeps the file size down by an order of magnitude versus a
full snapshot every tick.

To allow a future viewer to seek to any time-point cleanly, the
logger also emits a **full OGB snapshot** every ~30 seconds (a
`type: "ogb_snapshot"` event with every current OGB param). Cheap
in the streaming case, makes random-access loading possible.

### `bhaptics` — per tick, one event per position with non-zero dots

```jsonc
{
  "type":     "bhaptics",
  "t_ms":     1234,
  "position": "VestFront",
  "dots":     {"5": 80, "6": 80, "9": 40}     // only non-zero dots
}
```

Positions whose dots are all zero are skipped — no event emitted.
Dot values are the post-anti-stuck output intensities (0-100), same
as what `bhaptics_router.get_snapshot()` returns.

### `footer` — last line, flushed on stop

```jsonc
{
  "type":         "footer",
  "ended_at":     "2026-05-23T15:30:01",
  "ended_at_unix":1747837801.456,
  "duration_s":   3601.3,
  "event_count":  8421342
}
```

If the app crashes mid-session there's no footer; a viewer should
treat the absence as "session ended abruptly" and report the last
`t_ms` it saw as the effective end time.

## Storage

* Folder: `%APPDATA%/OscGoesPurrr/sessions/` (Windows). Same root
  as the rest of the per-user state (`profiles.json`,
  `app_settings.json`, etc.). Added to `settings/_paths.py`
  alongside the other constants.
* Per-session file lives in that folder verbatim — no
  per-session subdirectory.
* No external compression for v1.

## Retention

* Settings field `retention: int` (default 20) — the maximum number
  of session files kept on disk.
* Pruning runs **on each session start** (not on app shutdown — that
  path is unreliable; not on a timer — wasted work). Order: by file
  mtime, oldest first.
* Pruning runs even if the user has session logging disabled, so
  toggling it on/off doesn't surface stale files.
* A "Delete all" button in the UI clears the entire folder
  (confirmation dialog so the user can't fat-finger it).

## Concurrency

The router tick is the hot path — it must never block on disk I/O.

Design:

* `SessionLogger.start()` opens the file and spawns a worker thread
  that drains an in-memory queue.
* `SessionLogger.log_motor / log_ogb / log_bhaptics` from the
  routing thread just append to the queue (cheap, lock-protected).
* The worker drains the queue, serialises to JSONL, writes to disk.
  Flushes periodically (every ~1 s) so a crash doesn't lose the
  last few minutes.
* `SessionLogger.stop()` signals the worker to drain, writes the
  footer, and joins.
* If the queue grows past a high-water mark (back-pressure: disk
  too slow for the router rate), the logger drops the oldest
  events in the queue and emits a `type: "dropped"` event with a
  count. Better to lose a few sample ticks than to OOM.

## Settings schema

A new `settings/sessions.py` with `SessionSettingsManager`. JSON
schema:

```jsonc
{
  "enabled":    false,        // master toggle; opt-in
  "auto_start": false,        // start a session on app launch?
  "retention":  20            // max files kept on disk
}
```

`log_hz` is **deliberately absent** — logging always runs at the
router rate.

## Engine API

```python
class SessionLogger:
    def __init__(self, sessions_dir: Path): ...

    def start(self, metadata: dict) -> str:
        """Open a new session file, write the header, spawn worker.
        Returns the session id (the timestamped filename stem)."""

    def stop(self) -> None:
        """Drain queue, write footer, close file. Idempotent."""

    def log_motor(self, t_ms: float, device: str, motor: int,
                  d_raw, s_raw, d_shaped, s_shaped, mixed, out): ...

    def log_ogb(self, t_ms: float, params: Dict[str, Any]) -> None:
        """`params` is the *full current OGB-key snapshot*; the
        logger handles change-diff internally so callers don't have
        to track previous state."""

    def log_bhaptics(self, t_ms: float, snapshot: Dict[str, List[int]]):
        """`snapshot` is {position: [dot intensities]}; emitted as
        per-position events with non-zero dots only."""

    @property
    def is_running(self) -> bool: ...

    @property
    def current_session(self) -> Optional[dict]:
        """Live state for the UI: {id, started_at, duration_s,
        event_count, file_size_bytes}."""

    # Library queries (file system, not engine state)
    @staticmethod
    def list_sessions(sessions_dir: Path) -> List[dict]: ...

    @staticmethod
    def delete_session(sessions_dir: Path, session_id: str) -> None: ...

    @staticmethod
    def delete_all_sessions(sessions_dir: Path) -> int: ...

    @staticmethod
    def prune(sessions_dir: Path, keep_n: int) -> int: ...
```

All public methods take/return primitives (paths, dicts, lists of
str / int / float). The engine is a sealed box — no Qt, no
controller, no settings-manager reference inside. The controller
facade is responsible for ferrying primitives in and out.

## Router integration

Two new hooks, one each on `motor_router` and `bhaptics_router`,
mirroring the pattern of the existing Tune subscription:

```python
# motor_router.py
def set_session_broadcast(callback):
    """Subscribe to *every* motor's intermediates per tick.
    Distinct from the Tune subscription which is per-motor.
    `callback(device_name, motor_idx, intermediates_dict)`.
    None disables."""

# bhaptics_router.py
def set_session_broadcast(callback):
    """Subscribe to the per-tick dot snapshot.
    `callback(snapshot_dict)`.
    None disables."""
```

OGB params are polled by the controller's routing tick, which already
calls `parameter_store.snapshot()` — the logger just receives the
existing snapshot.

## Cuts

| Cut | Scope |
|---|---|
| 1 | Lock decisions in this file (you are here). |
| 2 | `SessionLogger` engine + `SessionSettingsManager` + tests. Dead code, no router/UI integration. |
| 3 | Router hooks + `SessionsFacade` + main-loop wiring + OGB snapshot poll. |
| 4 | Sessions tab UI in Settings view. |

In-app viewer is **not** in scope. JSONL files are easy to load in
pandas / Excel for now.

## Open questions deferred

* **gzip rotation on stop** — defer until file size becomes painful.
* **In-app viewer** — defer; user explicitly opted out of v1.
* **Logging the engine boundary (post-quantization Buttplug commands)**
  — interesting for hardware-specific debugging, but not for profile
  tuning. Defer.
* **Compressing OGB events further** (delta encoding floats, etc.)
  — current change-diff is already a big saving; revisit if needed.
