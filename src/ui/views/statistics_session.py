"""Statistics view, one session's page: its tiles, the timeline (an
intensity lane per toy, thrusts per minute, a lane per zone, the people
tagged), and a short analysis. Part of StatisticsMixin (statistics.py)."""

from typing import Any, Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton

from constants import BTN_HEIGHT_SMALL
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout
from ui.stats_charts import (
    SpanTimeline, fmt_clock, fmt_day, fmt_short, toy_color, zone_label,
)
from ui.session_timeline import SessionTimeline
from ui.stats_widgets import Tile
from ui.widgets import Card as _Card


class StatisticsSessionMixin:

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
        self._stats_detail_tiles = [Tile() for _ in range(4)]
        for i, tile in enumerate(self._stats_detail_tiles):
            tiles.addWidget(tile, 0, i)
            tiles.setColumnStretch(i, 1)
        lay.addLayout(tiles)

        self._stats_build_tags_box(lay)

        self._stats_timeline = SessionTimeline()
        self._stats_timeline.stretchSelected.connect(self._on_stats_stretch_selected)
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

    def _stats_open_session(self, session_id: str) -> None:
        view = self.views.get("Statistics") if hasattr(self, "views") else None
        bar = view.verticalScrollBar() if view is not None else None
        self._stats_list_scroll = bar.value() if bar is not None else 0
        self._on_stats_tag_cancel()
        self._stats_detail_id = session_id
        if not self._stats_fill_detail():
            self._stats_detail_id = None
            return
        self._stats_overview.setVisible(False)
        self._stats_detail.setVisible(True)
        if bar is not None:
            QTimer.singleShot(0, lambda: bar.setValue(0))

    def _stats_close_session(self) -> None:
        self._on_stats_tag_cancel()
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
        self._stats_fill_tags(d)
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
