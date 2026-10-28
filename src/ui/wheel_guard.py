"""The scroll wheel scrolls pages; it never changes a setting.

Blise's rule (2026-10-27): scrolling a page -- with a mouse, or a VR
controller's stick through a desktop overlay -- must never change a value
just because the pointer passes over a control. So for every spin box,
slider, dropdown and tab bar in the app, the wheel goes on to the page
around it instead, whether or not the control has focus: in VR the control
you just set is still focused, and the next scroll would pass over it.
Scroll bars keep the wheel. A control that really should take it says so:
``widget.setProperty(WHEEL_ADJUSTS, True)``.

One event filter on the QApplication (`install`) covers every page, those
built later included -- a new setting needs nothing of its own. It costs
well under a microsecond per event. It also stops the wheel from handing
these controls keyboard focus (WheelFocus becomes StrongFocus when they
are polished).
"""

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox,
    QScrollBar, QTabBar,
)

WHEEL_ADJUSTS = "wheelAdjusts"
_GUARDED = (QAbstractSpinBox, QComboBox, QAbstractSlider, QTabBar)
_WHEEL = QEvent.Wheel
_POLISH = QEvent.Polish


def _guarded(obj) -> bool:
    return (isinstance(obj, _GUARDED) and not isinstance(obj, QScrollBar)
            and not obj.property(WHEEL_ADJUSTS))


def _scroll_area_of(widget):
    p = widget.parentWidget()
    while p is not None and not isinstance(p, QAbstractScrollArea):
        p = p.parentWidget()
    return p


def _to_page(widget, event) -> None:
    """The wheel, to the scroll area the control sits in (none: nowhere).
    Sent straight there rather than left for Qt to hand up the parents,
    which it only does for a real mouse's wheel -- the same either way, and
    never twice."""
    area = _scroll_area_of(widget)
    if area is None:
        return
    vp = area.viewport()
    pos = vp.mapFromGlobal(event.globalPosition().toPoint())
    QApplication.sendEvent(vp, QWheelEvent(
        QPointF(pos), event.globalPosition(), event.pixelDelta(), event.angleDelta(),
        event.buttons(), event.modifiers(), event.phase(), event.inverted(), event.source()))


class WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == _WHEEL:
            if _guarded(obj):
                _to_page(obj, event)
                event.accept()          # handled: Qt hands it on no further
                return True
        elif kind == _POLISH and _guarded(obj) and obj.focusPolicy() == Qt.WheelFocus:
            obj.setFocusPolicy(Qt.StrongFocus)
        return False


_guard = None


def install(app: QApplication) -> None:
    """Once per application; a second call does nothing."""
    global _guard
    if _guard is None:
        _guard = WheelGuard(app)
        app.installEventFilter(_guard)
