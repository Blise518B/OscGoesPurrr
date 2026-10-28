"""Who a session was with: tags (the whole session, or stretches of it),
what each person is credited with, the People table, and the file.

The rules worth pinning: a person is credited with exactly the activity
inside their tags; two people on one stretch both get all of it; the same
person tagged twice over the same minutes counts once; names match without
regard to case; and nothing here can crash app boot.
"""
import json

import pytest

from stats_people import (
    StatsPeople, clean_names, credit, credit_from_totals, person_key,
    tag_measure,
)


T0 = 1_790_000_000.0


def _tl(buckets, started=T0, bs=10):
    """A timeline: {bucket index: (active seconds, thrusts)}."""
    return {"started_ts": started, "bucket_s": bs,
            "buckets": {i: {"a": a, "t": t, "y": {}, "z": {}}
                        for i, (a, t) in buckets.items()}}


@pytest.fixture
def store(tmp_path):
    return StatsPeople(tmp_path / "stats_people.json")


class TestNames:
    def test_commas_spaces_and_duplicates(self):
        assert clean_names(" Alex ,  sam  kim, alex,, ") == ["Alex", "sam kim"]

    def test_list_input(self):
        assert clean_names(["Alex", "ALEX", " "]) == ["Alex"]

    def test_key_ignores_case_and_spacing(self):
        assert person_key("  Sam   Kim ") == person_key("sam kim")

    def test_names_are_capped(self):
        assert len(clean_names(["x" * 200])[0]) == 48


class TestCredit:
    def test_whole_session_gets_everything(self):
        tl = _tl({0: (10, 3), 5: (10, 4)})
        c = credit(tl, [{"whole": True, "people": ["Alex"]}], T0 + 100)
        assert c == {"Alex": {"active_s": 20.0, "thrusts": 7, "peak_pace": 7}}

    def test_stretch_counts_buckets_whose_middle_is_inside(self):
        tl = _tl({0: (10, 1), 1: (10, 2), 2: (10, 4)})
        tag = {"whole": False, "people": ["Sam"], "start": T0 + 5, "end": T0 + 25}
        assert credit(tl, [tag], T0 + 30)["Sam"]["thrusts"] == 3

    def test_two_people_on_one_stretch_both_get_it(self):
        tl = _tl({0: (10, 5)})
        tag = {"whole": False, "people": ["Sam", "Kim"], "start": T0, "end": T0 + 10}
        c = credit(tl, [tag], T0 + 10)
        assert c["Sam"]["thrusts"] == c["Kim"]["thrusts"] == 5

    def test_overlapping_tags_of_one_person_count_once(self):
        tl = _tl({0: (10, 5), 1: (10, 5)})
        tags = [{"whole": True, "people": ["alex"]},
                {"whole": False, "people": ["Alex"], "start": T0, "end": T0 + 10}]
        c = credit(tl, tags, T0 + 20)
        assert c == {"alex": {"active_s": 20.0, "thrusts": 10, "peak_pace": 10}}

    def test_open_stretch_runs_to_the_end(self):
        tl = _tl({0: (10, 1), 30: (10, 2)})
        tag = {"whole": False, "people": ["Sam"], "start": T0 + 100, "end": None}
        assert credit(tl, [tag], T0 + 400)["Sam"]["thrusts"] == 2

    def test_peak_pace_is_the_busiest_minute_inside(self):
        tl = _tl({i: (10, 2) for i in range(12)})
        tag = {"whole": False, "people": ["Sam"], "start": T0, "end": T0 + 30}
        assert credit(tl, [tag], T0 + 120)["Sam"]["peak_pace"] == 6
        whole = credit(tl, [{"whole": True, "people": ["A"]}], T0 + 120)
        assert whole["A"]["peak_pace"] == 12

    def test_nobody_in_the_stretch_still_appears(self):
        tl = _tl({0: (10, 1)})
        tag = {"whole": False, "people": ["Sam"], "start": T0 + 50, "end": T0 + 60}
        assert credit(tl, [tag], T0 + 60)["Sam"]["thrusts"] == 0

    def test_tag_measure(self):
        tl = _tl({0: (10, 1), 1: (8, 2)})
        tag = {"whole": False, "people": ["Sam"], "start": T0 + 10, "end": T0 + 20}
        assert tag_measure(tl, tag, T0 + 20) == {
            "active_s": 8.0, "thrusts": 2, "peak_pace": 2}

    def test_from_totals_only_the_whole_tag_counts(self):
        tags = [{"whole": True, "people": ["Alex", "alex", "Sam"]},
                {"whole": False, "people": ["Kim"], "start": T0, "end": T0 + 9}]
        assert credit_from_totals(tags, 600.0, 90) == {
            "Alex": {"active_s": 600.0, "thrusts": 90, "peak_pace": 0},
            "Sam": {"active_s": 600.0, "thrusts": 90, "peak_pace": 0},
        }


class TestTags:
    def test_whole_tag_is_set_replaced_and_cleared(self, store):
        store.tag_whole("s1", T0, "Alex")
        store.tag_whole("s1", T0, ["Alex", "Sam"])
        tags = store.tags("s1")
        assert len(tags) == 1 and tags[0]["people"] == ["Alex", "Sam"]
        store.tag_whole("s1", T0, "")
        assert store.tags("s1") == []
        assert "s1" not in store.sessions

    def test_stretches_sort_after_the_whole_tag(self, store):
        store.add_stretch("s1", T0, T0 + 50, T0 + 60, "Kim")
        store.add_stretch("s1", T0, T0 + 10, T0 + 20, "Sam")
        store.tag_whole("s1", T0, "Alex")
        assert [t["people"][0] for t in store.tags("s1")] == ["Alex", "Sam", "Kim"]
        assert store.people_in("s1") == ["Alex", "Sam", "Kim"]

    def test_empty_stretch_or_no_names_is_refused(self, store):
        assert store.add_stretch("s1", T0, T0 + 10, T0 + 10, "Sam") == 0
        assert store.add_stretch("s1", T0, T0 + 10, T0 + 20, " , ") == 0
        assert store.sessions == {}

    def test_remove(self, store):
        tid = store.add_stretch("s1", T0, T0 + 10, T0 + 20, "Sam")
        assert store.remove_tag("s1", tid)
        assert not store.remove_tag("s1", tid)

    def test_close_reopen_and_close_open(self, store):
        tid = store.add_stretch("s1", T0, T0 + 10, None, "Sam")
        assert store.close_stretch("s1", tid, T0 + 30)
        assert store.tags("s1")[0]["end"] == T0 + 30
        assert store.reopen_stretch("s1", tid)
        assert store.tags("s1")[0]["end"] is None
        store.close_open("s1", T0 + 40)
        assert store.tags("s1")[0]["end"] == T0 + 40

    def test_closing_before_the_start_removes_it(self, store):
        tid = store.add_stretch("s1", T0, T0 + 10, None, "Sam")
        store.close_stretch("s1", tid, T0 + 5)
        assert store.tags("s1") == []

    def test_any_edit_drops_the_cached_credit(self, store):
        store.tag_whole("s1", T0, "Alex")
        store.set_credit("s1", {"Alex": {"active_s": 1, "thrusts": 1, "peak_pace": 1}})
        assert not store.needs_credit("s1")
        store.add_stretch("s1", T0, T0 + 10, T0 + 20, "Sam")
        assert store.needs_credit("s1")

    def test_invalidate_all(self, store):
        store.tag_whole("s1", T0, "Alex")
        store.set_credit("s1", {})
        store.invalidate_all()
        assert store.needs_credit("s1")

    def test_whole_people(self, store):
        assert store.whole_people("s1") == []
        store.add_stretch("s1", T0, T0 + 10, T0 + 20, "Sam")
        assert store.whole_people("s1") == []
        store.tag_whole("s1", T0, "Alex, Kim")
        assert store.whole_people("s1") == ["Alex", "Kim"]

    def test_known_names_latest_spelling(self, store):
        store.tag_whole("s1", T0, "alex")
        store.tag_whole("s2", T0 + 100, "Alex, Sam")
        assert store.known_names() == ["Alex", "Sam"]

    def test_vrc_user_keeps_their_first_name(self, store):
        assert store.vrc_name("usr_1", "Alex") == "Alex"
        assert store.vrc_name("usr_1", "AlexRenamed") == "Alex"
        assert store.vrc_name("", "Sam") == "Sam"


class TestTable:
    def _credit(self, store, sid, started, **people):
        store.tag_whole(sid, started, list(people))
        store.set_credit(sid, {n: {"active_s": a, "thrusts": t, "peak_pace": p}
                               for n, (a, t, p) in people.items()})

    def test_sums_per_person_most_thrusts_first(self, store):
        self._credit(store, "s1", T0, Alex=(100, 50, 20), Sam=(60, 80, 30))
        self._credit(store, "s2", T0 + 1000, alex=(40, 40, 25))
        rows = store.table()
        assert [r["name"] for r in rows] == ["alex", "Sam"]
        alex = rows[0]
        assert (alex["sessions"], alex["active_s"], alex["thrusts"],
                alex["peak_pace"], alex["last_ts"]) == (2, 140.0, 90, 25, T0 + 1000)

    def test_people_with_nothing_are_left_out(self, store):
        self._credit(store, "s1", T0, Alex=(0, 0, 0))
        assert store.table() == []

    def test_extra_sessions_count_and_win_over_a_cache(self, store):
        self._credit(store, "s1", T0, Alex=(10, 5, 5))
        rows = store.table({"s1": (T0, {"Alex": {"active_s": 10, "thrusts": 9,
                                                 "peak_pace": 9}}),
                            "live": (T0 + 50, {"Sam": {"active_s": 5, "thrusts": 1,
                                                       "peak_pace": 1}})})
        assert {r["name"]: r["thrusts"] for r in rows} == {"Alex": 9, "Sam": 1}

    def test_uncached_sessions_are_not_counted(self, store):
        store.tag_whole("s1", T0, "Alex")
        assert store.table() == []


class TestFile:
    def test_round_trip(self, store, tmp_path):
        store.tag_whole("s1", T0, "Alex")
        tid = store.add_stretch("s1", T0, T0 + 10, None, "Sam", auto=True,
                                vrc="usr_9")
        store.set_credit("s1", {"Alex": {"active_s": 3, "thrusts": 2, "peak_pace": 1}})
        store.vrc_name("usr_9", "Sam")
        store.flush()
        again = StatsPeople(tmp_path / "stats_people.json")
        tags = again.tags("s1")
        assert tags[1]["id"] == tid and tags[1]["auto"] and tags[1]["vrc"] == "usr_9"
        assert tags[1]["end"] is None
        assert not again.needs_credit("s1")
        assert again.vrc_names == {"usr_9": "Sam"}

    def test_no_write_without_changes(self, store, tmp_path):
        store.flush()
        assert not (tmp_path / "stats_people.json").exists()

    def test_corrupt_file_is_set_aside(self, tmp_path):
        path = tmp_path / "stats_people.json"
        path.write_text("{nope", encoding="utf-8")
        s = StatsPeople(path)
        assert s.sessions == {}
        assert (tmp_path / "stats_people.json.bak").exists()

    def test_bad_entries_are_dropped(self, tmp_path):
        path = tmp_path / "stats_people.json"
        path.write_text(json.dumps({"sessions": {
            "a": {"started_ts": T0, "tags": [
                {"id": 1, "people": ["Sam"], "whole": False, "start": T0 + 9, "end": T0 + 1},
                {"id": 2, "people": [], "whole": True},
                "junk",
                {"id": 3, "people": ["Kim"], "whole": True}]},
            "b": "junk",
            "c": {"tags": []}},
            "vrc_names": {"usr_1": "", "usr_2": "Kim"}}), encoding="utf-8")
        s = StatsPeople(path)
        assert list(s.sessions) == ["a"]
        assert [t["id"] for t in s.tags("a")] == [3]
        assert s.vrc_names == {"usr_2": "Kim"}

    def test_reset(self, store, tmp_path):
        store.tag_whole("s1", T0, "Alex")
        store.vrc_name("usr_1", "Alex")
        store.reset()
        again = StatsPeople(tmp_path / "stats_people.json")
        assert again.sessions == {} and again.vrc_names == {}
