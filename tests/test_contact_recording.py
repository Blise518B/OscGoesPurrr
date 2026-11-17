"""Record raw contacts (debug): the store's tap, the session logger's raw
lines, the setting, and replaying a raw recording through the store's whole
input path (see src/session_replay.py, docs/SESSION_LOGGING.md)."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from controllers.replay_facade import ReplayFacade
from controllers.sessions_facade import SessionsFacade, _RAW_PREFIXES
from parameter_store import ParameterStore
from session_logger import SessionLogger
from session_replay import RAW_BURST_MS, load_frames

REPO = Path(__file__).resolve().parent.parent


def _tapped(store):
    seen = {"packets": [], "snaps": []}
    store.set_contact_tap(
        lambda a, v: seen["packets"].append((a, v)),
        lambda values, types: seen["snaps"].append((values, types)),
        _RAW_PREFIXES)
    return seen


def _tree(params):
    """A tiny OSCQuery dump with `params` under avatar/parameters/."""
    leaves = {}
    for name, (value, tag) in params.items():
        node = leaves
        parts = name.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {"CONTENTS": {}})["CONTENTS"]
        node[parts[-1]] = {"VALUE": [value], "TYPE": tag}
    return {"CONTENTS": {"avatar": {"CONTENTS": {"parameters": {
        "CONTENTS": leaves}}}}}


# ------------------------------------------------------------- store tap

class TestStoreTap:
    def test_contact_packets_go_out_under_vrchat_names(self):
        s = ParameterStore()
        seen = _tapped(s)
        s.update_parameter("OGB/Socket/B/DepthSelf", 0.5)
        s.update_parameter("VFH/Zone/Touch/Head/Self", 0.2)
        s.update_parameter("OGB_ENABLED", True)
        s.update_parameter("avatar/change", "avtr_1")
        s.update_parameter("FaceTracking/JawOpen", 0.9)     # not a contact
        assert seen["packets"] == [
            ("OGB/Socket/B/DepthSelf", 0.5),
            ("VFH/Zone/Touch/Head/Self", 0.2),
            ("OGB_ENABLED", True),
            ("avatar/change", "avtr_1"),
        ]
        # ...while the store keeps its own names, as always.
        assert s.get_all_parameters()["OGB/Orf/B/DepthSelf"] == 0.5

    def test_no_tap_while_replaying_or_cleared(self):
        s = ParameterStore()
        seen = _tapped(s)
        s.set_input_locked(True)
        s.update_parameter("OGB/Socket/B/DepthSelf", 0.5)
        s.set_input_locked(False)
        s.clear_contact_tap()
        s.update_parameter("OGB/Socket/B/DepthSelf", 0.6)
        assert seen["packets"] == []

    def test_an_avatar_load_hands_over_its_contacts_unrenamed(self):
        s = ParameterStore()
        seen = _tapped(s)
        s.rebuild_from_json(_tree({
            "OGB/Socket/B/DepthRadius": (0.3, "f"),
            "OGB/Enabled": (False, "F"),
            "Smile": (1.0, "f"),
        }))
        (values, types), = seen["snaps"]
        assert values == {"OGB/Socket/B/DepthRadius": 0.3,
                          "OGB/Enabled": False}
        assert types["OGB/Socket/B/DepthRadius"] == "f"

    def test_a_failing_tap_never_breaks_input(self):
        s = ParameterStore()

        def boom(*_a):
            raise RuntimeError("disk full")
        s.set_contact_tap(boom, boom, _RAW_PREFIXES)
        s.update_parameter("OGB/Orf/B/TouchSelf", 0.4)
        s.rebuild_from_json(_tree({"OGB/Orf/B/TouchSelf": (0.1, "f")}))
        assert s.get_all_parameters()["OGB/Orf/B/TouchSelf"] == 0.1

    def test_contact_snapshot_leaves_out_derived_lengths(self):
        s = ParameterStore()
        s.update_parameter("OGB/Socket/B/DepthRadius", 0.5)
        s.update_parameter("OGB/Socket/B/DepthOthers_PointSeparation", 0.5)
        s.update_parameter("OGB/Socket/B/DepthOthers", 0.4)
        s.update_parameter("Smile", 1.0)
        values, _types = s.contact_snapshot(_RAW_PREFIXES)
        assert "OGB/Orf/B/DepthOthers_PlugLength" not in values
        assert values["OGB/Orf/B/DepthOthers"] == 0.4
        assert "Smile" not in values


class TestStoreReplay:
    def test_packets_take_the_whole_input_path_past_the_lock(self):
        s = ParameterStore()
        s.set_input_locked(True)
        s.replay_snapshot({"OGB/Socket/B/DepthRadius": 0.5})
        s.replay_packets([("OGB/Socket/B/DepthOthers_PointSeparation", 0.5),
                          ("OGB/Socket/B/DepthOthers", 0.4)], now=10.0)
        params, _v, zones = s.snapshot()
        assert zones == {("Orf", "B")}
        assert params["OGB/Orf/B/DepthOthers_PlugLength"] == pytest.approx(0.2)

    def test_replay_counts_no_onenter_edges(self):
        s = ParameterStore()
        s.replay_packets([("OGB/Touch/X/Hit", True)])
        _values, rises = s.read_watched(["OGB/Touch/X/Hit"])
        assert rises["OGB/Touch/X/Hit"] == 0

    def test_snapshot_replaces_contacts_only(self):
        s = ParameterStore()
        s.update_parameter("OGB/Orf/Old/TouchSelf", 0.3)
        s.update_parameter("Smile", 1.0)
        s.replay_snapshot({"OGB/Plug/T/LengthMult2": 0.2})
        params, _v, zones = s.snapshot()
        assert "OGB/Orf/Old/TouchSelf" not in params
        assert params["Smile"] == 1.0
        assert zones == {("Pen", "T")}


# ------------------------------------------------------------- logger

class TestLoggerRawLines:
    def test_raw_lines_are_written(self, tmp_path):
        lg = SessionLogger(tmp_path)
        lg.start({"raw_contacts": True})
        lg.log_raw(12.345, "OGB/Socket/B/DepthSelf", 0.123456789)
        lg.log_raw(13.0, "OGB/Enabled", True)
        lg.log_raw_snapshot(0.0, {"OGB/Socket/B/DepthRadius": 0.3},
                            {"OGB/Socket/B/DepthRadius": "f"}, "oscquery")
        lg.stop()
        lines = [json.loads(x) for x in
                 next(tmp_path.glob("session_*.jsonl")).read_text(
                     encoding="utf-8").splitlines()]
        raw = [x for x in lines if x["type"] == "raw"]
        assert raw[0] == {"type": "raw", "t_ms": 12.35,
                          "a": "OGB/Socket/B/DepthSelf", "v": 0.123457}
        assert raw[1]["v"] is True
        snap, = [x for x in lines if x["type"] == "raw_snapshot"]
        assert snap["source"] == "oscquery"
        assert snap["params"] == {"OGB/Socket/B/DepthRadius": 0.3}
        meta = SessionLogger.list_sessions(tmp_path)[0]
        assert meta["raw_contacts"] is True

    def test_nan_survives_as_text(self, tmp_path):
        lg = SessionLogger(tmp_path)
        lg.start()
        lg.log_raw(1.0, "OGB/Orf/B/TouchSelf", float("nan"))
        lg.stop()
        text = next(tmp_path.glob("session_*.jsonl")).read_text(encoding="utf-8")
        assert '"v": "nan"' in text


# ------------------------------------------------------------- frames

def _write(path, lines):
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")


class TestRawFrames:
    def test_bursts_snapshots_and_the_ogb_stream_before_them(self, tmp_path):
        f = tmp_path / "session_raw.jsonl"
        _write(f, [
            {"type": "header", "raw_contacts": True},
            {"type": "ogb_snapshot", "t_ms": 0, "params": {"OGB/Orf/A/PenSelf": 0.1}},
            {"type": "ogb", "t_ms": 50, "params": {"OGB/Orf/A/PenSelf": 0.2}},
            {"type": "raw_snapshot", "t_ms": 100, "source": "store",
             "params": {"OGB/Orf/A/PenSelf": 0.2}},
            {"type": "ogb", "t_ms": 120, "params": {"OGB/Orf/A/PenSelf": 0.3}},
            {"type": "raw", "t_ms": 110.0, "a": "OGB/Socket/B/DepthSelf", "v": 0.1},
            {"type": "raw", "t_ms": 110.4, "a": "OGB/Socket/B/DepthSelf_PointSeparation", "v": 0.3},
            {"type": "raw", "t_ms": 110.0 + RAW_BURST_MS + 9, "a": "OGB/Socket/B/DepthSelf", "v": 0.2},
        ])
        _header, frames = load_frames(f)
        kinds = [(fr.kind, fr.t_ms) for fr in frames]
        # The OGB stream until raw lines begin, then raw only.
        assert kinds == [("ogb", 0), ("ogb", 50), ("raw_snapshot", 100),
                         ("raw", 110.0), ("raw", 110.0 + RAW_BURST_MS + 9)]
        assert frames[3].packets == [
            ("OGB/Socket/B/DepthSelf", 0.1),
            ("OGB/Socket/B/DepthSelf_PointSeparation", 0.3)]

    def test_old_recordings_replay_as_before(self, tmp_path):
        f = tmp_path / "session_old.jsonl"
        _write(f, [{"type": "ogb_snapshot", "t_ms": 0,
                    "params": {"OGB/Orf/A/PenSelf": 0.1}}])
        _header, frames = load_frames(f)
        assert [fr.kind for fr in frames] == ["ogb"]


# ------------------------------------------------------------- facades

class _UI:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = []

    def schedule_callback(self, delay_ms, fn):
        with self.lock:
            self.pending.append(fn)

    def schedule_on_main_thread(self, fn):
        with self.lock:
            self.pending.append(fn)

    def pump(self, limit=500):
        deadline = time.monotonic() + 3.0
        done = 0
        while done < limit and time.monotonic() < deadline:
            with self.lock:
                fn = self.pending.pop(0) if self.pending else None
            if fn is None:
                time.sleep(0.005)
                continue
            fn()
            done += 1


class _ReplayHost(ReplayFacade):
    def __init__(self, sessions_dir):
        self.ui = _UI()
        self._dir = str(sessions_dir)
        self.levels = []
        self.logs = []

    def get_sessions_dir(self):
        return self._dir

    def is_session_logging_active(self):
        return False

    def log_message(self, msg):
        self.logs.append(msg)

    def force_recalculate(self, dispatch_direct=False):
        import parameter_store
        self.levels.append(dict(parameter_store.store.get_all_parameters()))


@pytest.fixture
def fresh_store(monkeypatch):
    s = ParameterStore()
    import controllers.replay_facade as rf
    import parameter_store as ps
    monkeypatch.setattr(rf, "store", s)
    monkeypatch.setattr(ps, "store", s)
    return s


class TestReplayFacadeRaw:
    def test_a_raw_recording_replays_through_the_input_path(
            self, tmp_path, fresh_store):
        _write(tmp_path / "session_r.jsonl", [
            {"type": "raw_snapshot", "t_ms": 0, "source": "oscquery",
             "params": {"OGB/Socket/B/DepthRadius": 0.5}},
            {"type": "raw", "t_ms": 5, "a": "OGB/Socket/B/DepthOthers_PointSeparation", "v": 0.5},
            {"type": "raw", "t_ms": 5.2, "a": "OGB/Socket/B/DepthOthers", "v": 0.4},
        ])
        h = _ReplayHost(tmp_path)
        assert h.start_replay("session_r")
        h.ui.pump()
        # Renamed, and the plug length measured from the replayed packets
        # (the last recalculation is after Stop, with the contacts cleared).
        lengths = [lv.get("OGB/Orf/B/DepthOthers_PlugLength")
                   for lv in h.levels]
        assert pytest.approx(0.2) in lengths
        assert h.levels[-1] == {}
        assert not fresh_store._input_locked          # finished, unlocked


class _SessionsHost(SessionsFacade):
    def __init__(self):
        self.logs = []

    def log_message(self, msg):
        self.logs.append(msg)


class TestSessionsFacadeRaw:
    def _host(self, tmp_path, monkeypatch, raw_on):
        import controllers.sessions_facade as sf
        import settings.sessions as ss
        monkeypatch.setattr(ss, "SESSIONS_SETTINGS_FILE",
                            str(tmp_path / "sessions_settings.json"))
        monkeypatch.setattr(sf, "SESSIONS_DIR", tmp_path / "sessions")
        s = ParameterStore()
        monkeypatch.setattr(sf, "store", s)
        h = _SessionsHost()
        h._session_init_components()
        h._session_logger = SessionLogger(tmp_path / "sessions")
        h.set_session_settings(enabled=True, raw_contacts=raw_on)
        return h, s

    def _lines(self, tmp_path):
        f = next((tmp_path / "sessions").glob("session_*.jsonl"))
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]

    def test_raw_on_records_packets_and_what_was_loaded(
            self, tmp_path, monkeypatch):
        h, s = self._host(tmp_path, monkeypatch, raw_on=True)
        s.update_parameter("OGB/Plug/T/LengthMult2", 0.2)   # before recording
        h.start_session_logging()
        s.update_parameter("OGB/Plug/T/DepthOthers", 0.7)
        s.update_parameter("Smile", 1.0)
        h.stop_session_logging()
        s.update_parameter("OGB/Plug/T/DepthOthers", 0.1)   # after: not recorded
        lines = self._lines(tmp_path)
        assert lines[0]["raw_contacts"] is True
        snap, = [x for x in lines if x["type"] == "raw_snapshot"]
        assert snap["source"] == "store"
        assert snap["params"] == {"OGB/Pen/T/LengthMult2": 0.2}
        assert [(x["a"], x["v"]) for x in lines if x["type"] == "raw"] == [
            ("OGB/Plug/T/DepthOthers", 0.7)]

    def test_motor_lines_are_on_the_session_clock(self, tmp_path, monkeypatch):
        # The router's own clock is time.monotonic; the line must not
        # take it for wall time.
        h, _s = self._host(tmp_path, monkeypatch, raw_on=False)
        h.start_session_logging()
        h._session_on_motor("Lush", 0, {"t_unix": time.monotonic(),
                                        "d_raw": 0.5, "out": 0.4})
        h.stop_session_logging()
        motor, = [x for x in self._lines(tmp_path) if x["type"] == "motor"]
        assert 0.0 <= motor["t_ms"] < 5000.0

    def test_raw_off_records_none(self, tmp_path, monkeypatch):
        h, s = self._host(tmp_path, monkeypatch, raw_on=False)
        h.start_session_logging()
        s.update_parameter("OGB/Plug/T/DepthOthers", 0.7)
        h.stop_session_logging()
        assert not [x for x in self._lines(tmp_path)
                    if x["type"] in ("raw", "raw_snapshot")]

    def test_switching_it_on_mid_session_starts_recording(
            self, tmp_path, monkeypatch):
        h, s = self._host(tmp_path, monkeypatch, raw_on=False)
        h.start_session_logging()
        s.update_parameter("OGB/Plug/T/DepthOthers", 0.3)
        h.set_session_settings(raw_contacts=True)
        s.update_parameter("OGB/Plug/T/DepthOthers", 0.4)
        h.stop_session_logging()
        raw = [x for x in self._lines(tmp_path) if x["type"] == "raw"]
        assert [x["v"] for x in raw] == [0.4]


# ------------------------------------------------------------- the tool

def test_contact_debug_reads_a_raw_recording(tmp_path, capsys):
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import contact_debug
    finally:
        sys.path.pop(0)
    f = tmp_path / "session_t.jsonl"
    lines = [{"type": "header", "app_version": "0.15.1-debug",
              "raw_contacts": True, "toys": [{"name": "Lush"}]},
             {"type": "raw_snapshot", "t_ms": 0, "source": "oscquery",
              "params": {"OGB/Socket/B/DepthRadius": 0.5,
                         "OGB/Enabled": False}, "types": {}}]
    t = 10.0
    for prox in (0.2, 0.4, 0.6, 0.8, 0.9):                  # a 20 cm plug in
        lines.append({"type": "raw", "t_ms": t, "a": "OGB/Socket/B/DepthOthers_PointSeparation",
                      "v": 0.2 + 0.5 * (1 - prox)})
        lines.append({"type": "raw", "t_ms": t + 0.3, "a": "OGB/Socket/B/DepthOthers", "v": prox})
        t += 50
    lines.append({"type": "raw", "t_ms": t, "a": "OGB/Socket/B/DepthOthers_PointSeparation", "v": 0.1})
    lines.append({"type": "raw", "t_ms": t + 0.3, "a": "OGB/Socket/B/DepthOthers", "v": 1.0})
    lines.append({"type": "motor", "t_ms": t, "device": "Lush", "motor": 0,
                  "d_raw": 0.5, "out": 0.4})
    _write(f, lines)
    out_csv = tmp_path / "zones.csv"
    contact_debug.main([str(f), "--csv", str(out_csv), "--hz", "1000"])
    out = capsys.readouterr().out
    assert "Socket B" in out and "SPS 3" in out
    assert "Orf/B: peak level 0.500" in out
    assert "Lush motor 0: peak out 0.400" in out
    assert out_csv.read_text(encoding="utf-8").startswith("t_s,zone,sps3,level")
