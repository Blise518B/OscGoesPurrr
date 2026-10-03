"""Toy connect / disconnect chimes — the controller side.

On by default, switchable in Settings → Connection Settings: a low→high
chime when a toy connects and a high→low one when a toy drops, at a volume
of the user's choosing, with a Test button that plays both.

Driven by a diff of the engine's connected-toy list rather than by any
single event, so every way that list changes — the first connect, a toy
switched on later, one switching off or running flat, Intiface dropping,
a manual Disconnect — goes through one rule, and several toys arriving
together make one chime. The list is tracked even while the chimes are
off, so switching them on mid-session never fires a stale chime.

Sealed-box rules: the UI calls these methods, never `toy_sounds` itself.
"""

from __future__ import annotations

import toy_sounds

SETTING_KEY = "toy_connect_sounds"
VOLUME_KEY = "toy_connect_sounds_volume"
DEFAULT_ON = True


class ToySoundsFacade:
    """Mixin: toy chimes. Composed into OscGoesPurrrApp.

    Assumes the host has `self.mode_manager` (with `app_settings`) and
    `self.haptic_engine`.
    """

    def toy_sounds_on_devices_changed(self) -> None:
        """Main thread, after anything that may have changed which toys are
        connected. Chimes when the set actually changed."""
        engine = getattr(self, "haptic_engine", None)
        try:
            present = frozenset(engine.list_connected_device_names()) if engine else frozenset()
        except Exception:
            return
        before = getattr(self, "_toy_sounds_present", frozenset())
        self._toy_sounds_present = present
        kind = toy_sounds.presence_change(before, present)
        if kind and self.get_toy_sounds_enabled():
            toy_sounds.play(kind, self.get_toy_sounds_volume())

    def get_toy_sounds_enabled(self) -> bool:
        return bool(self.mode_manager.app_settings.get(SETTING_KEY, DEFAULT_ON))

    def set_toy_sounds_enabled(self, enabled: bool) -> None:
        """Switching on plays the connect chime once, so the user knows
        what to listen for."""
        self.mode_manager.app_settings.set(SETTING_KEY, bool(enabled))
        if enabled:
            toy_sounds.play(toy_sounds.CONNECTED, self.get_toy_sounds_volume())

    def get_toy_sounds_volume(self) -> int:
        """Chime volume, 0-100 %."""
        return toy_sounds.clamp_volume(self.mode_manager.app_settings.get(
            VOLUME_KEY, toy_sounds.DEFAULT_VOLUME))

    def set_toy_sounds_volume(self, volume, preview: bool = True) -> None:
        """Store the volume and, unless told not to, play the connect chime
        at it so the user hears the level they just picked."""
        volume = toy_sounds.clamp_volume(volume)
        self.mode_manager.app_settings.set(VOLUME_KEY, volume)
        if preview:
            toy_sounds.play(toy_sounds.CONNECTED, volume)

    def test_toy_sounds(self) -> None:
        """Play the connect chime, then the disconnect one, at the stored
        volume — whether or not the chimes are switched on."""
        toy_sounds.play(toy_sounds.TEST, self.get_toy_sounds_volume())
