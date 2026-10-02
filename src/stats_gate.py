"""Which activity counts as playing — the statistics' noise gate.

An avatar with haptic contacts keeps producing stray signals while nobody
is playing: a contact brushing past, a lone stroke, a zone flickering on,
and strokes counted with no zone in contact at all (seen for hours on an
avatar nobody was touching). Counted as they come, those turn every idle
evening into a "session" and salt the totals with thrusts that never
happened. So:

* **While a toy is running, everything counts.** The toy really moved.
* **Without one, a stroke only counts with contact** — a zone in contact
  at that moment, or within `CONTACT_GRACE_S` of it. Strokes with no
  contact anywhere near them are dropped outright.
* **And activity is held back** until it proves to be a scene, one of
  two ways:
    - a streak of `MIN_THRUSTS` thrusts, no pause between two of them
      longer than `STREAK_GAP_S` (penetration), or
    - `MIN_CONTACT_S` of contact within any `CONTACT_WINDOW_S`, however
      it is broken up (lots of touching, no penetration needed).
  Then it counts from `LEAD_S` before the scene's held-back start, and
  goes on counting until `SCENE_END_S` without activity. Activity that
  never gets there is dropped — it never reaches the tracker or the
  history, so it never starts a session either.

`ActivityGate` is generic over what it holds back: the live sampler feeds
it one-second samples, and the clean-up of older timelines feeds it
10-second buckets (with the streak gap and the contact grace widened by a
bucket, since bucket times are coarser than the real gaps). Pure: no
clock, no I/O.

`GATE_VERSION` names the rules above. Timelines remember which version
recorded them; the clean-up re-runs the gate over anything older.
"""

from collections import deque
from typing import Any, Deque, List, Optional, Tuple


GATE_VERSION = 2

MIN_THRUSTS = 20
STREAK_GAP_S = 10.0
MIN_CONTACT_S = 60.0
CONTACT_WINDOW_S = 180.0
CONTACT_GRACE_S = 3.0
LEAD_S = 30.0
# Long enough that a break in the middle of a night stays one session —
# safe now that strokes with nothing touching can't keep a scene going.
SCENE_END_S = 1800.0


class ActivityGate:
    """Feed it every sample in time order with `push`; it returns the
    samples that count, possibly several at once (the held-back lead-in
    when a scene is confirmed) and possibly none. Samples need not be
    evenly spaced: a gap with no samples counts as quiet."""

    def __init__(self, min_thrusts: int = MIN_THRUSTS,
                 streak_gap_s: float = STREAK_GAP_S,
                 lead_s: float = LEAD_S,
                 scene_end_s: float = SCENE_END_S,
                 min_contact_s: float = MIN_CONTACT_S,
                 contact_window_s: float = CONTACT_WINDOW_S,
                 contact_grace_s: float = CONTACT_GRACE_S) -> None:
        self.min_thrusts = int(min_thrusts)
        self.streak_gap_s = float(streak_gap_s)
        self.lead_s = float(lead_s)
        self.scene_end_s = float(scene_end_s)
        self.min_contact_s = float(min_contact_s)
        self.contact_window_s = float(contact_window_s)
        self.contact_grace_s = float(contact_grace_s)
        self._in_scene = False
        self._last_activity = 0.0
        self._last_contact: Optional[float] = None
        # Held-back samples while no scene is confirmed: (time, item).
        self._held: Deque[Tuple[float, Any]] = deque()
        self._streak = 0
        self._streak_start: Optional[float] = None
        self._last_thrust: Optional[float] = None
        # Contact seconds within the window: (time, seconds), and the sum.
        self._contact: Deque[Tuple[float, float]] = deque()
        self._contact_sum = 0.0

    @property
    def in_scene(self) -> bool:
        return self._in_scene

    def push(self, t: float, item: Any, toy_on: bool, contact: float,
             thrusts: int) -> List[Any]:
        """One sample at time `t`. `toy_on`: a toy is being driven;
        `contact`: seconds of zone contact in this sample (0 = none; True
        counts as one second); `thrusts`: strokes counted in this sample.
        Returns the items to count now, oldest first. An item comes back
        only when it is busy — a toy on, contact, or strokes that count —
        so a released sample's strokes always count."""
        thrusts = max(0, int(thrusts))
        contact_s = max(0.0, float(contact))
        if contact_s > 0:
            self._last_contact = t
        near_contact = (self._last_contact is not None
                        and t - self._last_contact <= self.contact_grace_s)
        if not toy_on and not near_contact:
            thrusts = 0         # a stroke with nothing touching: a misfire
        busy = toy_on or contact_s > 0 or thrusts > 0

        if self._in_scene and t - self._last_activity > self.scene_end_s:
            self._in_scene = False      # went quiet (maybe between samples)
        if self._in_scene:
            if busy:
                self._last_activity = t
                return [item]
            return []

        if toy_on:
            # A running toy needs no proof — and whatever was building up
            # to it in the last LEAD_S belongs to the same scene.
            out = [held for when, held in self._held
                   if when >= t - self.lead_s] + [item]
            self._start_scene(t)
            return out

        if thrusts:
            if (self._last_thrust is None
                    or t - self._last_thrust > self.streak_gap_s):
                self._streak = 0
                self._streak_start = t
            self._streak += thrusts
            self._last_thrust = t
        if contact_s:
            self._contact.append((t, contact_s))
            self._contact_sum += contact_s
        while self._contact and self._contact[0][0] < t - self.contact_window_s:
            self._contact_sum -= self._contact.popleft()[1]
        if busy:
            self._held.append((t, item))

        # Keep only the lead-in to what could still become a scene: the
        # current streak and the contact inside the window (or, with
        # neither, the last LEAD_S). The buffer stays small.
        alive = (self._last_thrust is not None
                 and t - self._last_thrust <= self.streak_gap_s)
        anchor = t
        if alive and self._streak_start is not None:
            anchor = min(anchor, self._streak_start)
        if self._contact:
            anchor = min(anchor, self._contact[0][0])
        while self._held and self._held[0][0] < anchor - self.lead_s:
            self._held.popleft()

        if ((alive and self._streak >= self.min_thrusts)
                or self._contact_sum >= self.min_contact_s - 1e-9):
            out = [held for _, held in self._held]
            self._start_scene(t)
            return out
        return []

    def _start_scene(self, t: float) -> None:
        self._in_scene = True
        self._last_activity = t
        self._held.clear()
        self._streak = 0
        self._streak_start = None
        self._last_thrust = None
        self._contact.clear()
        self._contact_sum = 0.0
