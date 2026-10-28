"""Thrust counters for the avatar — the controller side.

Settings → Connection Settings → "Send thrust counters to VRChat" (off
until switched on) sends the lifetime total, this session's count and the
live pace as avatar Int parameters, each as the plain number and as its
digits (thrust_params has the names and the rules).

The numbers come from the statistics: the tracker's totals and the stats
facade's pace window, both fed only what passed the activity gate. So the
counters need Settings → Features → Usage statistics; with it off there is
nothing to send.

Like the connected-toy parameters (toy_presence_facade), only values that
changed go out — except when VRChat can have lost them: the OSC link
coming up and an avatar loading re-send the lot. Turning the switch off,
and quitting, put the pace back to 0 so an avatar never shows a stale
"per minute".

Not a hot path: `_thrust_params_tick()` rides the 1 Hz heartbeat right
after the stats sample.

Sealed-box rules: the UI calls these methods and passes primitives.
"""

from __future__ import annotations

import time
from typing import Dict

from thrust_params import COUNTERS, counter_params, counter_values

ENABLED_KEY = "thrust_params_enabled"

_PARAM_PREFIX = "/avatar/parameters/"


class ThrustParamsFacade:
    """Mixin: thrust counter avatar parameters. Composed into
    OscGoesPurrrApp.

    Assumes the host has `self.mode_manager` (with `app_settings`),
    `self.osc_manager`, and the stats facade's `self.stats_tracker` and
    `self._stats_pace`.
    """

    # ------------------------------------------------------------------
    # What should be on the wire
    # ------------------------------------------------------------------

    def _thrust_params_values(self) -> Dict[str, int]:
        """Parameter name -> value, or {} with statistics off."""
        tracker = getattr(self, "stats_tracker", None)
        if tracker is None:
            return {}
        pace = getattr(self, "_stats_pace", None)
        per_min = pace.rate(time.time()) if pace is not None else 0
        return counter_values(int(tracker.lifetime.get("thrusts", 0)),
                              int(tracker.session.get("thrusts", 0)),
                              per_min)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _thrust_params_send(self, name: str, value: int) -> bool:
        """One parameter out. True when it went (the OSC link is up). Sent
        as an Int unless the avatar declares another type for it."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return False
        try:
            osc.send_parameter(_PARAM_PREFIX + name, int(value),
                               ignore_rate_limit=True, default_type="i")
        except Exception:
            return False
        return True

    def thrust_params_sync(self, force: bool = False) -> None:
        """Bring VRChat up to date: what changed since the last successful
        send, or everything with `force`. A failed send is due again."""
        if not self.get_thrust_params_enabled():
            return
        sent: Dict[str, int] = {} if force else dict(
            getattr(self, "_thrust_params_sent", {}))
        for name, value in self._thrust_params_values().items():
            if sent.get(name) != value and self._thrust_params_send(name, value):
                sent[name] = value
        self._thrust_params_sent = sent

    def _thrust_params_tick(self) -> None:
        """1 Hz, after the stats sample. Guarded: a bug here must not stop
        the heartbeat that hosts it."""
        try:
            self.thrust_params_sync()
        except Exception as e:
            print(f"[thrust params] sync failed: {e}")

    def thrust_params_send_all(self) -> None:
        """The OSC link came up or an avatar loaded: say everything again."""
        self.thrust_params_sync(force=True)

    def _thrust_params_zero_pace(self) -> None:
        places = dict(COUNTERS)["PerMin"]
        for name, value in counter_params("PerMin", 0, places).items():
            if getattr(self, "_thrust_params_sent", {}).get(name, 0):
                self._thrust_params_send(name, value)
        self._thrust_params_sent = {}

    def thrust_params_shutdown(self) -> None:
        """Quit: nothing is being counted any more, so the pace goes to 0
        (the totals stay true and stay)."""
        self._thrust_params_zero_pace()

    # ------------------------------------------------------------------
    # Settings (UI-facing, primitives only)
    # ------------------------------------------------------------------

    def get_thrust_params_enabled(self) -> bool:
        return bool(self.mode_manager.app_settings.get(ENABLED_KEY, False))

    def set_thrust_params_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        self.mode_manager.app_settings.set(ENABLED_KEY, enabled)
        if enabled:
            self.thrust_params_send_all()
        else:
            self._thrust_params_zero_pace()
