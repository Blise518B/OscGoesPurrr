"""Dashboard, profile slots, simple-mode panel, and device-routing view.

Mixin for ui_components.OscGoesPurrrUI. Relies on attributes initialised
by OscGoesPurrrUI.__init__ (self.controller, self.invoker, etc.)."""

from typing import List, Optional, Dict, Any, Callable
import os
import sys

from PySide6.QtCore import (
    Qt, QTimer, Signal, QObject, QEvent, QSize, QPointF, QRectF
)
from PySide6.QtGui import (
    QFont, QColor, QTextCharFormat, QTextCursor, QIcon,
    QPixmap, QPainter, QPen, QBrush, QPainterPath, QPolygonF
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QCheckBox, QLineEdit, QSlider, QProgressBar,
    QFrame, QScrollArea, QTextEdit, QPlainTextEdit, QSizePolicy, QSpacerItem,
    QDialog, QMessageBox, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QButtonGroup, QStackedWidget, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QComboBox, QSpinBox, QDoubleSpinBox, QToolButton,
)
from ui import lovense_icons as _lovense_icons

from constants import *
from parameter_store import store
from utilities import strip_param_prefix

from ui.geometry import parse_tk_geometry as _parse_tk_geometry
from ui.geometry import format_tk_geometry as _format_tk_geometry
from ui.layout_helpers import vbox as _vbox, hbox as _hbox, clear_layout as _clear_layout
from ui.text_helpers import truncate as _truncate, html_escape as _html_escape
from ui.icons import (
    new_icon_pixmap as _new_icon_pixmap,
    icon_pencil as _icon_pencil,
    icon_copy as _icon_copy,
    icon_paste as _icon_paste,
    icon_trash as _icon_trash,
    icon_check as _icon_check,
    icon_cross as _icon_cross,
)
from ui.widgets import (
    ToggleSwitch,
    Invoker as _Invoker,
    MainWindow as _MainWindow,
    Card as _Card,
    BHapticsDotGrid as _BHapticsDotGrid,
    SliderProxy as _SliderProxy,
    ProgressProxy as _ProgressProxy,
    RainbowMeter as _RainbowMeter,
    install_rainbow_scrollbars as _install_rainbow_scrollbars,
)


class DashboardMixin:

    # ----------------------------------------------------------
    # Dashboard view
    # ----------------------------------------------------------

    def _build_dashboard_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Dashboard")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # ===== Profile manager card =====
        prof_card = _Card()
        prof_lay = _vbox(16, 10)
        prof_card.setLayout(prof_lay)

        # Active-profile banner (kind + name)
        self.profile_active_label = QLabel("Active profile: —")
        f = self.profile_active_label.font(); f.setBold(True); f.setPointSize(13)
        self.profile_active_label.setFont(f)
        prof_lay.addWidget(self.profile_active_label)

        prof_lay.addWidget(self._muted_label(
            "Profiles hold per-toy settings: SPS zones, OSC mappings, filters. "
            "Avatar profiles auto-activate when their bound avatar loads."
        ))

        # ---- Global section ----
        global_header = QLabel("Global Profiles")
        global_header.setObjectName("sectionTitle")
        prof_lay.addWidget(global_header)
        prof_lay.addWidget(self._muted_label(
            "Manually selected. Active when no avatar profile is bound."
        ))

        self.global_profile_list_host = QWidget()
        self.global_profile_list_layout = _vbox(0, 4)
        self.global_profile_list_host.setLayout(self.global_profile_list_layout)
        prof_lay.addWidget(self.global_profile_list_host)

        gfooter = QWidget()
        gflay = _hbox(0, 6)
        gfooter.setLayout(gflay)
        new_global = QPushButton("+ New Global Profile")
        new_global.setMinimumHeight(34)
        new_global.setProperty("role", "secondary")
        new_global.clicked.connect(self._add_new_profile)
        gflay.addWidget(new_global, 1)
        self.global_paste_btn = QPushButton("📥 Paste")
        self.global_paste_btn.setMinimumHeight(34)
        self.global_paste_btn.setProperty("role", "secondary")
        self.global_paste_btn.clicked.connect(lambda _=False: self.controller.paste_profile("global"))
        gflay.addWidget(self.global_paste_btn)
        gflay.addWidget(self._make_help_badge(
            "Paste profile",
            "Creates a new global profile from the profile most recently "
            "copied with a row's 📋 Copy button. Use Copy + Paste to "
            "duplicate a setup before experimenting, or to turn an avatar "
            "profile into a global one."
        ))
        prof_lay.addWidget(gfooter)

        # ---- Divider ----
        divider = QFrame()
        divider.setObjectName("separator")
        prof_lay.addSpacing(4)
        prof_lay.addWidget(divider)
        prof_lay.addSpacing(4)

        # ---- Avatar section ----
        avatar_header_row = QWidget()
        ahlay = _hbox(0, 8)
        avatar_header_row.setLayout(ahlay)
        avatar_header = QLabel("Avatar Profiles")
        avatar_header.setObjectName("sectionTitle")
        ahlay.addWidget(avatar_header)
        ahlay.addStretch(1)
        self.current_avatar_label = QLabel("Current avatar: (not detected)")
        self.current_avatar_label.setProperty("muted", "true")
        ahlay.addWidget(self.current_avatar_label)
        prof_lay.addWidget(avatar_header_row)

        prof_lay.addWidget(self._muted_label(
            "Bound to a VRChat avatar ID. The bound profile auto-activates "
            "when that avatar loads, taking precedence over the global selection."
        ))

        self.avatar_profile_list_host = QWidget()
        self.avatar_profile_list_layout = _vbox(0, 4)
        self.avatar_profile_list_host.setLayout(self.avatar_profile_list_layout)
        prof_lay.addWidget(self.avatar_profile_list_host)

        afooter = QWidget()
        aflay = _hbox(0, 6)
        afooter.setLayout(aflay)
        self.avatar_new_btn = QPushButton("+ New Avatar Profile (bind to current)")
        self.avatar_new_btn.setMinimumHeight(34)
        self.avatar_new_btn.setProperty("role", "secondary")
        self.avatar_new_btn.clicked.connect(lambda _=False: self.controller.create_avatar_profile())
        aflay.addWidget(self.avatar_new_btn, 1)
        self.avatar_paste_btn = QPushButton("📥 Paste")
        self.avatar_paste_btn.setMinimumHeight(34)
        self.avatar_paste_btn.setProperty("role", "secondary")
        self.avatar_paste_btn.clicked.connect(lambda _=False: self.controller.paste_profile("avatar"))
        aflay.addWidget(self.avatar_paste_btn)
        aflay.addWidget(self._make_help_badge(
            "Paste profile",
            "Creates a new avatar profile (bound to the current avatar) "
            "from the profile most recently copied with a row's 📋 Copy "
            "button — handy for carrying a tuned setup over to a new "
            "avatar."
        ))
        prof_lay.addWidget(afooter)

        # Manage-all button lives below the "+ New / Paste" row so the
        # Dashboard list can stay short (only profiles bound to the current
        # avatar) while still offering a single click to browse the full set.
        self.avatar_manage_btn = QPushButton("📂 Manage all avatar profiles")
        self.avatar_manage_btn.setMinimumHeight(30)
        self.avatar_manage_btn.setProperty("role", "secondary")
        self.avatar_manage_btn.clicked.connect(
            lambda _=False: self._open_avatar_profile_manager()
        )
        prof_lay.addWidget(self.avatar_manage_btn)

        parent_layout.addWidget(prof_card)

        # ===== Purr-check card =====
        self.testing_frame = _Card()
        tlay = _vbox(12, 8)
        self.testing_frame.setLayout(tlay)
        self.purr_check_button = QPushButton("Purr-Check (Test All)")
        self.purr_check_button.setMinimumHeight(40)
        self.purr_check_button.clicked.connect(self.controller.trigger_purr_check)
        tlay.addWidget(self.purr_check_button, alignment=Qt.AlignHCenter)
        parent_layout.addWidget(self.testing_frame)
        parent_layout.addStretch(1)

        # Initial render of both lists.
        self._refresh_profile_buttons()

    # ------------------------------------------------------------------
    # Profile section helpers
    # ------------------------------------------------------------------

    def _refresh_profile_buttons(self):
        """Rebuild both profile sections + update the active banner."""
        ctl = self.controller
        active = ctl.get_active_profile_info() \
            if hasattr(ctl, "get_active_profile_info") \
            else {"kind": "global", "name": ctl.get_current_global_profile_name()}

        # ---- Active banner ----
        if self.profile_active_label is not None:
            kind_label = "Avatar" if active["kind"] == "avatar" else "Global"
            self.profile_active_label.setText(
                f"Active profile: {kind_label} · {active['name']}"
            )

        # ---- Current avatar label ----
        if self.current_avatar_label is not None:
            avatar_id = ctl.get_current_avatar_id() or ""
            if avatar_id:
                self.current_avatar_label.setText(f"Current avatar: {_truncate(avatar_id, 28)}")
            else:
                self.current_avatar_label.setText("Current avatar: (not detected)")

        # ---- Clipboard-aware paste buttons ----
        has_clip = ctl.has_clipboard()
        src = ctl.get_clipboard_source_name() or ""
        for btn in (self.global_paste_btn, self.avatar_paste_btn):
            if btn is None:
                continue
            btn.setEnabled(has_clip)
            btn.setText(f"📥 Paste (from '{_truncate(src, 18)}')" if has_clip else "📥 Paste")

        # ---- Avatar 'New' button availability ----
        if self.avatar_new_btn is not None:
            avatar_id = ctl.get_current_avatar_id() or ""
            if avatar_id:
                self.avatar_new_btn.setEnabled(True)
                self.avatar_new_btn.setText(
                    f"+ New Avatar Profile (binds to {_truncate(avatar_id, 16)})"
                )
                self.avatar_new_btn.setToolTip("")
            else:
                self.avatar_new_btn.setEnabled(False)
                self.avatar_new_btn.setText("+ New Avatar Profile (no avatar detected)")
                self.avatar_new_btn.setToolTip(
                    "Load any avatar in VRChat first so the profile knows which avatar to bind to."
                )

        # ---- Manage-all button ----
        if self.avatar_manage_btn is not None:
            total = len(ctl.get_avatar_profile_names())
            self.avatar_manage_btn.setText(
                f"📂 Manage all avatar profiles ({total})"
            )
            self.avatar_manage_btn.setEnabled(total > 0)

        # ---- Rebuild rows ----
        self._build_global_profile_rows(active)
        self._build_avatar_profile_rows(active)

    # Backwards-compat alias for older internal callers.
    def _build_profile_slots(self):
        self._refresh_profile_buttons()

    def _build_global_profile_rows(self, active: dict):
        if self.global_profile_list_layout is None:
            return
        _clear_layout(self.global_profile_list_layout)

        names = self.controller.get_global_profile_names()
        can_delete = len(names) > 1
        for name in names:
            # Exactly one profile across both sections shows the highlight:
            # whichever the resolver currently considers active. Clicking
            # any global flips the override on, so the highlight follows.
            is_active = (active["kind"] == "global" and name == active["name"])
            row = self._make_profile_row(
                name=name,
                is_selected=is_active,
                is_active=is_active,
                on_activate=lambda n=name: self.controller.switch_profile(n),
                on_rename=lambda n=name: self._start_profile_rename("global", n),
                on_copy=lambda n=name: self.controller.copy_profile("global", n),
                on_delete=lambda n=name: self._confirm_profile_delete("global", n),
                can_delete=can_delete,
                kind="global",
            )
            self.global_profile_list_layout.addWidget(row)

    def _build_avatar_profile_rows(self, active: dict):
        """Show only profiles bound to the *current* avatar (typically 0–1
        rows). The rest live in the Avatar Profile Manager dialog so the
        Dashboard stays uncluttered when you have many avatars."""
        if self.avatar_profile_list_layout is None:
            return
        _clear_layout(self.avatar_profile_list_layout)

        ctl = self.controller
        current_avatar = ctl.get_current_avatar_id() or ""
        all_names = ctl.get_avatar_profile_names()
        relevant = [
            n for n in all_names
            if ctl.get_avatar_binding(n) == current_avatar and current_avatar
        ]

        if not relevant:
            if not current_avatar:
                msg = "No avatar detected — load any avatar in VRChat first."
            elif not all_names:
                msg = "No avatar profiles yet. Click '+ New Avatar Profile' above."
            else:
                msg = ("No profile bound to the current avatar. Create one above, "
                       "or open the manager below to bind an existing profile.")
            empty = QLabel(msg)
            empty.setProperty("muted", "true")
            empty.setWordWrap(True)
            self._repolish(empty)
            self.avatar_profile_list_layout.addWidget(empty)
        else:
            for name in relevant:
                bound_id = ctl.get_avatar_binding(name)
                is_active = (active["kind"] == "avatar" and name == active["name"])
                row = self._make_profile_row(
                    name=name,
                    is_selected=is_active,
                    is_active=is_active,
                    bound_avatar_id=bound_id,
                    bound_is_current=True,
                    on_activate=lambda n=name: self.controller.bind_avatar_profile_to_current(n),
                    on_rename=lambda n=name: self._start_profile_rename("avatar", n),
                    on_copy=lambda n=name: self.controller.copy_profile("avatar", n),
                    on_delete=lambda n=name: self._confirm_profile_delete("avatar", n),
                    can_delete=True,
                    show_bind=True,
                    kind="avatar",
                )
                self.avatar_profile_list_layout.addWidget(row)


    def _make_profile_row(self, name: str, on_activate, on_rename,
                          on_copy, on_delete, can_delete: bool = True,
                          is_active: bool = False, is_selected: bool = False,
                          meta_text: str = "",
                          bound_avatar_id: str = "", bound_is_current: bool = False,
                          show_bind: bool = False,
                          extra_actions: Optional[list] = None,
                          kind: str = "global",
                          on_after_paste: Optional[Callable] = None) -> QWidget:
        """Build a single profile row.

        Visual states:
          * `is_selected` controls the button highlight (purple). This is what
            the user clicked most recently — i.e. their *intent*.
          * `is_active` controls the leading dot (filled green vs hollow).
            This is what's actually driving haptics right now. For the global
            section these can diverge when an avatar profile overrides.

        `extra_actions` is a list of (label, tooltip, callback) appended to
        the end of the row — used by the manager dialog for the "Bind to
        current avatar" button.
        """
        row = QWidget()
        row.setProperty("profileName", name)
        rlay = _hbox(0, 6)
        row.setLayout(rlay)

        dot = QLabel("●" if is_active else "○")
        dot.setProperty("role", "success" if is_active else "muted")
        self._repolish(dot)
        rlay.addWidget(dot)

        name_btn = QPushButton(name)
        name_btn.setMinimumHeight(34)
        name_btn.setProperty(
            "role", "profileActive" if is_selected else "profileIdle"
        )
        name_btn.clicked.connect(lambda _=False: on_activate())
        rlay.addWidget(name_btn, 1)

        if meta_text:
            note = QLabel(meta_text)
            note.setProperty("muted", "true")
            self._repolish(note)
            rlay.addWidget(note)

        # Avatar-binding label (avatar section only)
        if show_bind:
            if bound_avatar_id:
                bind_text = f"🔗 {_truncate(bound_avatar_id, 18)}"
                if bound_is_current:
                    bind_text += "  (current)"
            else:
                bind_text = "(unbound)"
            meta = QLabel(bind_text)
            meta.setProperty("role", "success" if bound_is_current else "muted")
            meta.setMinimumWidth(150)
            self._repolish(meta)
            rlay.addWidget(meta)

        def make_action(text, tooltip, cb, role="secondary", enabled=True,
                        width: int = 34, icon: Optional[QIcon] = None):
            b = QPushButton(text if icon is None else "")
            b.setFixedSize(width, 34)
            b.setProperty("role", role)
            b.setToolTip(tooltip)
            b.setEnabled(enabled)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _=False: cb())
            return b

        rlay.addWidget(make_action("", "Rename", on_rename, icon=_icon_pencil()))

        # Middle button is context-sensitive based on clipboard state:
        #   * empty clipboard  -> "Copy" (purple-secondary, two-sheets icon)
        #   * this row is the clipboard source -> green "Copied — click to
        #     cancel" using the same two-sheets icon on a success background
        #   * a different row is the source -> "Paste here" (clipboard+arrow
        #     icon) which overwrites this row with the clipboard contents
        ctl = self.controller
        has_clip = ctl.has_clipboard()
        clip_src_name = ctl.get_clipboard_source_name() if has_clip else None
        clip_src_kind = ctl.get_clipboard_source_kind() if has_clip else None
        is_clip_source = (
            clip_src_name == name and clip_src_kind == kind
        )

        def _paste_here(_n=name, _k=kind):
            self.controller.paste_profile_into(_k, _n)
            if on_after_paste is not None:
                on_after_paste()

        def _cancel_copy():
            self.controller.clear_clipboard()
            if on_after_paste is not None:
                on_after_paste()

        if not has_clip:
            rlay.addWidget(make_action(
                "", "Copy to clipboard", on_copy, icon=_icon_copy()
            ))
        elif is_clip_source:
            # Source row: not a paste target (pasting onto itself is a no-op).
            # Show a green "Copied" badge plus a small × to cancel.
            badge = QLabel("✓ Copied")
            badge.setProperty("role", "success")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedHeight(34)
            badge.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-weight: bold; padding: 0 6px;"
            )
            badge.setToolTip(
                "This profile is on the clipboard — click paste on another "
                "row to overwrite it, or × to cancel."
            )
            self._repolish(badge)
            rlay.addWidget(badge)
            rlay.addWidget(make_action(
                "", "Cancel copy", _cancel_copy,
                role="secondary", icon=_icon_cross(COLOR_TEXT_MUTED),
            ))
        else:
            rlay.addWidget(make_action(
                "", f"Paste over '{name}' (overwrite with clipboard)",
                _paste_here, role="confirm", icon=_icon_paste(),
            ))
        trash_color = COLOR_TEXT if can_delete else COLOR_TEXT_MUTED
        rlay.addWidget(make_action(
            "", "Delete", on_delete,
            role="danger" if can_delete else "secondary",
            enabled=can_delete,
            icon=_icon_trash(trash_color),
        ))
        for (label, tooltip, cb) in (extra_actions or []):
            rlay.addWidget(make_action(label, tooltip, cb, width=110))
        return row

    def _open_avatar_profile_manager(self):
        """Modal viewer + editor for every avatar profile, regardless of which
        avatar is currently loaded. Shows binding info and offers rename /
        copy / delete plus a 'Bind to current avatar' shortcut."""
        ctl = self.controller
        dlg = QDialog(self.window)
        dlg.setWindowTitle("Avatar Profile Manager")
        dlg.resize(720, 520)
        dlg.setModal(True)

        lay = _vbox(14, 8)
        dlg.setLayout(lay)

        title = QLabel("Avatar Profile Manager")
        title.setObjectName("sectionTitle")
        lay.addWidget(title)

        cur_id = ctl.get_current_avatar_id() or "(not detected)"
        lay.addWidget(self._muted_label(
            f"Current avatar: {cur_id} — use ↻ to rebind a profile to it."
        ))

        # Scrollable rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
        host = QWidget()
        host_lay = _vbox(0, 6)
        host.setLayout(host_lay)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        # Bottom: Close button
        btn_row = QWidget()
        btn_row_lay = _hbox(0, 6)
        btn_row.setLayout(btn_row_lay)
        btn_row_lay.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(dlg.accept)
        btn_row_lay.addWidget(close)
        lay.addWidget(btn_row)

        # The manager mirrors the Dashboard's row helper. After any edit we
        # have to rebuild both the dialog list AND the Dashboard list, so
        # wrap the build step in a closure that reuses both.
        def rebuild():
            _clear_layout(host_lay)
            active = ctl.get_active_profile_info()
            names = ctl.get_avatar_profile_names()
            current_avatar = ctl.get_current_avatar_id() or ""
            if not names:
                empty = QLabel("No avatar profiles. Close this dialog and create one from the Dashboard.")
                empty.setProperty("muted", "true")
                self._repolish(empty)
                host_lay.addWidget(empty)
                return
            for name in names:
                bound_id = ctl.get_avatar_binding(name)
                is_active = (active["kind"] == "avatar" and name == active["name"])
                # "Activating" from this dialog rebinds the profile to the
                # current avatar (the only way to make an avatar profile go
                # live without changing avatars).
                row = self._make_profile_row(
                    name=name,
                    is_selected=is_active,
                    is_active=is_active,
                    bound_avatar_id=bound_id,
                    bound_is_current=bool(bound_id and bound_id == current_avatar),
                    on_activate=lambda n=name: (
                        ctl.bind_avatar_profile_to_current(n),
                        rebuild(),
                    ),
                    on_rename=lambda n=name: self._dialog_rename_avatar(dlg, n, rebuild),
                    on_copy=lambda n=name: (
                        ctl.copy_profile("avatar", n),
                        rebuild(),
                    ),
                    on_delete=lambda n=name: self._dialog_delete_avatar(dlg, n, rebuild),
                    can_delete=True,
                    show_bind=True,
                    kind="avatar",
                    on_after_paste=rebuild,
                    extra_actions=[(
                        "↻ Bind to current",
                        "Rebind this profile to the currently-loaded avatar",
                        lambda n=name: (
                            ctl.bind_avatar_profile_to_current(n),
                            rebuild(),
                        ),
                    )] if current_avatar else [],
                )
                host_lay.addWidget(row)
            host_lay.addStretch(1)

        rebuild()
        dlg.exec()

    def _dialog_rename_avatar(self, dlg: QDialog, current_name: str, rebuild):
        """Tiny rename prompt for use inside the manager dialog. Avoids
        inline-editing inside the scroll area for simplicity."""
        from PySide6.QtWidgets import QInputDialog
        new_name, ok = QInputDialog.getText(
            dlg, "Rename Avatar Profile",
            f"New name for '{current_name}':",
            text=current_name,
        )
        if ok:
            new_name = (new_name or "").strip()
            if new_name and new_name != current_name:
                self.controller.rename_avatar_profile(current_name, new_name)
        rebuild()

    def _dialog_delete_avatar(self, dlg: QDialog, name: str, rebuild):
        box = QMessageBox(dlg)
        box.setWindowTitle("Delete Avatar Profile")
        box.setText(f"Delete avatar profile '{name}'?")
        box.setInformativeText(
            "This removes the profile's saved per-toy settings.\n"
            "Your toys themselves remain."
        )
        box.setIcon(QMessageBox.Warning)
        del_btn = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is del_btn:
            self.controller.delete_avatar_profile(name)
        rebuild()

    def _add_new_profile(self):
        name = self.controller.create_profile()
        self._refresh_profile_buttons()
        self._start_profile_rename("global", name)

    def _confirm_profile_delete(self, kind: str, name: str):
        if kind == "global" and len(self.controller.get_global_profile_names()) <= 1:
            return
        box = QMessageBox(self.window)
        kind_word = "avatar profile" if kind == "avatar" else "profile"
        box.setWindowTitle(f"Delete {kind_word.title()}")
        box.setText(f"Delete {kind_word} '{name}'?")
        box.setInformativeText(
            "This removes the profile's saved per-toy settings.\n"
            "Your toys themselves remain."
        )
        box.setIcon(QMessageBox.Warning)
        del_btn = box.addButton("Delete", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is del_btn:
            if kind == "avatar":
                self.controller.delete_avatar_profile(name)
            else:
                self.controller.delete_profile(name)

    def _start_profile_rename(self, kind: str, current_name: str):
        """Replace the matching row's name button with an inline QLineEdit
        plus explicit ✓ / ✗ buttons. Avoids using `editingFinished` because
        it fires on stray focus changes (including the rebuild that happens
        when a commit succeeds), which used to silently revert the rename.
        """
        if not self.controller.profile_exists(kind, current_name):
            return
        layout = (self.global_profile_list_layout if kind == "global"
                  else self.avatar_profile_list_layout)
        if layout is None:
            return

        # Find the row widget with this profile name.
        target_row = None
        for i in range(layout.count()):
            item = layout.itemAt(i)
            row = item.widget() if item else None
            if row is not None and row.property("profileName") == current_name:
                target_row = row
                break
        if target_row is None:
            return
        row_layout = target_row.layout()
        if row_layout is None:
            return

        # Rebuild the row in place: leading dot + inline editor.
        _clear_layout(row_layout)

        dot = QLabel("✎")
        dot.setProperty("role", "muted")
        self._repolish(dot)
        row_layout.addWidget(dot)

        entry = QLineEdit(current_name)
        entry.setMinimumHeight(34)
        entry.selectAll()
        row_layout.addWidget(entry, 1)

        # One-shot guard so returnPressed + button clicks can't double-commit.
        state = {"done": False}

        def commit():
            if state["done"]:
                return
            state["done"] = True
            new_name = entry.text().strip()
            if not new_name or new_name == current_name:
                # No change → just rebuild the row.
                self._refresh_profile_buttons()
                return
            if kind == "avatar":
                self.controller.rename_avatar_profile(current_name, new_name)
            else:
                self.controller.rename_profile(current_name, new_name)

        def cancel():
            if state["done"]:
                return
            state["done"] = True
            self._refresh_profile_buttons()

        entry.returnPressed.connect(commit)
        # Escape cancels. We use a key-press event filter via a small lambda
        # subclass-free hack: connect to keyPressEvent via installEventFilter
        # on a dedicated object would be overkill — instead handle Escape
        # by listening through a child shortcut on the QLineEdit.
        from PySide6.QtGui import QKeySequence, QShortcut
        esc = QShortcut(QKeySequence("Escape"), entry)
        esc.activated.connect(cancel)

        ok = QPushButton("")
        ok.setFixedSize(34, 34)
        ok.setProperty("role", "confirm")
        ok.setToolTip("Confirm")
        ok.setIcon(_icon_check(COLOR_TEXT))
        ok.setIconSize(QSize(18, 18))
        ok.clicked.connect(lambda _=False: commit())
        row_layout.addWidget(ok)

        no = QPushButton("")
        no.setFixedSize(34, 34)
        no.setProperty("role", "cancel")
        no.setToolTip("Cancel")
        no.setIcon(_icon_cross(COLOR_TEXT))
        no.setIconSize(QSize(18, 18))
        no.clicked.connect(lambda _=False: cancel())
        row_layout.addWidget(no)

        entry.setFocus()

    # ----------------------------------------------------------
    # Simple Mode view
    # ----------------------------------------------------------

    def _build_simple_mode_view(self, parent_layout: QVBoxLayout):
        title = QLabel("Simple Mode")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        parent_layout.addWidget(title)

        # ===== Getting-started checklist =====
        # Simple Mode is the de-facto onboarding flow, but its three cards
        # each only explain their own gap — a first-time user had to infer
        # the OSC -> zones -> toy dependency chain themselves. This card
        # ticks the chain off live and disappears once everything lines up.
        gs_card = _Card()
        gs_lay = _vbox(14, 6)
        gs_card.setLayout(gs_lay)
        gs_hdr = QLabel("Getting started")
        f = gs_hdr.font(); f.setBold(True); f.setPointSize(12)
        gs_hdr.setFont(f)
        gs_lay.addWidget(gs_hdr)
        gs_lay.addWidget(self._muted_label(
            "Three things have to line up before you feel anything — each "
            "row ticks green on its own as you get there."
        ))
        self._simple_mode_step_text = {
            "osc": "VRChat OSC connected — use the sidebar's "
                   "\"Connect to VRChat\" button (VRChat must be running "
                   "with OSC enabled)",
            "zones": "SPS zones detected — load an avatar with OGB / SPS "
                     "contacts",
            "toy": "A toy is connected — power it on; it's discovered "
                   "automatically",
        }
        self._simple_mode_steps: Dict[str, QLabel] = {}
        for key in ("osc", "zones", "toy"):
            row_lbl = QLabel("")
            row_lbl.setWordWrap(True)
            gs_lay.addWidget(row_lbl)
            self._simple_mode_steps[key] = row_lbl
        gs_lay.addWidget(self._muted_label(
            "Then press ▶ Test on a toy below — if you feel it, you're set."
        ))
        self._simple_mode_gs_card = gs_card
        parent_layout.addWidget(gs_card)

        # ===== Toggle card =====
        toggle_card = _Card()
        tlay = _vbox(14, 8)
        toggle_card.setLayout(tlay)

        self.simple_mode_toggle = ToggleSwitch("Enable Simple Mode")
        f = self.simple_mode_toggle.font(); f.setBold(True); f.setPointSize(13)
        self.simple_mode_toggle.setFont(f)
        self.simple_mode_toggle.setChecked(bool(self.controller.get_simple_mode()))
        self.simple_mode_toggle.toggled.connect(self._on_simple_mode_toggled)
        tlay.addWidget(self.simple_mode_toggle)

        tlay.addWidget(self._muted_label(
            "Routes every detected SPS source to every connected toy with no "
            "per-toy configuration. Profiles are ignored while this is on."
        ))

        self.simple_mode_status_label = QLabel("")
        self.simple_mode_status_label.setProperty("muted", "true")
        tlay.addWidget(self.simple_mode_status_label)

        # Phase 2 simplification: Simple Mode is pure depth (no speed
        # contribution). Users who want speed blending, curves, or per-toy
        # tuning use full Device Routing instead.

        hint = QLabel(
            "Tip: you can always come back to Simple Mode from Settings."
        )
        hint.setProperty("muted", "true")
        hint.setWordWrap(True)
        tlay.addWidget(hint)

        parent_layout.addWidget(toggle_card)

        # ===== Sources card =====
        src_card = _Card()
        slay = _vbox(14, 6)
        src_card.setLayout(slay)

        src_header = QLabel("SPS Sources")
        f = src_header.font(); f.setBold(True); f.setPointSize(12)
        src_header.setFont(f)
        slay.addWidget(src_header)
        slay.addWidget(self._muted_label("Detected from the active VRChat avatar."))

        sources_host = QWidget()
        self.simple_mode_sources_layout = _vbox(0, 3)
        sources_host.setLayout(self.simple_mode_sources_layout)
        slay.addWidget(sources_host)

        parent_layout.addWidget(src_card)

        # ===== Toys card =====
        toys_card = _Card()
        toylay = _vbox(14, 6)
        toys_card.setLayout(toylay)

        toys_header = QLabel("Connected Toys")
        f = toys_header.font(); f.setBold(True); f.setPointSize(12)
        toys_header.setFont(f)
        toylay.addWidget(toys_header)
        toylay.addWidget(self._muted_label("Battery and test pulse for every toy in range."))

        toys_host = QWidget()
        self.simple_mode_toys_layout = _vbox(0, 4)
        toys_host.setLayout(self.simple_mode_toys_layout)
        toylay.addWidget(toys_host)

        parent_layout.addWidget(toys_card)
        parent_layout.addStretch(1)

        # Initial paint.
        self.refresh_simple_mode_view(force=True)

    def _on_simple_mode_toggled(self, checked: bool):
        if hasattr(self.controller, "set_simple_mode"):
            self.controller.set_simple_mode(bool(checked))
        # Keep the two mirror checkboxes (Simple Mode panel + Settings) in
        # sync without re-firing the handler.
        for cb in (self.simple_mode_toggle, self.simple_mode_settings_toggle):
            if cb is not None and cb.isChecked() != bool(checked):
                cb.blockSignals(True)
                cb.setChecked(bool(checked))
                cb.blockSignals(False)
        self._apply_simple_mode_visibility()
        # Jump to a view that's actually visible in the new sidebar — the
        # Simple Mode entry disappears when the user turns it off, so we
        # land them on Dashboard rather than an orphaned page.
        if bool(checked):
            self.select_view("Simple Mode")
        else:
            self.select_view("Dashboard")
        self.refresh_simple_mode_view(force=True)

    # When Simple Mode is on, hide every advanced nav button — only
    # Simple Mode, Settings and Help remain. This is the "Just Works"
    # onboarding mode where the user shouldn't be surprised by SteamVR,
    # bHaptics, the OSC inspector, etc. before they've connected a toy.
    _SIMPLE_MODE_HIDDEN_VIEWS = (
        "Dashboard", "Device Routing", "SPS Sources", "SteamVR Device Comms",
        "bHaptics", "PiShock", "Coyote", "OWO", "Handy", "OSC Inspector",
        "OSC Diagnostics", "Overview", "System Log",
    )

    # Sidebar entries gated by Settings → Features. A view is hidden if any
    # of its required feature flags is off. "SteamVR Device Comms" is shown
    # when either haptics OR battery is enabled — both halves live in that
    # one view.
    _FEATURE_VIEW_REQUIREMENTS = {
        "bHaptics":              ("feature_bhaptics",),
        "PiShock":               ("feature_pishock",),
        "Coyote":                ("feature_coyote",),
        "OWO":                   ("feature_owo",),
        "Handy":                 ("feature_handy",),
        "OSC Inspector":         ("feature_osc_inspector",),
        "SteamVR Device Comms":  ("feature_steamvr_haptics", "feature_steamvr_battery"),
        # Device Routing is entirely about Intiface toy motor mapping, so hide
        # it when the user has turned Intiface off.
        "Device Routing":        ("feature_intiface",),
    }

    def _feature_allows_view(self, view_name: str) -> bool:
        reqs = self._FEATURE_VIEW_REQUIREMENTS.get(view_name)
        if not reqs:
            return True
        get = getattr(self.controller, "get_feature_enabled", None)
        if get is None:
            return True
        # SteamVR view needs either half on; other views need their single flag.
        if view_name == "SteamVR Device Comms":
            return any(bool(get(k)) for k in reqs)
        return all(bool(get(k)) for k in reqs)

    def apply_feature_visibility(self):
        """Re-evaluate sidebar visibility after a feature toggle changes."""
        # Hide the Intiface connect block when that feature is off.
        if self.intiface_sidebar_section is not None:
            get = getattr(self.controller, "get_feature_enabled", None)
            on = bool(get("feature_intiface")) if get else True
            self.intiface_sidebar_section.setVisible(on)
        self._apply_simple_mode_visibility()

    def _apply_simple_mode_visibility(self):
        on = bool(getattr(self.controller, "get_simple_mode", lambda: False)())
        for name, btn in self.nav_buttons.items():
            if name == "Simple Mode":
                # Only present in the sidebar while Simple Mode is on.
                # When off, the user re-enables it from Settings.
                btn.setVisible(on)
                continue
            # Feature-gated views disappear entirely when their toggle is off,
            # regardless of Simple Mode state.
            if not self._feature_allows_view(name):
                btn.setVisible(False)
                continue
            if name in self._SIMPLE_MODE_HIDDEN_VIEWS:
                btn.setVisible(not on)
            else:
                btn.setVisible(True)
        # If the currently-shown view just got hidden, fall back to Dashboard
        # (or Simple Mode when that's the only visible option).
        current = self.main_stack.currentWidget() if self.main_stack else None
        if current is not None:
            for name, page in self.views.items():
                if page is current and not self.nav_buttons.get(name, None) is None:
                    btn = self.nav_buttons.get(name)
                    if btn is not None and not btn.isVisible():
                        fallback = "Simple Mode" if on else "Dashboard"
                        self.select_view(fallback)
                    break

    def _make_battery_label(self, level: Optional[float]) -> QLabel:
        lbl = QLabel("")
        lbl.setMinimumWidth(60)
        self._apply_battery_text(lbl, level)
        return lbl

    def _apply_battery_text(self, lbl: QLabel, level: Optional[float]):
        if level is None:
            lbl.setText("🔋 --")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return
        try:
            pct = int(float(level) * 100)
        except (TypeError, ValueError):
            lbl.setText("🔋 --")
            lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            return
        if pct > 50:
            color = COLOR_SUCCESS
        elif pct > 20:
            color = COLOR_ALERT
        else:
            color = "#FF4444"
        lbl.setText(f"🔋 {pct}%")
        lbl.setStyleSheet(f"color: {color};")

    def _refresh_simple_mode_checklist(self, sources, toys) -> None:
        """Tick the getting-started rows off live; hide the card once the
        whole OSC -> zones -> toy chain is green. ``sources``/``toys`` are
        passed in by refresh_simple_mode_view so the parameter-store copy
        behind them happens once per tick, not twice. Change-gated — this
        rides the periodic UI tick, so identical states must cost nothing."""
        card = getattr(self, "_simple_mode_gs_card", None)
        steps = getattr(self, "_simple_mode_steps", None)
        if card is None or not steps:
            return
        try:
            osc_ok = bool((self.controller.get_osc_status_snapshot() or {})
                          .get("connected"))
        except Exception:
            osc_ok = False
        src = sources or {}
        zones_ok = bool(src.get("Orifices") or src.get("Penetrators")
                        or src.get("Touch"))
        toy_ok = bool(toys)
        state = {"osc": osc_ok, "zones": zones_ok, "toy": toy_ok}
        if state == getattr(self, "_simple_mode_gs_state", None):
            return
        self._simple_mode_gs_state = state
        for key, lbl in steps.items():
            ok = state[key]
            try:
                lbl.setText(("✓  " if ok else "○  ")
                            + self._simple_mode_step_text[key])
                lbl.setStyleSheet(f"color: {COLOR_SUCCESS};" if ok
                                  else f"color: {COLOR_TEXT_MUTED};")
            except RuntimeError:
                return
        card.setVisible(not all(state.values()))

    def refresh_simple_mode_view(self, force: bool = False):
        """Rebuild source + toy lists when the underlying data has changed.
        Called from the periodic UI tick and after key controller events."""
        if self.simple_mode_sources_layout is None or self.simple_mode_toys_layout is None:
            return
        ctl = self.controller

        # Fetched once and shared with the checklist below — the sources
        # getter copies the whole parameter store under the lock the OSC
        # ingest thread contends on, so it must not run twice per tick.
        sources = ctl.get_simple_mode_sources() if hasattr(ctl, "get_simple_mode_sources") else {}
        toys = ctl.get_simple_mode_toys() if hasattr(ctl, "get_simple_mode_toys") else []

        self._refresh_simple_mode_checklist(sources, toys)

        # Keep both mirror toggles in sync with the persisted flag.
        desired = bool(getattr(ctl, "get_simple_mode", lambda: False)())
        for cb in (self.simple_mode_toggle, self.simple_mode_settings_toggle):
            if cb is not None and cb.isChecked() != desired:
                cb.blockSignals(True)
                cb.setChecked(desired)
                cb.blockSignals(False)

        # ---- Status line ----
        if self.simple_mode_status_label is not None:
            if ctl.get_simple_mode():
                self.simple_mode_status_label.setText(
                    "Simple Mode is ON — Device Routing profiles are bypassed."
                )
                self.simple_mode_status_label.setStyleSheet(f"color: {COLOR_SUCCESS};")
            else:
                self.simple_mode_status_label.setText(
                    "Simple Mode is OFF — normal per-profile routing is active."
                )
                self.simple_mode_status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")

        # ---- Sources ----
        orifices = tuple(sources.get("Orifices", []))
        penetrators = tuple(sources.get("Penetrators", []))
        touch = tuple(sources.get("Touch", []))
        sources_key = (orifices, penetrators, touch)
        if force or sources_key != self._simple_mode_last_sources:
            self._simple_mode_last_sources = sources_key
            _clear_layout(self.simple_mode_sources_layout)
            if not orifices and not penetrators and not touch:
                lbl = QLabel("No SPS sources detected. Load an avatar with OGB zones.")
                lbl.setProperty("muted", "true")
                self._repolish(lbl)
                self.simple_mode_sources_layout.addWidget(lbl)
            else:
                for heading, names in (("Orifices", orifices),
                                       ("Penetrators", penetrators),
                                       ("Touch zones", touch)):
                    if not names:
                        continue
                    h = QLabel(heading)
                    fh = h.font(); fh.setBold(True); h.setFont(fh)
                    self.simple_mode_sources_layout.addWidget(h)
                    for name in names:
                        self.simple_mode_sources_layout.addWidget(QLabel(f"  • {name}"))

        # ---- Toys ----
        toys_key = tuple((t["name"], t.get("motor_count", 0), t.get("connected", False)) for t in toys)
        if force or toys_key != self._simple_mode_last_toys:
            self._simple_mode_last_toys = toys_key
            _clear_layout(self.simple_mode_toys_layout)
            self.simple_mode_battery_labels.clear()
            if not toys:
                lbl = QLabel("No connected toys. Open Intiface and connect a device.")
                lbl.setProperty("muted", "true")
                self._repolish(lbl)
                self.simple_mode_toys_layout.addWidget(lbl)
            else:
                for toy in toys:
                    row = QFrame()
                    row.setObjectName("chip")
                    row_lay = _hbox(8, 8)
                    row.setLayout(row_lay)

                    name_lbl = QLabel(f"✓ {toy['name']}")
                    name_lbl.setProperty("role", "success")
                    self._repolish(name_lbl)
                    row_lay.addWidget(name_lbl, 1)

                    batt = self._make_battery_label(toy.get("battery"))
                    row_lay.addWidget(batt)
                    self.simple_mode_battery_labels[toy["name"]] = batt

                    test_btn = QPushButton("Test")
                    test_btn.setFixedHeight(BTN_HEIGHT_SMALL)
                    test_btn.setProperty("role", "secondary")
                    test_btn.clicked.connect(
                        lambda _=False, n=toy["name"]: self.controller.test_toy(n)
                    )
                    row_lay.addWidget(test_btn)

                    self.simple_mode_toys_layout.addWidget(row)
        else:
            # Refresh battery text on existing labels even if the toy list itself
            # is unchanged — battery_update messages may have moved values.
            for toy in toys:
                lbl = self.simple_mode_battery_labels.get(toy["name"])
                if lbl is not None:
                    self._apply_battery_text(lbl, toy.get("battery"))

    def update_simple_mode_battery(self, device_name: str, level: float):
        """Live battery push from the controller. No-op if the label hasn't
        been built yet (the next refresh tick will pick up the value from
        the controller's cache)."""
        lbl = self.simple_mode_battery_labels.get(device_name)
        if lbl is not None:
            self._apply_battery_text(lbl, level)

    # ----------------------------------------------------------
    # Device Routing view
    # ----------------------------------------------------------

    def _build_device_routing_view(self, parent_layout: QVBoxLayout):
        # Title row: centered title + Help Mode toggle on the right.
        title_row = QWidget()
        title_lay = _hbox(0, 8)
        title_row.setLayout(title_lay)
        title_lay.addStretch(1)
        title = QLabel("Device Routing")
        title.setObjectName("viewTitle")
        title.setAlignment(Qt.AlignHCenter)
        title_lay.addWidget(title)
        title_lay.addStretch(1)

        help_toggle = ToggleSwitch("Help Mode")
        self._register_help_mode_toggle(help_toggle)
        title_lay.addWidget(help_toggle)
        parent_layout.addWidget(title_row)

        # ---- Anti-stuck card (two-timer model; parity with SteamVR/bHaptics) ----
        # Safety cutoff for frozen SPS inputs on the toy path. VRChat only
        # sends OSC on parameter change, so a stuck proximity (avatar swap,
        # partner leaves) would otherwise drive a toy at its last value
        # forever. Global to Device Routing; persisted in app settings and
        # read fresh by the routing tick (controller._get_toy_antistuck).
        as_card = _Card()
        aslay = _vbox(14, 8)
        as_card.setLayout(aslay)
        as_hdr = QLabel("Anti-stuck")
        as_hdr.setObjectName("sectionTitle")
        aslay.addWidget(as_hdr)
        aslay.addWidget(self._muted_label(
            "VRChat only sends OSC on parameter change. If an SPS input stops "
            "updating (avatar swap, partner leaves, OSC routing loss), the last "
            "value would drive the toy forever. The active timeout cuts "
            "mid-range stuck values; the peaked timeout gives saturated (100%) "
            "values a longer fuse — they often mean a legitimate hold — then "
            "ramps them down."
        ))
        as_row = _hbox(0, 8)
        self.toy_antistuck_check = ToggleSwitch("Enabled")
        self.toy_antistuck_check.setChecked(
            bool(self.controller.get_app_setting("toy_antistuck_enabled", True))
        )
        as_row.addWidget(self.toy_antistuck_check)
        as_row.addSpacing(12)

        as_row.addWidget(QLabel("Active timeout (s)"))
        self.toy_antistuck_active_spin = QSpinBox()
        self.toy_antistuck_active_spin.setRange(1, 600)
        self.toy_antistuck_active_spin.setValue(
            int(self.controller.get_app_setting("toy_antistuck_active_s", 7))
        )
        as_row.addWidget(self.toy_antistuck_active_spin)

        as_row.addWidget(QLabel("Peaked timeout (s)"))
        self.toy_antistuck_peaked_spin = QSpinBox()
        self.toy_antistuck_peaked_spin.setRange(1, 600)
        self.toy_antistuck_peaked_spin.setValue(
            int(self.controller.get_app_setting("toy_antistuck_peaked_s", 15))
        )
        as_row.addWidget(self.toy_antistuck_peaked_spin)
        as_row.addStretch(1)
        aslay.addLayout(as_row)

        # Connect AFTER seeding values so the initial setValue/setChecked
        # calls above don't echo straight back into app settings.
        self.toy_antistuck_check.toggled.connect(self._on_toy_antistuck_changed)
        self.toy_antistuck_active_spin.valueChanged.connect(self._on_toy_antistuck_changed)
        self.toy_antistuck_peaked_spin.valueChanged.connect(self._on_toy_antistuck_changed)
        parent_layout.addWidget(as_card)

        self.devices_container_frame = _Card(dark_bg=True)
        container_lay = _vbox(10, 6)
        self.devices_container_frame.setLayout(container_lay)
        parent_layout.addWidget(self.devices_container_frame, 1)

        toys_hdr_row = QWidget()
        thl = _hbox(0, 6)
        toys_hdr_row.setLayout(thl)
        thl.addStretch(1)
        header = QLabel("Toys")
        f = header.font(); f.setBold(True); f.setPointSize(12)
        header.setFont(f)
        header.setAlignment(Qt.AlignHCenter)
        thl.addWidget(header)
        thl.addWidget(self._make_help_badge(
            "Toy cards",
            "Every connected or remembered toy gets a card. Click the bar "
            "to expand its per-motor signal chains (Input → Depth/Speed → "
            "Combine → Gate → Smoothing → Zero cut → Output — click any "
            "stage to edit it). <b>Mute</b> silences the toy without touching its "
            "config; <b>Test</b> pulses the motors; the mini bars mirror "
            "each motor's live output."
        ))
        thl.addStretch(1)
        container_lay.addWidget(toys_hdr_row)

        # Scrollable list of device cards.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        _install_rainbow_scrollbars(scroll)
        inner = QWidget()
        self.unified_devices_layout = _vbox(4, 8)
        self.unified_devices_layout.addStretch(1)
        inner.setLayout(self.unified_devices_layout)
        scroll.setWidget(inner)
        self.unified_devices_frame = inner
        container_lay.addWidget(scroll, 1)

    def _on_toy_antistuck_changed(self, *_):
        """Persist the Device Routing anti-stuck settings. The live routing
        tick reads them fresh each evaluation via the controller's
        `_get_toy_antistuck`, so the change takes effect on the next tick with
        no explicit recalc kick."""
        self.controller.set_app_setting(
            "toy_antistuck_enabled", bool(self.toy_antistuck_check.isChecked()))
        self.controller.set_app_setting(
            "toy_antistuck_active_s", int(self.toy_antistuck_active_spin.value()))
        self.controller.set_app_setting(
            "toy_antistuck_peaked_s", int(self.toy_antistuck_peaked_spin.value()))
