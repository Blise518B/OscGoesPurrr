"""Hover explanations -- the app's only in-place help.

Rest the mouse on a control for Qt's standard ~0.7 s and its explanation
appears on its own, styled by the QToolTip rule in ui/theme.py. There is
no mode to switch on first: every explanation is always there, one
still pointer away.

An explanation is a bold title and a short body that may carry simple
HTML (<b>, <br>). Qt word-wraps rich-text tooltips at a comfortable
reading width (~380 px), so bodies are written as plain paragraphs.

`explain()` accepts a widget, a layout, or any mix of them:

* a widget gets the tip itself. Its children that have no tooltip of
  their own show it too -- Qt hands an unanswered tooltip request up to
  the parent -- so tipping a container covers a whole group of controls.
* a layout tips every widget currently in it (nested layouts included)
  that does not already carry a more specific tooltip. Rows are built
  label-first, so explaining a row once its controls are in it covers
  the label and the controls alike.
"""

from html import escape
from typing import Iterable, Union

from PySide6.QtWidgets import QLayout, QWidget

Target = Union[QWidget, QLayout, Iterable]


def tip_html(title: str, text: str) -> str:
    """The rich-text tooltip for one explanation. The title is escaped
    (it is plain text); the body is trusted HTML written in this repo."""
    return f"<b>{escape(str(title))}</b><br>{text}"


def _tip_layout(layout: QLayout, html: str) -> None:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        widget = item.widget()
        if widget is not None:
            if not widget.toolTip():
                widget.setToolTip(html)
            continue
        child = item.layout()
        if child is not None:
            _tip_layout(child, html)


def explain(target: Target, title: str, text: str) -> None:
    """Attach the explanation to `target` (see the module docstring)."""
    html = tip_html(title, text)
    if target is None:
        return
    if isinstance(target, QLayout):
        _tip_layout(target, html)
    elif isinstance(target, QWidget):
        target.setToolTip(html)
    else:
        for t in target:
            if isinstance(t, QLayout):
                _tip_layout(t, html)
            elif isinstance(t, QWidget):
                t.setToolTip(html)
