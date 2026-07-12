"""Session-replay controller facade.

Mixin: plays a recorded session's OGB contact stream back through the
live routing pipeline so the user can re-tune modes / chains against real
captured motion with no partner present. Composed into OscGoesPurrrApp.

How it works: `session_replay.load_frames` parses the recorded OGB
events; this facade locks live OSC input at the parameter_store choke
point, then walks the frames on the GUI thread at the recorded cadence
(optionally time-scaled), folding each delta onto a running state,
applying it to the store, and forcing a recalculation. The routing
pipeline — current mode, master scale, chains — turns that motion into
output exactly as if it were live, which is the whole point.

The JSONL parse runs on a daemon thread (a 2-hour recording is hundreds
of MB — parsing it on the GUI thread would freeze routing), then hands
the frames back to the GUI thread to begin playback.

Host attributes assumed: `self.ui`, `self.motor_router`,
`self.log_message`, `self.force_recalculate`, and the sessions facade's
`get_sessions_dir()` / `is_session_logging_active()`.
"""

import os
import threading
from typing import Any, Dict, List

from parameter_store import store
from session_replay import ReplayFrame, load_frames, replay_duration_ms

# A single inter-frame wait is capped so a long idle stretch in the
# recording (a pause between scenes) doesn't freeze replay for minutes —
# the gap is compressed to this ceiling. Active motion is unaffected
# (its frames are milliseconds apart).
_MAX_FRAME_GAP_MS = 3000.0


class ReplayFacade:

    # Declared so status/guards work before any replay starts.
    _replay_active = False
    _replay_gen = 0
    _replay_frames: List[ReplayFrame] = []
    _replay_idx = 0
    _replay_session_id = ""
    _replay_speed = 1.0
    _replay_duration_ms = 0.0
    _replay_state: Dict[str, Any] = {}
    _replay_loading = False

    # ------------------------------------------------------------------
    # UI facade
    # ------------------------------------------------------------------

    def start_replay(self, session_id: str, speed: float = 1.0) -> bool:
        """Begin replaying session `session_id`'s OGB stream. The file is
        parsed on a background thread; playback starts once it's loaded.
        Returns False for a synchronous rejection (already
        replaying/loading, currently recording, or unknown session);
        an empty/no-contact file is reported after the async load."""
        if self._replay_active or self._replay_loading:
            return False
        if getattr(self, "is_session_logging_active", lambda: False)():
            self.log_message("Can't replay while a session is recording — "
                             "stop recording first.")
            return False
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            speed = 1.0
        speed = max(0.1, min(8.0, speed))

        path = self._replay_path(session_id)
        if not path:
            self.log_message(f"Replay: session '{session_id}' not found")
            return False

        self._replay_session_id = str(session_id)
        self._replay_speed = speed
        self._replay_loading = True
        self._replay_gen += 1
        gen = self._replay_gen
        self.log_message(f"Loading '{session_id}' for replay…")
        self._replay_refresh_ui()

        def _worker():
            _header, frames = load_frames(path)
            ui = getattr(self, "ui", None)
            post = getattr(ui, "schedule_on_main_thread", None)
            if post is not None:
                post(lambda: self._on_frames_loaded(gen, frames))
            else:  # headless: fold back synchronously
                self._on_frames_loaded(gen, frames)

        threading.Thread(target=_worker, daemon=True,
                         name="ReplayLoad").start()
        return True

    def _on_frames_loaded(self, gen: int, frames: List[ReplayFrame]) -> None:
        """GUI-thread continuation once the JSONL has parsed. Superseded
        by a stop()/new start() if `gen` no longer matches."""
        if gen != self._replay_gen or not self._replay_loading:
            return  # stopped or restarted during the load
        self._replay_loading = False
        if not frames:
            self.log_message(
                f"Replay: '{self._replay_session_id}' has no recorded "
                "contact to replay (OGB logging may have been off).")
            self._replay_refresh_ui()
            return
        self._replay_frames = frames
        self._replay_idx = 0
        self._replay_state = {}
        self._replay_duration_ms = replay_duration_ms(frames)
        self._replay_active = True
        # Block live OSC at the store so a stray packet / present partner
        # can't fight the replayed motion.
        store.set_input_locked(True)
        self._replay_reset_caches()
        self.log_message(
            f"▶ Replaying '{self._replay_session_id}' "
            f"({len(frames)} frames, {self._replay_duration_ms / 1000.0:.0f}s"
            f"{'' if self._replay_speed == 1.0 else f', {self._replay_speed:g}×'})"
            " — live OSC paused")
        self._replay_refresh_ui()
        self._replay_step(self._replay_gen)

    def stop_replay(self) -> None:
        """Stop replaying, unblock live OSC, and zero the replayed
        contacts so nothing latches. Safe to call when not replaying."""
        if not self._replay_active and not self._replay_loading:
            return
        was_active = self._replay_active
        self._replay_active = False
        self._replay_loading = False
        self._replay_gen += 1  # cancels any scheduled step / pending load
        if not was_active:
            # Cancelled while still parsing the file — the store was never
            # locked and nothing was dispatched.
            self.log_message(
                f"Cancelled loading '{self._replay_session_id}'")
            self._replay_refresh_ui()
            return
        store.clear_ogb_params()
        store.set_input_locked(False)
        # DELIBERATELY do NOT reset the polling routers' dispatch caches
        # here. force_recalculate below zeros the Buttplug toys (via the
        # changed-value comparison). The e-stim / EMS / stroker backends
        # zero themselves on their next ~60 Hz tick through router_base's
        # "store emptied while outputs live" idle path — but that path is
        # gated on `_last_outputs` being non-empty, so clearing it (as the
        # mode-switch reset does) would SKIP the zero and latch the last
        # replayed strength on hardware until the 10 s stale cutoff. Leave
        # the caches intact so the idle-zero fires immediately on Stop.
        if hasattr(self, "force_recalculate"):
            self.force_recalculate(dispatch_direct=True)
        self.log_message(
            f"■ Stopped replay of '{self._replay_session_id}' — "
            "live OSC resumed")
        self._replay_refresh_ui()

    def get_replay_status(self) -> Dict[str, Any]:
        """UI state: whether replay is active, which session, and how far
        through it is."""
        pos = 0.0
        if self._replay_frames and self._replay_idx > 0:
            i = min(self._replay_idx, len(self._replay_frames)) - 1
            pos = self._replay_frames[i].t_ms
        return {
            "active": self._replay_active,
            "loading": self._replay_loading,
            "session_id": self._replay_session_id,
            "position_ms": pos,
            "duration_ms": self._replay_duration_ms,
            "speed": self._replay_speed,
        }

    # ------------------------------------------------------------------
    # Frame driver (GUI thread, via ui.schedule_callback)
    # ------------------------------------------------------------------

    def _replay_step(self, gen: int) -> None:
        """Apply the current frame and schedule the next. `gen` guards
        against a stop()/restart having superseded this chain."""
        if not self._replay_active or gen != self._replay_gen:
            return
        frames = self._replay_frames
        if self._replay_idx >= len(frames):
            self.log_message(f"Replay of '{self._replay_session_id}' finished")
            self.stop_replay()
            return
        frame = frames[self._replay_idx]
        try:
            # Fold the frame onto the running OGB state: a full snapshot
            # replaces it, a delta merges. The store gets the complete
            # current state each tick (it drops keys a fresh snapshot no
            # longer lists).
            if frame.is_full:
                self._replay_state = dict(frame.params)
            else:
                self._replay_state.update(frame.params)
            store.apply_replay_frame(self._replay_state)
            if hasattr(self, "force_recalculate"):
                self.force_recalculate(dispatch_direct=True)
        except Exception as e:
            self.log_message(f"Replay error: {e}")
            self.stop_replay()
            return
        self._replay_idx += 1
        self._replay_refresh_ui()

        if self._replay_idx >= len(frames):
            # Let the final contact settle briefly, then finish.
            self._schedule_step(gen, 200.0)
            return
        gap = frames[self._replay_idx].t_ms - frame.t_ms
        gap = max(0.0, min(_MAX_FRAME_GAP_MS, gap)) / self._replay_speed
        self._schedule_step(gen, gap)

    def _schedule_step(self, gen: int, delay_ms: float) -> None:
        ui = getattr(self, "ui", None)
        schedule = getattr(ui, "schedule_callback", None)
        if schedule is None:
            return  # headless / torn down — driver simply stops
        schedule(int(round(delay_ms)), lambda: self._replay_step(gen))

    def _replay_refresh_ui(self) -> None:
        ui = getattr(self, "ui", None)
        refresh = getattr(ui, "refresh_replay_status", None)
        if refresh is not None:
            try:
                refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _replay_path(self, session_id: str):
        try:
            sessions_dir = self.get_sessions_dir()
        except Exception:
            return None
        # session_id is a filename stem; refuse anything that could escape
        # the sessions dir.
        sid = str(session_id or "")
        if not sid or sid in (".", "..") or "/" in sid or "\\" in sid:
            return None
        path = os.path.join(sessions_dir, sid + ".jsonl")
        return path if os.path.isfile(path) else None

    def _replay_reset_caches(self) -> None:
        """Reuse the modes facade's all-router cache reset when present so
        the first frame re-dispatches cleanly across every backend;
        degrade to the motor router alone otherwise."""
        reset = getattr(self, "_reset_output_caches", None)
        if reset is not None:
            try:
                reset()
                return
            except Exception:
                pass
        if hasattr(self, "motor_router"):
            try:
                self.motor_router.reset_outputs()
            except Exception:
                pass
