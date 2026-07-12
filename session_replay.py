"""Session replay — reconstruct a recorded session's OGB contact stream
so it can be fed back through the live routing pipeline for feel-tuning
without a partner present.

Sealed, pure parsing: no Qt, no threads, no store access. `load_frames`
reads a session JSONL (see docs/SESSION_LOGGING.md) and returns the
OGB events as time-ordered frames. To keep memory bounded on long
recordings (a 2-hour session is ~hundreds of MB of JSONL), frames hold
only the per-tick DELTA — the changed keys — exactly as logged, plus an
`is_full` flag on the periodic `ogb_snapshot` baselines. The replay
driver folds deltas onto a running state at playback time; storing a
full-state copy per frame would multiply memory by the key count.

Only the OGB stream is replayed — that's the contact input the router
turns into output. The `motor` / `bhaptics` lines are the recorded
OUTPUTS (what the router produced last time); replaying them would
defeat the purpose, which is to see what the CURRENT mode/chain settings
do with the same motion.
"""

import json
from typing import Any, Dict, List, Optional, Tuple


class ReplayFrame:
    """One logged OGB event: `t_ms` since session start, the event's
    `params` (a full snapshot when `is_full`, else the tick's delta), and
    whether it is an authoritative full snapshot (`ogb_snapshot`) that
    replaces the running state rather than merging into it."""

    __slots__ = ("t_ms", "params", "is_full")

    def __init__(self, t_ms: float, params: Dict[str, Any], is_full: bool):
        self.t_ms = t_ms
        self.params = params
        self.is_full = is_full


def load_frames(path) -> Tuple[Dict[str, Any], List[ReplayFrame]]:
    """Parse a session JSONL into `(header, frames)`.

    `header` is the session's header dict (empty if the file had none).
    `frames` is a time-ordered list of ReplayFrame carrying the raw OGB
    deltas / snapshots — NOT reconstructed full states (the driver folds
    them at playback). Frames with no OGB activity are omitted.

    Fully defensive: unreadable file, malformed lines, or missing OGB
    stream all yield `({}, [])` rather than raising — a corrupt log must
    never crash the replay UI. Malformed individual lines are skipped."""
    header: Dict[str, Any] = {}
    frames: List[ReplayFrame] = []
    seen_ogb = False
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                etype = event.get("type")
                if etype == "header":
                    header = event
                elif etype in ("ogb_snapshot", "ogb"):
                    params = event.get("params")
                    if isinstance(params, dict) and params:
                        seen_ogb = True
                        frames.append(ReplayFrame(
                            _t(event), dict(params),
                            is_full=(etype == "ogb_snapshot")))
    except OSError:
        return {}, []
    if not seen_ogb:
        return header, []
    frames.sort(key=lambda fr: fr.t_ms)
    return header, frames


def replay_duration_ms(frames: List[ReplayFrame]) -> float:
    return frames[-1].t_ms if frames else 0.0


def _t(event: Dict[str, Any]) -> float:
    try:
        return max(0.0, float(event.get("t_ms", 0.0)))
    except (TypeError, ValueError):
        return 0.0
