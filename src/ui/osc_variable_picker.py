"""Reusable "smart" OSC variable picker dialog.

A modal dialog that lists the live avatar parameters (from the shared
parameter_store) with search + live value updates, plus a manual-entry
escape hatch. Originally lived inside the Device Routing view; factored
out here so every place that needs to pick an OSC parameter — Device
Routing motors, SPS Sources contacts, anything future — shares one
implementation.

Usage:

    from ui.osc_variable_picker import open_osc_variable_picker
    open_osc_variable_picker(self.window, on_pick=lambda addr: ...)

`on_pick` is called once with the chosen parameter name (bare, exactly as
shown in the tree, or the raw manual text). The caller decides what to do
with it (append to a list, set a field, etc.). The dialog closes after a
pick.

Reading parameter_store directly is the sanctioned UI exception for live
debug / picker views (see ARCHITECTURE.md rule 1) — the picker is a
read-only live view, it never writes hardware or config.
"""

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QPushButton, QWidget,
)

from parameter_store import store
from ui.layout_helpers import vbox as _vbox, hbox as _hbox
from ui.widgets import ToggleSwitch, Card as _Card


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("muted", "true")
    lbl.setWordWrap(True)
    _repolish(lbl)
    return lbl


def open_osc_variable_picker(
    parent,
    on_pick: Callable[[str], None],
    *,
    title: str = "Add OSC Variable",
    subtitle: str = "Pick from live avatar parameters (double-click to add) "
                    "or enter one manually.",
    allow_wildcards: bool = True,
) -> None:
    """Open the variable picker modal. Calls `on_pick(name)` with the chosen
    parameter and closes. `allow_wildcards` only tweaks the manual-entry
    hint/placeholder — pass False where exact names are required (e.g. SPS
    source contacts, which are looked up by exact key)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(560, 600)
    dlg.setModal(True)

    lay = _vbox(12, 6)
    dlg.setLayout(lay)

    title_lbl = QLabel(title)
    title_lbl.setObjectName("sectionTitle")
    title_lbl.setAlignment(Qt.AlignHCenter)
    lay.addWidget(title_lbl)

    sub = QLabel(subtitle)
    sub.setProperty("muted", "true")
    sub.setAlignment(Qt.AlignHCenter)
    sub.setWordWrap(True)
    lay.addWidget(sub)

    search = QLineEdit()
    search.setPlaceholderText("Search avatar parameters...")
    lay.addWidget(search)

    show_all = ToggleSwitch("Include non-avatar parameters (OGB/SPS, system, etc.)")
    lay.addWidget(show_all)

    tree = QTreeWidget()
    tree.setColumnCount(2)
    tree.setHeaderLabels(["Parameter", "Value"])
    tree.setRootIsDecorated(False)
    tree.setAlternatingRowColors(False)
    tree.header().setStretchLastSection(False)
    tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
    tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
    lay.addWidget(tree, 1)

    empty_lbl = QLabel("No avatar parameters seen yet.")
    empty_lbl.setProperty("muted", "true")
    empty_lbl.setAlignment(Qt.AlignHCenter)
    empty_lbl.setVisible(False)
    lay.addWidget(empty_lbl)

    # Bottom card: manual entry + actions
    bottom = _Card()
    b_lay = _vbox(8, 6)
    bottom.setLayout(b_lay)

    if allow_wildcards:
        b_lay.addWidget(_muted("Or add manually (wildcards allowed, e.g. OGB/Tail/*):"))
        manual_placeholder = "e.g. OGB/Tail/Touch"
    else:
        b_lay.addWidget(_muted("Or add manually:"))
        manual_placeholder = "e.g. Contact/MyReceiver"

    manual_row = QWidget()
    m_lay = _hbox(0, 6)
    manual_row.setLayout(m_lay)
    manual_entry = QLineEdit()
    manual_entry.setPlaceholderText(manual_placeholder)
    m_lay.addWidget(manual_entry, 1)
    manual_add = QPushButton("Add Manual")
    manual_add.setProperty("role", "secondary")
    m_lay.addWidget(manual_add)
    b_lay.addWidget(manual_row)

    action_row = QWidget()
    a_lay = _hbox(0, 6)
    action_row.setLayout(a_lay)
    a_lay.addStretch(1)
    add_selected_btn = QPushButton("Add Selected")
    a_lay.addWidget(add_selected_btn)
    b_lay.addWidget(action_row)

    lay.addWidget(bottom)

    # ---- behavior ----
    state = {"last_keys": None, "last_query": None, "last_filtered": ()}

    def is_avatar_param(addr: str) -> bool:
        return not addr.startswith("OGB/")

    def fmt(val):
        if isinstance(val, float):
            return f"{val:.2f}"
        return str(val)

    def rebuild(filtered, params):
        tree.clear()
        for key in filtered:
            tree.addTopLevelItem(QTreeWidgetItem([key, fmt(params.get(key, ""))]))

    def update_values(filtered, params):
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            item.setText(1, fmt(params.get(item.text(0), "")))

    def refresh():
        params = store.get_all_parameters()
        if show_all.isChecked():
            keys = tuple(sorted(params.keys()))
        else:
            keys = tuple(sorted(k for k in params.keys() if is_avatar_param(k)))
        query = search.text().strip().lower()

        keys_changed = keys != state["last_keys"]
        query_changed = query != state["last_query"]
        state["last_keys"] = keys
        state["last_query"] = query

        if not keys:
            tree.clear()
            empty_lbl.setVisible(True)
            state["last_filtered"] = ()
            return

        empty_lbl.setVisible(False)
        if keys_changed or query_changed:
            filtered = tuple(k for k in keys if not query or query in k.lower())
            state["last_filtered"] = filtered
            rebuild(filtered, params)
        else:
            update_values(state["last_filtered"], params)

    def add_and_close(addr: str):
        try:
            on_pick(addr)
        finally:
            dlg.accept()

    def add_selected_action():
        items = tree.selectedItems()
        if items:
            add_and_close(items[0].text(0))

    def submit_manual():
        text = (manual_entry.text() or "").strip()
        if text:
            add_and_close(text)

    # Periodic value refresh while dialog is open.
    tick = QTimer(dlg)
    tick.setInterval(1500)
    tick.timeout.connect(refresh)
    tick.start()

    # Debounce search input.
    debounce = QTimer(dlg)
    debounce.setSingleShot(True)
    debounce.setInterval(180)
    debounce.timeout.connect(refresh)

    search.textChanged.connect(lambda _=None: debounce.start())
    show_all.toggled.connect(lambda _=False: refresh())

    tree.itemDoubleClicked.connect(lambda item, _col: add_and_close(item.text(0)))
    add_selected_btn.clicked.connect(add_selected_action)
    manual_entry.returnPressed.connect(submit_manual)
    manual_add.clicked.connect(submit_manual)

    refresh()
    search.setFocus()
    # Stop the refresh timers when the dialog closes and destroy it —
    # exec() only hides the dialog, so without this every open leaked a
    # live QDialog whose 1.5 s tick kept polling the parameter store and
    # rewriting an invisible tree for the rest of the session.
    dlg.finished.connect(tick.stop)
    dlg.finished.connect(debounce.stop)
    dlg.exec()
    dlg.deleteLater()
