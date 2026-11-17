"""Statistics view, who did what to you: the From whom card (next to People)
-- shocks, vibrates and beeps on your shockers in all, by person (your
avatar's behaviours, you through your avatar menu or Party Mode, each friend,
each web remote guest) and per shocker, plus friends' time on your toys and
their Avatar Remote sets; the switch that keeps friends' names and Forget
names -- and the Lifetime card's suits and trackers. Counted from the log
(controllers/stats_events_facade.py). Part of StatisticsMixin
(statistics.py)."""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QMessageBox, QPushButton, QWidget

from constants import BTN_HEIGHT_SMALL
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.stats_charts import fmt_day, fmt_dur, fmt_short
from ui.stats_widgets import Tile
from ui.widgets import IdentityMark, ToggleSwitch

# The card's spans: (button label, facade span)
WHOM_SPANS = (("Lifetime", "lifetime"), ("This session", "session"))

# The people grid's columns: (header, identity icon or "")
_COLUMNS = (("", ""), ("Who", ""), ("Shocks", "shock"), ("Vibrates", ""), ("Beeps", ""),
            ("Strongest", ""), ("Time", ""), ("Toys", "toys"), ("Avatar Remote", "params"),
            ("Last time", ""))
_SHOCKER_COLUMNS = (("Shocker", "shock"), ("Shocks", ""), ("Vibrates", ""), ("Beeps", ""),
                    ("Strongest", ""), ("Time", ""))
_PEOPLE_PAGE = 10

_ROLE_WORDS = {"avatar": "your avatar's behaviours on the Shockers page",
               "me": "you, as Me on the Friends page (your panel, your avatar menu, Party Mode)",
               "friend": "a friend", "web": "someone on your web remote"}


def _count(n: int) -> str:
    return f"{n:,}" if n else "—"


def secs_text(s: float) -> str:
    """How long shockers ran, the app's way: "0.5s", "48.2s", "3m 05s",
    "2h 14m"."""
    s = float(s or 0.0)
    if s < 60:
        return f"{s:.1f}s"
    return fmt_dur(s) if s < 3600 else fmt_short(s)


def op_cells(ops: Dict[str, Dict[str, Any]]) -> Tuple[str, str, str, str, str]:
    """Shocks, vibrates, beeps, strongest, time -- as the grids write them.
    Strongest is the strongest shock (the strongest vibrate when there was
    no shock, marked "vib")."""
    shock, vib, beep = ops["shock"], ops["vibrate"], ops["beep"]
    if shock["max"]:
        strongest = f"{shock['max']}"
    elif vib["max"]:
        strongest = f"{vib['max']} vib"
    else:
        strongest = "—"
    secs = shock["s"] + vib["s"] + beep["s"]
    return (_count(shock["n"]), _count(vib["n"]), _count(beep["n"]), strongest,
            secs_text(secs) if secs else "—")


def ops_line(ops: Dict[str, Dict[str, Any]]) -> str:
    """"12 shocks up to 45 (6.5s) · 30 vibrates up to 40 (20.0s) · 2 beeps"
    ("" for none) -- the session page's line."""
    parts = []
    for op, word in (("shock", "shock"), ("vibrate", "vibrate"), ("beep", "beep")):
        o = ops[op]
        if not o["n"]:
            continue
        text = f"{o['n']:,} {word}{'s' if o['n'] != 1 else ''}"
        if o["max"] and op != "beep":
            text += f" up to {o['max']}"
        if o["s"] and op != "beep":
            text += f" ({secs_text(o['s'])})"
        parts.append(text)
    return "  ·  ".join(parts)


def _head(text: str, icon: str, muted: bool = True) -> QWidget:
    """A column header: its identity icon (one icon per thing) and words."""
    w = QWidget()
    lay = _hbox(0, 4)
    w.setLayout(lay)
    if icon:
        lay.addWidget(IdentityMark(icon, 13))
    label = QLabel(text)
    if muted:
        label.setProperty("muted", "true")
    lay.addWidget(label)
    lay.addStretch(1)
    return w


class StatisticsWhomMixin:

    # ----------------------------------------------------------
    # Building
    # ----------------------------------------------------------

    def _stats_build_whom_card(self, parent_lay) -> None:
        lay, head = self._stats_card(parent_lay, "From whom")
        self._explain(head,
            "From whom",
            "Who did what to you: every shock, vibrate and beep that reached "
            "one of your shockers — how many, the strongest and how long — "
            "and who it came from. Your avatar's behaviours on the Shockers "
            "page are listed one by one under Your avatar; what you sent "
            "yourself as Me says when it came from your avatar menu or Party "
            "Mode. A friend's own menu or Party Mode isn't told over the link, "
            "so a friend is one row. Toys is how long they drove your toys, "
            "Avatar Remote how many of your avatar's controls they set.<br><br>"
            "An operation on two shockers counts on each. What was held back "
            "(Off, Pause, what you don't share) isn't counted here; hover a "
            "name for how much of theirs was. Counted from the log as it "
            "happens and kept for good, on this PC only: never sent to "
            "anyone.")
        self._stats_whom_span = 0
        self._stats_whom_btns: List[QPushButton] = []
        for i, (label, _span) in enumerate(WHOM_SPANS):
            b = QPushButton(label)
            b.setMinimumHeight(BTN_HEIGHT_SMALL)
            b.clicked.connect(lambda _=False, i=i: self._on_stats_whom_span(i))
            head.addWidget(b)
            self._stats_whom_btns.append(b)
        self._stats_mark_whom_span()

        names_row = _hbox(0, 8)
        self._stats_names_toggle = ToggleSwitch("Keep friends' names")
        try:
            on = bool(self.controller.get_stats_friend_names())
        except Exception:
            on = True
        self._stats_names_toggle.setChecked(on)
        self._stats_names_toggle.toggled.connect(self._on_stats_names)
        names_row.addWidget(self._stats_names_toggle)
        names_row.addStretch(1)
        self._stats_forget_btn = QPushButton("Forget names…")
        self._stats_forget_btn.setProperty("role", "secondary")
        self._stats_forget_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._stats_forget_btn.clicked.connect(self._on_stats_forget_names)
        names_row.addWidget(self._stats_forget_btn)
        lay.addLayout(names_row)
        self._explain(
            self._stats_names_toggle, "Keep friends' names",
            "On, each friend and each web remote guest has a row of their own "
            "here. Off, what they do from now on counts under A friend or Web "
            "remote, without a name. On by default. The names already kept "
            "stay until you click Forget names.")
        self._explain(
            self._stats_forget_btn, "Forget names",
            "Every friend's numbers go under A friend and every web remote "
            "guest's under Web remote, for good — lifetime and every session. "
            "Asks first. The Log page keeps its own 30 days of who did what; "
            "clear it there.")

        tiles = QGridLayout()
        tiles.setHorizontalSpacing(8)
        self._stats_whom_tiles = {op: Tile(caption) for op, caption in (
            ("shock", "Shocks"), ("vibrate", "Vibrates"), ("beep", "Beeps"))}
        for col, op in enumerate(("shock", "vibrate", "beep")):
            tiles.addWidget(self._stats_whom_tiles[op], 0, col)
            tiles.setColumnStretch(col, 1)
        self._stats_whom_tiles_host = QWidget()
        self._stats_whom_tiles_host.setLayout(tiles)
        tiles.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stats_whom_tiles_host)

        self._stats_whom_host = QWidget()
        self._stats_whom_grid = self._stats_whom_make_grid(self._stats_whom_host)
        lay.addWidget(self._stats_whom_host)
        self._stats_whom_empty = self._muted_label(
            "Nobody yet. Shocks, vibrates and beeps on your shockers, friends "
            "driving your toys and their Avatar Remote sets land here as they "
            "happen.")
        lay.addWidget(self._stats_whom_empty)
        more_row = _hbox(0, 8)
        self._stats_whom_more_label = QLabel("")
        self._stats_whom_more_label.setProperty("hint", "true")
        more_row.addWidget(self._stats_whom_more_label, 1)
        self._stats_whom_more_btn = QPushButton("Show all")
        self._stats_whom_more_btn.setMinimumHeight(BTN_HEIGHT_SMALL)
        self._stats_whom_more_btn.clicked.connect(self._on_stats_whom_more)
        more_row.addWidget(self._stats_whom_more_btn)
        lay.addLayout(more_row)
        self._stats_whom_all = False

        self._stats_shockers_head = QLabel("Per shocker")
        hf = self._stats_shockers_head.font()
        hf.setBold(True)
        self._stats_shockers_head.setFont(hf)
        lay.addWidget(self._stats_shockers_head)
        self._stats_shockers_host = QWidget()
        self._stats_shockers_grid = self._stats_whom_make_grid(self._stats_shockers_host)
        lay.addWidget(self._stats_shockers_host)
        self._stats_whom_sig: Optional[tuple] = None
        self._stats_whom_cells: List[List[QLabel]] = []
        self._stats_shockers_sig: Optional[tuple] = None
        self._stats_shockers_cells: List[List[QLabel]] = []

    @staticmethod
    def _stats_whom_make_grid(host: QWidget) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(2)
        host.setLayout(grid)
        return grid

    def _stats_build_worn_table(self, parent_lay) -> None:
        """The Lifetime card's suits and trackers: name / lifetime / this
        session, like the toys -- only once one has buzzed."""
        self._stats_worn_box = QWidget()
        box = _vbox(0, 4)
        self._stats_worn_box.setLayout(box)
        parent_lay.addWidget(self._stats_worn_box)
        self._stats_worn_table = self._stats_make_table(box, "Suits and trackers")
        self._stats_worn_box.setVisible(False)

    def _stats_mark_whom_span(self) -> None:
        for i, b in enumerate(self._stats_whom_btns):
            b.setProperty("role", "segActive" if i == self._stats_whom_span else "segIdle")
            self._repolish(b)

    # ----------------------------------------------------------
    # Filling
    # ----------------------------------------------------------

    def _stats_fill_whom(self) -> None:
        span = WHOM_SPANS[self._stats_whom_span][1]
        try:
            d = self.controller.get_stats_from_whom(span) or {}
        except Exception:
            d = {}
        ops = d.get("ops") or {}
        if ops:
            for op, tile in self._stats_whom_tiles.items():
                o = ops[op]
                note = ""
                if o["n"] and op != "beep":
                    secs = secs_text(o["s"])
                    note = f"up to {o['max']}  ·  {secs}" if o["max"] else secs
                tile.set(f"{o['n']:,}", note)
        names = bool(d.get("names", True))
        if self._stats_names_toggle.isChecked() != names:
            self._stats_names_toggle.blockSignals(True)
            self._stats_names_toggle.setChecked(names)
            self._stats_names_toggle.blockSignals(False)
        self._stats_forget_btn.setEnabled(bool(d.get("kept")))

        people = d.get("people") or []
        shown = people if self._stats_whom_all else people[:_PEOPLE_PAGE]
        rows: List[Tuple[str, Dict[str, Any], Optional[int]]] = []
        for i, p in enumerate(shown):
            rows.append(("person", p, i + 1))
            rows += [("via", v, None) for v in p["via"]]
        self._stats_fill_whom_grid(rows)
        self._stats_whom_host.setVisible(bool(shown))
        self._stats_whom_empty.setVisible(not people)
        more = len(people) > _PEOPLE_PAGE
        self._stats_whom_more_btn.setVisible(more)
        self._stats_whom_more_btn.setText("Top 10" if self._stats_whom_all else "Show all")
        self._stats_whom_more_label.setText(f"{len(people)} people" if more else "")
        self._stats_whom_more_label.setVisible(more)

        shockers = d.get("shockers") or []
        self._stats_fill_shockers_grid(shockers)
        self._stats_shockers_head.setVisible(bool(shockers))
        self._stats_shockers_host.setVisible(bool(shockers))

    def _stats_fill_whom_grid(self, rows) -> None:
        grid = self._stats_whom_grid
        sig = tuple((kind, d.get("key") or d.get("via")) for kind, d, _n in rows)
        if sig != self._stats_whom_sig:
            self._stats_clear_grid(grid)
            self._stats_whom_cells = []
            if rows:
                for col, (text, icon) in enumerate(_COLUMNS):
                    grid.addWidget(_head(text, icon), 0, col)
                grid.setColumnStretch(len(_COLUMNS) - 1, 1)
            for r, (kind, _d, _n) in enumerate(rows):
                cells = [QLabel() for _ in _COLUMNS]
                for col, cell in enumerate(cells):
                    if kind == "via" or col == 0:
                        cell.setProperty("muted", "true")
                        self._repolish(cell)
                    grid.addWidget(cell, r + 1, col)
                self._stats_whom_cells.append(cells)
            self._stats_whom_sig = sig
        for cells, (kind, d, n) in zip(self._stats_whom_cells, rows):
            shocks, vibs, beeps, strongest, secs = op_cells(d["ops"])
            if kind == "person":
                texts = (f"{n}", d["name"], shocks, vibs, beeps, strongest, secs,
                         fmt_short(d["drive_s"]) if d["drive_s"] else "—",
                         _count(d["sets"]), fmt_day(d["last"]) if d["last"] else "—")
                tip = f"{d['name']}: {_ROLE_WORDS.get(d['role'], d['role'])}."
                if d["held"]:
                    tip += f" {d['held']:,} held back (not counted above)."
            else:
                texts = ("", f"   ↳ {d['label']}", shocks, vibs, beeps, strongest, secs,
                         "", "", "")
                tip = (f"{d['label']}: what came through it."
                       + (f" {d['held']:,} held back." if d["held"] else ""))
            for cell, text in zip(cells, texts):
                cell.setText(text)
            cells[1].setToolTip(tip)
            sv = d["ops"]["vibrate"]["max"]
            cells[5].setToolTip(f"Strongest shock {d['ops']['shock']['max'] or '—'}, "
                                f"strongest vibrate {sv or '—'}")

    def _stats_fill_shockers_grid(self, shockers: List[Dict[str, Any]]) -> None:
        grid = self._stats_shockers_grid
        sig = tuple(s["name"] for s in shockers)
        if sig != self._stats_shockers_sig:
            self._stats_clear_grid(grid)
            self._stats_shockers_cells = []
            if shockers:
                for col, (text, icon) in enumerate(_SHOCKER_COLUMNS):
                    grid.addWidget(_head(text, icon), 0, col)
                grid.setColumnStretch(len(_SHOCKER_COLUMNS) - 1, 1)
            for r, _s in enumerate(shockers):
                cells = [QLabel() for _ in _SHOCKER_COLUMNS]
                for col, cell in enumerate(cells):
                    grid.addWidget(cell, r + 1, col)
                self._stats_shockers_cells.append(cells)
            self._stats_shockers_sig = sig
        for cells, s in zip(self._stats_shockers_cells, shockers):
            for cell, text in zip(cells, (s["name"],) + op_cells(s["ops"])):
                cell.setText(text)

    def _stats_fill_worn(self) -> None:
        try:
            worn = self.controller.get_stats_worn() or {}
        except Exception:
            worn = {}
        life = dict((n, s) for n, s in worn.get("lifetime") or [])
        sess = dict((n, s) for n, s in worn.get("session") or [])
        rows = [(name, name, float(life.get(name, 0.0)), float(sess.get(name, 0.0)))
                for name in sorted(set(life) | set(sess), key=str.lower)]
        self._stats_worn_box.setVisible(bool(rows))
        if rows:
            self._stats_fill_table(self._stats_worn_table, rows, "")

    # ----------------------------------------------------------
    # Handlers
    # ----------------------------------------------------------

    def _on_stats_whom_span(self, index: int) -> None:
        self._stats_whom_span = index
        self._stats_mark_whom_span()
        self._stats_fill_whom()

    def _on_stats_whom_more(self) -> None:
        self._stats_whom_all = not self._stats_whom_all
        self._stats_fill_whom()

    def _on_stats_names(self, checked: bool) -> None:
        try:
            self.controller.set_stats_friend_names(bool(checked))
        except Exception as e:
            self.log_message(f"Keeping friends' names failed: {e}")

    def _on_stats_forget_names(self) -> None:
        confirm = QMessageBox.question(
            (getattr(self, "dialog_parent", None) or self.window), "Forget names",
            "Forget every friend's and web remote guest's name in your statistics? "
            "Their numbers stay, under A friend and Web remote, lifetime and every "
            "session. This cannot be undone. (The Log page keeps its own 30 days "
            "of who did what.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        try:
            self.controller.forget_stats_friend_names()
        except Exception as e:
            self.log_message(f"Forgetting names failed: {e}")
            return
        self._stats_fill_whom()
