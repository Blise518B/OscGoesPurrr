"""Tell the avatar which toys are connected — the controller side.

Two kinds of outgoing avatar parameter, both Bools, both off until the
user switches them on:

* one for the whole rig — true while ANY toy is connected
  (Settings → Connection Settings);
* one per toy — true while THAT toy is connected (the toy's card on Home).

So an avatar can light a "toys on" icon, or the one toy that is live, with
nothing more than a Bool in its parameter list.

Driven, like the chimes, by the engine's connected-toy list rather than by
any single event, so every way that list changes goes through one rule.
Only values that changed go out — except when VRChat can have lost them:
the OSC link coming up and an avatar loading (a swap resets every
parameter) re-send the lot. A parameter that is switched off, renamed or
whose toy is deleted is sent false once, and on quit everything is, so an
avatar is never left claiming toys the app no longer holds.

Not a hot path: nothing here runs on the routing tick.

Sealed-box rules: the UI calls these methods and passes primitives.
"""

from __future__ import annotations

import re
from typing import Dict, Tuple

from utilities import strip_param_prefix

# App settings (the whole-rig parameter).
ANY_ENABLED_KEY = "toy_presence_param_enabled"
ANY_PARAM_KEY = "toy_presence_param"
DEFAULT_ANY_PARAM = "OGP/ToyConnected"
# Per-toy keys. They live in the toy's wiring entry — a fact about the toy,
# shared by every mode (not routing keys, see config_manager.is_routing_key).
TOY_ENABLED_KEY = "connected_param_enabled"
TOY_PARAM_KEY = "connected_param"

_PARAM_PREFIX = "/avatar/parameters/"


def default_toy_param(device_name: str) -> str:
    """The name a toy's parameter gets until the user types their own:
    `OGP/<Name>Connected`, the toy's name reduced to letters and digits so
    it is a safe OSC address ("Lovense Lush" -> `OGP/LovenseLushConnected`)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "", str(device_name or "")) or "Toy"
    return f"OGP/{slug}Connected"


class ToyPresenceFacade:
    """Mixin: connected-toy avatar parameters. Composed into
    OscGoesPurrrApp.

    Assumes the host has `self.mode_manager` (with `app_settings` and the
    merged per-device dicts), `self.haptic_engine` and `self.osc_manager`.
    """

    # ------------------------------------------------------------------
    # What should be on the wire
    # ------------------------------------------------------------------

    def _toy_presence_present(self) -> frozenset:
        engine = getattr(self, "haptic_engine", None)
        try:
            return frozenset(engine.list_connected_device_names()) if engine else frozenset()
        except Exception:
            return frozenset()

    def _toy_presence_wanted(self) -> Dict[str, bool]:
        """Parameter name -> value for every parameter that is switched on.
        Toys that share a name share the parameter: it is true while any
        of them is connected."""
        present = self._toy_presence_present()
        wanted: Dict[str, bool] = {}
        enabled, name = self.get_toy_presence_param()
        if enabled and name:
            wanted[name] = bool(present)
        try:
            devices = dict(self.mode_manager.get_active_profile_dict() or {})
        except Exception:
            devices = {}
        for device in devices:
            enabled, name = self.get_toy_connected_param(device)
            if enabled and name:
                wanted[name] = wanted.get(name, False) or (device in present)
        return wanted

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _toy_presence_send(self, name: str, value: bool) -> bool:
        """One parameter out. True when it went (the OSC link is up). No
        forced type: the OSC layer coerces to whatever type the avatar
        declares, so a Float or Int parameter gets 1 / 0."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return False
        try:
            osc.send_parameter(_PARAM_PREFIX + name, bool(value),
                               ignore_rate_limit=True)
        except Exception:
            return False
        return True

    def toy_presence_sync(self, force: bool = False) -> None:
        """Bring VRChat up to date. Sends what changed since the last
        successful send; `force` re-sends everything (VRChat may have
        lost it). A send that fails (link down) is simply due again."""
        wanted = self._toy_presence_wanted()
        sent: Dict[str, bool] = {} if force else dict(
            getattr(self, "_toy_presence_sent", {}))
        for name in [n for n in sent if n not in wanted]:
            # Switched off, renamed, or its toy deleted: clear it once.
            if not sent[name] or self._toy_presence_send(name, False):
                del sent[name]
        for name, value in wanted.items():
            if sent.get(name) != value and self._toy_presence_send(name, value):
                sent[name] = value
        self._toy_presence_sent = sent

    def toy_presence_on_devices_changed(self) -> None:
        """Main thread, after anything that may have changed which toys
        are connected."""
        self.toy_presence_sync()

    def toy_presence_send_all(self) -> None:
        """The OSC link came up or an avatar loaded: VRChat knows nothing,
        so say everything again."""
        self.toy_presence_sync(force=True)

    def toy_presence_shutdown(self) -> None:
        """Quit: no toy is ours any more, so every parameter goes false."""
        for name, value in dict(getattr(self, "_toy_presence_sent", {})).items():
            if value:
                self._toy_presence_send(name, False)
        self._toy_presence_sent = {}

    # ------------------------------------------------------------------
    # Settings (UI-facing, primitives only)
    # ------------------------------------------------------------------

    def get_toy_presence_param(self) -> Tuple[bool, str]:
        """(switched on, parameter name) for the whole-rig parameter."""
        s = self.mode_manager.app_settings
        name = strip_param_prefix(s.get(ANY_PARAM_KEY, "")) or DEFAULT_ANY_PARAM
        return bool(s.get(ANY_ENABLED_KEY, False)), name

    def set_toy_presence_param(self, enabled: bool, name: str) -> None:
        s = self.mode_manager.app_settings
        s.set(ANY_PARAM_KEY, strip_param_prefix(name) or DEFAULT_ANY_PARAM)
        s.set(ANY_ENABLED_KEY, bool(enabled))
        self.toy_presence_sync()

    def get_toy_connected_param(self, device_name: str) -> Tuple[bool, str]:
        """(switched on, parameter name) for one toy's parameter."""
        get = self.mode_manager.get_profile_config
        name = (strip_param_prefix(get(device_name, TOY_PARAM_KEY, ""))
                or default_toy_param(device_name))
        return bool(get(device_name, TOY_ENABLED_KEY, False)), name

    def set_toy_connected_param(self, device_name: str, enabled: bool,
                                name: str) -> None:
        name = strip_param_prefix(name) or default_toy_param(device_name)
        self.mode_manager.update_device_config(device_name, TOY_PARAM_KEY, name)
        self.mode_manager.update_device_config(
            device_name, TOY_ENABLED_KEY, bool(enabled))
        self.mode_manager.save_profiles()
        self.toy_presence_sync()
