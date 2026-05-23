"""Session-logger UI panel.

Mixin: lives behind a tab in the Settings view. Exposes the session
logger's facade methods (enable / auto-start / retention / start /
stop / list / delete / open-folder) to the user."""

import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

from constants import BTN_HEIGHT_SMALL

from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import (
    Card as _Card,
    ToggleSwitch,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


class SessionsMixin:
    """Sessions tab inside the Settings view. Controller methods used:
    `is_session_logging_active`, `get_session_logging_status`,
    `start_session_logging`, `stop_session_logging`, `set_session_settings`,
    `list_logged_sessions`, `delete_logged_session`,
    `delete_all_logged_sessions`, `open_sessions_folder`."""

    # Re-entrancy guard so programmatic widget updates (refresh tick
    # resyncing toggles) don't echo back through their valueChanged
    # signals and re-trigger a controller call.
    _is_updating_sessions = False

    # Tracks the session-id set we last rendered. Lets the refresh
    # tick skip the expensive rebuild when nothing has changed.
    _sessions_last_ids: tuple = ()

    def _build_sessions_panel(self, parent_layout: QVBoxLayout) -> None:
        parent_layout.addWidget(self._muted_label(
            "Record VR sessions to disk as line-delimited JSON for later "
            "analysis. Each file captures every router intermediate per "
            "motor, OGB SPS inputs (change-diffed), and bHaptics dot "
            "outputs — see SESSION_LOGGING.md for the on-disk schema."
        ))

        # ---- Status card ----
        status_card = _Card()
        slay = _vbox(14, 6)
        status_card.setLayout(slay)
        sh = QLabel("Status")
        sh.setObjectName("sectionTitle")
        slay.addWidget(sh)

        self.sessions_state_label = QLabel("Idle")
        f = self.sessions_state_label.font(); f.setBold(True); f.setPointSize(12)
        self.sessions_state_label.setFont(f)
        slay.addWidget(self.sessions_state_label)

        self.sessions_current_label = QLabel("No active session")
        self.sessions_current_label.setProperty("role", "muted")
        slay.addWidget(self.sessions_current_label)

        self.sessions_stats_label = QLabel("")
        self.sessions_stats_label.setProperty("role", "muted")
        slay.addWidget(self.sessions_stats_label)

        btn_row = _hbox(0, 8)
        self.sessions_start_btn = QPushButton("Start")
        self.sessions_start_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.sessions_start_btn.clicked.connect(self._on_sessions_start)
        btn_row.addWidget(self.sessions_start_btn)

        self.sessions_stop_btn = QPushButton("Stop")
        self.sessions_stop_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self.sessions_stop_btn.clicked.connect(self._on_sessions_stop)
        btn_row.addWidget(self.sessions_stop_btn)

        btn_row.addStretch(1)
        slay.addLayout(btn_row)
        parent_layout.addWidget(status_card)

        # ---- Preferences card ----
        prefs_card = _Card()
        play = _vbox(14, 6)
        prefs_card.setLayout(play)
        ph = QLabel("Preferences")
        ph.setObjectName("sectionTitle")
        play.addWidget(ph)

        self.sessions_enabled_check = ToggleSwitch("Enable session logging")
        self.sessions_enabled_check.setToolTip(
            "Master switch. When off, the Start button is disabled and no "
            "session will record. Existing files are left on disk."
        )
        self.sessions_enabled_check.toggled.connect(
            lambda v: self._on_sessions_pref_changed(enabled=bool(v))
        )
        play.addWidget(self.sessions_enabled_check)

        self.sessions_autostart_check = ToggleSwitch(
            "Auto-start a session on app launch"
        )
        self.sessions_autostart_check.setToolTip(
            "When both this and Enable are on, a new session file is "
            "created automatically every time the app starts."
        )
        self.sessions_autostart_check.toggled.connect(
            lambda v: self._on_sessions_pref_changed(auto_start=bool(v))
        )
        play.addWidget(self.sessions_autostart_check)

        ret_row = _hbox(0, 8)
        ret_row.addWidget(QLabel("Retention (files kept):"))
        self.sessions_retention_spin = QSpinBox()
        self.sessions_retention_spin.setRange(1, 1000)
        self.sessions_retention_spin.setSingleStep(1)
        self.sessions_retention_spin.setToolTip(
            "Maximum number of session files kept on disk. Pruning runs "
            "every time a new session starts; oldest files are deleted "
            "first by mtime."
        )
        self.sessions_retention_spin.valueChanged.connect(
            lambda v: self._on_sessions_pref_changed(retention=int(v))
        )
        ret_row.addWidget(self.sessions_retention_spin)
        ret_row.addStretch(1)
        play.addLayout(ret_row)

        self.sessions_dir_label = QLabel("")
        self.sessions_dir_label.setProperty("role", "muted")
        self.sessions_dir_label.setWordWrap(True)
        self.sessions_dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        play.addWidget(self.sessions_dir_label)

        parent_layout.addWidget(prefs_card)

        # ---- Saved sessions list ----
        list_card = _Card(dark_bg=True)
        llay = _vbox(10, 6)
        list_card.setLayout(llay)

        list_header = _hbox(0, 8)
        lh = QLabel("Saved sessions")
        lh.setObjectName("sectionTitle")
        list_header.addWidget(lh)
        list_header.addStretch(1)
        open_btn = QPushButton("Open folder")
        open_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        open_btn.setToolTip("Open the sessions folder in your file browser.")
        open_btn.clicked.connect(self._on_sessions_open_folder)
        list_header.addWidget(open_btn)
        del_all_btn = QPushButton("Delete all")
        del_all_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        del_all_btn.setToolTip("Delete every saved session file. Asks first.")
        del_all_btn.clicked.connect(self._on_sessions_delete_all)
        list_header.addWidget(del_all_btn)
        llay.addLayout(list_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(180)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        self.sessions_list_layout = _vbox(6, 6)
        inner.setLayout(self.sessions_list_layout)
        scroll.setWidget(inner)
        llay.addWidget(scroll, 1)

        parent_layout.addWidget(list_card, 1)

        # Initial render + 1 Hz tick that refreshes status + list when
        # something changes. The list rebuild is throttled by an id-set
        # equality check so unchanged renders are cheap.
        self._refresh_sessions_view(force_list_rebuild=True)
        self._sessions_refresh_timer = QTimer(self.window)
        self._sessions_refresh_timer.setInterval(1000)
        self._sessions_refresh_timer.timeout.connect(self._refresh_sessions_view)
        self._sessions_refresh_timer.start()

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def _refresh_sessions_view(self, force_list_rebuild: bool = False) -> None:
        if not hasattr(self, "sessions_state_label"):
            return
        try:
            status = self.controller.get_session_logging_status()
        except Exception:
            return
        self._is_updating_sessions = True
        try:
            self._apply_sessions_status(status)
            self._apply_sessions_list(force=force_list_rebuild)
        finally:
            self._is_updating_sessions = False

    def _apply_sessions_status(self, status: Dict[str, Any]) -> None:
        settings = status.get("settings") or {}
        active = status.get("active")
        sessions_dir = status.get("sessions_dir", "")

        # Preferences widgets — only set if value differs to avoid
        # spurious round-trips through the toggled/valueChanged handlers.
        en = bool(settings.get("enabled", False))
        if self.sessions_enabled_check.isChecked() != en:
            self.sessions_enabled_check.setChecked(en)
        au = bool(settings.get("auto_start", False))
        if self.sessions_autostart_check.isChecked() != au:
            self.sessions_autostart_check.setChecked(au)
        rt = int(settings.get("retention", 20))
        if self.sessions_retention_spin.value() != rt:
            self.sessions_retention_spin.setValue(rt)
        # Auto-start is only meaningful when the master toggle is on.
        # Grey it out (still readable) when the master is off so the
        # dependency is obvious.
        self.sessions_autostart_check.setEnabled(en)
        self.sessions_dir_label.setText(f"Saved to: {sessions_dir}")

        # Status section: state + current-session line + stats.
        if active:
            self.sessions_state_label.setText("Recording")
            self.sessions_state_label.setProperty("role", "success")
            self.sessions_current_label.setText(f"{active.get('id', '?')}")
            self.sessions_stats_label.setText(
                f"Duration {_fmt_duration(active.get('duration_s', 0.0))}  •  "
                f"{int(active.get('event_count', 0)):,} events  •  "
                f"{_fmt_bytes(int(active.get('file_size_bytes', 0)))} on disk"
                + (
                    f"  •  {int(active.get('dropped_count', 0)):,} dropped"
                    if int(active.get("dropped_count", 0)) > 0 else ""
                )
            )
            self.sessions_start_btn.setEnabled(False)
            self.sessions_stop_btn.setEnabled(True)
        else:
            self.sessions_state_label.setText("Idle")
            self.sessions_state_label.setProperty("role", None)
            self.sessions_current_label.setText("No active session")
            self.sessions_stats_label.setText("")
            # Start button is gated by the master enable toggle so an
            # accidental click while disabled doesn't surface an error.
            self.sessions_start_btn.setEnabled(en)
            self.sessions_stop_btn.setEnabled(False)
        self.sessions_state_label.style().unpolish(self.sessions_state_label)
        self.sessions_state_label.style().polish(self.sessions_state_label)

    def _apply_sessions_list(self, force: bool = False) -> None:
        try:
            sessions = self.controller.list_logged_sessions() or []
        except Exception:
            sessions = []
        # The currently-recording session's file lives on disk from the
        # moment of start(), so list_sessions() picks it up. But it has
        # no footer yet (duration/event-count read as 0) and its Delete
        # button would nuke the in-flight file. Exclude it here — the
        # Status card above already shows the live numbers, so nothing
        # is hidden, and the user can't shoot themselves in the foot.
        try:
            status = self.controller.get_session_logging_status()
            active = status.get("active") if status else None
        except Exception:
            active = None
        active_id = (active or {}).get("id") if active else None
        if active_id:
            sessions = [s for s in sessions if s.get("id") != active_id]
        ids = tuple(s.get("id", "") for s in sessions)
        if not force and ids == self._sessions_last_ids:
            # The list shape hasn't changed; there's nothing live to
            # refresh because the active session was filtered out
            # above. Cheap early-return.
            return
        self._sessions_last_ids = ids
        # Tear down + rebuild.
        while self.sessions_list_layout.count():
            item = self.sessions_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not sessions:
            empty_msg = (
                "Saved sessions appear here once recording stops. The "
                "currently-recording session is shown above."
                if active_id else
                "No saved sessions yet. Start a session above to record one."
            )
            self.sessions_list_layout.addWidget(self._muted_label(empty_msg))
            return
        for s in sessions:
            self.sessions_list_layout.addWidget(self._build_session_row(s))
        self.sessions_list_layout.addStretch(1)

    def _build_session_row(self, s: Dict[str, Any]) -> QFrame:
        row = QFrame()
        row.setObjectName("sessionRow")
        rlay = _hbox(8, 8)
        row.setLayout(rlay)

        name = QLabel(s.get("id", "?"))
        nf = name.font(); nf.setFamily("Consolas"); name.setFont(nf)
        name.setMinimumWidth(220)
        name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rlay.addWidget(name)

        started = QLabel(_fmt_when(s.get("started_at_unix")))
        started.setProperty("role", "muted")
        started.setMinimumWidth(140)
        rlay.addWidget(started)

        duration = QLabel(_fmt_duration(s.get("duration_s", 0)))
        duration.setProperty("role", "muted")
        duration.setMinimumWidth(70)
        rlay.addWidget(duration)

        events = QLabel(f"{int(s.get('event_count', 0)):,} events")
        events.setProperty("role", "muted")
        events.setMinimumWidth(110)
        rlay.addWidget(events)

        size = QLabel(_fmt_bytes(int(s.get("size_bytes", 0))))
        size.setProperty("role", "muted")
        size.setMinimumWidth(80)
        rlay.addWidget(size)

        rlay.addStretch(1)

        del_btn = QPushButton("Delete")
        del_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        sid = s.get("id", "")
        del_btn.clicked.connect(
            lambda _=False, i=sid: self._on_sessions_delete_one(i)
        )
        rlay.addWidget(del_btn)
        return row

    # ----------------------------------------------------------
    # Handlers
    # ----------------------------------------------------------

    def _on_sessions_pref_changed(self, enabled: Optional[bool] = None,
                                  auto_start: Optional[bool] = None,
                                  retention: Optional[int] = None) -> None:
        if self._is_updating_sessions:
            return
        try:
            self.controller.set_session_settings(
                enabled=enabled, auto_start=auto_start, retention=retention,
            )
        except Exception as e:
            self.log_message(f"Session settings save failed: {e}")
            return
        # Immediately reflect the new master-enable state in button
        # enabledness so the user sees the change without waiting on
        # the 1 Hz timer.
        self._refresh_sessions_view()

    def _on_sessions_start(self) -> None:
        try:
            sid = self.controller.start_session_logging()
        except Exception as e:
            self.log_message(f"Session start failed: {e}")
            QMessageBox.warning(self.window, "Session logger",
                                f"Could not start session: {e}")
            return
        if sid:
            self.log_message(f"Session started: {sid}")
        self._refresh_sessions_view(force_list_rebuild=True)

    def _on_sessions_stop(self) -> None:
        try:
            self.controller.stop_session_logging()
        except Exception as e:
            self.log_message(f"Session stop failed: {e}")
        self._refresh_sessions_view(force_list_rebuild=True)

    def _on_sessions_delete_one(self, session_id: str) -> None:
        if not session_id:
            return
        confirm = QMessageBox.question(
            self.window, "Delete session",
            f"Delete '{session_id}.jsonl' permanently?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.controller.delete_logged_session(session_id)
        except Exception as e:
            self.log_message(f"Session delete failed ({session_id}): {e}")
            return
        self._refresh_sessions_view(force_list_rebuild=True)

    def _on_sessions_delete_all(self) -> None:
        confirm = QMessageBox.question(
            self.window, "Delete all sessions",
            "Delete every saved session file? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            n = int(self.controller.delete_all_logged_sessions() or 0)
        except Exception as e:
            self.log_message(f"Session delete-all failed: {e}")
            return
        self.log_message(f"Deleted {n} session file(s).")
        self._refresh_sessions_view(force_list_rebuild=True)

    def _on_sessions_open_folder(self) -> None:
        try:
            ok = bool(self.controller.open_sessions_folder())
        except Exception as e:
            self.log_message(f"Open sessions folder failed: {e}")
            ok = False
        if not ok:
            QMessageBox.information(
                self.window, "Sessions folder",
                "Could not open the sessions folder. Check the path in "
                "the Saved to: line above."
            )


# ----------------------------------------------------------
# Formatting helpers (module-level — pure, testable)
# ----------------------------------------------------------

def _fmt_bytes(n: int) -> str:
    n = max(0, int(n))
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _fmt_duration(seconds: float) -> str:
    s = max(0, int(round(float(seconds or 0))))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}:{s:02d}"
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _fmt_when(unix_ts: Optional[float]) -> str:
    if not unix_ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(unix_ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"
