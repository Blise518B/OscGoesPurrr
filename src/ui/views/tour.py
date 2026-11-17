"""The guided tour in the window: starting it, the one-time invitation, and
the answers the tour (ui/tour.py) asks of the window.

Where it starts (Blise's go on the default, 2026-11-14):
* a new install: right after "What are you here for?" closes, by itself
  (controllers/tour_facade.py decides; the window waits for the question);
* an install from before the tour: offered once, on the update that brings
  it, as a small bar over the page -- Take the tour / No thanks;
* any time after: Help → Take the tour, and Getting started's Take the tour.
Never again by itself.

The answers: which page a step is on, its sidebar entry, whether a step is
for this user (its feature is on; the toy's steps unless Continue without
a toy), where to look for its control (the tour's toy's card or row), and
whether the thing a step waits for has happened -- read from the window and
the controller's facade, never written. The tour's toy is the first toy
that connects (or is connected), in Home's order.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from shiboken6 import isValid

from ui import tour_steps
from ui.help_mode import _c, find_control
from ui.motor_signal_chain import _get_chain_count
from ui.tour import Tour

TOYS_FEATURE = "feature_intiface"

# Take the tour's explanation -- the same on Help and in Getting started.
TAKE_TOUR_TITLE = "Take the tour"
TAKE_TOUR_TIP = (
    "Walks you through OscGoesPurrr for real, one step at a time. Your toy, its "
    "zones, the four chips, Test and strength, then what you picked - shockers, "
    "friends, the avatar remote. It lights where to click and moves on when you've "
    "done it; skip any step, Esc ends it. It never changes a setting by itself.")
SUIT_FEATURES = ("feature_bhaptics", "feature_owo", "feature_trackers")


class _Invite(QWidget):
    """The invitation over the page, once, for an install from before the
    tour: what it is, Take the tour, No thanks."""

    def __init__(self, on_take: Callable[[], None], on_dismiss: Callable[[], None]):
        super().__init__()
        self.setObjectName("tourInvite")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(10)
        self.text = QLabel("New: a guided tour. It shows you around OscGoesPurrr, one real "
                           "step at a time - your toy, its zones, the settings that matter.")
        self.text.setWordWrap(True)
        lay.addWidget(self.text, 1)
        self.take = QPushButton("Take the tour")
        self.take.setProperty("role", "sideSmall")
        self.take.setCursor(Qt.PointingHandCursor)
        self.take.clicked.connect(lambda _=False: on_take())
        lay.addWidget(self.take, 0, Qt.AlignVCenter)
        self.dismiss = QPushButton("No thanks")
        self.dismiss.setProperty("role", "sideSmall")
        self.dismiss.setCursor(Qt.PointingHandCursor)
        self.dismiss.clicked.connect(lambda _=False: on_dismiss())
        lay.addWidget(self.dismiss, 0, Qt.AlignVCenter)

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), _c("panel"))
        p.setPen(QPen(_c("accent"), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class _Seen:
    """Whether a control titled `title` shows under the tour's toy's card --
    remembered once found, so most looks cost one isVisible()."""

    def __init__(self, scopes: Callable[[], List[QWidget]], title: str):
        self._scopes, self._title = scopes, title
        self._w: Optional[QWidget] = None
        self._skip = 0

    def __call__(self) -> bool:
        w = self._w
        if w is not None and isValid(w) and w.isVisible():
            return True
        if self._skip > 0:
            self._skip -= 1
            return False
        self._skip = 4
        scopes = [s for s in self._scopes() if s is not None and isValid(s)]
        self._w = find_control(scopes, self._title) if scopes else None
        return self._w is not None


class TourMixin:
    """Mixin for OscGoesPurrrUI: the host of ui/tour.Tour. Needs
    `controller`, `views`, `nav_buttons`, `main_stack`, `_root_widget`,
    `device_ui_frames`, `select_view` and `_feature_allows_view`."""

    # ---- starting ----------------------------------------------------------
    def _tour(self) -> Tour:
        tour = getattr(self, "_tour_obj", None)
        if tour is None:
            tour = Tour(self._root_widget, self.main_stack, self,
                        add_section=getattr(getattr(self, "live_theme", None), "add_root", None))
            self._tour_obj = tour
        return tour

    def tour_active(self) -> bool:
        tour = getattr(self, "_tour_obj", None)
        return bool(tour is not None and tour.active)

    def start_tour(self) -> None:
        """Facade (a new install's first launch) and the Take the tour
        buttons: the tour from its first step, on Home. Waits while "What
        are you here for?" is open (it runs when that closes)."""
        if getattr(self, "_interests_dialog", None) is not None:
            self._tour_waiting = True
            return
        self._tour_waiting = False
        self._hide_tour_invite()
        helper = getattr(self, "_help_mode", None)
        if helper is not None and helper.active:
            helper.stop()
        self._tour_toy_name = None
        if "Home" in (getattr(self, "views", None) or {}):
            self.select_view("Home")
        self._tour().start()

    def end_tour(self) -> None:
        """Off without a word (help mode is starting)."""
        tour = getattr(self, "_tour_obj", None)
        if tour is not None and tour.active:
            tour.stop()

    def offer_tour(self) -> None:
        """Facade: an install from before the tour, on the update that
        brings it -- the invitation over the page, this launch only."""
        bar = getattr(self, "_tour_invite", None)
        if bar is None:
            bar = _Invite(self._take_tour_invite, self._hide_tour_invite)
            holder = self.main_stack.parentWidget() if self.main_stack is not None else None
            lay = holder.layout() if holder is not None else None
            if lay is None:
                return
            lay.insertWidget(lay.indexOf(self.main_stack), bar)
            add = getattr(getattr(self, "live_theme", None), "add_root", None)
            if callable(add):
                add(bar)
            self._tour_invite = bar
        bar.show()

    def _take_tour_invite(self) -> None:
        self._hide_tour_invite()
        self.start_tour()

    def _hide_tour_invite(self) -> None:
        bar = getattr(self, "_tour_invite", None)
        if bar is not None:
            bar.hide()

    # ---- what the tour asks ------------------------------------------------
    def tour_page(self, name: str) -> Optional[QWidget]:
        page = (getattr(self, "views", None) or {}).get(name)
        if page is None:
            return None
        allows = getattr(self, "_feature_allows_view", None)
        return page if not callable(allows) or allows(name) else None

    def tour_nav(self, name: str) -> Optional[QWidget]:
        return (getattr(self, "nav_buttons", None) or {}).get(name)

    def _tour_feature(self, key: str) -> bool:
        get = getattr(self.controller, "get_feature_enabled", None)
        return bool(get(key)) if callable(get) else True

    def tour_applies(self, step: tour_steps.TourStep, no_toy: bool) -> bool:
        if step.page and self.tour_page(step.page) is None:
            return False
        needs = step.needs
        if needs == "toy":
            return not no_toy and self._tour_feature(TOYS_FEATURE)
        if needs == "suits":
            return any(self._tour_feature(k) for k in SUIT_FEATURES)
        if needs:
            return self._tour_feature(needs)
        return True

    def tour_scopes(self, step: tour_steps.TourStep) -> List[QWidget]:
        if step.scope in ("toy", "toy_row"):
            data = self.device_ui_frames.get(self._tour_toy() or "") or {}
            if step.scope == "toy_row":
                data = data.get("home") or {}
            frame = data.get("frame")
            return [frame] if frame is not None else []
        if not step.page:
            side = getattr(self, "sidebar_frame", None)
            return [side if side is not None else self._root_widget]
        page = self.tour_page(step.page)
        return [page] if page is not None else []

    def tour_fill(self, target: str) -> str:
        if tour_steps.TOY in target:
            return target.replace(tour_steps.TOY, self._tour_toy() or "\x00")
        return target

    def tour_passthrough(self, w: QWidget) -> bool:
        """The sidebar's pages keep working: the tour follows."""
        return any(w is b or b.isAncestorOf(w) for b in (self.nav_buttons or {}).values())

    def tour_finished(self, how: str) -> None:
        pass

    # ---- the tour's toy ------------------------------------------------------
    def _tour_connected(self) -> List[str]:
        """The connected toys in Home's order (the order they connected)."""
        c = self.controller
        order = getattr(c, "get_connected_toys_in_order", None)
        try:
            names = list(order()) if callable(order) else sorted(c.get_connected_device_names())
        except Exception:
            return []
        return [n for n in names if n in self.device_ui_frames]

    def _tour_connected_toy(self) -> Optional[str]:
        """A connected toy for the tour -- the one it already has, else the
        first in Home's order -- or None."""
        names = self._tour_connected()
        mine = getattr(self, "_tour_toy_name", None)
        if mine in names:
            return mine
        if names:
            self._tour_toy_name = names[0]
            return names[0]
        return None

    def _tour_toy(self) -> Optional[str]:
        """The toy the tour is about: the one it picked (even switched off
        meanwhile -- its row and card stay, grey), else a connected one."""
        mine = getattr(self, "_tour_toy_name", None)
        if mine in self.device_ui_frames:
            return mine
        return self._tour_connected_toy()

    def _tour_toy_card(self) -> List[QWidget]:
        data = self.device_ui_frames.get(self._tour_toy() or "") or {}
        return [data["frame"]] if data.get("frame") is not None else []

    def _tour_zones(self) -> tuple:
        """Every zones value of the tour's toy's chains, as stored."""
        name = self._tour_toy()
        data = self.device_ui_frames.get(name or "") or {}
        get = self.controller.get_profile_config
        missing = object()
        out = []
        for motor in range(len(data.get("motors", ()))):
            out.append(get(name, f"motor_{motor}_zones", missing))
            try:
                chains = _get_chain_count(self.controller, name, motor)
            except Exception:
                chains = 1
            for chain in range(chains):
                out.append(get(name, f"motor_{motor}_c{chain}_zones", missing))
        return tuple(v if v is not missing else None for v in out)

    def _tour_chips(self) -> Dict[str, tuple]:
        name = self._tour_toy()
        data = self.device_ui_frames.get(name or "") or {}
        values = self._toy_contact_values(name, len(data.get("motors", ())))
        return {pair: tuple(on for _m, _c, on in vals) for pair, vals in values.items()}

    def _tour_strength(self):
        slider = getattr(self, "sidebar_strength_slider", None)
        return slider.value() if slider is not None and isValid(slider) else None

    def tour_waiter(self, step: tour_steps.TourStep) -> Callable[[], bool]:
        """A callable that is True once the thing `step` waits for has
        happened -- a change from how it was when the step began."""
        key = step.waits
        if key == "toy":
            return lambda: self._tour_connected_toy() is not None
        if key == "toy_card_open":
            def card_open() -> bool:
                data = self.device_ui_frames.get(self._tour_toy() or "") or {}
                body = data.get("body")
                page = self.tour_page("Toys")
                return bool(body is not None and isValid(body) and body.isVisible()
                            and page is not None and self.main_stack.currentWidget() is page)
            return card_open
        if key == "input_open":
            return _Seen(self._tour_toy_card, "Zone selector")
        if key == "zones_open":
            return _Seen(self._tour_toy_card, "Your SPS sources")
        if key == "zone_picked":
            before = self._tour_zones()
            return lambda: self._tour_zones() != before
        if key == "chips":
            before = self._tour_chips()
            return lambda: self._tour_chips() != before
        if key == "strength":
            before = self._tour_strength()
            return lambda: self._tour_strength() != before
        return lambda: False
