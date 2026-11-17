"""ShockOSC's settings and the Shockers behaviours' values, one value each,
kept in step both ways (controllers/shockosc_sync.py; Blise's call,
2026-11-16): the avatar's menu (or a friend's YOLO set) changes the
behaviours, saved; the page changes the avatar's; `_All` is the default a
group follows unless the avatar has the group's own; OGP first after an
avatar loads; never an echo; Paused is On / Off, the global one a kill
switch."""

import queue
import time

import pytest

import controllers.shockosc_facade as sf
import controllers.shockosc_sync as sync
from controllers.pishock_facade import FEATURE_KEY, PiShockFacade
from parameter_store import ParameterStore
from settings.pishock import PiShockSettingsManager

P = "/avatar/parameters/"
GLOBAL = {f"ShockOsc/_Config/_All/{s}" for s in (
    "Paused", "Intensity", "Duration", "CooldownTime", "HoldTime")}
AVATAR = {"ShockOsc/Collar", "ShockOsc/Collar_IShock", "ShockOsc/Collar_CVibrate",
          "ShockOsc/Tail_IsGrabbed", "ShockOsc/Tail_Stretch", "ShockOsc/_All_ISound",
          "Contact/Headpat"} | GLOBAL


class Osc:
    is_connected = True

    def __init__(self):
        self.sent = []

    def send_parameter(self, address, value, ignore_rate_limit=False, **_k):
        self.sent.append((address, value))

    def last(self, name):
        return next((v for a, v in reversed(self.sent) if a == P + name), None)


class Host(PiShockFacade):
    def __init__(self):
        self.thread_queue = queue.Queue()
        self.logged = []
        self._features = {FEATURE_KEY: True}
        self.osc_manager = Osc()
        self._ogp_mode_guard_until = 0.0

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
    h._features[FEATURE_KEY] = False            # no threads: the init only
    h._pishock_init()
    h._features[FEATURE_KEY] = True
    h._shockosc_shocker_names = lambda: [(24325, "Collar"), (24326, "Tail")]
    h.listed, h.said = listed, shared
    h.shockosc_set_up({})                       # sends OGP's values to the avatar
    h.osc_manager.sent.clear()
    h._sosc_sent.clear()                        # long ago: not an echo any more
    while not h.thread_queue.empty():
        h.thread_queue.get_nowait()
    yield h
    h._pishock_shutdown()


def rules(kind):
    return {r["param"]: r for r in PiShockSettingsManager().get_rules(kind)}


def heard(host, name, value):
    """VRChat says the avatar's `name` is `value` (what the OSC thread
    hands the main thread)."""
    host.said.update_parameter(name, value)
    host._shockosc_config_heard(name, value)


def queued(host):
    out = []
    while not host.thread_queue.empty():
        out.append(host.thread_queue.get_nowait()[0])
    return out


# --- the avatar's menu -> the behaviours -------------------------------------------

def test_the_avatars_intensity_changes_every_group_following_all(host):
    heard(host, "ShockOsc/_Config/_All/Intensity", 0.45)
    t, c, p = rules("triggers"), rules("continuous"), rules("pulls")
    assert t["ShockOsc/Collar"]["intensity"] == 45
    assert t["ShockOsc/Collar_IShock"]["intensity"] == 45
    assert t["ShockOsc/_All_ISound"]["intensity"] == 45
    assert c["ShockOsc/Collar_CVibrate"]["max_int"] == 45
    assert p["ShockOsc/Tail"]["max_int"] == 45
    assert "shockosc_rules" in queued(host)              # the page redraws
    assert host.osc_manager.sent == []                   # nothing sent back


def test_length_rest_hold_from_the_avatar(host):
    heard(host, "ShockOsc/_Config/_All/Duration", 0.2)          # 2 s
    heard(host, "ShockOsc/_Config/_All/CooldownTime", 0.05)     # 5 s
    heard(host, "ShockOsc/_Config/_All/HoldTime", 0.3)          # 0.3 s
    t = rules("triggers")
    assert t["ShockOsc/Collar_IShock"]["duration_ms"] == 2000
    assert rules("pulls")["ShockOsc/Tail"]["duration_ms"] == 2000
    assert t["ShockOsc/Collar_IShock"]["rest_ms"] == 5000
    assert rules("continuous")["ShockOsc/Collar_CVibrate"]["rest_ms"] == 5000
    assert t["ShockOsc/Collar"]["hold_ms"] == 300               # the touch only
    assert t["ShockOsc/Collar_IShock"]["hold_ms"] == 0
    # the router has the new values at once
    assert any(p.rest_ms == 5000 for p in host.pishock_router._compiled.pulse_triggers)


def test_a_group_with_its_own_setting_goes_with_that(host):
    host.listed["names"] = AVATAR | {"ShockOsc/_Config/Collar/Intensity"}
    heard(host, "ShockOsc/_Config/Collar/Intensity", 0.6)
    heard(host, "ShockOsc/_Config/_All/Intensity", 0.1)
    t = rules("triggers")
    assert t["ShockOsc/Collar"]["intensity"] == 60
    assert t["ShockOsc/Collar_IShock"]["intensity"] == 60
    assert t["ShockOsc/_All_ISound"]["intensity"] == 10
    assert rules("pulls")["ShockOsc/Tail"]["max_int"] == 10


def test_strength_0_from_the_avatar_is_kept_and_sends_nothing(host):
    heard(host, "ShockOsc/_Config/_All/Intensity", 0.0)
    assert rules("triggers")["ShockOsc/Collar_IShock"]["intensity"] == 0
    assert rules("pulls")["ShockOsc/Tail"]["min_int"] == 0           # bottom follows down


def test_a_value_above_a_cap_is_kept_the_engine_holds_the_cap(host):
    host.pishock_settings.set_limit("max_intensity", 25)
    heard(host, "ShockOsc/_Config/_All/Intensity", 1.0)
    assert rules("triggers")["ShockOsc/Collar_IShock"]["intensity"] == 100
    assert host.pishock_settings.get_limits()["max_intensity"] == 25   # untouched


def test_the_global_paused_is_a_kill_switch(host):
    idx = host.add_pishock_rule("triggers")              # a behaviour of your own
    host.set_pishock_rule("triggers", idx, dict(host.get_pishock_rules("triggers")[idx],
                                                param="Contact/Boop"))
    host.listed["names"] = AVATAR | {"ShockOsc/_Config/Tail/Paused"}
    heard(host, "ShockOsc/_Config/_All/Paused", True)
    t = rules("triggers")
    assert not any(r["enabled"] for p, r in t.items() if p.startswith("ShockOsc/"))
    assert not rules("pulls")["ShockOsc/Tail"]["enabled"]   # even with its own Paused
    assert t["Contact/Boop"]["enabled"]                      # not ShockOSC's
    heard(host, "ShockOsc/_Config/_All/Paused", False)
    t = rules("triggers")
    assert all(r["enabled"] for r in t.values())
    assert not rules("pulls")["ShockOsc/Tail"]["enabled"]   # goes with its own Paused
    heard(host, "ShockOsc/_Config/Tail/Paused", False)
    assert rules("pulls")["ShockOsc/Tail"]["enabled"]


def test_a_friends_yolo_set_counts_like_the_avatars_menu(host):
    host._shockosc_heard_set("ShockOsc/_Config/_All/Intensity", 0.7)
    host._shockosc_heard_set("Contact/Headpat", True)          # not a setting: nothing
    msgs = []
    while not host.thread_queue.empty():
        msgs.append(host.thread_queue.get_nowait())
    assert msgs == [("shockosc_config", ("ShockOsc/_Config/_All/Intensity", 0.7))]
    host._shockosc_config_heard(*msgs[0][1])
    assert rules("triggers")["ShockOsc/Collar_IShock"]["intensity"] == 70


def test_the_osc_thread_only_queues_settings(host):
    host._shockosc_on_osc(P + "ShockOsc/_Config/_All/Duration", 0.3)
    host._shockosc_on_osc(P + "ShockOsc/_Config/Paused", True)
    host._shockosc_on_osc(P + "ShockOsc/Collar", True)
    assert [m[1][0] for m in [host.thread_queue.get_nowait() for _ in range(2)]] == [
        "ShockOsc/_Config/_All/Duration", "ShockOsc/_Config/Paused"]
    assert host.thread_queue.empty()


def test_nothing_while_the_shockers_feature_is_off(host):
    host._features[FEATURE_KEY] = False
    heard(host, "ShockOsc/_Config/_All/Intensity", 0.9)
    assert rules("triggers")["ShockOsc/Collar_IShock"]["intensity"] == 20


# --- the page -> the avatar --------------------------------------------------------

def edit(host, kind, param, **changes):
    listed = host.get_pishock_rules(kind)
    idx = next(i for i, r in enumerate(listed) if r["param"] == param)
    host.set_pishock_rule(kind, idx, dict(listed[idx], **changes))


def test_a_page_edit_moves_its_partners_and_the_avatar(host):
    edit(host, "triggers", "ShockOsc/Collar_IShock", intensity=33, duration_ms=1200)
    t = rules("triggers")
    assert t["ShockOsc/Collar"]["intensity"] == 33
    assert t["ShockOsc/_All_ISound"]["intensity"] == 33
    assert rules("pulls")["ShockOsc/Tail"]["max_int"] == 33
    assert rules("pulls")["ShockOsc/Tail"]["duration_ms"] == 1200
    osc = host.osc_manager
    assert osc.last("ShockOsc/_Config/_All/Intensity") == pytest.approx(0.33)
    assert osc.last("ShockOsc/_Config/_All/Duration") == pytest.approx(0.12)
    assert "shockosc_rules" in queued(host)


def test_an_edit_on_a_behaviour_of_your_own_goes_nowhere(host):
    idx = host.add_pishock_rule("triggers")
    host.osc_manager.sent.clear()
    host.set_pishock_rule("triggers", idx, dict(host.get_pishock_rules("triggers")[idx],
                                                param="Contact/Boop", intensity=77))
    assert host.osc_manager.sent == []
    assert rules("triggers")["ShockOsc/Collar_IShock"]["intensity"] == 20


def test_on_off_sends_paused_only_when_all_are_off(host):
    edit(host, "triggers", "ShockOsc/Collar_IShock", enabled=False)
    assert host.osc_manager.last("ShockOsc/_Config/_All/Paused") is None    # others still on
    assert rules("triggers")["ShockOsc/Collar"]["enabled"]                  # not dragged along
    for kind, param in (("triggers", "ShockOsc/Collar"), ("triggers", "ShockOsc/_All_ISound"),
                        ("continuous", "ShockOsc/Collar_CVibrate"), ("pulls", "ShockOsc/Tail")):
        edit(host, kind, param, enabled=False)
    assert host.osc_manager.last("ShockOsc/_Config/_All/Paused") is True
    edit(host, "pulls", "ShockOsc/Tail", enabled=True)
    assert host.osc_manager.last("ShockOsc/_Config/_All/Paused") is False


def test_the_hold_time_is_every_touchs(host):
    host.listed["names"] = AVATAR | {"ShockOsc/Tail"}
    host.shockosc_set_up({})                               # Tail's touch too
    edit(host, "triggers", "ShockOsc/Collar", hold_ms=400)
    assert rules("triggers")["ShockOsc/Tail"]["hold_ms"] == 400
    assert rules("triggers")["ShockOsc/Collar_IShock"]["hold_ms"] == 0
    assert host.osc_manager.last("ShockOsc/_Config/_All/HoldTime") == pytest.approx(0.4)


# --- OGP first, never an echo ------------------------------------------------------

def test_after_an_avatar_loads_ogps_values_go_first(host):
    edit(host, "triggers", "ShockOsc/Collar_IShock", intensity=40, rest_ms=3000)
    host.osc_manager.sent.clear()
    host.shockosc_avatar_changed()
    osc = host.osc_manager
    assert osc.last("ShockOsc/_Config/_All/Intensity") == pytest.approx(0.40)
    assert osc.last("ShockOsc/_Config/_All/CooldownTime") == pytest.approx(0.03)
    assert osc.last("ShockOsc/_Config/_All/Paused") is False
    # the touches' ShockOSC hold time (Blise's call, 2026-11-17)
    assert osc.last("ShockOsc/_Config/_All/HoldTime") == pytest.approx(0.25)
    # VRChat replays the avatar's saved values: answered with OGP's
    host._ogp_mode_guard_until = time.monotonic() + 5
    osc.sent.clear()
    heard(host, "ShockOsc/_Config/_All/Intensity", 0.9)
    assert rules("triggers")["ShockOsc/Collar_IShock"]["intensity"] == 40
    assert osc.sent == [(P + "ShockOsc/_Config/_All/Intensity", pytest.approx(0.40))]


def test_ogps_own_value_coming_back_is_no_hand(host):
    edit(host, "triggers", "ShockOsc/Collar_IShock", intensity=33)
    edit(host, "triggers", "ShockOsc/Collar_IShock", intensity=40)
    heard(host, "ShockOsc/_Config/_All/Intensity", 0.33)       # a late echo of the first
    heard(host, "ShockOsc/_Config/_All/Intensity", 0.40)
    assert rules("triggers")["ShockOsc/Collar"]["intensity"] == 40


def test_the_mode_moves_where_the_strength_goes(host):
    host.listed["names"] = AVATAR | {"ShockOsc/_Config/_All/MaxIntensity",
                                     "ShockOsc/_Config/_All/MinIntensity",
                                     "ShockOsc/_Config/_All/ModeIntensity"}
    edit(host, "triggers", "ShockOsc/Collar_IShock", intensity=50)
    assert host.osc_manager.last("ShockOsc/_Config/_All/Intensity") == pytest.approx(0.5)
    heard(host, "ShockOsc/_Config/_All/ModeIntensity", True)        # the avatar: a range
    assert host.osc_manager.last("ShockOsc/_Config/_All/MaxIntensity") == pytest.approx(0.5)
    assert host.osc_manager.last("ShockOsc/_Config/_All/MinIntensity") == pytest.approx(0.05)
    heard(host, "ShockOsc/_Config/_All/MinIntensity", 0.2)
    assert rules("pulls")["ShockOsc/Tail"]["min_int"] == 20
    assert rules("triggers")["ShockOsc/Collar_IShock"]["intensity"] == 50   # no bottom


def test_without_the_avatars_settings_nothing_is_kept_in_step(host):
    host.listed["names"] = AVATAR - GLOBAL
    edit(host, "triggers", "ShockOsc/Collar_IShock", intensity=61)
    assert host.osc_manager.sent == []
    assert rules("triggers")["ShockOsc/Collar"]["intensity"] == 20    # each its own


def test_a_set_through_avatar_remote_is_handed_to_the_sync(monkeypatch):
    """Every set OGP makes for a friend (YOLO, the board, the menu's slots)
    goes through ParamsFacade._params_send: a ShockOSC setting among them
    reaches the sync like the avatar's own menu."""
    import controllers.params_facade as pf
    monkeypatch.setattr(pf, "store", ParameterStore())
    handed = []

    class Fake:
        osc_manager = Osc()
        _shockosc_heard_set = staticmethod(lambda n, v: handed.append((n, v)))

    fake = Fake()
    assert pf.ParamsFacade._params_send(fake, "ShockOsc/_Config/_All/Intensity", "float", 0.8)
    assert pf.ParamsFacade._params_send(fake, "Hat", "bool", True)
    assert handed == [("ShockOsc/_Config/_All/Intensity", 0.8), ("Hat", True)]
    assert fake.osc_manager.sent[0] == (P + "ShockOsc/_Config/_All/Intensity", 0.8)


# --- Paused stops at once --------------------------------------------------------

def test_paused_going_on_stops_what_those_behaviours_run(host, monkeypatch):
    stops = []
    monkeypatch.setattr(host.pishock_router, "stop_shockosc", lambda g=None: stops.append(g))
    host.listed["names"] = AVATAR | {"ShockOsc/_Config/Tail/Paused"}
    heard(host, "ShockOsc/_Config/Tail/Paused", True)          # a group's own
    assert stops == [{"Tail"}]
    assert not rules("pulls")["ShockOsc/Tail"]["enabled"]
    heard(host, "ShockOsc/_Config/_All/Paused", True)          # the kill switch
    assert stops == [{"Tail"}, None]
    heard(host, "ShockOsc/_Config/_All/Paused", False)         # back on: nothing to stop
    assert stops == [{"Tail"}, None]


def test_paused_ends_a_pulse_already_playing_on_the_real_engine(host, monkeypatch, store_and_rig):
    """End to end: a ShockOSC shock is playing on the hub; the avatar's
    Paused stops the shocker at once, while a friend's hold on another
    shocker goes on."""
    router, eng, link, clock, store = store_and_rig
    host.pishock_router, host.pishock_engine = router, eng
    store.update_parameter("ShockOsc/Collar_IShock", True)
    clock.t += 0.01
    router.tick()
    assert (111, "shock", 20, 500) in link.sent
    eng.hold(222, "vibrate", 30, source="friend")
    link.sent.clear()
    heard(host, "ShockOsc/_Config/_All/Paused", True)
    clock.t += 0.01
    router.tick()
    assert (111, "end") in link.sent                  # the playing shock: stopped now
    assert (222, "end") not in link.sent              # the friend's hold: untouched
    assert not rules("triggers")["ShockOsc/Collar_IShock"]["enabled"]


@pytest.fixture
def store_and_rig(host, monkeypatch):
    """A real PiShockEngine on a fake hub (shockers 111, 222) and a router
    on the host's rules, sharing the host's parameter store."""
    import pishock_router
    import router_base
    from pishock_engine import PiShockEngine
    from pishock_router import PiShockRouter

    class Link:
        def __init__(self):
            self.sent, self.port, self.is_open, self.kind = [], "COM9", True, "pishock"

        def set_openshock_shockers(self, _s):
            pass

        def open(self, port, handshake_timeout_s=6.0):
            return {"version": "3.1", "shockers": [{"id": 111, "paused": False},
                                                   {"id": 222, "paused": False}]}

        def operate(self, sid, op, intensity, duration_ms):
            self.sent.append((sid, op, intensity, duration_ms))
            return True

        def end(self, sid):
            self.sent.append((sid, "end"))
            return True

        def close(self):
            self.is_open = False

    class Clock:
        t = 100.0

        def __call__(self):
            return self.t

    store = host.said
    monkeypatch.setattr(pishock_router, "store", store)
    monkeypatch.setattr(router_base, "store", store)
    monkeypatch.setattr(router_base.StaleSignalMonitor, "is_stale", lambda self: False)
    clock, link = Clock(), Link()
    eng = PiShockEngine(link_factory=lambda **_k: link, clock=clock)
    eng.set_port("COM9")
    eng._want_connected = True
    eng._try_connect()
    eng.set_armed(True)
    for kind in ("triggers", "continuous", "pulls"):
        for i, r in enumerate(host.get_pishock_rules(kind)):
            if r["param"].startswith("ShockOsc/Collar"):
                host.set_pishock_rule(kind, i, dict(r, shockers=[111]))
    router = PiShockRouter(eng, get_rules=host.pishock_settings.get_all_rules,
                           is_output_off=lambda: False, clock=clock)
    router.tick()                                       # baseline
    return router, eng, link, clock, store
