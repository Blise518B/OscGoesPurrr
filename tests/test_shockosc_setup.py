"""The ShockOSC setup and feedback wiring (controllers/shockosc_facade.py)
and the settings it adds to (a touch's hold time, the Pull): the worn
avatar's ShockOSC groups offered with what each becomes, one click adding
what's missing -- nothing without it, nothing more on a second -- a dropped
shocker winning over the name match, and the feedback told which groups
and parameters to send."""

import queue

import pytest

import controllers.shockosc_facade as sf
import controllers.shockosc_sync as sync
from controllers.pishock_facade import FEATURE_KEY, PiShockFacade
from parameter_store import ParameterStore
from settings.pishock import (
    PiShockSettingsManager, clean_pull, clean_trigger, physbone_name,
)

AVATAR = {"ShockOsc/Collar", "ShockOsc/Collar_IShock", "ShockOsc/Collar_CVibrate",
          "ShockOsc/Collar_Active", "ShockOsc/Collar_Intensity",
          "ShockOsc/Tail_IsGrabbed", "ShockOsc/Tail_Stretch",
          "ShockOsc/_All_ISound", "ShockOsc/_Any_Active", "ShockOsc/Glow_Active",
          "Contact/Headpat"}


class Osc:
    is_connected = True

    def __init__(self):
        self.sent = []

    def send_parameter(self, address, value, ignore_rate_limit=False, **_k):
        self.sent.append((address, value))


class Host(PiShockFacade):
    def __init__(self):
        self.thread_queue = queue.Queue()
        self.logged = []
        self._features = {FEATURE_KEY: False}
        self.osc_manager = Osc()

    def is_output_off(self):
        return False

    def get_feature_enabled(self, key):
        return self._features.get(key, True)

    def log_message(self, msg):
        self.logged.append(msg)

    def get_current_avatar_id(self):
        return "avtr_00000000-0000-4000-8000-000000000001"


@pytest.fixture
def host(monkeypatch):
    listed = {"names": set(AVATAR)}
    monkeypatch.setattr(sf.vrchat_avatars, "avatar_parameters",
                        lambda _aid, *a, **k: listed["names"])
    shared = ParameterStore()
    monkeypatch.setattr(sf, "store", shared)
    monkeypatch.setattr(sync, "store", shared)
    h = Host()
    h._pishock_init()
    h._shockosc_shocker_names = lambda: [(24325, "Collar"), (24326, "Thigh")]
    h.listed = listed
    yield h
    h._pishock_shutdown()


def test_the_card_lists_the_avatars_groups(host):
    setup = host.get_shockosc_setup()
    assert setup["source"] == "file"
    groups = {g["name"]: g for g in setup["groups"]}
    assert list(groups) == ["Collar", "Tail", "_All"]             # every shocker last
    assert groups["Collar"]["makes"] == ["touch", "shock at once", "continuous vibrate"]
    assert groups["Collar"]["suggested"] == [24325]             # the shocker named Collar
    assert groups["Tail"]["makes"] == ["pull"] and groups["Tail"]["suggested"] == []
    assert groups["_All"]["label"] == "All shockers" and groups["_All"]["suggested"] == "all"
    assert all(g["missing"] == g["total"] for g in groups.values())
    assert "Glow" not in groups                                 # feedback only: nothing to set up


def test_nothing_is_set_up_without_the_click(host):
    host.get_shockosc_setup()
    host.shockosc_avatar_changed()
    assert all(not any(r["param"].startswith("ShockOsc/") for r in host.get_pishock_rules(k))
               for k in ("triggers", "continuous", "pulls"))


def test_one_click_sets_it_all_up_and_a_second_adds_nothing(host):
    added = host.shockosc_set_up({"Tail": [24326]})
    assert added == 5
    triggers = {r["param"]: r for r in host.get_pishock_rules("triggers")}
    assert triggers["ShockOsc/Collar"]["shockers"] == [24325]
    # a new Contact's own values (Blise's call, 2026-11-16), but ShockOSC's
    # hold time for its touch (2026-11-17)
    assert (triggers["ShockOsc/Collar"]["intensity"],
            triggers["ShockOsc/Collar"]["hold_ms"]) == (20, 250)
    assert triggers["ShockOsc/Collar_IShock"]["op"] == "shock"
    assert triggers["ShockOsc/_All_ISound"]["op"] == "beep"
    assert triggers["ShockOsc/_All_ISound"]["shockers"] == "all"
    cont = host.get_pishock_rules("continuous")
    assert [(r["param"], r["op"]) for r in cont] == [("ShockOsc/Collar_CVibrate", "vibrate")]
    pulls = host.get_pishock_rules("pulls")
    assert [(r["param"], r["shockers"]) for r in pulls] == [("ShockOsc/Tail", [24326])]
    assert "ShockOsc/Tail_IsGrabbed" in host.pishock_router._keys      # the router has them
    assert any("set up 5 behaviours" in m for m in host.logged)
    # again: nothing more, nothing changed
    before = PiShockSettingsManager().get_all_rules()
    assert host.shockosc_set_up({"Tail": [24325]}) == 0
    assert PiShockSettingsManager().get_all_rules() == before
    assert all(g["missing"] == 0 for g in host.get_shockosc_setup()["groups"])


def test_a_behaviour_made_by_hand_is_kept(host):
    idx = host.add_pishock_rule("triggers")
    rule = host.get_pishock_rules("triggers")[idx]
    host.set_pishock_rule("triggers", idx, dict(rule, param="ShockOsc/Collar", intensity=55))
    host.shockosc_set_up()
    mine = [r for r in host.get_pishock_rules("triggers") if r["param"] == "ShockOsc/Collar"]
    assert len(mine) == 1 and mine[0]["intensity"] == 55


def test_an_avatar_without_shockosc_offers_nothing(host):
    host.listed["names"] = {"Contact/Headpat"}
    assert host.get_shockosc_setup()["groups"] == []
    assert host.shockosc_set_up() == 0


def test_the_card_says_which_settings_are_kept_in_step(host):
    assert host.get_shockosc_setup()["synced"] == []          # none on this avatar
    host.listed["names"] = set(AVATAR) | {"ShockOsc/_Config/_All/Intensity",
                                          "ShockOsc/_Config/_All/CooldownTime",
                                          "ShockOsc/_Config/Collar/Paused"}
    assert host.get_shockosc_setup()["synced"] == ["Intensity", "CooldownTime", "Paused"]


# --- the feedback's groups --------------------------------------------------------

def test_the_feedback_sends_what_the_avatar_has(host):
    fb = host.shockosc_feedback
    host.shockosc_set_up({"Tail": [24326]})
    # groups with behaviours, and Glow (feedback only: the shocker named so -- none)
    assert fb._groups["Collar"] == [24325]
    assert fb._groups["Glow"] == []
    assert "Tail" in fb._groups and fb._any
    assert fb._only == {"ShockOsc/Collar_Active", "ShockOsc/Collar_Intensity",
                        "ShockOsc/_Any_Active", "ShockOsc/Glow_Active"}
    fb.tick()
    sent = {a for a, _v in host.osc_manager.sent}
    assert sent == {"/avatar/parameters/" + n for n in fb._only}


def test_an_avatar_with_nothing_to_light_gets_nothing(host):
    host.listed["names"] = {"ShockOsc/Collar_IShock"}
    host.shockosc_avatar_changed()
    assert host.shockosc_feedback._groups == {} and not host.shockosc_feedback._any
    host.shockosc_feedback.tick()
    assert host.osc_manager.sent == []


def test_without_the_avatars_file_the_behaviours_groups_get_everything(host):
    host.shockosc_set_up({})
    host.listed["names"] = None
    host.shockosc_avatar_changed()
    fb = host.shockosc_feedback
    assert set(fb._groups) == {"Collar", "Tail", "_All"} and fb._only is None


def test_an_avatar_change_resends(host):
    host.shockosc_set_up({})
    fb = host.shockosc_feedback
    fb.tick()
    n = len(host.osc_manager.sent)
    assert n
    host.osc_manager.sent.clear()
    fb.tick()
    assert host.osc_manager.sent == []
    host.shockosc_avatar_changed()
    fb.tick()
    assert len(host.osc_manager.sent) == n


def test_the_feature_going_off_rests_the_feedback(host):
    host.shockosc_set_up({})
    fb = host.shockosc_feedback
    fb.tick()
    fb._sent["ShockOsc/Collar_Active"] = True           # as if a shock was showing
    host.osc_manager.sent.clear()
    host._pishock_stop()
    assert ("/avatar/parameters/ShockOsc/Collar_Active", False) in host.osc_manager.sent


# --- the settings ------------------------------------------------------------------

def test_a_contacts_hold_time_is_kept_and_clamped():
    assert clean_trigger({})["hold_ms"] == 0
    assert clean_trigger({"hold_ms": 250})["hold_ms"] == 250
    assert clean_trigger({"hold_ms": 99999})["hold_ms"] == 2000
    assert clean_trigger({"hold_ms": "junk"})["hold_ms"] == 0


def test_a_pull_is_cleaned():
    r = clean_pull({"param": "/avatar/parameters/ShockOsc/Tail_IsGrabbed",
                    "min_int": 80, "max_int": 20, "held_op": "explode"})
    assert r["param"] == "ShockOsc/Tail"
    assert (r["min_int"], r["max_int"]) == (20, 80)
    assert r["held_op"] == "vibrate" and r["op"] == "shock"     # ShockOSC's let-go
    assert clean_pull({"op": "beep", "held_op": "none"})["held_op"] == "none"
    assert r["shockers"] == []                                  # none until dropped


@pytest.mark.parametrize("picked, name", [
    ("ShockOsc/Tail_IsGrabbed", "ShockOsc/Tail"), ("Tail_Stretch", "Tail"),
    ("Ear_L_Angle", "Ear_L"), ("Tail", "Tail"), ("_Stretch", "_Stretch"),
])
def test_physbone_name(picked, name):
    assert physbone_name(picked) == name


def test_a_new_pull_and_several_at_once():
    s = PiShockSettingsManager()
    assert s.get_rules("pulls") == []
    s.add_rule("pulls")
    assert s.get_rules("pulls")[0]["op"] == "shock"
    assert s.add_rules([("triggers", {"param": "A"}), ("nope", {}), ("pulls", {"param": "B"})]) == 2
    again = PiShockSettingsManager()
    assert [r["param"] for r in again.get_rules("pulls")] == ["", "B"]
    assert again.get_rules("triggers")[-1]["param"] == "A"


def test_undo_treats_shockosc_behaviours_like_every_other_behaviour():
    """Ctrl+Z (settings_history): behaviours coming back -- a Pull, the
    ShockOSC setup's, a shorter touch -- ask nothing, as no behaviour does
    (that is Blise's open call for all of them); the limits and switches
    still ask as before."""
    from settings.pishock import history_asks
    base = PiShockSettingsManager().settings
    contact = clean_trigger({"param": "ShockOsc/Collar", "op": "shock", "hold_ms": 250,
                             "shockers": [7]})
    pull = clean_pull({"param": "ShockOsc/Tail", "shockers": "all"})
    with_them = {**base, "triggers": [contact], "pulls": [pull]}
    assert history_asks(base, with_them) == []                   # redo of the setup
    shorter = {**with_them, "triggers": [dict(contact, hold_ms=0)]}
    assert history_asks(with_them, shorter) == []
    assert [a.text for a in history_asks(with_them, {**with_them, "armed": True})] \
        == ["arms shocks"]


def test_behaviour_names_for_the_log_name_a_pull_too():
    from pishock_router import behaviour_name
    assert behaviour_name("pulls", {"name": "Pull", "param": "ShockOsc/Tail"}) == "Pull · Tail"
    assert behaviour_name("pulls", {"name": "Tail · pull", "param": "ShockOsc/Tail"}) == (
        "Pull · Tail · pull")
    assert behaviour_name("triggers", {"name": "Collar · touch", "param": "ShockOsc/Collar"}) \
        == "Contact · Collar · touch"
    assert behaviour_name("mystery", {}) == "Mystery"
