"""Friends whose OGP is newer or older than yours: the hello says the
version, the facade tells you once a launch -- loudly when you're behind --
and an older friend's row says so. A build from before versions were sent
counts as older."""

import remote_link
import remote_protocol as proto
import remote_session
from test_friends_facade import A, B, Host
from test_remote_link import PEER, FakeConn, make_link
from version import VERSION


def test_a_version_is_a_version_and_nothing_else():
    for good in ("0.14.0", "0.14.0-alpha.11", "1.2", "0.9.0-rc.1"):
        assert proto.clean_version(good) == good
    for bad in (None, "", "v0.14.0", "0.14.0-dev(3)", "<b>1.0</b>", "1", "0.14.0 " * 9, 14):
        assert proto.clean_version(bad) == ""


def test_the_hello_carries_this_copys_version_and_a_change_is_told_once(tmp_path):
    events = []
    link = make_link(tmp_path, events=events)
    assert link._hello(PEER)["app"] == VERSION
    s = remote_session.Session(FakeConn(), PEER, PEER)
    link._sessions[PEER] = s
    link._on_msg(s, {"t": "hello", "nick": "Mika", "app": "0.15.0"})
    link._on_msg(s, {"t": "hello", "nick": "Mika", "app": "0.15.0"})    # the next hello
    link._on_msg(s, {"t": "hello", "nick": "Mika", "app": "0.15.1"})
    assert [e for e in events if e[0] == "version"] == [
        ("version", PEER, "0.15.0"), ("version", PEER, "0.15.1")]


def test_a_hello_without_a_version_says_none(tmp_path):
    events = []
    link = make_link(tmp_path, events=events)
    s = remote_session.Session(FakeConn(), PEER, PEER)
    link._sessions[PEER] = s
    link._on_msg(s, {"t": "hello", "nick": "Mika"})
    assert ("version", PEER, "") in events
    assert remote_link.APP_VERSION == VERSION


class UI:
    def __init__(self):
        self.warned = []

    def show_friend_update_warning(self, *args):
        self.warned.append(args)

    def refresh_friends(self):
        pass


def host():
    h = Host()
    h.ui = UI()
    h.befriend(A)
    h.befriend(B)
    return h


def heard(h, peer, version):
    h._friends_on_event("version", peer, version)
    h.drain()


def test_a_newer_friend_warns_you_once_a_launch_with_the_release_page():
    h = host()
    heard(h, A, "99.0.0")
    heard(h, A, "99.0.0")
    heard(h, B, "99.1.0")
    assert len(h.ui.warned) == 1                              # once a launch, however many
    nick, theirs, mine, offer, url = h.ui.warned[0]
    assert (nick, theirs, mine, offer) == ("Alex", "99.0.0", VERSION, None)
    assert url.startswith("https://github.com/Blise518B/OscGoesPurrr/releases")
    st = h.get_friends_status()
    assert st["behind"] == {"version": "99.1.0", "mine": VERSION, "who": ["Sam"]}
    assert "Alex has a newer OGP (99.0.0)" in h.log_text()


def test_update_now_only_when_the_found_release_reaches_theirs(monkeypatch):
    import updater
    monkeypatch.setattr(updater, "is_self_updatable", lambda: True)
    h = host()
    h._pending_update = {"available": True, "asset": {"name": "x.exe"}, "latest": "99.0.0",
                         "url": "https://example.invalid/r"}
    heard(h, A, "99.0.0")
    assert h.ui.warned[-1][3] == ("99.0.0", "https://example.invalid/r")
    assert h._friends_update_offer("99.0.1") is None          # still short of theirs


def test_an_older_friend_is_tagged_and_logged_never_warned():
    h = host()
    heard(h, A, "0.1.0")
    heard(h, B, "")                                           # from before version checks
    assert h.ui.warned == [] and h.get_friends_status()["behind"] is None
    rows = {f["id"]: f for f in h.get_friends_status()["friends"]}
    assert rows[A]["version"] == "older" and rows[A]["app"] == "0.1.0"
    assert rows[B]["version"] == "older"
    assert "Sam has an older OGP (from before version checks)" in h.log_text()


def test_the_same_version_says_nothing_and_an_unheard_one_is_unknown():
    h = host()
    heard(h, A, VERSION)
    rows = {f["id"]: f for f in h.get_friends_status()["friends"]}
    assert rows[A]["version"] == "same" and rows[B]["version"] == ""
    assert "OGP" not in h.log_text()


def test_an_unfriended_newer_friend_no_longer_counts():
    h = host()
    heard(h, A, "99.0.0")
    h.friends_settings.remove_friend(A)
    assert h.get_friends_status()["behind"] is None


# --- the page: the banner and the window ------------------------------------

def test_the_banner_shows_while_you_are_behind_and_the_window_opens_once():
    import sys
    from PySide6.QtWidgets import QApplication, QWidget
    import ui_components as uc
    app = QApplication.instance() or QApplication(sys.argv[:1])
    ui = uc.OscGoesPurrrUI.__new__(uc.OscGoesPurrrUI)
    ui.window = QWidget()
    banner = ui._build_friends_update_banner()
    ui._update_friends_update_banner({"version": "99.0.0", "mine": VERSION, "who": ["Mika"]})
    assert not banner.isHidden() and "Mika has v99.0.0" in ui._friends_update_lbl.text()
    ui._update_friends_update_banner(None)
    assert banner.isHidden()
    url = "https://github.com/Blise518B/OscGoesPurrr/releases"
    ui.show_friend_update_warning("Mika", "99.0.0", VERSION, None, url)
    first = ui._friend_update_dialog
    ui.show_friend_update_warning("Sam", "99.1.0", VERSION, None, url)
    assert ui._friend_update_dialog is first                 # never two at once
    first.reject()
    app.processEvents()
    assert ui._friend_update_dialog is None
