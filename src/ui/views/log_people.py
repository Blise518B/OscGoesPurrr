"""The log "by person": a row per person -- their name, what they did last
and how long ago -- and ▸ unfolds what they did, newest first, shocks
standing out. Used twice: the Friends page's log card (By person) and the
Log page's People card, where a click on a name shows only that person.

Fed primitive dicts (controller.get_friends_log_people / get_log_people,
event_log.Person.as_dict); never talks to the controller itself.
"""

import html
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QWidget

import constants
import event_log
from ui.icons import identity_color
from ui.layout_helpers import hbox, vbox

Explain = Callable[[QWidget, str, str], None]

# What each kind of person is called on hover (their row's name says who)
_ROLE_WORDS = {
    event_log.ROLE_FRIEND: "a friend",
    event_log.ROLE_ME: "you, as the Me row on the Friends page",
    event_log.ROLE_WEB: "someone on your web remote",
    event_log.ROLE_GROUP: "a group of friends",
    event_log.ROLE_AVATAR: "your own avatar's behaviours on the Shockers page",
    event_log.ROLE_YOU: "you, switching things on the page",
}


class _Elided(QLabel):
    """One line that ends in … instead of pushing the row wider."""

    def __init__(self, text: str = ""):
        super().__init__()
        self._full = text
        pol = self.sizePolicy()
        pol.setHorizontalPolicy(QSizePolicy.Ignored)
        self.setSizePolicy(pol)
        self._apply()

    def set_full_text(self, text: str) -> None:
        if text != self._full:
            self._full = text
            self._apply()

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._apply()

    def _apply(self) -> None:
        avail = max(24, self.width() - 2)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.ElideRight, avail))


def history_html(events: List[Dict[str, Any]], now: Optional[float] = None) -> str:
    """A person's recent entries as lines: the time, then the entry. A shock
    that reached a shocker is bold in the shockers' yellow; one held back
    is quiet. One OGP corrected on its way out has what went out and why
    muted on a line under it."""
    shock = identity_color("shock")
    muted, dim = constants.COLOR_MUTED, constants.COLOR_DIM
    lines = []
    for e in events:
        when = html.escape(event_log.when(e["t"], now))
        text = html.escape(e["text"])
        if e.get("stands_out"):
            text = f'<b style="color:{shock}">{text}</b>'
        elif e.get("shocker_op"):
            text = f'<span style="color:{shock}">{text}</span>'
        elif e.get("held"):
            text = f'<span style="color:{dim}">{text}</span>'
        lines.append(f'<span style="color:{muted}">{when}</span>&nbsp;&nbsp;{text}')
        note = e.get("correction")
        if note:
            lines.append(f'<span style="color:{muted}">{"&nbsp;" * 6}'
                         f'{html.escape(note)}</span>')
    return "<br>".join(lines)


class _PersonRow(QFrame):
    """One person: a header line that unfolds, and their history under it."""

    def __init__(self, who: str, on_toggle: Callable[[str], None],
                 on_pick: Optional[Callable[[str], None]], explain: Optional[Explain]):
        super().__init__()
        self.who = who
        self.setObjectName("logPerson")
        lay = vbox(8, 4)
        self.setLayout(lay)
        # Two lines: who (and their shocks), how long ago; under it what
        # they did last.
        head = QWidget()
        head.setObjectName("logPersonHead")
        head.setCursor(Qt.PointingHandCursor)
        head.mousePressEvent = lambda _ev: on_toggle(self.who)
        hv = vbox(0, 2)
        head.setLayout(hv)
        hl = hbox(0, 8)
        hv.addLayout(hl)
        self.caret = QLabel("▸")
        self.caret.setObjectName("logCaret")
        self.caret.setFixedWidth(12)
        hl.addWidget(self.caret)
        self.name = QLabel("")
        self.name.setObjectName("logPersonName")
        self.name.setTextFormat(Qt.PlainText)        # a stranger's nickname, never markup
        hl.addWidget(self.name)
        self.shocks = QLabel("")
        self.shocks.setObjectName("logShocks")
        hl.addWidget(self.shocks)
        hl.addStretch(1)
        self.ago = QLabel("")
        self.ago.setProperty("muted", "true")
        hl.addWidget(self.ago)
        line2 = hbox(0, 8)
        line2.addSpacing(20)
        self.last = _Elided("")
        self.last.setProperty("muted", "true")
        line2.addWidget(self.last, 1)
        hv.addLayout(line2)
        self.pick: Optional[QPushButton] = None
        if on_pick is not None:
            self.pick = QPushButton("Only them")
            self.pick.setProperty("role", "chip")
            self.pick.setCursor(Qt.PointingHandCursor)
            self.pick.clicked.connect(lambda _=False: on_pick(self.who))
            hl.addWidget(self.pick)
            if explain is not None:
                explain(self.pick, "Only them",
                        "Shows only this person's entries in the list beside it. Pick "
                        "Everyone in the Person filter to see everyone again.")
        lay.addWidget(head)
        self.body = QLabel("")
        self.body.setObjectName("logPersonBody")
        self.body.setTextFormat(Qt.RichText)
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setVisible(False)
        lay.addWidget(self.body)
        if explain is not None:
            explain(head, "A person in the log",
                    "Who it is, the last thing they did and how long ago. Click to "
                    "unfold what they did, newest first; shocks stand out in yellow.")
        self._shown: Any = None
        self._last_t = 0.0

    def refresh_ago(self, now: float) -> None:
        text = event_log.ago(now - self._last_t)
        if self.ago.text() != text:
            self.ago.setText(text)

    def set_person(self, p: Dict[str, Any], is_open: bool, now: Optional[float]) -> None:
        self._last_t = float(p["last"]["t"])
        if self.name.text() != p["name"]:
            self.name.setText(p["name"])
            self.name.setToolTip(f"{p['name']}: {_ROLE_WORDS.get(p['role'], '')}")
        n = int(p.get("shocks") or 0)
        text = f"{n} shock{'' if n == 1 else 's'}" if n else ""
        if self.shocks.text() != text:
            self.shocks.setText(text)
        self.shocks.setVisible(bool(n))
        self.last.set_full_text(p["last"]["text"])
        if self.ago.text() != p["ago"]:
            self.ago.setText(p["ago"])
        self.caret.setText("▾" if is_open else "▸")
        self.body.setVisible(is_open)
        if is_open:
            key = tuple((e["t"], e["text"]) for e in p["recent"])
            if key != self._shown:
                self._shown = key
                self.body.setText(history_html(p["recent"], now))


class PersonLog(QWidget):
    """Rows of people in the order given (most recently active first); each
    unfolds on a click and stays unfolded across refreshes."""

    def __init__(self, empty_text: str, on_pick: Optional[Callable[[str], None]] = None,
                 explain: Optional[Explain] = None):
        super().__init__()
        self._on_pick, self._explain = on_pick, explain
        self._lay = vbox(0, 6)
        self.setLayout(self._lay)
        self._rows: Dict[str, _PersonRow] = {}
        self._order: List[str] = []
        self._open: set = set()
        self._people: List[Dict[str, Any]] = []
        self._now: Optional[float] = None
        self._empty = QLabel(empty_text)
        self._empty.setProperty("muted", "true")
        self._empty.setWordWrap(True)
        self._lay.addWidget(self._empty)

    def people(self) -> List[str]:
        """Who has a row, in order."""
        return list(self._order)

    def is_open(self, who: str) -> bool:
        return who in self._open

    def refresh_ago(self, now: float) -> None:
        """Only "how long ago" -- it moves on while nothing new comes in."""
        for row in self._rows.values():
            row.refresh_ago(now)

    def toggle(self, who: str) -> None:
        (self._open.discard if who in self._open else self._open.add)(who)
        self.set_people(self._people, self._now)

    def set_people(self, people: List[Dict[str, Any]], now: Optional[float] = None) -> None:
        self._people, self._now = people, now
        order = [p["who"] for p in people]
        if order != self._order:
            self._order = order
            keep = {}
            while self._lay.count():             # rows are reused: taken out, not deleted
                self._lay.takeAt(0)
            for who in order:
                row = self._rows.get(who) or _PersonRow(who, self.toggle, self._on_pick,
                                                        self._explain)
                keep[who] = row
                self._lay.addWidget(row)
            for who, row in self._rows.items():
                if who not in keep:
                    row.hide()
                    row.setParent(None)
                    row.deleteLater()
            self._rows = keep
            self._lay.addWidget(self._empty)
            self._open &= set(order)
        for p in people:
            self._rows[p["who"]].set_person(p, p["who"] in self._open, now)
        self._empty.setVisible(not people)
