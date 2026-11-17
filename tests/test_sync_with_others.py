"""Sync with others: which change to the shared toy cards is the newest.

The receiver decides it on the versions it can vouch for
(friends_receive._sync_version): an honest OGP or web remote page raises
its number by one per action and takes the shared panel's when it catches
up, so its numbers pass through as they are and every honest case plays
as it always did. Only a number that claims "newer" without a change on
the cards behind it is held at the newest. Each test is one situation, run
through real OGPs passing the real messages (`Room`); what a modified
sender gains is in test_receiver_clamps.py.
"""

import time

import pytest

import remote_protocol as proto
from controllers.friends_receive import _sync_newest
from test_friends_facade import A, B, W, Host, me_host, scmd, two_who_sync, web_host

R = "e" * 64            # the one they drive, as their OGPs know them
C = "7" * 64            # a third friend
ALL = proto.ALL_TOYS


@pytest.fixture
def hand_clock(monkeypatch):
    """time.monotonic, moving a microsecond per look (so who came first is
    always clear) -- and as far as a test moves it by hand."""
    now = [1000.0]

    def monotonic():
        now[0] += 1e-6
        return now[0]

    monkeypatch.setattr(time, "monotonic", monotonic)
    return now


class App(Host):
    """A friend's OGP. It shares the test's settings folder with the
    receiver, whose nickname would put a new OGP online for real -- this
    one never goes (its link is the fake one anyway)."""

    def _friends_maybe_start(self):
        pass


def app():
    a = App()
    a.befriend(R)
    return a


class Room:
    """One person (`recv`) and the friends driving them with Sync with
    others on, each a real OGP (`app`). A web remote page (W) is played by
    an OGP too -- its sync is the same code in remote.js -- except that it
    keeps its cards and version when its link drops (`drop(keeps=True)`)."""

    def __init__(self, *peers):
        self.recv, code = web_host()
        self.peers = peers
        self.app = {}
        for p in peers:
            if p == W:
                self.recv._friends_invite_ok(W, code, "Kim")
            else:
                self.recv.befriend(p)
            self.app[p] = app()

    def send(self, p):
        """`p`'s cmd reaches the receiver."""
        self.recv._friends_on_event("message", p, self.app[p]._friends_cmd_for(R))

    def back(self, p):
        """What the receiver says back -- the shared panel, who else drives
        -- reaches `p`."""
        for msg in self.recv._friends_sync_more_for(p).values():
            self.app[p]._friends_on_event("message", R, msg)

    def tick(self, n=1):
        for _ in range(n):
            for p in self.peers:
                self.send(p)
            for p in self.peers:
                self.back(p)

    def drop(self, p, keeps=False):
        """`p`'s link ends: the receiver lets go of them; their OGP clears
        its cards for the receiver -- a web remote page keeps them."""
        self.recv._friends_on_event("unlinked", p, "lost")
        if not keeps:
            self.app[p]._friends_on_event("unlinked", R, "lost")

    @property
    def playing(self):
        return self.recv.get_friend_drive("Edge")

    def owner(self):
        newest = _sync_newest(self.recv._friend_drive)
        return newest[0] if newest is not None else None

    def panel(self, p):
        return self.app[p]._my_levels.get(R, {})


# --- 1. taking turns ---------------------------------------------------------

def test_three_friends_taking_turns_each_latest_change_plays(hand_clock):
    room = Room(A, B, C)
    room.tick()
    for who, level in ((A, 0.3), (B, 0.6), (C, 0.9), (A, 0.2)):
        room.app[who].set_friend_level(R, ALL, level)
        room.tick(2)
        assert room.playing == pytest.approx(level)
        assert room.owner() == who
        assert all(room.panel(p) == {ALL: level} for p in room.peers)


def test_a_change_made_on_out_of_date_cards_does_not_undo_newer_ones(hand_clock):
    """Why the order isn't simply "last to arrive": every cmd carries the
    whole panel. Alex sets the level twice; Sam, who hasn't heard of it yet,
    starts a wave on cards that still show the old level. As before, Sam's
    loses -- and Sam's cards then catch up -- instead of carrying the old
    level back over Alex's."""
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.4)
    room.tick(2)
    room.app[A].set_friend_level(R, ALL, 0.5)
    room.app[A].set_friend_level(R, ALL, 0.6)
    room.send(A)
    room.app[B].set_friend_pattern(R, ALL, "sine")
    room.send(B)
    assert room.playing == pytest.approx(0.6) and room.owner() == A
    room.back(B)
    assert room.panel(B) == {ALL: 0.6} and not room.app[B]._my_patterns[R]


# --- 2. taking the shared panel and sending it back -------------------------------

def test_taking_the_shared_panel_and_sending_it_back_takes_nothing(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.7)
    room.tick(3)
    assert room.panel(B) == {ALL: 0.7}
    assert room.owner() == A                       # Sam's copies never take it
    drive = room.recv._friend_drive                # the same version, Alex's first
    assert drive[B].syn == drive[A].syn and drive[B].since > drive[A].since


# --- 3. top-ups, keepalives and values set again ----------------------------------

def test_unchanged_top_ups_and_keepalives_change_nothing(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.4)
    room.tick(2)
    before = dict(room.recv._friend_drive)
    room.tick(20)
    after = room.recv._friend_drive
    assert all((after[p].syn, after[p].since) == (before[p].syn, before[p].since)
               for p in (A, B))
    assert room.owner() == A


def test_setting_a_value_to_what_it_already_was_never_undoes_a_newer_change(hand_clock):
    """The avatar menu sets the level again whenever another radial moves.
    Alex's does that just after Sam's change, before Alex's cards have
    caught up: Alex's cards don't change, so nothing is taken -- Sam's
    change stays and Alex's cards catch up. (Before, the higher count could
    bring Alex's old cards back over Sam's change.)"""
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.4)
    room.tick(2)
    room.app[B].set_friend_level(R, ALL, 0.9)
    room.send(B)
    for _ in range(3):
        room.app[A].set_friend_level(R, ALL, 0.4, source="menu")
    room.send(A)
    assert room.playing == pytest.approx(0.9) and room.owner() == B
    room.back(A)
    assert room.panel(A) == {ALL: 0.9}


# --- 4. going quiet, leaving, coming back -------------------------------------

def test_when_the_one_who_changed_last_goes_quiet_the_others_carry_on(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.3)
    room.tick(2)
    room.app[B].set_friend_level(R, ALL, 0.8)
    room.tick(2)
    hand_clock[0] += proto.DRIVE_STALE_S / 2
    room.send(A)                                   # only Alex is still heard
    hand_clock[0] += proto.DRIVE_STALE_S / 2 + 0.1
    assert room.playing == pytest.approx(0.8)      # Alex's copy of Sam's change


def test_a_friend_who_reconnects_joins_the_shared_panel_as_it_stands(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.5)
    room.tick(2)
    room.app[B].set_friend_level(R, ALL, 0.8)
    room.tick(2)
    room.drop(A)
    assert room.panel(A) == {}
    room.tick(2)                                   # back: empty cards at version 0
    assert room.playing == pytest.approx(0.8) and room.owner() == B
    assert room.panel(A) == {ALL: 0.8}


def test_a_web_remote_page_that_moved_a_slider_while_its_link_was_down_carries_it_back(hand_clock):
    """The page keeps showing its cards until it notices its link is gone;
    a slider moved then reaches nobody. When the page is back and nobody
    changed anything meanwhile, that change plays -- as before."""
    room = Room(A, W)
    room.app[A].set_friend_level(R, ALL, 0.5)
    room.tick(2)
    room.drop(W, keeps=True)
    room.app[W].set_friend_level(R, ALL, 0.7)
    room.tick(2)
    assert room.playing == pytest.approx(0.7) and room.owner() == W
    assert room.panel(A) == {ALL: 0.7}


def test_a_web_remote_page_coming_back_unchanged_takes_what_changed_meanwhile(hand_clock):
    room = Room(A, W)
    room.app[A].set_friend_level(R, ALL, 0.5)
    room.tick(2)
    room.drop(W, keeps=True)
    room.app[A].set_friend_level(R, ALL, 0.2)
    room.send(A)
    room.tick(2)
    assert room.playing == pytest.approx(0.2) and room.owner() == A
    assert room.panel(W) == {ALL: 0.2}


def test_a_friend_whose_toys_switch_comes_back_on_carries_on_from_where_they_were(hand_clock):
    """Your Toys switch for Sam goes off (their drive is let go) and back
    on; the avatar menu moved Sam's level meanwhile. As before, that change
    plays once they're let back in."""
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.5)
    room.tick(2)
    room.recv.set_friend_permission(B, "toys", False)
    room.app[B].set_friend_level(R, ALL, 0.9, source="menu")
    room.recv.set_friend_permission(B, "toys", True)
    room.tick(2)
    assert room.playing == pytest.approx(0.9) and room.owner() == B
    assert room.panel(A) == {ALL: 0.9}


# --- 5. Sync with others: the owner's call (Blise's, 2026-11-17) ------------------

def told(room, p):
    """What `p`'s panel reads of the owner's choice, from their ``st``."""
    room.recv._my_state = room.recv._build_my_state()
    room.app[p]._friends_on_event("message", R, room.recv._friends_st_for(p))
    return room.app[p]._friend_status[R]["separate"]


def test_synced_is_the_default_and_every_panel_reads_it(hand_clock):
    room = Room(A, W)
    assert room.recv.get_friends_sync() is True
    assert told(room, A) is False and told(room, W) is False


def test_the_owner_switching_sync_off_has_each_drive_on_their_own_and_the_highest_wins(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.5)
    room.tick(2)
    room.recv.set_friends_sync(False)
    assert told(room, A) is True and told(room, B) is True
    room.app[A].set_friend_level(R, ALL, 0.3)
    room.app[B].set_friend_level(R, ALL, 0.9)
    room.tick(2)
    assert room.playing == pytest.approx(0.9)          # the higher of the two
    room.app[B].set_friend_level(R, ALL, 0.2)
    room.tick(2)
    assert room.playing == pytest.approx(0.3)          # Alex's own, now the higher
    assert room.panel(A) == {ALL: 0.3} and room.panel(B) == {ALL: 0.2}   # no shared cards


def test_the_owner_switching_sync_back_on_puts_everyone_on_one_set_of_cards_at_once(hand_clock):
    """Separate, nobody's panel follows anyone's, so the two changes were
    made from the same version: as for any two such, the first to arrive
    plays -- at once, since the order is kept while separate -- and every
    panel takes it."""
    room = Room(A, B)
    room.tick()
    room.recv.set_friends_sync(False)
    room.app[A].set_friend_level(R, ALL, 0.9)
    room.tick(2)
    room.app[B].set_friend_level(R, ALL, 0.2)
    room.tick(2)
    assert room.playing == pytest.approx(0.9)          # the higher
    room.app[A].set_friend_level(R, ALL, 0.95)
    room.tick(2)
    room.recv.set_friends_sync(True)
    assert room.playing == pytest.approx(0.95) and room.owner() == A
    room.tick(2)
    assert room.panel(A) == room.panel(B) == {ALL: 0.95}
    assert told(room, A) is False
    room.app[B].set_friend_level(R, ALL, 0.2)          # and it's one panel again
    room.tick(2)
    assert room.playing == pytest.approx(0.2) and room.panel(A) == {ALL: 0.2}


def test_an_older_receiver_that_says_nothing_reads_as_synced():
    from test_friends_facade import Host
    h = Host()
    h.befriend(R)
    h._friends_on_event("message", R, proto.make_status([], {}, 1.0, False, False, True,
                                                        False, [], False, 0.0, 0))
    assert h._friend_status[R]["separate"] is False


# --- 6. restarts ---------------------------------------------------------------

def test_after_a_restart_an_open_web_remote_page_carries_on_as_before(hand_clock):
    """Your OGP restarted: friends' OGPs come back with empty cards at
    version 0, a web remote page that stayed open with its cards and its
    version -- and, as before, its cards play again."""
    h, code = web_host()
    h.befriend(A)
    h._friends_invite_ok(W, code, "Kim")
    h._friends_on_event("message", A, scmd({}, 0))
    h._friends_on_event("message", W, scmd({ALL: 0.6}, 40))
    assert h.get_friend_drive("Edge") == pytest.approx(0.6)
    assert proto.read_panel(h._friends_sync_more_for(A)["pnl"])[:2] == (40, {ALL: 0.6})


def test_after_a_restart_an_old_page_cannot_undo_a_change_made_since(hand_clock):
    """The one case that plays differently: Alex already changed something
    after your restart when the page from before comes back. Its old
    version no longer brings its old cards back over Alex's change -- it
    joins, as an OGP coming back does."""
    h, code = web_host()
    h.befriend(A)
    h._friends_invite_ok(W, code, "Kim")
    h._friends_on_event("message", A, scmd({}, 0))
    h._friends_on_event("message", A, scmd({ALL: 0.3}, 1))
    h._friends_on_event("message", W, scmd({ALL: 0.6}, 40))
    assert h.get_friend_drive("Edge") == pytest.approx(0.3)
    assert proto.read_panel(h._friends_sync_more_for(W)["pnl"])[:2] == (40, {ALL: 0.3})


def test_a_friend_whose_ogp_restarted_comes_back_at_version_zero_and_joins(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.6)
    room.tick(2)
    room.recv._friends_on_event("unlinked", B, "lost")
    room.app[B] = app()                            # Sam's OGP, started anew
    room.tick(2)
    assert room.playing == pytest.approx(0.6) and room.owner() == A
    assert room.panel(B) == {ALL: 0.6}


# --- 7. at the same time -------------------------------------------------------

def test_two_changes_from_the_same_version_the_first_to_arrive_wins(hand_clock):
    room = Room(A, B)
    room.tick()
    room.app[A].set_friend_level(R, ALL, 0.2)
    room.app[B].set_friend_level(R, ALL, 0.7)
    room.send(B)
    room.send(A)
    assert room.playing == pytest.approx(0.7) and room.owner() == B
    room.tick(2)
    assert room.panel(A) == {ALL: 0.7}


def test_two_changes_at_the_very_same_instant_are_ordered_the_same_way_every_time(monkeypatch):
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    for first, second in ((A, B), (B, A)):
        h = two_who_sync()
        for peer in (first, second):
            h._friends_on_event("message", peer, scmd({}, 0))
        for peer in (first, second):
            h._friends_on_event("message", peer, scmd({ALL: 0.2 if peer == A else 0.7}, 1))
        assert h.get_friend_drive("Edge") == pytest.approx(0.7)   # by peer id: B's


# --- 8. older OGPs and the web remote -----------------------------------------

def test_an_older_ogp_whose_own_switch_is_off_still_joins_the_shared_panel(hand_clock):
    """Its cmd says no version (what an older OGP sends with its own Sync
    switch off): ignored -- it shares the panel like anyone. Its changes
    take the cards; its top-ups don't; it gets no panel back (it can't
    take one)."""
    h = two_who_sync()
    h._friends_on_event("message", A, scmd({ALL: 0.3}, 1))
    h._friends_on_event("message", A, scmd({ALL: 0.4}, 2))
    h._friends_on_event("message", B, proto.make_cmd({ALL: 0.6}, None))   # joins as it stands
    assert h.get_friend_drive("Edge") == pytest.approx(0.4)
    h._friends_on_event("message", B, proto.make_cmd({ALL: 0.7}, None))   # its change
    assert h.get_friend_drive("Edge") == pytest.approx(0.7)
    for _ in range(5):
        h._friends_on_event("message", B, proto.make_cmd({ALL: 0.7}, None))
    seq = proto.read_panel(h._friends_sync_more_for(A)["pnl"])[0]
    h._friends_on_event("message", A, scmd({ALL: 0.2}, seq + 1))      # Alex, caught up
    assert h.get_friend_drive("Edge") == pytest.approx(0.2)
    assert _sync_newest(h._friend_drive)[0] == A
    assert "pnl" not in h._friends_sync_more_for(B)


def test_a_web_remote_page_shares_the_panel_like_an_ogp(hand_clock):
    room = Room(A, W)
    room.tick()
    room.app[W].set_friend_pattern(R, ALL, "heart", 1.5)
    room.tick(2)
    assert room.owner() == W and room.app[A]._my_patterns[R][ALL][0] == "heart"
    room.app[A].set_friend_level(R, "Edge", 0.4)
    room.tick(2)
    assert room.owner() == A and room.panel(W) == {"Edge": 0.4}


# --- 10. Me ----------------------------------------------------------------------

def test_me_shares_the_panel_with_friends_like_any_of_them():
    h, me = me_host()
    h.befriend(A)
    h.set_friend_level(me, ALL, 0.4)
    assert h.get_friend_drive("Edge") == pytest.approx(0.4)
    h._friends_on_event("message", A, scmd({ALL: 0.4}, 1))        # Alex joins as it stands
    seq = proto.read_panel(h._friends_sync_more_for(A)["pnl"])[0]
    h._friends_on_event("message", A, scmd({ALL: 0.2}, seq + 1))  # and changes it
    assert h.get_friend_drive("Edge") == pytest.approx(0.2)
    h._me_tick()
    assert h._my_levels[me] == {ALL: 0.2}                         # your own panel follows


def test_with_sync_off_me_drives_on_my_own_beside_friends():
    h, me = me_host()
    h.befriend(A)
    h.set_friends_sync(False)
    h.set_friend_level(me, ALL, 0.4)
    h._friends_on_event("message", A, scmd({ALL: 0.2}, 1))
    assert h.get_friend_drive("Edge") == pytest.approx(0.4)
    h.set_friend_level(me, ALL, 0.0)
    assert h.get_friend_drive("Edge") == pytest.approx(0.2)


# --- 11. the waves ---------------------------------------------------------------

def test_the_wave_keeps_its_place_when_the_panel_passes_to_another_friend(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_pattern(R, ALL, "sine", 2.0)
    room.tick(2)
    hand_clock[0] += 0.7                                # a third of a cycle on
    room.app[B].set_friend_pattern(R, ALL, "sine", 1.0)
    room.send(B)
    assert room.owner() == B
    a, b = (room.recv._friend_drive[p].pat[ALL] for p in (A, B))
    assert b["ph0"] == pytest.approx(a["ph0"] + (b["t0"] - a["t0"]) / a["p"][1])
    assert b["ts"] == a["ts"]


# --- 12. what the shared panel says --------------------------------------------

def test_the_shared_panel_says_the_highest_version_sent_so_every_panel_follows(hand_clock):
    room = Room(A, B)
    room.app[A].set_friend_level(R, ALL, 0.4)
    room.tick(2)
    for _ in range(3):
        room.app[A].set_friend_level(R, ALL, 0.4, source="menu")
    room.send(A)
    assert room.owner() == A
    assert proto.read_panel(room.recv._friends_sync_more_for(B)["pnl"])[0] == 4
    room.back(B)
    room.app[B].set_friend_level(R, ALL, 0.6)
    room.tick(2)
    assert room.playing == pytest.approx(0.6) and room.panel(A) == {ALL: 0.6}


def test_after_a_change_every_panel_settles_and_nothing_keeps_going_out(hand_clock):
    room = Room(A, B, C)
    room.app[C].set_friend_pattern(R, "Edge", "heart", 1.5)
    room.app[A].set_friend_level(R, ALL, 0.3)
    room.tick(3)
    state = [(room.app[p]._my_pseq[R], dict(room.panel(p))) for p in room.peers]
    pushed = [len(room.app[p].friends_link.pushed) for p in room.peers]
    room.tick(10)
    assert [(room.app[p]._my_pseq[R], dict(room.panel(p))) for p in room.peers] == state
    assert [len(room.app[p].friends_link.pushed) for p in room.peers] == pushed
