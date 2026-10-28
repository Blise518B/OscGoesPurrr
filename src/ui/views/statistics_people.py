"""Statistics view, who sessions were with: the People card (everyone
tagged, most thrusts first, and the switch that tags from VRChat's log),
and tagging -- a right-click on a session in the list, or on its page the
whole session or a stretch dragged out on its timeline. Part of
StatisticsMixin (statistics.py)."""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtWidgets import QGridLayout, QLabel, QMenu, QPushButton, QWidget

from constants import BTN_HEIGHT_SMALL
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout
from ui.stats_charts import fmt_clock, fmt_day, fmt_short
from ui.stats_widgets import NamesEditor
from ui.widgets import ToggleSwitch

# People shown before "Show all".
_PEOPLE_PAGE = 10


def _people_status_text(st: Dict[str, Any]) -> str:
    """The VRChat-log switch's status line."""
    state = st.get("state")
    return {
        "off": "",
        "no_stats": "Usage statistics are off (Settings → Features), so "
                    "nothing is tagged.",
        "starting": "Reading VRChat's log…",
        "reading": "Reading VRChat's log…",
        "no_log": "VRChat's log isn't there. VRChat writes it to "
                  "AppData\\LocalLow\\VRChat\\VRChat unless logging is "
                  "switched off in its settings.",
        "no_vrchat": "Waiting for VRChat.",
        "alone": "Nobody else is in your instance.",
        "with": f"Alone with {st.get('name', '')}: this session is being "
                f"tagged with them.",
        "crowd": f"{st.get('count', 0)} other people are in your instance, "
                 f"so nobody is tagged.",
    }.get(state, "")


class StatisticsPeopleMixin:

    # ----------------------------------------------------------
    # Building
    # ----------------------------------------------------------

    def _stats_build_people_card(self, parent_lay) -> None:
        lay, head = self._stats_card(parent_lay, "People")
        self._explain(head,
            "People",
            "Everyone you tagged sessions with, most thrusts first. Each "
            "person gets what happened while they were tagged: the active "
            "time, the thrusts, and their best minute (peak pace).<br><br>"
            "Tag a session on its page: the whole session, or drag across "
            "its timeline to tag a stretch of it — for a session that had "
            "more than one person in it. Two people tagged on the same "
            "stretch both get all of it. Names match without regard to "
            "upper and lower case."
        )
        self._stats_auto_toggle = ToggleSwitch(
            "Tag who you're with from VRChat's log")
        try:
            on = bool(self.controller.get_people_autodetect_enabled())
        except Exception:
            on = False
        self._stats_auto_toggle.setChecked(on)
        self._stats_auto_toggle.toggled.connect(self._on_stats_autodetect)
        lay.addWidget(self._stats_auto_toggle)
        self._explain(
            self._stats_auto_toggle, "Tag who you're with from VRChat's log",
            "While you are alone in an instance with exactly one other "
            "person, the running session is tagged with them, from the "
            "moment that was true until it isn't any more (someone joins, "
            "they leave, you change world). A stretch with nothing in it is "
            "dropped again. With more people around nobody is tagged; tag "
            "those sessions yourself.<br><br>"
            "VRChat writes who joins and leaves your instance to a log file "
            "on this PC; the app reads that file while this is on, and keeps "
            "only the names of people you were tagged with. Nothing leaves "
            "your PC. Off by default.")
        self._stats_auto_status = QLabel("")
        self._stats_auto_status.setProperty("hint", "true")
        self._stats_auto_status.setWordWrap(True)
        lay.addWidget(self._stats_auto_status)

        host = QWidget()
        self._stats_people_grid = QGridLayout()
        self._stats_people_grid.setContentsMargins(0, 4, 0, 0)
        self._stats_people_grid.setHorizontalSpacing(20)
        self._stats_people_grid.setVerticalSpacing(2)
        self._stats_people_grid.setColumnStretch(1, 1)
        host.setLayout(self._stats_people_grid)
        lay.addWidget(host)
        self._stats_people_host = host
        self._stats_people_empty = self._muted_label(
            "Nobody tagged yet. Open a session and tag who it was with: the "
            "whole session, or drag across its timeline to tag a stretch.")
        lay.addWidget(self._stats_people_empty)
        more_row = _hbox(0, 8)
        self._stats_people_more_label = QLabel("")
        self._stats_people_more_label.setProperty("hint", "true")
        more_row.addWidget(self._stats_people_more_label, 1)
        self._stats_people_more_btn = QPushButton("Show all")
        self._stats_people_more_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._stats_people_more_btn.clicked.connect(self._on_stats_people_more)
        more_row.addWidget(self._stats_people_more_btn)
        lay.addLayout(more_row)
        self._stats_people_all = False
        self._stats_people_keys: Optional[tuple] = None
        self._stats_people_cells: Dict[str, List[QLabel]] = {}

    def _stats_build_tags_box(self, parent_lay) -> None:
        """Who the session was with: the whole-session names, the tag
        editor (shared by the whole session and a dragged-out stretch),
        and the tagged stretches."""
        box = QWidget()
        lay = _vbox(0, 6)
        box.setLayout(lay)
        parent_lay.addWidget(box)

        row = _hbox(0, 8)
        with_lbl = QLabel("With")
        wf = with_lbl.font()
        wf.setBold(True)
        with_lbl.setFont(wf)
        row.addWidget(with_lbl)
        self._stats_with_host = QWidget()
        self._stats_with_lay = _hbox(0, 6)
        self._stats_with_host.setLayout(self._stats_with_lay)
        row.addWidget(self._stats_with_host)
        self._stats_with_none = QLabel("nobody tagged")
        self._stats_with_none.setProperty("hint", "true")
        row.addWidget(self._stats_with_none)
        row.addStretch(1)
        self._stats_tag_whole_btn = QPushButton("Tag session…")
        self._stats_tag_whole_btn.setProperty("role", "secondary")
        self._stats_tag_whole_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._stats_tag_whole_btn.clicked.connect(self._on_stats_tag_whole)
        row.addWidget(self._stats_tag_whole_btn)
        lay.addLayout(row)
        self._explain(
            self._stats_tag_whole_btn, "Tag session",
            "Who this whole session was with. Type one name or several, "
            "separated by commas; names you used before are suggested. "
            "Clear the field to remove the tag. For a session with more "
            "than one person in it, drag across the timeline below instead "
            "and tag each stretch.")

        self._stats_tag_editor = NamesEditor(self._on_stats_tag_save, self._on_stats_tag_cancel)
        lay.addWidget(self._stats_tag_editor)
        # ("whole",) or ("stretch", start epoch, end epoch) while editing.
        self._stats_tag_mode: Optional[tuple] = None

        self._stats_stretch_lay = _vbox(0, 2)
        lay.addLayout(self._stats_stretch_lay)
        self._stats_stretch_rows: Dict[int, Tuple[QWidget, QLabel]] = {}
        self._stats_stretch_sig: Optional[tuple] = None
        self._stats_tags_hint = QLabel(
            "More than one person? Drag across the timeline to tag a stretch "
            "of the session with someone.")
        self._stats_tags_hint.setProperty("hint", "true")
        self._stats_tags_hint.setWordWrap(True)
        lay.addWidget(self._stats_tags_hint)
        self._stats_tags_box = box

    def _stats_build_list_editor(self) -> None:
        """The name field a right-click on a session opens under its row
        (one, moved to whichever row asked)."""
        self._stats_list_editor = NamesEditor(
            self._on_stats_list_save, self._on_stats_list_cancel, "With:",
            parent=self._stats_list_host, margins=(8, 2, 8, 6))
        self._stats_list_edit_id: Optional[str] = None

    # ----------------------------------------------------------
    # Filling
    # ----------------------------------------------------------

    def _stats_fill_people_status(self) -> None:
        try:
            st = self.controller.get_people_autodetect_status() or {}
        except Exception:
            st = {}
        text = _people_status_text(st)
        self._stats_auto_status.setText(text)
        self._stats_auto_status.setVisible(bool(text))

    def _stats_fill_people(self) -> None:
        try:
            rows = self.controller.get_people_table() or []
        except Exception:
            rows = []
        shown = rows if self._stats_people_all else rows[:_PEOPLE_PAGE]
        keys = tuple(r["name"] for r in shown)
        grid = self._stats_people_grid
        if keys != self._stats_people_keys:
            self._stats_clear_grid(grid)
            self._stats_people_cells = {}
            self._stats_people_keys = keys
            if shown:
                for col, text in enumerate(("", "Name", "Sessions", "Active",
                                            "Thrusts", "Peak pace", "Last time")):
                    h = QLabel(text)
                    h.setProperty("muted", "true")
                    self._repolish(h)
                    grid.addWidget(h, 0, col)
            for i, r in enumerate(shown):
                cells = [QLabel() for _ in range(7)]
                cells[0].setProperty("muted", "true")
                self._repolish(cells[0])
                for col, cell in enumerate(cells):
                    grid.addWidget(cell, i + 1, col)
                self._stats_people_cells[r["name"]] = cells
        for i, r in enumerate(shown):
            cells = self._stats_people_cells.get(r["name"])
            if cells is None:
                continue
            pace = int(r.get("peak_pace", 0))
            for cell, text in zip(cells, (
                    f"{i + 1}", r["name"], f"{int(r.get('sessions', 0)):,}",
                    fmt_short(r.get("active_s", 0.0)),
                    f"{int(r.get('thrusts', 0)):,}",
                    f"{pace} / min" if pace else "—",
                    fmt_day(r.get("last_ts", 0.0)))):
                cell.setText(text)
        self._stats_people_host.setVisible(bool(shown))
        self._stats_people_empty.setVisible(not rows)
        more = len(rows) > _PEOPLE_PAGE
        self._stats_people_more_btn.setVisible(more)
        self._stats_people_more_btn.setText(
            "Top 10" if self._stats_people_all else "Show all")
        self._stats_people_more_label.setText(
            f"{len(rows)} people" if more else "")
        self._stats_people_more_label.setVisible(more)

    def _stats_fill_tags(self, d: Dict[str, Any]) -> None:
        """The session's people: names on the With row, the stretch list,
        and the stretches on the timeline. Rows rebuild only when the tags
        change, so a running session's page doesn't churn every second."""
        tags = d.get("tags") or []
        kind = d.get("kind")
        started = float(d.get("started_ts", 0.0))
        end = started + float(d.get("duration_s", 0.0))
        whole = next((t for t in tags if t.get("whole")), None)
        stretches = [t for t in tags if not t.get("whole")]

        names = tuple(whole["people"]) if whole else ()
        if names != getattr(self, "_stats_with_names", None):
            clear_layout(self._stats_with_lay)
            for name in names:
                chip = QLabel(name)
                chip.setProperty("role", "pill")
                self._stats_with_lay.addWidget(chip)
            self._stats_with_names = names
        self._stats_with_host.setVisible(bool(names))
        self._stats_with_none.setVisible(not names)
        self._stats_tag_whole_btn.setText("Change…" if names else "Tag session…")

        sig = tuple((t["id"], tuple(t["people"]), t.get("start"), t.get("end"))
                    for t in stretches)
        if sig != self._stats_stretch_sig:
            clear_layout(self._stats_stretch_lay)
            self._stats_stretch_rows = {}
            for t in stretches:
                row = QWidget()
                rl = _hbox(0, 10)
                row.setLayout(rl)
                t0 = float(t.get("start", started))
                t1 = t.get("end")
                when = QLabel(f"{fmt_clock(t0)} to "
                              f"{fmt_clock(t1) if t1 is not None else 'now'}")
                when.setMinimumWidth(110)
                rl.addWidget(when)
                who = QLabel(", ".join(t["people"]))
                wf = who.font()
                wf.setBold(True)
                who.setFont(wf)
                rl.addWidget(who)
                numbers = QLabel("")
                numbers.setProperty("muted", "true")
                self._repolish(numbers)
                rl.addWidget(numbers)
                if t.get("auto"):
                    src = QLabel("from VRChat")
                    src.setProperty("role", "pill")
                    src.setProperty("tone", "idle")
                    src.setToolTip("Tagged from VRChat's log: you were alone "
                                   "in the instance with them.")
                    rl.addWidget(src)
                rl.addStretch(1)
                rm = QPushButton("Remove")
                rm.setProperty("role", "ghost")
                rm.setMinimumHeight(BTN_HEIGHT_SMALL)
                rm.clicked.connect(
                    lambda _=False, tid=t["id"]: self._on_stats_tag_remove(tid))
                rl.addWidget(rm)
                self._stats_stretch_lay.addWidget(row)
                self._stats_stretch_rows[t["id"]] = (row, numbers)
            self._stats_stretch_sig = sig
        for t in stretches:
            entry = self._stats_stretch_rows.get(t["id"])
            if entry is None:
                continue
            thrusts = int(t.get("thrusts", 0))
            entry[1].setText(f"{thrusts:,} thrusts  ·  "
                             f"{fmt_short(t.get('active_s', 0.0))} active")

        timeline = kind != "summary"
        self._stats_tags_hint.setVisible(timeline and not stretches)
        if timeline:
            self._stats_timeline.set_tags([
                (float(t.get("start", started)),
                 float(t["end"]) if t.get("end") is not None else end,
                 ", ".join(t["people"]))
                for t in stretches])

    # ----------------------------------------------------------
    # Tagging
    # ----------------------------------------------------------

    def _stats_row_menu(self, sid: str, pos) -> None:
        """Right-click on a session in the list."""
        row = self._stats_row_data.get(sid) or {}
        whole = row.get("whole_people") or []
        menu = QMenu(self._stats_list_host)
        menu.addAction("Open session").triggered.connect(
            lambda _=False: self._stats_open_session(sid))
        menu.addSeparator()
        menu.addAction("Change tag\u2026" if whole else "Tag session\u2026").triggered.connect(
            lambda _=False: self._stats_list_tag(sid))
        if whole:
            menu.addAction("Remove tag").triggered.connect(
                lambda _=False: self._stats_list_untag(sid))
        menu.exec(pos)

    def _stats_list_tag(self, sid: str) -> None:
        """Open the name field under a session's row."""
        if sid not in self._stats_row_ids:
            return
        row = self._stats_row_data.get(sid) or {}
        try:
            names = self.controller.get_people_names() or []
        except Exception:
            names = []
        self._stats_list_lay.removeWidget(self._stats_list_editor)
        self._stats_list_lay.insertWidget(
            self._stats_row_ids.index(sid) + 1, self._stats_list_editor)
        self._stats_list_edit_id = sid
        self._stats_list_editor.open(names, ", ".join(row.get("whole_people") or []))

    def _stats_list_untag(self, sid: str) -> None:
        try:
            self.controller.tag_session(sid, "")
        except Exception as e:
            self.log_message(f"Removing the tag failed: {e}")
        self._stats_after_list_edit()

    def _on_stats_list_save(self) -> None:
        sid = self._stats_list_edit_id
        if not sid:
            return
        try:
            self.controller.tag_session(sid, self._stats_list_editor.text())
        except Exception as e:
            self.log_message(f"Tagging the session failed: {e}")
        self._on_stats_list_cancel()
        self._stats_after_list_edit()

    def _on_stats_list_cancel(self) -> None:
        self._stats_list_edit_id = None
        self._stats_list_editor.dismiss()

    def _stats_after_list_edit(self) -> None:
        self._stats_fill_sessions()
        self._stats_fill_people()

    def _on_stats_autodetect(self, checked: bool) -> None:
        try:
            self.controller.set_people_autodetect(bool(checked))
        except Exception as e:
            self.log_message(f"VRChat-log tagging switch failed: {e}")
        self._stats_fill_people_status()

    def _on_stats_people_more(self) -> None:
        self._stats_people_all = not self._stats_people_all
        self._stats_fill_people()

    def _stats_open_tag_editor(self, what: str, prefill: str) -> None:
        try:
            names = self.controller.get_people_names() or []
        except Exception:
            names = []
        self._stats_tag_editor.open(names, prefill, what)

    def _on_stats_tag_whole(self) -> None:
        self._stats_tag_mode = ("whole",)
        self._stats_timeline.clear_selection()
        self._stats_open_tag_editor(
            "Whole session:", ", ".join(getattr(self, "_stats_with_names", ())))

    def _on_stats_stretch_selected(self, start: float, end: float) -> None:
        self._stats_tag_mode = ("stretch", start, end)
        self._stats_open_tag_editor(
            f"{fmt_clock(start)} to {fmt_clock(end)}:", "")

    def _on_stats_tag_cancel(self) -> None:
        self._stats_tag_mode = None
        if hasattr(self, "_stats_tag_editor"):
            self._stats_tag_editor.dismiss()
            self._stats_timeline.clear_selection()

    def _on_stats_tag_save(self) -> None:
        mode, sid = self._stats_tag_mode, self._stats_detail_id
        text = self._stats_tag_editor.text()
        if mode is None or not sid:
            return
        try:
            if mode[0] == "whole":
                self.controller.tag_session(sid, text)
            elif text.strip():
                self.controller.tag_session_stretch(sid, mode[1], mode[2], text)
        except Exception as e:
            self.log_message(f"Tagging the session failed: {e}")
        self._on_stats_tag_cancel()
        self._stats_fill_detail()

    def _on_stats_tag_remove(self, tag_id: int) -> None:
        sid = self._stats_detail_id
        if not sid:
            return
        try:
            self.controller.remove_session_tag(sid, tag_id)
        except Exception as e:
            self.log_message(f"Removing the tag failed: {e}")
        self._stats_fill_detail()
