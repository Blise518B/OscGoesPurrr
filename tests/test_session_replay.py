"""Tests for session replay: parameter_store live-input gating +
replay-frame application, JSONL frame reconstruction (snapshot + deltas),
and the ReplayFacade frame driver."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from parameter_store import ParameterStore
from session_replay import load_frames, replay_duration_ms
from controllers.replay_facade import ReplayFacade


# ============================================================ store gating

class TestStoreGating:
    def test_lock_drops_live_writes_replay_still_applies(self):
        s = ParameterStore()
        s.update_parameter("OGB/Orf/A/TouchOthers", 0.5)
        assert s.get_all_parameters()["OGB/Orf/A/TouchOthers"] == 0.5

        s.set_input_locked(True)
        s.update_parameter("OGB/Orf/A/TouchOthers", 0.9)   # live: dropped
        assert s.get_all_parameters()["OGB/Orf/A/TouchOthers"] == 0.5

        s.apply_replay_frame({"OGB/Orf/A/TouchOthers": 0.7})  # replay: wins
        assert s.get_all_parameters()["OGB/Orf/A/TouchOthers"] == 0.7

        s.set_input_locked(False)
        s.update_parameter("OGB/Orf/A/TouchOthers", 0.2)   # live resumes
        assert s.get_all_parameters()["OGB/Orf/A/TouchOthers"] == 0.2

    def test_replay_frame_drops_stale_ogb_keys(self):
        # A contact that ended mid-session must not latch: keys absent
        # from the new frame are removed.
        s = ParameterStore()
        s.apply_replay_frame({"OGB/Orf/A/PenOthers": 0.8,
                              "OGB/Orf/B/PenOthers": 0.4})
        s.apply_replay_frame({"OGB/Orf/A/PenOthers": 0.9})  # B released
        params = s.get_all_parameters()
        assert params == {"OGB/Orf/A/PenOthers": 0.9}

    def test_replay_frame_registers_new_zones(self):
        s = ParameterStore()
        s.apply_replay_frame({"OGB/Orf/Hole/PenOthers": 0.5,
                              "OGB/Pen/Shaft/PenOthers": 0.3})
        zones = s.get_detected_zones()
        assert "Hole" in zones["Orifices"]
        assert "Shaft" in zones["Penetrators"]

    def test_clear_ogb_leaves_non_ogb_params(self):
        s = ParameterStore()
        s.update_parameter("OGB/Orf/A/TouchOthers", 0.5)
        s.update_parameter("SomeAvatarBool", True)
        s.clear_ogb_params()
        params = s.get_all_parameters()
        assert "OGB/Orf/A/TouchOthers" not in params
        assert params["SomeAvatarBool"] is True
        assert s.get_detected_zones()["Orifices"] == []

    def test_rebuild_from_json_blocked_while_locked(self):
        s = ParameterStore()
        s.apply_replay_frame({"OGB/Orf/A/PenOthers": 0.6})
        s.set_input_locked(True)
        s.rebuild_from_json({"CONTENTS": {"Whatever": {"VALUE": [1.0]}}})
        assert "OGB/Orf/A/PenOthers" in s.get_all_parameters()
        assert "Whatever" not in s.get_all_parameters()

    def test_replay_bumps_packet_counter(self):
        # Keeps the routers'/stats' stale-signal monitors alive.
        s = ParameterStore()
        before = s.get_packets_received()
        s.apply_replay_frame({"OGB/Orf/A/PenOthers": 0.5})
        assert s.get_packets_received() == before + 1


# ============================================================ reconstruction

def _write_session(path, lines):
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")


class TestFrameReconstruction:
    def test_snapshot_then_deltas_fold_into_full_state(self, tmp_path):
        f = tmp_path / "session_x.jsonl"
        _write_session(f, [
            {"type": "header", "profile": "Default"},
            {"type": "ogb_snapshot", "t_ms": 0,
             "params": {"OGB/Orf/A/PenOthers": 0.1,
                        "OGB/Orf/B/PenOthers": 0.0}},
            {"type": "motor", "t_ms": 10, "device": "T", "motor": 0},  # ignored
            {"type": "ogb", "t_ms": 20,
             "params": {"OGB/Orf/A/PenOthers": 0.5}},
            {"type": "ogb", "t_ms": 40,
             "params": {"OGB/Orf/B/PenOthers": 0.9}},
        ])
        header, frames = load_frames(f)
        assert header["profile"] == "Default"
        assert [fr.t_ms for fr in frames] == [0, 20, 40]
        # Frames hold raw deltas (memory-bounded); the driver folds them.
        assert frames[0].is_full is True
        assert frames[0].params == {"OGB/Orf/A/PenOthers": 0.1,
                                    "OGB/Orf/B/PenOthers": 0.0}
        assert frames[1].is_full is False
        assert frames[1].params == {"OGB/Orf/A/PenOthers": 0.5}
        assert frames[2].params == {"OGB/Orf/B/PenOthers": 0.9}
        assert replay_duration_ms(frames) == 40

    def test_no_ogb_stream_yields_no_frames(self, tmp_path):
        f = tmp_path / "session_y.jsonl"
        _write_session(f, [
            {"type": "header", "profile": "P"},
            {"type": "motor", "t_ms": 5, "device": "T", "motor": 0},
        ])
        header, frames = load_frames(f)
        assert header["profile"] == "P"
        assert frames == []

    def test_malformed_lines_are_skipped(self, tmp_path):
        f = tmp_path / "session_z.jsonl"
        f.write_text(
            '{"type": "ogb_snapshot", "t_ms": 0, "params": {"OGB/Orf/A/PenOthers": 0.2}}\n'
            'not json at all\n'
            '{"type": "ogb", "t_ms": 10, "params": {"OGB/Orf/A/PenOthers": 0.7}}\n',
            encoding="utf-8")
        _header, frames = load_frames(f)
        assert len(frames) == 2
        assert frames[-1].params["OGB/Orf/A/PenOthers"] == 0.7

    def test_missing_file_is_empty(self, tmp_path):
        header, frames = load_frames(tmp_path / "nope.jsonl")
        assert header == {} and frames == []


# ============================================================ facade driver

class _FakeUI:
    def __init__(self):
        import threading as _t
        self._lock = _t.Lock()
        self.pending = []          # (delay_ms, fn)
        self.refreshes = 0

    def schedule_callback(self, delay_ms, fn):
        with self._lock:
            self.pending.append((delay_ms, fn))

    def schedule_on_main_thread(self, fn):
        # The load worker runs on a real daemon thread and posts its
        # continuation here.
        with self._lock:
            self.pending.append((0, fn))

    def refresh_replay_status(self):
        self.refreshes += 1

    def _pop(self):
        with self._lock:
            return self.pending.pop(0) if self.pending else None

    def run_pending(self, max_steps=2000):
        # Spin briefly so the background load thread can post its
        # continuation, then drain everything it schedules.
        import time as _time
        steps = 0
        deadline = _time.monotonic() + 3.0
        while steps < max_steps:
            item = self._pop()
            if item is None:
                if _time.monotonic() > deadline:
                    break
                _time.sleep(0.005)
                continue
            item[1]()
            steps += 1
            deadline = _time.monotonic() + 0.5


class _FakeRouter:
    def __init__(self):
        self.resets = 0

    def reset_outputs(self):
        self.resets += 1


class _Host(ReplayFacade):
    def __init__(self, sessions_dir, store):
        self.ui = _FakeUI()
        self.motor_router = _FakeRouter()
        self._sessions_dir = str(sessions_dir)
        self._store = store
        self.recalcs = 0
        self.logs = []
        self._recording = False

    def get_sessions_dir(self):
        return self._sessions_dir

    def is_session_logging_active(self):
        return self._recording

    def log_message(self, msg):
        self.logs.append(msg)

    def force_recalculate(self, dispatch_direct=False):
        self.recalcs += 1

    def _await_load(self):
        """Pump the fake UI until the background parse's continuation has
        run (replay becomes active, or reports empty)."""
        import time as _time
        deadline = _time.monotonic() + 3.0
        while self._replay_loading and _time.monotonic() < deadline:
            item = self.ui._pop()
            if item is not None:
                item[1]()
            else:
                _time.sleep(0.005)


@pytest.fixture
def replay_store(monkeypatch):
    # Point the facade + store module at a fresh store instance.
    s = ParameterStore()
    import controllers.replay_facade as rf
    import parameter_store as ps
    monkeypatch.setattr(rf, "store", s)
    monkeypatch.setattr(ps, "store", s)
    return s


class TestReplayFacade:
    def _session(self, tmp_path):
        f = tmp_path / "session_run.jsonl"
        _write_session(f, [
            {"type": "ogb_snapshot", "t_ms": 0,
             "params": {"OGB/Orf/A/PenOthers": 0.2}},
            {"type": "ogb", "t_ms": 100,
             "params": {"OGB/Orf/A/PenOthers": 0.8}},
            {"type": "ogb", "t_ms": 200,
             "params": {"OGB/Orf/A/PenOthers": 0.0}},
        ])
        return "session_run"

    def test_start_locks_input_and_applies_first_frame(
            self, tmp_path, replay_store):
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        assert h.start_replay(sid) is True   # accepted; loads async
        h._await_load()
        assert replay_store._input_locked is True
        # First frame applied once loaded.
        assert replay_store.get_all_parameters()["OGB/Orf/A/PenOthers"] == 0.2
        st = h.get_replay_status()
        assert st["active"] and st["session_id"] == sid
        assert st["duration_ms"] == 200

    def test_full_run_walks_frames_then_unlocks(self, tmp_path, replay_store):
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        h.start_replay(sid)
        h.ui.run_pending()
        # Finished: input unlocked, OGB cleared, not active.
        assert replay_store._input_locked is False
        assert h.get_replay_status()["active"] is False
        assert all(not k.startswith("OGB/")
                   for k in replay_store.get_all_parameters())

    def test_delta_folding_reconstructs_state(self, tmp_path, replay_store):
        # Second frame is a delta on A; after applying it the store must
        # carry the folded value, not just the delta.
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        h.start_replay(sid)
        h._await_load()               # frame 0: A=0.2
        item = h.ui._pop()            # frame 1: delta A=0.8
        assert item is not None
        item[1]()
        assert replay_store.get_all_parameters()["OGB/Orf/A/PenOthers"] == 0.8

    def test_stop_midway_unlocks_and_clears(self, tmp_path, replay_store):
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        h.start_replay(sid)
        h._await_load()              # first frame applied, next scheduled
        h.stop_replay()
        assert replay_store._input_locked is False
        assert h.get_replay_status()["active"] is False
        # A stale scheduled step must no-op (generation guard).
        h.ui.run_pending()
        assert h.get_replay_status()["active"] is False

    def test_stop_does_not_reset_router_caches(self, tmp_path, replay_store):
        # Regression: resetting the polling routers' caches on Stop
        # defeated their idle-zero path, latching e-stim ~10 s. Stop must
        # NOT reset them (only start does).
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        h.start_replay(sid)
        h._await_load()
        resets_after_start = h.motor_router.resets
        h.stop_replay()
        assert h.motor_router.resets == resets_after_start
        assert h.recalcs > 0   # but it did force_recalculate to zero toys

    def test_refuses_while_recording(self, tmp_path, replay_store):
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        h._recording = True
        assert h.start_replay(sid) is False
        assert replay_store._input_locked is False

    def test_refuses_double_start(self, tmp_path, replay_store):
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        assert h.start_replay(sid) is True
        # A second start while the first is still loading is rejected.
        assert h.start_replay(sid) is False

    def test_empty_session_reports_and_does_not_lock(
            self, tmp_path, replay_store):
        f = tmp_path / "session_empty.jsonl"
        _write_session(f, [{"type": "header", "profile": "P"}])
        h = _Host(tmp_path, replay_store)
        # Accepted synchronously (can't know it's empty without parsing)…
        assert h.start_replay("session_empty") is True
        h._await_load()
        # …then reported empty, with no lock left behind.
        assert replay_store._input_locked is False
        assert h.get_replay_status()["active"] is False
        assert any("no recorded contact" in m for m in h.logs)

    def test_cancel_during_load_never_locks(self, tmp_path, replay_store):
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        h.start_replay(sid)
        h.stop_replay()               # cancel while still parsing
        h._await_load()
        assert replay_store._input_locked is False
        assert h.get_replay_status()["active"] is False

    def test_hostile_session_id_rejected(self, tmp_path, replay_store):
        h = _Host(tmp_path, replay_store)
        assert h.start_replay("../evil") is False
        assert h.start_replay("") is False

    def test_speed_is_clamped(self, tmp_path, replay_store):
        sid = self._session(tmp_path)
        h = _Host(tmp_path, replay_store)
        h.start_replay(sid, speed=99.0)
        assert h.get_replay_status()["speed"] == 8.0
