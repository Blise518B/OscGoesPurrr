"""Each friend linked to their VRChat account: where the link is kept, the
"in your instance" check the instance-only option builds on, the picker's
two sources (your instance, VRCX), one name for one person -- and that a
link never leaves this PC.

Every id, name and database here is made up."""

import json

import pytest

import vrcx_friends
from controllers.people_facade import FRIENDS_LOG_KEY
from settings.friends import FriendsSettingsManager
from test_friends_facade import A, B, Host
from test_vrcx_friends import make_db

RIN = "usr_0000000a-0000-4000-8000-00000000000a"
SAM = "usr_0000000b-0000-4000-8000-00000000000b"
KAI = "usr_0000000c-0000-4000-8000-00000000000c"


# ---- where it's kept --------------------------------------------------------

def test_a_link_is_kept_by_id_with_the_name_it_had(tmp_path, monkeypatch):
    monkeypatch.setattr(FriendsSettingsManager, "FILE_PATH", tmp_path / "friends.json")
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    assert s.get_friend(A)["vrc"] == ""                 # nobody linked at first
    assert s.set_vrc_link(A, RIN.upper(), "  Rin  VR ")
    assert s.get_friend(A)["vrc"] == RIN
    assert s.get_friend(A)["vrc_name"] == "Rin VR"
    again = FriendsSettingsManager()                     # read back from the file
    assert again.get_friend(A)["vrc"] == RIN and again.get_friend(A)["vrc_name"] == "Rin VR"
    assert again.vrc_links() == {A: RIN}


def test_bad_links_are_refused_or_dropped(tmp_path, monkeypatch):
    path = tmp_path / "friends.json"
    monkeypatch.setattr(FriendsSettingsManager, "FILE_PATH", path)
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    assert not s.set_vrc_link(A, "Rin")                  # a name is no account
    assert not s.set_vrc_link(B, RIN)                    # not a friend
    assert s.get_friend(A)["vrc"] == ""
    # a file edited by hand: a broken id is dropped with its name
    data = json.loads(path.read_text(encoding="utf-8"))
    data["friends"][0].update(vrc="usr_nope", vrc_name="Ghost")
    path.write_text(json.dumps(data), encoding="utf-8")
    f = FriendsSettingsManager().get_friend(A)
    assert f["vrc"] == "" and f["vrc_name"] == ""


def test_one_vrchat_account_belongs_to_one_friend(tmp_path, monkeypatch):
    monkeypatch.setattr(FriendsSettingsManager, "FILE_PATH", tmp_path / "friends.json")
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    s.add_friend(B, "Sam")
    s.set_vrc_link(A, RIN, "Rin")
    s.set_vrc_link(B, RIN, "Rin")                        # dragged onto the right one
    assert s.vrc_links() == {B: RIN}
    s.set_vrc_link(B, "")                                # unlinked
    assert s.vrc_links() == {}
    assert s.get_friend(B)["vrc_name"] == ""


def test_a_link_goes_with_the_friend(tmp_path, monkeypatch):
    monkeypatch.setattr(FriendsSettingsManager, "FILE_PATH", tmp_path / "friends.json")
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    s.add_friend(B, "Sam")
    s.set_vrc_link(A, RIN, "Rin")
    s.set_vrc_link(B, SAM, "Sam")
    s.remove_friend(A)
    assert s.vrc_links() == {B: SAM}
    s.add_friend(A, "Alex")                              # back as a new friend: unlinked
    assert s.get_friend(A)["vrc"] == ""
    s.forget_everyone()                                  # New ID
    assert s.vrc_links() == {}


# ---- the facade -------------------------------------------------------------

class _Settings:
    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _Modes:
    def __init__(self):
        self.app_settings = _Settings()


class _Osc:
    is_connected = True


class _People:
    def __init__(self):
        self.vrc_names = {}


class VHost(Host):
    """The Friends facade with VRChat's log (PeopleFacade's half) stood in."""

    def __init__(self, **features):
        self.mode_manager = _Modes()
        self.osc_manager = _Osc()
        self.snap = None
        self.syncs = 0
        super().__init__(**features)

    def _vrc_log_snapshot(self):
        return self.snap

    def _vrc_log_sync(self):
        self.syncs += 1

    def here(self, *people, in_room=True, state="ok"):
        """Your log: these people are in your instance."""
        self.snap = {"state": state, "file": "output_log.txt", "since": None,
                     "in_room": in_room, "others": list(people)}

    def friend(self, fid):
        return next(f for f in self.get_friends_status()["friends"] if f["id"] == fid)


@pytest.fixture
def h():
    host = VHost()
    host.befriend(A)
    host.befriend(B)
    host.set_friends_vrc_log(True)
    return host


def test_the_log_switch_is_its_own_and_starts_the_watcher():
    h = VHost()
    assert not h.get_friends_vrc_log()
    h.set_friends_vrc_log(True)
    assert h.mode_manager.app_settings.get(FRIENDS_LOG_KEY) is True and h.syncs == 1
    h.set_friends_vrc_log(True)                          # no change, no second start
    assert h.syncs == 1
    h.set_friends_vrc_log(False)
    assert h.syncs == 2 and not h.get_friends_vrc_log()


def test_in_your_instance_by_your_own_log(h):
    h.link_friend_vrchat(A, RIN, "Rin")
    assert not h.friend_in_instance(A)                   # nobody there yet
    h.here((RIN, "Rin"), (KAI, "Kai"))
    assert h.friend_in_instance(A)
    assert h.friend(A)["here"] and h.friend(A)["vrc_name"] == "Rin"
    assert not h.friend_in_instance(B)                   # unlinked = not here
    assert not h.friend(B)["here"] and h.friend(B)["vrc"] == ""
    h.here((KAI, "Kai"))                                 # Rin left
    assert not h.friend_in_instance(A) and not h.friend(A)["here"]


def test_in_your_instance_is_no_without_the_switch_or_vrchat(h):
    h.link_friend_vrchat(A, RIN, "Rin")
    h.here((RIN, "Rin"))
    assert h.friend_in_instance(A)
    h.osc_manager.is_connected = False                   # VRChat closed: a stale log
    assert not h.friend_in_instance(A) and not h.friend(A)["here"]
    h.osc_manager.is_connected = True
    h.set_friends_vrc_log(False)                         # the log may be read for People
    assert not h.friend_in_instance(A)                   # ... but Friends wasn't asked
    assert not h.friend_in_instance("__me__")
    assert not h.friend_in_instance("not a friend")


def test_the_pages_vrchat_part_says_what_the_log_does(h):
    def state():
        return h.get_friends_status()["vrchat"]["state"]

    assert state() == "starting"                         # switched on, nothing read yet
    h.here(state="no_log")
    assert state() == "no_log"
    h.here(state="reading")
    assert state() == "reading"
    h.here(in_room=False)
    assert state() == "no_room"
    h.osc_manager.is_connected = False
    h.here((RIN, "Rin"))
    assert state() == "no_vrchat"
    assert h.get_friends_status()["vrchat"]["people"] == []
    h.osc_manager.is_connected = True
    h.link_friend_vrchat(B, RIN, "Rin")
    h.here((RIN, "Rin"), (KAI, "Kai"), ("OldLogName", "OldLogName"))
    v = h.get_friends_status()["vrchat"]
    assert v["state"] == "ok" and v["log"]
    # an old log's name without an id can't be linked, so it isn't offered
    assert v["people"] == [{"id": RIN, "name": "Rin", "friend": B},
                           {"id": KAI, "name": "Kai", "friend": ""}]
    h.set_friends_vrc_log(False)
    assert h.get_friends_status()["vrchat"] == {"log": False, "state": "off", "people": [],
                                                "vrcx": "", "vrcx_count": 0}


def test_linking_moves_an_account_and_logs_no_vrchat_name(h):
    assert h.link_friend_vrchat(A, RIN, "Rin")
    assert h.link_friend_vrchat(B, RIN, "Rin")
    assert h.friend(A)["vrc"] == "" and h.friend(B)["vrc"] == RIN
    h.unlink_friend_vrchat(B)
    assert h.friend(B)["vrc"] == ""
    log = h.log_text()
    assert "Sam to their VRChat account" in log and "Alex is no longer linked" in log
    assert "unlinked Sam" in log
    assert "Rin" not in log                              # the system log may be shared


def test_me_the_web_remote_and_strangers_have_no_vrchat_account(h):
    assert not h.link_friend_vrchat("__me__", RIN, "Rin")
    assert not h.link_friend_vrchat("__web__", RIN, "Rin")
    assert not h.link_friend_vrchat("c" * 64, RIN, "Rin")
    assert not h.link_friend_vrchat(A, "Rin", "Rin")     # a name is no account
    me = h.get_friends_status()["friends"][0]
    assert me.get("me") and not me.get("vrc")


def test_a_link_never_leaves_this_pc(h):
    h.link_friend_vrchat(A, RIN, "RinTheSecret")
    h.here((RIN, "RinTheSecret"))
    h.set_friend_level(A, "all", 0.5)                    # you drive them: a cmd goes out
    h._my_state = h._build_my_state()
    sent = repr((h._friends_status_for(A), h._friends_cmd_for(A), h._friends_more_for(A),
                 h.friends_link.events, h.friends_link.pushed))
    assert RIN not in sent and "RinTheSecret" not in sent
    # and nothing about it in what the web remote's row carries
    assert RIN not in repr(h.get_friends_status().get("web"))


# ---- one name for one person ------------------------------------------------

def test_people_statistics_name_wins_and_takes_the_links(h):
    h.stats_people = _People()
    h.link_friend_vrchat(A, RIN, "Rin (new name)")
    assert h.friend(A)["vrc_name"] == "Rin (new name)"
    # People statistics met that account first, under its old name: one name
    h.stats_people.vrc_names[RIN] = "Rin"
    assert h.friend(A)["vrc_name"] == "Rin"
    h.here((RIN, "Rin (new name)"))
    assert h.get_friends_status()["vrchat"]["people"][0]["name"] == "Rin"
    # what PeopleFacade asks before it tags a linked account for the first time
    assert h._friends_vrc_link_name(RIN) == "Rin (new name)"
    assert h._friends_vrc_link_name(SAM) == ""


# ---- the picker -------------------------------------------------------------

@pytest.fixture
def vrcx_db(tmp_path, monkeypatch):
    path = make_db(tmp_path / "VRCX.sqlite3", {"usr" + "1" * 32: [
        (RIN, "Rin"), (SAM, "Sam"), (KAI, "Kai")] + [
        (f"usr_{n:08x}-0000-4000-8000-{n:012x}", f"Friend {n:03d}") for n in range(100, 160)]})
    monkeypatch.setattr(vrcx_friends, "default_path", lambda: path)
    return path


def test_import_from_vrcx_and_pick(h, vrcx_db):
    got = h.get_vrchat_choices()
    assert got["vrcx"] == [] and got["vrcx_installed"] and got["vrcx_state"] == ""
    assert h.import_vrcx_friends() == {"state": "ok", "count": 63}
    assert "imported 63 VRChat friends from VRCX" in h.log_text()
    h.link_friend_vrchat(B, SAM, "Sam")
    h.here((KAI, "Kai"))
    got = h.get_vrchat_choices("", limit=5)
    assert got["instance"] == [{"id": KAI, "name": "Kai", "friend": ""}]
    # Kai is offered once, from your instance; the rest by name, cut at the limit
    names = [p["name"] for p in got["vrcx"]]
    assert names == ["Friend 100", "Friend 101", "Friend 102", "Friend 103", "Friend 104"]
    assert got["vrcx_more"] == 63 - 1 - 5 and got["vrcx_count"] == 63
    got = h.get_vrchat_choices("sa")
    assert got["vrcx"] == [{"id": SAM, "name": "Sam", "friend": B}] and got["instance"] == []
    got = h.get_vrchat_choices("  KA ")
    assert got["instance"] == [{"id": KAI, "name": "Kai", "friend": ""}] and got["vrcx"] == []
    assert h.link_friend_vrchat(A, RIN, "Rin")
    assert h.friend(A)["vrc_name"] == "Rin"


def test_vrcx_missing_or_busy(h, tmp_path, monkeypatch, vrcx_db):
    monkeypatch.setattr(vrcx_friends, "default_path", lambda: tmp_path / "none.sqlite3")
    assert not h.get_vrchat_choices()["vrcx_installed"]
    assert h.import_vrcx_friends() == {"state": "missing", "count": 0}
    monkeypatch.setattr(vrcx_friends, "default_path", lambda: vrcx_db)
    assert h.import_vrcx_friends()["count"] == 63
    # busy the next time: the list you had stays
    monkeypatch.setattr(vrcx_friends, "read_friends",
                        lambda path=None: {"state": "busy", "friends": [], "error": "locked"})
    assert h.import_vrcx_friends() == {"state": "busy", "count": 63}
    assert h.get_vrchat_choices()["vrcx_count"] == 63


def test_the_imported_list_stays_in_memory(h, vrcx_db, tmp_path, monkeypatch):
    path = tmp_path / "friends.json"
    monkeypatch.setattr(h.friends_settings, "FILE_PATH", path)
    h.import_vrcx_friends()
    h.link_friend_vrchat(A, RIN, "Rin")
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    assert "Friend 1" not in text and SAM not in text   # only the link you made
