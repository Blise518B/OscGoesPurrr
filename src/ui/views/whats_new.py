"""The "What's new" window, and the jumps its buttons make.

Opens once at launch after an update (controllers/whats_new_facade.py
decides) and from Settings → Quality of Life → What's new. Each change is
a title and a sentence or two; a change that lives somewhere in the app
gets a "Take me there" button, which closes the window, opens that page,
scrolls to the card and lights it up for a moment so the eye lands on it.

The content is `whats_new.py`; this module only draws it.
"""
from __future__ import annotations

import shiboken6
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QLabel, QPushButton, QSizePolicy, QWidget,
)

from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.text_helpers import html_escape as _html_escape

# Where a "Take me there" button leads: the page, and the attribute that
# holds the card to scroll to and light up ("" = the page is enough).
PLACES = {
    "appearance":   ("Settings", "_appearance_card"),
    "home":         ("Home", ""),
    "toy_presence": ("Settings", "_connection_card"),
    "toy_safety":   ("Settings", "_toy_safety_card"),
}
# The card a jump leads to is lit, goes out for a blink, and is lit again
# -- one beat is enough to pull the eye without being a flashing light.
# (ms from the jump, lit?)
_SPOT_BEATS = ((0, True), (450, False), (700, True), (2400, False))
_SPOT_MS = _SPOT_BEATS[-1][0]
# The lit card lands this far below the top of the page.
_SPOT_TOP_PX = 12
# The window is this wide; its height follows from the text.
_WIDTH_PX = 580
# The jump waits this long for a page that was never shown to lay itself
# out, so there is something to scroll to.
_SETTLE_MS = 30


class WhatsNewMixin:
    """Mixin: `show_whats_new` (controller facade), `open_whats_new` (the
    Settings button) and `reveal` (the jump). The host provides `views`,
    `select_view`, `_repolish` and `controller`."""

    def open_whats_new(self) -> None:
        """The newest notes this build carries, on request."""
        getter = getattr(self.controller, "get_whats_new", None)
        self.show_whats_new(getter() if callable(getter) else [])

    def show_whats_new(self, releases) -> None:
        """Controller facade: open the window for `releases` --
        `[(version, [(title, text, target), ...]), ...]`, newest first."""
        releases = [(v, items) for v, items in (releases or []) if items]
        if not releases or getattr(self, "_whats_new_dialog", None) is not None:
            return

        dlg = QDialog(getattr(self, "dialog_parent", None) or self.window)
        dlg.setWindowTitle("What's new")
        dlg.setWindowModality(Qt.WindowModal)
        lay = _vbox(20, 14)
        dlg.setLayout(lay)
        jumped = []

        for index, (version, items) in enumerate(releases):
            head = QLabel(
                f"What's new in v{_html_escape(str(version))}" if index == 0
                else f"Before that, in v{_html_escape(str(version))}")
            head.setObjectName("sectionTitle")
            head.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            lay.addWidget(head)
            for title, text, target in items:
                lay.addWidget(self._whats_new_row(dlg, title, text, target, jumped))

        lay.addSpacing(4)
        foot = _hbox(0, 12)
        again = QLabel("Find this again in Settings → Quality of Life.")
        again.setProperty("muted", "true")
        foot.addWidget(again, 1)
        done = QPushButton("Got it")
        done.setProperty("role", "primary")
        done.setDefault(True)
        done.clicked.connect(lambda _=False: dlg.accept())
        foot.addWidget(done)
        lay.addLayout(foot)

        def _closed(_result):
            self._whats_new_dialog = None
            # An update offer that arrived meanwhile waited its turn; after
            # a jump it also waits for the spotlight to finish.
            waiting = getattr(self, "_update_popup_waiting", None)
            self._update_popup_waiting = None
            if waiting:
                QTimer.singleShot(
                    _SPOT_MS + 400 if jumped else 0,
                    lambda: self.show_update_popup(*waiting))
        dlg.finished.connect(_closed)

        # The texts wrap, so the height depends on the width: fix the
        # width and take the height the layout needs at it. (Left to its
        # size hint, a dialog of wrapped labels comes out too tall and
        # spreads the slack between the rows.)
        lay.activate()
        dlg.setFixedSize(_WIDTH_PX, lay.totalHeightForWidth(_WIDTH_PX))

        self._whats_new_dialog = dlg
        # open(), not exec(): this is called from the controller's launch
        # callback, and a nested event loop would hold that up.
        dlg.open()

    def _whats_new_row(self, dlg: QDialog, title: str, text: str,
                       target: str, jumped: list) -> QWidget:
        row = QWidget()
        row_lay = _hbox(0, 14)
        row.setLayout(row_lay)
        col = _vbox(0, 2)
        name = QLabel(str(title))
        name.setObjectName("newsTitle")
        col.addWidget(name)
        body = QLabel(str(text))
        body.setWordWrap(True)
        body.setProperty("muted", "true")
        col.addWidget(body)
        row_lay.addLayout(col, 1)
        if self._can_reveal(target):
            go = QPushButton("Take me there")
            go.setProperty("role", "secondary")
            go.setCursor(Qt.PointingHandCursor)

            def _go(_=False, place=target):
                jumped.append(place)
                dlg.accept()
                self.reveal(place)
            go.clicked.connect(_go)
            row_lay.addWidget(go, 0, Qt.AlignVCenter)
        return row

    # ------------------------------------------------------------------
    # The jump
    # ------------------------------------------------------------------

    def _can_reveal(self, place: str) -> bool:
        page, _attr = PLACES.get(place, ("", ""))
        return bool(page) and page in (getattr(self, "views", None) or {})

    def reveal(self, place: str) -> bool:
        """Open the page a change lives on and, when it has a card of its
        own, scroll to it and light it up briefly. False for a place this
        build does not have."""
        if not self._can_reveal(place):
            return False
        page, attr = PLACES[place]
        self.select_view(page)
        card = getattr(self, attr, None) if attr else None
        if card is None:
            return True
        tabs = getattr(self, "_settings_tabs", None)
        if page == "Settings" and tabs is not None:
            tabs.setCurrentIndex(0)             # the cards are on General
        QTimer.singleShot(_SETTLE_MS, lambda: self._spotlight(card, page))
        return True

    def _spotlight(self, card: QWidget, page: str) -> None:
        if not shiboken6.isValid(card):
            return
        # Bring the card to the top of the page (as far as the page
        # scrolls), not merely into view at its bottom edge.
        scroll = (getattr(self, "views", None) or {}).get(page)
        inner = scroll.widget() if hasattr(scroll, "widget") else None
        bar = (scroll.verticalScrollBar()
               if hasattr(scroll, "verticalScrollBar") else None)
        if inner is not None and bar is not None:
            top = card.mapTo(inner, QPoint(0, 0)).y()
            bar.setValue(max(0, top - _SPOT_TOP_PX))
        for at_ms, lit in _SPOT_BEATS:
            if at_ms == 0:
                self._set_spot(card, lit)
            else:
                QTimer.singleShot(
                    at_ms, lambda lit=lit: self._set_spot(card, lit))

    def _set_spot(self, card: QWidget, on: bool) -> None:
        if not shiboken6.isValid(card):
            return
        card.setProperty("spot", "true" if on else "false")
        self._repolish(card)
