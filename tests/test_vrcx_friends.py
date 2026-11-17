"""Import from VRCX: your VRChat friends read from VRCX's database --
read-only, coping with VRCX holding the file, and nothing but ids and names.

Every database here is synthetic, built in the test's own folder with the
table and column names a real VRCX database has (checked 2026-11-14)."""

import os
import sqlite3
import threading
from pathlib import Path

import pytest

import vrcx_friends

ACCOUNT = "usr" + "1" * 32          # the VRChat account logged in to VRCX
ALT = "usr" + "2" * 32              # a second one


def uid(n: int) -> str:
    return f"usr_{n:08x}-0000-4000-8000-{n:012x}"


def make_db(path: Path, tables=None, journal="delete") -> Path:
    """A database shaped like VRCX's: a friend list per account, its
    history, a config table."""
    tables = {ACCOUNT: [(uid(1), "Mika"), (uid(2), "  Kiko   the  Cat "), (uid(3), "alex")],
              ALT: [(uid(2), "Kiko (older name)"), (uid(4), "Nova")]} if tables is None else tables
    con = sqlite3.connect(str(path))
    con.execute(f"PRAGMA journal_mode={journal}")
    con.execute("CREATE TABLE configs (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO configs VALUES ('config:lastuserloggedin', ?)", (uid(99),))
    for account, rows in tables.items():
        con.execute(f'CREATE TABLE "{account}_friend_log_current" (user_id TEXT PRIMARY KEY,'
                    ' display_name TEXT, trust_level TEXT, friend_number INTEGER)')
        con.execute(f'CREATE TABLE "{account}_friend_log_history" (id INTEGER PRIMARY KEY,'
                    ' created_at TEXT, type TEXT, user_id TEXT, display_name TEXT,'
                    ' previous_display_name TEXT, trust_level TEXT, previous_trust_level TEXT,'
                    ' friend_number INTEGER)')
        con.execute(f'INSERT INTO "{account}_friend_log_history" (user_id, display_name)'
                    ' VALUES (?, ?)', (uid(50), "Someone you unfriended"))
        for n, (u, name) in enumerate(rows):
            con.execute(f'INSERT INTO "{account}_friend_log_current" VALUES (?, ?, ?, ?)',
                        (u, name, "Trusted", n))
    con.commit()
    con.close()
    return path


@pytest.fixture
def db(tmp_path):
    return make_db(tmp_path / "VRCX.sqlite3")


def test_reads_every_accounts_friends_once_by_name(db):
    got = vrcx_friends.read_friends(db)
    assert got["state"] == "ok"
    # the first account's name wins for a friend both know; names cleaned;
    # by name, any case; never the history table's unfriended person
    assert got["friends"] == [(uid(3), "alex"), (uid(2), "Kiko the Cat"),
                              (uid(1), "Mika"), (uid(4), "Nova")]


def test_rows_that_are_no_vrchat_user_are_skipped(tmp_path):
    db = make_db(tmp_path / "x.sqlite3", {ACCOUNT: [
        (uid(1), "Mika"), ("not-an-id", "Broken"), (uid(5), "   "), ("usr_" + "z" * 36, "Odd"),
        (uid(6).upper(), "Shouty")]})
    got = vrcx_friends.read_friends(db)
    assert got["friends"] == [(uid(1), "Mika"), (uid(6), "Shouty")]


def test_no_vrcx_on_this_pc(tmp_path, monkeypatch):
    assert vrcx_friends.read_friends(tmp_path / "nope.sqlite3") == {"state": "missing",
                                                                     "friends": []}
    assert not vrcx_friends.installed(tmp_path / "nope.sqlite3")
    monkeypatch.setattr(vrcx_friends, "default_path", lambda: None)
    assert vrcx_friends.read_friends()["state"] == "missing"


def test_vrcx_never_logged_in_has_no_friend_list(tmp_path):
    db = make_db(tmp_path / "x.sqlite3", {})
    assert vrcx_friends.read_friends(db) == {"state": "none", "friends": []}


def test_not_a_database(tmp_path):
    bad = tmp_path / "VRCX.sqlite3"
    bad.write_bytes(b"this is not sqlite" * 100)
    got = vrcx_friends.read_friends(bad)
    assert got["state"] == "error" and got["friends"] == []


def test_the_file_is_never_written(db):
    before = (db.read_bytes(), os.stat(db).st_mtime_ns)
    names = set(os.listdir(db.parent))
    vrcx_friends.read_friends(db)
    assert (db.read_bytes(), os.stat(db).st_mtime_ns) == before
    assert set(os.listdir(db.parent)) == names          # no journal left behind


def test_the_connection_is_read_only(db):
    con = sqlite3.connect(vrcx_friends._ro_uri(db), uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("CREATE TABLE sneaky (x)")
    finally:
        con.close()


def test_a_path_with_spaces_and_accents(tmp_path):
    folder = tmp_path / "Bénédicte's AppData" / "VRCX #1"
    folder.mkdir(parents=True)
    db = make_db(folder / "VRCX.sqlite3")
    assert vrcx_friends.read_friends(db)["state"] == "ok"


def test_vrcx_running_beside_us_wal(tmp_path):
    """VRCX keeps its file open in WAL mode, writing now and then: a reader
    reads beside it."""
    db = make_db(tmp_path / "VRCX.sqlite3", journal="wal")
    vrcx = sqlite3.connect(str(db))
    try:
        vrcx.execute("BEGIN IMMEDIATE")
        vrcx.execute(f'INSERT INTO "{ACCOUNT}_friend_log_current" VALUES (?, ?, ?, ?)',
                     (uid(7), "Not committed yet", "Known", 9))
        got = vrcx_friends.read_friends(db)
        assert got["state"] == "ok"
        assert (uid(7), "Not committed yet") not in got["friends"]
        assert (uid(1), "Mika") in got["friends"]
    finally:
        vrcx.rollback()
        vrcx.close()


def test_vrcx_holding_a_lock_is_busy_not_a_freeze(tmp_path):
    db = make_db(tmp_path / "VRCX.sqlite3", journal="delete")
    vrcx = sqlite3.connect(str(db))
    try:
        vrcx.execute("BEGIN EXCLUSIVE")
        result = {}
        t = threading.Thread(target=lambda: result.update(vrcx_friends.read_friends(db)))
        t.start()
        t.join(5.0)
        assert not t.is_alive()                  # gave up quickly, never hung
        assert result["state"] == "busy" and result["friends"] == []
    finally:
        vrcx.rollback()
        vrcx.close()
    assert vrcx_friends.read_friends(db)["state"] == "ok"     # and again once it's free


def test_default_path(monkeypatch, tmp_path):
    if os.name == "nt":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert vrcx_friends.default_path() == tmp_path / "VRCX" / "VRCX.sqlite3"
        monkeypatch.delenv("APPDATA")
        assert vrcx_friends.default_path() is None
    else:
        assert vrcx_friends.default_path().parts[-3:] == (".config", "VRCX", "VRCX.sqlite3")
