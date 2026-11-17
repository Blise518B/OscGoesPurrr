"""App-level settings (auto_connect, auto_refresh, modes, etc.)."""

import json
import os
from typing import Any, Dict

import settings_history
from utilities import atomic_write_json

from ._paths import APP_SETTINGS_FILE


# Default app settings
DEFAULT_APP_SETTINGS = {
    "auto_connect": True,
    "auto_refresh": True,
    # While no toy is connected, a scan for toys starts every this many
    # seconds (constants.TOY_SEARCH_RATE_RANGE); with one connected, every
    # AUTO_REFRESH_RATE_S.
    "toy_scan_interval_s": 5,
    "auto_connect_osc": True,
    "bind_all_interfaces": True,
    "hide_console": True,
    "minimize_to_tray": False,
    # When ON, each avatar remembers the mode that was active the last time
    # it was worn and restores it on avatar change. OFF (default) = the
    # active mode simply carries across avatars.
    "avatar_modes_enabled": False,
    # Anti-stuck safety cutoff for the toy (Buttplug) path.
    # VRChat OSC only fires on parameter change, so a frozen SPS proximity
    # (avatar swap, partner leaves, OSC routing loss) would otherwise drive a
    # motor at its last value forever. Two-timer model: a mid-range value
    # stuck for `active_s` is cut hard; a saturated (~100%) value gets the
    # longer `peaked_s` fuse then a gentle ramp. Set on the Toys page; each
    # toy has its own on / off too (antistuck.py). The suits, the trackers
    # and the PSVR2 have their own since 2026-11-17, seeded from these.
    "toy_antistuck_enabled": True,
    "toy_antistuck_active_s": 1,
    "toy_antistuck_peaked_s": 10,
    # Off while you're away (away_off.py, Settings → Safety): while
    # VRChat's AFK, GoGo Loco's AFK (VRCEmote 101) or a picked parameter
    # is on, everything is held off -- the same Off as OGP/Off, without
    # touching that switch. On by default (decided 2026-11-14).
    "away_off_enabled": True,
    "away_off_vrchat_afk": True,
    "away_off_gogo_afk": True,
    "away_off_params": [],
    # How often the router re-evaluates all motors. Time-constant math
    # (decay_tau / attack_ms / release_ms) is wall-clock-based so this
    # is purely a CPU-vs-fidelity knob — no recalibration needed when
    # the rate changes. 30 / 60 / 90 / 120 are the UI presets; any
    # int in [10, 240] is accepted. Default matches the common headset
    # refresh rate (Index, Quest 2/3) so the router stays in step with
    # VRChat's avatar-parameter update cadence.
    "router_poll_rate_hz": 90,
    # Feature toggles — turn off subsystems the user doesn't need so their
    # background threads / OSC traffic don't run. All default ON to match
    # pre-toggle behaviour.
    "feature_osc_inspector": True,
    "feature_intiface": True,
    # Subscribe the OSC receive port at the local OSC Router 518, so VRChat
    # data keeps arriving when VRChat's mDNS discovery dies mid-session
    # (see 518Hub/docs/STANDARD.md). Harmless when no router runs.
    "feature_osc_router_518": True,
    # Intiface server provisioning. True (default) = OscGoesPurrr spawns and
    # supervises its own bundled intiface-engine, so no separate Intiface
    # Central launch is needed. False = connect to a user-run Intiface Central
    # (the original behavior). See intiface_connection.py and the Settings →
    # Intiface Engine toggle.
    "use_integrated_intiface": True,
    # Where that user-run Intiface is: "" (default) = find it by itself --
    # announced on the network (mDNS), else this PC -- or a typed
    # "host:port", e.g. a phone running Intiface Central on the same
    # Wi-Fi. See intiface_external.py.
    "intiface_address": "",
    # Show connected toys in SteamVR's device list (icon + battery) through
    # the bundled toy driver. On by default: installs a small SteamVR driver
    # when SteamVR is on the PC; switching it off takes the driver out of
    # SteamVR again. Toys never appear as trackers.
    "show_toys_in_steamvr": True,
    # A low→high chime when a toy connects, high→low when one drops (see
    # toy_sounds.py). On by default — in VR it's the only sign a toy
    # dropped; Settings → Connection Settings turns it off.
    "toy_connect_sounds": True,
    # Their volume, 0-100 % (toy_sounds.volume_to_peak maps it on a
    # squared curve; 60 is about a third of full scale).
    "toy_connect_sounds_volume": 60,
    # Ask GitHub once at launch whether a newer release exists (a single
    # HTTPS request — nothing downloads or installs itself). A newer release
    # gets a line in Settings and a window at launch.
    "update_check_enabled": True,
    # The release the user ticked "don't remind me" for in that window; a
    # later release pops up again.
    "update_popup_skipped_version": "",
    # Slowly drift the background gradient (~12 fps paint layer, paused
    # while minimized). Only engages on gradient color profiles (Purrple
    # gradient, Aurora, Custom with gradient); flat profiles ignore it.
    # 518 design system mode: "neon" (default) or "midnight" -- "Vibrant"
    # and "Darker" in Settings → Appearance. Like the colour below it
    # applies while the app runs.
    "ui_mode": "neon",
    # The newest version whose "What's new" notes this install has been
    # shown (whats_new.py); "" = none yet. A later build with notes opens
    # the window once at launch.
    "whats_new_seen_version": "",
    # "What are you here for?" (interests.py) was answered or skipped.
    # False -- a new install, or one from before the question -- asks it
    # once at launch.
    "interests_asked": False,
    # The guided tour (ui/tour.py) started by itself (a new install, after
    # the question above) or was offered (an older one, on the update that
    # brought it). False -- not yet: it happens once at launch.
    "tour_offered": False,
    # Settings → Appearance → Colour: the hue (OKLCH degrees, 0-360) every
    # green in the UI is turned to, or None for the house green. Changing
    # it applies while the app runs (ui/live_theme.py); constants.py reads
    # it at import so the next launch starts in it.
    "ui_accent_hue": None,
    # Settings → Appearance → Other colours: identity colours set by hand,
    # {"pink": hue, ...}. One left out moves by itself when the colour
    # above lands too close to it (constants.IDENTITY_HUES).
    "ui_identity_hues": {},
    # The Add Variable picker's filter chips, once for every picker:
    # {group key: hidden} (param_filters.SETTING_KEY / GROUPS). {} -- or a
    # group not named -- takes the group's default.
    "picker_hidden_groups": {},
    # Friends → a friend's shockers: whose shocker buttons every panel
    # shows, "pishock" (PiShock's own panel, the default) or "openshock"
    # (OpenShock's card with Live control) -- shocker_layout.py. Only a
    # face: both send the same, and the receiver's rules hold either way.
    "shocker_layout": "pishock",
}


# Kept here but no setting, so never a Ctrl+Z step (settings_history.py):
# where windows are and how big, folds and docks, what you've already been
# shown, offered or asked (What's new, the questions, the tour), the
# variable picker's filter chips.
NOT_SETTINGS = frozenset({
    "window_geometry", "window_state",
    "friends_window_state", "friends_window_on_top",
    "params_dock_w", "home_setup_compact", "picker_hidden_groups",
    "whats_new_seen_version", "interests_asked", "update_popup_skipped_version",
    "tour_offered",
})
# ...and any key that ends like one of those
NOT_SETTINGS_ENDINGS = ("_geometry", "_window_state", "_dock_w", "_open", "_folded",
                        "_collapsed", "_expanded", "_seen", "_shown", "_offered",
                        "_seen_version", "_skipped_version", "_asked")

# Settings → their names on the Settings page, for "Undid: ..." when the
# control it was changed on has no name of its own.
DESCRIBE = {
    "auto_connect": "Auto Connect to Intiface",
    "auto_refresh": "Auto Refresh Devices",
    "auto_connect_osc": "Auto Connect to VRChat",
    "bind_all_interfaces": "OSC network bind",
    "avatar_modes_enabled": "Remember mode per avatar",
    "toy_antistuck_enabled": "Toys' anti-stuck",
    "toy_antistuck_active_s": "Toys' anti-stuck: stuck part-way",
    "toy_antistuck_peaked_s": "Toys' anti-stuck: stuck at the top",
    "away_off_enabled": "Off while you're away",
    "router_poll_rate_hz": "Update rate",
    "toy_connect_sounds": "Toy connect sounds",
    "toy_connect_sounds_volume": "Toy connect sounds volume",
    "ui_mode": "Vibrant / Darker",
    "ui_accent_hue": "Colour",
    "ui_identity_hues": "Other colours",
    "show_toys_in_steamvr": "Show toys in SteamVR",
    "use_integrated_intiface": "Intiface engine",
    "intiface_address": "Intiface address",
    "shocker_layout": "Shocker buttons",
}


def is_setting(key: Any) -> bool:
    """False for what app_settings.json keeps that is no setting."""
    key = str(key)
    return key not in NOT_SETTINGS and not key.endswith(NOT_SETTINGS_ENDINGS)


class AppSettingsManager:
    """Manages app-level settings (auto_connect, auto_refresh, etc.)"""

    HISTORY_KEY = "app"
    HISTORY_LABEL = "Settings"

    def __init__(self):
        self.settings: Dict[str, Any] = {}
        # True when this launch found no settings file: a first install,
        # not an update (nothing to tell it about what changed).
        self.created_fresh = False
        self._load_or_create_defaults()
        settings_history.track(self)

    # -- Ctrl+Z (settings_history.py) ---------------------------------------

    @staticmethod
    def history_ignore(path, before, after) -> bool:
        return not path or not is_setting(path[0])

    @staticmethod
    def history_asks(current: Dict[str, Any], target: Dict[str, Any]) -> list:
        """Ctrl+Z (settings_history.py): the toys' anti-stuck switched off,
        or a timer made longer, asks first -- it loosens a safety cutoff."""
        import antistuck
        from settings_history import Ask

        def block(state):
            state = state if isinstance(state, dict) else {}
            return antistuck.from_app(lambda k, d: state.get(k, d))
        return [Ask("confirm", f"Toys' anti-stuck: {what}")
                for what in antistuck.loosens(block(current), block(target))]

    @staticmethod
    def history_describe(path) -> str:
        if not path:
            return ""
        key = str(path[0])
        if key in DESCRIBE:
            return DESCRIBE[key]
        if key.startswith("feature_"):
            return f"Features: {settings_history.humanize(key[len('feature_'):])}"
        return settings_history.humanize(key)

    def _load_or_create_defaults(self) -> None:
        """Load settings from JSON file or create defaults if not exists."""
        if os.path.exists(APP_SETTINGS_FILE):
            try:
                with open(APP_SETTINGS_FILE, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults to ensure all keys exist
                    self.settings = {**DEFAULT_APP_SETTINGS, **loaded}
                    print(f"Loaded app settings from {APP_SETTINGS_FILE}")
                    return
            except (json.JSONDecodeError, IOError) as e:
                print(f"App settings load error: {e}, using defaults")
        else:
            self.created_fresh = True

        # Use defaults if file doesn't exist or has errors
        self.settings = DEFAULT_APP_SETTINGS.copy()
        self._save_settings()

    def _save_settings(self) -> None:
        """Save current settings to JSON file."""
        try:
            atomic_write_json(APP_SETTINGS_FILE, self.settings, indent=2)
        except OSError as e:
            print(f"App settings save error: {e}")
        settings_history.saved(self)

    def get(self, key: str, default=None) -> Any:
        """Get a setting value"""
        return self.settings.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a setting value and save to file"""
        self.settings[key] = value
        self._save_settings()

    def update_setting(self, key: str, value: Any) -> None:
        """Update a setting value and persist to file (alias for set)"""
        self.settings[key] = value
        self._save_settings()
