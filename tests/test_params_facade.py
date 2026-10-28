"""A friend and your avatar board, end to end between two OGPs joined by a
fake link: nothing goes out until they look, the board comes over its
stream and its values follow, what they set lands in VRChat within your
board's rules (locks, YOLO, STOP, Pause, their switch), and a held button
is let go when they stop holding it -- or stop saying so."""

import queue
import time

import pytest

import param_board as pb
import remote_params as rp
import remote_protocol as proto
from controllers.friends_facade import FriendsFacade
from controllers.params_facade import ParamsFacade, read_relay_boards
from parameter_store import store

OWNER = "a" * 64
WATCHER = "b" * 64
AVATAR = "avtr_3f9a61c2-7b4e-4d2a-9c81-5e2d0b7a4f16"
OTHER = "avtr_8c47d05e-2f1b-4a96-b3e0-7d61c94a2e08"


def oscquery(params):
    """An OSCQuery tree like VRChat's /avatar/parameters."""
    tags = {bool: "T", int: "i", float: "f"}
    return {"CONTENTS": {"avatar": {"CONTENTS": {"parameters": {"CONTENTS": {
        name: {"TYPE": tags[type(v)], "VALUE": [v]} for name, v in params.items()}}}}}}


AVATAR_PARAMS = {"Hoodie": False, "TailWag": True, "Outfit": 0, "Emote": 0,
                 "Brightness": 0.5, "Secret": False, "Hue": 0.25, "VelocityX": 0.0}


@pytest.fixture(autouse=True)
def _empty_store_after():
    yield
    store.rebuild_from_json({})          # the store is the app's one; leave it empty


class FakeLink:
    def __init__(self, my_id):
        self.my_id, self.running, self.online, self.error = my_id, True, True, ""
        self.events, self.blobs = [], []
        self._peers = {}

    def peers(self):
        return self._peers

    def send_event(self, peer, msg, repeat=3):
        for _ in range(max(1, repeat)):
            self.events.append((peer, proto.decode(proto.encode(msg))))

    def send_blob(self, peer, msg):
        self.blobs.append((peer, proto.decode(proto.encode(msg))))

    def push_cmd(self, peer):
        pass

    def set_contacts(self, ids):
        pass

    def set_unfriended(self, ids):
        pass

    def stop(self, timeout=1.5):
        self.running = False


class FakeOsc:
    is_connected = True

    def __init__(self):
        self.sent = []

    def send_parameter(self, address, value, ignore_rate_limit=False, force_type=None,
                       default_type=None):
        self.sent.append((address.rsplit("/", 1)[-1], value))


class Host(FriendsFacade, ParamsFacade):
    def __init__(self, me, friend, params=True):
        self.thread_queue = queue.Queue()
        self.ui = None
        self.logs = []
        self._features = {"feature_friends": True, "feature_params": params,
                          "feature_pishock": False}
        self.osc_manager = FakeOsc()
        self._params_init()
        self._friends_init()
        self.friends_link = FakeLink(me)
        self.friends_settings.add_friend(friend, "Pal")
        self._friends_rebuild_perms()
        self._my_state = self._build_my_state()

    def get_feature_enabled(self, key):
        return self._features.get(key, True)

    def get_app_setting(self, key, default=None):
        return getattr(self, "_app", {}).get(key, default)

    def set_app_setting(self, key, value):
        self._app = {**getattr(self, "_app", {}), key: value}

    def is_output_off(self):
        return False

    def get_strength(self):
        return 1.0

    def log_message(self, msg):
        self.logs.append(msg)

    def notes(self):
        return [text for _t, text in self._friends_log]


def wire(owner, watcher, rounds=3):
    """Let the two talk: statuses, slots, streams and events, both ways."""
    def deliver(src, dst, src_id, dst_id):
        st = src._friends_status_for(dst_id)
        if st:
            dst._friends_on_event("message", src_id, proto.decode(proto.encode(st)))
        for _slot, msg in src._friends_more_for(dst_id).items():
            dst._friends_on_event("message", src_id, proto.decode(proto.encode(msg)))
        blobs, src.friends_link.blobs = src.friends_link.blobs, []
        for _peer, msg in blobs:
            dst._friends_on_event("message", src_id, msg)
        events, src.friends_link.events = src.friends_link.events, []
        for _peer, msg in events:
            dst._friends_on_event("message", src_id, msg)
    for _ in range(rounds):
        deliver(owner, watcher, OWNER, WATCHER)
        deliver(watcher, owner, WATCHER, OWNER)


def pair(**kw):
    store.rebuild_from_json(oscquery(AVATAR_PARAMS))
    owner = Host(OWNER, WATCHER, **kw)
    watcher = Host(WATCHER, OWNER, params=False)
    owner._params_avatar_changed(AVATAR)
    return owner, watcher


def build(owner):
    """Toggles (one inverted), a locked category, a hold button."""
    cats = owner._params_book.board["categories"]
    ids = {
        "hoodie": owner.params_edit("add_control", "Hoodie", "toggle")["id"],
        "nowag": owner.params_edit("add_control", "TailWag", "toggle", "No wag", invert=True)["id"],
        "bright": owner.params_edit("add_control", "Brightness", "slider")["id"],
        "wave": owner.params_edit("add_control", "Emote", "button", "Wave", on=3)["id"],
        "secret": owner.params_edit("add_control", "Secret", "toggle",
                                    category=cats[1]["id"])["id"],
    }
    owner.params_edit("set_category_locked", cats[1]["id"], True)
    return ids


def watched(**kw):
    owner, watcher = pair(**kw)
    ids = build(owner)
    watcher.set_friend_params_watch(OWNER)
    wire(owner, watcher)
    return owner, watcher, ids


def test_a_worn_avatar_is_called_by_vrchats_name(monkeypatch):
    """VRChat's OSC says only the id; its OSC files have the name -- the
    page and friends see that, not a piece of the id."""
    import vrchat_avatars
    asked = []
    monkeypatch.setattr(vrchat_avatars, "avatar_name",
                        lambda aid: asked.append(aid) or "Moth Girl")
    owner, _watcher = pair()
    assert asked == [AVATAR]
    assert owner.get_params_status()["avatar_name"] == "Moth Girl"


def test_nothing_goes_out_until_a_friend_looks():
    owner, watcher = pair()
    build(owner)
    st = owner._friends_status_for(WATCHER)
    assert rp.read_prm(st["prm"])["ver"]               # says there is a board ...
    assert owner._friends_more_for(WATCHER) == {}      # ... but sends none of it
    wire(owner, watcher)
    assert owner.friends_link.blobs == [] and watcher.get_friend_board(OWNER)["board"] is None


def test_a_watcher_gets_the_board_and_its_values():
    owner, watcher, ids = watched()
    theirs = watcher.get_friend_board(OWNER)
    assert theirs["board"]["ver"] == theirs["prm"]["ver"]
    assert {c["id"] for c in theirs["board"]["controls"]} == set(ids.values())
    assert theirs["values"]["Brightness"] == 0.5 and theirs["values"]["TailWag"] is True
    store.update_parameter("Brightness", 0.75)
    wire(owner, watcher, rounds=1)
    assert watcher.get_friend_board(OWNER)["values"]["Brightness"] == 0.75


def test_sets_land_in_vrchat_and_the_log_says_who():
    owner, watcher, ids = watched()
    watcher.friend_param_set(OWNER, ids["hoodie"], True)
    watcher.friend_param_set(OWNER, ids["nowag"], True)       # shown ON = parameter OFF
    watcher.friend_param_set(OWNER, ids["bright"], 9.0)       # kept inside the slider
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == [("Hoodie", True), ("TailWag", False), ("Brightness", 1.0)]
    assert "Pal turned your Hoodie on" in owner.notes()
    assert "You turned Pal's Hoodie on" in watcher.notes()


def test_a_copy_or_an_older_set_is_dropped():
    owner, watcher, ids = watched()
    watcher.friend_param_set(OWNER, ids["bright"], 0.2)
    watcher.friend_param_set(OWNER, ids["bright"], 0.4)
    events = list(watcher.friends_link.events)
    watcher.friends_link.events = list(reversed(events))     # the old one arrives last
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == [("Brightness", 0.4)]


def test_locked_categories_and_buttons_cant_be_set():
    owner, watcher, ids = watched()
    watcher.friend_param_set(OWNER, ids["secret"], True)      # refused on their side ...
    seq = 10 ** 15
    watcher.friends_link.send_event(OWNER, rp.make_set(seq, 1, control=ids["secret"]))
    watcher.friends_link.send_event(OWNER, rp.make_set(seq + 1, 1, control=ids["wave"]))
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == []                       # ... and on yours


def test_yolo_opens_every_parameter_but_vrchats_own():
    owner, watcher, ids = watched()
    watcher.friends_link.send_event(OWNER, rp.make_set(1, 0.5, param="Hue"))
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == []                       # no YOLO, no names
    owner.params_set_yolo(True)
    watcher.set_friend_params_watch(OWNER, yolo_open=True)
    wire(owner, watcher)
    board = watcher.get_friend_board(OWNER)["board"]
    names = dict(board["all"])
    assert "Hue" in names and "VelocityX" not in names
    assert watcher.get_friend_board(OWNER)["values"]["Hue"] == 0.25
    watcher.friend_param_set_any(OWNER, "Hue", 3.0)
    watcher.friends_link.send_event(OWNER, rp.make_set(10 ** 16, 1.0, param="VelocityX"))
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == [("Hue", 1.0)]           # clamped; the built-in refused


def test_a_held_button_is_let_go_when_they_stop_saying_so():
    owner, watcher, ids = watched()
    watcher.friend_param_hold(OWNER, ids["wave"], True)
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == [("Emote", 3)]
    assert "Pal held your Wave" in owner.notes()
    for peer in owner._params_held_t:                         # their updates stopped
        owner._params_held_t[peer] -= rp.HOLD_STALE_S + 0.1
    owner._params_tick()
    assert owner.osc_manager.sent[-1] == ("Emote", 0)


def test_letting_go_sends_the_release():
    owner, watcher, ids = watched()
    watcher.friend_param_hold(OWNER, ids["wave"], True)
    wire(owner, watcher, rounds=1)
    watcher.friend_param_hold(OWNER, ids["wave"], False)
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == [("Emote", 3), ("Emote", 0)]


def test_pause_blocks_everything_and_lets_go():
    owner, watcher, ids = watched()
    watcher.friend_param_hold(OWNER, ids["wave"], True)
    wire(owner, watcher, rounds=1)
    owner.set_friends_paused(True)
    assert owner.osc_manager.sent[-1] == ("Emote", 0)          # the held one let go
    wire(owner, watcher, rounds=1)
    assert watcher.get_friend_board(OWNER)["prm"]["stop"]      # they see it paused
    owner.osc_manager.sent.clear()
    watcher.friends_link.send_event(OWNER, rp.make_set(10 ** 15, 1, control=ids["hoodie"]))
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == []
    owner.set_friends_paused(False)
    watcher.friends_link.send_event(OWNER, rp.make_set(10 ** 15 + 1, 1, control=ids["hoodie"]))
    wire(owner, watcher, rounds=1)
    # resumed: their set lands, and the button they still hold presses again
    assert ("Hoodie", True) in owner.osc_manager.sent and ("Emote", 3) in owner.osc_manager.sent


def test_a_stop_left_on_by_an_older_version_is_dropped(tmp_path):
    import json
    from settings.param_boards import ParamBoardsSettingsManager
    path = tmp_path / "param_boards.json"
    path.write_text(json.dumps({"avatars": {}, "stop": True}), encoding="utf-8")
    old = ParamBoardsSettingsManager.FILE_PATH
    ParamBoardsSettingsManager.FILE_PATH = str(path)
    try:
        assert "stop" not in ParamBoardsSettingsManager().settings
    finally:
        ParamBoardsSettingsManager.FILE_PATH = old


def test_their_switch_off_hides_the_board_and_lets_go():
    owner, watcher, ids = watched()
    watcher.friend_param_hold(OWNER, ids["wave"], True)
    wire(owner, watcher, rounds=1)
    owner.set_friend_permission(WATCHER, "params", False)
    assert owner.osc_manager.sent[-1] == ("Emote", 0)
    assert owner._friends_status_for(WATCHER).get("prm") is None
    assert owner._friends_more_for(WATCHER) == {}


def test_feature_off_shares_nothing():
    owner, watcher = pair(params=False)
    build(owner)
    assert owner._friends_status_for(WATCHER).get("prm") is None


def test_friends_see_the_worn_board_while_you_edit_another():
    owner, watcher, ids = watched()
    ver = watcher.get_friend_board(OWNER)["prm"]["ver"]
    owner.params_settings.save(pb.normalize_profile({"name": "Other"}, OTHER))
    owner.params_open_avatar(OTHER)
    owner.params_edit("add_control", "Whatever", "toggle")
    wire(owner, watcher)
    assert watcher.get_friend_board(OWNER)["prm"]["ver"] == ver
    watcher.friend_param_set(OWNER, ids["hoodie"], True)
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == [("Hoodie", True)]


def test_an_edit_reaches_a_watcher_at_once():
    owner, watcher, ids = watched()
    owner.params_edit("rename_category", owner._params_book.board["categories"][0]["id"], "Clothes")
    wire(owner, watcher)
    names = [c["name"] for c in watcher.get_friend_board(OWNER)["board"]["categories"]]
    assert "Clothes" in names


def test_looking_away_stops_the_values():
    owner, watcher, ids = watched()
    watcher.set_friend_params_watch(None)
    wire(owner, watcher)
    assert owner._friends_more_for(WATCHER) == {}
    assert watcher._friends_more_for(OWNER)["pw"] == rp.WATCH_OFF


def test_vrchat_gone_means_no_board():
    owner, watcher, ids = watched()
    owner._params_vrchat_gone()
    wire(owner, watcher, rounds=1)
    assert watcher.get_friend_board(OWNER)["prm"]["ver"] == ""
    watcher.friends_link.send_event(OWNER, rp.make_set(10 ** 15, 1, control=ids["hoodie"]))
    wire(owner, watcher, rounds=1)
    assert owner.osc_manager.sent == []


def test_an_avatar_open_for_editing_sends_nothing_from_the_page():
    owner, watcher, ids = watched()
    assert owner.params_set_control(ids["hoodie"], True)
    owner.params_settings.save(pb.normalize_profile({"name": "Other"}, OTHER))
    owner.params_open_avatar(OTHER)
    added = owner.params_edit("add_control", "Whatever", "toggle")
    assert not owner.params_set_control(added["id"], True)
    assert owner.osc_manager.sent == [("Hoodie", True)]


def test_relay_boards_import(tmp_path, monkeypatch):
    folder = tmp_path / "VRCParameterRelay" / "avatars"
    folder.mkdir(parents=True)
    (folder / "a.json").write_text(
        '{"avatar_id": "%s", "name": "Base V7", "presets": [{"id": "p", "name": "Default", '
        '"categories": [{"id": "c", "name": "Outfit", "color": "yellow"}], '
        '"controls": [{"id": "k", "param": "Hoodie", "ptype": "Bool", "kind": "toggle", '
        '"label": "Hoodie", "cat": "c"}]}]}' % OTHER, "utf-8")
    (folder / "junk.json").write_text("not json", "utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert [p["avatar_id"] for p in read_relay_boards()] == [OTHER]
    owner, _ = pair()
    assert owner.params_relay_import_preview() == (1, 0)
    assert owner.params_relay_import() == (1, 0, 0)
    assert owner.params_settings.load(OTHER)["presets"][0]["categories"][0]["color"] == "amber"
    assert owner.params_relay_import_preview() == (1, 1)



def test_a_new_avatar_never_shows_the_old_board():
    owner, watcher, ids = watched()
    assert watcher.get_friend_board(OWNER)["board"] is not None
    store.rebuild_from_json(oscquery({"Ears": True}))
    owner._params_avatar_changed("avtr_00000000-0000-4000-8000-0000000000aa")
    owner.friends_link.blobs = []                     # the new board's stream got lost
    st = owner._friends_status_for(WATCHER)
    watcher._friends_on_event("message", OWNER, proto.decode(proto.encode(st)))
    assert watcher.get_friend_board(OWNER)["board"] is None     # "Getting their board…"
    pw = watcher._friends_more_for(OWNER)["pw"]
    assert pw.get("r")                                 # asks again
    ver, _t = owner._params_blob_sent[WATCHER]
    owner._params_blob_sent[WATCHER] = (ver, time.monotonic() - 10)   # a few seconds on
    wire(owner, watcher, rounds=2)
    theirs = watcher.get_friend_board(OWNER)
    assert theirs["board"] is not None and theirs["board"]["avatar"] == theirs["prm"]["avatar"]
    assert theirs["board"]["controls"] == []           # the new avatar's (empty) board


def test_the_every_parameter_list_refreshes_at_most_once_a_second():
    owner, watcher, ids = watched()
    owner.params_set_yolo(True)
    watcher.set_friend_params_watch(OWNER, yolo_open=True)
    wire(owner, watcher)
    assert watcher.get_friend_board(OWNER)["values"]["Hue"] == 0.25
    store.update_parameter("Hue", 0.75)                  # not on the board: the long list
    store.update_parameter("Hoodie", True)               # on the board: live
    wire(owner, watcher, rounds=1)
    values = watcher.get_friend_board(OWNER)["values"]
    assert values["Hoodie"] is True or values["Hoodie"] == 1
    assert values["Hue"] == 0.25                         # within the second: not yet
    ver, _at, rest = owner._params_rest
    owner._params_rest = (ver, time.monotonic() - 2.0, rest)   # a second later
    wire(owner, watcher, rounds=1)
    assert watcher.get_friend_board(OWNER)["values"]["Hue"] == 0.75
