"""SteamVR-toys facade mixin.

Owns the optional SteamVR virtual-device feature: install / register the
trampoline driver, run the IPC bridge that mirrors the user's connected
Buttplug toys into SteamVR's device strip.

Sealed-box rules: the UI calls these methods, never `self.steamvr_toy_bridge`
or the installer module directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from steamvr_toy_bridge import SteamVRToyBridge, ToyEntry
from ui import lovense_icons


class SteamVRToysFacade:
    """Mixin: SteamVR virtual-toy-device methods. Composed into OscGoesPurrrApp."""

    # ------------------------------------------------------------------
    # Initialisation hook — main.py calls this once during _setup_components
    # ------------------------------------------------------------------

    def _steamvr_toys_init(self) -> None:
        """Construct the bridge and start it if the user has the feature on.

        Safe to call before `self.ui` exists — the bridge logger falls back
        to print() until the UI is wired in via `_steamvr_toys_attach_ui()`.
        """
        # Lazy imports — installer touches the filesystem; keep this lightweight
        # for unit tests that don't use the SteamVR side.
        import steamvr_toy_driver_installer as installer

        self._steamvr_toy_installer = installer
        self._steamvr_toy_bridge = SteamVRToyBridge()
        # Use a safe-until-UI-ready logger; the controller will swap in
        # self.log_message via `_steamvr_toys_attach_ui()` once UI exists.
        self._steamvr_toy_bridge.set_logger(self._steamvr_toys_safe_log)

        if self._steamvr_toys_is_enabled():
            if not installer.is_installed():
                installer.install(log=self._steamvr_toys_safe_log)
            self._steamvr_toy_bridge.start()
            # Push whatever toys are already connected (rare on startup but
            # possible if Intiface was already running with auto-connect).
            self._steamvr_toys_sync_from_engine()

    def _steamvr_toys_attach_ui(self) -> None:
        """Swap the bridge's logger over to the live UI sink once the UI
        is constructed. main.py calls this right after `self.ui = ...`."""
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if bridge is not None:
            bridge.set_logger(self.log_message)

    def _steamvr_toys_safe_log(self, msg: str) -> None:
        """Pre-UI logger: route through self.ui.log_message when it exists,
        otherwise fall back to print()."""
        ui = getattr(self, "ui", None)
        if ui is not None:
            try:
                ui.log_message(msg)
                return
            except Exception:
                pass
        print(msg)

    # ------------------------------------------------------------------
    # Settings <-> facade
    # ------------------------------------------------------------------

    def _steamvr_toys_is_enabled(self) -> bool:
        return bool(self.profile_manager.steamvr_settings.get_show_toys())

    def get_steamvr_toys_status(self) -> Dict[str, Any]:
        # Status must be safe to call before `_steamvr_toys_init()` has run,
        # because the Settings tab queries it during UI construction (which
        # happens before _setup_components finishes wiring engines).
        import steamvr_toy_driver_installer as installer
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        return {
            "supported": installer.is_supported(),
            "enabled": self._steamvr_toys_is_enabled(),
            "installed": installer.is_installed(),
            "bridge_running": (bridge.is_running if bridge else False),
            "bridge_connected": (bridge.is_connected if bridge else False),
        }

    def set_steamvr_toys_enabled(self, enabled: bool) -> Dict[str, Any]:
        """Toggle the feature. Returns a status dict the UI can read so it
        can show a 'restart SteamVR' hint after enabling for the first time,
        OR a clear failure message when the bundled DLL is missing (i.e.
        nobody has built the driver yet for this checkout)."""
        installer = getattr(self, "_steamvr_toy_installer", None)
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if installer is None or bridge is None:
            return self.get_steamvr_toys_status()

        self.profile_manager.steamvr_settings.set_show_toys(bool(enabled))

        first_install = False
        install_failed = False
        if enabled:
            if not installer.is_installed():
                first_install = installer.install(log=self.log_message)
                if not first_install:
                    install_failed = True
            bridge.start()
            self._steamvr_toys_sync_from_engine()
        else:
            bridge.clear_devices()
            bridge.stop()
            # Leave the driver registered. Disabling is just "stop reporting
            # devices" — the user can flip it back on without a restart.

        status = self.get_steamvr_toys_status()
        status["first_install"] = bool(first_install)
        status["install_failed"] = bool(install_failed)
        return status

    def uninstall_steamvr_toys_driver(self, remove_files: bool = True) -> bool:
        """User-initiated full uninstall (called from a Settings button)."""
        installer = getattr(self, "_steamvr_toy_installer", None)
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if bridge is not None:
            bridge.clear_devices()
            bridge.stop()
        if installer is None:
            return False
        return installer.uninstall(log=self.log_message, remove_files=remove_files)

    def reinstall_steamvr_toys_driver(self) -> Dict[str, Any]:
        """User-initiated force-reinstall. Copies the bundled DLL/manifest
        on top of any existing install (so a freshly-rebuilt DLL replaces
        a stale one) and re-registers the path with SteamVR.

        Returns a dict with `ok`, `dll`, `registered`, and `error_kind`
        ('dll_locked' | 'bundle_missing' | 'copy_failed' | 'register_failed'
        | '' on success). The UI uses error_kind to show a specific hint
        instead of guessing.
        """
        installer = getattr(self, "_steamvr_toy_installer", None)
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        result: Dict[str, Any] = {"ok": False, "dll": "", "registered": False,
                                  "error_kind": ""}
        if installer is None:
            self.log_message("[steamvr-toys] reinstall: installer not initialised")
            result["error_kind"] = "uninitialised"
            return result

        # Bridge has to release the IPC socket *before* we overwrite the DLL.
        if bridge is not None:
            bridge.clear_devices()

        try:
            installer.install_or_raise(self.log_message)
            ok = True
        except installer.InstallError as e:
            ok = False
            result["error_kind"] = e.kind
            self.log_message(f"[steamvr-toys] reinstall failed ({e.kind}): {e}")

        result["ok"] = bool(ok)
        result["dll"] = str(installer.driver_dll_path())
        result["registered"] = installer.is_installed()

        # Re-arm the bridge so it reconnects to whichever vrserver is up.
        if bridge is not None and self._steamvr_toys_is_enabled():
            if not bridge.is_running:
                bridge.start()
            self._steamvr_toys_sync_from_engine()

        if ok:
            self.log_message(
                "[steamvr-toys] driver reinstalled. If the DLL was rebuilt, "
                "restart SteamVR for the new code to take effect."
            )
        return result

    # ------------------------------------------------------------------
    # Engine-event hooks — main.py's queue handler calls these
    # ------------------------------------------------------------------

    def steamvr_toys_on_devices_changed(self) -> None:
        """A toy connected / disconnected / had its feature set re-detected."""
        if not self._steamvr_toys_is_enabled():
            return
        self._steamvr_toys_sync_from_engine()

    def steamvr_toys_on_battery(self, device_name: str, level: float) -> None:
        if not self._steamvr_toys_is_enabled():
            return
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if bridge is None:
            return
        bridge.update_battery(self._steamvr_toys_serial_for(device_name), float(level))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _steamvr_toys_serial_for(device_name: str) -> str:
        """Stable serial string SteamVR uses as a uniqueness key. We base it
        on the toy's user-visible name so reconnecting the same toy reuses
        the same SteamVR slot instead of duplicating."""
        safe = "".join(ch if ch.isalnum() else "_" for ch in (device_name or "toy"))
        return f"OGP_TOY_{safe.upper()}"[:64]

    def _steamvr_toys_icon_for(self, device_name: str) -> tuple[Optional[str], Optional[str]]:
        """Resolve `device_name` to (icon_key, icon_path) for IPC to the driver.

        - icon_key is the bare lookup name (e.g. "edge_2"). The driver
          sets this as Prop_ModelNumber_String so SteamVR matches it
          against a key in driver.vrresources' statusicons map.
        - icon_path is the substitution-style filesystem reference
          (e.g. "{oscgoespurrr}/icons/edge_2.png"), used as a fallback
          when the JSON statusicons lookup misses.

        Returns (None, None) when the icon catalog has no match.
        """
        try:
            override = self.profile_manager.get_profile_config(device_name, "icon_override", None)
        except Exception:
            override = None
        key = lovense_icons.resolve_key(device_name, override)
        if not key:
            return None, None
        installer = getattr(self, "_steamvr_toy_installer", None)
        if installer is None:
            return None, None
        if not installer.resolve_installed_icon_path(f"{key}.png"):
            return None, None
        return key, f"{{oscgoespurrr}}/icons/{key}.png"

    def _steamvr_toys_sync_from_engine(self) -> None:
        bridge = getattr(self, "_steamvr_toy_bridge", None)
        if bridge is None:
            return
        engine = getattr(self, "haptic_engine", None)
        if engine is None:
            bridge.clear_devices()
            return
        names: List[str] = engine.list_connected_device_names()
        battery_cache: Dict[str, float] = getattr(self, "_battery_cache", {}) or {}

        entries: List[ToyEntry] = []
        for name in names:
            icon_key, icon_path = self._steamvr_toys_icon_for(name)
            entries.append(ToyEntry(
                serial=self._steamvr_toys_serial_for(name),
                name=name,
                icon_key=icon_key or "",
                icon_path=icon_path or "",
                battery=float(battery_cache.get(name, 1.0)),
            ))
        bridge.set_devices(entries)
