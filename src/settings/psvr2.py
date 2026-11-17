"""PlayStation VR2 headset rumble integration state: the usable frequency
band, the command-rate cap, an optional keepalive, and the single contact
receiver that drives it.

The source is a raw VRChat contact receiver parameter rather than an OGB
zone — see psvr2_router for why.

Auto-connect: the full edition starts it off, because the engine loads a
third-party DLL and claims a toolkit IPC slot. Here the feature switch
(`feature_psvr2`, off by default) is that opt-in, so once it's on the
headset is joined whenever SteamVR runs -- as the bHaptics suit and the
haptic trackers are (OWO and the shockers, which aren't plain motors,
connect only when asked)."""

from typing import Any, Dict

import antistuck
from utilities import strip_param_prefix

from ._base import JsonSettingsManager
from ._paths import PSVR2_SETTINGS_FILE

# The rumble field is a single byte and the toolkit's own UI caps it here.
HZ_MIN = 1.0
HZ_MAX = 25.0


def _default_contact() -> Dict[str, Any]:
    return {
        "enabled": False,
        # Bare contact receiver parameter name, e.g. "Contact/HeadPat".
        "parameter": "",
        "threshold": 0.0,
        "gain": 1.0,
    }


class PSVR2SettingsManager(JsonSettingsManager):
    HISTORY_KEY = "psvr2"
    HISTORY_LABEL = "PSVR2"

    @staticmethod
    def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
        """Ctrl+Z (settings_history.py): raising the command cap -- a
        hardware send limit -- asks first, and so does its anti-stuck
        switched off or made to wait longer."""
        from settings_history import Ask, raised
        asks = []
        if raised(current, target, ("max_cmd_hz",), 10.0):
            asks.append(Ask("confirm", f"raises the headset's command cap to "
                        f"{float(target['max_cmd_hz']):g} a second"))
        for what in antistuck.loosens((current or {}).get("antistuck"),
                                      (target or {}).get("antistuck")):
            asks.append(Ask("confirm", f"PSVR2 anti-stuck: {what}"))
        return asks

    FILE_PATH = PSVR2_SETTINGS_FILE

    DEFAULTS: Dict[str, Any] = {
        "auto_connect": True,
        # Usable rumble band (Hz). The level maps onto [min_hz..max_hz];
        # zero level always means zero (motor off). The floor defaults to
        # 10 Hz: the toolkit says the headset really does 10-25 Hz and takes
        # 1-9 as 10 (main's 5 Hz floor flattened the bottom of the range).
        "min_hz": 10.0,
        "max_hz": 25.0,
        # Cap on commands/second to the headset. Each one is a USB control
        # transfer the driver must ack, and the toolkit's command ring buffer
        # is shared with every other client, so this is a hardware limit
        # rather than a politeness knob.
        "max_cmd_hz": 10.0,
        # Optional re-send of a held non-zero value, in seconds. 0 = off.
        # The driver writes the value to a headset register, which should
        # latch; this exists only in case some firmware lets it decay.
        "keepalive_s": 0.0,
        "contact": _default_contact(),
        # Home's On / Off (this edition): off holds the motor at 0, still
        # connected, until switched on again -- across restarts too, like
        # the suits'. The full edition sharing this file ignores it.
        "enabled": True,
        # Its own anti-stuck (antistuck.py, since 2026-11-17): a file
        # without one starts as a copy of the toys' (seed_antistuck).
        "antistuck": dict(antistuck.DEFAULTS),
    }

    # True until seed_antistuck ran on a file that had no block yet (a new
    # file has none either).
    _antistuck_unseeded = True

    def _post_load(self, loaded: Dict[str, Any]) -> None:
        self._antistuck_unseeded = not isinstance(loaded.get("antistuck"), dict)
        self.settings["antistuck"] = antistuck.clean(self.settings.get("antistuck"))
        base = _default_contact()
        if isinstance(self.settings.get("contact"), dict):
            base.update(self.settings["contact"])
        self.settings["contact"] = self._clean_contact(base)

    # ---- connection ----
    def get_auto_connect(self) -> bool:
        return bool(self.settings.get("auto_connect", True))

    def set_auto_connect(self, value: bool) -> None:
        self.settings["auto_connect"] = bool(value)
        self._save()

    # ---- On / Off ----
    def get_enabled(self) -> bool:
        return bool(self.settings.get("enabled", True))

    def set_enabled(self, value: bool) -> None:
        self.settings["enabled"] = bool(value)
        self._save()

    # ---- anti-stuck (antistuck.py) ----
    def seed_antistuck(self, values: Dict[str, Any]) -> None:
        """Before 2026-11-17 the headset followed the toys' anti-stuck: a
        file without its own block starts as a copy of `values`. Once."""
        if self._antistuck_unseeded:
            self._antistuck_unseeded = False
            self.settings["antistuck"] = antistuck.clean(values)
            self._save()

    def get_antistuck(self) -> Dict[str, Any]:
        """`{enabled, active_s, peaked_s}`, what the router reads."""
        return antistuck.clean(self.settings.get("antistuck"))

    def set_antistuck(self, **changes) -> None:
        new = antistuck.changed(self.get_antistuck(), **changes)
        if new != self.get_antistuck():
            self.settings["antistuck"] = new
            self._save()

    # ---- output ----
    def get_output(self) -> Dict[str, Any]:
        """Primitive snapshot the engine's send loop reads every tick."""
        lo = self._f("min_hz", 10.0, HZ_MIN, HZ_MAX)
        hi = self._f("max_hz", 25.0, HZ_MIN, HZ_MAX)
        if hi < lo:
            lo, hi = hi, lo
        return {
            "min_hz": lo,
            "max_hz": hi,
            "max_cmd_hz": self._f("max_cmd_hz", 10.0, 1.0, 30.0),
            "keepalive_s": self._f("keepalive_s", 0.0, 0.0, 60.0),
        }

    def set_output(self, cfg: Dict[str, Any]) -> None:
        if not isinstance(cfg, dict):
            return
        merged = self.get_output()
        merged.update({k: v for k, v in cfg.items() if k in merged})
        lo = max(HZ_MIN, min(HZ_MAX, float(merged["min_hz"])))
        hi = max(HZ_MIN, min(HZ_MAX, float(merged["max_hz"])))
        if hi < lo:
            lo, hi = hi, lo
        self.settings.update({
            "min_hz": lo,
            "max_hz": hi,
            "max_cmd_hz": max(1.0, min(30.0, float(merged["max_cmd_hz"]))),
            "keepalive_s": max(0.0, min(60.0, float(merged["keepalive_s"]))),
        })
        self._save()

    # ---- contact routing ----
    def get_contact(self) -> Dict[str, Any]:
        return self._clean_contact(self.settings.get("contact", {}))

    def set_contact(self, cfg: Dict[str, Any]) -> None:
        self.settings["contact"] = self._clean_contact(cfg)
        self._save()

    # ---- helpers ----
    def _f(self, key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(self.settings.get(key, default))))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clean_contact(cfg: Dict[str, Any]) -> Dict[str, Any]:
        base = _default_contact()
        if not isinstance(cfg, dict):
            return base

        def _f(key, default):
            try:
                return float(cfg.get(key, default))
            except (TypeError, ValueError):
                return default

        return {
            "enabled": bool(cfg.get("enabled", False)),
            # strip_param_prefix so a full "/avatar/parameters/X" path (from
            # a hand-edited file, or pasted out of the OSC Inspector) matches
            # the bare parameter_store keys the router looks up.
            "parameter": strip_param_prefix(cfg.get("parameter", "")),
            "threshold": max(0.0, min(1.0, _f("threshold", 0.0))),
            "gain": max(0.0, min(5.0, _f("gain", 1.0))),
        }
