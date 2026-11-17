"""Checking whether a friend is online, now (the Friends list's ↻ and
Check all): a click dials outside the background budget, through the dial
loop like any other dial, each friend at most once per CHECK_GAP_S -- and
the page says "checking" until they answer or the try gives up. No network:
the link's loop-side methods are called by hand, a fake endpoint dials."""

import asyncio
import sys
import time
import types

import pytest

import remote_link
import remote_session
from test_friends_facade import A, B, Host
from test_remote_link import FakeConn

C = "c" * 64
D = "d" * 64


def online_link(contacts=(A, B)):
    """A link that looks online, its loop calls queued instead of run."""
    link = remote_link.RemoteLink("unused.key", log=lambda m: None, on_event=lambda *a: None,
                                  status_for=lambda p: None, cmd_for=lambda p: None)
    link.online, link._loop, link.my_id = True, object(), "e" * 64
    link._contacts = set(contacts)
    link.calls = []
    link._call = lambda fn, *args: link.calls.append((fn, args))
    return link


def run_calls(link):
    """What the link's thread would run next."""
    calls, link.calls = link.calls, []
    for fn, args in calls:
        fn(*args)


def live_session(peer):
    s = remote_session.Session(FakeConn(), peer, peer)
    s.live = True
    return s


# --- the limit: one try per friend per CHECK_GAP_S ---------------------------

def test_a_check_goes_once_per_friend_per_gap_however_often_it_is_clicked():
    link = online_link()
    assert link.check_now([A]) == [A]
    for _ in range(20):                                   # clicking away
        assert link.check_now([A]) == []
    assert len(link.calls) == 1
    run_calls(link)
    link._check_over(A)                                   # the try gave up
    assert link.check_now([A]) == []                      # still within the gap
    link._check_at[A] -= remote_link.CHECK_GAP_S
    assert link.check_now([A]) == [A]


def test_the_limit_is_per_friend_and_check_all_counts_for_each():
    link = online_link()
    assert link.check_now([A]) == [A]
    assert link.check_now([A, B]) == [B]                  # A was checked moments ago
    assert link.check_now([A, B, A]) == []


def test_no_check_for_a_stranger_a_linked_friend_or_while_offline():
    link = online_link()
    link._sessions[B] = live_session(B)
    assert link.check_now([C, B]) == []                   # not a friend / already linked
    link.online = False
    assert link.check_now([A]) == []
    link.online = True
    link._stopping = True
    assert link.check_now([A]) == []
    assert link.calls == []


def test_the_state_says_checking_and_how_long_until_the_next_may_go():
    link = online_link()
    link.check_now([A])
    checking, wait = link.check_state()[A]
    assert checking and remote_link.CHECK_GAP_S - 1 < wait <= remote_link.CHECK_GAP_S
    link._check_over(A)
    checking, wait = link.check_state()[A]
    assert not checking and wait > 0
    link._check_at[A] -= remote_link.CHECK_GAP_S          # the gap passed: nothing to show
    assert A not in link.check_state() and A not in link._check_at


def test_a_check_nothing_settles_stops_saying_so_after_a_while():
    link = online_link()
    link.check_now([A])
    link._checking[A] -= remote_link.CHECK_SHOW_MAX_S
    link._check_at[A] -= remote_link.CHECK_SHOW_MAX_S
    assert A not in link.check_state()
    assert link.check_now([A]) == [A]                     # and may be checked again


def test_stopping_clears_what_is_being_checked():
    link = online_link()
    link.check_now([A])
    link._loop = None                                     # no real loop to tell
    link.stop(timeout=0.1)
    assert link.check_state()[A][0] is False


# --- the dial path: the dial loop's own, outside the budget ------------------

def test_a_checked_friend_is_dialled_at_once_even_with_the_budget_spent():
    link = online_link(contacts=(A, B, C))
    now = time.monotonic()
    for peer in (A, B, C):
        link._fails[peer] = 4                             # offline all day
        link._next_try[peer] = now + 1000                 # next background try far off
    link._last_retry = now                                # the budget is spent
    assert link._next_dial(now) is None
    link.check_now([B])
    run_calls(link)
    assert link._next_dial(now) == B
    assert link._last_retry == now                        # the budget is untouched


def test_check_all_goes_out_one_dial_per_gap_never_in_a_burst():
    link = online_link(contacts=[f"{i:064x}" for i in range(30)])
    now = time.monotonic()
    for peer in link._contacts:
        link._fails[peer] = 4
        link._next_try[peer] = now + 1000
    link._last_retry = now
    assert len(link.check_now(sorted(link._contacts))) == 30
    run_calls(link)
    picked = []
    for i in range(10):                                   # ten ticks of the dial loop
        peer = link._next_dial(now + i * remote_link.DIAL_GAP_S)
        link._dialing.add(peer)
        picked.append(peer)
    assert len(set(picked)) == 10                         # one per tick, each once


def test_a_friend_already_being_dialled_is_not_dialled_twice():
    link = online_link()
    link._dialing.add(A)                                  # a background dial is going
    link.check_now([A])
    run_calls(link)
    assert A not in link._check_saved                     # nothing queued ...
    assert link.check_state()[A][0]                       # ... but it says checking


def test_a_check_of_a_friend_who_got_linked_meanwhile_is_over_at_once():
    link = online_link()
    link.check_now([A])
    link._sessions[A] = live_session(A)                   # they dialled us first
    run_calls(link)
    assert not link.check_state()[A][0]


class FakeEp:
    def __init__(self, connects):
        self.connects = connects
        self.dialled = []

    async def connect(self, addr, alpn):
        self.dialled.append(addr)
        if not self.connects:
            raise ConnectionError("nobody there")
        return FakeConn()


def fake_iroh():
    return types.SimpleNamespace(
        EndpointAddr=lambda eid, relay, direct: eid,
        EndpointId=types.SimpleNamespace(from_string=lambda s: s))


def dial(link, peer, connects, monkeypatch):
    """The dial loop's dial of `peer`, against a fake endpoint."""
    monkeypatch.setattr(remote_link, "iroh", fake_iroh())
    link._ep = FakeEp(connects)
    link._dialing.add(peer)
    adopted = []
    link._adopt = lambda conn, p, dialer, live: (
        adopted.append(p), link._sessions.__setitem__(p, remote_session.Session(conn, p, dialer)))
    asyncio.run(link._dial(peer))
    return adopted


def test_a_failed_check_leaves_the_background_schedule_alone(monkeypatch):
    link = online_link()
    later = time.monotonic() + 600
    link._fails[A], link._next_try[A] = 3, later
    link.check_now([A])
    run_calls(link)
    assert link._next_try[A] == 0.0                       # queued at the front
    dial(link, A, connects=False, monkeypatch=monkeypatch)
    assert link._fails[A] == 3                            # not counted as a failure
    assert link._next_try[A] == later                     # background as before
    assert not link.check_state()[A][0]                   # gave up: no longer checking
    assert A not in link._check_saved


def test_a_failed_check_is_never_followed_at_once_by_a_background_dial(monkeypatch):
    link = online_link()
    link._fails[A], link._next_try[A] = 2, time.monotonic() - 5   # a retry was due
    link.check_now([A])
    run_calls(link)
    dial(link, A, connects=False, monkeypatch=monkeypatch)
    assert link._next_try[A] - time.monotonic() > remote_link.CHECK_GAP_S - 1


def test_a_check_standing_in_for_a_first_try_counts_as_that_try(monkeypatch):
    link = online_link()                                  # just online: A not tried yet
    link.check_now([A])
    run_calls(link)
    dial(link, A, connects=False, monkeypatch=monkeypatch)
    assert link._fails[A] == 1                            # the first round's dial is done
    assert link._next_try[A] > time.monotonic()


def test_a_check_that_connects_says_checking_until_they_say_hello(monkeypatch):
    link = online_link()
    link._fails[A] = 3
    link.check_now([A])
    run_calls(link)
    assert dial(link, A, connects=True, monkeypatch=monkeypatch) == [A]
    assert link.check_state()[A][0]                       # connected, no hello yet
    s = link._sessions[A]
    link._on_msg(s, {"t": "hello", "nick": "Alex", "v": 2})
    assert s.live and A not in link._check_saved
    assert link.check_state()[A][0]                       # the page can't see it yet
    link._checks_seen_linked({A: {"linked": False}})
    assert link.check_state()[A][0]
    link._checks_seen_linked({A: {"linked": True}})       # now it can
    assert not link.check_state()[A][0]


def test_a_link_that_ends_before_the_hello_ends_the_check(monkeypatch):
    link = online_link()
    link._fails[A] = 3
    link.check_now([A])
    run_calls(link)
    dial(link, A, connects=True, monkeypatch=monkeypatch)
    s = link._sessions[A]
    s.conn.reason = "timeout"
    link._ended(s)
    assert not link.check_state()[A][0]


def test_unfriending_a_friend_being_checked_ends_the_check():
    link = online_link()
    link.check_now([A])
    run_calls(link)
    link._set_contacts({B})
    assert not link.check_state()[A][0] and A not in link._check_saved
    assert link._next_dial(time.monotonic()) != A


# --- the facade --------------------------------------------------------------

def test_the_facade_checks_one_friend_or_every_offline_one():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    h.friends_link._peers = {B: {"linked": True}}
    assert h.friends_check_now(A) == [A]
    assert h.friends_check_now() == [A]                    # B is linked
    assert h.friends_check_now(C) == []                    # not a friend
    h.friends_link.online = False
    assert h.friends_check_now() == []
    assert h.friends_link.checked == [[A], [A]]


def test_the_page_sees_checking_and_the_wait():
    h = Host()
    h.befriend(A)
    h.befriend(B)
    h.friends_link.checks = {A: (True, 9.5), B: (False, 3.0)}
    rows = {f["id"]: f for f in h.get_friends_status()["friends"]}
    assert rows[A]["checking"] and rows[A]["check_wait"] == 9.5
    assert not rows[B]["checking"] and rows[B]["check_wait"] == 3.0
    h.friends_link._peers = {A: {"linked": True}}          # answered: no longer checking
    rows = {f["id"]: f for f in h.get_friends_status()["friends"]}
    assert not rows[A]["checking"]


def test_the_me_row_passes_a_check_through_to_the_link():
    from controllers.friends_me import MeLink
    link = online_link(contacts=(A,))
    me = MeLink(types.SimpleNamespace(), link)
    assert me.check_now([A]) == [A]
    assert A in me.check_state()


# --- the list: a ↻ per offline row, and Check all ----------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv[:1])


class Stub:
    def __init__(self):
        self.checked = []
        self.friends = {
            A: {"linked": False, "checking": False, "check_wait": 0.0},
            B: {"linked": True, "rtt": 20.0},
        }
        self.online = True

    def get_friends_status(self):
        friends = [{"id": "__me__", "nick": "Me", "me": True, "linked": True, "rtt": None,
                    "driving_me": False, "toys": True, "shock": True, "params": True}]
        for fid, extra in self.friends.items():
            friends.append({"id": fid, "nick": "Mika" if fid == A else "Kiko", "toys": True,
                            "shock": True, "params": True, "rtt": None, "driving_me": False,
                            **extra})
        return {"friends": friends, "groups": [], "selected": {}, "params_on": True,
                "online": self.online}

    def friends_check_now(self, fid=None):
        self.checked.append(fid)
        return []

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


def column(qapp):
    import ui_components as uc
    from PySide6.QtWidgets import QWidget
    from ui.layout_helpers import vbox
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.controller = Stub()
    ui.views = {}
    root = QWidget()
    ui.window = root
    lay = vbox(0, 0)
    root.setLayout(lay)
    lay.addWidget(ui._build_friends_list_column())
    ui.refresh_friends = lambda: ui._update_friend_rows(ui.controller.get_friends_status())
    ui._rebuild_friend_rows(ui.controller.get_friends_status())
    root.show()
    qapp.processEvents()
    return ui, root


def test_an_offline_friend_has_a_check_button_a_linked_one_none(qapp):
    ui, root = column(qapp)
    ui.refresh_friends()
    assert ui._friend_rows[A]["check"].isVisible()
    assert not ui._friend_rows[B]["check"].isVisible()
    assert not ui._friend_rows["__me__"]["check"].isVisible()
    assert ui._friends_check_all.isVisible() and ui._friends_check_all.isEnabled()
    ui._friend_rows[A]["check"].click()
    ui._friends_check_all.click()
    assert ui.controller.checked == [A, None]
    root.hide()


def test_the_row_says_checking_until_the_try_settles(qapp):
    ui, root = column(qapp)
    ui.controller.friends[A].update(checking=True, check_wait=9.0)
    ui.refresh_friends()
    assert ui._friend_rows[A]["ping"].text() == "checking…"
    assert not ui._friend_rows[A]["check"].isVisible()
    assert ui._friends_check_all.text() == "Checking…"
    assert not ui._friends_check_all.isEnabled()
    # gave up: offline again, its ↻ greyed until the gap has passed
    ui.controller.friends[A].update(checking=False, check_wait=4.0)
    ui.refresh_friends()
    assert ui._friend_rows[A]["ping"].text() == "offline"
    assert ui._friend_rows[A]["check"].isVisible()
    assert not ui._friend_rows[A]["check"].isEnabled()
    assert not ui._friends_check_all.isEnabled()
    ui.controller.friends[A]["check_wait"] = 0.0
    ui.refresh_friends()
    assert ui._friend_rows[A]["check"].isEnabled() and ui._friends_check_all.isEnabled()
    root.hide()


def test_no_check_buttons_while_friends_is_offline_or_everyone_is_linked(qapp):
    ui, root = column(qapp)
    ui.controller.online = False
    ui.refresh_friends()
    assert not ui._friend_rows[A]["check"].isVisible()
    assert not ui._friends_check_all.isVisible()
    ui.controller.online = True
    ui.controller.friends[A] = {"linked": True, "rtt": 30.0}
    ui.refresh_friends()
    assert not ui._friends_check_all.isVisible()
    root.hide()
