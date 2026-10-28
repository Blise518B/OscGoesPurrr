"""The Friends facade's rules: who may drive what, Pause and Off, stale
levels, the strength slider, and every shock going through the shocker
engine within the receiver's own caps."""

import queue
import time

import pytest

import remote_protocol as proto
from constants import OGP_FRIEND_LEVEL_PARAMETER
from controllers.friends_common import Drive
from controllers.friends_facade import FriendsFacade

A = "a" * 64
B = "b" * 64
ME = "c" * 64


class FakeLink:
    def __init__(self):
        self.pushed, self.events, self.answers = [], [], []
        self.contacts = None
        self.running, self.online, self.error, self.my_id = True, True, "", ME
        self._peers = {}

    def peers(self):
        return self._peers

    def push_cmd(self, peer):
        self.pushed.append(peer)

    def send_event(self, peer, msg, repeat=3):
        self.events.append((peer, msg))

    def set_contacts(self, ids):
        self.contacts = list(ids)

    def answer(self, peer, ok):
        self.answers.append((peer, ok))

    def pair_with(self, peer, invite=""):
        self.paired = peer
        self.invite = invite

    def set_nickname(self, nick):
        pass

    def stop(self, timeout=1.5):
        self.running = False

    def start(self, nick, contacts, unfriended=()):
        self.running = True
        self.contacts = list(contacts)
        self.unfriended = list(unfriended)

    def set_unfriended(self, ids):
        self.unfriended = list(ids)

    def forget_identity(self):
        self.my_id = "d" * 64
        return True

    def drop(self, peer, reason=b"nolink"):
        self.dropped = getattr(self, "dropped", []) + [(peer, reason)]


class FakeShockers:
    def __init__(self):
        self.is_connected, self.is_armed = True, False
        self.pulses, self.holds, self.released, self.ended = [], [], [], []

    own = {}                    # a shocker's own caps, by id

    def limits(self):
        return {"max_intensity": 40, "max_pulse_ms": 2000, "cooldown_s": 1.0,
                "max_hold_s": 5.0, "hold_rest_s": 1.0}

    def limits_for(self, sid):
        lim = self.limits()
        return {"max_intensity": lim["max_intensity"],
                "max_vibrate": lim.get("max_vibrate", lim["max_intensity"]),
                "max_pulse_ms": lim["max_pulse_ms"], **self.own.get(sid, {})}

    def shocker_ids(self):
        return [s["id"] for s in self.shockers()]

    def shockers(self):
        return [{"id": 11, "name": "Collar"}, {"id": 22}]

    def pulse(self, sid, op, intensity, ms):
        self.pulses.append((sid, op, intensity, ms))
        return True

    def hold(self, sid, op, intensity):
        self.holds.append((sid, op, intensity))

    def release(self, sid):
        self.released.append(sid)

    def end(self, sid):
        self.ended.append(sid)


class Host(FriendsFacade):
    def __init__(self, **features):
        self.thread_queue = queue.Queue()
        self.ui = None
        self.logs = []
        self._features = {"feature_friends": True, "feature_pishock": True, **features}
        self._off = False
        self.strength = 1.0
        self.strength_calls = []
        self._needs_recalculation = False
        self.pishock_engine = FakeShockers()
        self._friends_init()
        self.friends_link = FakeLink()

    def get_feature_enabled(self, key):
        return self._features.get(key, True)

    def set_feature_enabled(self, key, on):
        self._features[key] = bool(on)
        if key == "feature_friends":
            self._friends_feature_changed(bool(on))

    def is_output_off(self):
        return self._off

    def get_strength(self):
        return self.strength

    def set_strength(self, value, source="ui"):
        self.strength = value
        self.strength_calls.append((value, source))

    def log_message(self, msg):
        self.logs.append(msg)

    def befriend(self, peer, toys=True, shock=False):
        self.friends_settings.add_friend(peer, "Alex" if peer == A else "Sam")
        self.friends_settings.set_permission(peer, "toys", toys)
        self.friends_settings.set_permission(peer, "shock", shock)
        self._friends_rebuild_perms()

    def drain(self):
        while not self.thread_queue.empty():
            kind, data = self.thread_queue.get()
            if kind == "friends":
                self._friends_on_queue(*data)

    def log_text(self):
        return " | ".join(e["text"] for e in self.get_friends_log())


def cmd(levels, strength=None):
    return proto.make_cmd(levels, strength)


# --- toys ------------------------------------------------------------------

def test_a_friends_level_drives_the_toys():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.4, "Edge": 0.8}))
    assert h.get_friend_drive("Edge") == 0.8
    assert h.get_friend_drive("Hush") == 0.4
    assert h._needs_recalculation


def test_strangers_and_friends_without_the_toys_switch_drive_nothing():
    h = Host()
    h.befriend(A, toys=False)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 1.0}))
    h._friends_on_event("message", B, cmd({proto.ALL_TOYS: 1.0}))
    assert h.get_friend_drive("Edge") == 0.0


def test_every_allowed_friend_at_once_the_highest_wins():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    h._friends_on_event("message", A, cmd({"Edge": 0.3}))
    h._friends_on_event("message", B, cmd({proto.ALL_TOYS: 0.6}))
    assert h.get_friend_drive("Edge") == 0.6
    h._friends_on_event("message", B, cmd({}))
    assert h.get_friend_drive("Edge") == 0.3


def test_a_silent_friend_drives_nothing():
    h = Host()
    h.befriend(A)
    h._friend_drive = {A: Drive({proto.ALL_TOYS: 1.0}, time.monotonic() - proto.DRIVE_STALE_S - 0.1)}
    assert h.get_friend_drive("Edge") == 0.0


def test_pause_and_switching_toys_off_stop_the_drive():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 1.0}))
    h.set_friends_paused(True)
    assert h.get_friend_drive("Edge") == 0.0
    h.set_friends_paused(False)
    assert h.get_friend_drive("Edge") == 1.0
    h.set_friend_permission(A, "toys", False)
    assert h.get_friend_drive("Edge") == 0.0


def test_going_offline_drops_the_drive():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 1.0}))
    h._friends_on_event("unlinked", A, "timeout")
    assert h.get_friend_drive("Edge") == 0.0
    assert "went offline" in h.log_text()


# --- strength --------------------------------------------------------------

def test_strength_applies_once_per_change():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, cmd({}, (5, 0.3)))
    h._friends_on_event("message", A, cmd({}, (5, 0.3)))     # the resend
    h._friends_on_event("message", A, cmd({}, (4, 0.9)))     # older, late
    h.drain()
    assert h.strength_calls == [(0.3, "friend")]
    h._friends_on_event("message", A, cmd({}, (6, 0.7)))
    h.drain()
    assert h.strength_calls[-1] == (0.7, "friend")
    assert "set your strength to 70 %" in h.log_text()


def test_strength_needs_the_toys_switch_and_no_pause():
    h = Host()
    h.befriend(A, toys=False)
    h._friends_on_event("message", A, cmd({}, (5, 0.3)))
    h.befriend(B)
    h.set_friends_paused(True)
    h._friends_on_event("message", B, cmd({}, (5, 0.3)))
    h.drain()
    assert h.strength_calls == []


# --- shocks ----------------------------------------------------------------

def shock(sid="s1", slots=(0,), intensity=1.0, length=1.0):
    return proto.make_shock(sid, list(slots), intensity, length)


def test_shocks_need_the_shockers_switch():
    h = Host()
    h.befriend(A, shock=False)          # switched off on their card
    h._friends_on_event("message", A, shock())
    assert h.pishock_engine.pulses == []
    assert "held back: shocks from them are switched off" in h.log_text()


def test_a_shock_fires_once_within_the_receivers_caps():
    h = Host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, shock("x1", (0, 1), 1.0, 1.0))
    h._friends_on_event("message", A, shock("x1", (0, 1), 1.0, 1.0))   # repeat
    assert h.pishock_engine.pulses == [(11, "shock", 40, 2000), (22, "shock", 40, 2000)]
    assert "vibrate 40 (shocks aren't armed)" in h.log_text()


def test_shocks_are_held_back_by_off_pause_and_a_missing_hub():
    for setup in (lambda h: setattr(h, "_off", True),
                  lambda h: h.set_friends_paused(True),
                  lambda h: h._features.__setitem__("feature_pishock", False),
                  lambda h: setattr(h.pishock_engine, "is_connected", False)):
        h = Host()
        h.befriend(A, shock=True)
        setup(h)
        h._friends_on_event("message", A, shock())
        assert h.pishock_engine.pulses == []
        assert "held back" in h.log_text()


# --- what goes out -----------------------------------------------------------

def test_status_goes_only_to_friends_and_shockers_only_when_allowed():
    h = Host()
    h.befriend(A)
    h._my_state = h._build_my_state()
    assert h._friends_status_for(B) is None
    st = h._friends_status_for(A)
    assert st["allow"] == {"toys": True, "shock": False}
    assert "shk" not in st
    h.set_friend_permission(A, "shock", True)
    assert h._friends_status_for(A)["shk"] == ["Collar", "Shocker 22"]


def test_my_levels_and_strength_ride_the_cmd():
    h = Host()
    h.befriend(A)
    h.set_friend_level(A, proto.ALL_TOYS, 0.5)
    h.set_friend_strength(A, 0.25)
    out = h._friends_cmd_for(A)
    assert out["lvl"] == {proto.ALL_TOYS: 0.5}
    assert out["str"][1] == 0.25
    assert h.friends_link.pushed == [A, A]
    h.set_friend_level(A, proto.ALL_TOYS, 0.0)
    assert h._friends_cmd_for(A)["lvl"] == {}
    assert h._friends_cmd_for(B) is None


def test_shocking_a_friend_needs_their_permission():
    h = Host()
    h.befriend(A)
    assert not h.friend_shock(A, [0], 0.5, 0.5)
    h._friend_status = {A: proto.read_status(proto.make_status(
        [], {}, 1.0, False, False, True, True, ["Collar"], False, 40, 2000))}
    assert h.friend_shock(A, [0], 0.5, 0.5)
    peer, msg = h.friends_link.events[0]
    assert peer == A and msg["t"] == "shk" and msg["slots"] == [0]
    assert "their shocks aren't armed" in h.log_text()


def test_a_nickname_can_change_but_never_go_empty():
    h = Host()
    h.friends_link.running = True      # skip starting a real link
    assert h.set_friends_nickname("  Blise  ") == "Blise"
    assert h.set_friends_nickname("   ") == "Blise"
    assert h.friends_settings.get_nickname() == "Blise"


def test_accepting_a_request_makes_a_friend():
    h = Host()
    h._friends_on_event("request", B, "Sam")
    h.friends_answer(B, True)
    assert B in h.friends_settings.friend_ids()
    assert h.friends_link.contacts == [B]
    assert h.friends_link.answers == [(B, True)]
    # both switches on for a new friend; arming on the Shockers page is the gate
    assert h.friends_settings.get_friend(B)["toys"] is True
    assert h.friends_settings.get_friend(B)["shock"] is True


# --- the VRChat menu's Friends submenu: it acts on what is selected ---------

def linked_with_toys(h, peer, allow_shock=True):
    h._friend_status = {**h._friend_status, peer: proto.read_status(proto.make_status(
        [("Edge", 2), ("Hush", 1)], {}, 1.0, False, False, True, allow_shock,
        ["Collar", "Cuff"], True, 40, 2000))}


def test_menu_level_drives_the_selected_friend():
    h = Host()
    h.befriend(A)                       # the first friend starts selected
    h.befriend(B)
    h.set_friends_selected("friend", B)
    h._friends_on_osc("OGP/Friend/Level", 0.7)
    assert h._friends_cmd_for(B)["lvl"] == {proto.ALL_TOYS: 0.7}
    assert h._friends_cmd_for(A)["lvl"] == {}


def test_menu_drives_every_member_of_a_selected_group():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    gid = h.friends_add_group("Pair")   # a new group is selected
    h.set_group_member(gid, A, True)
    h.set_group_member(gid, B, True)
    linked_with_toys(h, A)
    linked_with_toys(h, B, allow_shock=False)
    h._friends_on_osc("OGP/Friend/Level", 0.5)
    h._friends_on_osc("OGP/Friend/Strength", 0.3)
    h._friends_on_osc("OGP/Friend/Shock", True)
    for peer in (A, B):
        assert h._friends_cmd_for(peer)["lvl"] == {proto.ALL_TOYS: 0.5}
        assert h._friends_cmd_for(peer)["str"][1] == 0.3
    # only the friend who allows shocks gets one
    assert [peer for peer, _ in h.friends_link.events] == [A]


def test_a_group_panel_acts_on_every_member():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    gid = h.friends_add_group("Pair")
    h.set_group_member(gid, A, True)
    h.set_group_member(gid, B, True)
    linked_with_toys(h, A)
    linked_with_toys(h, B)
    h.set_targets_level(0.6)
    h.set_targets_strength(0.2)
    assert h.targets_shock([0], 0.5, 0.5) == 2
    for peer in (A, B):
        assert h._friends_cmd_for(peer)["lvl"] == {proto.ALL_TOYS: 0.6}
        assert h._friends_cmd_for(peer)["str"][1] == 0.2
    h.set_group_member(gid, A, False)
    h.set_group_member(gid, B, False)
    assert h.targets_shock([0], 0.5, 0.5) == 0
    assert "nobody selected allows it" in h.log_text()


def test_a_party_drives_the_shockers_it_names_in_real_seconds():
    # PiShock's Party Mode: shockers of several friends, a length in real
    # time -- each friend's own longest pulse at most
    h = Host()
    h.befriend(A)
    h.befriend(B)
    h._friend_status = {
        A: {"allow_shock": True, "shockers": ["Collar", "Thigh"], "armed": True,
            "max_intensity": 40, "max_pulse_ms": 2100},
        B: {"allow_shock": True, "shockers": ["Collar"], "armed": False,
            "max_intensity": 60, "max_pulse_ms": 10000}}
    assert h.party_shock([(A, 0), (A, 1), (B, 0)], "shock", 0.5, 5000) == 2
    sent = {peer: msg for peer, msg in h.friends_link.events}
    assert sent[A]["slots"] == [0, 1] and sent[A]["len"] == 1.0         # capped at 2.1 s
    assert sent[B]["slots"] == [0] and sent[B]["len"] == round(4900 / 9900, 3)   # 5 s of 10
    h.party_hold([(B, 0)], "vibrate", 0.4)
    assert h._my_holds[B] == {0: ("vibrate", 0.4)}
    h.party_release([(B, 0)])
    assert h._my_holds[B] == {}
    h._friend_status = {}
    assert h.party_shock([(A, 0)], "shock", 0.5, 300) == 0
    assert "nobody in the party allows it" in h.log_text()


def test_menu_toy_toggles_pick_which_toys(monkeypatch):
    h = Host()
    h.befriend(A)
    linked_with_toys(h, A)
    h._friends_on_osc("OGP/Friend/Level", 0.5)
    assert h._friends_cmd_for(A)["lvl"] == {proto.ALL_TOYS: 0.5}   # all four on: every toy
    h._friends_on_osc("OGP/Friend/Toy1", False)
    h._friends_on_osc("OGP/Friend/Toy3", False)
    h._friends_on_osc("OGP/Friend/Toy4", False)
    assert h._friends_cmd_for(A)["lvl"] == {"Hush": 0.5}           # only their toy 2
    h._friends_on_osc("OGP/Friend/Toy2", False)
    assert h._friends_cmd_for(A)["lvl"] == {}


def test_menu_buttons_fire_once_per_press_on_the_ticked_shockers():
    h = Host()
    h.befriend(A)
    linked_with_toys(h, A)
    h._friends_on_osc("OGP/Friend/Shocker3", False)
    h._friends_on_osc("OGP/Friend/Shocker4", False)
    h._friends_on_osc("OGP/Friend/ShockStrength", 1.0)
    h._friends_on_osc("OGP/Friend/Shock", True)
    h._friends_on_osc("OGP/Friend/Shock", True)       # still held
    h._friends_on_osc("OGP/Friend/Shock", False)
    h._friends_on_osc("OGP/Friend/Vibrate", True)
    h._friends_on_osc("OGP/Friend/Beep", True)
    ops = [(m["slots"], m.get("op", "shock"), m["int"]) for _, m in h.friends_link.events]
    assert ops == [([0, 1], "shock", 1.0), ([0, 1], "vibrate", 1.0), ([0, 1], "beep", 1.0)]
    h._friends_on_osc("OGP/Friend/StopShock", True)
    assert h.friends_link.events[-1][1]["t"] == "stp"


def test_menu_warning_puts_small_warnings_before_shocks():
    h = Host()
    h.befriend(A)
    linked_with_toys(h, A)
    h._friends_on_osc("OGP/Friend/Warning", True)
    h._friends_on_osc("OGP/Friend/Shock", True)
    msg = h.friends_link.events[-1][1]
    assert msg["warn"] == "vibrate" and 1000 <= msg["wms"] <= 3000


def test_menu_auto_modes_speed_range_and_stop():
    h = Host()
    h.befriend(A)
    linked_with_toys(h, A)
    h._friends_on_osc("OGP/Friend/Range", 0.6)
    h._friends_on_osc("OGP/Friend/Mode", 2)                         # Square
    cmd = h._friends_cmd_for(A)
    assert cmd["pat"][proto.ALL_TOYS][0] == "square" and cmd["pat"][proto.ALL_TOYS][3] == 0.6
    assert cmd["lvl"] == {}
    slow = cmd["pat"][proto.ALL_TOYS][1]
    h._friends_on_osc("OGP/Friend/Speed", 1.0)
    assert h._friends_cmd_for(A)["pat"][proto.ALL_TOYS][1] < slow
    h._friends_on_osc("OGP/Friend/Override", True)
    assert h._friends_cmd_for(A)["ovr"] == [proto.ALL_TOYS]
    h._friends_on_osc("OGP/Friend/Level", 0.4)                      # direct control again
    assert "pat" not in h._friends_cmd_for(A)
    assert h._friends_cmd_for(A)["lvl"] == {proto.ALL_TOYS: 0.4}
    h._friends_on_osc("OGP/Friend/Mode", 8)                         # Oscillate around Level
    lo, hi = h._friends_cmd_for(A)["pat"][proto.ALL_TOYS][2:]
    assert (lo, hi) == pytest.approx((0.1, 0.7))
    h._friends_on_osc("OGP/Friend/StopToys", True)
    assert h._friends_cmd_for(A)["lvl"] == {} and "pat" not in h._friends_cmd_for(A)


def test_both_of_us_drives_you_and_them():
    h = Host()
    h.befriend(A, shock=True)
    linked_with_toys(h, A)
    h._friends_on_osc("OGP/Both/Level", 0.5)
    assert h._friends_cmd_for(A)["lvl"] == {proto.ALL_TOYS: 0.5}
    assert h.get_friend_drive_mode("Your Lush") == (0.5, False)     # your own toys too
    h.set_friends_paused(True)                                       # pausing friends isn't you
    assert h.get_friend_drive("Your Lush") == 0.5
    h.set_friends_paused(False)
    h._friends_on_osc("OGP/Both/Mode", 1)
    assert h.friends_need_tick()
    assert h._friends_cmd_for(A)["pat"][proto.ALL_TOYS][0] == "sine"
    h._friends_on_osc("OGP/Both/Stop", True)
    assert h.get_friend_drive("Your Lush") == 0.0 and not h.friends_need_tick()
    assert h._friends_cmd_for(A)["lvl"] == {}


def test_both_of_us_shocks_you_and_them():
    h = Host()
    h.befriend(A, shock=True)
    linked_with_toys(h, A)
    h._friends_on_osc("OGP/Both/Strength", 1.0)
    h._friends_on_osc("OGP/Both/Shock", True)
    assert h.friends_link.events[-1][1]["int"] == 1.0                # them
    assert h.pishock_engine.pulses[0][:3] == (11, "shock", 40)       # you, within your caps
    assert "You (Both of us): vibrate 40 (shocks aren't armed)" in h.log_text()
    h._off = True
    h._friends_on_osc("OGP/Both/Vibrate", True)
    assert "not on you - Off is on" in h.log_text()


def test_menu_ignores_the_avatar_reload_replay():
    h = Host()
    h.befriend(A)
    h._ogp_mode_guard_until = time.monotonic() + 5
    h._friends_on_osc("OGP/Friend/Level", 0.9)
    h._friends_on_osc("OGP/Friend/Strength", 0.85)
    assert h._friends_cmd_for(A)["lvl"] == {}
    assert "str" not in h._friends_cmd_for(A)


def test_changing_the_selection_moves_the_menu_level():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    h._friends_on_osc("OGP/Friend/Level", 0.4)        # A is selected
    gid = h.friends_add_group("Pair")                 # selects the (empty) group
    assert h._friends_cmd_for(A)["lvl"] == {}
    h.set_group_member(gid, B, True)                  # B joins: the level follows
    assert h._friends_cmd_for(B)["lvl"] == {proto.ALL_TOYS: 0.4}
    h.set_group_member(gid, B, False)
    assert h._friends_cmd_for(B)["lvl"] == {}
    h.set_friends_selected("friend", A)
    assert h._friends_cmd_for(A)["lvl"] == {proto.ALL_TOYS: 0.4}
    h.friends_delete_group(gid)
    assert "deleted the group Pair" in h.log_text()


# --- invite links ----------------------------------------------------------

def test_an_invite_is_accepted_once_and_makes_them_a_friend():
    h = Host()
    code = h.friends_settings.new_invite()
    assert h._friends_invite_ok(A, code, "Alex")
    assert not h._friends_invite_ok(B, code, "Sam")          # once only
    h.drain()
    assert A in h.friends_settings.friend_ids()
    assert h.friends_link.contacts == [A]
    assert not h.friends_settings.invite_valid(code)
    assert "Alex joined with your invite link" in h.log_text()


def test_unknown_or_expired_invites_ask_as_usual():
    h = Host()
    assert not h._friends_invite_ok(A, "0" * 16, "Alex")
    code = h.friends_settings.new_invite(now=time.time() - 25 * 3600)
    assert not h._friends_invite_ok(A, code, "Alex")
    h.drain()
    assert h.friends_settings.friend_ids() == []


def test_the_copied_invite_is_the_link_and_a_note_with_a_fresh_code():
    h = Host()
    h.friends_settings.set_nickname("Blise")
    msg = h.friends_invite_message()
    assert msg.startswith("https://") and ME in msg
    assert msg.endswith("\n(Add Blise on OscGoesPurrr)")
    code = msg.split(ME + ".", 1)[1].split(".", 1)[0]
    assert h.friends_settings.invite_valid(code)
    assert h.friends_invite_message() != msg                  # a new one each time


def test_pasting_an_invite_link_dials_with_its_code():
    import friend_links
    h = Host()
    h.friends_settings.set_nickname("Sam")
    assert h.friends_add(friend_links.invite_message(A, "1" * 16, "Alex")) == ""
    assert (h.friends_link.paired, h.friends_link.invite) == (A, "1" * 16)
    assert "own invite" in h.friends_add(friend_links.web_link(ME, "1" * 16, "me"))


def test_a_clicked_invite_waits_for_the_nickname():
    import friend_links
    h = Host()
    h.friends_link.running = False
    h.friends_open_link(friend_links.app_link(A, "2" * 16, "Alex"))
    assert h.get_friends_status()["pending_invite"] == "Alex"
    assert not hasattr(h.friends_link, "paired")
    h.friends_link.running = True                             # the nickname starts the link
    h.set_friends_nickname("Sam")
    assert (h.friends_link.paired, h.friends_link.invite) == (A, "2" * 16)
    assert h.get_friends_status()["pending_invite"] == ""


def test_an_invite_from_a_friend_just_picks_them():
    import friend_links
    h = Host()
    h.friends_settings.set_nickname("Sam")
    h.befriend(A)
    h.befriend(B)
    h.friends_open_link(friend_links.app_link(B, "3" * 16, "Sam"))
    assert not hasattr(h.friends_link, "paired")
    assert h.friends_settings.get_selected() == {"kind": "friend", "id": B}


def test_day_week_and_forever_links_let_several_friends_in():
    h = Host()
    for kind in ("day", "week", "forever"):
        h2 = Host()
        code = h2.friends_settings.new_invite(kind)
        assert h2._friends_invite_ok(A, code, "Alex")
        assert h2._friends_invite_ok(B, code, "Sam")
        h2.drain()
        assert set(h2.friends_settings.friend_ids()) == {A, B}
        assert h2.friends_settings.get_invites()[0]["uses"] == 2
    msg = h.friends_invite_message("week")
    assert "for a week" in h.log_text() and msg


def test_closing_the_links_keeps_the_friends():
    h = Host()
    h.befriend(A)
    code = h.friends_settings.new_invite("forever")
    h.friends_close_invites()
    assert not h._friends_invite_ok(B, code, "Sam")
    assert h.friends_settings.friend_ids() == [A]
    assert h.get_friends_status()["invites"] == []


def test_a_new_id_unfriends_everyone_and_kills_the_links():
    h = Host()
    h.friends_settings.set_nickname("Blise")
    h.befriend(A)
    h.befriend(B)
    gid = h.friends_settings.add_group("Crew", [A, B])
    code = h.friends_settings.new_invite("forever")
    h.friends_reset_id()
    assert h.friends_settings.friend_ids() == [] and h.friends_settings.get_group(gid) is None
    assert not h._friends_invite_ok(A, code, "Alex")
    assert h.friends_link.my_id == "d" * 64 and h.friends_link.running
    assert h.friends_link.contacts == []
    assert "new ID - 2 friends unlinked" in h.log_text()


# --- unfriending -----------------------------------------------------------

def test_unfriending_tells_the_link_who_not_to_let_back_by_redial():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    gid = h.friends_settings.add_group("Crew", [A, B])
    h.friends_remove(A)
    assert h.friends_settings.friend_ids() == [B]
    assert h.friends_settings.get_group(gid)["members"] == [B]
    assert h.friends_link.contacts == [B] and h.friends_link.unfriended == [A]
    assert "You unfriended Alex" in h.log_text()
    h.befriend(A)                                        # added again: no longer unfriended
    h._friends_contacts_changed()
    assert h.friends_link.unfriended == []


def test_a_friend_who_unfriends_you_leaves_your_list_too():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.5}))
    h._friends_on_event("unlinked", A, "removed")
    h._friends_on_event("removed", A, None)
    h.drain()
    assert h.friends_settings.friend_ids() == []
    assert h.friends_link.unfriended == []               # they did it, not you
    assert h.get_friend_drive("Edge") == 0.0
    text = h.log_text()
    assert "Alex unfriended you" in text and "went offline" not in text


# --- the Online switch -----------------------------------------------------

def test_offline_means_no_link_and_back_online_starts_it():
    h = Host()
    h.friends_settings.set_nickname("Sam")
    h.set_friends_online(False)
    assert not h.friends_link.running
    assert h.get_friends_status()["online_switch"] is False
    h._friends_maybe_start()                             # e.g. a feature toggle
    assert not h.friends_link.running
    h.set_friends_online(True)
    assert h.friends_link.running
    assert "You went online" in h.log_text()


def test_clicking_an_invite_while_offline_goes_online_for_it():
    import friend_links
    h = Host()
    h.friends_settings.set_nickname("Sam")
    h.set_friends_online(False)
    h.friends_open_link(friend_links.app_link(A, "4" * 16, "Alex"))
    assert h.friends_settings.get_online() and h.friends_link.running
    assert (h.friends_link.paired, h.friends_link.invite) == (A, "4" * 16)


# --- override, auto modes ---------------------------------------------------

def test_override_counts_only_while_they_drive_that_toy():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, proto.make_cmd({"Edge": 0.4}, None, override={"Edge"}))
    assert h.get_friend_drive_mode("Edge") == (0.4, True)
    assert h.get_friend_drive_mode("Hush") == (0.0, False)
    h._friends_on_event("message", A, proto.make_cmd({}, None, override={"*"}))
    assert h.get_friend_drive_mode("Edge") == (0.0, False)   # Override alone mutes nothing


def test_an_auto_mode_plays_on_the_receivers_side():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, proto.make_cmd(
        {}, None, override={"*"}, patterns={"*": ("square", 0.5, 0.2, 0.8)}))
    assert h.friends_need_tick()
    seen = set()
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.6:
        level, over = h.get_friend_drive_mode("Edge")
        seen.add(round(level, 2))
        assert over
    assert seen == {0.2, 0.8}
    assert h._is_driving(A, time.monotonic())
    h._friend_drive = {A: h._friend_drive[A]._replace(levels={}, t=time.monotonic() - 5)}
    assert not h.friends_need_tick() and h.get_friend_drive("Edge") == 0.0


def test_a_new_speed_keeps_the_cycle_where_it_is():
    from friend_patterns import anchor, play
    a = anchor(("saw", 2.0, 0.0, 1.0), None, 100.0)
    level = play(a, 101.0)                                # halfway up the ramp
    b = anchor(("saw", 4.0, 0.0, 1.0), a, 101.0)
    assert play(b, 101.0) == pytest.approx(level)
    c = anchor(("sine", 4.0, 0.0, 1.0), b, 101.0)
    assert c["ph0"] == 0.0                                # a new wave starts over


def test_what_you_set_goes_out_in_the_cmd():
    h = Host()
    h.befriend(A)
    h.set_friend_override(A, "Edge", True)
    h.set_friend_pattern(A, "*", "heart", 1.0, 0.1, 0.6)
    h.friend_hold(A, [1], "vibrate", 0.5)
    over, pats, holds = proto.read_cmd_more(h._friends_cmd_for(A))
    assert over == {"Edge"} and pats["*"][0] == "heart" and holds == {1: ("vibrate", 0.5)}
    h.friend_stop(A, [1])
    assert proto.read_cmd_more(h._friends_cmd_for(A))[2] == {}
    assert h.friends_link.events[-1][1]["t"] == "stp"
    h.set_friend_pattern(A, "*", "")
    assert proto.read_cmd_more(h._friends_cmd_for(A))[1] == {}
    status = next(f for f in h.get_friends_status()["friends"] if f["id"] == A)
    assert status["my_override"] == {"Edge"}


# --- shocker ops, warnings, holds, stop -----------------------------------

def test_vibrate_uses_their_vibrate_cap(monkeypatch):
    h = Host()
    h.befriend(A, shock=True)
    h.pishock_engine.limits = lambda: {"max_intensity": 40, "max_vibrate": 90, "max_pulse_ms": 2000,
                                       "cooldown_s": 1.0}
    h._friends_on_event("message", A, proto.make_shock("v1", [0], 1.0, 0.0, op="vibrate"))
    h._friends_on_event("message", A, proto.make_shock("b1", [1], 0.0, 0.0, op="beep"))
    assert h.pishock_engine.pulses == [(11, "vibrate", 90, 100), (22, "beep", 1, 100)]


def test_a_warning_vibrates_for_its_length_then_the_shock_goes():
    h = Host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_shock(
        "w1", [0], 1.0, 1.0, warn="vibrate", warn_intensity=1.0, warn_ms=2500))
    t0 = time.monotonic()
    h._pump_friend_holds(t0)
    assert h.pishock_engine.holds == [(11, "vibrate", 40)] and h.pishock_engine.pulses == []
    h._pump_friend_holds(t0 + 2.6)
    assert h.pishock_engine.released == [11]
    assert h.pishock_engine.pulses == [(11, "shock", 40, 2000)]
    assert "warning 2.5 s, then shock" in h.log_text()


def test_a_stop_during_the_warning_means_no_shock():
    h = Host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_shock("w2", [0], 1.0, 1.0, warn="vibrate",
                                                        warn_ms=3000))
    h._friends_on_event("message", A, proto.make_stop("s1", [0]))
    h._pump_friend_holds(time.monotonic() + 5)
    assert h.pishock_engine.pulses == [] and h.pishock_engine.ended == [11]
    assert "stopped Collar" in h.log_text()


def test_the_level_radial_switches_to_direct_control():
    h = Host()
    h.befriend(A)
    h.friends_settings.set_selected("friend", A)
    h.set_friend_pattern(A, "*", "sine", 2.0, 0.1, 0.9)
    h.set_friend_pattern(A, "Edge", "square", 1.0, 0.0, 1.0)
    h._friends_on_osc(OGP_FRIEND_LEVEL_PARAMETER, 0.6)
    assert h._my_patterns[A] == {}
    assert h._my_levels[A] == {proto.ALL_TOYS: 0.6}


def test_sending_a_warning_carries_its_length():
    h = Host()
    h.befriend(A)
    h._friend_status = {A: {"allow_shock": True, "shockers": ["Collar"], "armed": True,
                            "max_intensity": 40, "max_pulse_ms": 2000}}
    assert h.friend_shock(A, [0], 0.5, 0.5, "shock", 4200, 0.3)
    msg = h.friends_link.events[-1][1]
    assert (msg["warn"], msg["wms"]) == ("vibrate", 4200)
    assert "4.2 s warning, then shock" in h.log_text()


def test_a_held_shocker_runs_while_held_and_lets_go(monkeypatch):
    h = Host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={0: ("vibrate", 1.0)}))
    h._pump_friend_holds(time.monotonic())
    assert h.pishock_engine.holds == [(11, "vibrate", 40)]
    h._friends_on_event("message", A, proto.make_cmd({}, None))
    h._pump_friend_holds(time.monotonic())
    assert h.pishock_engine.released == [11]
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={1: ("shock", 0.0)}))
    h._pump_friend_holds(time.monotonic() + proto.DRIVE_STALE_S + 0.5)   # they went quiet
    assert h.pishock_engine.holds == [(11, "vibrate", 40)]


def test_holds_need_the_shockers_switch_too():
    h = Host()
    h.befriend(A, shock=False)
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={0: ("shock", 1.0)}))
    h._pump_friend_holds(time.monotonic())
    assert h.pishock_engine.holds == []


# --- an invite clicked before you have a nickname --------------------------

class _PromptUI:
    def __init__(self):
        self.prompts, self.views = [], []

    def prompt_friends_invite(self, who, nickname, friends_off):
        self.prompts.append((who, nickname, friends_off))

    def select_view(self, name):
        self.views.append(name)

    def show_window(self):
        pass


def test_an_invite_without_a_nickname_asks_for_one_and_links():
    import friend_links
    h = Host()
    h.ui = _PromptUI()
    h.friends_link.running = False
    h.friends_open_link(friend_links.app_link(A, "5" * 16, "Alex"))
    assert h.ui.prompts == [("Alex", "", False)]
    assert h.accept_friends_invite("   ") == "Type a nickname first."
    h.friends_link.running = True                       # the nickname starts the link
    assert h.accept_friends_invite("Sam") == ""
    assert h.friends_settings.get_nickname() == "Sam"
    assert (h.friends_link.paired, h.friends_link.invite) == (A, "5" * 16)
    assert h.ui.views[-1] == "Friends"
    h._friends_on_queue("linked", (A, "Alex"))         # their invite let us in
    assert h.friends_settings.get_selected() == {"kind": "friend", "id": A}


def test_an_invite_while_friends_is_off_switches_it_on():
    import friend_links
    h = Host(feature_friends=False)
    h.ui = _PromptUI()
    h.friends_settings.set_nickname("Sam")
    h.friends_open_link(friend_links.app_link(A, "6" * 16, "Alex"))
    assert h.ui.prompts == [("Alex", "Sam", True)]
    assert h.accept_friends_invite("Sam") == ""
    assert h.get_feature_enabled("feature_friends")
    assert (h.friends_link.paired, h.friends_link.invite) == (A, "6" * 16)


def test_with_a_nickname_an_invite_links_without_asking():
    import friend_links
    h = Host()
    h.ui = _PromptUI()
    h.friends_settings.set_nickname("Sam")
    h.befriend(B)
    h.friends_open_link(friend_links.app_link(A, "7" * 16, "Alex"))
    assert h.ui.prompts == [] and h.ui.views == ["Friends"]
    assert (h.friends_link.paired, h.friends_link.invite) == (A, "7" * 16)
    h._friends_on_queue("linked", (A, "Alex"))
    assert h.friends_settings.get_selected() == {"kind": "friend", "id": A}


# --- the avatar's menu -------------------------------------------------------

def test_the_app_sees_whether_the_avatar_has_the_menu(monkeypatch):
    import controllers.friends_menu as ff
    from parameter_store import ParameterStore
    fresh = ParameterStore()
    monkeypatch.setattr(ff, "store", fresh)
    h = Host()
    assert h.get_avatar_menu() == {"known": False, "self": False, "friends": False}
    fresh.rebuild_from_json({"CONTENTS": {"avatar": {"CONTENTS": {"parameters": {"CONTENTS": {
        "OGP": {"CONTENTS": {"Strength": {"VALUE": [1.0]},
                             "Friend": {"CONTENTS": {"Level": {"VALUE": [0.0]}}}}},
        "VRCEmote": {"VALUE": [0]}}}}}}})
    assert h.get_avatar_menu() == {"known": True, "self": True, "friends": True}
    h._note_avatar_menu()
    assert "Your avatar has the OGP Friends menu" in h.log_text()
    assert h.get_friends_status()["avatar_menu"]["friends"] is True
    fresh.rebuild_from_json({"CONTENTS": {"avatar": {"CONTENTS": {"parameters": {"CONTENTS": {
        "VRCEmote": {"VALUE": [0]}}}}}}})
    h._note_avatar_menu()
    assert "This avatar has no OGP Friends menu" in h.log_text()


def test_friends_off_silences_the_menu_and_both_of_us():
    h = Host()
    h.befriend(A, shock=True)
    linked_with_toys(h, A)
    h._friends_on_osc("OGP/Both/Level", 0.5)
    assert h.get_friend_drive("Your Lush") == 0.5
    h.set_feature_enabled("feature_friends", False)
    assert h.get_friend_drive("Your Lush") == 0.0          # what ran stops
    h._friends_on_osc("OGP/Both/Level", 0.7)               # and the menu does nothing
    h._friends_on_osc("OGP/Both/Vibrate", True)
    h._friends_on_osc("OGP/Friend/Level", 0.7)
    assert h.get_friend_drive("Your Lush") == 0.0
    assert h.pishock_engine.pulses == [] and h._my_levels == {}


def test_switching_a_friends_shockers_off_cancels_their_warning():
    h = Host()
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, proto.make_shock(
        "w9", [0], 1.0, 1.0, warn="vibrate", warn_intensity=1.0, warn_ms=3000))
    t0 = time.monotonic()
    h._pump_friend_holds(t0)
    assert h.pishock_engine.holds == [(11, "vibrate", 40)]
    h.set_friend_permission(A, "shock", False)
    assert h.pishock_engine.released == [11]               # the warning stops now
    h._pump_friend_holds(t0 + 0.2)
    h._pump_friend_holds(t0 + 5)
    assert h.pishock_engine.holds == [(11, "vibrate", 40)]
    assert h.pishock_engine.pulses == []                    # and its shock never comes


def test_both_of_us_warns_you_even_while_friends_are_paused():
    # Pause all is about friends; Both of us on you is your own say-so, so
    # its shock (which still goes) keeps its warning.
    h = Host()
    h.befriend(A, shock=True)
    linked_with_toys(h, A)
    h.set_friends_paused(True)
    h._friends_on_osc("OGP/Friend/Warning", True)
    h._friends_on_osc("OGP/Both/Shock", True)
    t0 = time.monotonic()
    h._pump_friend_holds(t0)
    assert h.pishock_engine.holds and h.pishock_engine.holds[0][1] == "vibrate"
    h._pump_friend_holds(t0 + 3.1)
    assert sorted((p[0], p[1]) for p in h.pishock_engine.pulses) == [(11, "shock"), (22, "shock")]


def test_a_pasted_id_given_up_on_is_logged():
    h = Host()
    h._friends_on_event("gave_up", A, None)
    assert "never answered" in h.log_text()


class _Shared:
    """pishock_settings' two Home switches: Share with friends, and On."""

    def __init__(self, on, enabled=True):
        self.on, self.enabled = on, enabled

    def get_friends_may_use(self):
        return self.on

    def get_enabled(self):
        return self.enabled


def test_homes_friends_may_use_them_switch_holds_back_every_friends_shock():
    h = Host()
    h.pishock_settings = _Shared(False)
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, shock())
    assert h.pishock_engine.pulses == []
    assert "held back: your shockers aren't shared with friends" in h.log_text()
    h._my_state = h._build_my_state()
    st = h._friends_status_for(A)
    assert st["allow"]["shock"] is False and "shk" not in st     # they see it's off
    h.pishock_settings.on = True
    h._friends_on_event("message", A, shock("s2"))
    assert h.pishock_engine.pulses


def test_a_drive_that_goes_quiet_is_a_drop_out_not_a_stop():
    h = Host()
    h.befriend(A)
    h._friends_on_event("message", A, cmd({"*": 0.5}))
    t0 = h._friend_drive[A].t
    h._note_drive_change(A, True, t0)
    assert "Alex started driving your toys" in h.log_text()
    h._note_drive_change(A, False, t0 + 1.2)               # nothing came: stale
    assert "Alex's control dropped out" in h.log_text()
    h._friends_on_event("message", A, cmd({"*": 0.5}))    # it arrives again
    h._note_drive_change(A, True, time.monotonic())
    assert "Alex's control is back after" in h.log_text()
    h._friends_on_event("message", A, cmd({}))            # a real stop
    h._note_drive_change(A, False, time.monotonic())
    assert h.log_text().startswith("Alex stopped driving your toys")    # newest first



# --- sync with others ----------------------------------------------------------

def scmd(levels, syn, patterns=None):
    """A cmd from someone who syncs, at panel version `syn`."""
    return proto.make_cmd(levels, None, patterns=patterns, syn=syn)


def two_who_sync():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    return h


def test_those_who_sync_play_the_newest_change_not_the_highest():
    h = two_who_sync()
    h._friends_on_event("message", A, scmd({"*": 0.8}, 1))
    h._friends_on_event("message", B, scmd({"*": 0.3}, 2))
    assert h.get_friend_drive("Edge") == pytest.approx(0.3)
    h._friends_on_event("message", A, scmd({"*": 0.5}, 3))
    assert h.get_friend_drive("Edge") == pytest.approx(0.5)


def test_off_is_a_change_too():
    h = two_who_sync()
    h._friends_on_event("message", A, scmd({"*": 0.8}, 1))
    h._friends_on_event("message", B, scmd({}, 2))          # B switched it off
    assert h.get_friend_drive("Edge") == 0.0


def test_on_a_tie_the_first_one_wins():
    h = two_who_sync()
    h._friends_on_event("message", A, scmd({"*": 0.8}, 2))
    h._friends_on_event("message", B, scmd({"*": 0.3}, 2))
    assert h.get_friend_drive("Edge") == pytest.approx(0.8)


def test_one_on_their_own_meets_the_shared_panel_as_before():
    h = two_who_sync()
    h._friends_on_event("message", A, scmd({"*": 0.3}, 1))
    h._friends_on_event("message", B, cmd({"*": 0.6}))      # Sync off: highest wins
    assert h.get_friend_drive("Edge") == pytest.approx(0.6)


def test_when_the_newest_goes_quiet_the_others_carry_on():
    h = two_who_sync()
    h._friends_on_event("message", B, scmd({"*": 0.3}, 2))
    h._friends_on_event("message", A, scmd({"*": 0.8}, 3))
    d = h._friend_drive[A]
    h._friend_drive = {**h._friend_drive,
                       A: d._replace(t=d.t - proto.DRIVE_STALE_S - 0.5)}
    assert h.get_friend_drive("Edge") == pytest.approx(0.3)


def test_they_hear_who_else_drives_and_the_shared_panel():
    h = two_who_sync()
    h._friends_on_event("message", A, scmd({"*": 0.8}, 4))
    h._friends_on_event("message", B, scmd({"*": 0.8}, 4))
    out = h._friends_sync_more_for(B)
    assert out["oth"]["n"] == ["Alex"]                       # never themselves
    seq, levels, _ovr, _pat = proto.read_panel(out["pnl"])
    assert seq == 4 and levels == {"*": 0.8}


def test_nothing_extra_goes_out_while_nobody_else_drives():
    h = two_who_sync()
    assert h._friends_sync_more_for(A) == {}
    h._friends_on_event("message", B, cmd({"*": 0.5}))       # B on their own
    assert h._friends_sync_more_for(A)["oth"]["n"] == ["Sam"]
    assert "pnl" not in h._friends_sync_more_for(A)          # A doesn't sync
    h._friends_on_event("message", B, cmd({}))               # B stops
    assert h._friends_sync_more_for(A)["oth"]["n"] == []     # said once it ended


def test_your_changes_raise_your_panel_version():
    h = Host()
    h.befriend(A)
    h.set_friend_level(A, proto.ALL_TOYS, 0.5)
    h.set_friend_pattern(A, "Edge", "sine")
    assert h._friends_cmd_for(A)["syn"] == 2
    h.set_friend_sync(A, False)
    assert "syn" not in h._friends_cmd_for(A)
    h.set_friend_level(A, proto.ALL_TOYS, 0.6)
    assert "syn" not in h._friends_cmd_for(A)


def test_a_newer_shared_panel_becomes_yours():
    h = Host()
    h.befriend(A)
    h.set_friend_level(A, proto.ALL_TOYS, 0.5)               # your version 1
    h._friend_panel_in(A, proto.make_panel(5, {"Edge": 0.7}, {"Edge"},
                                           {"Edge": ("sine", 2.0, 0.0, 1.0)}))
    assert h._my_levels[A] == {"Edge": 0.7} and h._my_override[A] == {"Edge"}
    assert h._my_patterns[A]["Edge"][0] == "sine"
    assert h._friends_cmd_for(A)["syn"] == 5
    h._friend_panel_in(A, proto.make_panel(3, {"Edge": 0.1}))   # older: yours stands
    assert h._my_levels[A] == {"Edge": 0.7}
    h.set_friend_level(A, "Edge", 0.2)                       # version 6 beats it
    assert h._friends_cmd_for(A)["syn"] == 6


def test_a_tie_lost_to_someone_else_takes_theirs():
    h = Host()
    h.befriend(A)
    h.set_friend_level(A, proto.ALL_TOYS, 0.5)               # version 1
    h._friend_panel_in(A, proto.make_panel(1, {proto.ALL_TOYS: 0.9}))
    assert h._my_levels[A] == {proto.ALL_TOYS: 0.9}


def test_without_sync_the_shared_panel_is_ignored():
    h = Host()
    h.befriend(A)
    h.set_friend_sync(A, False)
    h._friend_panel_in(A, proto.make_panel(9, {proto.ALL_TOYS: 0.9}))
    assert A not in h._my_levels or not h._my_levels[A]


def test_who_else_drives_them_reaches_your_panel():
    h = Host()
    h.befriend(A)
    h._friend_others_in(A, proto.make_others(["Sam", "Kim"]))
    assert h._friend_others[A] == ["Sam", "Kim"]


def test_two_controllers_end_up_on_one_panel():
    """A receiver and two friends who drive it, passing the real messages."""
    R = "e" * 64
    recv = two_who_sync()                       # Alex = A, Sam = B
    alex, sam = Host(), Host()
    alex.befriend(R)
    sam.befriend(R)

    def tick():
        for who, peer in ((alex, A), (sam, B)):
            recv._friends_on_event("message", peer, who._friends_cmd_for(R))
        for who, peer in ((alex, A), (sam, B)):
            for msg in recv._friends_sync_more_for(peer).values():
                who._friends_on_event("message", R, msg)

    alex.set_friend_level(R, proto.ALL_TOYS, 0.6)
    tick()
    assert sam._my_levels[R] == {proto.ALL_TOYS: 0.6}
    assert recv.get_friend_drive("Edge") == pytest.approx(0.6)
    tick()                                      # Sam now drives the shared panel too
    assert sam._friend_others[R] == ["Alex"] and alex._friend_others[R] == ["Sam"]
    sam.set_friend_pattern(R, proto.ALL_TOYS, "sine")
    tick()
    tick()
    assert alex._my_patterns[R][proto.ALL_TOYS][0] == "sine"
    assert alex._friends_cmd_for(R)["syn"] == sam._friends_cmd_for(R)["syn"]


def test_shockers_switched_off_on_home_vanish_for_friends():
    h = Host()
    h.pishock_settings = _Shared(True, enabled=False)        # Home's On / Off: off
    h.befriend(A, shock=True)
    h._friends_on_event("message", A, shock())
    assert h.pishock_engine.pulses == []
    assert "held back: your shockers are switched off" in h.log_text()
    h._my_state = h._build_my_state()
    st = h._friends_status_for(A)
    assert st["allow"]["shock"] is False and "shk" not in st    # their panel drops them
    h.pishock_settings.enabled = True
    assert h._friends_status_for(A)["allow"]["shock"] is True


def test_without_the_shockers_feature_friends_see_no_shockers():
    h = Host(feature_pishock=False)
    h.befriend(A, shock=True)
    h._my_state = h._build_my_state()
    assert h._friends_status_for(A)["allow"]["shock"] is False


# --- a column for everyone, and you on your own list -------------------------

def test_a_column_header_sets_everyone_off_first_then_on():
    h = Host()
    h.befriend(A, toys=True)
    h.befriend(B, toys=False)
    h._friends_on_event("message", A, cmd({"*": 0.5}))
    assert h.set_friend_permission_all("toys") is False      # any on: all off
    assert not h.friends_settings.get_friend(A)["toys"] and not h.friends_settings.get_friend(B)["toys"]
    assert h.get_friend_drive("Edge") == 0.0                 # A's drive let go
    assert h.set_friend_permission_all("toys") is True       # all off: all on
    assert h.friends_settings.get_friend(B)["toys"]
    assert "Every friend may now control your toys" in h.log_text()


def me_host():
    from controllers.friends_common import ME as ME_ROW
    from controllers.friends_me import MeLink
    h = Host()
    h.friends_link = MeLink(h, h.friends_link)
    h.set_friends_selected("friend", ME_ROW)
    h._my_state = h._build_my_state()
    h._me_tick()
    return h, ME_ROW


def test_you_are_always_a_working_row_on_your_own_list():
    h, me = me_host()
    st = h.get_friends_status()
    row = st["friends"][0]
    assert row["me"] and row["linked"] and st["selected"] == {"kind": "friend", "id": me}
    assert row["theirs"]["allow_toys"] and row["theirs"]["allow_shock"]
    h.set_friend_level(me, proto.ALL_TOYS, 0.5)              # straight back in, no network
    assert h.get_friend_drive("Edge") == pytest.approx(0.5)
    assert h.friends_link.pushed == []                       # nothing for the real link
    assert h.friend_shock(me, [0], 1.0, 1.0)
    assert h.pishock_engine.pulses and h.pishock_engine.pulses[0][0] == 11


def test_me_follows_the_rules_a_friend_does():
    h, me = me_host()
    h.set_friend_level(me, proto.ALL_TOYS, 0.5)
    h.set_friends_paused(True)
    assert h.get_friend_drive("Edge") == 0.0                 # Pause all friends holds for you too
    h.set_friends_paused(False)
    h._me_tick()
    assert h.get_friend_drive("Edge") == pytest.approx(0.5)


def test_me_is_never_named_to_real_friends():
    h, me = me_host()
    h.befriend(A)
    h.set_friend_level(me, proto.ALL_TOYS, 0.5)
    h._friends_on_event("message", A, cmd({"*": 0.3}))
    assert h._friends_sync_more_for(A).get("oth", {"n": []})["n"] == []
    assert h._friends_sync_more_for(me)["oth"]["n"] == ["Alex"]


def test_you_are_first_even_with_no_friends_and_old_files_lose_the_switch():
    h = Host()
    st = h.get_friends_status()
    assert [f.get("me") for f in st["friends"]] == [True]
    assert "me" not in h.friends_settings.settings          # "Add myself" is gone


# --- live levels: only to whoever has your panel open ------------------------

def levels_host():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    h._my_state = {**h._build_my_state(), "toys": [("Edge", 1)], "outputs": {"Edge": 0.6}}
    return h


def test_live_levels_go_only_to_a_friend_watching_my_panel():
    # Moving toys change them every tick: to everyone, that's a status 4x a
    # second per friend for nothing.
    h = levels_host()
    assert h._friends_status_for(A)["out"] == {}
    h._friends_on_event("message", A, proto.LEVELS_WATCH)
    assert h._friends_status_for(A)["out"] == {"Edge": 0.6}
    assert h._friends_status_for(B)["out"] == {}             # B isn't looking
    h._friends_on_event("message", A, proto.LEVELS_UNWATCH)
    assert h._friends_status_for(A)["out"] == {}


def test_a_watch_that_stops_repeating_or_a_dropped_link_ends_it():
    h = levels_host()
    h._friends_on_event("message", A, proto.LEVELS_WATCH)
    h._level_watchers[A] = time.monotonic() - proto.WATCH_STALE_S - 1
    assert h._friends_status_for(A)["out"] == {}
    h._friends_on_event("message", A, proto.LEVELS_WATCH)
    h._friends_on_event("unlinked", A, "timeout")
    assert h._friends_status_for(A)["out"] == {}


def test_a_friend_without_the_toys_switch_never_gets_the_levels():
    h = levels_host()
    h.set_friend_permission(A, "toys", False)
    h._friends_on_event("message", A, proto.LEVELS_WATCH)
    assert h._friends_status_for(A)["out"] == {}


def test_an_older_ogp_that_cant_say_it_watches_gets_the_levels_as_before():
    h = levels_host()
    versions = {A: 1, B: proto.LEVELS_SINCE}
    h.friends_link.peer_version = lambda peer: versions.get(peer, 0)
    assert h._friends_status_for(A)["out"] == {"Edge": 0.6}
    assert h._friends_status_for(B)["out"] == {}


def test_my_page_tells_the_friend_whose_panel_is_open():
    h = levels_host()
    assert "lw" not in h._friends_more_for(A)                # never watched: nothing
    h.set_friend_levels_watch(A)
    assert h._friends_more_for(A)["lw"] == proto.LEVELS_WATCH
    assert "lw" not in h._friends_more_for(B)
    h.set_friend_levels_watch(None)                          # page hidden, or a group
    assert h._friends_more_for(A)["lw"] == proto.LEVELS_UNWATCH


def test_the_me_panel_shows_my_own_live_levels():
    h, me = me_host()
    h._my_state = {**h._my_state, "toys": [("Edge", 1)], "outputs": {"Edge": 0.6}}
    h._me_tick()
    assert h._friend_status[me]["outputs"] == {"Edge": 0.0}  # Me's panel isn't in view
    h.set_friend_levels_watch(me)
    h._me_tick()
    h._me_tick()                                             # the watch, then the status
    assert h._friend_status[me]["outputs"] == {"Edge": 0.6}


def test_a_friends_shock_is_a_part_of_each_shockers_own_cap():
    h = Host()
    h.befriend(A, shock=True)
    h.pishock_engine.own = {22: {"max_intensity": 10, "max_pulse_ms": 500}}
    h._friends_on_event("message", A, proto.make_shock("s1", [0, 1], 1.0, 1.0))
    # all the way up on both: each at its own top (the engine turns an
    # unarmed shock into a vibrate later, as for any other shock)
    assert sorted(h.pishock_engine.pulses) == [(11, "shock", 40, 2000), (22, "shock", 10, 500)]


# --- the web remote ---------------------------------------------------------

W = "9" * 64                      # a browser on the web remote
W2 = "8" * 64


def web_host():
    h = Host()
    h.friends_settings.set_nickname("Blise")
    h.friends_web_link_message()
    h.drain()
    return h, h.friends_settings.web_code()


def test_the_first_web_link_makes_the_link_and_the_row():
    h = Host()
    h.friends_settings.set_nickname("Blise")
    assert h.get_friends_status()["web"] is None              # no row before the first copy
    msg = h.friends_web_link_message()
    assert msg.startswith("https://") and f"remote.html#{ME}." in msg
    assert msg.endswith("\n(Drive Blise's toys - OscGoesPurrr web remote)")
    code = h.friends_settings.web_code()
    assert code and f".{code}." in msg
    assert h.friends_web_link_message() == msg                # one link, the same each time
    web = h.get_friends_status()["web"]
    assert (web["on"], web["toys"], web["guests"]) == (True, True, [])
    assert "You made your web remote link" in h.log_text()


def test_a_browser_with_the_web_code_is_a_toys_only_guest_never_a_friend():
    h, code = web_host()
    assert h._friends_invite_ok(W, code, "Sam") is True
    h.drain()
    assert W not in h.friends_settings.friend_ids()
    assert h.friends_link.contacts in (None, [])             # nobody dials a browser
    assert h._friend_perms[W] == (True, False, False)
    h._my_state = h._build_my_state()
    st = h._friends_status_for(W)
    assert st["allow"] == {"toys": True, "shock": False} and "shk" not in st
    assert st.get("prm") is None
    h._friends_on_event("linked", W, "Sam")
    h._friends_on_event("version", W, "")
    h.drain()
    assert W not in h.friends_settings.friend_ids()           # still not a friend
    assert [g["nick"] for g in h.get_friends_status()["web"]["guests"]] == ["Sam"]
    assert "Sam opened your web remote" in h.log_text()


def test_a_web_guest_has_a_friends_toy_panel_but_no_shockers_until_ticked():
    h, code = web_host()
    h._friends_invite_ok(W, code, "Sam")
    full = proto.make_cmd({proto.ALL_TOYS: 0.5}, (1, 0.2), override=[proto.ALL_TOYS],
                          patterns={"Edge": ("sine", 2.0, 0.0, 1.0)},
                          holds={0: ("shock", 1.0)}, syn=3)
    h._friends_on_event("message", W, full)
    d = h._friend_drive[W]
    assert (d.ovr, set(d.pat), d.syn) == (frozenset({proto.ALL_TOYS}), {"Edge"}, 3)
    h._friends_on_event("message", W, proto.make_shock("s1", [0, 1], 1.0, 1.0))
    h._pump_friend_holds(time.monotonic())
    h.drain()
    assert h.strength_calls == [(0.2, "friend")]              # their strength slider, like a friend
    assert h.pishock_engine.pulses == [] and h.pishock_engine.holds == []   # Shockers is off
    assert "Sam (web) tried to shock you" in h.log_text()
    h.set_friends_web_permission("shock", True)
    assert h._friend_perms[W] == (True, True, False)
    h._friends_on_event("message", W, proto.make_shock("s2", [0], 1.0, 1.0))
    assert h.pishock_engine.pulses == [(11, "shock", 40, 2000)]   # inside your caps
    h.set_friends_paused(True)
    assert h.get_friend_drive("Edge") == 0.0                  # Pause all holds for it too


def test_web_guests_never_hear_your_friends_names():
    h, code = web_host()
    h.befriend(A)
    h._friends_invite_ok(W, code, "Sam")
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.4}))
    h._friends_on_event("message", W, cmd({proto.ALL_TOYS: 0.3}))
    assert h._friends_more_for(W)["oth"]["n"] == ["someone"]     # a count, no names
    assert h._friends_more_for(A)["oth"]["n"] == ["Sam (web)"]   # your friends see them


def test_off_and_a_new_link_let_the_browsers_go():
    h, code = web_host()
    h._friends_invite_ok(W, code, "Sam")
    h.drain()
    h.set_friends_web_on(False)
    assert h.friends_link.dropped == [(W, b"nolink")]
    assert h.get_friends_status()["web"]["guests"] == []
    assert h._friends_invite_ok(W2, code, "Jo") is False      # nobody gets in
    h.set_friends_web_on(True)
    assert h._friends_invite_ok(W2, code, "Jo") is True
    h.friends_web_new_link()
    new = h.friends_settings.web_code()
    assert new != code and (W2, b"nolink") in h.friends_link.dropped
    assert h._friends_invite_ok(W2, code, "Jo") is False      # the old link is dead
    assert h._friends_invite_ok(W2, new, "Jo") is True


def test_a_kicked_browser_cant_come_back():
    h, code = web_host()
    h._friends_invite_ok(W, code, "Sam")
    h._friends_on_event("message", W, cmd({proto.ALL_TOYS: 0.7}))
    h.friends_web_kick(W)
    assert h.friends_link.dropped == [(W, b"kicked")]
    assert h.get_friend_drive("Edge") == 0.0 and W not in h._friend_perms
    assert h._friends_invite_ok(W, code, "Sam") is False
    h.friends_web_new_link()
    assert h._friends_invite_ok(W, h.friends_settings.web_code(), "Sam") is False
    assert "You kicked Sam off your web remote" in h.log_text()


def test_the_web_toys_switch_stops_every_browser():
    h, code = web_host()
    h._friends_invite_ok(W, code, "Sam")
    h._friends_on_event("message", W, cmd({proto.ALL_TOYS: 0.6}))
    h.set_friends_web_permission("toys", False)
    assert h.get_friend_drive("Edge") == 0.0 and h._friend_perms[W][0] is False
    h._friends_on_event("message", W, cmd({proto.ALL_TOYS: 0.6}))
    assert h.get_friend_drive("Edge") == 0.0
    assert h._friends_invite_ok(W2, code, "Jo") is True
    assert h._friend_perms[W2] == (False, False, False)        # a newcomer too


def test_a_browser_leaving_is_logged_and_forgotten():
    h, code = web_host()
    h._friends_invite_ok(W, code, "Sam")
    h._friends_on_event("message", W, cmd({proto.ALL_TOYS: 0.6}))
    h._friends_on_event("unlinked", W, "bye")
    assert h.get_friend_drive("Edge") == 0.0                  # at once, on the link's thread
    h.drain()
    assert W not in h._web_guests and W not in h._friend_perms
    assert "Sam left your web remote (closed the page)" in h.log_text()
    assert "went offline" not in h.log_text()


def test_the_web_remote_row_drives_nobody_and_can_be_removed():
    h, code = web_host()
    h._friends_invite_ok(W, code, "Sam")
    h.set_friends_selected("web", "__web__")
    assert h.get_friends_status()["selected"] == {"kind": "web", "id": "__web__"}
    assert h._friends_targets() == []
    h.friends_web_remove()
    assert h.get_friends_status()["web"] is None
    assert h.friends_link.dropped == [(W, b"nolink")]
    assert h._friends_invite_ok(W, code, "Sam") is False      # not a web code any more


def test_a_new_id_takes_the_web_remote_along():
    h, code = web_host()
    h._friends_invite_ok(W, code, "Sam")
    h.friends_reset_id()
    assert h.get_friends_status()["web"] is None and h._web_guests == {}
