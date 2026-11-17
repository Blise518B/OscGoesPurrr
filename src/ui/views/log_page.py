"""Log view -- who did what, person by person, for the last 30 days.

Mixin for ui_components.OscGoesPurrrUI, a sidebar entry right after
Statistics, shown while Friends or the Shockers are on (the two that log).
Everything friends, Me, web remote guests and groups did -- and you did to
them -- plus what your own avatar's behaviours fired on your shockers
("Your avatar"):

  * Filters: Person (everyone, everyone but your avatar, or one person),
    Time, kinds (toys, shocks, Avatar Remote, link, switches) and a search;
    Clear empties the whole log after asking.
  * People: a row per person within those filters -- their last action, how
    long ago, ▸ for what they did, Only them for just their entries
    (log_people.py).
  * Entries: the list itself, newest first, shocks standing out. An entry
    OGP corrected on its way out says what was asked, with what went out
    and why muted under it ("Cut to 1.2 s: their longest pulse").

The log stays on this PC (controllers/log_facade.py, event_log.py); it's
never sent to anyone. Everything goes through the controller.
"""

import time
from typing import Any, Dict, List

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QPushButton, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import constants
import event_log
from ui.frame_clock import when_on_screen
from ui.icons import identity_color, page_icon
from ui.layout_helpers import SIDE_GAP, SideBySide, hbox as _hbox, vbox as _vbox
from ui.views.log_people import PersonLog
from ui.widgets import Card as _Card

VIEW_NAME = "Log"
PEOPLE_W = 380                    # the People column, side by side
_REFRESH_MS = 1000
_BUSY_S = 1.5                     # while the log keeps changing: a redraw this often
EVERYONE, NOT_AVATAR = "", "__not_avatar__"     # the Person filter's first two
# An entry's correction (event_log.Event.correction), on its WHAT cell
CORRECTION_ROLE = Qt.UserRole + 1

# The kind filter's icon for each kind: one icon per thing, the same everywhere
KIND_ICONS = {event_log.TOYS: "toys", event_log.SHOCK: "shock", event_log.PARAMS: "params",
              event_log.LINK: "friends", event_log.SETTINGS: "settings"}
_KIND_TITLES = {event_log.TOYS: "Show toys", event_log.SHOCK: "Show shocks",
                event_log.PARAMS: "Show Avatar Remote", event_log.LINK: "Show the link",
                event_log.SETTINGS: "Show switches"}
_KIND_TIPS = {
    event_log.TOYS: "Shows driving toys: levels, auto modes, Override and strength.",
    event_log.SHOCK: "Shows shocks, vibrates and beeps, with holds, warnings and Stops.",
    event_log.PARAMS: "Shows Avatar Remote: toggles, buttons and sliders set on an avatar.",
    event_log.LINK: "Shows the link: friends coming online and going, requests and invites.",
    event_log.SETTINGS: "Shows switches: what each friend may use, Pause, groups and the "
                        "web remote.",
}


class CorrectionDelegate(QStyledItemDelegate):
    """The WHAT column: the entry as usual -- and where OGP sent something
    other than was asked, a second line under it, muted: what went out and
    why. The row is that much taller (_fill_log_table sets it)."""

    def __init__(self, table: QTableWidget):
        super().__init__(table)
        self._table = table

    def paint(self, painter, option, index) -> None:  # noqa: D102
        note = index.data(CORRECTION_ROLE)
        if not note:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        # the whole row's background (selection), then the entry in the top
        # line as every other row has it, then the correction under it
        style.drawPrimitive(QStyle.PE_PanelItemViewItem, opt, painter, widget)
        line = self._table.verticalHeader().defaultSectionSize()
        top = QStyleOptionViewItem(opt)
        top.rect = QRect(opt.rect.left(), opt.rect.top(), opt.rect.width(), line)
        style.drawControl(QStyle.CE_ItemViewItem, top, painter, widget)
        left = style.subElementRect(QStyle.SE_ItemViewItemText, top, widget).left()
        below = QRect(left, opt.rect.top() + line - 4, opt.rect.right() - left,
                      opt.rect.height() - line + 4)
        painter.save()
        painter.setPen(QColor(constants.COLOR_MUTED))
        painter.setFont(opt.font)
        painter.drawText(below, int(Qt.AlignLeft | Qt.AlignTop),
                         opt.fontMetrics.elidedText(str(note), Qt.ElideRight, below.width()))
        painter.restore()


class LogPageMixin:

    # ----------------------------------------------------------
    # View
    # ----------------------------------------------------------

    def _build_log_view(self, parent_layout: QVBoxLayout):
        title = QLabel(VIEW_NAME)
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)
        parent_layout.addWidget(self._muted_label(
            "Who did what, person by person: everything friends, Me and your web "
            "remote did - and you did to them - and what your own avatar fired on "
            "your shockers. Kept on this PC for 30 days, never sent to anyone."))
        self._log_shown: Any = None
        self._log_person = EVERYONE
        self._log_kinds = set(event_log.KINDS)
        parent_layout.addWidget(self._build_log_filters())

        self._log_people = PersonLog(
            "Nobody in the log for these filters yet.", on_pick=self._log_pick_person,
            explain=self._explain)
        left, llay = self._log_card("People")
        llay.addWidget(self._log_people)
        llay.addStretch(1)
        right, rlay = self._log_card("Entries")
        self._log_count = QLabel("")
        self._log_count.setProperty("muted", "true")
        self._log_count.setWordWrap(True)
        rlay.addWidget(self._log_count)
        rlay.addWidget(self._build_log_table(), 1)
        self._log_left = left
        self._log_main = SideBySide(left, right, PEOPLE_W + SIDE_GAP + 420, self._log_stacked)
        parent_layout.addWidget(self._log_main, 1)

        self._refresh_log_view()
        t = QTimer(self.window)
        t.setInterval(_REFRESH_MS)
        t.timeout.connect(when_on_screen(self, self._log_tick))
        t.start()
        self._log_timer = t

    def _log_card(self, heading: str):
        card = _Card()
        lay = _vbox(16, 8)
        card.setLayout(lay)
        hdr = QLabel(heading)
        hdr.setObjectName("sectionTitle")
        row = _hbox(0, 8)
        row.addWidget(hdr)
        row.addStretch(1)
        lay.addLayout(row)
        return card, lay

    def _build_log_filters(self) -> QWidget:
        card = _Card()
        lay = _vbox(16, 8)
        card.setLayout(lay)
        row = _hbox(0, 8)
        row.addWidget(QLabel("Person"))
        self._log_person_box = QComboBox()
        self._log_person_box.setMinimumWidth(200)
        self._log_person_box.currentIndexChanged.connect(self._on_log_person_box)
        self._explain(self._log_person_box, "Person",
                      "Shows everyone, everyone but your avatar's own behaviours, or just "
                      "one person - a friend, Me, someone on your web remote, a group.")
        row.addWidget(self._log_person_box)
        row.addSpacing(8)
        row.addWidget(QLabel("Time"))
        self._log_span_box = QComboBox()
        spans = self.controller.get_log_spans()
        self._log_span_box.addItems(spans)
        self._log_span_box.setCurrentIndex(len(spans) - 1)
        self._log_span_box.currentIndexChanged.connect(lambda _i: self._refresh_log_view())
        self._explain(self._log_span_box, "Time",
                      "How far back the list goes: the last hour, today, the last 7 days "
                      "or everything kept (30 days).")
        row.addWidget(self._log_span_box)
        row.addSpacing(8)
        self._log_search = QLineEdit()
        self._log_search.setPlaceholderText("Search: a name, a shocker, a toy…")
        self._log_search.setClearButtonEnabled(True)
        self._log_search.setMinimumWidth(180)
        self._log_search.textChanged.connect(lambda _t: self._refresh_log_view())
        self._explain(self._log_search, "Search the log",
                      "Shows only entries with all of these words, in the entry or the "
                      "person's name - a shocker's name, a toy, \"held back\".")
        row.addWidget(self._log_search, 1)
        clear = QPushButton("Clear log")
        clear.setProperty("role", "danger")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._confirm_clear_log)
        self._explain(clear, "Clear log",
                      "Deletes the whole log on this PC, every day of it, after asking. "
                      "It can't be undone.")
        row.addWidget(clear)
        lay.addLayout(row)

        chips = _hbox(0, 6)
        chips.addWidget(QLabel("Show"))
        self._log_kind_chips: Dict[str, QPushButton] = {}
        for k in self.controller.get_log_kinds():
            b = QPushButton(k["label"])
            b.setCheckable(True)
            b.setChecked(True)
            b.setProperty("role", "logKind")
            b.setCursor(Qt.PointingHandCursor)
            b.setIcon(page_icon(KIND_ICONS.get(k["key"], ""), 14))
            b.setIconSize(QSize(14, 14))
            b.toggled.connect(lambda on, key=k["key"]: self._on_log_kind(key, on))
            self._explain(b, _KIND_TITLES.get(k["key"], f"Show {k['label']}"),
                          f"{_KIND_TIPS.get(k['key'], '')} Click to leave them out of the "
                          "list, again to bring them back.")
            self._log_kind_chips[k["key"]] = b
            chips.addWidget(b)
        chips.addStretch(1)
        lay.addLayout(chips)
        theme = getattr(self, "live_theme", None)
        if theme is not None:                  # the icons are drawn: redraw with the colours
            theme.on_change(self._log_redraw_icons)
        self._log_fill_person_box([])
        return card

    def _build_log_table(self) -> QTableWidget:
        t = QTableWidget(0, 3)
        t.setHorizontalHeaderLabels(["WHEN", "WHO", "WHAT"])
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setAlternatingRowColors(True)
        t.setWordWrap(False)
        t.setShowGrid(False)
        t.setIconSize(QSize(14, 14))
        head = t.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        t.setMinimumHeight(420)
        t.setItemDelegateForColumn(2, CorrectionDelegate(t))
        self._explain(t, "Entries",
                      "The log itself, newest first: when, who, and what happened. Shocks "
                      "that reached a shocker stand out in yellow; what was held back is "
                      "greyed, with why. Where OGP sent less than was asked - a limit, the "
                      "longest pulse - or stretched a warning, the line under it says so.")
        self._log_table = t
        return t

    def _log_stacked(self, stacked: bool, width: int) -> None:
        w = max(PEOPLE_W, width) if stacked else PEOPLE_W
        if self._log_left.minimumWidth() != w or self._log_left.maximumWidth() != w:
            self._log_left.setFixedWidth(w)

    # ----------------------------------------------------------
    # Filters
    # ----------------------------------------------------------

    def _log_filters(self) -> Dict[str, Any]:
        person = self._log_person
        return {"person": None if person in (EVERYONE, NOT_AVATAR) else person,
                "kinds": sorted(self._log_kinds),
                "span": self._log_span_box.currentText(),
                "text": self._log_search.text().strip(),
                "hide_avatar": person == NOT_AVATAR}

    def _on_log_kind(self, key: str, on: bool) -> None:
        (self._log_kinds.add if on else self._log_kinds.discard)(key)
        self._refresh_log_view()

    def _on_log_person_box(self, _i: int) -> None:
        who = self._log_person_box.currentData()
        self._log_person = who if isinstance(who, str) else EVERYONE
        self._refresh_log_view()

    def _log_pick_person(self, who: str) -> None:
        """A People row's Only them."""
        self._log_person = who
        self._refresh_log_view(force=True)

    def _log_fill_person_box(self, people: List[Dict[str, Any]]) -> None:
        """Everyone, everyone but your avatar, then each person -- the one
        picked stays picked (and listed) even when the filters leave them out."""
        box = self._log_person_box
        items = [("Everyone", EVERYONE), ("Everyone but your avatar", NOT_AVATAR)]
        items += [(p["name"], p["who"]) for p in people]
        if self._log_person not in [w for _n, w in items]:
            items.append((getattr(self, "_log_person_name", "") or self._log_person,
                          self._log_person))
        key = tuple(items)
        if key != getattr(self, "_log_person_items", None):
            self._log_person_items = key
            box.blockSignals(True)
            box.clear()
            for name, who in items:
                box.addItem(name, who)
            box.blockSignals(False)
        idx = box.findData(self._log_person)
        if idx >= 0 and idx != box.currentIndex():
            box.blockSignals(True)
            box.setCurrentIndex(idx)
            box.blockSignals(False)

    def _confirm_clear_log(self) -> None:
        box = QMessageBox(
            QMessageBox.Question, "Clear log",
            "Delete the whole log on this PC - every entry of the last 30 days? "
            "It can't be undone.",
            QMessageBox.Yes | QMessageBox.No,
            getattr(self, "dialog_parent", None) or self.window)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() == QMessageBox.Yes:
            self.controller.clear_log()
            self._refresh_log_view(force=True)

    def _log_redraw_icons(self) -> None:
        for key, b in getattr(self, "_log_kind_chips", {}).items():
            b.setIcon(page_icon(KIND_ICONS.get(key, ""), 14))
        self._log_shown = None            # the list's colours and icons too, next tick

    # ----------------------------------------------------------
    # Refresh
    # ----------------------------------------------------------

    def _log_tick(self) -> None:
        page = self.views.get(VIEW_NAME) if hasattr(self, "views") else None
        if page is None or not page.isVisible():
            return
        self._refresh_log_view()

    def _refresh_log_view(self, force: bool = False) -> None:
        """Redraw when the filters or the log changed. The Qt loop also runs
        the routing tick, so while the log is busy (a friend dragging a
        slider changes it many times a second) the list follows at most
        every _BUSY_S; "3 min ago" moves on by itself in between."""
        if not hasattr(self, "_log_table"):
            return
        f = self._log_filters()
        now = time.time()
        filters = tuple(sorted(f.items(), key=str))
        sig = (self.controller.get_log_version(), filters)
        last = self._log_shown
        if not force and last is not None:
            if sig == last[0]:
                self._log_people.refresh_ago(now)
                return
            if filters == last[0][1] and now - last[1] < _BUSY_S:
                self._log_people.refresh_ago(now)
                return
        self._log_shown = (sig, now)
        got = self.controller.get_log_page(**f)
        people = got["people"]
        if f["person"] is not None:
            match = next((p for p in people if p["who"] == f["person"]), None)
            if match is not None:
                self._log_person_name = match["name"]
        self._log_fill_person_box(people)
        shown = people if f["person"] is None else [p for p in people if p["who"] == f["person"]]
        self._log_people.set_people(shown, now)
        self._fill_log_table(got["events"], now)
        if not got.get("loaded", True):
            text = "Reading the log…"
        elif got["total"] > got["shown"]:
            text = (f"The newest {got['shown']:,} of {got['total']:,} entries - narrow it "
                    "down with the filters above.")
        else:
            n = got["total"]
            text = f"{n:,} entr{'y' if n == 1 else 'ies'}" if n else (
                "Nothing here yet for these filters. Friends driving you, you driving "
                "them and your avatar's shocker behaviours all land here.")
        self._log_count.setText(text)

    def _fill_log_table(self, events: List[Dict[str, Any]], now: float) -> None:
        t = self._log_table
        shock = QColor(identity_color("shock"))
        dim = QColor(constants.COLOR_DIM)
        bold = QFont(t.font())
        bold.setBold(True)
        icons = {k: page_icon(v, 14) for k, v in KIND_ICONS.items()}
        line = t.verticalHeader().defaultSectionSize()
        two_lines = line + t.fontMetrics().height()
        t.setUpdatesEnabled(False)
        try:
            t.setRowCount(len(events))
            for r, e in enumerate(events):
                note = e.get("correction") or ""
                want = two_lines if note else line
                if t.rowHeight(r) != want:
                    t.setRowHeight(r, want)
                cells = (event_log.when(e["t"], now), e["name"], e["text"])
                for c, text in enumerate(cells):
                    item = t.item(r, c)
                    if item is None:
                        item = QTableWidgetItem()
                        t.setItem(r, c, item)
                    item.setText(text)
                    item.setFont(bold if e["stands_out"] and c == 2 else t.font())
                    if e["stands_out"] or (e["shocker_op"] and c == 2):
                        item.setForeground(QBrush(shock))
                    elif e["held"]:
                        item.setForeground(QBrush(dim))
                    else:
                        item.setData(Qt.ForegroundRole, None)
                    if c == 2:
                        item.setIcon(icons.get(e["kind"]) or icons[event_log.LINK])
                        item.setData(CORRECTION_ROLE, note or None)
                        item.setToolTip(e["text"] + (f"\n{note}" if note else "")
                                        + (f"\nHeld back: {e['held']}" if e["held"] else ""))
        finally:
            t.setUpdatesEnabled(True)
