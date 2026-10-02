"""Statistics view — sessions, lifetime totals, and when you play.

Read-only dashboard over the controller's stats facade, top to bottom:

* **Sessions** — every recorded session, newest first (the running one
  on top while it has activity), each with a small activity graph. A
  click opens that session's page: an intensity lane per toy, thrusts
  per minute, a contact lane per zone, and a short analysis.
* **Lifetime** — the headline totals, a row of fun facts, and per-toy /
  per-zone time (lifetime and this session side by side).
* **When you play** — active time by weekday x hour over a chosen span.
* **Month** — a calendar of active time per day with the month's totals.

The only mutating control is the Reset button (`controller.reset_stats()`),
double-confirmed.

Refresh follows the hidden-pages rule: a 1 s QTimer whose handler
early-outs while the page isn't visible (same gate as overview.py), with
a one-shot arrival refresh registered in select_view. The session list
refreshes every tick; the charts and fun facts every few ticks.
"""

from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from constants import BTN_HEIGHT_SMALL

from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout
from ui.stats_charts import (
    MonthCalendar, SessionTimeline, SpanStrip, SpanTimeline, Sparkline,
    WEEKDAYS_LONG, WeekHourChart,
    fmt_clock, fmt_day, fmt_dur, fmt_short, toy_color, zone_label,
)
from ui.widgets import Card as _Card


_REFRESH_MS = 1000

# The charts and fun facts read the whole history; once every few ticks
# is plenty for numbers that move by the minute.
_SLOW_EVERY_TICKS = 5

# Sessions shown before "Show more".
_LIST_PAGE = 20

# "When you play" spans: (button label, days or None for everything,
# the phrase tooltips use).
_SPANS = (
    ("4 weeks", 28, "over the last 4 weeks"),
    ("3 months", 91, "over the last 3 months"),
    ("All time", None, "all time"),
)
_DEFAULT_SPAN = 1

# Backward-compatible name: other code and older tests import it from here.
_fmt_dur = fmt_dur


def _fmt_when(unix_ts: Any) -> str:
    if not unix_ts:
        return "—"
    try:
        return datetime.fromtimestamp(float(unix_ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "—"


class _SessionRow(QFrame):
    """One clickable session in the list."""

    def __init__(self, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.setObjectName("statsSessionRow")
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        lay = _hbox(8, 10)
        lay.setContentsMargins(8, 4, 8, 4)
        self.setLayout(lay)
        # Date and the "recording" badge share one fixed-width cell, so
        # the running session's columns line up with the rest.
        when_cell = QWidget()
        when_cell.setFixedWidth(206)
        when_lay = _hbox(0, 6)
        when_cell.setLayout(when_lay)
        self.when = QLabel()
        self.badge = QLabel("recording")
        self.badge.setProperty("role", "pill")
        self.badge.setProperty("tone", "run")
        when_lay.addWidget(self.when)
        when_lay.addWidget(self.badge)
        when_lay.addStretch(1)
        self.duration = QLabel()
        self.active = QLabel()
        self.thrusts = QLabel()
        for lbl, width in ((self.duration, 64), (self.active, 86),
                           (self.thrusts, 104)):
            lbl.setProperty("muted", "true")
            lbl.setMinimumWidth(width)
        self.spark = Sparkline()
        self.strip = SpanStrip()
        self.no_spark = QLabel("totals only")
        self.no_spark.setProperty("hint", "true")
        chevron = QLabel("›")
        chevron.setProperty("muted", "true")
        lay.addWidget(when_cell)
        lay.addWidget(self.duration)
        lay.addWidget(self.active)
        lay.addWidget(self.thrusts)
        lay.addWidget(self.spark, 1)
        lay.addWidget(self.strip, 1)
        lay.addWidget(self.no_spark, 1)
        lay.addWidget(chevron)
        for w in (when_cell, self.when, self.badge, self.duration,
                  self.active, self.thrusts, self.no_spark, chevron):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    def fill(self, row: Dict[str, Any]) -> None:
        live = row.get("kind") == "live"
        if live:
            self.when.setText(f"Now, since {fmt_clock(row.get('started_ts'))}")
        else:
            self.when.setText(f"{fmt_day(row.get('started_ts'))}  "
                              f"{fmt_clock(row.get('started_ts'))}")
        self.badge.setVisible(live)
        self.duration.setText(fmt_short(row.get("duration_s", 0.0)))
        self.active.setText(f"{fmt_short(row.get('active_s', 0.0))} active")
        self.thrusts.setText(f"{int(row.get('thrusts', 0) or 0):,} thrusts")
        has_spark = row.get("spark") is not None
        connected = None if has_spark else row.get("connected")
        self.spark.setVisible(has_spark)
        self.strip.setVisible(bool(connected))
        self.no_spark.setVisible(not has_spark and not connected)
        if has_spark:
            self.spark.set_values(row.get("spark"))
        elif connected:
            self.strip.set_spans(connected, row.get("started_ts", 0.0),
                                 row.get("duration_s", 0.0))
        if row.get("recovered"):
            self.setToolTip("The app was closed without shutting down "
                            "(killed or crashed). This session was rebuilt "
                            "from its last save, so its last minute may be "
                            "missing.")
        elif connected:
            self.setToolTip("Recorded before session timelines existed, so "
                            "only its totals are known. The bars show when a "
                            "toy was connected, from the app's log.")
        elif not has_spark:
            self.setToolTip("Recorded before session timelines existed, or "
                            "by the full edition — totals only.")
        else:
            self.setToolTip("")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._on_click()
        super().mouseReleaseEvent(event)


class _Tile(QFrame):
    """Caption over a bold value over a dim note."""

    def __init__(self, caption: str = "", big: bool = False) -> None:
        super().__init__()
        self.setObjectName("statsTile")
        lay = _vbox(0, 1)
        lay.setContentsMargins(10, 6, 10, 7)
        self.setLayout(lay)
        self.caption = QLabel(caption)
        self.caption.setProperty("muted", "true")
        self.value = QLabel("—")
        vf = self.value.font()
        vf.setBold(True)
        vf.setPixelSize(20 if big else 16)
        self.value.setFont(vf)
        self.note = QLabel("")
        self.note.setProperty("hint", "true")
        self.note.setWordWrap(True)
        lay.addWidget(self.caption)
        lay.addWidget(self.value)
        lay.addWidget(self.note)
        lay.addStretch(1)
        self.note.setVisible(False)

    def set(self, value: str, note: str = "", caption: Optional[str] = None) -> None:
        if caption is not None:
            self.caption.setText(caption)
        self.value.setText(value)
        self.note.setText(note)
        self.note.setVisible(bool(note))


class StatisticsMixin:
    """Statistics sidebar view. Controller methods used:
    `get_stats_snapshot`, `get_stats_sessions`, `get_stats_session_detail`,
    `get_stats_patterns`, `get_stats_month`, `get_stats_fun_facts`,
    `reset_stats`."""

    # ----------------------------------------------------------
    # View construction
    # ----------------------------------------------------------

    def _build_statistics_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Statistics")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # Two pages in one: the overview, and one session's page. Only
        # one is visible; a hidden widget takes no room in the layout.
        self._stats_overview = QWidget()
        ov = _vbox(0, 12)
        self._stats_overview.setLayout(ov)
        self._stats_detail = QWidget()
        dv = _vbox(0, 12)
        self._stats_detail.setLayout(dv)
        self._stats_detail.setVisible(False)
        parent_layout.addWidget(self._stats_overview)
        parent_layout.addWidget(self._stats_detail)
        parent_layout.addStretch(1)

        ov.addWidget(self._muted_label(
            "How much your gear actually gets used, and when. Sampled once "
            "per second; nothing here touches the haptic path."
        ))
        self._stats_build_sessions_card(ov)
        self._stats_build_lifetime_card(ov)
        self._stats_build_patterns_card(ov)
        self._stats_build_month_card(ov)
        self._stats_build_detail_page(dv)

        self._stats_estimated_until = 0.0
        self._stats_detail_id: Optional[str] = None
        self._stats_detail_kind: Optional[str] = None
        self._stats_list_scroll = 0
        self._stats_tick_n = 0

        # Initial render + the 1 s visibility-gated refresh timer.
        self._refresh_statistics_view()
        if getattr(self, "_stats_refresh_timer", None) is None:
            t = QTimer(self.window)
            t.setInterval(_REFRESH_MS)
            t.timeout.connect(self._stats_tick)
            t.start()
            self._stats_refresh_timer = t

    def _stats_card(self, parent_lay, title_text: str,
                    dark: bool = False) -> Tuple[QVBoxLayout, Any]:
        """A card with its section-title bar; returns (body layout,
        header row) so callers can add trailing controls to the row."""
        card = _Card(dark_bg=dark)
        lay = _vbox(14, 8)
        card.setLayout(lay)
        head = _hbox(0, 8)
        bar = QLabel(title_text)
        bar.setObjectName("sectionTitle")
        head.addWidget(bar, 1)
        lay.addLayout(head)
        parent_lay.addWidget(card)
        return lay, head

    # ---- Sessions ------------------------------------------------------

    def _stats_build_sessions_card(self, parent_lay) -> None:
        lay, head = self._stats_card(parent_lay, "Sessions")
        self._explain(head,
            "Sessions",
            "Every app run that saw activity, newest first. The graph is "
            "how busy each part of it was. Click a session for its "
            "timeline: each toy's intensity, thrusts per minute, which "
            "zones were touched, and a short analysis.<br><br>With no toy "
            "running, stray contacts don't start a session: contact only "
            "counts once it adds up to 20 thrusts without a pause longer "
            "than 10 seconds, or to a minute of touching within three "
            "minutes. Strokes counted while nothing is touching you never "
            "count."
        )
        self._stats_rows: List[_SessionRow] = []
        self._stats_row_ids: List[str] = []
        self._stats_list_host = QWidget()
        self._stats_list_lay = _vbox(0, 2)
        self._stats_list_host.setLayout(self._stats_list_lay)
        lay.addWidget(self._stats_list_host)
        self._stats_list_empty = self._muted_label(
            "Sessions land here as soon as something happens: a toy "
            "running or a zone being touched.")
        lay.addWidget(self._stats_list_empty)
        more_row = _hbox(0, 8)
        self._stats_more_label = QLabel("")
        self._stats_more_label.setProperty("hint", "true")
        more_row.addWidget(self._stats_more_label, 1)
        self._stats_more_btn = QPushButton("Show more")
        self._stats_more_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._stats_more_btn.clicked.connect(self._on_stats_show_more)
        more_row.addWidget(self._stats_more_btn)
        lay.addLayout(more_row)
        self._stats_list_limit = _LIST_PAGE

    # ---- Lifetime ------------------------------------------------------

    def _stats_build_lifetime_card(self, parent_lay) -> None:
        lay, head = self._stats_card(parent_lay, "Lifetime")
        self._explain(head,
            "Lifetime statistics",
            "What counts: a toy is <b>on</b> while any of its motors is "
            "driven above zero; a zone is <b>in contact</b> while any of "
            "its OGB signals reads above zero; <b>active time</b> ticks "
            "while either is true. One full in-out stroke = one "
            "<b>thrust</b>. Everything is sampled once per second, so "
            "sub-second blips can round away. Sessions are app runs that "
            "saw any activity.<br><br>While no toy is running, contact "
            "is held back until it turns into a real scene: 20 thrusts "
            "with no pause longer than 10 seconds, or a minute of "
            "touching within three minutes (one long touch or many short "
            "ones), and a stroke only counts while something is touching "
            "you. Then the 30 seconds before it count as well, and it "
            "keeps counting until half an hour of quiet. Stray contacts "
            "and lone strokes never count."
        )
        reset_btn = QPushButton("Reset")
        reset_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        reset_btn.setToolTip("Zero every statistic, session and chart. "
                             "Asks first.")
        reset_btn.clicked.connect(self._on_stats_reset)
        head.addWidget(reset_btn)

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(8)
        tiles.setVerticalSpacing(8)
        self._stats_active_tile = _Tile("Total active time", big=True)
        self._stats_thrusts_tile = _Tile("Thrusts", big=True)
        self._stats_sessions_tile = _Tile("Sessions", big=True)
        for col, tile in enumerate((self._stats_active_tile,
                                    self._stats_thrusts_tile,
                                    self._stats_sessions_tile)):
            tiles.addWidget(tile, 0, col)
            tiles.setColumnStretch(col, 1)
        lay.addLayout(tiles)

        # This-session line under the headline numbers.
        self._stats_session_label = QLabel("")
        self._stats_session_label.setProperty("muted", "true")
        self._stats_session_label.setWordWrap(True)
        self._repolish(self._stats_session_label)
        lay.addWidget(self._stats_session_label)

        # Fun facts: whichever have enough data behind them.
        facts_head = QLabel("Fun facts")
        hf = facts_head.font()
        hf.setBold(True)
        facts_head.setFont(hf)
        lay.addWidget(facts_head)
        self._stats_facts_host = QWidget()
        self._stats_facts_grid = QGridLayout()
        self._stats_facts_grid.setContentsMargins(0, 0, 0, 0)
        self._stats_facts_grid.setHorizontalSpacing(8)
        self._stats_facts_grid.setVerticalSpacing(8)
        self._stats_facts_host.setLayout(self._stats_facts_grid)
        lay.addWidget(self._stats_facts_host)
        self._stats_facts_empty = self._muted_label(
            "Fun facts show up once there is a session or two to go on.")
        lay.addWidget(self._stats_facts_empty)
        self._stats_fact_tiles: Dict[str, _Tile] = {}
        self._stats_facts_sig: Optional[tuple] = None

        # Per-toy and per-zone tables (name / lifetime / this session).
        self._stats_toys_table = self._stats_make_table(lay, "Toys")
        self._stats_zones_table = self._stats_make_table(lay, "Zones")

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

    # ---- When you play -------------------------------------------------

    def _stats_build_patterns_card(self, parent_lay) -> None:
        lay, head = self._stats_card(parent_lay, "When you play")
        self._explain(head,
            "When you play",
            "Active time by weekday and hour of the day. The brighter the "
            "cell, the more happened in that hour. The bars below add up "
            "every day per hour; the bars on the right add up each "
            "weekday. Hover anything for the numbers."
        )
        self._stats_span = _DEFAULT_SPAN
        self._stats_span_btns: List[QPushButton] = []
        for i, (label, _days, _phrase) in enumerate(_SPANS):
            b = QPushButton(label)
            b.setMinimumHeight(BTN_HEIGHT_SMALL)
            b.clicked.connect(lambda _=False, i=i: self._on_stats_span(i))
            head.addWidget(b)
            self._stats_span_btns.append(b)
        self._stats_mark_span()
        self._stats_week_chart = WeekHourChart()
        lay.addWidget(self._stats_week_chart)
        self._stats_patterns_hint = QLabel("")
        self._stats_patterns_hint.setProperty("hint", "true")
        self._stats_patterns_hint.setWordWrap(True)
        lay.addWidget(self._stats_patterns_hint)

    def _stats_mark_span(self) -> None:
        for i, b in enumerate(self._stats_span_btns):
            b.setProperty("role", "segActive" if i == self._stats_span
                          else "segIdle")
            self._repolish(b)

    # ---- Month ---------------------------------------------------------

    def _stats_build_month_card(self, parent_lay) -> None:
        lay, head = self._stats_card(parent_lay, "Month")
        today = date.today()
        self._stats_month = (today.year, today.month)
        prev_btn = QPushButton("←")
        prev_btn.setToolTip("Previous month")
        prev_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        prev_btn.clicked.connect(lambda: self._on_stats_month_step(-1))
        self._stats_month_label = QLabel("")
        self._stats_month_label.setAlignment(Qt.AlignCenter)
        self._stats_month_label.setMinimumWidth(120)
        next_btn = QPushButton("→")
        next_btn.setToolTip("Next month")
        next_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        next_btn.clicked.connect(lambda: self._on_stats_month_step(1))
        for w in (prev_btn, self._stats_month_label, next_btn):
            head.addWidget(w)

        body = _hbox(0, 16)
        self._stats_calendar = MonthCalendar()
        body.addWidget(self._stats_calendar, 0, Qt.AlignTop)
        tiles = QGridLayout()
        tiles.setHorizontalSpacing(8)
        tiles.setVerticalSpacing(8)
        order = (("active", "Active"), ("thrusts", "Thrusts"),
                 ("sessions", "Sessions"), ("days", "Days with play"),
                 ("best", "Best day"), ("per_day", "Average play day"))
        self._stats_month_tiles = {key: _Tile(caption) for key, caption in order}
        for i, (key, _caption) in enumerate(order):
            tiles.addWidget(self._stats_month_tiles[key], i // 2, i % 2)
        tiles.setColumnStretch(0, 1)
        tiles.setColumnStretch(1, 1)
        tiles.setRowStretch(3, 1)
        body.addLayout(tiles, 1)
        lay.addLayout(body)
        self._stats_month_hint = QLabel("")
        self._stats_month_hint.setProperty("hint", "true")
        self._stats_month_hint.setWordWrap(True)
        lay.addWidget(self._stats_month_hint)

    # ---- One session ---------------------------------------------------

    def _stats_build_detail_page(self, parent_lay) -> None:
        head = _hbox(0, 8)
        back = QPushButton("←  All sessions")
        back.setMinimumHeight(BTN_HEIGHT_SMALL)
        back.clicked.connect(self._stats_close_session)
        head.addWidget(back)
        self._stats_detail_title = QLabel("Session")
        self._stats_detail_title.setObjectName("sectionTitle")
        head.addWidget(self._stats_detail_title, 1)
        parent_lay.addLayout(head)

        card = _Card()
        lay = _vbox(14, 10)
        card.setLayout(lay)
        parent_lay.addWidget(card)

        self._stats_detail_note = QLabel("")
        self._stats_detail_note.setProperty("hint", "true")
        self._stats_detail_note.setWordWrap(True)
        lay.addWidget(self._stats_detail_note)

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(8)
        self._stats_detail_tiles = [_Tile() for _ in range(4)]
        for i, tile in enumerate(self._stats_detail_tiles):
            tiles.addWidget(tile, 0, i)
            tiles.setColumnStretch(i, 1)
        lay.addLayout(tiles)

        self._stats_timeline = SessionTimeline()
        lay.addWidget(self._stats_timeline)
        self._stats_span_chart = SpanTimeline()
        lay.addWidget(self._stats_span_chart)

        self._stats_insights_head = QLabel("Analysis")
        hf = self._stats_insights_head.font()
        hf.setBold(True)
        self._stats_insights_head.setFont(hf)
        lay.addWidget(self._stats_insights_head)
        self._stats_insights_lay = _vbox(0, 4)
        lay.addLayout(self._stats_insights_lay)

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
        self._stats_tick_n = getattr(self, "_stats_tick_n", 0) + 1
        if self._stats_detail.isVisible():
            # A finished session never changes; the running one does.
            if self._stats_detail_kind == "live":
                self._stats_fill_detail()
            return
        self._refresh_statistics_view(
            slow=self._stats_tick_n % _SLOW_EVERY_TICKS == 0)

    def _refresh_statistics_view(self, slow: bool = True) -> None:
        if not hasattr(self, "_stats_active_tile"):
            return
        if self._stats_detail.isVisible():
            self._stats_fill_detail()
            return
        self._stats_fill_sessions()
        self._stats_fill_lifetime()
        if slow:
            self._stats_fill_facts()
            self._stats_fill_patterns()
            self._stats_fill_month()

    # ---- Sessions ------------------------------------------------------

    def _stats_fill_sessions(self) -> None:
        try:
            rows = self.controller.get_stats_sessions() or []
        except Exception:
            rows = []
        shown = rows[:self._stats_list_limit]
        ids = [r["id"] for r in shown]
        if ids != self._stats_row_ids:
            clear_layout(self._stats_list_lay)
            self._stats_rows = []
            for r in shown:
                row = _SessionRow(lambda sid=r["id"]: self._stats_open_session(sid))
                self._stats_list_lay.addWidget(row)
                self._stats_rows.append(row)
            self._stats_row_ids = ids
        for widget, r in zip(self._stats_rows, shown):
            widget.fill(r)
        self._stats_list_empty.setVisible(not rows)
        more = len(rows) > len(shown)
        self._stats_more_btn.setVisible(more)
        self._stats_more_label.setText(
            f"Showing {len(shown)} of {len(rows)}" if more else "")
        self._stats_more_label.setVisible(more)

    # ---- Lifetime ------------------------------------------------------

    def _stats_fill_lifetime(self) -> None:
        try:
            snap = self.controller.get_stats_snapshot() or {}
        except Exception:
            return
        lifetime = snap.get("lifetime") or {}
        session = snap.get("session") or {}

        self._stats_active_tile.set(fmt_dur(lifetime.get("active_s", 0.0)))
        self._stats_thrusts_tile.set(f"{int(lifetime.get('thrusts', 0)):,}")
        self._stats_sessions_tile.set(f"{int(lifetime.get('sessions', 0)):,}")

        started = session.get("started_ts") or 0.0
        started_txt = _fmt_when(started) if started else "—"
        self._stats_session_label.setText(
            f"This session: {fmt_dur(session.get('active_s', 0.0))} active"
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
            zone_rows.append((
                key, zone_label(key),
                float((lifetime_zones.get(key) or {}).get("contact_s", 0.0)),
                float((session_zones.get(key) or {}).get("contact_s", 0.0)),
            ))
        self._stats_fill_table(self._stats_zones_table, zone_rows,
                               "No zone contact recorded yet.")

    def _stats_fill_facts(self) -> None:
        try:
            facts = self.controller.get_stats_fun_facts() or {}
        except Exception:
            facts = {}
        tiles: List[Tuple[str, str, str, str]] = []   # key, caption, value, note
        if "avg_session_s" in facts:
            tiles.append(("avg", "Average session",
                          fmt_short(facts["avg_session_s"]),
                          f"active, {facts.get('avg_session_thrusts', 0):,.0f} thrusts"))
        if "pace" in facts:
            tiles.append(("pace", "Average pace", f"{facts['pace']:.0f} / min",
                          "thrusts per active minute"))
        if "fav_toy" in facts:
            name, share = facts["fav_toy"]
            tiles.append(("toy", "Favourite toy", name,
                          f"{share:.0%} of all toy time"))
        if "fav_zone" in facts:
            key, share = facts["fav_zone"]
            tiles.append(("zone", "Favourite spot", zone_label(key),
                          f"{share:.0%} of all contact"))
        if "night_share" in facts:
            tiles.append(("night", "Night owl", f"{facts['night_share']:.0%}",
                          "of your play is between 22:00 and 04:00"))
        if "busiest_weekday" in facts:
            tiles.append(("weekday", "Busiest day",
                          WEEKDAYS_LONG[facts["busiest_weekday"]],
                          "by active time"))
        if "best_session" in facts:
            n, ts = facts["best_session"]
            tiles.append(("best", "Best session", f"{n:,} thrusts", fmt_day(ts)))
        if "longest_session" in facts:
            s, ts = facts["longest_session"]
            tiles.append(("longest", "Longest session",
                          f"{fmt_short(s)} active", fmt_day(ts)))
        if "record_pace" in facts:
            n, ts = facts["record_pace"]
            tiles.append(("record", "Record pace", f"{n} / min",
                          f"thrusts in one minute, {fmt_day(ts)}"))

        sig = tuple(t[0] for t in tiles)
        if sig != self._stats_facts_sig:
            clear_layout(self._stats_facts_grid)
            self._stats_fact_tiles = {}
            cols = 3
            for i, (key, caption, _v, _n) in enumerate(tiles):
                tile = _Tile(caption)
                self._stats_facts_grid.addWidget(tile, i // cols, i % cols)
                self._stats_fact_tiles[key] = tile
            for c in range(cols):
                self._stats_facts_grid.setColumnStretch(c, 1)
            self._stats_facts_sig = sig
        for key, _caption, value, note in tiles:
            self._stats_fact_tiles[key].set(value, note)
        self._stats_facts_host.setVisible(bool(tiles))
        self._stats_facts_empty.setVisible(not tiles)

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
                # One line: in a grid with no column stretch a wrapping
                # label collapses to ~85px and breaks mid-sentence.
                empty.setWordWrap(False)
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
                life = QLabel(fmt_dur(life_s))
                sess = QLabel(fmt_dur(sess_s))
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
            pair[0].setText(fmt_dur(life_s))
            pair[1].setText(fmt_dur(sess_s))

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

    # ---- Charts --------------------------------------------------------

    def _stats_fill_patterns(self) -> None:
        _label, days, phrase = _SPANS[self._stats_span]
        try:
            pat = self.controller.get_stats_patterns(days) or {}
        except Exception:
            pat = {}
        active = pat.get("active") or [[0.0] * 24 for _ in range(7)]
        thrusts = pat.get("thrusts") or [[0] * 24 for _ in range(7)]
        self._stats_week_chart.set_data(active, thrusts, phrase)
        self._stats_estimated_until = float(pat.get("estimated_until") or 0.0)
        first = pat.get("first_hour")
        if self._stats_estimated_until:
            self._stats_patterns_hint.setText(
                f"Before {fmt_day(self._stats_estimated_until)} these are "
                f"estimates: your saved session totals, spread over the hours "
                f"your toys were connected according to the app's log. From "
                f"then on every second is measured. Hover a cell or a bar for "
                f"the numbers.")
        elif first:
            try:
                since = datetime.strptime(first, "%Y-%m-%dT%H")
                since_txt = f"{fmt_day(since.timestamp())} {since.year}"
            except ValueError:
                since_txt = first
            self._stats_patterns_hint.setText(
                f"Recording by the hour since {since_txt}. Hover a cell or "
                f"a bar for the numbers.")
        else:
            self._stats_patterns_hint.setText(
                "Recording by the hour starts with your next session. "
                "Older sessions only kept their totals, so they show up on "
                "the month calendar but not here.")

    def _stats_fill_month(self) -> None:
        y, m = self._stats_month
        self._stats_month_label.setText(date(y, m, 1).strftime("%B %Y"))
        try:
            days = self.controller.get_stats_month(y, m) or {}
        except Exception:
            days = {}
        today = date.today()
        until = self._stats_estimated_until
        self._stats_calendar.set_month(y, m, days,
                                       (today.year, today.month, today.day),
                                       estimated_until=until)
        self._stats_month_hint.setText(
            f"Days before {fmt_day(until)} are estimated from the app's log "
            f"and your saved session totals." if until else
            "Sessions from before the charts existed count on the day they "
            "started.")
        active = sum(v.get("active_s", 0.0) for v in days.values())
        thrusts = sum(int(v.get("thrusts", 0)) for v in days.values())
        sessions = sum(int(v.get("sessions", 0)) for v in days.values())
        t = self._stats_month_tiles
        t["active"].set(fmt_short(active))
        t["thrusts"].set(f"{thrusts:,}")
        t["sessions"].set(f"{sessions:,}")
        played = {d: v for d, v in days.items() if v.get("active_s", 0.0) > 0}
        ndays = (date(y + (m == 12), m % 12 + 1, 1) - date(y, m, 1)).days
        t["days"].set(f"{len(played)}", f"of {ndays}")
        if played:
            best = max(played, key=lambda d: played[d]["active_s"])
            when = datetime(y, m, best).timestamp()
            t["best"].set(fmt_day(when),
                          f"{fmt_short(played[best]['active_s'])} active")
            avg = active / len(played)
            t["per_day"].set(fmt_short(avg),
                             f"{thrusts / len(played):,.0f} thrusts")
        else:
            t["best"].set("—", "nothing this month")
            t["per_day"].set("—")

    # ---- One session ---------------------------------------------------

    def _stats_open_session(self, session_id: str) -> None:
        view = self.views.get("Statistics") if hasattr(self, "views") else None
        bar = view.verticalScrollBar() if view is not None else None
        self._stats_list_scroll = bar.value() if bar is not None else 0
        self._stats_detail_id = session_id
        if not self._stats_fill_detail():
            self._stats_detail_id = None
            return
        self._stats_overview.setVisible(False)
        self._stats_detail.setVisible(True)
        if bar is not None:
            QTimer.singleShot(0, lambda: bar.setValue(0))

    def _stats_close_session(self) -> None:
        self._stats_detail_id = None
        self._stats_detail_kind = None
        self._stats_detail.setVisible(False)
        self._stats_overview.setVisible(True)
        self._refresh_statistics_view()
        view = self.views.get("Statistics") if hasattr(self, "views") else None
        if view is not None:
            pos = self._stats_list_scroll
            QTimer.singleShot(0, lambda: view.verticalScrollBar().setValue(pos))

    def _stats_fill_detail(self) -> bool:
        """Populate the session page from the controller. False when the
        session no longer exists (reset, pruned)."""
        sid = self._stats_detail_id
        try:
            d = self.controller.get_stats_session_detail(sid) if sid else None
        except Exception:
            d = None
        if not d:
            if self._stats_detail.isVisible():
                self._stats_close_session()
            return False
        kind = d.get("kind")
        self._stats_detail_kind = kind
        started = d.get("started_ts", 0.0)
        if kind == "live":
            title = f"{fmt_day(started)}  {fmt_clock(started)}, still going"
        else:
            end = started + float(d.get("duration_s", 0.0))
            title = (f"{fmt_day(started)}  {fmt_clock(started)} to "
                     f"{fmt_clock(end)}  ·  app open "
                     f"{fmt_short(d.get('duration_s', 0.0))}")
        self._stats_detail_title.setText(title)

        notes = {
            "live": "This session is still being recorded; the page "
                    "updates every second.",
            "summary": "Recorded before session timelines existed, or by "
                       "the full edition, so only the totals are known.",
        }
        note = notes.get(kind, "")
        if kind == "summary" and d.get("connected"):
            note = ("Recorded before session timelines existed, so only the "
                    "totals are known. The bars show when each toy was "
                    "connected, from the app's log.")
        if d.get("recovered"):
            note = ("The app was closed without shutting down. This session "
                    "was rebuilt from its last save, so its last minute may "
                    "be missing.")
        self._stats_detail_note.setText(note)
        self._stats_detail_note.setVisible(bool(note))

        active = float(d.get("active_s", 0.0))
        thrusts = int(d.get("thrusts", 0) or 0)
        tiles = self._stats_detail_tiles
        a = d.get("analysis") or {}
        if kind == "summary":
            minutes = active / 60.0
            tiles[0].set(fmt_short(active), "toy on or zone touched",
                         caption="Active")
            tiles[1].set(f"{thrusts:,}", "", caption="Thrusts")
            tiles[2].set(fmt_short(d.get("duration_s", 0.0)), "",
                         caption="App open")
            tiles[3].set(f"{thrusts / minutes:.0f} / min" if minutes >= 1 else "—",
                         "thrusts per active minute", caption="Average pace")
        else:
            window = float(a.get("window_s", 0.0))
            share = f"{active / window:.0%} of " if window else ""
            w0 = started + float(a.get("window_start_s", 0.0))
            tiles[0].set(fmt_short(active),
                         f"{share}{fmt_clock(w0)} to {fmt_clock(w0 + window)}",
                         caption="Active")
            per_min = thrusts / (active / 60.0) if active >= 60 else 0.0
            tiles[1].set(f"{thrusts:,}",
                         f"{per_min:.0f} per active minute" if per_min else "",
                         caption="Thrusts")
            pace = int(a.get("peak_pace", 0))
            tiles[2].set(f"{pace} / min" if pace else "—",
                         f"at {fmt_clock(started + a.get('peak_pace_at_s', 0))}"
                         if pace else "no thrusts", caption="Peak pace")
            tiles[3].set(fmt_short(a.get("streak_s", 0)),
                         "without a real break", caption="Longest streak")
        self._stats_timeline.setVisible(kind != "summary")
        spans = d.get("connected") if kind == "summary" else None
        self._stats_span_chart.setVisible(bool(spans))
        if spans:
            self._stats_span_chart.set_spans(spans, started,
                                             float(d.get("duration_s", 0.0)))
        self._stats_insights_head.setText(
            "Totals" if kind == "summary" else "Analysis")
        if kind != "summary":
            self._stats_timeline.set_detail(d)
        self._stats_fill_insights(d)
        return True

    def _stats_fill_insights(self, d: Dict[str, Any]) -> None:
        clear_layout(self._stats_insights_lay)
        started = d.get("started_ts", 0.0)
        a = d.get("analysis") or {}
        lines: List[str] = []
        if d.get("kind") != "summary" and a.get("hot_len_s"):
            t0 = started + a.get("hot_at_s", 0)
            t1 = t0 + a.get("hot_len_s", 0)
            if a.get("hot_kind") == "thrusts":
                lines.append(f"Hottest 5 minutes: {fmt_clock(t0)} to "
                             f"{fmt_clock(t1)}, {int(a.get('hot_value', 0)):,} "
                             f"thrusts.")
            else:
                lines.append(f"Most intense 5 minutes: {fmt_clock(t0)} to "
                             f"{fmt_clock(t1)}, toys at "
                             f"{a.get('hot_value', 0):.0%} on average.")
        if a.get("top_toy"):
            lines.append(f"{a['top_toy']} did {a['top_toy_share']:.0%} of the "
                         f"buzzing, at {a['top_toy_level']:.0%} on average.")
        if a.get("break_s"):
            lines.append(f"Longest break: {fmt_short(a['break_s'])}, from "
                         f"{fmt_clock(started + a['break_at_s'])}.")
        if a.get("top_zone"):
            lines.append(f"Most contact: {zone_label(a['top_zone'])}, "
                         f"{fmt_short(a['top_zone_s'])}.")
        toys = d.get("toys") or {}
        if toys:
            order = sorted(toys, key=lambda n: -float(toys[n]))
            if d.get("kind") != "summary":
                lane_order = self._stats_timeline.toy_order()
            elif d.get("connected"):
                lane_order = self._stats_span_chart.toy_order()
            else:
                lane_order = order
            parts = []
            for name in order:
                dot = ""
                if name in lane_order:
                    color = toy_color(lane_order.index(name))
                    dot = f"<span style='color:{color}'>&#9632;</span> "
                parts.append(f"{dot}{name} {fmt_short(toys[name])}")
            lines.append("Toy time: " + "  ·  ".join(parts))
        zones = d.get("zones") or {}
        if zones:
            order = sorted(zones, key=lambda z: -float(zones[z]))
            lines.append("Contact: " + "  ·  ".join(
                f"{zone_label(z)} {fmt_short(zones[z])}" for z in order))
        if not lines:
            lines.append("Nothing much happened in this one.")
        for text in lines:
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.RichText)
            lbl.setWordWrap(True)
            self._stats_insights_lay.addWidget(lbl)

    # ----------------------------------------------------------
    # Handlers
    # ----------------------------------------------------------

    def _on_stats_show_more(self) -> None:
        self._stats_list_limit += _LIST_PAGE
        self._stats_fill_sessions()

    def _on_stats_span(self, index: int) -> None:
        self._stats_span = index
        self._stats_mark_span()
        self._stats_fill_patterns()

    def _on_stats_month_step(self, step: int) -> None:
        y, m = self._stats_month
        m += step
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self._stats_month = (y, m)
        self._stats_fill_month()

    def _on_stats_reset(self) -> None:
        confirm = QMessageBox.question(
            self.window, "Reset statistics",
            "Reset ALL statistics: the lifetime totals, every session and "
            "its timeline, and the charts? This cannot be undone.",
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
        self.log_message("Statistics reset.")
        self._refresh_statistics_view()
