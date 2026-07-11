"""Session-logger controller facade.

Mixin: owns the `SessionLogger` engine + `SessionSettingsManager`,
exposes start/stop/list/delete to the UI, and adapts the routing-
thread broadcast callbacks into the engine's primitive log_* calls.

Wiring contract (see docs/SESSION_LOGGING.md):

* `__init__` of OscGoesPurrrApp calls `_session_init_components()`
  once, before the routing tick starts.
* The routing tick calls `_session_sample_tick()` every tick while
  a session is recording — that's what feeds the OGB-param and
  bHaptics-dot streams. The motor stream is pushed automatically
  by the `motor_router.set_session_broadcast(...)` callback the
  facade registers on start.
* `quit_app()` calls `stop_session_logging()` so the footer lands.
"""

import os
import sys
from typing import Any, Dict, List, Optional

from parameter_store import store
from session_logger import SessionLogger
from settings import SESSIONS_DIR, SessionSettingsManager


# Parameter-store keys are filtered to this prefix before being sent
# to the session logger's OGB stream. SPS-mirror entries are
# always-on OGB consumers, so logging this prefix gives us full
# coverage of every input the router or the mirror could care about.
_OGB_PREFIX = "OGB/"


class SessionsFacade:
    """Mixin: VR session logger management. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Init / shutdown wiring (called from main.py)
    # ------------------------------------------------------------------

    def _session_init_components(self) -> None:
        """Build the logger + settings instances. Must run once before
        any session can start. Called from OscGoesPurrrApp.__init__."""
        self._session_settings: SessionSettingsManager = SessionSettingsManager()
        self._session_logger: SessionLogger = SessionLogger(SESSIONS_DIR)
        # Cached at start so the broadcast adapter doesn't reach into
        # the logger's internals every motor tick to compute t_ms.
        self._session_started_at_unix: Optional[float] = None
        # bHaptics dedup: the bHaptics router runs its own poll loop at
        # a separate rate (often slower than the motor router), so
        # sampling it on every motor-router tick can produce identical
        # snapshots N times in a row. We hash the snapshot to a
        # comparable tuple and skip the log call when unchanged.
        # Reset on every start/stop.
        self._session_last_bhaptics_sig: tuple = ()

    def _session_auto_start_if_configured(self) -> None:
        """Honour `enabled and auto_start` from the settings file by
        starting a session on app launch. Called from main.py after
        all engines and the routing tick are wired up."""
        try:
            s = self._session_settings.snapshot()
        except Exception:
            return
        if not (s.get("enabled") and s.get("auto_start")):
            return
        try:
            self.start_session_logging()
        except Exception as e:
            self.log_message(f"Session logger auto-start failed: {e}")

    def _session_stop_for_shutdown(self) -> None:
        """Best-effort stop so the footer + final flush land before
        the process exits. Called from quit_app."""
        try:
            self.stop_session_logging()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API — start / stop
    # ------------------------------------------------------------------

    def start_session_logging(self) -> Optional[str]:
        """Open a new session file with current-app metadata in the
        header, wire the motor_router broadcast, and prune old files
        per the retention setting. Returns the session id, or None
        if a session is already running (idempotent guard)."""
        if self._session_logger.is_running:
            return self._session_logger.current_session and self._session_logger.current_session.get("id")
        # Retention pruning runs on every start (not on stop, not on a
        # timer) — see docs/SESSION_LOGGING.md.
        try:
            keep = self._session_settings.get_retention()
            SessionLogger.prune(SESSIONS_DIR, keep_n=keep)
        except Exception:
            pass
        metadata = self._session_build_metadata()
        sid = self._session_logger.start(metadata)
        # Cache start time for the broadcast adapter's relative-ms math.
        cs = self._session_logger.current_session or {}
        self._session_started_at_unix = float(cs.get("started_at_unix", 0.0))
        self._session_last_bhaptics_sig = ()
        # Hook the routers AFTER the file is open + state is cached, so
        # the very first broadcast already has a sane start time.
        try:
            if hasattr(self, "motor_router") and self.motor_router is not None:
                self.motor_router.set_session_broadcast(self._session_on_motor)
        except Exception as e:
            self.log_message(f"Session logger: failed to hook motor_router: {e}")
        self.log_message(f"Session logging started → {sid}")
        return sid

    def stop_session_logging(self) -> None:
        """Stop the current session (idempotent). Unhooks the
        motor_router broadcast so the per-tick callback drops back to
        a single None comparison."""
        try:
            if hasattr(self, "motor_router") and self.motor_router is not None:
                self.motor_router.set_session_broadcast(None)
        except Exception:
            pass
        if not self._session_logger.is_running:
            return
        sid = (self._session_logger.current_session or {}).get("id", "?")
        self._session_logger.stop()
        self._session_started_at_unix = None
        self._session_last_bhaptics_sig = ()
        self.log_message(f"Session logging stopped → {sid}")

    def is_session_logging_active(self) -> bool:
        return bool(self._session_logger and self._session_logger.is_running)

    # ------------------------------------------------------------------
    # Public API — status + library
    # ------------------------------------------------------------------

    def get_session_logging_status(self) -> Dict[str, Any]:
        """One-shot status for the UI: settings snapshot + (if a session
        is active) live duration/event-count/size info."""
        settings = self._session_settings.snapshot()
        active = self._session_logger.current_session if self._session_logger else None
        return {
            "settings":      settings,
            "active":        active,
            "sessions_dir":  str(SESSIONS_DIR),
        }

    def list_logged_sessions(self) -> List[Dict[str, Any]]:
        return SessionLogger.list_sessions(SESSIONS_DIR)

    def delete_logged_session(self, session_id: str) -> bool:
        return SessionLogger.delete_session(SESSIONS_DIR, session_id)

    def delete_all_logged_sessions(self) -> int:
        return SessionLogger.delete_all_sessions(SESSIONS_DIR)

    def get_sessions_dir(self) -> str:
        return str(SESSIONS_DIR)

    def open_sessions_folder(self) -> bool:
        """Pop up the platform file browser at the sessions directory.
        Returns True on success. Defensive: never raises."""
        path = str(SESSIONS_DIR)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # type: ignore[attr-defined]
                return True
            if sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", path])
                return True
            import subprocess
            subprocess.Popen(["xdg-open", path])
            return True
        except Exception as e:
            self.log_message(f"Session folder open failed ({path}): {e}")
            return False

    # ------------------------------------------------------------------
    # Public API — settings
    # ------------------------------------------------------------------

    def get_session_settings(self) -> Dict[str, Any]:
        return self._session_settings.snapshot()

    def set_session_settings(self, enabled: Optional[bool] = None,
                             auto_start: Optional[bool] = None,
                             retention: Optional[int] = None) -> None:
        """Update one or more fields. Passing None for a field leaves
        it untouched. Cheap — the settings manager persists each
        write so the UI doesn't need a separate save call."""
        if enabled is not None:
            self._session_settings.set_enabled(bool(enabled))
        if auto_start is not None:
            self._session_settings.set_auto_start(bool(auto_start))
        if retention is not None:
            self._session_settings.set_retention(int(retention))

    # ------------------------------------------------------------------
    # Routing-thread adapters (private)
    # ------------------------------------------------------------------

    def _session_on_motor(self, device_name: str, motor_idx: int,
                          intermediates: Dict[str, Any]) -> None:
        """Adapter for motor_router.set_session_broadcast. Translates
        wall-clock `t_unix` into relative ms and forwards to
        logger.log_motor. Runs on the routing thread (UI thread)."""
        if not self.is_session_logging_active():
            return
        t_unix = float(intermediates.get("t_unix", 0.0))
        started = self._session_started_at_unix or t_unix
        t_ms = (t_unix - started) * 1000.0
        try:
            self._session_logger.log_motor(
                t_ms, device_name, motor_idx,
                intermediates.get("d_raw",    0.0),
                intermediates.get("s_raw",    0.0),
                intermediates.get("d_shaped", 0.0),
                intermediates.get("s_shaped", 0.0),
                intermediates.get("mixed",    0.0),
                intermediates.get("out",      0.0),
            )
        except Exception:
            # Hot-path safety: never let a logger glitch break routing.
            pass

    def _session_sample_tick(self) -> None:
        """Called from routing_tick once per tick while a session is
        recording. Pulls the current OGB-param snapshot and the
        bHaptics dot snapshot and pushes them through the logger.

        Motor events are pushed by the broadcast callback in
        `_session_on_motor`; this method handles the two streams
        that aren't naturally per-motor."""
        if not self.is_session_logging_active():
            return
        if self._session_started_at_unix is None:
            return
        import time as _time
        t_ms = (_time.time() - self._session_started_at_unix) * 1000.0

        # ---- OGB stream ----
        try:
            params = store.get_all_parameters() or {}
        except Exception:
            params = {}
        if params:
            ogb_only = {
                k: v for k, v in params.items() if k.startswith(_OGB_PREFIX)
            }
            if ogb_only:
                try:
                    self._session_logger.log_ogb(t_ms, ogb_only)
                except Exception:
                    pass

        # ---- bHaptics stream ----
        try:
            if hasattr(self, "bhaptics_router") and self.bhaptics_router is not None:
                snap = self.bhaptics_router.get_snapshot()
            else:
                snap = None
        except Exception:
            snap = None
        if snap:
            # Dedup: build a sortable signature out of the snapshot and
            # skip when it matches the last logged one. Cheap (one
            # tuple build, one equality compare); guarantees we don't
            # spam duplicate events when the bHaptics router is
            # idling between updates.
            sig = tuple(sorted(
                (str(pos), tuple(int(v) for v in (dots or [])))
                for pos, dots in snap.items()
            ))
            if sig != self._session_last_bhaptics_sig:
                self._session_last_bhaptics_sig = sig
                try:
                    self._session_logger.log_bhaptics(t_ms, snap)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Private metadata builder
    # ------------------------------------------------------------------

    def _session_build_metadata(self) -> Dict[str, Any]:
        """Assemble the header dict from whatever facades exist on the
        controller. Every field is defensive — missing data turns into
        a null or an empty list rather than a crash."""
        meta: Dict[str, Any] = {}

        # Active mode (the "profile" key name is kept so existing session
        # files and their readers stay parseable).
        try:
            info = self.mode_manager.get_active_profile_info()
            meta["profile"] = info.get("name", "") or ""
        except Exception:
            meta["profile"] = ""

        # Avatar id (no name available without OSCQuery lookup; leave null)
        try:
            meta["avatar_id"] = self.mode_manager.current_avatar_id or None
        except Exception:
            meta["avatar_id"] = None

        # Router rate from app settings
        try:
            hz = int(self.get_app_setting("router_poll_rate_hz", 90))
        except Exception:
            hz = 90
        meta["router_hz"] = max(10, min(240, hz))

        # Connected toys (name + motor_count)
        toys: List[Dict[str, Any]] = []
        try:
            if self.haptic_engine and self.haptic_engine.is_connected:
                counts = self.haptic_engine.get_motor_count_map() or {}
                for name in self.haptic_engine.list_connected_device_names() or []:
                    toys.append({
                        "name":        name,
                        "motor_count": int(counts.get(name, 0)),
                    })
        except Exception:
            pass
        meta["toys"] = toys

        # bHaptics detected device positions on the current avatar.
        # Use the router's per-position table — the live debug grid
        # uses the same source.
        bhaptics_positions: List[str] = []
        try:
            from bhaptics_router import detected_positions
            params = store.get_all_parameters() or {}
            bhaptics_positions = sorted(detected_positions(params))
        except Exception:
            pass
        meta["bhaptics_devices"] = bhaptics_positions

        return meta
