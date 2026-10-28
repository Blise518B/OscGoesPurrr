"""The Statistics page's own small widgets: a session row of the list, a
number tile, and the name field that tags who a session was with."""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QCompleter, QFrame, QLabel, QLineEdit, QPushButton, QWidget

from constants import BTN_HEIGHT_SMALL
from ui.layout_helpers import hbox, vbox
from ui.stats_charts import SpanStrip, Sparkline, fmt_clock, fmt_day, fmt_short


class NamesCompleter(QCompleter):
    """Suggests known names for the part after the last comma, so several
    people can be typed into one field."""

    def splitPath(self, path: str) -> List[str]:
        return [path.split(",")[-1].strip()]

    def pathFromIndex(self, index) -> str:
        done = self.widget().text().split(",")[:-1]
        return ", ".join([p.strip() for p in done if p.strip()]
                         + [super().pathFromIndex(index)])


class NamesEditor(QWidget):
    """A name field: "Who? Separate several names with commas", names used
    before suggested (for the part after the last comma), Tag / Cancel --
    Enter tags, Esc cancels. Hidden until `open()`."""

    def __init__(self, on_save: Callable[[], None], on_cancel: Callable[[], None],
                 what: str = "", parent: Optional[QWidget] = None,
                 margins=(0, 0, 0, 0)) -> None:
        super().__init__(parent)
        lay = hbox(0, 8)
        lay.setContentsMargins(*margins)
        self.setLayout(lay)
        self.what = QLabel(what)
        lay.addWidget(self.what)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Who? Separate several names with commas")
        self._model = QStringListModel([])
        completer = NamesCompleter(self._model, self.input)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.input.setCompleter(completer)
        self.input.returnPressed.connect(on_save)
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self.input)
        esc.setContext(Qt.WidgetShortcut)
        esc.activated.connect(on_cancel)
        lay.addWidget(self.input, 1)
        save = QPushButton("Tag")
        save.setMinimumHeight(BTN_HEIGHT_SMALL)
        save.clicked.connect(on_save)
        lay.addWidget(save)
        cancel = QPushButton("Cancel")
        cancel.setProperty("role", "ghost")
        cancel.setMinimumHeight(BTN_HEIGHT_SMALL)
        cancel.clicked.connect(on_cancel)
        lay.addWidget(cancel)
        self.setVisible(False)

    def text(self) -> str:
        return self.input.text()

    def open(self, names: List[str], prefill: str, what: Optional[str] = None) -> None:
        self._model.setStringList(list(names))
        if what is not None:
            self.what.setText(what)
        self.input.setText(prefill)
        self.setVisible(True)
        self.input.setFocus()
        self.input.selectAll()

    def dismiss(self) -> None:
        self.setVisible(False)
        self.input.clear()


class SessionRow(QFrame):
    """One clickable session in the list; a right-click asks `on_menu`
    for its menu at the pointer."""

    def __init__(self, on_click: Callable[[], None],
                 on_menu: Optional[Callable[[Any], None]] = None) -> None:
        super().__init__()
        self.setObjectName("statsSessionRow")
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        self._on_menu = on_menu
        lay = hbox(8, 10)
        lay.setContentsMargins(8, 4, 8, 4)
        self.setLayout(lay)
        # Date and the "recording" badge share one fixed-width cell, so
        # the running session's columns line up with the rest.
        when_cell = QWidget()
        when_cell.setFixedWidth(206)
        when_cell.setObjectName("statsWhenCell")
        when_lay = hbox(0, 6)
        when_cell.setLayout(when_lay)
        self.when = QLabel()
        self.badge = QLabel("recording")
        self.badge.setProperty("role", "pill")
        self.badge.setProperty("tone", "run")
        # Who it was with, in what the date leaves of the cell.
        self.who = QLabel()
        self.who.setProperty("hint", "true")
        when_lay.addWidget(self.when)
        when_lay.addWidget(self.badge)
        when_lay.addWidget(self.who)
        when_lay.addStretch(1)
        self._when_w = 206
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
                  self.active, self.thrusts, self.who, self.no_spark, chevron):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)

    def fill(self, row: Dict[str, Any]) -> None:
        live = row.get("kind") == "live"
        if live:
            self.when.setText(f"Now, since {fmt_clock(row.get('started_ts'))}")
        else:
            self.when.setText(f"{fmt_day(row.get('started_ts'))}  "
                              f"{fmt_clock(row.get('started_ts'))}")
        self.badge.setVisible(live)
        people = row.get("people") or []
        if people:
            used = self.when.sizeHint().width() + 6
            if live:
                used += self.badge.sizeHint().width() + 6
            text = self.who.fontMetrics().elidedText(
                ", ".join(people), Qt.ElideRight, max(0, self._when_w - used))
            self.who.setText(text)
        self.who.setVisible(bool(people))
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
        if people:
            tip = self.toolTip()
            self.setToolTip("With " + ", ".join(people)
                            + (f"<br><br>{tip}" if tip else ""))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self._on_click()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self._on_menu is not None:
            self._on_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)


class Tile(QFrame):
    """Caption over a bold value over a dim note."""

    def __init__(self, caption: str = "", big: bool = False) -> None:
        super().__init__()
        self.setObjectName("statsTile")
        lay = vbox(0, 1)
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
