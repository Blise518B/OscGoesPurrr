"""Connected-device avatar parameters: one Bool for "any toy is
connected", one per toy; one for the bHaptics suit and one per part; one
for the OWO suit; one for "a shocker is connected" and one per shocker.

What the avatar must be able to rely on: the value follows the devices, it
is said again whenever VRChat forgot it (link up, avatar loaded), a
parameter is never left true for something the app no longer holds, and
every one is on by default under a fixed name an asset can be built
against (Blise's call, 2026-11-05).
"""
import pytest

import body_map
from config_manager import is_routing_key
from controllers import presence_facade as tp
from controllers.presence_facade import PresenceFacade


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


class Host(PresenceFacade):
    """The toys only, and (`quiet`) with their parameters switched off, so
    a test hears only the ones it switches on."""

    def __init__(self, devices=("Lush", "Edge"), quiet=True):
        self.mode_manager = _Modes(devices)
        self.osc_manager = _Osc()
        self.haptic_engine = _Engine()
        if quiet:
            self.mode_manager.app_settings.values[tp.ANY_ENABLED_KEY] = False
            for d in devices:
                self.mode_manager.wiring[d][tp.TOY_ENABLED_KEY] = False

    def take(self):
        """What went out since the last look."""
        out, self.osc_manager.sent = self.osc_manager.sent, []
        return out

    def connect(self, *names):
        self.haptic_engine.names = list(names)
        self.presence_on_devices_changed()


P = "/avatar/parameters/"


class TestOnByDefault:
    def test_every_toy_parameter_starts_on(self):
        h = Host(["Lovense Lush"], quiet=False)
        assert h.get_toy_presence_param() == (True, "OGP/ToyConnected")
        assert h.get_toy_connected_param("Lovense Lush") == (
            True, "OGP/LovenseLushConnected")

    def test_a_fresh_install_tells_the_avatar_at_once(self):
        h = Host(["Lush"], quiet=False)
        h.connect("Lush")
        assert sorted(h.take()) == [(P + "OGP/LushConnected", True),
                                    (P + "OGP/ToyConnected", True)]

    def test_a_switch_someone_set_stays_as_they_set_it(self):
        h = Host(["Lush"], quiet=False)
        h.set_toy_presence_param(False, "OGP/ToyConnected")
        h.set_toy_connected_param("Lush", False, "")
        h.take()
        h.connect("Lush")
        assert h.take() == []

    def test_a_toy_name_becomes_a_safe_parameter_name(self):
        assert tp.default_toy_param("Lovense Edge 2 (left)") ==             "OGP/LovenseEdge2leftConnected"
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
        h.presence_send_all()
        assert sorted(h.take()) == [(P + "Any", True), (P + "LushOn", True)]

    def test_nothing_is_lost_while_the_link_is_down(self):
        h = Host()
        h.osc_manager.is_connected = False
        h.set_toy_presence_param(True, "Any")
        h.connect("Lush")
        assert h.take() == []
        h.osc_manager.is_connected = True
        h.presence_send_all()                # the link came up
        assert h.take() == [(P + "Any", True)]

    def test_a_change_made_while_down_goes_out_on_the_next_change(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.take()
        h.osc_manager.is_connected = False
        h.connect("Lush")
        h.osc_manager.is_connected = True
        h.presence_on_devices_changed()
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
        h.presence_sync()
        assert h.take() == [(P + "LushOn", False)]

    def test_quitting_says_no_toy_is_connected(self):
        h = Host()
        h.set_toy_presence_param(True, "Any")
        h.set_toy_connected_param("Lush", True, "LushOn")
        h.set_toy_connected_param("Edge", True, "EdgeOn")
        h.connect("Lush")
        h.take()
        h.presence_shutdown()
        # Only what was true needs saying; EdgeOn was already false.
        assert sorted(h.take()) == [(P + "Any", False), (P + "LushOn", False)]


# ----------------------------------------------------------------------
# The suits and the shockers
# ----------------------------------------------------------------------

class _BHaptics:
    def __init__(self):
        self.positions = set()

    @property
    def is_connected(self):
        return bool(self.positions)

    def connected_positions(self):
        return set(self.positions)


class _Owo:
    def __init__(self):
        self.is_connected = False


class _SuitsSettings:
    def __init__(self):
        self.have = list(body_map.DEFAULT_HAVE)

    def bhaptics(self):
        return {"have": list(self.have)}


class _Hub:
    def __init__(self):
        self.is_connected = False
        self.hub_kind = ""
        self.listed = []          # the hub's own list, ids
        self.off = set()

    def all_shockers(self):
        return [{"id": sid, "off": sid in self.off} for sid in self.listed]

    def shocker_ids(self):
        return [sid for sid in self.listed if sid not in self.off]


class _HubSettings:
    def __init__(self):
        self.openshock = []

    def get_openshock_shockers(self):
        return [dict(s) for s in self.openshock]


class DeviceHost(Host):
    """No toys; the suits and the shockers, their features switched on."""

    def __init__(self, features=("feature_bhaptics", "feature_owo", "feature_pishock")):
        super().__init__(devices=())
        self.features = set(features)
        self.bhaptics_engine = _BHaptics()
        self.owo_engine = _Owo()
        self.suits_settings = _SuitsSettings()
        self.pishock_engine = _Hub()
        self.pishock_settings = _HubSettings()

    def get_feature_enabled(self, key):
        return key in self.features

    def state(self):
        """A suit's or the hub's state changed (the queue's suits_state /
        pishock_state)."""
        self.presence_on_devices_changed()

    def on_wire(self):
        """name -> value as the avatar has it now."""
        return dict(self._presence_sent)


class TestTheNames:
    def test_fixed_names_an_asset_can_count_on(self):
        h = DeviceHost()
        assert h.get_device_connected_param(tp.SLOT_BHAPTICS) == (True, "OGP/BHapticsConnected")
        assert h.get_device_connected_param(tp.SLOT_OWO) == (True, "OGP/OWOConnected")
        assert h.get_device_connected_param(tp.SLOT_SHOCKERS) == (True, "OGP/ShockerConnected")
        assert [h.get_device_connected_param(tp.bhaptics_part_slot(k))[1]
                for k, _n, _p in body_map.PART_GROUPS] == [
            "OGP/BHapticsVestConnected", "OGP/BHapticsSleevesConnected",
            "OGP/BHapticsHandsConnected", "OGP/BHapticsFeetConnected",
            "OGP/BHapticsHeadConnected"]

    def test_shockers_are_numbered_like_their_cards(self):
        h = DeviceHost()
        h.pishock_engine.is_connected = True
        h.pishock_engine.listed = [4711, 815]
        assert h.get_device_connected_param(tp.shocker_slot(4711))[1] == "OGP/Shocker1Connected"
        assert h.get_device_connected_param(tp.shocker_slot(815))[1] == "OGP/Shocker2Connected"

    def test_an_openshock_list_is_numbered_while_the_hub_is_unplugged_too(self):
        h = DeviceHost()
        h.pishock_settings.openshock = [{"id": 900}, {"id": 12}]
        assert h.get_device_connected_param(tp.shocker_slot(12))[1] == "OGP/Shocker2Connected"

    def test_a_renamed_one_keeps_its_name_and_a_cleared_one_its_default(self):
        h = DeviceHost()
        h.set_device_connected_param(tp.SLOT_OWO, True, "/avatar/parameters/MyVest")
        assert h.get_device_connected_param(tp.SLOT_OWO) == (True, "MyVest")
        h.set_device_connected_param(tp.SLOT_OWO, False, "")
        assert h.get_device_connected_param(tp.SLOT_OWO) == (False, "OGP/OWOConnected")

    def test_the_default_typed_out_still_follows_the_card(self):
        """Saved as "the default", so a shocker that moves to another card
        number takes its new number."""
        h = DeviceHost()
        h.pishock_engine.is_connected = True
        h.pishock_engine.listed = [4711, 815]
        h.set_device_connected_param(tp.shocker_slot(815), True, "OGP/Shocker2Connected")
        h.pishock_engine.listed = [815]
        assert h.get_device_connected_param(tp.shocker_slot(815))[1] == "OGP/Shocker1Connected"


class TestSuits:
    def test_the_suit_and_each_part_follow_what_is_connected(self):
        h = DeviceHost(features=("feature_bhaptics",))
        h.suits_settings.have = ["vest", "arms"]
        h.state()
        assert h.on_wire() == {"OGP/BHapticsConnected": False,
                               "OGP/BHapticsVestConnected": False,
                               "OGP/BHapticsSleevesConnected": False}
        h.take()
        h.bhaptics_engine.positions = {"VestFront", "VestBack"}
        h.state()
        assert sorted(h.take()) == [(P + "OGP/BHapticsConnected", True),
                                    (P + "OGP/BHapticsVestConnected", True)]
        h.bhaptics_engine.positions = {"VestFront", "VestBack", "ForearmL"}
        h.state()
        assert h.take() == [(P + "OGP/BHapticsSleevesConnected", True)]
        h.bhaptics_engine.positions = set()
        h.state()
        assert sorted(h.take()) == [(P + "OGP/BHapticsConnected", False),
                                    (P + "OGP/BHapticsSleevesConnected", False),
                                    (P + "OGP/BHapticsVestConnected", False)]

    def test_a_part_not_in_you_have_still_counts_while_connected(self):
        h = DeviceHost(features=("feature_bhaptics",))
        h.bhaptics_engine.positions = {"Head"}
        h.state()
        assert h.on_wire()["OGP/BHapticsHeadConnected"] is True
        assert "OGP/BHapticsFeetConnected" not in h.on_wire()

    def test_owo_follows_my_owo(self):
        h = DeviceHost(features=("feature_owo",))
        h.state()
        assert h.take() == [(P + "OGP/OWOConnected", False)]
        h.owo_engine.is_connected = True
        h.state()
        assert h.take() == [(P + "OGP/OWOConnected", True)]

    def test_switching_the_feature_off_clears_it_once(self):
        h = DeviceHost(features=("feature_owo",))
        h.owo_engine.is_connected = True
        h.state()
        h.take()
        h.features.clear()
        h.presence_sync()
        assert h.take() == [(P + "OGP/OWOConnected", False)]
        h.presence_send_all()
        assert h.take() == []                    # gone with its feature

    def test_a_feature_that_is_off_sends_nothing(self):
        h = DeviceHost(features=())
        h.owo_engine.is_connected = True
        h.bhaptics_engine.positions = {"VestFront"}
        h.presence_send_all()
        assert h.take() == []


class TestShockers:
    def test_true_while_the_hub_is_connected_with_a_shocker_in_use(self):
        h = DeviceHost(features=("feature_pishock",))
        h.state()
        assert h.take() == [(P + "OGP/ShockerConnected", False)]
        hub = h.pishock_engine
        hub.is_connected, hub.listed = True, [4711, 815]
        h.state()
        assert sorted(h.take()) == [(P + "OGP/Shocker1Connected", True),
                                    (P + "OGP/Shocker2Connected", True),
                                    (P + "OGP/ShockerConnected", True)]

    def test_a_shocker_switched_off_goes_false_and_keeps_its_number(self):
        h = DeviceHost(features=("feature_pishock",))
        hub = h.pishock_engine
        hub.is_connected, hub.listed = True, [4711, 815]
        h.state()
        h.take()
        hub.off = {4711}
        h.state()
        assert h.take() == [(P + "OGP/Shocker1Connected", False)]
        hub.off = {4711, 815}
        h.state()
        # none in use: nothing can shock, so the hub's goes false too
        assert sorted(h.take()) == [(P + "OGP/Shocker2Connected", False),
                                    (P + "OGP/ShockerConnected", False)]

    def test_unplugging_the_hub_takes_everything_down(self):
        h = DeviceHost(features=("feature_pishock",))
        hub = h.pishock_engine
        hub.is_connected, hub.listed = True, [4711]
        h.state()
        h.take()
        hub.is_connected = False
        h.state()
        assert sorted(h.take()) == [(P + "OGP/Shocker1Connected", False),
                                    (P + "OGP/ShockerConnected", False)]

    def test_an_openshock_list_counts_only_while_its_hub_is_connected(self):
        h = DeviceHost(features=("feature_pishock",))
        h.pishock_settings.openshock = [{"id": 900}]
        h.state()
        assert h.on_wire() == {"OGP/ShockerConnected": False,
                               "OGP/Shocker1Connected": False}
        hub = h.pishock_engine
        hub.is_connected, hub.hub_kind, hub.listed = True, "openshock", [900]
        h.state()
        assert h.on_wire()["OGP/Shocker1Connected"] is True


class TestEverythingTogether:
    def test_an_avatar_swap_gets_every_device_again(self):
        h = DeviceHost()
        h.owo_engine.is_connected = True
        h.state()
        h.take()
        h.presence_send_all()
        names = {a[len(P):] for a, _v in h.take()}
        assert {"OGP/BHapticsConnected", "OGP/BHapticsVestConnected",
                "OGP/OWOConnected", "OGP/ShockerConnected"} <= names

    def test_quitting_says_nothing_is_connected(self):
        h = DeviceHost()
        h.owo_engine.is_connected = True
        h.bhaptics_engine.positions = {"VestFront"}
        h.state()
        h.take()
        h.presence_shutdown()
        assert sorted(h.take()) == [(P + "OGP/BHapticsConnected", False),
                                    (P + "OGP/BHapticsVestConnected", False),
                                    (P + "OGP/OWOConnected", False)]

    def test_a_toy_and_a_suit_given_one_name_share_it(self):
        h = DeviceHost()
        h.mode_manager.wiring["Lush"] = {}
        h.set_toy_connected_param("Lush", True, "Live")
        h.set_device_connected_param(tp.SLOT_OWO, True, "Live")
        h.owo_engine.is_connected = True
        h.state()
        assert h.on_wire()["Live"] is True
        h.haptic_engine.names = ["Lush"]
        h.owo_engine.is_connected = False
        h.state()
        assert h.on_wire()["Live"] is True       # the toy still holds it


class TestWiredIntoTheApp:
    def test_the_app_class_carries_the_facade(self):
        import inspect
        import main
        assert issubclass(main.OscGoesPurrrApp, PresenceFacade)
        src = inspect.getsource(main.OscGoesPurrrApp)
        # Toys arriving and leaving, a suit's, the hub's and the PSVR2
        # headset's state, the link coming up, an avatar loading, a toy
        # deleted or a feature switched, and quitting.
        assert src.count("self.presence_on_devices_changed()") == 5
        assert src.count("self.presence_send_all()") == 2
        assert "self.presence_shutdown()" in src
        assert src.count("self.presence_sync()") == 2
        from controllers.intiface_facade import IntifaceFacade
        assert "self.presence_on_devices_changed()" in inspect.getsource(
            IntifaceFacade.update_connection_status)

    def test_the_pages_own_changes_bring_it_along(self):
        """You have (which parts get one) and the OpenShock list (which
        shockers do, while the hub is unplugged) change no engine state."""
        import inspect
        from controllers.pishock_facade import PiShockFacade
        from controllers.suits_facade import SuitsFacade
        assert "presence_sync" in inspect.getsource(SuitsFacade.set_bhaptics_have)
        for fn in (PiShockFacade.add_openshock_shocker, PiShockFacade.set_openshock_shocker,
                   PiShockFacade.delete_openshock_shocker):
            assert "_pishock_presence_follow()" in inspect.getsource(fn)
