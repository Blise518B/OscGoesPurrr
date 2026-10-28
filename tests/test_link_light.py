"""The Friends link stays light on the network: changes only, a slow
keepalive, and no polling of friends who are offline."""

import time

import remote_link
import remote_protocol as proto
import remote_session


class FakeConn:
    def __init__(self):
        self.sent = []

    def send_datagram(self, data):
        self.sent.append(proto.decode(data))


def session():
    return remote_session.Session(FakeConn(), "a" * 64, "b" * 64)


def test_an_unchanged_status_goes_out_three_times_then_every_refresh():
    s = session()
    st = {"t": "st", "str": 0.5}
    t = 100.0
    for i in range(60):                                  # 15 s of ticks
        s.send_state("st", st, t + i * remote_session.SEND_S)
    assert len(s.conn.sent) == 1 + remote_session.REPEATS + 1   # + one refresh at 10 s
    s.send_state("st", {"t": "st", "str": 0.6}, t + 15.1)
    assert s.conn.sent[-1]["str"] == 0.6


def test_a_cmd_that_drives_toys_keeps_going_and_an_idle_one_stops():
    s = session()
    drive = proto.make_cmd({"*": 0.4}, None)
    idle = proto.make_cmd({}, None)
    for i in range(20):
        s.send_state("cmd", drive, 1.0 + i * 0.25)
    assert len(s.conn.sent) == 20                        # the receiver needs it < DRIVE_STALE_S
    for i in range(40):
        s.send_state("cmd", idle, 10.0 + i * 0.25)
    assert len(s.conn.sent) == 20 + 1 + remote_session.REPEATS


def test_offline_friends_are_retried_slower_and_slower():
    link = remote_link.RemoteLink("unused.key", log=lambda m: None, on_event=lambda *a: None,
                                  status_for=lambda p: None, cmd_for=lambda p: None)
    peer = "c" * 64
    gaps = []
    for _ in range(7):
        now = time.monotonic()
        link._retry_later(peer)
        gaps.append(link._next_try[peer] - now)
    assert gaps[0] >= 9 and gaps[-1] >= 1600              # 10 s ... 30 min
    assert all(b >= a * 0.8 for a, b in zip(gaps, gaps[1:]))
    link._targets.add("d" * 64)                           # a pasted ID: someone's waiting
    link._retry_later("d" * 64)
    assert link._next_try["d" * 64] - time.monotonic() < 4


def new_link():
    return remote_link.RemoteLink("unused.key", log=lambda m: None, on_event=lambda *a: None,
                                  status_for=lambda p: None, cmd_for=lambda p: None)


def dials(link, start, seconds):
    """Who the dial loop picks, tick by tick (a pick counts as dialling)."""
    picked = []
    for i in range(int(seconds / remote_link.DIAL_GAP_S)):
        peer = link._next_dial(start + i * remote_link.DIAL_GAP_S)
        if peer is not None:
            link._dialing.add(peer)
            picked.append(peer)
    return picked


def test_retries_of_offline_friends_share_one_budget_however_long_the_list():
    link = new_link()
    link._contacts = {f"{i:064x}" for i in range(1000)}
    for peer in link._contacts:
        link._fails[peer] = 4                             # offline all day, all overdue
    picked = dials(link, 1000.0, 60.0)
    assert len(picked) == 60 / remote_link.BACKGROUND_GAP_S


def test_coming_online_a_pasted_id_and_a_dropped_link_dont_wait_for_the_budget():
    link = new_link()
    link._contacts = {f"{i:064x}" for i in range(20)}     # just online: nobody tried yet
    assert len(dials(link, 1000.0, 20 * remote_link.DIAL_GAP_S)) == 20
    link._dialing.clear()
    for peer in link._contacts:
        link._fails[peer] = 4
    link._last_retry = 2000.0                             # the budget is spent
    dropped, pasted = "e" * 64, "f" * 64
    link._contacts.add(dropped)                           # _ended: fails 0, next try now
    link._targets.add(pasted)
    assert dials(link, 2000.0, 2 * remote_link.DIAL_GAP_S) == [pasted, dropped]


def test_the_fewest_failed_dials_go_first():
    link = new_link()
    long_gone, just_dropped = "a" * 64, "b" * 64
    link._contacts = {long_gone, just_dropped}
    link._fails = {long_gone: 5, just_dropped: 1}
    link._next_try = {long_gone: 0.0, just_dropped: 900.0}
    assert link._next_dial(1000.0) == just_dropped


def test_the_hello_says_which_protocol_their_ogp_speaks():
    link = new_link()
    s = remote_session.Session(FakeConn(), "a" * 64, "a" * 64)
    assert link.peer_version(s.peer) == 0
    link._on_msg(s, {"t": "hello", "nick": "Alex", "v": proto.PROTOCOL_VERSION})
    assert link.peer_version(s.peer) == proto.PROTOCOL_VERSION


def test_a_panel_watch_refreshes_and_looking_away_goes_quiet():
    s = session()
    for i in range(60):                                  # 15 s of ticks
        s.send_state("lw", proto.LEVELS_WATCH, 100.0 + i * remote_session.SEND_S)
    assert len(s.conn.sent) == 1 + remote_session.REPEATS + 1
    s.conn.sent.clear()
    for i in range(200):                                 # 50 s
        s.send_state("lw", proto.LEVELS_UNWATCH, 200.0 + i * remote_session.SEND_S)
    assert len(s.conn.sent) == 1 + remote_session.REPEATS


def test_moving_toys_dont_resend_the_status_to_a_friend_not_watching():
    # What the facade builds for a friend who isn't looking: no levels, so
    # the status is the same every tick and goes out only on the refresh.
    s = session()
    for i in range(60):
        st = proto.make_status([("Edge", 1)], {}, 1.0, False, False, True, False, [], False, 0, 0)
        s.send_state("st", st, 100.0 + i * remote_session.SEND_S)
    assert len(s.conn.sent) == 1 + remote_session.REPEATS + 1



def test_an_auto_mode_or_a_hold_keeps_the_cmd_going_too():
    for cmd in (proto.make_cmd({}, None, patterns={"*": ("sine", 2, 0, 1)}),
                proto.make_cmd({}, None, holds={0: ("vibrate", 0.5)})):
        s = session()
        for i in range(8):
            s.send_state("cmd", cmd, 1.0 + i * 0.25)
        assert len(s.conn.sent) == 8


def test_a_held_board_button_keeps_going_and_a_release_stops():
    s = session()
    for i in range(8):
        s.send_state("ph", {"t": "ph", "h": ["k1"]}, 1.0 + i * 0.25)
    assert len(s.conn.sent) == 8                         # let go after HOLD_STALE_S without
    for i in range(40):
        s.send_state("ph", {"t": "ph", "h": []}, 5.0 + i * 0.25)
    assert len(s.conn.sent) == 8 + 1 + remote_session.REPEATS


def test_a_board_watch_refreshes_and_looking_away_goes_quiet():
    s = session()
    for i in range(60):                                  # 15 s of ticks
        s.send_state("pw", {"t": "pw", "b": "v1"}, 100.0 + i * remote_session.SEND_S)
    assert len(s.conn.sent) == 1 + remote_session.REPEATS + 1
    s.conn.sent.clear()
    for i in range(200):                                 # 50 s
        s.send_state("pw", {"t": "pw", "off": 1}, 200.0 + i * remote_session.SEND_S)
    assert len(s.conn.sent) == 1 + remote_session.REPEATS


def test_unchanged_board_values_go_out_only_on_the_refresh():
    s = session()
    pv = {"t": "pv", "b": "v1", "w": 1, "o": 0, "x": [1, 0.5]}
    for i in range(60):
        s.send_state("pv0", pv, 100.0 + i * remote_session.SEND_S)
    assert len(s.conn.sent) == 1 + remote_session.REPEATS + 1


def test_a_link_we_closed_ends_with_our_own_reason():
    # The connection itself only says it was closed locally; the session
    # keeps why (a "removed" must not read as a lost link).
    s = session()
    s.conn.close_reason = lambda: "closed by local"
    s.conn.close = lambda code, reason: None
    s.close(7, b"removed")
    assert s.ended_word() == "removed"
