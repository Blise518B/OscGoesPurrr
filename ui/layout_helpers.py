"""Small Qt layout constructors used all over the UI code."""

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout


def vbox(margin: int = 0, spacing: int = 6) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def hbox(margin: int = 0, spacing: int = 6) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setContentsMargins(margin, margin, margin, margin)
    lay.setSpacing(spacing)
    return lay


def clear_layout(layout):
    """Remove and destroy every child of `layout`."""
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            # Hide before detaching: reparenting a still-visible child to
            # None can briefly realise it as a top-level window (a flash)
            # before deleteLater() destroys it. Hiding first keeps the
            # teardown invisible.
            w.hide()
            w.setParent(None)
            w.deleteLater()
        else:
            sub = item.layout()
            if sub is not None:
                clear_layout(sub)
                sub.deleteLater()
