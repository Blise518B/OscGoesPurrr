""""What are you here for?" -- the controller side.

At launch: if this install has never answered the question (a new
install, or one from before the question), hand it to the UI once. An
answer sets the feature switches it ticks and unticks; Skip and closing
the window leave every switch as it is. Either way it is not asked again
by itself -- Settings → Features opens it on request.

The choices and the rule live in `interests.py`; the window in
`ui/views/interests.py`.

Sealed-box rules: the UI calls these methods and gets primitives.
"""

from __future__ import annotations

from typing import Dict

import interests


class InterestsFacade:
    """Mixin: the "What are you here for?" window. Composed into
    OscGoesPurrrApp.

    Assumes the host has `get_app_setting` / `set_app_setting`,
    `get_feature_flags` / `set_feature_enabled`, `log_message` and
    `self.ui`.
    """

    def interests_on_launch(self) -> bool:
        """Ask once. True when the window was opened. Called once, after
        the main window is up, ahead of "What's new"."""
        if self.get_app_setting(interests.ASKED_KEY, False):
            return False
        show = getattr(self.ui, "show_interests", None)
        if not callable(show):
            return False
        show(self.get_interests(), True)
        return True

    def get_interests(self) -> list:
        """The question with the switches as they are now:
        `[(group, [(feature, title, hint, on), ...]), ...]`."""
        flags = self.get_feature_flags()
        return [(g.title, [(c.feature, c.title, c.hint, bool(flags[c.feature]))
                           for c in g.choices if c.feature in flags])
                for g in interests.GROUPS]

    def set_interests(self, picked: Dict[str, bool]) -> None:
        """An answer: `{feature: ticked}`. Flips the switches that differ
        and remembers the question was answered."""
        flipped = interests.changes(self.get_feature_flags(), dict(picked or {}))
        for key, on in flipped.items():
            self.set_feature_enabled(key, on)
        self.set_app_setting(interests.ASKED_KEY, True)
        if flipped:
            self.log_message("Features picked: " + ", ".join(
                f"{key.removeprefix('feature_')} {'on' if on else 'off'}"
                for key, on in flipped.items()))

    def skip_interests(self) -> None:
        """Skipped or closed: nothing changes, and it isn't asked again."""
        self.set_app_setting(interests.ASKED_KEY, True)
