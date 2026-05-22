"""Profile-CRUD controller facade.

Mixin: global + avatar profile management + clipboard. Composed into
OscGoesPurrrApp. Relies on `self.profile_manager`, `self.ui`,
`self.log_message`, `self.force_recalculate`, and `self.thread_queue`."""

import threading
from typing import Any, Dict, List


class ProfilesFacade:

    def _refresh_profile_buttons_ui(self) -> None:
        """Tell the UI to redraw its profile buttons. No-op when self.ui is
        None or doesn't expose the method (early startup, headless tests)."""
        ui = getattr(self, "ui", None)
        if ui is None:
            return
        refresh = getattr(ui, "_refresh_profile_buttons", None)
        if refresh is not None:
            refresh()

    def _seed_profile_with_known_devices(self, profile_name: str) -> None:
        """Make sure every known toy has a default entry in the given profile.

        This is what gives new/empty profiles the "remember my toys" behaviour
        — the user gets blank-but-present device cards to configure, rather
        than having to reconnect each toy to see it.
        """
        profile = self.profile_manager.profiles.setdefault(profile_name, {})
        known = self.profile_manager.known_devices.all()
        if not known:
            return
        added = []
        for name, meta in known.items():
            if name in profile:
                continue
            motor_count = int(meta.get("motor_count", 1))
            entry = {"motor_count": motor_count}
            if meta.get("motor_kinds"):
                entry["motor_kinds"] = list(meta["motor_kinds"])
            # Default per-motor OSC addresses match what build_device_list_ui
            # would seed for a freshly-discovered device.
            addrs = {}
            for i in range(motor_count):
                suffix = f"_{i}" if motor_count > 1 else ""
                addrs[str(i)] = [f"{name.replace(' ', '_')}{suffix}"]
            entry["osc_addresses"] = addrs
            profile[name] = entry
            added.append(name)
        if added:
            self.profile_manager.save_profiles()
            print(f"[profiles] seeded profile '{profile_name}' with {len(added)} known toy(s): {added}")

    def switch_profile(self, profile_name: str):
        """Switch to a different profile and reload the device UI.

        Auto-creates an empty profile if `profile_name` doesn't exist yet, so
        the four dashboard slots feel like real profile slots even before the
        user has saved anything to them.

        Args:
            profile_name: Name of the profile to switch to.
        """
        if profile_name not in self.profile_manager.profiles:
            self.profile_manager.profiles[profile_name] = {}
            self.profile_manager.save_profiles()
            self.log_message(f"Created new profile: {profile_name}")

        # Toys are global; profiles are pure settings overlays. Every profile
        # therefore has an entry for every known toy (default settings until
        # the user changes them). "Delete" is the explicit way to forget a toy
        # across all profiles — see delete_stored_device.
        self._seed_profile_with_known_devices(profile_name)

        self.profile_manager.current_profile = profile_name
        self.current_profile = profile_name
        # Remember this choice for the currently-loaded avatar (if any) so
        # the next time that avatar loads, this global stays selected
        # instead of auto-switching to a bound avatar profile.
        self.profile_manager.record_choice("global", profile_name)

        # Per-toy mute is a session-level safety toggle, not a configured
        # preference — drop it whenever the profile changes so a mute from
        # the previous config doesn't silently follow the user.
        if hasattr(self, "clear_all_device_mutes"):
            self.clear_all_device_mutes()

        # Clear cached UI frames so build_stored_devices_ui doesn't short-circuit
        # and leave the previous profile's device cards on screen when the new
        # profile is empty.
        self.ui.clear_device_caches()

        self.ui.build_stored_devices_ui()
        self._refresh_profile_buttons_ui()
        if hasattr(self, "force_recalculate"):
            self.force_recalculate()
        self.log_message(f"Switched to profile: {profile_name}")

        # Refresh the profile buttons on the Dashboard
        self._refresh_profile_buttons_ui()
    
    def create_profile(self, base_name: str = "New Profile") -> str:
        """Create a fresh profile and return its name. If `base_name` is
        already taken, appends ' 2', ' 3', ... until a free name is found."""
        existing = set(self.profile_manager.profiles.keys())
        name = base_name
        n = 2
        while name in existing:
            name = f"{base_name} {n}"
            n += 1
        self.profile_manager.profiles[name] = {}
        self._seed_profile_with_known_devices(name)
        self.profile_manager.save_profiles()
        self.log_message(f"Created profile '{name}'")
        self._refresh_profile_buttons_ui()
        return name

    def delete_profile(self, profile_name: str):
        """Delete a profile. Refuses to delete the last remaining profile.
        If the deleted profile is currently active, switches to another."""
        if profile_name not in self.profile_manager.profiles:
            return
        if len(self.profile_manager.profiles) <= 1:
            self.log_message("Cannot delete the only remaining profile.")
            return

        del self.profile_manager.profiles[profile_name]
        self.profile_manager.save_profiles()
        self.log_message(f"Deleted profile '{profile_name}'")

        if self.profile_manager.current_profile == profile_name:
            fallback = next(iter(self.profile_manager.profiles.keys()))
            self.switch_profile(fallback)
        else:
            self._refresh_profile_buttons_ui()

    def rename_profile(self, old_name: str, new_name: str):
        """Rename a profile, or create a new one if `old_name` is a placeholder
        slot (e.g. "Profile 3") that hasn't been used yet.

        Args:
            old_name: Current name of the profile (or placeholder slot name).
            new_name: New name for the profile.
        """
        new_name = new_name.strip()
        if not new_name:
            return
        if new_name in self.profile_manager.profiles and new_name != old_name:
            self.log_message(f"Cannot rename: profile '{new_name}' already exists.")
            return

        if old_name in self.profile_manager.profiles:
            data = self.profile_manager.profiles.pop(old_name)
            self.profile_manager.profiles[new_name] = data
            self.log_message(f"Renamed profile '{old_name}' to '{new_name}'")
        else:
            # Renaming an empty placeholder slot creates a fresh profile,
            # seeded with all previously-seen toys (default settings).
            self.profile_manager.profiles[new_name] = {}
            self._seed_profile_with_known_devices(new_name)
            self.log_message(f"Created profile '{new_name}'")

        self.profile_manager.save_profiles()

        if self.profile_manager.current_profile == old_name:
            self.profile_manager.current_profile = new_name
            self.current_profile = new_name

        self._refresh_profile_buttons_ui()

    # ====================
    # Avatar profiles + clipboard (copy/paste)
    # ====================

    def _schedule_avatar_id_probe(self):
        """Spawn a short background poll that asks VRChat's OSCQuery server
        for the current avatar id. Posts an avatar_change queue message on
        success. Safe to call repeatedly — it's just a few HTTP GETs."""
        def _probe():
            import time as _t
            # OSCQuery mDNS discovery + JSON build can lag a couple of seconds
            # after OSC starts. Retry briefly so the user doesn't see "not
            # detected" on first launch.
            for attempt in range(6):
                if not self.osc_manager or not self.osc_manager.is_connected:
                    return
                avatar_id = self.osc_manager.query_avatar_id()
                if avatar_id:
                    self.thread_queue.put(("avatar_change", avatar_id))
                    return
                _t.sleep(1.0)
        threading.Thread(target=_probe, daemon=True).start()

    def _on_avatar_change(self, avatar_id: str):
        """Handle a fresh /avatar/change message from VRChat.

        If an avatar profile is bound to this id, it becomes the active
        profile silently — device cards rebuild against the new settings.
        Otherwise we keep the currently-selected global profile.
        """
        avatar_id = (avatar_id or "").strip()
        previously_active = self.profile_manager.get_active_profile_info()
        bound_name = self.profile_manager.set_current_avatar(avatar_id)
        now_active = self.profile_manager.get_active_profile_info()

        if previously_active != now_active:
            if now_active["kind"] == "avatar":
                self.log_message(
                    f"Avatar changed → activating avatar profile '{now_active['name']}'"
                )
            else:
                self.log_message(
                    f"Avatar changed → no bound profile, staying on global '{now_active['name']}'"
                )
            self.ui.clear_device_caches()
            self.ui.build_stored_devices_ui()
            self.force_recalculate()
        else:
            self.log_message(f"Avatar changed (id={avatar_id or 'unknown'})")

        self._refresh_profile_buttons_ui()

        # Avatar swaps reset every avatar parameter on the VRChat side, so
        # the bHaptics-connected bool needs to be re-asserted whether or not
        # the engine state changed.
        try:
            self._bhaptics_send_connected_bool()
        except Exception:
            pass

    def get_current_avatar_id(self) -> str:
        return self.profile_manager.current_avatar_id or ""

    def get_active_profile_info(self) -> dict:
        """{"kind": "avatar"|"global", "name": str} — for UI display."""
        return self.profile_manager.get_active_profile_info()

    def get_avatar_profile_names(self) -> list:
        return list(self.profile_manager.avatar_profiles.keys())

    def get_avatar_binding(self, profile_name: str) -> str:
        return self.profile_manager.avatar_bindings.get(profile_name, "")

    def create_avatar_profile(self, base_name: str = "New Avatar Profile") -> str:
        """Create an avatar profile bound to the *current* avatar id and seeded
        from the currently-active profile's settings (per design decision).
        """
        active = self.profile_manager.get_active_profile_dict() or {}
        new_name = self.profile_manager.create_avatar_profile(
            base_name=base_name,
            avatar_id=self.profile_manager.current_avatar_id,
            copy_from=active,
        )
        self.log_message(f"Created avatar profile '{new_name}'")
        # The new profile is automatically bound to the current avatar (if any),
        # which makes it the active profile. Rebuild device cards so the user
        # sees the inherited settings under the new profile name.
        self.ui.clear_device_caches()
        self.ui.build_stored_devices_ui()
        self._refresh_profile_buttons_ui()
        return new_name

    def delete_avatar_profile(self, name: str):
        if name not in self.profile_manager.avatar_profiles:
            return
        was_active = (self.profile_manager.get_active_profile_info()
                      == {"kind": "avatar", "name": name})
        self.profile_manager.delete_avatar_profile(name)
        self.log_message(f"Deleted avatar profile '{name}'")
        if was_active:
            self.ui.clear_device_caches()
            self.ui.build_stored_devices_ui()
            self.force_recalculate()
        self._refresh_profile_buttons_ui()

    def rename_avatar_profile(self, old: str, new: str):
        if self.profile_manager.rename_avatar_profile(old, new):
            self.log_message(f"Renamed avatar profile '{old}' → '{new}'")
        self._refresh_profile_buttons_ui()

    def bind_avatar_profile_to_current(self, name: str):
        """Bind `name` to the current avatar and record it as the user's
        remembered choice for that avatar."""
        self.profile_manager.bind_avatar_profile(
            name, self.profile_manager.current_avatar_id
        )
        self.log_message(
            f"Bound avatar profile '{name}' to "
            f"{self.profile_manager.current_avatar_id or 'no avatar'}"
        )
        self.ui.clear_device_caches()
        self.ui.build_stored_devices_ui()
        self.force_recalculate()
        self._refresh_profile_buttons_ui()

    def copy_profile(self, kind: str, name: str):
        """Copy a profile into the in-memory clipboard. `kind` is 'global'|'avatar'."""
        ok = self.profile_manager.copy_profile_to_clipboard(kind, name)
        if ok:
            self.log_message(f"Copied {kind} profile '{name}' to clipboard")
        self._refresh_profile_buttons_ui()

    def paste_profile(self, target_kind: str):
        """Paste the clipboard into a new profile in the target section."""
        bind_avatar = self.profile_manager.current_avatar_id if target_kind == "avatar" else None
        name = self.profile_manager.paste_profile(target_kind, avatar_id=bind_avatar)
        if name:
            self.log_message(f"Pasted clipboard → new {target_kind} profile '{name}'")
            if target_kind == "avatar" and bind_avatar:
                self.ui.clear_device_caches()
                self.ui.build_stored_devices_ui()
                self.force_recalculate()
            self._refresh_profile_buttons_ui()
        else:
            self.log_message("Paste failed — clipboard is empty")

    def paste_profile_into(self, target_kind: str, target_name: str):
        """Overwrite an existing profile with the current clipboard contents,
        then clear the clipboard so the row toggles back to Copy mode."""
        ok = self.profile_manager.paste_into_profile(target_kind, target_name)
        if not ok:
            self.log_message("Paste failed — clipboard empty or target missing")
            return
        self.profile_manager.clear_clipboard()
        self.log_message(
            f"Pasted clipboard onto {target_kind} profile '{target_name}'"
        )
        # If we just overwrote the currently-active profile, reapply it so
        # devices pick up the new settings immediately.
        active = self.profile_manager.get_active_profile_info() or {}
        if active.get("kind") == target_kind and active.get("name") == target_name:
            self.ui.clear_device_caches()
            self.ui.build_stored_devices_ui()
            self.force_recalculate()
        self._refresh_profile_buttons_ui()

    def clear_clipboard(self):
        """Cancel a pending copy — used when the user clicks the source row
        again to dismiss the paste-mode UI."""
        if not self.profile_manager.has_clipboard():
            return
        self.profile_manager.clear_clipboard()
        self._refresh_profile_buttons_ui()

    def has_clipboard(self) -> bool:
        return self.profile_manager.has_clipboard()

    def get_clipboard_source_name(self) -> str:
        return self.profile_manager.get_clipboard_source_name() or ""

    def get_clipboard_source_kind(self) -> str:
        """Facade: which section ('global'|'avatar') the clipboard came from."""
        return self.profile_manager.get_clipboard_source_kind() or ""

    # ---- Profile-list facades (used by the UI to render rows) ----

    def get_global_profile_names(self) -> List[str]:
        """Facade: ordered list of every global profile's name."""
        return list(self.profile_manager.profiles.keys())

    def get_current_global_profile_name(self) -> str:
        """Facade: the global profile most recently selected by the user.
        Falls back to the resolver's active name if none is set."""
        return self.profile_manager.current_profile or ""

    def profile_exists(self, kind: str, name: str) -> bool:
        """Facade: True if a profile with this name exists in the given pool."""
        pool = (self.profile_manager.profiles if kind == "global"
                else self.profile_manager.avatar_profiles)
        return name in pool

    def get_active_profile_dict(self) -> Dict[str, Any]:
        """Facade: the live dict of per-device settings the router/UI read."""
        return self.profile_manager.get_active_profile_dict() or {}
