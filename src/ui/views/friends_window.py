"""Friends view, Control mode in a window of its own (from friends' reviews,
2026-11-14): Pop out moves the control panel -- the same one, for whatever
is picked on the page -- into a separate window, everything big, so a VR
overlay (XSOverlay, OVR Toolkit, Desktop+) can capture just that window.

* One window, and it follows the pick: pick another friend or group in
  your list on the page and the window shows them. The page keeps a small
  card where the panel was (Show it, Back into the page).
* Closing the window -- or its Back into the page -- puts the panel back
  where it was. Its size and place are remembered (`friends_window_state`,
  Qt's own save, as the main window's `window_state`), and so is its Stay
  on top (`friends_window_on_top`).
* Everything stays inside it: no popup windows or menus, because an
  overlay that captures the window doesn't show them. While the panel is
  in here it leaves out its one right-click menu and the web remote's two
  confirmations (those stay on the page). The app-wide wheel guard
  (ui/wheel_guard.py) holds in here as everywhere: the wheel scrolls the
  window, never a setting.
* It keeps refreshing while the main window is minimized, in the tray or
  on another page -- that is the point of it.

Part of FriendsMixin (friends.py), with friends_panel.py."""

from typing import Callable, Optional

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QScrollArea, QWidget

from constants import APP_NAME
from ui import frame_clock
from ui.history_keys import HistoryLine
from ui.icons import glyph_icon
from ui.layout_helpers import hbox as _hbox, vbox as _vbox
from ui.theme import PALETTE
from ui.widgets import Card, ToggleSwitch, install_rainbow_scrollbars

# The window's title never changes (not with the friend picked either): an
# overlay may find the window again by it.
WINDOW_TITLE = f"{APP_NAME} · Control"
DEFAULT_SIZE = QSize(840, 940)     # a friend's big panel fits without growing it
MIN_SIZE = QSize(440, 360)         # its width grows to the panel inside (_fit_width)
SAVE_AFTER_MS = 600          # moved or resized: saved once it rests this long

STATE_KEY = "friends_window_state"
ON_TOP_KEY = "friends_window_on_top"


def _encode(blob: QByteArray) -> str:
    return bytes(blob.toBase64()).decode("ascii")


def _decode(text: str) -> QByteArray:
    try:
        return QByteArray.fromBase64(str(text).encode("ascii"))
    except Exception:
        return QByteArray()


class ControlWindow(QWidget):
    """The window itself: a bar (Stay on top, Back into the page) over a
    scroll area that holds the control panel while it is out of the page.
    Closing it hands the panel back (`on_close`); a move or resize that
    has come to rest calls `on_moved`, Stay on top `on_top_changed`."""

    def __init__(self, on_close: Callable[[], None], on_moved: Callable[[], None],
                 on_top_changed: Callable[[bool], None],
                 on_restored: Optional[Callable[[], None]] = None):
        super().__init__(None, Qt.Window)
        self.setObjectName("root")                 # the window's ground, as the main one
        # Closing it never ends the app (with the main window in the tray it
        # would be the last one), and only the main window's own close quits.
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(MIN_SIZE)
        self.resize(DEFAULT_SIZE)
        self._on_close, self._on_moved = on_close, on_moved
        self._on_top_changed, self._on_restored = on_top_changed, on_restored

        lay = _vbox(12, 10)
        self.setLayout(lay)
        bar = _hbox(8, 10)
        self.on_top = ToggleSwitch("Stay on top")
        self.on_top.setProperty("big", "true")
        self.on_top.toggled.connect(self._top_toggled)
        bar.addWidget(self.on_top)
        # Ctrl+Z / Ctrl+Y work in here too (ui/history_keys.py): what was
        # undone, and an undo's question, on this line -- in the window
        self.history_line = HistoryLine()
        bar.addWidget(self.history_line, 1)
        bar.addStretch(1)
        self.back = QPushButton(" Back into the page")
        self.back.setProperty("role", "control")
        self.back.setProperty("big", "true")
        self.back.setIconSize(QSize(16, 16))
        self.back.setCursor(Qt.PointingHandCursor)
        self.back.clicked.connect(lambda _=False: self.close())
        bar.addWidget(self.back)
        lay.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        install_rainbow_scrollbars(self.scroll)
        self._body = QWidget()
        self._body_lay = _vbox(8, 0)
        self._body.setLayout(self._body_lay)
        self._body_lay.addStretch(1)
        self.scroll.setWidget(self._body)
        lay.addWidget(self.scroll, 1)
        # The panel inside never gets cut off, nor scrolls sideways (a VR
        # stick scrolls up and down): the window is at least as wide as it,
        # checked whenever its contents change.
        self._body.installEventFilter(self)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_width)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_AFTER_MS)
        self._save_timer.timeout.connect(self._moved)
        self.recolour()

    def recolour(self) -> None:
        self.back.setIcon(glyph_icon("popin", PALETTE["cyan"][0], 16))

    # ---- the panel ---------------------------------------------

    def hold(self, panel: QWidget) -> None:
        self._body_lay.insertWidget(0, panel)
        panel.show()

    def let_go(self, panel: QWidget) -> None:
        self._body_lay.removeWidget(panel)

    def holds(self, panel: QWidget) -> bool:
        return self._body_lay.indexOf(panel) >= 0

    # ---- size, place, on top -----------------------------------

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._body and event.type() == QEvent.LayoutRequest:
            self._fit_timer.start()          # once its layout has settled
        return False

    def _fit_width(self) -> None:
        """At least as wide as the panel inside needs (a window narrower
        than that grows to it)."""
        m = self.layout().contentsMargins()
        need = (self._body.minimumSizeHint().width() + m.left() + m.right()
                + self.scroll.verticalScrollBar().sizeHint().width())
        need = max(MIN_SIZE.width(), need)
        if self.minimumWidth() != need:
            self.setMinimumWidth(need)

    def state(self) -> str:
        return _encode(self.saveGeometry())

    def restore_state(self, text: str) -> bool:
        """Its place and size the way state() found them; False, changing
        nothing, for none or junk. Before it is shown."""
        blob = _decode(text) if text else QByteArray()
        return bool(blob) and bool(self.restoreGeometry(blob))

    def is_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowStaysOnTopHint)

    def set_on_top(self, on: bool) -> None:
        on = bool(on)
        if self.on_top.isChecked() != on:
            self.on_top.blockSignals(True)
            self.on_top.setChecked(on)
            self.on_top.blockSignals(False)
        if self.is_on_top() == on:
            return
        # Qt hides a shown window to change its flags: put it back as it was
        shown = self.isVisible()
        where = self.saveGeometry() if shown else None
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if shown:
            self.restoreGeometry(where)
            self.show()

    def _top_toggled(self, on: bool) -> None:
        self.set_on_top(on)
        self._on_top_changed(bool(on))

    def _moved(self) -> None:
        if self.isVisible():
            self._on_moved()

    # ---- Qt events ---------------------------------------------

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if self.isVisible():
            self._save_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.isVisible():
            self._save_timer.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        frame_clock.wake()                # its meters paint again at once

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if (event.type() == QEvent.WindowStateChange
                and event.oldState() & Qt.WindowMinimized and not self.isMinimized()):
            frame_clock.wake()
            if self._on_restored is not None:
                try:
                    self._on_restored()      # caught up at once, not on the next tick
                except Exception:
                    pass

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_timer.stop()
        try:
            self._on_close()
        finally:
            event.accept()


class FriendsWindowMixin:
    """Pop out / put back, on the UI object (FriendsPanelMixin's base)."""

    _friends_popped = False                 # the panel is in its own window
    _friends_win: Optional[ControlWindow] = None
    _friends_away: Optional[QFrame] = None  # the page's card while it is

    # ---- the button on the panel -------------------------------

    def _pop_out_button(self) -> QPushButton:
        b = QPushButton(" Pop out")
        b.setProperty("role", "control")
        if self._friends_big:
            b.setProperty("big", "true")
        b.setIcon(glyph_icon("popout", PALETTE["cyan"][0], 16))
        b.setIconSize(QSize(16, 16))
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False: self._friends_pop_out())
        self._explain(b, "Pop out",
                      "This panel in a window of its own, big, for a VR overlay to "
                      "show. It follows whoever you pick in your list, it can stay "
                      "on top, and closing it puts the panel back here.")
        return b

    # ---- where things are --------------------------------------

    def _friends_window_seen(self) -> bool:
        """The panel is popped out and its window is on screen."""
        win = self._friends_win
        return (self._friends_popped and win is not None
                and frame_clock.window_on_screen(win))

    def _friends_panel_seen(self) -> bool:
        """Whether anyone can see the control panel: its own window while
        it is popped out, else the Friends page. A friend's live levels and
        board only come while it is."""
        if self._friends_popped:
            return self._friends_window_seen()
        page = self.views.get("Friends") if hasattr(self, "views") else None
        return page is not None and page.isVisible()

    def _friends_tick(self) -> None:
        """The page's live refresh: while the main window is on screen, or
        the popped-out panel is. Friends switched off closes the window."""
        if self._friends_popped:
            allows = getattr(self, "_feature_allows_view", None)
            if allows is not None and not allows("Friends"):
                self._friends_put_back()
        main = getattr(self, "window", None)
        if (not isinstance(main, QWidget) or frame_clock.window_on_screen(main)
                or self._friends_window_seen()):
            self._refresh_friends_live()

    # ---- out and back ------------------------------------------

    def _friends_window(self) -> ControlWindow:
        if self._friends_win is None:
            win = ControlWindow(on_close=self._friends_window_closed,
                                on_moved=self._friends_save_window,
                                on_top_changed=self._friends_save_on_top,
                                on_restored=self.refresh_friends)
            self._explain(win.on_top, "Stay on top",
                          "This window stays in front of every other window, VRChat "
                          "included. Remembered for next time.")
            self._explain(win.back, "Back into the page",
                          "Closes this window and puts the panel back on the Friends "
                          "page - closing the window does the same.")
            live = getattr(self, "live_theme", None)
            if live is not None:
                live.add_root(win)        # a colour change reaches it too
            self._friends_win = win
        return self._friends_win

    def _friends_away_card(self) -> QFrame:
        """What the page shows where the panel was, while it is out."""
        if self._friends_away is None:
            card = Card()
            lay = _vbox(20, 8)
            card.setLayout(lay)
            row = _hbox(0, 8)
            title = QLabel("In its own window")
            title.setObjectName("sectionTitle")
            row.addWidget(title)
            row.addStretch(1)
            lay.addLayout(row)
            lay.addWidget(self._muted_label(
                "The control panel is in a window of its own. Pick a friend or a "
                "group in your list and it shows them there."))
            btns = _hbox(0, 8)
            show = QPushButton("Show it")
            show.setProperty("role", "secondary")
            show.setCursor(Qt.PointingHandCursor)
            show.clicked.connect(lambda _=False: self._friends_show_window())
            self._explain(show, "Show it",
                          "Brings the control panel's window to the front.")
            btns.addWidget(show)
            back = QPushButton(" Back into the page")
            back.setProperty("role", "control")
            back.setIconSize(QSize(16, 16))
            back.setCursor(Qt.PointingHandCursor)
            back.clicked.connect(lambda _=False: self._friends_put_back())
            self._explain(back, "Back into the page",
                          "Closes the control panel's window and puts the panel back "
                          "here.")
            btns.addWidget(back)
            btns.addStretch(1)
            lay.addLayout(btns)
            card.show_btn, card.back_btn = show, back
            card.setVisible(False)
            rl = self._friends_right.layout()
            rl.insertWidget(rl.indexOf(self._panel_card) + 1, card)
            self._friends_away = card
            self._friends_window_recolour()
        return self._friends_away

    def _friends_pop_out(self) -> None:
        """Pop out: the panel moves into its window, big; the page gets the
        small card in its place. Already out: its window comes to the front."""
        if self._friends_popped:
            self._friends_show_window()
            return
        if self._friends_big:                 # out of control mode on the page
            self._friends_page_chrome(True)
        win = self._friends_window()
        away = self._friends_away_card()
        self._friends_right.layout().removeWidget(self._panel_card)
        win.hold(self._panel_card)
        away.setVisible(True)
        self._friends_popped = self._friends_big = True
        self._panel_card.setProperty("big", "true")
        self._repolish(self._panel_card)
        get = self.controller.get_app_setting
        win.set_on_top(bool(get(ON_TOP_KEY, False)))
        if not win.restore_state(get(STATE_KEY, "") or ""):
            self._friends_first_place(win)
        self._friends_show_window()
        self._friends_panel_key = None
        self.refresh_friends()                # rebuilt big, in there

    def _friends_put_back(self) -> None:
        """Back into the page -- what closing the window does too."""
        win = self._friends_win
        if win is not None and win.isVisible():
            win.close()                      # its closeEvent brings the panel home
        else:
            self._friends_window_closed()

    def _friends_window_closed(self) -> None:
        if not self._friends_popped:
            return
        win = self._friends_win
        self._friends_save_window()
        self._friends_popped = self._friends_big = False
        win.let_go(self._panel_card)
        rl = self._friends_right.layout()
        away = self._friends_away_card()
        rl.insertWidget(rl.indexOf(away), self._panel_card)
        away.setVisible(False)
        self._panel_card.setVisible(True)
        self._panel_card.setProperty("big", "false")
        self._repolish(self._panel_card)
        self._friends_panel_key = None
        self.refresh_friends()                # rebuilt small, on the page

    def _friends_show_window(self) -> None:
        win = self._friends_win
        if win is None or not self._friends_popped:
            return
        if win.isMinimized():                 # back as it was, maximized or not
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
        win.show()
        win.raise_()
        win.activateWindow()

    def _friends_first_place(self, win: ControlWindow) -> None:
        """Nothing remembered yet: its default size (as tall as the screen
        allows), in the middle of the screen the main window is on."""
        main = getattr(self, "window", None)
        screen = main.screen() if isinstance(main, QWidget) else win.screen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        size = DEFAULT_SIZE.boundedTo(QSize(avail.width() - 40, avail.height() - 80))
        win.resize(size)
        win.move(avail.center().x() - size.width() // 2, avail.center().y() - size.height() // 2)

    # ---- remembered --------------------------------------------

    def _friends_save_window(self) -> None:
        win = self._friends_win
        if win is not None:
            state = win.state()
            if state:
                self.controller.set_app_setting(STATE_KEY, state)

    def _friends_save_on_top(self, on: bool) -> None:
        self.controller.set_app_setting(ON_TOP_KEY, bool(on))

    def _friends_window_recolour(self) -> None:
        """After a colour change: the window's and the page card's icons are
        pixmaps, painted again in today's colours."""
        for fix in (lambda: self._friends_win is not None and self._friends_win.recolour(),
                    lambda: self._friends_away is not None and self._friends_away.back_btn.setIcon(
                        glyph_icon("popin", PALETTE["cyan"][0], 16))):
            try:
                fix()
            except RuntimeError:
                pass
