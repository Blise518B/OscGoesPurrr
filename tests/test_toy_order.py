"""The connected toys' order (intiface_facade.get_connected_toys_in_order):
the order they connected, so a toy's number -- on Home and in the friends'
Which toys -- never moves when another connects (Blise's ask, 2026-10-28)."""

from controllers.intiface_facade import IntifaceFacade


class _Engine:
    def __init__(self):
        self.names = []

    def list_connected_device_names(self):
        return list(self.names)


class _Host:
    get_connected_toys_in_order = IntifaceFacade.get_connected_toys_in_order

    def __init__(self):
        self.haptic_engine = _Engine()


def test_a_newcomer_goes_last_and_a_returning_toy_too():
    h = _Host()
    h.haptic_engine.names = ["Lush"]
    assert h.get_connected_toys_in_order() == ["Lush"]
    h.haptic_engine.names = ["Edge", "Lush"]          # however the engine lists them
    assert h.get_connected_toys_in_order() == ["Lush", "Edge"]
    h.haptic_engine.names = ["Edge"]                  # the Lush drops ...
    assert h.get_connected_toys_in_order() == ["Edge"]
    h.haptic_engine.names = ["Lush", "Edge"]          # ... and comes back after the Edge
    assert h.get_connected_toys_in_order() == ["Edge", "Lush"]


def test_no_engine_no_toys():
    h = _Host()
    h.haptic_engine = None
    assert h.get_connected_toys_in_order() == []
