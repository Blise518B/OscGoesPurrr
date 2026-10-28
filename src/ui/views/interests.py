"""The "What are you here for?" window.

Opens once at launch (controllers/interests_facade.py decides) and from
Settings → Features → "Choose what you use…". One tick per thing someone
has or wants, starting from the switches as they are; Done sets the
feature switches, Skip (Cancel, from Settings) leaves them alone. While it
is open, "What's new" and an update offer wait their turn.

The content is `interests.py`; this module only draws it.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QPushButton, QSizePolicy

from ui.icons import page_icon
from ui.layout_helpers import vbox as _vbox, hbox as _hbox

# The window is this wide; its height follows from the text.
_WIDTH_PX = 520
# Each choice carries the icon its page has in the sidebar
# (ui/icons.identity_icon / page_icon), so the titles stay in one column.
_ICONS = {"feature_intiface": "toys", "feature_pishock": "shock",
          "feature_bhaptics": "suits", "feature_owo": "suits",
          "feature_friends": "friends", "feature_params": "params",
          "feature_statistics": "stats", "feature_osc_inspector": "inspector"}
_ICON_PX = 16
# A choice's hint starts under its title's text, past the box and its gap
# (QCheckBox::indicator in ui/theme.py, with its border and spacing), then
# the icon and the gap Qt leaves after it.
_HINT_INDENT_PX = 24 + _ICON_PX + 4


class _Hint(QLabel):
    """A choice's hint line; clicked, it ticks its box like the title does."""

    def __init__(self, text: str, on_click: Callable[[], None]):
        super().__init__(text)
        self._on_click = on_click
        self.setWordWrap(True)
        self.setProperty("muted", "true")
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._on_click()
            ev.accept()
        else:
            super().mousePressEvent(ev)


class InterestsMixin:
    """Mixin: `show_interests` (controller facade) and `open_interests`
    (the Settings button). The host provides `controller` and `window`,
    and `show_whats_new` / `show_update_popup` for what waited."""

    def open_interests(self) -> None:
        """The question again, on request, from the switches as they are."""
        getter = getattr(self.controller, "get_interests", None)
        self.show_interests(getter() if callable(getter) else [], False)

    def show_interests(self, groups, at_launch: bool = False) -> None:
        """Controller facade: open the window for `groups` --
        `[(group, [(feature, title, hint, on), ...]), ...]`. `at_launch`:
        asked by itself, so Skip (or closing it) is an answer too."""
        groups = [(g, items) for g, items in (groups or []) if items]
        if not groups or getattr(self, "_interests_dialog", None) is not None:
            return

        dlg = QDialog(getattr(self, "dialog_parent", None) or self.window)
        dlg.setWindowTitle("What are you here for?")
        dlg.setWindowModality(Qt.WindowModal)
        lay = _vbox(20, 6)
        dlg.setLayout(lay)

        head = QLabel("What are you here for?")
        head.setObjectName("sectionTitle")
        head.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        lay.addWidget(head)
        lead = QLabel("Tick what you'll use: those pages come on, the rest "
                      "stay out of your way.")
        lead.setWordWrap(True)
        lead.setProperty("muted", "true")
        lay.addWidget(lead)

        boxes = {}
        for group, items in groups:
            lay.addSpacing(8)
            cap = QLabel(str(group))
            cap.setObjectName("listDivider")
            lay.addWidget(cap)
            for feature, title, hint, on in items:
                box = QCheckBox(str(title))
                box.setObjectName("interestChoice")
                box.setChecked(bool(on))
                box.setCursor(Qt.PointingHandCursor)
                box.setIcon(page_icon(_ICONS.get(feature, ""), _ICON_PX))
                box.setIconSize(QSize(_ICON_PX, _ICON_PX))
                lay.addWidget(box)
                tip = _Hint(str(hint), lambda b=box: b.toggle())
                tip.setContentsMargins(_HINT_INDENT_PX, 0, 0, 2)
                lay.addWidget(tip)
                boxes[feature] = box

        lay.addSpacing(10)
        foot = _hbox(0, 10)
        later = QLabel("Change any of this later in Settings → Features.")
        later.setWordWrap(True)
        later.setProperty("muted", "true")
        foot.addWidget(later, 1)
        skip = QPushButton("Skip" if at_launch else "Cancel")
        skip.setProperty("role", "secondary")
        skip.clicked.connect(lambda _=False: dlg.reject())
        foot.addWidget(skip)
        done = QPushButton("Done")
        done.setProperty("role", "primary")
        done.setDefault(True)
        foot.addWidget(done)
        lay.addLayout(foot)

        answered = []

        def _done(_=False):
            answered.append(True)
            self.controller.set_interests(
                {feature: box.isChecked() for feature, box in boxes.items()})
            dlg.accept()
        done.clicked.connect(_done)

        def _closed(_result):
            self._interests_dialog = None
            if at_launch and not answered:
                self.controller.skip_interests()
            sync = getattr(self, "_sync_feature_toggles", None)
            if callable(sync):
                sync()
            # What waited its turn: "What's new" first (an update offer
            # then waits for that), else the offer.
            news = getattr(self, "_whats_new_waiting", None)
            self._whats_new_waiting = None
            offer = getattr(self, "_update_popup_waiting", None)
            if news:
                QTimer.singleShot(0, lambda: self.show_whats_new(news))
            elif offer:
                self._update_popup_waiting = None
                QTimer.singleShot(0, lambda: self.show_update_popup(*offer))
        dlg.finished.connect(_closed)

        # Wrapped texts: fix the width and take the height the layout
        # needs at it (see ui/views/whats_new.py).
        lay.activate()
        dlg.setFixedSize(_WIDTH_PX, lay.totalHeightForWidth(_WIDTH_PX))

        self._interests_dialog = dlg
        # open(), not exec(): called from the controller's launch callback.
        dlg.open()
