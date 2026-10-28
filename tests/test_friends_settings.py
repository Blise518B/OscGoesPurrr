"""Friends settings: nickname, contacts, and the two switches per friend."""

import json
import time

from settings.friends import FriendsSettingsManager

A = "a" * 64
B = "b" * 64


def test_defaults():
    s = FriendsSettingsManager()
    assert s.get_nickname() == ""
    assert not s.get_paused()
    assert s.get_friends() == []
    assert s.get_selected() == {}
    assert s.get_groups() == []
    assert s.targets() == []


def test_new_friend_may_drive_toys_and_shock():
    s = FriendsSettingsManager()
    assert s.add_friend(A, "Alex")
    f = s.get_friend(A)
    assert f["toys"] is True and f["shock"] is True
    assert f["nick"] == "Alex"
    assert s.get_selected() == {"kind": "friend", "id": A}   # the menu just works
    assert s.targets() == [A]


def test_bad_ids_are_refused():
    s = FriendsSettingsManager()
    assert not s.add_friend("not-an-id")
    assert not s.add_friend("g" * 64)
    assert s.get_friends() == []


def test_permissions_and_remove():
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    s.add_friend(B, "Sam")
    s.set_permission(A, "shock", True)
    s.set_permission(A, "nonsense", True)
    assert s.get_friend(A)["shock"] is True
    gid = s.add_group("Pair", [A, B])
    s.remove_friend(A)
    assert s.friend_ids() == [B]
    assert s.get_group(gid)["members"] == [B]
    assert s.get_selected() == {"kind": "friend", "id": B}   # A was selected


def test_adding_twice_refreshes_the_nick():
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    s.add_friend(A, "Alexandra")
    assert len(s.get_friends()) == 1
    assert s.get_friend(A)["nick"] == "Alexandra"


def test_hand_edited_file_is_cleaned(tmp_path):
    path = FriendsSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"nickname": "  x  y ", "paused": "yes", "active": "zzz",
                   "friends": [{"id": A.upper(), "nick": "N", "toys": 0, "shock": 1},
                               {"id": A}, {"id": "short"}, "junk"]}, fh)
    s = FriendsSettingsManager()
    assert s.get_nickname() == "x y"
    assert s.get_paused() is True
    assert s.friend_ids() == [A]                  # duplicates and junk dropped
    assert s.get_friend(A)["toys"] is False and s.get_friend(A)["shock"] is True
    assert s.get_selected() == {"kind": "friend", "id": A}


def test_the_old_single_menu_friend_carries_over():
    path = FriendsSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"active": A, "friends": [{"id": A}, {"id": B}]}, fh)
    assert FriendsSettingsManager().get_selected() == {"kind": "friend", "id": A}


def test_the_old_together_list_becomes_a_group():
    path = FriendsSettingsManager.FILE_PATH
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"together": [A, B], "friends": [{"id": A}, {"id": B}]}, fh)
    s = FriendsSettingsManager()
    sel = s.get_selected()
    assert sel["kind"] == "group"
    assert s.get_group(sel["id"]) == {"id": sel["id"], "name": "Together", "members": [A, B]}
    assert s.targets() == [A, B]


def test_groups_and_what_the_selection_stands_for():
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    s.add_friend(B, "Sam")
    gid = s.add_group("  Night   crew ", [A, "c" * 64])
    assert s.get_group(gid) == {"id": gid, "name": "Night crew", "members": [A]}
    s.set_member(gid, B, True)
    s.set_member(gid, A, False)
    assert s.get_group(gid)["members"] == [B]
    assert s.set_selected("group", gid)
    assert s.targets() == [B]
    other = s.add_group("Pair", [A, B])          # a friend can be in several groups
    assert s.get_group(other)["members"] == [A, B]
    s.rename_group(gid, "Crew")
    s.rename_group(gid, "   ")                    # never emptied
    assert s.get_group(gid)["name"] == "Crew"
    s.delete_group(gid)
    assert s.get_group(gid) is None
    assert s.get_selected() == {"kind": "friend", "id": A}
    assert not s.set_selected("group", "nope")
    assert s.add_group("") is None


def test_a_once_invite_works_within_a_day_and_once():
    s = FriendsSettingsManager()
    code = s.new_invite(now=1000.0)
    assert len(code) == 16
    assert s.invite_kind(code, now=1000.0) == "once"
    assert s.invite_valid(code, now=1000.0 + 23 * 3600)
    assert not s.invite_valid(code, now=1000.0 + 25 * 3600)
    assert not s.invite_valid("f" * 16, now=1000.0)
    s.use_invite(code)
    assert not s.invite_valid(code, now=1001.0)


def test_day_week_and_forever_invites_work_for_anyone_until_they_end():
    s = FriendsSettingsManager()
    t = time.time()
    day, week, forever = (s.new_invite(k, now=t) for k in ("day", "week", "forever"))
    for _ in range(3):
        s.use_invite(day)
        s.use_invite(forever)
    assert s.invite_valid(day) and s.invite_valid(forever)
    assert {i["kind"]: i["uses"] for i in s.get_invites()} == {"day": 3, "week": 0, "forever": 3}
    later = t + 2 * 24 * 3600
    assert not s.invite_valid(day, now=later)
    assert s.invite_valid(week, now=later) and not s.invite_valid(week, now=t + 8 * 24 * 3600)
    assert s.invite_valid(forever, now=t + 10 * 365 * 24 * 3600)
    assert s.new_invite("nonsense") and s.get_invites()[-1]["kind"] == "once"
    s.close_invites()
    assert s.get_invites() == [] and not s.invite_valid(forever)


def test_old_invites_are_dropped_and_kept_few():
    s = FriendsSettingsManager()
    codes = [s.new_invite() for _ in range(25)]
    assert not s.invite_valid(codes[0])
    assert s.invite_valid(codes[-1])
    assert len(s.settings["invites"]) == 20
    s.settings["invites"] = [{"code": "x"}, {"code": "a" * 16, "expires": 1.0}, "junk",
                             {"code": "b" * 16, "kind": "weird", "expires": 9e12}]
    s._post_load({})
    assert s.settings["invites"] == []


def test_a_new_id_forgets_everyone():
    s = FriendsSettingsManager()
    s.set_nickname("Blise")
    s.add_friend(A, "Alex")
    s.add_group("Crew", [A])
    s.new_invite("forever")
    s.forget_everyone()
    assert (s.get_friends(), s.get_groups(), s.get_selected(), s.get_invites()) == ([], [], {}, [])
    assert s.get_nickname() == "Blise"


def test_unfriended_ids_are_kept_until_you_add_them_again():
    s = FriendsSettingsManager()
    s.add_friend(A, "Alex")
    s.add_friend(B, "Sam")
    s.remove_friend(A)
    s.remove_friend(B, unfriended=False)                 # they unfriended you
    assert s.get_unfriended() == [A]
    s.settings["unfriended"] += ["junk", A]
    s._post_load({})
    assert s.get_unfriended() == [A]
    s.add_friend(A, "Alex")
    assert s.get_unfriended() == []


# --- the web remote ---------------------------------------------------------

def test_no_web_remote_until_its_first_link():
    s = FriendsSettingsManager()
    assert s.get_web() == {"code": "", "on": True, "toys": True, "shock": False,
                           "params": False, "blocked": []}     # anyone with the link: ticked by hand
    assert s.web_code() == ""                     # asking doesn't make one
    code = s.web_code(make=True)
    assert len(code) == 16 and s.web_code() == code and s.web_code(make=True) == code
    assert s.get_web()["on"] is True


def test_a_new_web_link_kicks_and_switches():
    s = FriendsSettingsManager()
    code = s.web_code(make=True)
    assert s.new_web_code() != code
    s.set_web_on(False)
    s.set_web_permission("toys", False)
    s.set_web_permission("shock", True)
    s.set_web_permission("nothing", True)
    s.web_block(A)
    s.web_block(A)
    web = s.get_web()
    assert (web["on"], web["toys"], web["shock"], web["blocked"]) == (False, False, True, [A])
    s.forget_web()
    assert s.get_web()["code"] == ""


def test_a_damaged_web_entry_is_cleaned():
    s = FriendsSettingsManager()
    s._post_load({})
    s.settings["web"] = {"code": "nope", "on": 0, "blocked": ["x", A, A, B]}
    s._post_load({})
    assert s.get_web() == {"code": "", "on": False, "toys": True, "shock": False,
                           "params": False, "blocked": [A, B]}


def test_a_new_id_forgets_the_web_remote():
    s = FriendsSettingsManager()
    s.web_code(make=True)
    s.forget_everyone()
    assert s.get_web()["code"] == ""
