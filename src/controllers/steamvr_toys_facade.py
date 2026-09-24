"""SteamVR-toys facade mixin.

On by default, one switch in Settings: shows the user's connected toys in
SteamVR's device list (the status window strip), with their name, icon and
battery. A small bundled driver does the SteamVR side; this mixin installs
it, runs the IPC bridge that feeds it, and mirrors the toy list into it.
On a PC without SteamVR nothing is installed or started; switching the
feature off takes the driver out of SteamVR again.

The driver registers toys as TrackingReference devices with no pose and no
tracker role, so no app — VRChat's full-body tracking included — can ever
mistake a toy for a body tracker.

Sealed-box rules: the UI calls these methods, never the bridge or the
installer module directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from steamvr_toy_bridge import SteamVRToyBridge, ToyEntry, driver_listening

SETTING_KEY = "show_toys_in_steamvr"
DEFAULT_ON = True


class SteamVRToysFacade:
    """Mixin: toys in SteamVR's device list. Composed into OscGoesPurrrApp.

    Assumes the host has `self.mode_manager` (with `app_settings`),
    `self.haptic_engine` and `self.log_message`.
    """

    # ------------------------------------------------------------------
    # Lifecycle — main.py calls init before the UI exists, shutdown on quit
    # ------------------------------------------------------------------

    def _steamvr_toys_init(self) -> None:
        import steamvr_toy_driver_installer as installer

        self._steamvr_toy_installer = installer
        self._steamvr_toy_bridge = SteamVRToyBridge()
        self._steamvr_toy_bridge.set_logger(self._steamvr_toys_log)
        self._steamvr_toy_batteries: Dict[str, float] = {}
        if self._steamvr_toys_is_enabled():
            if not installer.steamvr_present():
                # Nothing to show the toys in, and nothing of SteamVR's to
                # touch. The next launch after SteamVR arrives picks it up.
                self._steamvr_toys_log("[steamvr-toys] SteamVR not found on this PC — nothing to do")
                return
            self._steamvr_toys_ensure_installed()
            self._steamvr_toy_bridge.start()
            self._steamvr_toys_sync()

    def _steamvr_toys_shutdown(self) -> None:
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if bridge is not None:
            bridge.clear_devices()
            bridge.stop()

    def _steamvr_toys_log(self, msg: str) -> None:
        """Log through the UI once it exists; print before that."""
        if getattr(self, "ui", None) is not None:
            try:
                self.log_message(msg)
                return
            except Exception:
                pass
        print(msg)

    # ------------------------------------------------------------------
    # Settings <-> facade
    # ------------------------------------------------------------------

    def _steamvr_toys_is_enabled(self) -> bool:
        installer = getattr(self, "_steamvr_toy_installer", None)
        if installer is None or not installer.is_supported():
            return False
        return bool(self.mode_manager.app_settings.get(SETTING_KEY, DEFAULT_ON))

    def _steamvr_toys_ensure_installed(self) -> Dict[str, Any]:
        """Lay the driver down (or refresh it after an app update).

        Returns {"installed_now": bool, "error_kind": str}; error_kind is
        '' on success, else the installer's kind ('dll_locked', ...).
        """
        installer = self._steamvr_toy_installer
        result = {"installed_now": False, "error_kind": ""}
        try:
            if not installer.is_installed() or installer.needs_update():
                installer.install_or_raise(self._steamvr_toys_log)
                result["installed_now"] = True
        except installer.InstallError as e:
            result["error_kind"] = e.kind
            self._steamvr_toys_log(f"[steamvr-toys] install failed ({e.kind}): {e}")
        return result

    def get_steamvr_toys_status(self) -> Dict[str, Any]:
        """Safe before `_steamvr_toys_init()` has run."""
        import steamvr_toy_driver_installer as installer
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        return {
            "supported": installer.is_supported(),
            "steamvr": installer.steamvr_present(),
            "enabled": bool(self.mode_manager.app_settings.get(SETTING_KEY, DEFAULT_ON)),
            "installed": installer.is_installed(),
            "connected": bool(bridge.is_connected) if bridge else False,
        }

    def set_steamvr_toys_enabled(self, enabled: bool) -> Dict[str, Any]:
        """Switch the feature on or off. The returned status adds
        `error_kind` ('' on success, 'no_steamvr', or an installer kind),
        `installed_now` and `driver_loaded` (SteamVR is running with the
        driver right now — False means the toys appear from SteamVR's next
        start) so the UI can say what happens next."""
        self.mode_manager.app_settings.set(SETTING_KEY, bool(enabled))
        installer = getattr(self, "_steamvr_toy_installer", None)
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        outcome = {"installed_now": False, "error_kind": "", "driver_loaded": False}
        if bridge is not None and installer is not None:
            if enabled:
                if not installer.steamvr_present():
                    outcome["error_kind"] = "no_steamvr"
                else:
                    outcome.update(self._steamvr_toys_ensure_installed())
                    # Asked before the bridge starts, so the probe never
                    # competes with it for the driver's one connection.
                    outcome["driver_loaded"] = driver_listening()
                    bridge.start()
                    self._steamvr_toys_sync()
            else:
                # Emptying the list first lets the driver mark every toy
                # disconnected, so they leave SteamVR's strip right away.
                bridge.clear_devices()
                bridge.stop()
                # Off means out of SteamVR: unregistered, SteamVR stops
                # loading the driver from its next start. The files stay,
                # so switching back on is only a registration.
                installer.uninstall(log=self._steamvr_toys_log)
        status = self.get_steamvr_toys_status()
        status.update(outcome)
        return status

    # ------------------------------------------------------------------
    # Engine-event hooks — main.py's queue handler calls these
    # ------------------------------------------------------------------

    def steamvr_toys_on_devices_changed(self) -> None:
        """A toy connected or disconnected."""
        if self._steamvr_toys_is_enabled():
            self._steamvr_toys_sync()

    def steamvr_toys_on_battery(self, device_name: str, level: float) -> None:
        try:
            level = float(level)
        except (TypeError, ValueError):
            return
        batteries = getattr(self, "_steamvr_toy_batteries", None)
        if batteries is None:
            return
        batteries[device_name] = level
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if bridge is not None and self._steamvr_toys_is_enabled():
            bridge.update_battery(self.steamvr_toy_serial(device_name), level)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def steamvr_toy_serial(device_name: str) -> str:
        """Stable SteamVR serial for a toy, from its name, so a reconnecting
        toy reuses its SteamVR slot instead of adding a duplicate."""
        safe = "".join(ch if ch.isalnum() else "_" for ch in (device_name or "toy"))
        return f"OGP_TOY_{safe.upper()}"[:64]

    def _steamvr_toy_icon(self, device_name: str) -> "tuple[str, str]":
        """(icon_key, icon_path) for the driver: the key SteamVR matches its
        per-toy icon set by, and the icon file as a fallback. ('', '') when
        there is no icon for this toy."""
        from ui import lovense_icons
        try:
            override = self.mode_manager.get_profile_config(device_name, "icon_override", None)
        except Exception:
            override = None
        key = lovense_icons.resolve_key(device_name, override)
        installer = getattr(self, "_steamvr_toy_installer", None)
        if not key or installer is None:
            return "", ""
        if not installer.resolve_installed_icon_path(f"{key}.png"):
            return "", ""
        return key, f"{{oscgoespurrr}}/icons/{key}.png"

    def _steamvr_toys_entries(self) -> List[ToyEntry]:
        engine = getattr(self, "haptic_engine", None)
        if engine is None:
            return []
        try:
            names = list(engine.list_connected_device_names())
        except Exception:
            return []
        batteries = getattr(self, "_steamvr_toy_batteries", {}) or {}
        entries = []
        for name in names:
            key, path = self._steamvr_toy_icon(name)
            entries.append(ToyEntry(
                serial=self.steamvr_toy_serial(name),
                name=name,
                icon_key=key,
                icon_path=path,
                battery=float(batteries.get(name, 1.0)),
            ))
        return entries

    def _steamvr_toys_sync(self) -> None:
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if bridge is not None:
            bridge.set_devices(self._steamvr_toys_entries())
