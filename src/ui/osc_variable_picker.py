"""Reusable "smart" OSC variable picker dialog.

A modal dialog that lists the live avatar parameters (from the shared
parameter_store) with search + live value updates, plus a manual-entry
escape hatch. Originally lived inside the Device Routing view; factored
out here so every place that needs to pick an OSC parameter — Device
Routing motors, SPS Sources contacts, the Shockers behaviours, anything
future — shares one implementation.

Usage:

    from ui.osc_variable_picker import open_osc_variable_picker
    open_osc_variable_picker(self.window, on_pick=lambda addr: ...,
                             mapped=[...], settings=self.controller)

`on_pick` is called once with the chosen parameter name (bare, exactly as
shown in the tree, or the raw manual text). The caller decides what to do
with it (append to a list, set a field, etc.). The dialog closes after a
pick.

Filters (param_filters.py): under the search box a chip per group of
well-known parameters on this avatar, with its count -- a lit chip hides
its group, *Show everything* turns them all off. The chips are remembered
once for every picker (the app setting param_filters.SETTING_KEY, through
`settings` -- anything with get_app_setting / set_app_setting, i.e. the
controller). Nothing is lost: a parameter in `mapped` (what the caller
already has mapped) is never hidden, and a search also finds hidden ones,
listed under "Hidden by filters". `keep` names groups this picker always
shows (the Shockers' PhysBone states); `first` groups it lists before
everything else, each under its own heading (the Shockers' ShockOSC).

Reading parameter_store directly is the sanctioned UI exception for live
debug / picker views (see ARCHITECTURE.md rule 1) — the picker is a
read-only live view, it never writes hardware or config.
"""

from typing import Callable, Dict, Iterable, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QPushButton, QWidget,
)

import param_filters as pf
from parameter_store import store
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, FlowLayout
from ui.widgets import Card as _Card

DEFAULT_SUBTITLE = ("Pick from live avatar parameters (double-click to add) "
                    "or enter one manually.")

# A tree row's parameter name; a heading ("Hidden by filters") has none.
_NAME_ROLE = Qt.UserRole + 1
# A heading's part of the list: "first", "shown" or "hidden".
_PART_ROLE = Qt.UserRole + 2


def _repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


def _muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("muted", "true")
    lbl.setWordWrap(True)
    _repolish(lbl)
    return lbl


def _fmt(val) -> str:
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)


class OscVariablePicker(QDialog):
    """The picker itself. `open_osc_variable_picker` runs it modally;
    tests build it directly (and `refresh(params)` it with their own)."""

    def __init__(self, parent, on_pick: Callable[[str], None], *,
                 title: str = "Add OSC Variable",
                 subtitle: str = DEFAULT_SUBTITLE,
                 allow_wildcards: bool = True,
                 mapped: Iterable[str] = (),
                 settings=None,
                 keep: Iterable[str] = (),
                 first: Iterable[str] = ()):
        super().__init__(parent)
        self._on_pick = on_pick
        self._settings = settings
        self._mapped = tuple(m for m in (mapped or ()) if m)
        self._is_mapped = pf.mapped_matcher(self._mapped)
        self._first = tuple(dict.fromkeys(first or ()))
        # a group listed first needs no chip: it is never hidden here
        self._keep = frozenset(keep or ()) | frozenset(self._first)
        saved = None
        if settings is not None:
            try:
                saved = settings.get_app_setting(pf.SETTING_KEY, {})
            except Exception:
                saved = None
        self._hidden = set(pf.hidden_from_setting(saved))
        self._last = None             # (names, query, hidden) of the tree as built
        self._params: Dict[str, object] = {}

        self.setWindowTitle(title)
        self.setModal(True)
        self._size_to_screen(parent)

        lay = _vbox(12, 6)
        self.setLayout(lay)

        title_lbl = QLabel(title)
        title_lbl.setObjectName("sectionTitle")
        title_lbl.setAlignment(Qt.AlignHCenter)
        lay.addWidget(title_lbl)

        sub = QLabel(subtitle)
        sub.setProperty("muted", "true")
        sub.setAlignment(Qt.AlignHCenter)
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search avatar parameters...")
        lay.addWidget(self.search)

        # The chips: "Hide:" then one per group this avatar has.
        self.chip_row = QWidget()
        flow = FlowLayout(margin=0, h_spacing=6, v_spacing=6)
        self.chip_row.setLayout(flow)
        hide_lbl = _muted("Hide:")
        hide_lbl.setWordWrap(False)
        hide_lbl.setFixedHeight(24)          # a chip's height, so the text lines up
        hide_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        hide_lbl.setToolTip("Lit chips hide their parameters from this list. "
                            "A search still finds them.")
        flow.addWidget(hide_lbl)
        self.chips: Dict[str, QPushButton] = {}
        for g in pf.GROUPS:
            if g.key in self._keep:
                continue
            b = QPushButton(g.label)
            b.setCheckable(True)
            b.setChecked(g.key in self._hidden)
            b.setProperty("role", "chip")
            b.setProperty("filter", "true")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{g.tip} Lit: hidden from this list (a search still "
                         "finds them).")
            b.toggled.connect(lambda on, k=g.key: self._set_hidden(k, on))
            b.setVisible(False)
            flow.addWidget(b)
            self.chips[g.key] = b
        self.show_all_btn = QPushButton("Show everything")
        self.show_all_btn.setProperty("role", "ghost")
        self.show_all_btn.setCursor(Qt.PointingHandCursor)
        self.show_all_btn.setToolTip("Turn every filter off: list every parameter "
                                     "the avatar sends.")
        self.show_all_btn.clicked.connect(lambda _=False: self.show_everything())
        flow.addWidget(self.show_all_btn)
        lay.addWidget(self.chip_row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Parameter", "Value"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        lay.addWidget(self.tree, 1)

        self.empty_lbl = QLabel("No avatar parameters seen yet.")
        self.empty_lbl.setProperty("muted", "true")
        self.empty_lbl.setAlignment(Qt.AlignHCenter)
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setVisible(False)
        lay.addWidget(self.empty_lbl)

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
        self.manual_entry = QLineEdit()
        self.manual_entry.setPlaceholderText(manual_placeholder)
        m_lay.addWidget(self.manual_entry, 1)
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

        # Periodic value refresh while the dialog is open.
        self._tick = QTimer(self)
        self._tick.setInterval(1500)
        self._tick.timeout.connect(lambda: self.refresh())
        # Debounce search input.
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(lambda: self.refresh())

        self.search.textChanged.connect(lambda _=None: self._debounce.start())
        self.tree.itemDoubleClicked.connect(lambda item, _col: self._pick_item(item))
        add_selected_btn.clicked.connect(self._add_selected)
        self.manual_entry.returnPressed.connect(self._submit_manual)
        manual_add.clicked.connect(self._submit_manual)
        # Stop the timers when the dialog closes -- exec() only hides it.
        self.finished.connect(self._tick.stop)
        self.finished.connect(self._debounce.stop)

    # ---- size ----

    def _size_to_screen(self, parent) -> None:
        w, h = 620, 780
        screen = parent.screen() if parent is not None and hasattr(parent, "screen") else None
        if screen is None:
            screen = self.screen()
        if screen is not None:
            h = min(h, max(480, screen.availableGeometry().height() - 80))
        self.resize(w, h)

    # ---- filters ----

    def hidden_groups(self) -> frozenset:
        return frozenset(self._hidden)

    def _set_hidden(self, key: str, on: bool) -> None:
        if (key in self._hidden) == bool(on):
            return
        if on:
            self._hidden.add(key)
        else:
            self._hidden.discard(key)
        self._save()
        self.refresh(self._params)

    def show_everything(self) -> None:
        """Every chip off (a group this picker always shows keeps what was
        saved for the other pickers)."""
        self._hidden &= self._keep
        for b in self.chips.values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        self._save()
        self.refresh(self._params)

    def _save(self) -> None:
        if self._settings is None:
            return
        try:
            self._settings.set_app_setting(pf.SETTING_KEY, pf.setting_from_hidden(self._hidden))
        except Exception as e:      # a settings hiccup never breaks picking
            print(f"Picker filters: could not save ({e})")

    # ---- the list ----

    def refresh(self, params: Optional[Dict[str, object]] = None) -> None:
        """Re-read the parameters (from the store unless given) and bring
        the chips and the tree up to date; values only, when nothing else
        changed."""
        self._params = dict(store.get_all_parameters() if params is None else params)
        names = tuple(sorted(self._params))
        query = self.search.text().strip()
        result = pf.split(names, self._hidden, mapped=self._mapped, keep=self._keep,
                          first=self._first, query=query)
        self._update_chips(result.counts)

        state = (names, query.lower(), frozenset(self._hidden))
        if state != self._last:
            self._last = state
            self._rebuild(result)
        else:
            self._update_values()
        self._update_empty(names, result, query)

    def _update_chips(self, counts: Dict[str, int]) -> None:
        any_lit = False
        for key, b in self.chips.items():
            n = counts.get(key, 0)
            b.setText(f"{pf.BY_KEY[key].label} · {n}")
            b.setVisible(n > 0)
            any_lit = any_lit or (n > 0 and b.isChecked())
        self.chip_row.setVisible(any(counts.get(k, 0) for k in self.chips))
        self.show_all_btn.setEnabled(any_lit)

    def _row(self, name: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([name, _fmt(self._params.get(name, ""))])
        item.setData(0, _NAME_ROLE, name)
        if self._is_mapped(name):
            item.setToolTip(0, "Already mapped here - the filters never hide it.")
        return item

    def _heading(self, text: str, part: str, tip: str) -> None:
        head = QTreeWidgetItem([text, ""])
        head.setFlags(Qt.ItemIsEnabled)
        head.setData(0, _PART_ROLE, part)
        font = head.font(0)
        font.setBold(True)
        head.setFont(0, font)
        head.setToolTip(0, tip)
        self.tree.addTopLevelItem(head)
        head.setFirstColumnSpanned(True)

    def _rebuild(self, result: pf.Split) -> None:
        self.tree.clear()
        for key, names in result.first:
            group = pf.BY_KEY[key]
            self._heading(f"{group.label} ({len(names)})", "first", group.tip)
            for name in names:
                self.tree.addTopLevelItem(self._row(name))
        if result.first and result.shown:
            self._heading("Everything else", "shown",
                          "The avatar's other parameters, as the chips let through.")
        for name in result.shown:
            self.tree.addTopLevelItem(self._row(name))
        if result.hidden:
            self._heading(f"Hidden by filters ({len(result.hidden)})", "hidden",
                          "Parameters the lit chips hide that match your search. "
                          "Double-click one to pick it anyway.")
            for name in result.hidden:
                self.tree.addTopLevelItem(self._row(name))

    def _update_values(self) -> None:
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            name = item.data(0, _NAME_ROLE)
            if name is not None:
                item.setText(1, _fmt(self._params.get(name, "")))

    def _update_empty(self, names, result: pf.Split, query: str) -> None:
        if not names:
            text = "No avatar parameters seen yet."
        elif result.first or result.shown or result.hidden:
            text = ""
        elif query:
            text = "Nothing matches that search."
        else:
            text = ("The filters hide every parameter here. Search for one, or "
                    "Show everything.")
        self.empty_lbl.setText(text)
        self.empty_lbl.setVisible(bool(text))
        self.tree.setVisible(bool(result.first or result.shown or result.hidden))

    def listed(self) -> Dict[str, list]:
        """What the tree lists, for tests: {"shown": [...], "hidden": [...]}
        -- and "first": [...] (in order) when a group is listed first."""
        out = {"shown": [], "hidden": []}
        part = "shown"
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            name = item.data(0, _NAME_ROLE)
            if name is None:
                part = item.data(0, _PART_ROLE) or "hidden"
                out.setdefault(part, [])
            else:
                out[part].append(name)
        return out

    def headings(self) -> list:
        """The tree's headings, in order (for tests)."""
        return [self.tree.topLevelItem(i).text(0)
                for i in range(self.tree.topLevelItemCount())
                if self.tree.topLevelItem(i).data(0, _NAME_ROLE) is None]

    # ---- picking ----

    def _pick(self, addr: str) -> None:
        try:
            self._on_pick(addr)
        finally:
            self.accept()

    def _pick_item(self, item: QTreeWidgetItem) -> None:
        name = item.data(0, _NAME_ROLE)
        if name is not None:
            self._pick(name)

    def _add_selected(self) -> None:
        for item in self.tree.selectedItems():
            if item.data(0, _NAME_ROLE) is not None:
                self._pick_item(item)
                return

    def _submit_manual(self) -> None:
        text = (self.manual_entry.text() or "").strip()
        if text:
            self._pick(text)

    def start(self) -> None:
        """Fill the list and start the live refresh."""
        self.refresh()
        self._tick.start()
        self.search.setFocus()


def open_osc_variable_picker(
    parent,
    on_pick: Callable[[str], None],
    *,
    title: str = "Add OSC Variable",
    subtitle: str = DEFAULT_SUBTITLE,
    allow_wildcards: bool = True,
    mapped: Iterable[str] = (),
    settings=None,
    keep: Iterable[str] = (),
    first: Iterable[str] = (),
) -> None:
    """Open the variable picker modal. Calls `on_pick(name)` with the chosen
    parameter and closes. `allow_wildcards` only tweaks the manual-entry
    hint/placeholder — pass False where exact names are required (e.g. SPS
    source contacts, which are looked up by exact key). `mapped`: what the
    caller already has mapped (bare names or globs) -- never hidden by the
    filters. `settings`: where the chips are remembered (the controller's
    get_app_setting / set_app_setting); without it they start from the
    defaults and aren't saved. `keep`: param_filters group keys this picker
    always shows. `first`: group keys it lists before everything else,
    each under its own heading."""
    dlg = OscVariablePicker(parent, on_pick, title=title, subtitle=subtitle,
                            allow_wildcards=allow_wildcards, mapped=mapped,
                            settings=settings, keep=keep, first=first)
    dlg.start()
    dlg.exec()
    # exec() only hides the dialog: without this every open leaked a live
    # QDialog whose 1.5 s tick kept polling the parameter store.
    dlg.deleteLater()
