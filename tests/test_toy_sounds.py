"""Toy connect / disconnect chimes (toy_sounds.py + toy_sounds_facade.py).

The chimes are well-formed, click-free WAVs that rise on connect and fall
on disconnect, at a volume that scales their level and silences them at 0;
the facade chimes once per real change in the set of connected toys, only
while switched on (the default), at the stored volume, and never for a
change it missed while it was off.
"""

import io
import struct
import wave

import pytest

import toy_sounds
from controllers.toy_sounds_facade import SETTING_KEY, VOLUME_KEY, ToySoundsFacade


def _samples(kind, volume=toy_sounds.DEFAULT_VOLUME):
    with wave.open(io.BytesIO(toy_sounds.chime_wav(kind, volume)), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (
            1, 2, toy_sounds.SAMPLE_RATE)
        n = w.getnframes()
        return struct.unpack(f"<{n}h", w.readframes(n))


def _crossings_per_s(samples):
    """Rising zero crossings per second — the pitch of a mostly-sine tone."""
    rising = sum(1 for a, b in zip(samples, samples[1:]) if a < 0 <= b)
    return rising * toy_sounds.SAMPLE_RATE / len(samples)


def _pitch_of_notes(kind):
    s = _samples(kind)
    step = int(toy_sounds.STEP_S * toy_sounds.SAMPLE_RATE)
    # The middle of each note, clear of the other's tail and onset.
    first = s[step // 4: step * 3 // 4]
    second = s[step + step // 4: step + step * 3 // 4]
    return _crossings_per_s(first), _crossings_per_s(second)


@pytest.mark.parametrize("kind", [toy_sounds.CONNECTED, toy_sounds.DISCONNECTED])
def test_chime_is_short_and_click_free(kind):
    s = _samples(kind)
    assert 0.15 < len(s) / toy_sounds.SAMPLE_RATE < 0.5
    assert s[0] == 0 and s[-1] == 0


def test_connect_goes_up_and_disconnect_goes_down():
    low, high = _pitch_of_notes(toy_sounds.CONNECTED)
    assert low == pytest.approx(toy_sounds.LOW_HZ, rel=0.1)
    assert high == pytest.approx(toy_sounds.HIGH_HZ, rel=0.1)
    high, low = _pitch_of_notes(toy_sounds.DISCONNECTED)
    assert high == pytest.approx(toy_sounds.HIGH_HZ, rel=0.1)
    assert low == pytest.approx(toy_sounds.LOW_HZ, rel=0.1)


def test_test_chime_is_connect_then_pause_then_disconnect():
    connect = _samples(toy_sounds.CONNECTED)
    disconnect = _samples(toy_sounds.DISCONNECTED)
    test = _samples(toy_sounds.TEST)
    gap = int(toy_sounds.TEST_GAP_S * toy_sounds.SAMPLE_RATE)
    assert test == connect + (0,) * gap + disconnect


@pytest.mark.parametrize("volume", [5, 30, 60, 100])
def test_volume_sets_the_peak(volume):
    peak = max(abs(v) for v in _samples(toy_sounds.CONNECTED, volume))
    assert peak == round(toy_sounds.volume_to_peak(volume) * 32767)


def test_volume_curve():
    peaks = [toy_sounds.volume_to_peak(v) for v in range(0, 101)]
    assert peaks[0] == 0.0
    assert peaks[100] == toy_sounds.MAX_PEAK < 1.0          # never clips
    assert all(a < b for a, b in zip(peaks, peaks[1:]))     # always louder
    # Half the slider is a quarter of the amplitude (about -12 dB), so the
    # top half of the slider still does real work.
    assert peaks[50] == pytest.approx(peaks[100] / 4)
    # The default is about where the original fixed level sat.
    assert toy_sounds.volume_to_peak(toy_sounds.DEFAULT_VOLUME) == pytest.approx(0.34, abs=0.02)


@pytest.mark.parametrize("raw, expected", [
    (-20, 0), (0, 0), (42, 42), (42.6, 43), (100, 100), (250, 100),
    ("70", 70), (None, toy_sounds.DEFAULT_VOLUME), ("loud", toy_sounds.DEFAULT_VOLUME),
])
def test_clamp_volume(raw, expected):
    assert toy_sounds.clamp_volume(raw) == expected


@pytest.mark.parametrize("before, after, expected", [
    ((), ("Gush",), toy_sounds.CONNECTED),
    (("Gush",), ("Gush", "Lush"), toy_sounds.CONNECTED),
    (("Gush", "Lush"), ("Gush",), toy_sounds.DISCONNECTED),
    (("Gush",), (), toy_sounds.DISCONNECTED),
    (("Gush",), ("Lush",), toy_sounds.CONNECTED),   # arrival wins
    (("Gush",), ("Gush",), None),
    ((), (), None),
])
def test_presence_change(before, after, expected):
    assert toy_sounds.presence_change(before, after) == expected


class _FakeWinsound:
    SND_MEMORY = 4
    SND_NODEFAULT = 2

    def __init__(self):
        self.played = []

    def PlaySound(self, data, flags):
        self.played.append((data, flags))


class _InlineThread:
    def __init__(self, target, args=(), **_):
        self._run = lambda: target(*args)

    def start(self):
        self._run()


@pytest.fixture
def fake_winsound(monkeypatch):
    ws = _FakeWinsound()
    monkeypatch.setattr(toy_sounds, "winsound", ws)
    monkeypatch.setattr(toy_sounds.threading, "Thread", _InlineThread)
    return ws


def test_play_hands_the_wav_to_playsound(fake_winsound):
    toy_sounds.play(toy_sounds.CONNECTED, 80)
    assert fake_winsound.played == [
        (toy_sounds.chime_wav(toy_sounds.CONNECTED, 80),
         _FakeWinsound.SND_MEMORY | _FakeWinsound.SND_NODEFAULT)]


def test_volume_zero_plays_nothing(fake_winsound):
    toy_sounds.play(toy_sounds.CONNECTED, 0)
    assert fake_winsound.played == []


def test_play_never_raises_without_winsound(monkeypatch):
    monkeypatch.setattr(toy_sounds, "winsound", None)
    monkeypatch.setattr(toy_sounds, "find_player", lambda: None)
    toy_sounds.play(toy_sounds.CONNECTED)


# ---------------------------------------------------------------- Linux


class _FakeProc:
    def __init__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        self.terminated = False
        self.running = True

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def fake_player(monkeypatch):
    """No winsound (Linux): play() hands a WAV file to the desktop's
    player, inline and without spawning anything real."""
    spawned = []

    def _popen(cmd, **kwargs):
        proc = _FakeProc(cmd, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(toy_sounds, "winsound", None)
    monkeypatch.setattr(toy_sounds, "find_player", lambda: ("/usr/bin/pw-play",))
    monkeypatch.setattr(toy_sounds.threading, "Thread", _InlineThread)
    monkeypatch.setattr(toy_sounds.subprocess, "Popen", _popen)
    monkeypatch.setattr(toy_sounds, "_player_proc", None)
    return spawned


def test_linux_plays_the_chime_file_through_the_player(fake_player):
    toy_sounds.play(toy_sounds.CONNECTED, 80)
    (proc,) = fake_player
    assert proc.cmd[0] == "/usr/bin/pw-play"
    with open(proc.cmd[-1], "rb") as fh:
        assert fh.read() == toy_sounds.chime_wav(toy_sounds.CONNECTED, 80)


def test_linux_newer_chime_cuts_off_the_one_playing(fake_player):
    toy_sounds.play(toy_sounds.CONNECTED, 80)
    toy_sounds.play(toy_sounds.DISCONNECTED, 80)
    first, second = fake_player
    assert first.terminated and not second.terminated


def test_linux_volume_zero_spawns_nothing(fake_player):
    toy_sounds.play(toy_sounds.CONNECTED, 0)
    assert fake_player == []


def test_player_preference_order(monkeypatch):
    toy_sounds.find_player.cache_clear()
    monkeypatch.setattr(toy_sounds.shutil, "which",
                        lambda name: f"/usr/bin/{name}" if name != "pw-play" else None)
    try:
        assert toy_sounds.find_player() == ("/usr/bin/paplay",)
    finally:
        toy_sounds.find_player.cache_clear()


# ---------------------------------------------------------------- facade

class _Settings(dict):
    def set(self, key, value):
        self[key] = value


class _Modes:
    def __init__(self, enabled, volume=None):
        self.app_settings = _Settings({} if enabled is None else {SETTING_KEY: enabled})
        if volume is not None:
            self.app_settings[VOLUME_KEY] = volume


class _Engine:
    def __init__(self):
        self.names = []

    def list_connected_device_names(self):
        return list(self.names)


class _Host(ToySoundsFacade):
    def __init__(self, enabled, volume=None):
        self.mode_manager = _Modes(enabled, volume)
        self.haptic_engine = _Engine()


@pytest.fixture
def played(monkeypatch):
    calls = []
    monkeypatch.setattr(toy_sounds, "play", lambda kind, volume: calls.append((kind, volume)))
    return calls


def test_on_by_default_at_default_volume(played):
    host = _Host(None)
    assert host.get_toy_sounds_enabled() is True
    assert host.get_toy_sounds_volume() == toy_sounds.DEFAULT_VOLUME
    host.haptic_engine.names = ["Gush"]
    host.toy_sounds_on_devices_changed()
    assert played == [(toy_sounds.CONNECTED, toy_sounds.DEFAULT_VOLUME)]


def test_app_settings_default_matches_the_facade():
    from settings.app import DEFAULT_APP_SETTINGS
    from controllers.toy_sounds_facade import DEFAULT_ON
    assert DEFAULT_APP_SETTINGS[SETTING_KEY] is DEFAULT_ON
    assert DEFAULT_APP_SETTINGS[VOLUME_KEY] == toy_sounds.DEFAULT_VOLUME


def test_chimes_once_per_real_change_at_the_stored_volume(played):
    host = _Host(True, volume=35)
    host.haptic_engine.names = ["Gush", "Lush"]     # two toys at once
    host.toy_sounds_on_devices_changed()
    host.toy_sounds_on_devices_changed()            # nothing changed
    host.haptic_engine.names = ["Gush"]
    host.toy_sounds_on_devices_changed()
    host.haptic_engine.names = []                   # Intiface dropped
    host.toy_sounds_on_devices_changed()
    assert played == [(toy_sounds.CONNECTED, 35), (toy_sounds.DISCONNECTED, 35),
                      (toy_sounds.DISCONNECTED, 35)]


def test_switching_on_previews_and_skips_what_happened_while_off(played):
    host = _Host(False)
    host.haptic_engine.names = ["Gush"]
    host.toy_sounds_on_devices_changed()            # off: tracked, silent
    host.set_toy_sounds_enabled(True)
    assert host.mode_manager.app_settings[SETTING_KEY] is True
    preview = [(toy_sounds.CONNECTED, toy_sounds.DEFAULT_VOLUME)]
    assert played == preview
    host.toy_sounds_on_devices_changed()            # Gush was already here
    host.set_toy_sounds_enabled(False)
    assert played == preview


def test_setting_the_volume_stores_and_previews_it(played):
    host = _Host(False)
    host.set_toy_sounds_volume(80)
    host.set_toy_sounds_volume(250)                 # clamped
    host.set_toy_sounds_volume(20, preview=False)
    assert host.mode_manager.app_settings[VOLUME_KEY] == 20
    assert host.get_toy_sounds_volume() == 20
    assert played == [(toy_sounds.CONNECTED, 80), (toy_sounds.CONNECTED, 100)]


def test_test_plays_both_chimes_even_while_off(played):
    host = _Host(False, volume=45)
    host.test_toy_sounds()
    assert played == [(toy_sounds.TEST, 45)]


def test_a_mangled_stored_volume_falls_back(played):
    host = _Host(True, volume="very")
    assert host.get_toy_sounds_volume() == toy_sounds.DEFAULT_VOLUME


def test_engine_error_changes_nothing(played):
    host = _Host(True)
    host.haptic_engine.names = ["Gush"]
    host.toy_sounds_on_devices_changed()

    def boom():
        raise RuntimeError("client gone")
    host.haptic_engine.list_connected_device_names = boom
    host.toy_sounds_on_devices_changed()
    assert played == [(toy_sounds.CONNECTED, toy_sounds.DEFAULT_VOLUME)]
