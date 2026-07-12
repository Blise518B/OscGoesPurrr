"""Statistics view — lifetime usage totals + per-session summaries.

Read-only dashboard over the controller's `get_stats_snapshot()`
facade: total active time / thrust count / session count, per-toy
on-time and per-zone contact time (lifetime and this-session side by
side), plus the last 20 finalized sessions. The only mutating control
is the Reset button (`controller.reset_stats()`), double-confirmed.

Refresh follows the hidden-pages rule: a 1 s QTimer whose handler
early-outs while the page isn't visible (same gate as overview.py),
with a one-shot arrival refresh registered in select_view.
"""

from datetime import datetime
from typing import Any, Dict, List, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from constants import BTN_HEIGHT_SMALL

from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import Card as _Card


# Zone-type prefix (the stats zone_key is "<type>/<name>") -> the
# user-facing noun. OGB calls them Orf/Pen; humans say socket/plug.
_ZONE_TYPE_LABELS = {
    "Orf": "socket",
    "Pen": "plug",
    "Touch": "touch",
}

_REFRESH_MS = 1000


class StatisticsMixin:
    """Statistics sidebar view. Controller methods used:
    `get_stats_snapshot`, `reset_stats`."""

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_statistics_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Statistics")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        parent_layout.addWidget(self._muted_label(
            "How much your gear actually gets used — lifetime totals "
            "plus a summary of every app run that saw activity. Sampled "
            "once per second; nothing here touches the haptic path."
        ))

        # ---- Lifetime card ----
        life_card = _Card()
        llay = _vbox(14, 8)
        life_card.setLayout(llay)

        head_row = _hbox(0, 8)
        lh = QLabel("Lifetime")
        lh.setObjectName("sectionTitle")
        head_row.addWidget(lh)
        head_row.addWidget(self._make_help_badge(
            "Lifetime statistics",
            "What counts: a toy is <b>on</b> while any of its motors is "
            "driven above zero; a zone is <b>in contact</b> while any of "
            "its OGB signals reads above zero; <b>active time</b> ticks "
            "while either is true. One full in-out stroke = one "
            "<b>thrust</b> (counted per motor, so two motors riding the "
            "same contact both count it). Everything is sampled once per "
            "second, so sub-second blips can round away. Sessions are "
            "app runs that saw any activity."
        ))
        head_row.addStretch(1)
        reset_btn = QPushButton("Reset")
        reset_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        reset_btn.setToolTip("Zero every lifetime statistic. Asks first.")
        reset_btn.clicked.connect(self._on_stats_reset)
        head_row.addWidget(reset_btn)
        llay.addLayout(head_row)

        # Stat tiles: three headline numbers.
        tiles_row = _hbox(0, 28)
        self._stats_active_value = self._stats_add_tile(
            tiles_row, "Total active time")
        self._stats_thrusts_value = self._stats_add_tile(
            tiles_row, "Thrusts")
        self._stats_sessions_value = self._stats_add_tile(
            tiles_row, "Sessions")
        tiles_row.addStretch(1)
        llay.addLayout(tiles_row)

        # This-session line under the headline numbers.
        self._stats_session_label = QLabel("")
        self._stats_session_label.setProperty("muted", "true")
        self._stats_session_label.setWordWrap(True)
        self._repolish(self._stats_session_label)
        llay.addWidget(self._stats_session_label)

        # Per-toy and per-zone tables (name / lifetime / this session).
        self._stats_toys_table = self._stats_make_table(llay, "Toys")
        self._stats_zones_table = self._stats_make_table(llay, "Zones")

        parent_layout.addWidget(life_card)

        # ---- Recent sessions card ----
        recent_card = _Card(dark_bg=True)
        rlay = _vbox(10, 6)
        recent_card.setLayout(rlay)
        rh = QLabel("Recent sessions")
        rh.setObjectName("sectionTitle")
        rlay.addWidget(rh)
        self._stats_recent_layout = _vbox(0, 4)
        rhost = QWidget()
        rhost.setLayout(self._stats_recent_layout)
        rlay.addWidget(rhost)
        parent_layout.addWidget(recent_card)

        parent_layout.addStretch(1)

        # Rebuild-throttle signatures (tables rebuild only when their
        # key sets change; recent list only when its rows change).
        self._stats_recent_sig: tuple = None

        # Initial render + the 1 s visibility-gated refresh timer.
        self._refresh_statistics_view()
        if getattr(self, "_stats_refresh_timer", None) is None:
            t = QTimer(self.window)
            t.setInterval(_REFRESH_MS)
            t.timeout.connect(self._stats_tick)
            t.start()
            self._stats_refresh_timer = t

    def _stats_add_tile(self, row_layout, caption: str) -> QLabel:
        """One headline stat tile: big bold value over a muted caption.
        Returns the value label for the refresh path to update."""
        box = QWidget()
        lay = _vbox(0, 2)
        box.setLayout(lay)
        value = QLabel("—")
        vf = value.font(); vf.setBold(True)
        vf.setPointSize(max(vf.pointSize() + 4, 14))
        value.setFont(vf)
        lay.addWidget(value)
        cap = QLabel(caption)
        cap.setProperty("muted", "true")
        self._repolish(cap)
        lay.addWidget(cap)
        row_layout.addWidget(box)
        return value

    def _stats_make_table(self, parent_lay, header_text: str) -> Dict[str, Any]:
        """A small name / lifetime / this-session grid with in-place
        value updates (rows only rebuild when the key set changes, so
        the 1 Hz tick doesn't churn widgets)."""
        header = QLabel(header_text)
        hf = header.font(); hf.setBold(True)
        header.setFont(hf)
        parent_lay.addWidget(header)
        host = QWidget()
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(3, 1)
        host.setLayout(grid)
        parent_lay.addWidget(host)
        # keys starts as None (not the empty tuple) so the FIRST fill
        # always takes the rebuild branch — otherwise a fresh install's
        # empty table would skip it and never show the empty-state hint.
        return {"host": host, "grid": grid, "rows": {}, "keys": None}

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def _stats_tick(self) -> None:
        """Timer slot — early-outs while the page is hidden (same gate
        as the Overview refresh timer); select_view refreshes once on
        arrival so the page never shows stale data."""
        view = self.views.get("Statistics") if hasattr(self, "views") else None
        if view is not None and not view.isVisible():
            return
        self._refresh_statistics_view()

    def _refresh_statistics_view(self) -> None:
        if not hasattr(self, "_stats_active_value"):
            return
        try:
            snap = self.controller.get_stats_snapshot() or {}
        except Exception:
            return
        lifetime = snap.get("lifetime") or {}
        session = snap.get("session") or {}
        recent = snap.get("recent_sessions") or []

        # Headline tiles.
        self._stats_active_value.setText(
            _fmt_dur(lifetime.get("active_s", 0.0)))
        self._stats_thrusts_value.setText(
            f"{int(lifetime.get('thrusts', 0)):,}")
        self._stats_sessions_value.setText(
            f"{int(lifetime.get('sessions', 0)):,}")

        # This-session line.
        started = session.get("started_ts") or 0.0
        started_txt = _fmt_when(started) if started else "—"
        self._stats_session_label.setText(
            f"This session: {_fmt_dur(session.get('active_s', 0.0))} active"
            f"  •  {int(session.get('thrusts', 0)):,} thrusts"
            f"  •  started {started_txt}"
        )

        # Toys table: every toy seen in lifetime OR this session.
        session_toys = session.get("toys") or {}
        lifetime_toys = lifetime.get("toys") or {}
        toy_rows: List[Tuple[str, str, float, float]] = []
        for name in sorted(set(lifetime_toys) | set(session_toys),
                           key=str.lower):
            toy_rows.append((
                name, name,
                float((lifetime_toys.get(name) or {}).get("on_s", 0.0)),
                float((session_toys.get(name) or {}).get("on_s", 0.0)),
            ))
        self._stats_fill_table(self._stats_toys_table, toy_rows,
                               "No toy on-time recorded yet.")

        # Zones table: zone_key is "<type>/<name>" — show the name with
        # its socket/plug/touch noun.
        session_zones = session.get("zones") or {}
        lifetime_zones = lifetime.get("zones") or {}
        zone_rows: List[Tuple[str, str, float, float]] = []
        for key in sorted(set(lifetime_zones) | set(session_zones),
                          key=str.lower):
            entry = lifetime_zones.get(key) or session_zones.get(key) or {}
            ztype = str(entry.get("type", "")) or key.split("/", 1)[0]
            zname = key.split("/", 1)[1] if "/" in key else key
            noun = _ZONE_TYPE_LABELS.get(ztype, ztype or "?")
            zone_rows.append((
                key, f"{zname} ({noun})",
                float((lifetime_zones.get(key) or {}).get("contact_s", 0.0)),
                float((session_zones.get(key) or {}).get("contact_s", 0.0)),
            ))
        self._stats_fill_table(self._stats_zones_table, zone_rows,
                               "No zone contact recorded yet.")

        # Recent sessions list.
        self._stats_fill_recent(recent)

    def _stats_fill_table(self, refs: Dict[str, Any],
                          rows: List[Tuple[str, str, float, float]],
                          empty_text: str) -> None:
        keys = tuple(r[0] for r in rows)
        if keys != refs["keys"]:
            # Key set changed — rebuild the grid.
            self._stats_clear_grid(refs["grid"])
            refs["rows"] = {}
            refs["keys"] = keys
            if not rows:
                empty = self._muted_label(empty_text)
                refs["grid"].addWidget(empty, 0, 0, 1, 3)
                return
            for col, text in enumerate(("", "Lifetime", "This session")):
                h = QLabel(text)
                h.setProperty("muted", "true")
                self._repolish(h)
                refs["grid"].addWidget(h, 0, col)
            for i, (key, name_text, life_s, sess_s) in enumerate(rows):
                name = QLabel(name_text)
                name.setToolTip(name_text)
                life = QLabel(_fmt_dur(life_s))
                sess = QLabel(_fmt_dur(sess_s))
                sess.setProperty("muted", "true")
                self._repolish(sess)
                refs["grid"].addWidget(name, i + 1, 0)
                refs["grid"].addWidget(life, i + 1, 1)
                refs["grid"].addWidget(sess, i + 1, 2)
                refs["rows"][key] = (life, sess)
            return
        # Same rows — update the duration labels in place.
        for key, _name_text, life_s, sess_s in rows:
            pair = refs["rows"].get(key)
            if pair is None:
                continue
            pair[0].setText(_fmt_dur(life_s))
            pair[1].setText(_fmt_dur(sess_s))

    def _stats_fill_recent(self, recent: List[Dict[str, Any]]) -> None:
        sig = tuple(
            (round(float(s.get("started_ts", 0.0) or 0.0)),
             round(float(s.get("duration_s", 0.0) or 0.0)),
             round(float(s.get("active_s", 0.0) or 0.0)),
             int(s.get("thrusts", 0) or 0))
            for s in recent
        )
        if sig == self._stats_recent_sig:
            return
        self._stats_recent_sig = sig
        lay = self._stats_recent_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        if not recent:
            lay.addWidget(self._muted_label(
                "Finished sessions land here — every app run that saw "
                "activity, newest first (last 20 kept)."
            ))
            return
        for s in recent:
            lay.addWidget(self._stats_build_recent_row(s))

    def _stats_build_recent_row(self, s: Dict[str, Any]) -> QFrame:
        row = QFrame()
        row.setObjectName("sessionRow")
        rlay = _hbox(8, 8)
        row.setLayout(rlay)

        when = QLabel(_fmt_when(s.get("started_ts")))
        when.setMinimumWidth(140)
        rlay.addWidget(when)

        duration = QLabel(_fmt_dur(s.get("duration_s", 0.0)))
        duration.setProperty("muted", "true")
        duration.setMinimumWidth(80)
        duration.setToolTip("Session duration (app run length)")
        self._repolish(duration)
        rlay.addWidget(duration)

        active = QLabel(f"{_fmt_dur(s.get('active_s', 0.0))} active")
        active.setProperty("muted", "true")
        active.setMinimumWidth(100)
        active.setToolTip("Time with a toy driven or a zone in contact")
        self._repolish(active)
        rlay.addWidget(active)

        thrusts = QLabel(f"{int(s.get('thrusts', 0) or 0):,} thrusts")
        thrusts.setProperty("muted", "true")
        self._repolish(thrusts)
        rlay.addWidget(thrusts)

        rlay.addStretch(1)
        return row

    def _stats_clear_grid(self, grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                # Hide before detaching so the orphan never flashes as
                # a top-level window (same pattern as overview.py).
                w.hide()
                w.setParent(None)
                w.deleteLater()

    # ----------------------------------------------------------
    # Handlers
    # ----------------------------------------------------------

    def _on_stats_reset(self) -> None:
        confirm = QMessageBox.question(
            self.window, "Reset statistics",
            "Reset ALL lifetime statistics? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        try:
            self.controller.reset_stats()
        except Exception as e:
            self.log_message(f"Statistics reset failed: {e}")
            return
        self.log_message("Lifetime statistics reset.")
        self._refresh_statistics_view()


# ----------------------------------------------------------
# Formatting helpers (module-level — pure, testable)
# ----------------------------------------------------------

def _fmt_dur(seconds: Any) -> str:
    """Compact human duration: "58s", "12m 03s", "3h 24m", "2d 5h"."""
    try:
        s = max(0, int(round(float(seconds or 0))))
    except (TypeError, ValueError):
        s = 0
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def _fmt_when(unix_ts: Any) -> str:
    if not unix_ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(unix_ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"
