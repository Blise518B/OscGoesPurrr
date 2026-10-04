"""Change the app's colour or mode while it runs — in small slices, never
a spike.

Qt re-styles everything beneath a widget whenever that widget's stylesheet
changes, and re-styling the whole app at once takes seconds (the app-level
`setStyleSheet` measured ~2.5 s on a five-toy rig). The Qt event loop also
hosts the routing tick, so those seconds would be a toy frozen at its last
level. Instead:

* The app-level stylesheet is set once, at launch, and never touched again.
* The UI registers SECTIONS ("roots"): the sidebar, each page, and on Home
  each toy's bar and each motor's chain block. Sections never contain one
  another, so re-styling one costs only that section — 5 to 30 ms.
* A colour change is applied to a section by giving it the new stylesheet
  as its own (it overrides the app's), and by swapping the colours its
  widgets copied into themselves (retint).
* Sections on screen go first, top to bottom with a short pause between
  them, so the change reads as a wave. Everything else follows a section
  per event-loop turn once the picker has been still for a moment — the
  routing tick runs in between, and a page you open is always done first.

Module state (the tokens, every `COLOR_*` copy) changes at once, inside
`theme.set_accent_hue` / `theme.set_mode`; it is only what is already
painted that trickles. A mode switch is the same sweep as a colour change:
a different stylesheet and a different set of colours to swap.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import shiboken6
from PySide6.QtCore import QElapsedTimer, QObject, QPoint, QTimer
from PySide6.QtWidgets import QLabel, QWidget

import retint
from ui import theme as _theme

# Work per event-loop turn before handing the loop back (ms). One section
# is never split, so a turn can run over by one section's cost.
_BUDGET_MS = 8
# Pause between two on-screen sections: long enough to read as a wave,
# short enough that a page of a dozen cards turns in a fifth of a second.
_WAVE_MS = 14
# Off-screen sections wait until the picker has been still this long, so
# dragging the slider only ever pays for what is visible.
_SETTLE_MS = 250


def _alive(w) -> bool:
    return w is not None and shiboken6.isValid(w)


class _At:
    """Which colours a section is currently wearing. A plain holder object
    on purpose: the table inside must not look like one of the widget's
    own colour copies to retint (it walks dicts, lists and tuples)."""
    __slots__ = ("table",)

    def __init__(self, table: Dict[str, str]):
        self.table = table


class LiveTheme(QObject):
    """The app's sections and the sweep that recolours them."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self._table: Dict[str, str] = dict(_theme.current_table())
        self._qss = ""          # no change yet: the app-level sheet is right
        self._roots: List[QWidget] = []
        self._pending: List[QWidget] = []
        self._loose_table = self._table
        self._listeners: List[Callable[[], None]] = []
        self._still = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._step)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_root(self, widget: Optional[QWidget]) -> None:
        """Register a section. It must not contain, or sit inside, another
        section. A section built after a colour change is given the
        override at once — it has not been polished yet, so that is free."""
        if not _alive(widget) or getattr(widget, "_live_at", None) is not None:
            return
        widget._live_at = _At(self._table)
        self._roots.append(widget)
        if self._qss:
            widget.setStyleSheet(self._qss)

    def on_change(self, callback: Callable[[], None]) -> None:
        """`callback()` runs right after the tokens changed — for the few
        things that are neither a stylesheet nor a stored colour (an icon
        drawn into a pixmap, say)."""
        self._listeners.append(callback)

    # ------------------------------------------------------------------
    # Changing the colour
    # ------------------------------------------------------------------

    def set_hue(self, hue) -> bool:
        """Turn the green to `hue` (None = the house green) and start the
        sweep. False when that is the colour already in use."""
        if not _theme.set_accent_hue(hue):
            return False
        self._changed()
        return True

    def set_mode(self, mode) -> bool:
        """Switch to the other mode and start the sweep. False when that
        is the mode already in use."""
        if not _theme.set_mode(mode):
            return False
        self._changed()
        return True

    def _changed(self) -> None:
        self._table = dict(_theme.current_table())
        # Once a section has an override it keeps one, even back at the
        # colour the app was launched with: CLEARING a widget's stylesheet
        # makes Qt restore a remembered font, and a nav entry that was
        # bold (active) at that moment stays bold for good.
        self._qss = _theme.build_qss()
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:
                pass
        self._still.restart()
        self._queue()

    def busy(self) -> bool:
        return bool(self._pending) or self._timer.isActive()

    def finish(self) -> None:
        """Apply everything still pending, now (tests; never the app)."""
        self._timer.stop()
        while self._pending:
            root = self._pending.pop(0)
            if _alive(root):
                self._apply(root)
        if self._loose_table is not self._table:
            self._sweep_loose()

    # ------------------------------------------------------------------
    # The sweep
    # ------------------------------------------------------------------

    def _queue(self) -> None:
        self._roots = [r for r in self._roots if _alive(r)]

        def where(root: QWidget):
            p = root.mapToGlobal(QPoint(0, 0))
            return (p.y(), p.x())

        todo = [r for r in self._roots if r._live_at.table is not self._table]
        self._pending = (sorted((r for r in todo if r.isVisible()), key=where)
                         + [r for r in todo if not r.isVisible()])
        self._timer.start(0)

    def _take(self) -> Optional[QWidget]:
        """The next section: one that is on screen if any is (so a page
        opened mid-sweep jumps the queue); an off-screen one only once the
        picker has been still for a moment."""
        self._pending = [r for r in self._pending if _alive(r)]
        for i, root in enumerate(self._pending):
            if root.isVisible():
                return self._pending.pop(i)
        if self._pending and self._still.elapsed() >= _SETTLE_MS:
            return self._pending.pop(0)
        return None

    def _step(self) -> None:
        clock = QElapsedTimer()
        clock.start()
        while self._pending:
            root = self._take()
            if root is None:                       # waiting for the picker
                self._timer.start(max(1, _SETTLE_MS - int(self._still.elapsed())))
                return
            visible = root.isVisible()
            self._apply(root)
            if visible:                            # the wave
                self._timer.start(_WAVE_MS)
                return
            if clock.elapsed() >= _BUDGET_MS:
                self._timer.start(0)
                return
        if self._loose_table is not self._table:
            self._sweep_loose()

    def _mapping(self, table: Dict[str, str]) -> Dict[str, str]:
        return {old: self._table[src] for src, old in table.items()
                if old != self._table[src]}

    def _apply(self, root: QWidget) -> None:
        mapping = self._mapping(root._live_at.table)
        root._live_at.table = self._table
        if root.styleSheet() != self._qss:
            root.setStyleSheet(self._qss)
        seen: set = set()
        retint.instance(root, mapping, seen)
        for child in root.findChildren(QWidget):
            self._retint_widget(child, mapping, seen)
        root.update()

    @staticmethod
    def _retint_widget(w: QWidget, mapping: Dict[str, str], seen: set) -> None:
        """One widget's own copies: its attributes, its inline stylesheet,
        and — for a label — colours written into its rich text. A widget
        marked `noRetint` shows colours that are NOT the current one on
        purpose (the picker's swatches) and repaints itself."""
        if w.property("noRetint"):
            return
        retint.instance(w, mapping, seen)
        sheet = w.styleSheet()
        if sheet:
            new = retint.text(sheet, mapping)
            if new != sheet:
                w.setStyleSheet(new)
        if isinstance(w, QLabel):
            text = w.text()
            if "#" in text:
                new = retint.text(text, mapping)
                if new != text:
                    w.setText(new)

    # ---- what is in no section: the containers between them ----

    def _sweep_loose(self) -> None:
        """The last step of a sweep, in one go: the widgets that belong to
        no section (the window, the stack, a page's scroll area, a toy's
        frame). They are few and carry no stylesheet of their own; the
        painted ones (the window ground, the toy frames) read their colour
        when they paint, so one repaint settles them."""
        roots = {id(r) for r in self._roots if _alive(r)}

        def in_section(w: QWidget) -> bool:
            while w is not None:
                if id(w) in roots:
                    return True
                w = w.parentWidget()
            return False

        mapping = self._mapping(self._loose_table)
        self._loose_table = self._table
        seen: set = set()
        retint.instance(self._window, mapping, seen)
        for w in self._window.findChildren(QWidget):
            if not in_section(w):
                self._retint_widget(w, mapping, seen)
        self._window.update()
