"""Connected-toy avatar parameters: one Bool for "any toy is connected",
one per toy for "this toy is connected".

What the avatar must be able to rely on: the value follows the toys, it
is said again whenever VRChat forgot it (link up, avatar loaded), and a
parameter is never left true for a toy the app no longer holds.
"""
import pytest

from config_manager import is_routing_key
from controllers import toy_presence_facade as tp
from controllers.toy_presence_facade import ToyPresenceFacade


class _Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _Modes:
    def __init__(self, devices):
        self.app_settings = _Settings()
        self.wiring = {d: {} for d in devices}
        self.saves = 0

    def get_active_profile_dict(self):
        return self.wiring

    def get_profile_config(self, device, key, default=None):
        return self.wiring.get(device, {}).get(key, default)

    def update_device_config(self, device, key, value):
        self.wiring.setdefault(device, {})[key] = value

    def save_profiles(self):
        self.saves += 1


class _Osc:
    def __init__(self):
        self.is_connected = True
        self.sent = []

    def send_parameter(self, address, value, ignore_rate_limit=False,
                       force_type=None):
        self.sent.append((address, value))


class _Engine:
    def __init__(self):
        self.names = []

    def list_connected_device_names(self):
        return list(self.names)


class Host(ToyPresenceFacade):
    def __init__(self, devices=("Lush", "Edge")):
        self.mode_manager = _Modes(devices)
        self.osc_manager = _Osc()
        self.haptic_engine = _Engine()

    def take(self):
        """What went out since the last look."""
        out, self.osc_manager.sent = self.osc_manager.sent, []
        return out

    def connect(self, *names):
        self.haptic_engine.names = list(names)
        self.toy_presence_on_devices_changed()


P = "/avatar/parameters/"


class TestOffByDefault:
    def test_nothing_is_sent_until_something_is_switched_on(self):
        h = Host()
        h.connect("Lush")
        h.toy_presence_send_all()
        h.toy_presence_shutdown()
        assert h.take() == []

    def test_the_names_are_ready_before_the_switch_is(self):
        h = Host(["Lovense Lush"])
        assert h.get_toy_presence_param() == (False, "OGP/ToyConnected")
        assert h.get_toy_connected_param("Lovense Lush") == (
            False, "OGP/LovenseLushConnected")

    def test_a_toy_name_becomes_a_safe_parameter_name(self):
        assert tp.default_toy_param("Lovense Edge 2 (left)") == \
            "OGP/LovenseEdge2leftConnected"
        assert tp.default_toy_param("") == "OGP/ToyConnected"


class TestAnyToy:
    def test_switching_it_on_says_where_things_stand_at_once(self):
        h = Host()
        h.set_toy_presence_param(True, "OGP/ToyConnected")
        assert h.take() == [(P + "OGP/ToyConnected", False)]

    def test_true_while_any_toy_is_connected(self):
        h = Host()
        h.set_toy_presence_param(True, "OGP/ToyConnected")
        h.take()
        h.connect("Lush")
        assert h.take() == [(P + "OGP/ToyConnected", True)]
        h.connect("Lush", "Edge")                 # still "any": no resend
        assert h.take() == []
        h.connect("Edge")
        assert h.take() == []
        h.connect()
        assert h.take() == [(P + "OGP/ToyConnected", False)]

    def test_values_are_real_bools(self):
        h = Host()
        h.set_toy_presence_param(True, "X")
        h.connect("Lush")
        assert all(type(v) is bool for _a, v in h.take())

    def test_a_pasted_full_address_is_reduced_to_the_name(self):
        h = Host()
        h.set_toy_presence_param(True, "/avatar/parameters/MyToys")
        assert h.get_toy_presence_param() == (True, "MyToys")
        assert h.take() == [(P + "MyToys", False)]


class TestPerToy:
    def test_each_toy_drives_only_its_own_parameter(self):
        h = Host()
        h.set_toy_connected_param("Lush", True, "LushOn")
        h.set_toy_connected_param("Edge", True, "EdgeOn")
        h.take()
        h.connect("Lush")
        assert h.take() == [(P + "LushOn", True)]
        h.connect("Lush", "Edge")
        assert h.take() == [(P + "EdgeOn", True)]
        h.connect("Edge")
        assert h.take() == [(P + "LushOn", False)]

    def test_it_is_a_fact_about_the_toy_not_about_a_mode(self):
        """Stored in the toy's wiring, so every mode shares it."""
        assert not is_routing_key(tp.TOY_ENABLED_KEY)
        assert not is_routing_key(tp.TOY_PARAM_KEY)
        h = Host()
        h.set_toy_connected_param("Lush", True, "LushOn")
        assert h.mode_manager.wiring["Lush"] == {
            tp.TOY_PARAM_KEY: "LushOn", tp.TOY_ENABLED_KEY: True}
        assert h.mode_manager.saves == 1

    def test_an_empty_name_falls_back_to_the_toys_default(self):
        h = Host()
        h.set_toy_connected_param("Lush", True, "")
        assert h.get_toy_connected_param("Lush") == (True, "OGP/LushConnected")

    def test_toys_sharing_a_name_share_the_parameter(self):
        h = Host()
        h.set_toy_connected_param("Lush", True, "Either")
        h.set_toy_connected_param("Edge", True, "Either")
        h.take()
        h.connect("Edge")
        assert h.take() == [(P + "Either", True)]
        h.connect("Lush")
        assert h.take() == []                    # still true
        h.connect()
        assert h.take() == [(P + "Either", False)]

    def test_any_and_per_toy_run_side_by_side(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.set_toy_connected_param("Lush", True, "LushOn")
        h.take()
        h.connect("Edge")
        assert h.take() == [(P + "Any", True)]
        h.connect("Edge", "Lush")
        assert h.take() == [(P + "LushOn", True)]


class TestVRChatForgets:
    def test_an_avatar_swap_gets_everything_again(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.set_toy_connected_param("Lush", True, "LushOn")
        h.connect("Lush")
        h.take()
        h.toy_presence_send_all()
        assert sorted(h.take()) == [(P + "Any", True), (P + "LushOn", True)]

    def test_nothing_is_lost_while_the_link_is_down(self):
        h = Host()
        h.osc_manager.is_connected = False
        h.set_toy_presence_param(True, "Any")
        h.connect("Lush")
        assert h.take() == []
        h.osc_manager.is_connected = True
        h.toy_presence_send_all()                # the link came up
        assert h.take() == [(P + "Any", True)]

    def test_a_change_made_while_down_goes_out_on_the_next_change(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.take()
        h.osc_manager.is_connected = False
        h.connect("Lush")
        h.osc_manager.is_connected = True
        h.toy_presence_on_devices_changed()
        assert h.take() == [(P + "Any", True)]


class TestNeverLeftTrue:
    def test_switching_off_clears_it_once(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.connect("Lush")
        h.take()
        h.set_toy_presence_param(False, "Any")
        assert h.take() == [(P + "Any", False)]
        h.connect()
        h.connect("Lush")
        assert h.take() == []                    # it really is off

    def test_switching_off_something_already_false_sends_nothing(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.take()
        h.set_toy_presence_param(False, "Any")
        assert h.take() == []

    def test_renaming_clears_the_old_name_and_fills_the_new(self):
        h = Host()
        h.set_toy_connected_param("Lush", True, "Old")
        h.connect("Lush")
        h.take()
        h.set_toy_connected_param("Lush", True, "New")
        assert sorted(h.take()) == [(P + "New", True), (P + "Old", False)]

    def test_a_deleted_toy_takes_its_parameter_down(self):
        h = Host()
        h.set_toy_connected_param("Lush", True, "LushOn")
        h.connect("Lush")
        h.take()
        del h.mode_manager.wiring["Lush"]
        h.toy_presence_sync()
        assert h.take() == [(P + "LushOn", False)]

    def test_quitting_says_no_toy_is_connected(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.set_toy_connected_param("Lush", True, "LushOn")
        h.set_toy_connected_param("Edge", True, "EdgeOn")
        h.connect("Lush")
        h.take()
        h.toy_presence_shutdown()
        # Only what was true needs saying; EdgeOn was already false.
        assert sorted(h.take()) == [(P + "Any", False), (P + "LushOn", False)]


class TestWiredIntoTheApp:
    def test_the_app_class_carries_the_facade(self):
        import inspect
        import main
        assert issubclass(main.OscGoesPurrrApp, ToyPresenceFacade)
        src = inspect.getsource(main.OscGoesPurrrApp)
        # Toys arriving, toys leaving, the link coming up, an avatar
        # loading, a toy being deleted, and quitting.
        assert src.count("self.toy_presence_on_devices_changed()") == 2
        assert src.count("self.toy_presence_send_all()") == 2
        assert "self.toy_presence_shutdown()" in src
        assert "self.toy_presence_sync()" in src
        from controllers.intiface_facade import IntifaceFacade
        assert "self.toy_presence_on_devices_changed()" in inspect.getsource(
            IntifaceFacade.update_connection_status)
