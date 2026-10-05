"""Connect / disconnect chimes for toys.

Two short two-note chimes, synthesized in memory: rising (low -> high) when
a toy connects, falling (high -> low) when one drops. They play on a
short-lived daemon thread, so neither the GUI nor any haptic path ever
waits on audio: through Windows' PlaySound, or on Linux through the
desktop's own player (PipeWire's pw-play, PulseAudio's paplay or ALSA's
aplay, whichever is there) — no audio library to bundle. With none of
those, `play()` is a no-op.

Loudness is a 0-100 % volume baked into the samples, so it is the chime's
own level, independent of (and on top of) the system volume.

Pure stdlib (no Qt) so the controller can own it without breaking the
visual-decoupling rule.
"""

import atexit
import io
import math
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import wave
from functools import lru_cache
from typing import Iterable, Optional, Tuple

try:
    import winsound
except ImportError:  # not Windows
    winsound = None

# Linux players, best first. Each takes a WAV file name.
_PLAYERS = (("pw-play", ()), ("paplay", ()), ("aplay", ("-q",)))

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
    if clamp_volume(volume) == 0:
        return
    if winsound is not None:
        data = chime_wav(kind, volume)
        threading.Thread(target=_play_blocking, args=(data,),
                         name="toy-chime", daemon=True).start()
        return
    player = find_player()
    if player is None:
        return
    threading.Thread(target=_play_with_player,
                     args=(player, kind, clamp_volume(volume)),
                     name="toy-chime", daemon=True).start()


def _play_blocking(data: bytes) -> None:
    try:
        # SND_MEMORY can't be combined with SND_ASYNC, hence the thread.
        winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:
        pass  # no audio device, or the device went away: just stay quiet


@lru_cache(maxsize=1)
def find_player() -> Optional[Tuple[str, ...]]:
    """The command (minus the file name) that plays a WAV file here, or
    None. Looked up once: the desktop's sound stack doesn't change while
    the app runs."""
    for name, args in _PLAYERS:
        path = shutil.which(name)
        if path:
            return (path,) + tuple(args)
    return None


_player_lock = threading.Lock()
_player_proc: Optional[subprocess.Popen] = None
_chime_dir: Optional[str] = None


def _wav_file(kind: str, volume: int) -> str:
    """The chime as a WAV file the player can open, written once per
    kind and volume into a folder of our own that goes when we do."""
    global _chime_dir
    if _chime_dir is None:
        _chime_dir = tempfile.mkdtemp(prefix="OscGoesPurrr_chimes_")
        atexit.register(shutil.rmtree, _chime_dir, True)
    path = os.path.join(_chime_dir, f"{kind}-{volume}.wav")
    if not os.path.isfile(path):
        with open(path, "wb") as fh:
            fh.write(chime_wav(kind, volume))
    return path


def _play_with_player(player: Tuple[str, ...], kind: str, volume: int) -> None:
    global _player_proc
    try:
        from utilities import system_env
        with _player_lock:
            path = _wav_file(kind, volume)
            # Like PlaySound, a newer chime cuts off the one still playing.
            if _player_proc is not None and _player_proc.poll() is None:
                _player_proc.terminate()
            proc = subprocess.Popen(
                list(player) + [path], env=system_env(),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            _player_proc = proc
        proc.wait(timeout=10)   # reap it; a chime is under a second
    except Exception:
        pass  # no sound server, or the player failed: just stay quiet
