"""bhaptics_ble waits until one write carries a whole frame: Windows reports
a link connected while writes still take 20 bytes, and the Pro / Air's
40-byte frame is refused until it grows ("The parameter is incorrect")."""

import asyncio

import pytest

import bhaptics_ble


class Char:
    """A characteristic whose room is read from `sizes`, the last repeating."""

    def __init__(self, sizes):
        self._sizes = list(sizes)

    @property
    def max_write_without_response_size(self):
        return self._sizes.pop(0) if len(self._sizes) > 1 else self._sizes[0]


def test_waits_until_a_whole_frame_fits(monkeypatch):
    monkeypatch.setattr(bhaptics_ble, "_ROOM_POLL_S", 0.0)
    char = Char([20, 20, 20, 244])
    asyncio.run(bhaptics_ble._wait_for_room(char, 40))
    assert char.max_write_without_response_size == 244


def test_room_already_there_returns_at_once():
    asyncio.run(bhaptics_ble._wait_for_room(Char([20]), 20))


def test_room_that_never_comes_says_why(monkeypatch):
    monkeypatch.setattr(bhaptics_ble, "_ROOM_POLL_S", 0.0)
    monkeypatch.setattr(bhaptics_ble, "ROOM_WAIT_S", 0.05)
    with pytest.raises(RuntimeError, match="20 bytes per write.*a frame is 40"):
        asyncio.run(bhaptics_ble._wait_for_room(Char([20]), 40))
