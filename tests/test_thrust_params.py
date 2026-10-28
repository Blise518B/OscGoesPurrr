"""Thrust counters for the avatar: the digit split, the live pace window,
and the controller that sends them.

What an avatar asset must be able to rely on: fixed parameter names, every
value an Int an avatar can hold (the plain number stops at 255, each digit
is 0..9), the same numbers as the Statistics page, everything said again
when VRChat forgot it, and a pace that never stays up after the app stops
counting.
"""
import pytest

import thrust_params as tp
from controllers.thrust_params_facade import ThrustParamsFacade
from vrchat_osc import VRChatOSCManager


P = "/avatar/parameters/"


class TestDigits:
    def test_ones_first(self):
        assert tp.digits(4072, 5) == [2, 7, 0, 4, 0]

    def test_too_big_reads_all_nines(self):
        assert tp.digits(12345, 3) == [9, 9, 9]

    def test_negative_reads_zero(self):
        assert tp.digits(-5, 2) == [0, 0]

    def test_counter_params(self):
        out = tp.counter_params("Session", 1709, 5)
        assert out == {
            "OGP/Thrusts/Session": 255,
            "OGP/Thrusts/Session/D1": 9,
            "OGP/Thrusts/Session/D2": 0,
            "OGP/Thrusts/Session/D3": 7,
            "OGP/Thrusts/Session/D4": 1,
            "OGP/Thrusts/Session/D5": 0,
        }

    def test_plain_number_below_255_is_exact(self):
        assert tp.counter_params("PerMin", 174, 3)["OGP/Thrusts/PerMin"] == 174

    def test_every_counter_and_place(self):
        out = tp.counter_values(96703, 4240, 61)
        assert len(out) == 3 + 7 + 5 + 3
        assert [out[f"OGP/Thrusts/Total/D{i}"] for i in range(1, 8)] == \
            [3, 0, 7, 6, 9, 0, 0]
        assert all(isinstance(v, int) and 0 <= v <= 255 for v in out.values())
        assert tp.parameter_names() == list(out)


class TestPaceWindow:
    def test_counts_the_last_minute(self):
        w = tp.PaceWindow()
        w.add(100.0, 3)
        w.add(130.0, 2)
        assert w.rate(131.0) == 5
        assert w.rate(160.5) == 2       # the 100 s sample fell out
        assert w.rate(190.5) == 0

    def test_late_samples_count_at_their_own_time(self):
        # The activity gate releases held-back samples late: ones older
        # than a minute must not inflate the pace.
        w = tp.PaceWindow()
        w.add(10.0, 20)
        w.add(80.0, 4)
        assert w.rate(100.0) == 4

    def test_ignores_empty_samples_and_resets(self):
        w = tp.PaceWindow()
        w.add(1.0, 0)
        w.add(1.0, -2)
        assert w.rate(2.0) == 0
        w.add(1.0, 5)
        w.reset()
        assert w.rate(2.0) == 0


class _Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _Modes:
    def __init__(self):
        self.app_settings = _Settings()


class _Osc:
    def __init__(self):
        self.is_connected = True
        self.sent = []

    def send_parameter(self, address, value, ignore_rate_limit=False,
                       force_type=None, default_type=None):
        self.sent.append((address, value, default_type))


class _Tracker:
    def __init__(self):
        self.lifetime = {"thrusts": 100}
        self.session = {"thrusts": 7}


class Host(ThrustParamsFacade):
    def __init__(self):
        self.mode_manager = _Modes()
        self.osc_manager = _Osc()
        self.stats_tracker = _Tracker()
        self._stats_pace = tp.PaceWindow()

    def take(self):
        out, self.osc_manager.sent = self.osc_manager.sent, []
        return {a[len(P):]: v for a, v, _t in out}


@pytest.fixture
def host():
    return Host()


class TestFacade:
    def test_off_by_default_sends_nothing(self, host):
        assert host.get_thrust_params_enabled() is False
        host._thrust_params_tick()
        host.thrust_params_send_all()
        assert host.take() == {}

    def test_switching_on_sends_everything_as_int(self, host):
        host.set_thrust_params_enabled(True)
        sent = host.osc_manager.sent
        assert len(sent) == 18
        assert all(t == "i" and isinstance(v, int) for _a, v, t in sent)
        out = host.take()
        assert out["OGP/Thrusts/Total"] == 100
        assert out["OGP/Thrusts/Session/D1"] == 7

    def test_only_changes_go_out(self, host):
        host.set_thrust_params_enabled(True)
        host.take()
        host._thrust_params_tick()
        assert host.take() == {}
        host.stats_tracker.lifetime["thrusts"] = 101
        host.stats_tracker.session["thrusts"] = 8
        host._thrust_params_tick()
        assert host.take() == {
            "OGP/Thrusts/Total": 101,
            "OGP/Thrusts/Total/D1": 1,
            "OGP/Thrusts/Session": 8,
            "OGP/Thrusts/Session/D1": 8,
        }

    def test_pace_comes_from_the_window(self, host, monkeypatch):
        import controllers.thrust_params_facade as f
        monkeypatch.setattr(f.time, "time", lambda: 1000.0)
        host._stats_pace.add(990.0, 12)
        host.set_thrust_params_enabled(True)
        out = host.take()
        assert out["OGP/Thrusts/PerMin"] == 12
        assert out["OGP/Thrusts/PerMin/D2"] == 1

    def test_send_all_repeats_everything(self, host):
        host.set_thrust_params_enabled(True)
        host.take()
        host.thrust_params_send_all()
        assert len(host.take()) == 18

    def test_link_down_means_due_again(self, host):
        host.set_thrust_params_enabled(True)
        host.take()
        host.osc_manager.is_connected = False
        host.stats_tracker.session["thrusts"] = 9
        host._thrust_params_tick()
        assert host.take() == {}
        host.osc_manager.is_connected = True
        host._thrust_params_tick()
        assert host.take()["OGP/Thrusts/Session"] == 9

    def test_switching_off_and_quitting_zero_the_pace(self, host, monkeypatch):
        import controllers.thrust_params_facade as f
        monkeypatch.setattr(f.time, "time", lambda: 1000.0)
        host._stats_pace.add(995.0, 42)
        host.set_thrust_params_enabled(True)
        host.take()
        host.set_thrust_params_enabled(False)
        assert host.take() == {"OGP/Thrusts/PerMin": 0,
                               "OGP/Thrusts/PerMin/D1": 0,
                               "OGP/Thrusts/PerMin/D2": 0}
        host.set_thrust_params_enabled(True)
        host.take()
        host.thrust_params_shutdown()
        assert host.take()["OGP/Thrusts/PerMin"] == 0

    def test_statistics_off_means_nothing_to_send(self, host):
        host.stats_tracker = None
        host.set_thrust_params_enabled(True)
        assert host.take() == {}


class _Client:
    def __init__(self):
        self.messages = []

    def send_message(self, address, value):
        self.messages.append((address, value))


class TestDefaultType:
    """send_parameter's default_type: the type to use when OSCQuery hasn't
    declared one — a declared type still wins."""

    def _manager(self):
        m = object.__new__(VRChatOSCManager)
        m.is_connected = True
        m.osc_client = _Client()
        m._param_types = {}
        return m

    def test_undeclared_goes_out_as_the_default(self):
        m = self._manager()
        m.send_parameter(P + "OGP/Thrusts/Total/D1", 3,
                         ignore_rate_limit=True, default_type="i")
        (_a, v), = m.osc_client.messages
        assert v == 3 and isinstance(v, int)

    def test_declared_type_wins(self):
        m = self._manager()
        m._param_types[P + "X"] = "f"
        m.send_parameter(P + "X", 3, ignore_rate_limit=True, default_type="i")
        (_a, v), = m.osc_client.messages
        assert v == 3.0 and isinstance(v, float)

    def test_does_not_pin_the_type(self):
        m = self._manager()
        m.send_parameter(P + "X", 3, ignore_rate_limit=True, default_type="i")
        assert P + "X" not in m._param_types
