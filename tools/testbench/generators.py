"""Test-signal generation for the bench's input side.

Two layers:

* :func:`sample_pattern` — a pure, stateless waveform sampler (verbatim port
  of the main app's ``mixer.sample_pattern``; kept inline so the bench stays
  decoupled from the app). Output is in ``[0, amp]``.
* :class:`SignalDriver` — a tiny ``QObject`` that fires a sink callback with a
  fresh ``[0, 1]`` value on a high-rate timer (continuous waveform) or on
  demand (manual hold / single-step / pulse). The sink does the actual OSC
  send + input timestamping, so the driver knows nothing about networking.

For clean end-to-end latency measurement use a low-frequency **square** wave:
its sharp 0->amp rising edge is exactly what the bench's edge detector pairs
against the toy's first output movement.
"""

from __future__ import annotations

import math
import time
from typing import Callable, Optional

from PySide6.QtCore import QObject, QTimer

# Match the main app's shape vocabulary (mixer.py WAVEFORMS) so the bench and
# the app's Tune view speak the same language. "square" is first here because
# it is the right default for latency edges.
WAVEFORMS = ("square", "sine", "triangle", "sawtooth")

# Spinbox bounds mirror the app's signal-generator panel.
FREQ_MIN, FREQ_MAX, FREQ_STEP = 0.05, 5.0, 0.05
AMP_MIN, AMP_MAX, AMP_STEP = 0.0, 1.0, 0.05


def clamp01(v: float) -> float:
    """Clamp to the unit interval."""
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return float(v)


def sample_pattern(waveform: str, freq_hz: float, amp: float, t_s: float) -> float:
    """One sample of a parametric periodic signal — pure, no state.

    Verbatim port of ``mixer.sample_pattern`` (the app keeps the canonical
    copy). Output range is ``[0, amp]``. ``freq_hz <= 0`` or an unknown
    waveform yields ``0.0``.
    """
    if freq_hz <= 0.0:
        return 0.0
    phase = (float(freq_hz) * float(t_s)) % 1.0
    if waveform == "sine":
        return float(amp) * (0.5 + 0.5 * math.sin(2.0 * math.pi * phase))
    if waveform == "square":
        return float(amp) if phase < 0.5 else 0.0
    if waveform == "triangle":
        if phase < 0.5:
            return float(amp) * (2.0 * phase)
        return float(amp) * (2.0 * (1.0 - phase))
    if waveform == "sawtooth":
        return float(amp) * phase
    return 0.0


class SignalDriver(QObject):
    """Drives a ``[0, 1]`` input value via a sink callback.

    The sink is ``on_sample(value: float) -> None`` and is responsible for the
    OSC send and the input-side timestamp (so the timestamp matches the actual
    send instant). The driver only decides *what* value to emit *when*:

    * **Continuous waveform** — ``start_wave()`` runs a timer (~125 Hz) that
      emits ``offset + sample_pattern(...)`` each tick until ``stop_wave()``.
    * **Manual hold** — ``set_manual(v)`` emits one value immediately (timer
      stays off so we don't flood UDP with unchanged values).
    * **Single step / pulse** — ``step(level)`` emits one held value;
      ``pulse(level, width_ms)`` emits the level now and ``0.0`` after the
      width via a one-shot timer.
    """

    def __init__(
        self,
        on_sample: Callable[[float], None],
        interval_ms: int = 8,
        clock: Callable[[], float] = time.perf_counter,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._on_sample = on_sample
        self._clock = clock
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval_ms))
        self._timer.timeout.connect(self._tick)
        self._t0: float = 0.0

        # Public knobs — written straight from the UI; applied on the next tick.
        self.waveform: str = "square"
        self.freq: float = 0.5
        self.amp: float = 1.0
        self.offset: float = 0.0

    @property
    def running(self) -> bool:
        return self._timer.isActive()

    # ----------------------------------------------------------- continuous
    def start_wave(self) -> None:
        self._t0 = self._clock()
        self._timer.start()

    def stop_wave(self) -> None:
        self._timer.stop()
        # Snap to 0 so the driven zone goes idle (and so a final falling edge
        # is recorded), matching the old sim's Stop behaviour.
        self._emit(0.0)

    # --------------------------------------------------------------- on-demand
    def set_manual(self, value: float) -> None:
        """Emit one held value (used by the manual slider)."""
        self._emit(clamp01(value))

    def step(self, level: float = 1.0) -> None:
        """Emit one held step value (stays until changed)."""
        self._emit(clamp01(level))

    def pulse(self, level: float = 1.0, width_ms: int = 250) -> None:
        """Emit ``level`` now, then ``0.0`` after ``width_ms`` (one-shot)."""
        self._emit(clamp01(level))
        QTimer.singleShot(int(width_ms), lambda: self._emit(0.0))

    # ------------------------------------------------------------------- tick
    def _tick(self) -> None:
        t = self._clock() - self._t0
        self._emit(clamp01(self.offset + sample_pattern(self.waveform, self.freq, self.amp, t)))

    def _emit(self, value: float) -> None:
        self._on_sample(float(value))
