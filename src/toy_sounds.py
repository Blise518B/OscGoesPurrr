"""Connect / disconnect chimes for toys.

Two short two-note chimes, synthesized in memory: rising (low -> high) when
a toy connects, falling (high -> low) when one drops. They play through
Windows' PlaySound on a short-lived daemon thread, so neither the GUI nor
any haptic path ever waits on audio. Off Windows, `play()` is a no-op.

Loudness is a 0-100 % volume baked into the samples, so it is the chime's
own level, independent of (and on top of) the Windows volume.

Pure stdlib (no Qt) so the controller can own it without breaking the
visual-decoupling rule.
"""

import io
import math
import struct
import threading
import wave
from functools import lru_cache
from typing import Iterable, Optional, Tuple

try:
    import winsound
except ImportError:  # not Windows
    winsound = None

CONNECTED = "connected"
DISCONNECTED = "disconnected"
TEST = "test"          # the connect chime, a pause, then the disconnect one

SAMPLE_RATE = 44100
MAX_PEAK = 0.95        # 100 % volume: just under full scale
DEFAULT_VOLUME = 60    # percent; about a third of full scale
LOW_HZ = 587.33        # D5
HIGH_HZ = 880.0        # A5, a fifth above
NOTE_S = 0.16          # how long each note rings
STEP_S = 0.10          # the second note starts this long after the first
TEST_GAP_S = 0.35      # pause between the two chimes of TEST
_ATTACK_S = 0.004      # soft onset, so a note never starts with a click
_DECAY_TAU_S = 0.06    # bell-like exponential decay
_TAIL_S = 0.012        # last bit fades to exactly zero


def presence_change(before: Iterable[str], after: Iterable[str]) -> Optional[str]:
    """Which chime a change in the set of connected toys calls for: a toy
    appearing wins over one leaving, and no change means no chime."""
    before, after = set(before), set(after)
    if after - before:
        return CONNECTED
    if before - after:
        return DISCONNECTED
    return None


def clamp_volume(volume) -> int:
    try:
        return max(0, min(100, int(round(float(volume)))))
    except (TypeError, ValueError):
        return DEFAULT_VOLUME


def volume_to_peak(volume) -> float:
    """Volume percent -> peak amplitude (fraction of full scale). Squared,
    because loudness is heard logarithmically: on a linear curve the top
    half of the slider would barely change anything."""
    v = clamp_volume(volume) / 100.0
    return MAX_PEAK * v * v


def _note(freq: float, t: float) -> float:
    """One note's sample at `t` seconds into it (0 outside the note)."""
    if t < 0.0 or t >= NOTE_S:
        return 0.0
    env = min(1.0, t / _ATTACK_S) * math.exp(-t / _DECAY_TAU_S)
    if t > NOTE_S - _TAIL_S:
        env *= (NOTE_S - t) / _TAIL_S
    # A little second harmonic makes it a chime rather than a test tone.
    return env * (math.sin(2 * math.pi * freq * t)
                  + 0.2 * math.sin(4 * math.pi * freq * t))


@lru_cache(maxsize=None)
def _shape(kind: str) -> Tuple[float, ...]:
    """The chime's waveform, normalized so its peak is exactly 1.0."""
    if kind == TEST:
        gap = (0.0,) * int(TEST_GAP_S * SAMPLE_RATE)
        return _shape(CONNECTED) + gap + _shape(DISCONNECTED)
    first, second = ((LOW_HZ, HIGH_HZ) if kind == CONNECTED
                     else (HIGH_HZ, LOW_HZ))
    # +1 so the last sample lands on the end of the fade, i.e. silence.
    n = int(round((STEP_S + NOTE_S) * SAMPLE_RATE)) + 1
    raw = [_note(first, i / SAMPLE_RATE) + _note(second, i / SAMPLE_RATE - STEP_S)
           for i in range(n)]
    top = max(abs(s) for s in raw)
    return tuple(s / top for s in raw)


def chime_wav(kind: str, volume=DEFAULT_VOLUME) -> bytes:
    """The chime for `kind` at `volume` percent, as a complete 16-bit mono
    WAV file."""
    shape = _shape(kind)
    scale = volume_to_peak(volume) * 32767
    pcm = struct.pack(f"<{len(shape)}h", *(int(round(s * scale)) for s in shape))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def play(kind: str, volume=DEFAULT_VOLUME) -> None:
    """Play the chime for `kind` without waiting for it. A newer chime
    cuts off one still playing; volume 0 plays nothing."""
    if winsound is None or clamp_volume(volume) == 0:
        return
    data = chime_wav(kind, volume)
    threading.Thread(target=_play_blocking, args=(data,),
                     name="toy-chime", daemon=True).start()


def _play_blocking(data: bytes) -> None:
    try:
        # SND_MEMORY can't be combined with SND_ASYNC, hence the thread.
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:
        pass  # no audio device, or the device went away: just stay quiet
