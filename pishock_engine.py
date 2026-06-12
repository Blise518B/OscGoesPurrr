# pishock_engine.py
# Sealed PiShock engine: connection lifecycle (via ReconnectingEngine) plus the
# hot fire() path with the HARD safety caps that are the last gate before a
# shock reaches a person.
#
# Safety is defense-in-depth: the router applies policy caps too, but every
# fire() here independently re-clamps intensity and duration and enforces a
# minimum interval — so a buggy router, a UI test button, or any future caller
# CANNOT exceed the ceiling, because this sealed engine is the only thing that
# talks to the transport. Per-setting caps may only *lower* the absolute
# ceilings below; they can never raise them.

import time
from typing import Callable, Optional

from engine_base import ReconnectingEngine
from pishock_connection import (
    MODE_CLOUD,
    MODE_SERIAL,
    VALID_OPS,
    make_pishock_connection,
)


class PiShockEngine(ReconnectingEngine):
    """Drives a PiShock through a swappable transport (serial / cloud).

    Connection lifecycle is inherited from ReconnectingEngine; `_open` readies
    the transport (open the port / validate creds) and `_close` releases it.
    The hot path is `fire()` / `stop_now()`."""

    # Absolute ceilings — code never exceeds these regardless of settings.
    ABSOLUTE_MAX_INTENSITY = 100
    ABSOLUTE_MAX_DURATION_MS = 15000
    ABSOLUTE_MIN_INTERVAL_S = 0.3

    # Conservative defaults (used until configure() supplies the user's caps).
    DEFAULT_MAX_INTENSITY = 30
    DEFAULT_MAX_DURATION_MS = 1000
    DEFAULT_MIN_INTERVAL_S = 1.0

    def __init__(self, mode: str = MODE_SERIAL,
                 log: Optional[Callable[[str], None]] = None,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__("PiShock")
        self._log = log or (lambda _m: None)
        self._clock = clock
        self._mode = mode if mode in (MODE_SERIAL, MODE_CLOUD) else MODE_SERIAL
        self._config: dict = {}
        self._cfg_max_intensity = self.DEFAULT_MAX_INTENSITY
        self._cfg_max_duration_ms = self.DEFAULT_MAX_DURATION_MS
        self._cfg_min_interval_s = self.DEFAULT_MIN_INTERVAL_S
        self._last_fire_ts = -1e9
        self._provider = make_pishock_connection(self._mode, log=self._log)

    # ---- Status / config ---------------------------------------------
    @property
    def _available(self) -> bool:
        return bool(self._provider and self._provider.is_available)

    @property
    def _unavailable_reason(self) -> str:
        return f"{self._mode} transport library not installed"

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def status_label(self) -> str:
        return self._provider.status_label if self._provider else "PiShock"

    def set_connection_mode(self, mode: str) -> None:
        if mode not in (MODE_SERIAL, MODE_CLOUD):
            mode = MODE_SERIAL
        if mode == self._mode and self._provider is not None:
            return
        self._mode = mode
        old = self._provider
        self._provider = make_pishock_connection(mode, log=self._log)
        self._provider.configure(self._config)
        if old is not None:
            try:
                old.shutdown()
            except Exception:
                pass
        # Force the reconnect loop to re-open with the new transport.
        self._connected = False

    def configure(self, config: dict) -> None:
        """Push connection config + safety caps. Caps are clamped to the
        absolute ceilings here so a hand-edited settings file can't widen
        them."""
        self._config = dict(config or {})
        self._cfg_max_intensity = self._clamp_int(
            self._config.get("max_intensity", self.DEFAULT_MAX_INTENSITY),
            1, self.ABSOLUTE_MAX_INTENSITY, self.DEFAULT_MAX_INTENSITY)
        self._cfg_max_duration_ms = self._clamp_int(
            self._config.get("max_duration_ms", self.DEFAULT_MAX_DURATION_MS),
            1, self.ABSOLUTE_MAX_DURATION_MS, self.DEFAULT_MAX_DURATION_MS)
        try:
            self._cfg_min_interval_s = max(
                self.ABSOLUTE_MIN_INTERVAL_S,
                float(self._config.get("min_interval_s", self.DEFAULT_MIN_INTERVAL_S)))
        except (TypeError, ValueError):
            self._cfg_min_interval_s = self.DEFAULT_MIN_INTERVAL_S
        if self._provider is not None:
            self._provider.configure(self._config)

    # Effective caps (settings clamped to the absolute ceilings).
    @property
    def max_intensity(self) -> int:
        return min(self.ABSOLUTE_MAX_INTENSITY, self._cfg_max_intensity)

    @property
    def max_duration_ms(self) -> int:
        return min(self.ABSOLUTE_MAX_DURATION_MS, self._cfg_max_duration_ms)

    @property
    def min_interval_s(self) -> float:
        return max(self.ABSOLUTE_MIN_INTERVAL_S, self._cfg_min_interval_s)

    # ---- Hot path -----------------------------------------------------
    def fire(self, op: str, intensity: int, duration_ms: int) -> bool:
        """Fire one discrete operation, with every safety cap enforced here.
        Returns True if it was dispatched, False if dropped (not connected,
        bad op, or inside the min-interval cooldown). Fire-and-forget."""
        if op not in VALID_OPS:
            return False
        if not self._connected or self._provider is None:
            return False
        now = self._clock()
        if now - self._last_fire_ts < self.min_interval_s:
            return False  # safety cooldown — drop too-soon events
        intensity = max(1, min(self.max_intensity, int(intensity)))
        duration_ms = max(1, min(self.max_duration_ms, int(duration_ms)))
        self._last_fire_ts = now
        try:
            self._provider.operate(op, intensity, duration_ms)
            return True
        except Exception as e:
            self._log(f"PiShock fire failed: {e}")
            return False

    def stop_now(self) -> None:
        """Best-effort early stop of an in-flight operation."""
        if self._provider is not None:
            try:
                self._provider.end()
            except Exception:
                pass

    # ---- ReconnectingEngine transport hooks --------------------------
    def _open(self) -> None:
        self._provider.configure(self._config)
        if not self._provider.prepare():
            raise RuntimeError("PiShock transport not ready (check port / credentials)")
        self._connected = True

    def _close(self) -> None:
        self._connected = False
        if self._provider is not None:
            try:
                self._provider.shutdown()
            except Exception:
                pass

    # ---- helpers ------------------------------------------------------
    @staticmethod
    def _clamp_int(value, lo: int, hi: int, default: int) -> int:
        try:
            return max(lo, min(hi, int(value)))
        except (TypeError, ValueError):
            return default
