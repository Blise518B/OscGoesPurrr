"""Pure collect-and-coalesce phase of the controller's thread_queue drain.

Extracted from main.process_async_queue so its load-bearing invariants are
unit-testable without importing the app:

  * consecutive ``osc_haptic_update`` messages coalesce latest-wins per
    ``(device, motor)`` — only the newest target matters to hardware;
  * the relative order of every OTHER event is preserved (sequence matters
    for e.g. ``connection_status`` -> ``devices_found``);
  * at most ``cap`` messages are drained per call — leftovers stay queued
    for the next tick so an OSC storm can't wedge the UI thread;
  * malformed messages are passed through untouched (the caller's dispatch
    loop skips non-tuples), never raised on.
"""

import queue as _queue
from typing import Any, Dict, List, Tuple


def drain_and_coalesce(q: "_queue.Queue",
                       cap: int) -> Tuple[List[Any], Dict[tuple, tuple]]:
    """Drain up to ``cap`` messages from ``q``.

    Returns ``(ordered_events, haptic_latest)`` where ``ordered_events``
    preserves arrival order of all non-haptic messages and
    ``haptic_latest`` maps ``(device, motor) -> (device, value, motor)``
    holding only each motor's newest target.
    """
    haptic_latest: Dict[tuple, tuple] = {}
    ordered_events: List[Any] = []
    drained = 0
    try:
        while drained < cap:
            msg = q.get_nowait()
            drained += 1
            if (isinstance(msg, tuple) and len(msg) == 2
                    and msg[0] == "osc_haptic_update"):
                device_name, val_float, motor_index = msg[1]
                haptic_latest[(device_name, motor_index)] = (
                    device_name, val_float, motor_index)
                continue
            ordered_events.append(msg)
    except _queue.Empty:
        pass
    return ordered_events, haptic_latest
