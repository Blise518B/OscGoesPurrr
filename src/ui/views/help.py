"""Help: "Show me around" -- help mode on any page (ui/help_mode.py) and the
Help page's card for it.

Help mode is switched on from three places: F1, the status bar's Show me
around, and a page's Show me on the Help page (which opens that page
first). It explains the page on the page itself: the page's steps
(ui/page_steps.py) on a strip above it, and whatever the pointer rests on
lit with its hover explanation. Nothing here talks to the controller.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QPushButton, QStatusBar, QVBoxLayout, QWidget

from ui import page_steps
from ui.help_mode import HelpMode
from ui.layout_helpers import CardGrid, vbox as _vbox
from ui.widgets import Card as _Card


class _OnShow(QWidget):
    """A plain container that calls `on_show` each time it comes on screen."""

    def __init__(self, on_show):
        super().__init__()
        self._on_show = on_show

    def showEvent(self, ev) -> None:  # noqa: N802
        self._on_show()
        super().showEvent(ev)


class HelpMixin:

    # ---- help mode ---------------------------------------------------------
    def _help(self) -> HelpMode:
        mode = getattr(self, "_help_mode", None)
        if mode is None:
            mode = HelpMode(self._root_widget, self.main_stack, self._help_steps_for,
                            self._help_passthrough,
                            getattr(getattr(self, "live_theme", None), "add_root", None))
            self._help_mode = mode
        return mode

    def toggle_help_mode(self) -> None:
        self._help().toggle()

    def show_me_around(self, page: str = "") -> None:
        """Help mode on `page` (the one on screen when empty)."""
        if page:
            self.select_view(page)
        self._help().start()

    def _help_steps_for(self, page: QWidget):
        name = next((n for n, w in self.views.items() if w is page), "")
        return name, page_steps.for_page(name)

    def _help_passthrough(self, w: QWidget) -> bool:
        """The sidebar's pages keep working in help mode: it follows."""
        return any(w is b or b.isAncestorOf(w) for b in self.nav_buttons.values())

    def _add_help_button(self, bar: QStatusBar) -> None:
        """Show me around in the status bar, and F1 for it anywhere."""
        btn = QPushButton("?  Show me around")
        btn.setProperty("role", "sideSmall")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self.toggle_help_mode)
        self._explain(btn, "Show me around",
                      "Explains the page you're on, on the page itself: what you do "
                      "there, step by step, and what each control is when you point "
                      "at it. F1 does the same; Esc leaves.")
        bar.addPermanentWidget(btn)
        self._help_button = btn
        self._help_key = QShortcut(QKeySequence(Qt.Key_F1), self.window)
        self._help_key.activated.connect(self.toggle_help_mode)

    # ---- the Help page's card ----------------------------------------------
    def _build_help_tour(self, parent_layout: QVBoxLayout) -> QWidget:
        """Help's first card: a tile per page with steps, each with Show me.
        Pages switched off under Settings -> Features are left out (checked
        each time the card shows)."""
        card = _Card()
        lay = _vbox(15, 8)
        card.setLayout(lay)
        head = QLabel("Show me around")
        head.setObjectName("sectionTitle")
        lay.addWidget(head)
        intro = QLabel("Pick a page: it opens with what you do there, step by step. "
                       "Point at anything to see what it is. F1 does the same on any page.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self._help_tiles = _OnShow(self._refresh_help_tour)
        self._help_tiles.setLayout(_vbox(0, 0))
        lay.addWidget(self._help_tiles)
        self._help_tiles_for = None
        parent_layout.addWidget(card)
        return card

    def _help_tour_pages(self):
        allowed = getattr(self, "_feature_allows_view", lambda _n: True)
        out = []
        for name in self.views:
            steps = page_steps.for_page(name)
            if steps and allowed(name):
                out.append((name, steps))
        return out

    def _refresh_help_tour(self) -> None:
        pages = self._help_tour_pages()
        key = tuple(name for name, _ in pages)
        if key == self._help_tiles_for:
            return
        self._help_tiles_for = key
        lay = self._help_tiles.layout()
        while lay.count():
            item = lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        lay.addWidget(CardGrid([self._help_tile(n, s) for n, s in pages],
                               min_card_w=230, gap=8, max_cols=3))

    def _help_tile(self, name: str, steps) -> QWidget:
        tile = _Card()
        lay = _vbox(12, 4)
        tile.setLayout(lay)
        title = QLabel(name)
        f = QFont(title.font())
        f.setPixelSize(15)
        f.setBold(True)
        title.setFont(f)
        lay.addWidget(title)
        for n, step in enumerate(steps, 1):
            line = QLabel(f"{n}   {step.label}")
            line.setProperty("muted", "true")
            lay.addWidget(line)
        lay.addSpacing(6)
        show = QPushButton("Show me  ▸")
        show.setCursor(Qt.PointingHandCursor)
        show.clicked.connect(lambda _=False, page=name: self.show_me_around(page))
        self._explain(show, f"Show me {name}",
                      f"Opens {name} with its steps on top. Point at anything there "
                      "to see what it is; Esc leaves.")
        lay.addWidget(show, 0, Qt.AlignLeft)
        lay.addStretch(1)
        return tile
