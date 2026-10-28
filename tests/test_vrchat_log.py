"""Reading who is in the VRChat instance from VRChat's own log.

The line formats are VRChat's as of 2026-10 (copied from a real log, names
replaced). The watcher test runs the real thread against a file in a temp
folder.
"""
import time

import pytest

import vrchat_log as vl
from vrchat_log import InstanceTracker, LogWatcher, companion


ME = "usr_11111111-1111-1111-1111-111111111111"
ALEX = "usr_22222222-2222-2222-2222-222222222222"
SAM = "usr_33333333-3333-3333-3333-333333333333"


def line(clock, text):
    return f"2026.10.07 {clock} Debug      -  {text}"


def join(clock, name, uid):
    return line(clock, f"[Behaviour] OnPlayerJoined {name} ({uid})")


def leave(clock, name, uid):
    return line(clock, f"[Behaviour] OnPlayerLeft {name} ({uid})")


ROOM = line("11:33:16", "[Behaviour] Joining wrld_1b1be7f6-8f9c-4bbf-994b-"
            "b3a5edc63bbc:27326~private(usr_x)~canRequestInvite~region(eu)")
AUTH = line("11:33:12", f"User Authenticated: Me ({ME})")


def _epoch(clock):
    h, m, s = (int(x) for x in clock.split(":"))
    return time.mktime((2026, 10, 7, h, m, s, 0, 0, -1))


def feed(tracker, *lines):
    return [tracker.feed(x) for x in lines]


class TestTracker:
    def test_you_are_not_one_of_the_others(self):
        t = InstanceTracker()
        feed(t, AUTH, ROOM, join("11:33:27", "Me", ME))
        assert t.others() == []
        feed(t, join("11:36:01", "Alex", ALEX))
        assert t.others() == [(ALEX, "Alex")]
        assert t.changed_at == _epoch("11:36:01")

    def test_leaving_and_new_rooms(self):
        t = InstanceTracker()
        feed(t, AUTH, ROOM, join("11:33:27", "Me", ME),
             join("11:36:01", "Alex", ALEX), join("11:37:00", "Sam", SAM))
        assert [n for _k, n in t.others()] == ["Alex", "Sam"]
        assert feed(t, leave("11:40:00", "Sam", SAM)) == [True]
        assert t.others() == [(ALEX, "Alex")]
        assert feed(t, line("11:42:16", "[Behaviour] OnLeftRoom")) == [True]
        assert t.others() == [] and not t.in_room
        feed(t, ROOM)
        assert t.in_room

    def test_unrelated_lines_change_nothing(self):
        t = InstanceTracker()
        assert feed(t, line("11:00:00", "[Behaviour] OnPlayerJoinComplete Alex"),
                    line("11:00:01", "something else entirely"),
                    leave("11:00:02", "Nobody", SAM)) == [False, False, False]

    def test_old_logs_without_user_ids(self):
        t = InstanceTracker()
        feed(t, line("10:00:00", "[Behaviour] OnPlayerJoined Me"),
             line("10:00:00", '[Behaviour] Initialized PlayerAPI "Me" is local'),
             line("10:00:05", "[Behaviour] OnPlayerJoined Alex Smith"))
        assert t.others() == [("Alex Smith", "Alex Smith")]


class TestCompanion:
    def test_exactly_one_other(self):
        snap = {"state": "ok", "others": [(ALEX, "Alex")], "since": 5.0}
        assert companion(snap) == (ALEX, "Alex", 5.0)

    def test_nobody_a_crowd_or_not_caught_up(self):
        assert companion({"state": "ok", "others": []}) is None
        assert companion({"state": "ok",
                          "others": [(ALEX, "Alex"), (SAM, "Sam")]}) is None
        assert companion({"state": "reading", "others": [(ALEX, "Alex")]}) is None


def _wait(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


class TestWatcher:
    def test_follows_the_newest_log(self, tmp_path, monkeypatch):
        monkeypatch.setattr(vl, "_NEW_FILE_EVERY_S", 0.05)
        first = tmp_path / "output_log_2026-10-07_11-33-08.txt"
        first.write_text("\n".join([AUTH, ROOM, join("11:33:27", "Me", ME),
                                    join("11:36:01", "Alex", ALEX)]) + "\n",
                         encoding="utf-8")
        w = LogWatcher(dirs=[tmp_path], poll_s=0.02)
        w.start()
        try:
            assert _wait(lambda: companion(w.snapshot()) is not None)
            assert w.snapshot()["file"] == first.name
            assert companion(w.snapshot())[1] == "Alex"
            # A line written while we watch, in two halves.
            with open(first, "a", encoding="utf-8") as f:
                f.write(join("11:37:00", "Sam", SAM)[:30])
                f.flush()
                time.sleep(0.1)
                f.write(join("11:37:00", "Sam", SAM)[30:] + "\n")
            assert _wait(lambda: len(w.snapshot()["others"]) == 2)
            # VRChat restarts: a newer file takes over, and it starts empty.
            second = tmp_path / "output_log_2026-10-07_12-00-00.txt"
            second.write_text(AUTH + "\n", encoding="utf-8")
            later = time.time() + 5
            import os
            os.utime(second, (later, later))
            assert _wait(lambda: w.snapshot()["file"] == second.name)
            assert w.snapshot()["others"] == []
        finally:
            w.stop()
        assert not w.running

    def test_no_log_folder(self, tmp_path):
        w = LogWatcher(dirs=[tmp_path / "missing"], poll_s=0.02)
        w.start()
        try:
            assert _wait(lambda: w.snapshot()["state"] == "no_log")
        finally:
            w.stop()


def test_newest_log_picks_the_latest(tmp_path):
    import os
    a = tmp_path / "output_log_a.txt"
    b = tmp_path / "output_log_b.txt"
    a.write_text("", encoding="utf-8")
    b.write_text("", encoding="utf-8")
    os.utime(a, (1000, 1000))
    os.utime(b, (2000, 2000))
    (tmp_path / "other.txt").write_text("", encoding="utf-8")
    assert vl.newest_log([tmp_path]) == b
    assert vl.newest_log([tmp_path / "nope"]) is None
