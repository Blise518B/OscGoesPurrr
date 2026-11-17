"""The guided tour -- the controller side: when it starts by itself.

At launch, once (Blise's go on the default, 2026-11-14): a new install
starts the tour right after "What are you here for?" (the window waits for
the question); an install from before the tour is offered it, on the
update that brings it, as a small invitation it can dismiss. Either way it
is remembered (`tour_offered` in the app settings) and never happens by
itself again -- Help and Getting started start it on request.

The tour itself is ui/tour.py, its steps ui/tour_steps.py, the window's
side ui/views/tour.py.

Sealed-box rules: the UI is handed nothing but the call.
"""

from __future__ import annotations

# The app setting that remembers the tour was started or offered.
OFFERED_KEY = "tour_offered"


class TourFacade:
    """Mixin: the tour at launch. Composed into OscGoesPurrrApp.

    Assumes the host has `self.mode_manager.app_settings` (its
    `created_fresh`), `get_app_setting` / `set_app_setting` and `self.ui`.
    """

    def tour_on_launch(self) -> str:
        """"start" (a new install), "offer" (an older one, once) or "" --
        what was done. Called once after the main window is up, after
        "What are you here for?" and "What's new" were handed out."""
        if self.get_app_setting(OFFERED_KEY, False):
            return ""
        settings = getattr(getattr(self, "mode_manager", None), "app_settings", None)
        fresh = bool(getattr(settings, "created_fresh", False))
        what = "start" if fresh else "offer"
        call = getattr(self.ui, "start_tour" if fresh else "offer_tour", None)
        if not callable(call):
            return ""
        self.set_app_setting(OFFERED_KEY, True)
        call()
        return what
