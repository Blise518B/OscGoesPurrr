"""How often a friend -- Me, a browser on the web remote -- may make this
OGP act on something they sent: a token bucket per sender.

What arrives over the Friends link is cleaned before it is used, and the
same goes for how often it arrives (Blise's rule, 2026-11-16: whatever a
modified client sends is corrected to what the app itself would). OGP's own
panels send a shock per press, a Stop per press and an Avatar Remote set at
most every 60 ms per slider -- far inside these budgets, so nothing they
send is ever turned away. A sender past its budget is refused at the door:
before the shocker engine, VRChat or the log see anything, so a flood can't
wear the log down to the disk, fill the GUI's queue or keep the hub's serial
line busy. The refusal is logged at most every `SAY_EVERY_S` per sender.

Toy cards (`CARDS`) are a state, not an event: a ``cmd`` costs one only when
its levels, auto modes or Override differ from what last landed (a top-up,
a copy or a keepalive is free). OGP's link sends a friend at most 64 changes
a second (60 pushes, remote_session.CMD_HZ, plus the 4 a second tick) --
measured 62 while a slider was dragged at 1000 steps a second; the web
remote at most 94 in any second (measured, a hand wiggling a slider through
zero at 3 to 30 Hz: its letting-go copies, 30 and 60 ms later, land after
newer cmds). The burst is what a link stalled for 3 s hands over at once.
Letting go is never refused (`spend`), only counted, so it can't be used to
change the cards past the budget either. Me is not budgeted: its loop on
this PC isn't throttled like the link (a fast mouse alone outruns any
number), and nothing from outside reaches it but the avatar menu, whose
senders hold to `PARAMS`.

The engine's own rules (caps, rest, cooldown, the longest hold) never
depend on these: they hold however often something arrives.

Pure: no Qt, no network, the clock passed in. Thread-safe -- the link's
thread and the GUI thread (Me) both ask.
"""

import threading
from typing import Dict, Hashable, Tuple

# (per second, burst): what one sender may do
SHOCKS = (10.0, 20)      # shocker operations (``shk``): a press, Party Mode's per length
STOPS = (10.0, 20)       # Stops (``stp``) that reach the shocker hub
PARAMS = (30.0, 60)      # Avatar Remote sets, new held buttons and height changes
CARDS = (150.0, 300)     # toy-card changes (``cmd``): 94 a second the most measured
SAY_EVERY_S = 5.0        # a sender over budget is logged at most this often


class Budget:
    """A token bucket per key (a peer): `take` spends one, refilling at
    `per_s` up to `burst`."""

    def __init__(self, per_s: float, burst: int, say_every_s: float = SAY_EVERY_S):
        self.per_s = float(per_s)
        self.burst = float(burst)
        self.say_every_s = float(say_every_s)
        self._lock = threading.Lock()
        self._left: Dict[Hashable, Tuple[float, float]] = {}    # key -> (tokens, at)
        self._said: Dict[Hashable, float] = {}

    def take(self, key: Hashable, now: float) -> bool:
        """Spend one for `key`: False when it has none left (refuse it)."""
        with self._lock:
            tokens, at = self._left.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + max(0.0, now - at) * self.per_s)
            if tokens < 1.0:
                self._left[key] = (tokens, now)
                return False
            self._left[key] = (tokens - 1.0, now)
            return True

    def spend(self, key: Hashable, now: float) -> None:
        """Spend one for `key` whatever is left: for what is never refused
        (letting go). It may leave `key` owing, down to -burst at most --
        the next `take` waits until that is paid back."""
        with self._lock:
            tokens, at = self._left.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + max(0.0, now - at) * self.per_s)
            self._left[key] = (max(-self.burst, tokens - 1.0), now)

    def say(self, key: Hashable, now: float) -> bool:
        """Log this refusal? True at most once per `say_every_s` per key."""
        with self._lock:
            last = self._said.get(key)
            if last is not None and now - last < self.say_every_s:
                return False
            self._said[key] = now
            return True

    def forget(self, key: Hashable) -> None:
        """`key` is gone (unfriended, offline): a fresh budget next time."""
        with self._lock:
            self._left.pop(key, None)
            self._said.pop(key, None)
