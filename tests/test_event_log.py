"""The log's record and store (event_log.py): one Event per thing that
happened, a slider drag as one entry, a row per person, the Log page's
filters -- and the day files: written off the hot path, read back,
rotated after KEEP_DAYS, cleared. Every file lands in a temp folder."""

import builtins
import json
import os
import time
from pathlib import Path

import event_log as el
from event_log import AVATAR, IN, Event, EventLog

A, B = "a" * 64, "b" * 64
NOON = time.mktime((2026, 11, 14, 12, 0, 0, 0, 0, -1))      # local noon, 14 Nov


def ev(t=NOON, text="x", who=A, name="Alex", role=el.ROLE_FRIEND, kind=el.TOYS, **kw):
    return Event(t, text, who, name, role, kind, **kw)


# --- the record ----------------------------------------------------------------

def test_a_record_round_trips_through_its_line():
    e = ev(text="Alex: shock 30 · 0.5 s on Collar", kind=el.SHOCK, op="shock", dir=IN,
           level=30, ms=500, on=("Collar",))
    line = json.dumps(e.to_json())
    assert Event.from_json(json.loads(line)) == e


def test_a_line_leaves_out_what_is_empty():
    d = ev(text="Alex is online", kind=el.LINK, op="online").to_json()
    assert set(d) == {"t", "who", "name", "role", "kind", "op", "text"}


def test_a_damaged_line_is_no_record():
    assert Event.from_json({"text": "no time"}) is None
    assert Event.from_json({"t": "soon", "text": "x"}) is None
    e = Event.from_json({"t": 1, "text": "x", "kind": "nonsense", "lvl": "high",
                         "on": ["Collar", 3]})
    assert e.kind == el.LINK and e.level is None and e.on == ("Collar",)


def test_shocks_that_went_out_stand_out():
    assert ev(kind=el.SHOCK, op="shock").stands_out
    assert ev(kind=el.SHOCK, op="hold", asked="shock").stands_out
    assert not ev(kind=el.SHOCK, op="shock", held="Off is on").stands_out
    assert not ev(kind=el.SHOCK, op="vibrate").stands_out
    assert ev(kind=el.SHOCK, op="vibrate").shocker_op
    assert ev(kind=el.SHOCK, op="hold", asked="beep").shocker_op
    assert not ev(kind=el.SHOCK, op="stop").shocker_op
    assert not ev(kind=el.TOYS, op="shock").stands_out


def test_how_an_operation_reads():
    assert el.shocker_text("shock", 30) == "shock 30"
    assert el.shocker_text("shock", 30, armed=False) == "vibrate 30 (shocks aren't armed)"
    assert el.shocker_text("beep", None) == "beep"
    assert el.seconds_text(1500) == "1.5 s"


# --- adding, coalescing ------------------------------------------------------------

def test_a_drag_with_one_key_is_one_entry():
    log = EventLog()
    assert log.add(ev(NOON, "strength 10 %"), key=("str", A)) is True
    assert log.add(ev(NOON + 1.0, "strength 40 %"), key=("str", A)) is False
    assert log.add(ev(NOON + 2.5, "strength 80 %"), key=("str", A)) is False   # 1.5 s on
    assert [e.text for e in log.recent()] == ["strength 80 %"]
    log.add(ev(NOON + 5.0, "strength 20 %"), key=("str", A))      # 2.5 s quiet: a new one
    log.add(ev(NOON + 5.5, "Alex let go"), key=None)
    log.add(ev(NOON + 6.0, "strength 30 %"), key=("str", A))      # not the last entry
    assert [e.text for e in log.recent()] == ["strength 30 %", "Alex let go",
                                              "strength 20 %", "strength 80 %"]


def test_every_change_moves_the_version_and_new_entries_reach_listeners():
    log = EventLog()
    heard = []
    log.on_add(heard.append)
    v0 = log.version
    log.add(ev(NOON), key="k")
    log.add(ev(NOON + 0.5), key="k")              # coalesced: no new entry
    assert log.version == v0 + 2 and len(heard) == 1
    log.clear()
    assert log.recent() == [] and log.version == v0 + 3


def test_recent_is_newest_first_and_can_filter():
    log = EventLog()
    for i in range(10):
        log.add(ev(NOON + i, f"e{i}", role=el.ROLE_AVATAR if i % 2 else el.ROLE_FRIEND))
    assert [e.text for e in log.recent(3)] == ["e9", "e8", "e7"]
    assert [e.text for e in log.recent(2, where=lambda e: e.role != el.ROLE_AVATAR)] == [
        "e8", "e6"]


def test_memory_keeps_the_newest_only():
    log = EventLog(max_memory=5)
    for i in range(8):
        log.add(ev(NOON + i, f"e{i}"))
    assert [e.text for e in log.recent()] == ["e7", "e6", "e5", "e4", "e3"]


def test_adding_never_touches_the_disk(tmp_path, monkeypatch):
    log = EventLog(tmp_path / "log")
    def no_disk(*_a, **_k):
        raise AssertionError("disk I/O while adding")
    monkeypatch.setattr(builtins, "open", no_disk)
    monkeypatch.setattr(Path, "mkdir", no_disk)
    monkeypatch.setattr(os, "replace", no_disk)
    for i in range(50):
        log.add(ev(NOON + i, f"e{i}"), key=("k", i % 3))
    monkeypatch.undo()
    assert not (tmp_path / "log").exists()


# --- by person ---------------------------------------------------------------------

def test_a_row_per_person_the_most_recent_first():
    events = [ev(NOON + 5, "Sam: shock 20", who=B, name="Sam", kind=el.SHOCK, op="shock"),
              ev(NOON + 4, "Alex set your strength", who=A),
              ev(NOON + 3, "Sam: beep", who=B, name="Sam", kind=el.SHOCK, op="beep"),
              ev(NOON + 2, "Your avatar: shock 10", who=AVATAR, name="Your avatar",
                 role=el.ROLE_AVATAR, kind=el.SHOCK, op="shock"),
              ev(NOON + 1, "You went online", who=el.YOU, name="You", role=el.ROLE_YOU),
              ev(NOON + 0, "Alex is online", who=A, name="Alex (old name)")]
    rows = el.by_person(events, recent_each=1)
    assert [p.who for p in rows] == [B, A, AVATAR, el.YOU]
    sam = rows[0]
    assert sam.last.text == "Sam: shock 20" and sam.count == 2
    assert sam.shocks == 1 and sam.shocker_ops == 2
    assert [e.text for e in sam.recent] == ["Sam: shock 20"]        # recent_each
    assert rows[1].name == "Alex"                                    # the newest name
    assert [p.who for p in el.by_person(events, skip_roles=(el.ROLE_YOU,))] == [B, A, AVATAR]
    d = sam.as_dict(now=NOON + 65)
    assert d["ago"] == "1 min ago" and d["recent"][0]["stands_out"] is True


def test_how_long_ago_reads():
    assert [el.ago(s) for s in (3, 42, 150, 7300, 90000, 3 * 86400)] == [
        "just now", "42 s ago", "2 min ago", "2 h ago", "yesterday", "3 days ago"]


def test_when_shows_the_clock_today_and_the_day_before():
    assert el.when(NOON + 61, now=NOON + 3600) == "12:01:01"
    assert el.when(NOON - 86400, now=NOON) == "13 Nov 12:00"


# --- the Log page's filters -------------------------------------------------------

def _filled():
    log = EventLog()
    rows = [(NOON - 3 * 86400, A, "Alex", el.ROLE_FRIEND, el.TOYS, "Alex drove your Lush"),
            (NOON - 600, B, "Sam", el.ROLE_FRIEND, el.SHOCK, "Sam: shock 20 on Collar"),
            (NOON - 300, AVATAR, "Your avatar", el.ROLE_AVATAR, el.SHOCK,
             "Your avatar: vibrate 15 on Collar"),
            (NOON - 60, A, "Alex", el.ROLE_FRIEND, el.PARAMS, "Alex turned your Tail on"),
            (NOON - 30, el.YOU, "You", el.ROLE_YOU, el.SETTINGS, "Friends resumed")]
    for t, who, name, role, kind, text in rows:
        log.add(Event(t, text, who, name, role, kind))
    return log


def test_filters_by_person_kind_time_and_words():
    log = _filled()
    texts = lambda **f: [e.text for e in log.query(**f)[0]]
    assert texts(person=A) == ["Alex turned your Tail on", "Alex drove your Lush"]
    assert texts(kinds=[el.SHOCK]) == ["Your avatar: vibrate 15 on Collar",
                                       "Sam: shock 20 on Collar"]
    assert texts(since=NOON - 3600) == ["Friends resumed", "Alex turned your Tail on",
                                        "Your avatar: vibrate 15 on Collar",
                                        "Sam: shock 20 on Collar"]
    assert texts(text="collar SAM") == ["Sam: shock 20 on Collar"]
    assert texts(text="alex") == ["Alex turned your Tail on", "Alex drove your Lush"]
    assert texts(kinds=[el.SHOCK], hide=[AVATAR]) == ["Sam: shock 20 on Collar"]
    # picking your avatar by name shows it, "everyone but your avatar" or not
    assert texts(person=AVATAR, hide=[AVATAR]) == ["Your avatar: vibrate 15 on Collar"]
    hits, total = log.query(limit=2)
    assert len(hits) == 2 and total == 5


# --- the day files -----------------------------------------------------------------

def _lines(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]


def test_flush_writes_one_jsonl_file_per_day(tmp_path):
    clock = [NOON + 10]
    log = EventLog(tmp_path, clock=lambda: clock[0])
    log.add(ev(NOON - 86400, "yesterday"))
    log.add(ev(NOON, "today 1"))
    log.add(ev(NOON + 1, "today 2"))
    assert log.flush() == 3
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["2026-11-13.jsonl", "2026-11-14.jsonl"]
    assert not any(n.endswith(".json") for n in names)       # settings backups copy those
    assert [d["text"] for d in _lines(tmp_path / "2026-11-14.jsonl")] == ["today 1", "today 2"]
    log.add(ev(NOON + 2, "today 3"))
    log.flush()
    assert [d["text"] for d in _lines(tmp_path / "2026-11-14.jsonl")][-1] == "today 3"
    assert log.flush() == 0


def test_a_drag_going_on_waits_and_lands_as_one_line(tmp_path):
    clock = [NOON]
    log = EventLog(tmp_path, clock=lambda: clock[0])
    log.add(ev(NOON, "Alex is online"))
    log.add(ev(NOON + 0.1, "strength 10 %"), key="str")
    clock[0] = NOON + 0.5
    assert log.flush() == 1                      # the drag may still change
    log.add(ev(NOON + 1.0, "strength 60 %"), key="str")
    clock[0] = NOON + 4.0                        # 3 s quiet: done
    assert log.flush() == 1
    assert [d["text"] for d in _lines(tmp_path / "2026-11-14.jsonl")] == [
        "Alex is online", "strength 60 %"]
    log.add(ev(NOON + 5, "strength 70 %"), key="str2")
    log.close()                                  # quitting writes the rest
    assert _lines(tmp_path / "2026-11-14.jsonl")[-1]["text"] == "strength 70 %"


def test_the_history_is_read_back_older_than_anything_new(tmp_path):
    clock = [NOON]
    first = EventLog(tmp_path, clock=lambda: clock[0])
    for i in range(3):
        first.add(ev(NOON - 86400 + i, f"old {i}"))
    first.add(ev(NOON - 10, "today"))
    first.close()
    with (tmp_path / "2026-11-14.jsonl").open("a", encoding="utf-8") as f:
        f.write("not json\n{}\n")                # a damaged file loses those lines only
    again = EventLog(tmp_path, clock=lambda: clock[0])
    assert not again.loaded
    again.add(ev(NOON + 1, "just now"))          # arrives while the files are read
    assert again.load() == 4
    assert again.loaded
    assert [e.text for e in again.recent()] == ["just now", "today", "old 2", "old 1", "old 0"]


def test_days_past_keep_days_are_dropped(tmp_path):
    clock = [NOON]
    for name in ("2026-10-15.jsonl", "2026-10-16.jsonl", "2026-11-14.jsonl",
                 "notes.txt", "2026-10-01.json"):
        (tmp_path / name).write_text(json.dumps({"t": NOON, "text": name}) + "\n",
                                     encoding="utf-8")
    log = EventLog(tmp_path, keep_days=30, clock=lambda: clock[0])
    assert log.rotate() == 1                     # 15 Oct is the 31st day back
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "2026-10-01.json", "2026-10-16.jsonl", "2026-11-14.jsonl", "notes.txt"]
    clock[0] = NOON + 86400                      # a day later, 16 Oct goes too
    log.add(ev(NOON - 29 * 86400, "16 Oct, in memory"))
    log.add(ev(NOON, "14 Nov, in memory"))
    assert log.rotate() == 1
    assert [e.text for e in log.recent()] == ["14 Nov, in memory"]


def test_clear_empties_memory_now_and_the_files_on_the_next_write(tmp_path):
    clock = [NOON]
    log = EventLog(tmp_path, clock=lambda: clock[0])
    log.add(ev(NOON - 86400, "yesterday"))
    log.add(ev(NOON, "today"))
    log.flush()
    (tmp_path / "keep.txt").write_text("not the log's", encoding="utf-8")
    log.clear()
    assert log.recent() == []
    log.add(ev(NOON + 1, "after clear"))
    clock[0] = NOON + 10
    log.flush()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-11-14.jsonl", "keep.txt"]
    assert [d["text"] for d in _lines(tmp_path / "2026-11-14.jsonl")] == ["after clear"]


def test_the_writer_thread_reads_writes_and_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(el, "FLUSH_S", 0.02)
    (tmp_path / el.day_name(time.time())).write_text(
        json.dumps({"t": time.time() - 5, "text": "from before"}) + "\n", encoding="utf-8")
    log = EventLog(tmp_path)
    log.start()
    deadline = time.time() + 5
    while not log.loaded and time.time() < deadline:
        time.sleep(0.01)
    assert [e.text for e in log.recent()] == ["from before"]
    log.add(ev(time.time(), "live"))
    deadline = time.time() + 5
    while time.time() < deadline:
        if "live" in (tmp_path / el.day_name(time.time())).read_text(encoding="utf-8"):
            break
        time.sleep(0.02)
    log.close()
    assert "live" in (tmp_path / el.day_name(time.time())).read_text(encoding="utf-8")
    assert log._thread is not None and not log._thread.is_alive()


def test_memory_only_never_writes(tmp_path):
    log = EventLog(None)
    log.add(ev(NOON))
    log.start()
    log.close()
    assert log.flush() == 0 and log.loaded and list(tmp_path.iterdir()) == []


# --- what was asked, what went out, and why (Blise's idea, 2026-11-16) ----------------

def test_a_corrected_record_keeps_what_was_asked_and_round_trips():
    e = ev(text="Alex: shock 40 · 2.0 s on Collar", kind=el.SHOCK, op="shock", dir=IN,
           level=25, ms=1200, on=("Collar",), asked_level=40, asked_ms=2000,
           fixed="their longest pulse")
    d = e.to_json()
    assert (d["alvl"], d["ams"], d["fix"]) == (40, 2000, "their longest pulse")
    assert Event.from_json(json.loads(json.dumps(d))) == e
    assert e.as_dict()["correction"] == "Lowered to 25 and cut to 1.2 s: their longest pulse"


def test_how_a_correction_reads():
    c = el.correction_text
    assert c(None, 30, 2000, 1200, "their longest pulse") == "Cut to 1.2 s: their longest pulse"
    assert c(40, 25, None, None, "your shock limit") == "Lowered to 25: your shock limit"
    assert c(None, None, 100, 1000, "OGP's shortest warning") == (
        "Stretched to 1.0 s: OGP's shortest warning")
    assert c(None, None, None, None, "a vibration instead: OGP's warnings vibrate") == (
        "A vibration instead: OGP's warnings vibrate")
    assert c(30, 30, 500, 500, "") == "" and c(None, 30, None, 500) == ""


def test_an_older_line_without_the_correction_reads_as_before():
    e = Event.from_json({"t": 1, "text": "Alex: shock 30", "kind": "shock", "lvl": 30})
    assert (e.asked_level, e.asked_ms, e.fixed, e.correction) == (None, None, "", "")
