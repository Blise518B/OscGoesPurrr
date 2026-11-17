"""Tell the avatar what is connected — the controller side.

Bool avatar parameters, each true while its device is connected and false
while it isn't:

* toys — one for the whole rig, true while ANY toy is connected
  (Settings → Connection Settings), and one per toy (its card on Home);
* the bHaptics suit — one while any part is connected, and one per part
  (Vest, Sleeves, Hands, Feet, Head: the parts you have, on the Suits page);
* the OWO suit — one while My OWO is connected (the Suits page);
* the PSVR2 headset — one while OGP is joined to its PSVR2Toolkit driver;
* shockers — one while the hub is connected with a shocker in use (the
  Shockers page's hub card), and one per shocker while it is connected and
  switched On (its card).

So an avatar can light a "toys on" icon, or the one part that is live, with
nothing more than a Bool in its parameter list. A general one is true while
any of its parts is; two things given the same name share the parameter
the same way.

**All on by default (Blise's call, 2026-11-05)**, under fixed names
(`OGP/<Thing>Connected`, below), so an asset can be built against them and
work without anyone flipping a switch; VRChat ignores a parameter the avatar
doesn't have. Every name can be changed, every switch turned off. The
suits' and the shockers' exist only while their feature is on.

Driven by each engine's own list of what is connected rather than by any
single event, so every way that list changes goes through one rule. Only
values that changed go out — except when VRChat can have lost them: the OSC
link coming up and an avatar loading (a swap resets every parameter)
re-send the lot. A parameter that is switched off, renamed, or whose device
is gone (a deleted toy, a feature switched off) is sent false once, and on
quit everything is, so an avatar is never left claiming a device the app
no longer holds.

Not a hot path: nothing here runs on the routing tick.

Sealed-box rules: the UI calls these methods and passes primitives (a
device is named by a slot string, `SLOT_*` / `bhaptics_part_slot` /
`shocker_slot`).
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

import body_map
from utilities import strip_param_prefix

from .pishock_facade import FEATURE_KEY as FEATURE_PISHOCK
from .psvr2_facade import FEATURE_PSVR2
from .suits_facade import FEATURE_BHAPTICS, FEATURE_OWO

# App settings (the whole-rig toy parameter).
ANY_ENABLED_KEY = "toy_presence_param_enabled"
ANY_PARAM_KEY = "toy_presence_param"
DEFAULT_ANY_PARAM = "OGP/ToyConnected"
# Per-toy keys. They live in the toy's wiring entry — a fact about the toy,
# shared by every mode (not routing keys, see config_manager.is_routing_key).
TOY_ENABLED_KEY = "connected_param_enabled"
TOY_PARAM_KEY = "connected_param"
# The suits and the shockers: one app setting, {slot: {"enabled", "name"}},
# holding only what the user changed — a slot missing from it is on, under
# its default name.
DEVICE_PARAMS_KEY = "connected_params"

SLOT_BHAPTICS = "bhaptics"
SLOT_OWO = "owo"
SLOT_SHOCKERS = "shockers"
SLOT_PSVR2 = "psvr2"

_PARAM_PREFIX = "/avatar/parameters/"
_FIXED_DEFAULTS = {
    SLOT_BHAPTICS: "OGP/BHapticsConnected",
    SLOT_OWO: "OGP/OWOConnected",
    SLOT_SHOCKERS: "OGP/ShockerConnected",
    SLOT_PSVR2: "OGP/PSVR2Connected",
    # OGP/BHapticsVestConnected, ...SleevesConnected, ...HeadConnected
    **{f"bhaptics:{key}": f"OGP/BHaptics{name}Connected"
       for key, name, _p in body_map.PART_GROUPS},
}


def bhaptics_part_slot(group: str) -> str:
    """The slot of one bHaptics part group (body_map.PART_GROUPS' key)."""
    return f"bhaptics:{group}"


def shocker_slot(shocker_id) -> str:
    return f"shocker:{int(shocker_id)}"


def default_toy_param(device_name: str) -> str:
    """The name a toy's parameter gets until the user types their own:
    `OGP/<Name>Connected`, the toy's name reduced to letters and digits so
    it is a safe OSC address ("Lovense Lush" -> `OGP/LovenseLushConnected`)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "", str(device_name or "")) or "Toy"
    return f"OGP/{slug}Connected"


class PresenceFacade:
    """Mixin: connected-device avatar parameters. Composed into
    OscGoesPurrrApp.

    Assumes the host has `self.mode_manager` (with `app_settings` and the
    merged per-device dicts), `self.haptic_engine` and `self.osc_manager`;
    and, when those features exist, `self.get_feature_enabled`,
    `self.bhaptics_engine` / `self.owo_engine` / `self.suits_settings` and
    `self.pishock_engine` / `self.pishock_settings` and `self.psvr2_engine`.
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

    def _presence_feature_on(self, key: str) -> bool:
        get = getattr(self, "get_feature_enabled", None)
        try:
            return bool(get(key)) if callable(get) else False
        except Exception:
            return False

    def _presence_bhaptics_have(self) -> List[str]:
        settings = getattr(self, "suits_settings", None)
        try:
            return list(settings.bhaptics()["have"]) if settings is not None else []
        except Exception:
            return []

    def _presence_shocker_order(self) -> List[int]:
        """The shockers the Shockers page has a card for, in its order —
        the hub's own list, or the page's for an OpenShock hub (kept while
        it's unplugged too). Their numbers are those of the default names."""
        eng = getattr(self, "pishock_engine", None)
        settings = getattr(self, "pishock_settings", None)
        if eng is None:
            return []
        try:
            connected = bool(eng.is_connected)
            openshock = list(settings.get_openshock_shockers() or []) if settings else []
            if eng.hub_kind == "openshock" or (openshock and not connected):
                return [int(s["id"]) for s in openshock]
            if connected:
                return [int(s["id"]) for s in eng.all_shockers()]
        except Exception:
            pass
        return []

    def _presence_devices(self) -> Dict[str, bool]:
        """Slot -> connected, for every suit and shocker slot there is:
        those of a feature that's switched off aren't."""
        out: Dict[str, bool] = {}
        bh = getattr(self, "bhaptics_engine", None)
        if bh is not None and self._presence_feature_on(FEATURE_BHAPTICS):
            try:
                positions = set(bh.connected_positions())
                out[SLOT_BHAPTICS] = bool(bh.is_connected)
            except Exception:
                positions = set()
                out[SLOT_BHAPTICS] = False
            live = {body_map.group_of(p) for p in positions}
            have = set(self._presence_bhaptics_have())
            for key, _name, _p in body_map.PART_GROUPS:
                # the parts you have (a part that connects is added to them)
                if key in have or key in live:
                    out[bhaptics_part_slot(key)] = key in live
        owo = getattr(self, "owo_engine", None)
        if owo is not None and self._presence_feature_on(FEATURE_OWO):
            try:
                out[SLOT_OWO] = bool(owo.is_connected)
            except Exception:
                out[SLOT_OWO] = False
        psvr2 = getattr(self, "psvr2_engine", None)
        if psvr2 is not None and self._presence_feature_on(FEATURE_PSVR2):
            try:
                out[SLOT_PSVR2] = bool(psvr2.is_connected)
            except Exception:
                out[SLOT_PSVR2] = False
        eng = getattr(self, "pishock_engine", None)
        if eng is not None and self._presence_feature_on(FEATURE_PISHOCK):
            try:
                in_use = set(eng.shocker_ids()) if eng.is_connected else set()
            except Exception:
                in_use = set()
            out[SLOT_SHOCKERS] = bool(in_use)
            for sid in self._presence_shocker_order():
                out[shocker_slot(sid)] = sid in in_use
        return out

    def _presence_wanted(self) -> Dict[str, bool]:
        """Parameter name -> value for every parameter that is switched on.
        Things that share a name share the parameter: it is true while any
        of them is connected."""
        wanted: Dict[str, bool] = {}

        def put(setting: Tuple[bool, str], value: bool) -> None:
            enabled, name = setting
            if enabled and name:
                wanted[name] = wanted.get(name, False) or bool(value)

        present = self._toy_presence_present()
        put(self.get_toy_presence_param(), bool(present))
        try:
            devices = dict(self.mode_manager.get_active_profile_dict() or {})
        except Exception:
            devices = {}
        for device in devices:
            put(self.get_toy_connected_param(device), device in present)
        for slot, value in self._presence_devices().items():
            put(self.get_device_connected_param(slot), value)
        return wanted

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def _presence_send(self, name: str, value: bool) -> bool:
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

    def presence_sync(self, force: bool = False) -> None:
        """Bring VRChat up to date. Sends what changed since the last
        successful send; `force` re-sends everything (VRChat may have
        lost it). A send that fails (link down) is simply due again."""
        wanted = self._presence_wanted()
        sent: Dict[str, bool] = {} if force else dict(
            getattr(self, "_presence_sent", {}))
        for name in [n for n in sent if n not in wanted]:
            # Switched off, renamed, or its device gone: clear it once.
            if not sent[name] or self._presence_send(name, False):
                del sent[name]
        for name, value in wanted.items():
            if sent.get(name) != value and self._presence_send(name, value):
                sent[name] = value
        self._presence_sent = sent

    def presence_on_devices_changed(self) -> None:
        """Main thread, after anything that may have changed what is
        connected: toys, a suit's state, the shocker hub's."""
        self.presence_sync()

    def presence_send_all(self) -> None:
        """The OSC link came up or an avatar loaded: VRChat knows nothing,
        so say everything again."""
        self.presence_sync(force=True)

    def presence_shutdown(self) -> None:
        """Quit: nothing is ours any more, so every parameter goes false."""
        for name, value in dict(getattr(self, "_presence_sent", {})).items():
            if value:
                self._presence_send(name, False)
        self._presence_sent = {}

    # ------------------------------------------------------------------
    # Settings (UI-facing, primitives only)
    # ------------------------------------------------------------------

    def get_toy_presence_param(self) -> Tuple[bool, str]:
        """(switched on, parameter name) for the whole-rig parameter."""
        s = self.mode_manager.app_settings
        name = strip_param_prefix(s.get(ANY_PARAM_KEY, "")) or DEFAULT_ANY_PARAM
        return bool(s.get(ANY_ENABLED_KEY, True)), name

    def set_toy_presence_param(self, enabled: bool, name: str) -> None:
        s = self.mode_manager.app_settings
        s.set(ANY_PARAM_KEY, strip_param_prefix(name) or DEFAULT_ANY_PARAM)
        s.set(ANY_ENABLED_KEY, bool(enabled))
        self.presence_sync()

    def get_toy_connected_param(self, device_name: str) -> Tuple[bool, str]:
        """(switched on, parameter name) for one toy's parameter."""
        get = self.mode_manager.get_profile_config
        name = (strip_param_prefix(get(device_name, TOY_PARAM_KEY, ""))
                or default_toy_param(device_name))
        return bool(get(device_name, TOY_ENABLED_KEY, True)), name

    def set_toy_connected_param(self, device_name: str, enabled: bool,
                                name: str) -> None:
        name = strip_param_prefix(name) or default_toy_param(device_name)
        self.mode_manager.update_device_config(device_name, TOY_PARAM_KEY, name)
        self.mode_manager.update_device_config(
            device_name, TOY_ENABLED_KEY, bool(enabled))
        self.mode_manager.save_profiles()
        self.presence_sync()

    def default_device_connected_param(self, slot: str) -> str:
        """The name a suit's, a part's or a shocker's parameter has until
        the user types their own. A shocker's is numbered like its card on
        the Shockers page: `OGP/Shocker1Connected`, `...2...`."""
        fixed = _FIXED_DEFAULTS.get(slot)
        if fixed:
            return fixed
        if slot.startswith("shocker:"):
            try:
                sid = int(slot.split(":", 1)[1])
            except ValueError:
                return _FIXED_DEFAULTS[SLOT_SHOCKERS]
            order = self._presence_shocker_order()
            number = order.index(sid) + 1 if sid in order else sid
            return f"OGP/Shocker{number}Connected"
        return f"OGP/{re.sub(r'[^A-Za-z0-9]+', '', slot) or 'Device'}Connected"

    def get_device_connected_param(self, slot: str) -> Tuple[bool, str]:
        """(switched on, parameter name) for a suit, a bHaptics part or a
        shocker (`SLOT_*`, `bhaptics_part_slot`, `shocker_slot`)."""
        saved = (self.mode_manager.app_settings.get(DEVICE_PARAMS_KEY, {}) or {}).get(slot)
        saved = saved if isinstance(saved, dict) else {}
        name = (strip_param_prefix(saved.get("name", ""))
                or self.default_device_connected_param(slot))
        return bool(saved.get("enabled", True)), name

    def set_device_connected_param(self, slot: str, enabled: bool,
                                   name: str) -> None:
        s = self.mode_manager.app_settings
        params = dict(s.get(DEVICE_PARAMS_KEY, {}) or {})
        # an empty name, or the default typed out, is kept as "the default"
        # -- so a shocker's number follows its card
        bare = strip_param_prefix(name)
        if bare == self.default_device_connected_param(slot):
            bare = ""
        params[str(slot)] = {"enabled": bool(enabled), "name": bare}
        s.set(DEVICE_PARAMS_KEY, params)
        self.presence_sync()
