"""Only friends in my instance (controllers/friends_instance.py): off by
default; while on, a friend whose linked VRChat account isn't in your
instance -- by your own log -- is refused like Pause, and whatever they had
going stops when they leave. An unlinked friend is not here, Me always is,
the web remote is blocked unless allowed anyway, a friend can be allowed
from anywhere. The receive path only reads a cached set, and nothing about
where you are goes out.

Every id and name here is made up."""

import time

import pytest

import remote_params as rp
import remote_protocol as proto
import vrchat_log
from controllers import friends_instance
from controllers.friends_common import ME
from controllers.people_facade import FRIENDS_LOG_KEY
from event_log import PARAMS, SHOCK, TOYS
from test_friends_facade import A, B, cmd, shock
from test_friends_vrchat import KAI, RIN, SAM, VHost
import test_params_facade as tpf

WEB_GUEST = "e" * 64


@pytest.fixture
def h():
    """You with two friends (Alex = A, linked to Rin; Sam = B, linked to
    Sam), the option on and both in your instance."""
    host = VHost()
    host.befriend(A, shock=True)
    host.befriend(B, shock=True)
    host.link_friend_vrchat(A, RIN, "Rin")
    host.link_friend_vrchat(B, SAM, "Sam")
    host.set_friends_instance_only(True)
    host.here((RIN, "Rin"), (SAM, "Sam"))
    host._instance_refresh()
    host._my_state = host._build_my_state()           # what their status is built from
    return host


def tick(h):
    """The friends tick's part: who is here now."""
    h._instance_refresh()


def entries(h, kind=None, op=None):
    return [e for e in h.event_log.recent()
            if (kind is None or e.kind == kind) and (op is None or e.op == op)]


# ---- the switch -----------------------------------------------------------------

def test_off_by_default_and_friends_drive_from_anywhere():
    h = VHost()
    h.befriend(A)
    assert not h.get_friends_instance_only()
    assert h.get_friends_status()["instance"] == {"on": False, "web_anyway": False,
                                                  "web_blocked": False}
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.5}))
    assert h.get_friend_drive("Edge") == 0.5          # unlinked, no log: fine while it's off
    assert not h.friend_not_here(A)


def test_switching_it_on_switches_the_log_on_too():
    h = VHost()
    h.befriend(A)
    assert not h.get_friends_vrc_log()
    h.set_friends_instance_only(True)
    assert h.get_friends_instance_only() and h.get_friends_vrc_log()
    assert h.mode_manager.app_settings.get(FRIENDS_LOG_KEY) is True
    assert h.friends_settings.get_instance_only()     # remembered in friends settings
    assert "Only friends in your VRChat instance may drive you now" in h.log_text()
    h.set_friends_instance_only(False)
    assert h.get_friends_vrc_log()                    # the log stays as it is
    assert "Friends may drive you from anywhere again" in h.log_text()


def test_the_log_switched_off_leaves_it_on_and_nobody_is_here(h):
    """Option (1): a switch about reading a file never opens you up to
    everyone -- with the log off nobody can be seen in your instance."""
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.7}))
    assert h.get_friend_drive("Edge") == 0.7
    h.set_friends_vrc_log(False)
    assert h.get_friends_instance_only()
    assert h.friend_not_here(A) and h.friend_not_here(B)
    assert h.get_friend_drive("Edge") == 0.0          # at once
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.7}))
    assert h.get_friend_drive("Edge") == 0.0


def test_vrchat_closing_means_nobody_is_here(h):
    h.osc_manager.is_connected = False
    tick(h)
    assert h.friend_not_here(A) and h.friend_not_here(B)
    h.osc_manager.is_connected = True
    tick(h)
    assert not h.friend_not_here(A)


# ---- in, leaving, unlinked ------------------------------------------------------

def test_a_friend_in_your_instance_drives_you(h):
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.4}, (3, 0.6)))
    h.drain()
    assert h.get_friend_drive("Edge") == 0.4
    assert h.strength_calls == [(0.6, "friend")]
    h._friends_on_event("message", A, shock("s1"))
    assert h.pishock_engine.pulses                    # a vibrate: shocks aren't armed
    st = h._friends_status_for(A)
    assert st["pause"] is False and "nh" not in st
    assert not h.friend(A)["not_here"] and h.friend(A)["here"]


def test_leaving_mid_drive_stops_everything_at_once_and_says_so(h):
    h._friends_on_event("message", A, proto.make_cmd({proto.ALL_TOYS: 0.9}, None,
                                                    holds={0: ("vibrate", 0.5)}))
    h._pump_friend_holds(time.monotonic())
    assert h.get_friend_drive("Edge") == 0.9
    assert h.pishock_engine.holds                     # their hold plays
    h.here((SAM, "Sam"), (KAI, "Kai"))               # Rin left the instance
    tick(h)
    assert h.friend_not_here(A) and not h.friend_not_here(B)
    assert h.get_friend_drive("Edge") == 0.0          # zero at once
    assert ("release", 11, ("friend", A, 0)) in h.pishock_engine.sources   # hold let go
    assert A not in h._friend_holds
    said = {e.kind: e for e in entries(h, op="not-here")}
    assert said[TOYS].held == "not in your VRChat instance" and said[TOYS].who == A
    assert said[SHOCK].held == "not in your VRChat instance"
    assert h.friend(A)["not_here"] and not h.friend(A)["here"]


def test_a_friend_not_here_is_refused_like_pause_and_logged(h):
    h.here((SAM, "Sam"))
    tick(h)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 1.0}, (4, 0.2)))
    h._friends_on_event("message", A, shock("s2"))
    h._friends_on_event("message", A, proto.make_cmd({}, None, holds={1: ("shock", 1.0)}))
    h._pump_friend_holds(time.monotonic())
    h.drain()
    assert h.get_friend_drive("Edge") == 0.0
    assert h.strength_calls == [] and h.pishock_engine.pulses == []
    assert h.pishock_engine.holds == []
    refused = entries(h, op="not-here")
    assert {e.kind for e in refused} == {TOYS, SHOCK}
    shocks = [e for e in entries(h, kind=SHOCK) if e.op == "shock"]
    assert shocks and shocks[0].held == "not in your VRChat instance"
    assert "Alex tried to drive your toys - held back: not in your VRChat instance" in h.log_text()
    # their panel: paused, and why -- nothing about where you are
    st = h._friends_status_for(A)
    assert st["pause"] is True and st["nh"] == 1
    assert proto.read_status(st)["not_here"] and proto.read_status(st)["paused"]
    text = proto.encode(st).decode()
    assert "wrld_" not in text and "usr_" not in text and "Sam" not in text


def test_coming_back_lets_them_drive_again_but_not_what_they_sent_meanwhile(h):
    h.here((SAM, "Sam"))
    tick(h)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 1.0}, (7, 0.2)))   # strength moved away
    h.here((RIN, "Rin"), (SAM, "Sam"))
    tick(h)
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.3}, (7, 0.2)))   # same seq resent
    h.drain()
    assert h.get_friend_drive("Edge") == 0.3
    assert h.strength_calls == []                     # used up while not here, as under Pause


def test_an_unlinked_friend_is_not_here_and_their_row_says_link_them(h):
    h.unlink_friend_vrchat(B)
    assert h.friend_not_here(B)                       # right away, not a tick later
    h._friends_on_event("message", B, cmd({proto.ALL_TOYS: 0.8}))
    assert h.get_friend_drive("Edge") == 0.0
    e = entries(h, op="not-here")[0]
    assert e.held == "not in your VRChat instance (no VRChat account linked)"
    f = h.friend(B)
    assert f["not_here"] and f["vrc"] == ""
    from ui.views.friends_account import NOT_HERE_LINK, row_tag
    assert row_tag(f, True)[0] == NOT_HERE_LINK
    h.link_friend_vrchat(B, SAM, "Sam")               # linked, and Sam is here
    assert not h.friend_not_here(B)


def test_me_is_always_here(h):
    h.here()
    h.set_friends_vrc_log(False)
    tick(h)
    assert not h.friend_not_here(ME)
    h._friends_on_event("message", ME, cmd({proto.ALL_TOYS: 0.6}))
    assert h.get_friend_drive("Edge") == 0.6
    assert h._friends_status_for(ME)["pause"] is False


# ---- exceptions -----------------------------------------------------------------

def test_allow_from_anywhere_lets_one_friend_in(h):
    h.here()
    tick(h)
    assert h.friend_not_here(A)
    h.set_friend_anywhere(A, True)
    assert not h.friend_not_here(A) and h.friend_not_here(B)
    assert h.friends_settings.get_friend(A)["anywhere"] is True
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 0.5}))
    assert h.get_friend_drive("Edge") == 0.5
    assert h.friend(A)["anywhere"] and not h.friend(A)["not_here"]
    from ui.views.friends_account import FROM_ANYWHERE, row_tag
    assert row_tag(h.friend(A), True)[0] == FROM_ANYWHERE
    # every other rule still holds for them
    h.set_friends_paused(True)
    assert h.get_friend_drive("Edge") == 0.0
    h.set_friends_paused(False)
    h.set_friend_anywhere(A, False)                   # taken back: stops at once
    assert h.friend_not_here(A) and h.get_friend_drive("Edge") == 0.0
    assert "Alex may drive you only from your VRChat instance" in h.log_text()


def test_allow_from_anywhere_is_off_for_a_new_friend_and_never_for_me(h):
    assert h.friends_settings.get_friend(A)["anywhere"] is False
    h.set_friend_anywhere(ME, True)
    assert h.friends_settings.get_friend(ME) is None


# ---- the web remote -------------------------------------------------------------

def join_web(h, gid=WEB_GUEST):
    h.friends_settings.web_code(make=True)
    code = h.friends_settings.get_web()["code"]
    assert h._friends_invite_ok(gid, code, "Visitor") is True


def test_the_web_remote_is_blocked_from_its_first_message(h):
    join_web(h)                                       # no tick in between
    assert h.friend_not_here(WEB_GUEST)
    h._friends_on_event("message", WEB_GUEST, cmd({proto.ALL_TOYS: 1.0}))
    assert h.get_friend_drive("Edge") == 0.0
    st = h._friends_status_for(WEB_GUEST)
    assert st["pause"] is True and st["nh"] == 1
    text = proto.encode(st).decode()
    assert "Alex" not in text and "Sam" not in text and "usr_" not in text
    assert entries(h, op="not-here")[0].held == "the web remote can't be in your VRChat instance"
    assert h.get_friends_status()["instance"]["web_blocked"]


def test_allow_the_web_remote_anyway(h):
    join_web(h)
    h.set_friends_web_anyway(True)
    assert not h.friend_not_here(WEB_GUEST)
    h._friends_on_event("message", WEB_GUEST, cmd({proto.ALL_TOYS: 0.4}))
    assert h.get_friend_drive("Edge") == 0.4
    assert h.get_friends_status()["web"]["anyway"] is True
    assert not h.get_friends_status()["instance"]["web_blocked"]
    h.set_friends_web_anyway(False)                   # blocked again: stops at once
    assert h.friend_not_here(WEB_GUEST) and h.get_friend_drive("Edge") == 0.0
    # a browser joining while it's allowed isn't held back either
    h.set_friends_web_anyway(True)
    join_web(h, "f" * 64)
    assert not h.friend_not_here("f" * 64)


def test_the_web_remote_is_free_while_the_option_is_off():
    h = VHost()
    join_web(h)
    assert not h.friend_not_here(WEB_GUEST)
    h._friends_on_event("message", WEB_GUEST, cmd({proto.ALL_TOYS: 0.4}))
    assert h.get_friend_drive("Edge") == 0.4


# ---- the receive path stays light ----------------------------------------------

def test_the_receive_path_reads_a_cached_state_only(h, monkeypatch):
    calls = []
    real = h._instance_compute
    monkeypatch.setattr(h, "_instance_compute", lambda: calls.append(1) or real())
    monkeypatch.setattr(vrchat_log, "here_ids", lambda *a: pytest.fail("checked per packet"))
    for i in range(50):
        h._friends_on_event("message", A, cmd({proto.ALL_TOYS: i / 100}))
        h._friends_on_event("message", B, cmd({proto.ALL_TOYS: 0.1}))
        h.get_friend_drive_mode("Edge")
    assert calls == []


def test_a_refused_friend_who_keeps_sending_is_told_once_in_a_while(h, monkeypatch):
    h.here((SAM, "Sam"))
    tick(h)
    clock = [1000.0]
    monkeypatch.setattr(friends_instance.time, "monotonic", lambda: clock[0])
    for _ in range(20):
        h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 1.0}))
    assert len(entries(h, kind=TOYS, op="not-here")) == 1
    clock[0] += friends_instance.TELL_AGAIN_S
    h._friends_on_event("message", A, cmd({proto.ALL_TOYS: 1.0}))
    assert len(entries(h, kind=TOYS, op="not-here")) == 2


def test_here_ids_agrees_with_in_instance():
    snaps = [None, {"state": "reading"}, {"state": "ok", "in_room": False, "others": [(RIN, "R")]},
             {"state": "ok", "in_room": True, "others": [(RIN.upper(), "R"), (KAI, "K")]}]
    for snap in snaps:
        for up in (True, False):
            here = vrchat_log.here_ids(snap, up)
            for uid in (RIN, KAI, SAM):
                assert (uid in here) == vrchat_log.in_instance(snap, uid, up)


# ---- Avatar Remote --------------------------------------------------------------

class _Modes:
    def __init__(self):
        from test_friends_vrchat import _Settings
        self.app_settings = _Settings()


def avatar_pair():
    """Two OGPs with an avatar board between them: the owner has only
    friends in their instance on, and the watcher (linked to Rin) is here."""
    owner, watcher, ids = tpf.watched()
    owner.mode_manager = _Modes()
    owner.snap = {"state": "ok", "in_room": True, "others": [(RIN, "Rin")]}
    owner._vrc_log_snapshot = lambda: owner.snap
    owner._vrc_log_sync = lambda: None
    owner.link_friend_vrchat(tpf.WATCHER, RIN, "Rin")
    owner.set_friends_instance_only(True)
    return owner, watcher, ids


def test_avatar_sets_are_refused_and_held_buttons_let_go(monkeypatch):
    owner, watcher, ids = avatar_pair()
    watcher.friend_param_hold(tpf.OWNER, ids["wave"], True)
    tpf.wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == [("Emote", 3)]
    owner.snap = {"state": "ok", "in_room": True, "others": []}     # they left
    owner._instance_refresh()
    assert owner.osc_manager.sent[-1] == ("Emote", 0)              # let go at once
    assert any(e.kind == PARAMS and e.op == "not-here" for e in owner.event_log.recent())
    owner.osc_manager.sent.clear()
    watcher.friends_link.send_event(tpf.OWNER, rp.make_set(10 ** 15, 1, control=ids["hoodie"]))
    tpf.wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == []                            # refused
    assert "Pal tried to use your avatar's board - held back: not in your VRChat instance" \
        in owner.notes()
    theirs = watcher.get_friend_board(tpf.OWNER)
    assert theirs["prm"]["stop"] and theirs["not_here"]            # their board says why
    owner.snap = {"state": "ok", "in_room": True, "others": [(RIN, "Rin")]}   # back
    owner._instance_refresh()
    watcher.friends_link.send_event(tpf.OWNER, rp.make_set(10 ** 15 + 1, 1, control=ids["hoodie"]))
    tpf.wire(owner, watcher, rounds=1)
    assert ("Hoodie", True) in owner.osc_manager.sent
