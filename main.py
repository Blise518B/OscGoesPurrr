# OscGoesPurrr - Main Orchestrator (The Traffic Cop)
#
# This file is the Controller. It boots the threads, holds the
# mode_manager, drains the cross-thread queue, and routes data
# between layers. Per-engine UI-facing methods live as mixins under
# `controllers/` and are composed into OscGoesPurrrApp via multiple
# inheritance below.
#
# See ARCHITECTURE.md for the full picture (Brain / Eardrum / Muscles
# family / stateless Routers / Face / Traffic Cop) and the four
# anti-tangling rules that keep the layers separate.

import threading
import asyncio
import queue
import pystray
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple

# ModeManager from config manager module
from config_manager import PROFILE_FILE, ModeManager

# UI Components for the Visual Shell (The Face / View)
from ui_components import OscGoesPurrrUI

# Haptic Engine for async hardware operations
from haptic_engine import HapticEngine

# VRChat OSC Manager for OSC discovery and routing
from vrchat_osc import VRChatOSCManager
from motor_router import MotorRouter
from parameter_store import store
from steamvr_engine import SteamVREngine
from steamvr_router import SteamVRRouter, SteamVRBatteryBroadcaster
from bhaptics_engine import BHapticsEngine
from bhaptics_router import BHapticsRouter
from pishock_engine import PiShockEngine
from pishock_router import PiShockRouter
from coyote_engine import CoyoteEngine
from coyote_router import CoyoteRouter
from owo_engine import OwoEngine
from owo_router import OwoRouter
from handy_engine import HandyEngine
from handy_router import HandyRouter
from motor_param_out import resolve_param_out
from queue_drain import drain_and_coalesce
from constants import *
from utilities import (
    classify_ogb_zone, value_to_hex_color, toggle_windows_console,
    create_default_icon, relaunch_self,
)
from version import __version__
import debug_log

# Per-engine facade mixins extend the controller's call surface without
# bloating main.py — each mixin's docstring covers its assumed attributes.
from controllers import (
    IntifaceFacade,
    SteamVRFacade,
    SteamVRToysFacade,
    BHapticsFacade,
    PiShockFacade,
    CoyoteFacade,
    OwoFacade,
    HandyFacade,
    OscFacade,
    ModesFacade,
    SessionsFacade,
    SpsSourcesFacade,
    StatsFacade,
)


class _BackendSpec(NamedTuple):
    """One row of the controller's backend lifecycle registry: the feature
    flag that gates the subsystem, a label for log lines, and the ordered
    start / stop steps (bound methods on the engines/routers plus any
    pre-start config hook)."""
    key: str
    label: str
    start: Tuple[Callable[[], None], ...]
    stop: Tuple[Callable[[], None], ...]


class OscGoesPurrrApp(
    IntifaceFacade,
    SteamVRFacade,
    SteamVRToysFacade,
    BHapticsFacade,
    PiShockFacade,
    CoyoteFacade,
    OwoFacade,
    HandyFacade,
    OscFacade,
    ModesFacade,
    SessionsFacade,
    SpsSourcesFacade,
    StatsFacade,
):
    def __init__(self):
        self.async_loop: asyncio.AbstractEventLoop = None
        
        # Thread-safe communication queue (standard library, not asyncio)
        self.thread_queue: queue.Queue = queue.Queue()
        
        # Mode manager instance (modes + wiring + all settings managers)
        self.mode_manager = ModeManager()

        # Seed the shared wiring store AND every mode's feel layer with
        # every known toy on startup, so a stale config from before the
        # global registry existed gets unified the first time you launch
        # the new build.
        self._seed_known_devices()
        print(f"[modes] known toys: {list(self.mode_manager.known_devices.all().keys())}")

        # UI Component - handles all GUI rendering and updates
        self.ui: OscGoesPurrrUI = None
        
        # Haptic Engine - async hardware interface (single source of truth for connection state)
        self.haptic_engine: Optional[HapticEngine] = None
        
        # Signal raised by the async worker thread once its event loop is
        # bound; replaces the old polling-sleep startup race.
        self._loop_ready = threading.Event()

        # Auto-refresh state - loaded from config in _setup_components
        self.auto_refresh_enabled = True
        self._auto_refresh_task = None  # For storing the periodic scan task
        
        # Auto-connect state - loaded from config in _setup_components
        self.auto_connect_enabled = True
        self._auto_connect_task = None  # For storing the auto-connect retry loop task reference
        
        # OSC Debugger state
        self.is_debugging_osc = False
        
        # UI Lock - prevent programmatic UI changes from echoing back to the controller
        self._is_updating_ui = False
        
        # Dirty flag to debounce rapid OSC bundles
        self._needs_recalculation = False

        # Cache of latest battery level per device (0..1). Populated from
        # battery_update queue messages; surfaced via get_simple_mode_toys()
        # so the Simple Mode panel can show a live battery icon next to each
        # connected toy.
        self._battery_cache: Dict[str, float] = {}

        # Per-toy soft-mute set. Session-only, never persisted: cleared on
        # app start (trivially, by being an empty set here) and on every
        # app start. Mode switches deliberately KEEP mutes (see
        # ModesFacade.switch_mode — a safety toggle must not lift because
        # the user tapped Low → Medium from the VR menu). Mute forces
        # the engine target to 0 while the mixer keeps computing real
        # values so the meter still shows what would be playing.
        self._muted_devices: set = set()

        # Initialize components in correct order
        self._setup_components()
        
        # Apply OS-level settings on boot
        self.apply_console_visibility()
    
    def _setup_components(self):
        """Initialize UI component and backend services."""
        # Instantiate Haptic Engine (now owns its own state)
        self.haptic_engine = HapticEngine(self.thread_queue)

        # Tell the engine how to provision the Buttplug server: spawn our own
        # bundled intiface-engine ("integrated", the default) or connect to a
        # user-run Intiface Central ("external"). Read from the persisted
        # setting; the live toggle goes through set_intiface_integrated().
        self.haptic_engine.set_connection_mode(
            "integrated"
            if self.mode_manager.app_settings.get("use_integrated_intiface", True)
            else "external"
        )

        # Initialize standalone OSC routing engine
        self.motor_router = MotorRouter()

        # Tune view's pattern player + source picker were deleted in
        # Cut 8 of the chain-inlined-tuning redesign; the parametric
        # simulator now lives on MotorChainListWidget itself and uses
        # the router's per-(motor, chain) value-provider API and
        # toy-output suppression set (see docs/CHAIN_INLINED_TUNING.md
        # § "Phased delivery"). The router exposes these via
        # `set_chain_value_provider` / `should_send_to_toy`.

        # VR session logger — built dead by default. The actual file
        # only opens once start_session_logging() is called (manually
        # from the UI, or automatically via _session_auto_start_if_configured
        # when the user has enabled both `enabled` and `auto_start`).
        # See docs/SESSION_LOGGING.md for the architecture and on-disk format.
        self._session_init_components()

        # SteamVR Haptics — independent pipeline that shares the parameter_store
        # but targets SteamVR trackers via OpenVR.
        self.steamvr_engine = SteamVREngine(
            get_tracker_config=self._steamvr_get_tracker_config,
            get_pattern_configs=self._steamvr_get_pattern_configs,
            get_no_data_config=self._steamvr_get_no_data,
        )
        self.steamvr_router = SteamVRRouter(
            engine=self.steamvr_engine,
            get_all_configs=self._steamvr_get_all_tracker_configs,
            get_master_scale=self.get_master_scale,
            get_test_level=self.get_ogp_test_level,
        )
        self.steamvr_battery = SteamVRBatteryBroadcaster(
            engine=self.steamvr_engine,
            get_all_configs=self._steamvr_get_all_tracker_configs,
            send_osc=self._steamvr_send_osc,
            poll_interval_s=self._steamvr_get_battery_interval(),
            get_auto_connect=self._steamvr_get_auto_connect,
        )

        # bHaptics integration — independent pipeline that shares the
        # parameter_store and translates v1 bHapticsOSC bool params into
        # dot-mode frames sent to the bHaptics Player over WebSocket.
        bs = self.mode_manager.bhaptics_settings
        self.bhaptics_engine = BHapticsEngine(host=bs.get_host(), port=bs.get_port())
        self.bhaptics_engine.set_auto_connect_getter(self._bhaptics_get_auto_connect)
        # Re-publish bhaptics devices into the SteamVR strip whenever the
        # Player connects/disconnects or its connected-position set changes.
        # Routed through the queue so the bridge update happens on the main
        # thread, matching how Lovense device-changed events flow.
        self.bhaptics_engine.set_state_callback(
            lambda: self.thread_queue.put(("bhaptics_state_changed", None))
        )
        self.bhaptics_router = BHapticsRouter(
            engine=self.bhaptics_engine,
            get_device_configs=self._bhaptics_get_device_configs,
            get_antistuck=self._bhaptics_get_antistuck,
            get_sps_mirror_config=self.get_bhaptics_sps_mirror,
            get_sps_sources=self._get_sps_source_map,
            get_master_scale=self.get_master_scale,
            get_test_level=self.get_ogp_test_level,
        )

        # PiShock integration — discrete-event shock/vibrate/beep router with
        # hard safety caps enforced in the engine. Shares the parameter_store
        # and resolves zones via the same zone_strength path as bHaptics.
        ps = self.mode_manager.pishock_settings
        self.pishock_engine = PiShockEngine(mode=ps.get_mode(), log=self.log_message)
        self.pishock_engine.set_auto_connect_getter(self._pishock_get_auto_connect)
        self.pishock_engine.configure(ps.get_engine_config())
        self.pishock_router = PiShockRouter(
            engine=self.pishock_engine,
            get_zone_configs=self._pishock_get_zones,
            get_sps_sources=self._get_sps_source_map,
            get_global_rate=self._pishock_get_global_rate,
            get_master_scale=self.get_master_scale,
        )

        # DG-Lab Coyote integration — direct-BLE A/B e-stim. The engine owns
        # its own asyncio loop + the 100 ms B0 cadence; the router pushes
        # debounced per-channel strength targets resolved via zone_strength.
        self.coyote_engine = CoyoteEngine(log=self.log_message)
        self.coyote_engine.set_auto_connect_getter(self._coyote_get_auto_connect)
        self.coyote_router = CoyoteRouter(
            engine=self.coyote_engine,
            get_channel_configs=self._coyote_get_channel_configs,
            get_sps_sources=self._get_sps_source_map,
            get_master_scale=self.get_master_scale,
        )

        # OWO suit integration — muscle e-stim via the OWO .NET SDK (loaded
        # through pythonnet, isolated in owo_sdk). The engine owns the sensation
        # re-send cadence; the router pushes the active muscle map on change.
        self.owo_engine = OwoEngine(
            get_game_id=self._owo_get_game_id,
            get_ip=self._owo_get_ip,
            log=self.log_message,
        )
        self.owo_engine.set_auto_connect_getter(self._owo_get_auto_connect)
        self.owo_router = OwoRouter(
            engine=self.owo_engine,
            get_muscle_configs=self._owo_get_muscle_configs,
            get_frequency=self._owo_get_frequency,
            get_sps_sources=self._get_sps_source_map,
            get_master_scale=self.get_master_scale,
        )

        # The Handy integration — official handyfeeling.com REST API v3
        # (cloud; firmware 4 / Handy 2). The engine owns a rate-capped,
        # latest-wins send loop (HAMP velocity or HDSP position commands);
        # the router pushes the shaped 0-1 level on change.
        self.handy_engine = HandyEngine(
            get_connection_key=self._handy_get_connection_key,
            get_api_key=self._handy_get_api_key,
            get_motion_config=self._handy_get_motion,
            log=self.log_message,
        )
        self.handy_engine.set_auto_connect_getter(self._handy_get_auto_connect)
        self.handy_router = HandyRouter(
            engine=self.handy_engine,
            get_zone_config=self._handy_get_zone_config,
            get_sps_sources=self._get_sps_source_map,
            get_master_scale=self.get_master_scale,
            get_test_level=self.get_ogp_test_level,
        )

        # Backend lifecycle registry: one row per feature-gated subsystem,
        # consumed by _apply_feature_state, run() startup and quit_app so the
        # start/stop choreography is written exactly ONCE per backend.
        # `start` steps run in order inside one guarded attempt (a backend
        # that half-starts logs and stays half-started, matching the old
        # inline blocks); `stop` steps are each guarded individually so one
        # failing sibling can't skip the rest. Adding backend #8 means
        # adding one row here — the three consumers never change.
        self._backend_specs: "Dict[str, _BackendSpec]" = {
            spec.key: spec for spec in (
                _BackendSpec(
                    "feature_steamvr_haptics", "SteamVR haptics",
                    start=(self.steamvr_router.start,),
                    stop=(self.steamvr_router.stop,),
                ),
                _BackendSpec(
                    "feature_steamvr_battery", "SteamVR battery",
                    start=(self.steamvr_battery.start,),
                    stop=(self.steamvr_battery.stop,),
                ),
                _BackendSpec(
                    "feature_bhaptics", "bHaptics",
                    start=(self.bhaptics_engine.start, self.bhaptics_router.start),
                    stop=(self.bhaptics_router.stop, self.bhaptics_engine.stop),
                ),
                _BackendSpec(
                    "feature_pishock", "PiShock",
                    start=(self._pishock_apply_config,
                           self.pishock_engine.start, self.pishock_router.start),
                    stop=(self.pishock_router.stop, self.pishock_engine.stop),
                ),
                _BackendSpec(
                    "feature_coyote", "Coyote",
                    # Engine first: configure() pushes limits through the
                    # engine's (started) asyncio loop.
                    start=(self.coyote_engine.start,
                           self._coyote_apply_config, self.coyote_router.start),
                    stop=(self.coyote_router.stop, self.coyote_engine.stop),
                ),
                _BackendSpec(
                    "feature_owo", "OWO",
                    start=(self.owo_engine.start, self.owo_router.start),
                    stop=(self.owo_router.stop, self.owo_engine.stop),
                ),
                _BackendSpec(
                    "feature_handy", "Handy",
                    start=(self.handy_engine.start, self.handy_router.start),
                    stop=(self.handy_router.stop, self.handy_engine.stop),
                ),
            )
        }

        # Instantiate VRChat OSC Manager
        bind_all = self.mode_manager.app_settings.settings.get("bind_all_interfaces", True)
        self.osc_manager = VRChatOSCManager(local_listen_port=0, bind_all_interfaces=bind_all)

        # Link our router to the global OSC callback
        self.osc_manager.global_osc_callback = self.on_osc_message

        # Connection hook - push to queue for thread-safe UI update
        self.osc_manager.on_connected = lambda ports: self.thread_queue.put(
            ("osc_status", (True, ports.get("local_listen_port")))
        )
        # Disconnect hook (mDNS removal or health-check failure) -- routes the
        # same queue message so the UI/log path is symmetric.
        self.osc_manager.on_disconnected = lambda: self.thread_queue.put(
            ("osc_status", (False, self.osc_manager.local_listen_port if self.osc_manager else None))
        )
        
        # Load profiles using profile manager (also initializes app_settings)
        self.mode_manager.load_profiles()
        
        # Load app settings (auto_connect, auto_refresh)
        self.auto_refresh_enabled = self.mode_manager.app_settings.get("auto_refresh", True)
        self.auto_connect_enabled = self.mode_manager.app_settings.get("auto_connect", True)
        
        # SteamVR virtual-toy-device feature — must be initialised BEFORE
        # the UI is constructed, because the Settings tab queries
        # `get_steamvr_toys_status()` while building the SteamVR card.
        # The facade no-ops the bridge/install steps when the user hasn't
        # enabled the feature, so it's cheap to call unconditionally.
        try:
            self._steamvr_toys_init()
        except Exception as e:
            print(f"[steamvr-toys] init failed: {e}")

        # Instantiate UI Component (must be after haptic_engine is created).
        # The UI owns its own root window so this controller stays
        # framework-agnostic.
        self.ui = OscGoesPurrrUI(self)
        # Now that the UI exists, let the SteamVR-toys bridge log through it.
        try:
            self._steamvr_toys_attach_ui()
        except Exception:
            pass

        # Push window-chrome settings through the UI facade.
        self.ui.set_title(f"{APP_NAME} - v{__version__}")
        saved_geometry = self.mode_manager.app_settings.settings.get(
            "window_geometry", WINDOW_GEOMETRY
        )
        self.ui.set_geometry(saved_geometry)

        # Build stored devices UI after loading profiles
        self.ui.build_stored_devices_ui()

        # Usage statistics — lifetime totals + per-session summaries.
        # Needs the motor router (thrust counter) so it comes last;
        # sampling rides the 1 Hz refresh_device_states heartbeat in
        # run(), and _stats_shutdown() in quit_app closes the session.
        self._stats_init()

    # Cap how many queue messages we drain per tick. Under an OSC storm this
    # keeps the UI thread responsive — anything not drained this tick gets
    # picked up on the next 100 ms poll.
    _QUEUE_BATCH_CAP = 500

    def process_async_queue(self):
        """Process messages from queue (called from main thread).

        Drains up to `_QUEUE_BATCH_CAP` messages per tick. Consecutive
        `osc_haptic_update` messages for the same `(device, motor)` are
        coalesced — only the most recent target value matters for hardware,
        so we drop the stale ones and dispatch a single command per motor.
        """
        # Collect-and-coalesce phase (pure, unit-tested in queue_drain.py):
        # haptic updates land latest-wins in a side dict keyed by
        # (device, motor) and replay at the end; the relative order of every
        # other event is preserved. Sequence preservation matters for stuff
        # like `connection_status` → `devices_found`.
        ordered_events, haptic_latest = drain_and_coalesce(
            self.thread_queue, self._QUEUE_BATCH_CAP)

        for msg in ordered_events:
            if not isinstance(msg, tuple):
                continue
            msg_type, data = msg

            if msg_type == "ui_update":
                try:
                    debug_log.get_logger("engine").info("%s", data)
                except Exception:
                    pass
                self.ui.log_message(data)
            elif msg_type == "connection_status":
                connected, server = data
                # Route through the controller method (NOT directly to UI) --
                # the controller method is what restarts the auto-reconnect
                # loop when `connected` is False. Calling self.ui directly
                # only repainted the status label and left the engine state
                # in limbo with no retries.
                self.update_connection_status(connected, server)
            elif msg_type == "devices_found":
                # Update the global known-toys registry so future
                # sessions still see these toys.
                _any_new = False
                for _info in (data.values() if isinstance(data, dict) else []):
                    if isinstance(_info, dict):
                        if self.mode_manager.known_devices.register(
                            _info.get("name", ""),
                            int(_info.get("motor_count", 1)),
                            _info.get("motor_kinds"),
                        ):
                            _any_new = True
                if _any_new:
                    # A never-before-seen toy: seed its wiring AND every
                    # mode's feel presets NOW, not at next boot — otherwise
                    # it plays with flat defaults in whatever mode is
                    # active (Sleep's wake gate wouldn't exist for it) and
                    # its feel silently changes after a restart.
                    self._seed_known_devices()
                self.ui.build_device_list_ui(data)
                changed_devices = self._sync_linear_configs(data)
                if changed_devices and hasattr(self.ui, "remove_device_frame"):
                    # Motor card structure depends on motor_kind (linear
                    # vs continuous-output choose different Output stage
                    # editors). When the engine reports a different
                    # kind for a toy that already has a UI frame, the
                    # cached frame is stale — rebuild ONLY the affected
                    # devices so the user sees the right labels and
                    # stage editor without disturbing other toys'
                    # expanded state, simulator panels, etc.
                    for dn in changed_devices:
                        try:
                            self.ui.remove_device_frame(dn)
                        except Exception:
                            pass
                    # build_device_list_ui re-adds devices that aren't
                    # in `device_ui_frames` — exactly the ones we just
                    # removed. Other toys are untouched.
                    self.ui.build_device_list_ui(data)
                # Re-evaluate the green-check vs yellow-warning icons
                # on every stored device frame so reconnects flip
                # back to connected immediately.
                self.ui.update_stored_devices_ui()
                # Mirror the new device list into the SteamVR toy driver
                # (no-op when the feature is disabled).
                try:
                    self.steamvr_toys_on_devices_changed()
                except Exception as e:
                    self.log_message(f"[steamvr-toys] sync failed: {e}")
            elif msg_type == "battery_update":
                try:
                    self._battery_cache[data["device_name"]] = float(data["level"])
                except (TypeError, ValueError):
                    pass
                self.ui.update_battery_label(data["device_name"], data["level"])
                # Push the same value into the Simple Mode panel if it
                # exposes a hook for live battery refresh.
                if hasattr(self.ui, "update_simple_mode_battery"):
                    self.ui.update_simple_mode_battery(data["device_name"], data["level"])
                try:
                    self.steamvr_toys_on_battery(data["device_name"], data["level"])
                except Exception:
                    pass
            elif msg_type == "device_removed":
                device_name = data
                self.log_message(f"Toy disconnected: {device_name}")
                # Frame stays (the device is "stored"); just flip its
                # connection-status icon from green to yellow.
                self.ui.update_stored_devices_ui()
                try:
                    self.steamvr_toys_on_devices_changed()
                except Exception:
                    pass
            elif msg_type == "bhaptics_state_changed":
                # bHaptics engine reported a connection-state or
                # connected-positions change. Mirror it into the SteamVR
                # device strip (no-op when the SteamVR toy feature is off)
                # AND push the user-configured connection bool to VRChat
                # so an avatar animation can react.
                try:
                    self.steamvr_toys_on_bhaptics_state_changed()
                except Exception:
                    pass
                try:
                    self._bhaptics_send_connected_bool()
                except Exception:
                    pass
            elif msg_type == "stored_devices_refresh":
                self.ui.build_stored_devices_ui()
            elif msg_type == "osc_status":
                is_connected, port = data
                self.ui.update_osc_status(is_connected, port)
                if is_connected:
                    self.ui.log_message(f"VRChat OSC Connected! Listening on port {port}")
                    # Dump full diagnostics on every connect so the user has
                    # a clean baseline (which ports were chosen, etc.) in the
                    # log when a future silent-connection failure happens.
                    try:
                        diag = self.osc_manager.get_diagnostics() if self.osc_manager else {}
                        self.ui.log_message(
                            f"OSC diag: our_listen={diag.get('our_listen_port')} "
                            f"our_http={diag.get('our_http_phonebook_port')} "
                            f"vrc_http={diag.get('vrc_http_port')} "
                            f"vrc_osc={diag.get('vrc_osc_port')} "
                            f"udp_socket={diag.get('udp_socket_bound')}"
                        )
                    except Exception:
                        pass
                    # /avatar/change fires only when the avatar loads.
                    # If we connected mid-session we'll never see it,
                    # so probe the OSCQuery HTTP node for the current
                    # value as soon as the OSCQuery handshake settles.
                    self._schedule_avatar_id_probe()
                    # Re-push the bHaptics connection bool — VRChat just
                    # came back, so its avatar parameter cache no longer
                    # reflects whatever we sent during the prior session.
                    try:
                        self._bhaptics_send_connected_bool()
                    except Exception:
                        pass
                    # Same for the mode index: the expression-menu highlight
                    # should match the app after every reconnect.
                    try:
                        self._send_ogp_mode_out()
                    except Exception:
                        pass
                else:
                    self.ui.log_message("VRChat OSC Disconnected. Waiting for VRChat to come back...")
                    # The OGP/Test release edge can never arrive on a dead
                    # link — drop the test floor so nothing stays latched
                    # at the pulse level.
                    try:
                        self.set_ogp_test_active(False)
                    except Exception:
                        pass
                    # Dump diagnostics so we can see whether packets ever
                    # arrived this session.
                    try:
                        diag = self.osc_manager.get_diagnostics() if self.osc_manager else {}
                        self.ui.log_message(
                            f"OSC diag at disconnect: packets_handled={diag.get('packets_handled')} "
                            f"phonebook_GETs={diag.get('phonebook_GETs')} "
                            f"handler_exc={diag.get('handler_exceptions')} "
                            f"session_age_s={diag.get('session_age_s')}"
                        )
                    except Exception:
                        pass
            elif msg_type == "ui_slider_update":
                device_name, value, motor_idx = data
                self._is_updating_ui = True  # Lock the UI to prevent echo loops
                try:
                    # Tell the UI to handle its own widgets
                    self.ui.update_device_visuals(device_name, motor_idx, value)
                finally:
                    self._is_updating_ui = False  # Unlock
            elif msg_type == "avatar_change":
                self._on_avatar_change(data)
            elif msg_type == "ogp_mode":
                # Expression-menu mode switch (OGP/Mode int from VRChat).
                self._on_ogp_mode_osc(data)
            elif msg_type == "ogp_test":
                # Menu Test button held/released (OGP/Test bool).
                self.set_ogp_test_active(bool(data))

        # Dispatch the coalesced haptic targets last — one command per motor
        # carrying the freshest value.
        for device_name, val_float, motor_index in haptic_latest.values():
            self.update_device_target(device_name, val_float, motor_index)
    
    def log_message(self, message: str):
        """Add a message to the log text box (main thread only)"""
        try:
            debug_log.get_logger().info("%s", message)
        except Exception:
            pass
        self.ui.log_message(message)
    
    # ====================
    # Facade Methods
    # Delegate to subordinate components to provide a clean single-entry API.
    # ====================

    def apply_console_visibility(self):
        """Applies the current console visibility setting via OS utilities."""
        show_console = not self.get_app_setting("hide_console", True)
        toggle_windows_console(show_console)

    def open_logs_folder(self):
        """Facade: open the folder holding the debug / crash / engine logs in
        the system file explorer, so the user can grab them for troubleshooting
        without digging through %APPDATA%. Wired to the Settings 'Open logs
        folder' button. Best-effort; Windows-first with a non-Windows fallback."""
        try:
            import debug_log
            folder = str(debug_log.log_path().parent)
        except Exception:
            from settings._paths import APPDATA_DIR
            folder = str(APPDATA_DIR)
        try:
            import os as _os
            import subprocess as _subp
            if _os.name == "nt":
                _os.startfile(folder)  # type: ignore[attr-defined]
            else:
                # This app targets Windows; keep the fallback from crashing
                # if someone runs it elsewhere.
                _subp.Popen(["xdg-open", folder])
            self.log_message(f"Opened logs folder: {folder}")
        except Exception as e:
            self.log_message(f"Open logs folder failed: {type(e).__name__}: {e}")

    def delete_stored_device(self, device_name: str):
        """Forget a toy entirely — removes its shared wiring, its feel entry
        in every mode, and its row in the global known-toys registry. To use
        this toy again, reconnect it."""
        self.mode_manager.delete_device(device_name)
        self.mode_manager.known_devices.forget(device_name)
        # And the router's runtime state: a stale >0 last_outputs entry
        # would keep the settling tick alive forever and book phantom
        # on-time against the deleted toy in the statistics.
        self.motor_router.forget_device(device_name)

        # Remove from UI via the framework-agnostic facade
        self.ui.remove_device_frame(device_name)

        self.log_message(f"Deleted stored toy: {device_name}")
    
    def get_profile_config(self, device_name: str, key: str, default=None):
        """Get a specific config value for a device from current profile using mode_manager"""
        return self.mode_manager.get_profile_config(device_name, key, default)
    
    def get_app_setting(self, key: str, default: Any = None):
        """Facade method for UI to safely read app settings."""
        if hasattr(self.mode_manager.app_settings, 'get'):
            return self.mode_manager.app_settings.get(key, default)
        return self.mode_manager.app_settings.settings.get(key, default)
    
    def set_app_setting(self, key: str, value: Any):
        """Facade method for UI to safely update app settings."""
        self.mode_manager.app_settings.set(key, value)

    def _get_toy_antistuck(self) -> Dict[str, Any]:
        """Anti-stuck config for the toy (Device Routing) path, read from app
        settings and reshaped into the `{enabled, active_s, peaked_s}` dict
        the motor router expects. Threaded into `reevaluate_state` each tick;
        a plain dict read on the GUI thread, so it holds the latency budget."""
        return {
            "enabled": bool(self.get_app_setting("toy_antistuck_enabled", True)),
            "active_s": int(self.get_app_setting("toy_antistuck_active_s", 7)),
            "peaked_s": int(self.get_app_setting("toy_antistuck_peaked_s", 15)),
        }

    # ==================================================================
    # Feature toggles — Settings → Features panel uses these to gate the
    # expensive background subsystems (bHaptics, SteamVR haptics/battery,
    # OSC Inspector). Each toggle starts/stops the matching
    # engine so disabled features actually free their threads.
    # ==================================================================

    FEATURE_KEYS = (
        "feature_osc_inspector",
        "feature_bhaptics",
        "feature_steamvr_haptics",
        "feature_steamvr_battery",
        "feature_intiface",
        "feature_pishock",
        "feature_coyote",
        "feature_owo",
        "feature_handy",
    )

    def get_feature_enabled(self, key: str) -> bool:
        return bool(self.get_app_setting(key, True))

    def get_feature_flags(self) -> Dict[str, bool]:
        return {k: self.get_feature_enabled(k) for k in self.FEATURE_KEYS}

    def set_feature_enabled(self, key: str, enabled: bool) -> None:
        enabled = bool(enabled)
        self.set_app_setting(key, enabled)
        try:
            self._apply_feature_state(key, enabled)
        except Exception as e:
            self.log_message(f"Feature toggle '{key}' apply error: {e}")
        # Sync the sidebar visibility so disabled features hide their nav entry.
        if self.ui is not None:
            try:
                self.ui.apply_feature_visibility()
            except Exception:
                pass

    def _start_backend(self, spec: "_BackendSpec") -> None:
        """Run a spec's start steps in order. One guarded attempt for the
        whole sequence — a half-started backend logs and stays as it is,
        matching the old per-backend inline blocks."""
        try:
            for step in spec.start:
                step()
        except Exception as e:
            self.log_message(f"{spec.label} start failed: {e}")

    def _stop_backend(self, spec: "_BackendSpec") -> None:
        """Run a spec's stop steps, each guarded individually so one failing
        sibling can never skip the rest (the old grouped try blocks did)."""
        for step in spec.stop:
            try:
                step()
            except Exception:
                pass

    def _apply_feature_state(self, key: str, enabled: bool) -> None:
        """Start or stop the background subsystem behind a feature toggle."""
        spec = self._backend_specs.get(key)
        if spec is not None:
            if enabled:
                self._start_backend(spec)
            else:
                self._stop_backend(spec)
            return
        if key == "feature_osc_inspector":
            # Pure UI / debug feature — refresh loop checks the flag itself.
            pass
        elif key == "feature_intiface":
            # Intiface toy communication. Turning it off disconnects any
            # active session and the auto-connect loop short-circuits on the
            # flag, so no reconnection happens until the user re-enables it.
            if enabled:
                self._ensure_auto_connect_running()
            else:
                if (self.haptic_engine
                        and self.haptic_engine.is_connected
                        and self.async_loop):
                    try:
                        asyncio.run_coroutine_threadsafe(
                            self.haptic_engine.async_disconnect(),
                            self.async_loop,
                        )
                    except Exception as e:
                        self.log_message(f"Intiface disconnect failed: {e}")
    
    def get_detected_zones(self) -> Dict[str, List[str]]:
        """Facade method for UI to safely read detected zones from the Central Store."""
        return store.get_detected_zones()
    
    def update_device_config(self, device_name: str, key: str, value):
        """Update a config value for a device in current profile using mode_manager"""
        self.mode_manager.update_device_config(device_name, key, value)

    def force_recalculate(self, dispatch_direct: bool = False):
        """Forces the router to recalculate output based on current state and new UI configs.

        Reads from whichever profile the manager considers *active* — an avatar
        profile when the current VRChat avatar has one bound, otherwise the
        selected global profile. In Simple Mode, profile config is bypassed
        and every connected motor gets the same global SPS max value.

        `dispatch_direct` controls how the resulting per-motor targets reach the
        engine. The live routing tick passes ``True`` to hand them straight to
        ``update_device_target`` on the GUI thread, skipping the ~50 ms UI-queue
        hop (``QUEUE_POLL_RATE_MS``) that otherwise sits between the router and
        the engine — that hop was the single biggest avoidable chunk of
        end-to-end latency. UI-triggered recalcs (config edits, profile
        switches) keep the default ``False`` so they still flow through the
        queue and inherit its ordering/echo-suppression semantics.
        """
        if not (hasattr(self, 'motor_router') and hasattr(self, 'osc_manager')):
            return
        params, _version, zones = store.snapshot()
        if self.get_app_setting("simple_mode", False):
            motor_counts = self.get_device_motor_counts()
            updates = self.motor_router.reevaluate_simple_mode(
                motor_counts, params, zones=zones
            )
            # Simple Mode bypasses per-toy profile config, so the per-motor
            # "mirror to VRChat parameter" feature (which lives in that config)
            # is inactive here. None signals "skip param-out" below.
            active = None
        else:
            active = self.mode_manager.get_active_profile_dict()
            if active is None:
                return
            updates = self.motor_router.reevaluate_state(
                active, params, zones=zones,
                sps_sources=self._get_sps_source_map(),
                antistuck=self._get_toy_antistuck(),
            )
        for device_name, target_val, motor_idx in updates:
            if dispatch_direct:
                # Hot path: we're already on the GUI thread (routing tick), so
                # call straight through instead of round-tripping the value
                # through thread_queue only to drain it on the same thread up to
                # QUEUE_POLL_RATE_MS later. update_device_target is a thread-safe
                # engine dict write plus a GUI-thread vibe-meter update.
                self.update_device_target(device_name, target_val, motor_idx)
            else:
                self.thread_queue.put(("osc_haptic_update", (device_name, target_val, motor_idx)))
            # Optional per-motor OSC-out mirror: push this motor's computed
            # value back to VRChat as an avatar parameter. Rides the same
            # change-debounced `updates`, so it only fires when the value
            # actually moves. Independent of toy connection / mute — it
            # reflects the contact, not the device. Skipped in Simple Mode.
            if active is not None:
                self._send_motor_param_out(active.get(device_name), motor_idx, target_val)

    def _send_motor_param_out(self, device_config, motor_idx: int, value: float) -> None:
        """Mirror a motor's computed 0..1 output to a VRChat avatar parameter
        when this motor has param-out configured (Device Routing → per-motor
        "Mirror to VRChat parameter"). Fire-and-forget OSC send — no queue
        hop, no ack — so it holds the latency budget. No-op when OSC is down
        or the motor has no param-out address; never raises into the routing
        tick. `send_parameter` applies its own per-address rate limit, so
        rapid changes stay bounded on the wire."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return
        try:
            resolved = resolve_param_out(device_config, motor_idx, value)
            if resolved is None:
                return
            address, send_value = resolved
            osc.send_parameter(address, send_value)
        except Exception as e:
            self.log_message(f"Motor param-out send failed: {e}")

    def toggle_osc_debugger(self, *args):
        """Toggle the OSC debugger on/off (accepts *args for safe UI toggle compatibility)"""
        self.is_debugging_osc = not self.is_debugging_osc
        if self.is_debugging_osc:
            self.ui.log_message("OSC Debugger Started")
        else:
            self.ui.log_message("OSC Debugger Stopped")
        
        # Update button appearance to reflect current state
        self.ui.update_osc_debugger_button(self.is_debugging_osc)

    def refresh_debugger_ui(self):
        """Refresh the debugger display at 10Hz (100ms intervals).

        The body must never kill the loop: the reschedule runs in `finally`
        (an unhandled exception in a QTimer slot would otherwise silently end
        this chain for the rest of the session)."""
        try:
            self._refresh_debugger_ui_body()
        except Exception:
            debug_log.get_logger().exception("refresh_debugger_ui failed")
        finally:
            # Schedule the next refresh (throttled to save UI thread).
            self.ui.schedule_callback(UI_REFRESH_RATE_MS, self.refresh_debugger_ui)

    def _refresh_debugger_ui_body(self):
        # Update SPS Zones Status
        if hasattr(self, 'osc_manager'):
            fresh_zones = store.get_detected_zones()
            orifices = fresh_zones.get("Orifices", [])
            penetrators = fresh_zones.get("Penetrators", [])
            touch = fresh_zones.get("Touch", [])

            # Change tracker — per-bucket tuples, not a flat concatenation,
            # so a name moving between zone types still registers as a change.
            current_state = (tuple(orifices), tuple(penetrators), tuple(touch))

            # Only update UI if the zones have actually changed to avoid flickering
            if not hasattr(self, '_last_detected_zones') or self._last_detected_zones != current_state:
                self._last_detected_zones = current_state

                # Update text with proper newlines
                sps_text = (
                    f"Orifices: {', '.join(orifices) if orifices else 'None'}\n\n"
                    f"Penetrators: {', '.join(penetrators) if penetrators else 'None'}"
                )
                if touch:
                    sps_text += f"\n\nTouch zones: {', '.join(touch)}"
                self.ui.update_sps_status(sps_text)

        if getattr(self, 'is_debugging_osc', False) and hasattr(self, 'osc_manager'):
            # Get search filter
            search_query = self.ui.get_osc_search_query()

            lines = []  # list of (addr_prefix, val_str, hex_color) triplets
            # Sort alphabetically, using Central Store for thread-safe data
            for addr, val in sorted(store.get_all_parameters().items()):
                if search_query in addr.lower():
                    # Cleanly format floats to 4 decimal places, leave bools/ints alone
                    if isinstance(val, float):
                        val_str = f"{val:.4f}"
                    else:
                        val_str = str(val)

                    color = value_to_hex_color(val)
                    lines.append((addr, val_str, color))

            if not lines and search_query:
                debug_data = [("No parameters match your search.", "", COLOR_TEXT_MUTED)]
            elif not lines:
                debug_data = [("Waiting for OSC data...", "", COLOR_TEXT_MUTED)]
            else:
                debug_data = lines

            # Push to the UI as a list of (text, color) tuples
            self.ui.update_debugger_display(debug_data)

        # Refresh the Simple Mode panel on the same cadence so newly connected
        # toys, fresh battery readings and zone changes appear without waiting
        # for a hard rebuild.
        if hasattr(self.ui, "refresh_simple_mode_view"):
            self.ui.refresh_simple_mode_view()
        # The diagnostics panel self-skips when it isn't the active view,
        # so this is cheap when the user is elsewhere.
        if hasattr(self.ui, "refresh_osc_diagnostics_view"):
            self.ui.refresh_osc_diagnostics_view()

    def get_osc_status_snapshot(self) -> Dict[str, Any]:
        """Quick snapshot of the VRChat OSC link's state for the
        Overview view's System tile. UI gets primitives only — never
        reaches into self.osc_manager directly."""
        mgr = getattr(self, "osc_manager", None)
        connected = bool(mgr and getattr(mgr, "is_connected", False))
        port = None
        try:
            port = int(getattr(mgr, "local_listen_port", 0) or 0) or None
        except Exception:
            port = None
        try:
            packets = int(store.get_packets_received())
        except Exception:
            packets = 0
        return {"connected": connected, "port": port, "packets": packets}

    # ==================================================================
    # Simple Mode Facade
    # When enabled, every detected SPS source drives every connected toy
    # with no per-toy profile config. Toggle, source list and toy list are
    # surfaced through these methods so the UI never reaches into backend
    # state directly.
    # ==================================================================

    def get_simple_mode(self) -> bool:
        return bool(self.get_app_setting("simple_mode", False))

    def set_simple_mode(self, enabled: bool):
        enabled = bool(enabled)
        if self.get_simple_mode() == enabled:
            return
        self.set_app_setting("simple_mode", enabled)
        # Clear router debounce so the new mode's first tick actually emits
        # values instead of being silently filtered as "unchanged".
        if hasattr(self, "motor_router"):
            self.motor_router.reset_outputs()
        # When turning OFF, also send zeros to every motor so they don't
        # hang at the last simple-mode value.
        if not enabled and self.haptic_engine and self.haptic_engine.is_connected:
            for device_name, motor_count in self.get_device_motor_counts().items():
                for motor_idx in range(motor_count):
                    self.thread_queue.put(("osc_haptic_update", (device_name, 0.0, motor_idx)))
        self.log_message(f"Simple Mode {'enabled' if enabled else 'disabled'}")
        # Rebuild device cards: the Device Routing view is now mostly
        # decorative while Simple Mode is on, but no clear-out is needed.
        self.force_recalculate()

    def get_simple_mode_sources(self) -> Dict[str, List[str]]:
        """Live snapshot of detected SPS zones — {'Orifices': [...],
        'Penetrators': [...], 'Touch': [...]}. Returns empty lists when
        no avatar is loaded. Uses the shared classifier so both wire
        forms (OGB/... and VFH/Zone/...) are recognized."""
        params = store.get_all_parameters()
        buckets: Dict[str, set] = {"Orf": set(), "Pen": set(), "Touch": set()}
        for path in params.keys():
            zone = classify_ogb_zone(path)
            if zone is not None:
                buckets[zone[0]].add(zone[1])
        return {
            "Orifices": sorted(buckets["Orf"]),
            "Penetrators": sorted(buckets["Pen"]),
            "Touch": sorted(buckets["Touch"]),
        }

    def get_simple_mode_toys(self) -> List[Dict[str, Any]]:
        """Snapshot of connected toys for the Simple Mode panel.
        Each entry: {'name': str, 'motor_count': int, 'connected': bool}."""
        out: List[Dict[str, Any]] = []
        if not self.haptic_engine:
            return out
        motor_counts = self.haptic_engine.get_motor_count_map()
        for name in self.haptic_engine.list_connected_device_names():
            out.append({
                "name": name,
                "motor_count": int(motor_counts.get(name, 1)),
                "connected": True,
                "battery": self._battery_cache.get(name),
            })
        out.sort(key=lambda d: d["name"].lower())
        return out
    
    def toggle_network_bind(self, value: bool):
        """Handle network bind toggle from Settings UI."""
        self.mode_manager.app_settings.update_setting("bind_all_interfaces", value)
        self.ui.log_message("Network bind changed. PLEASE RESTART APP to apply.")

    # ---- Haptic engine facades ----

    def save_profiles(self):  # Facade -> mode_manager.save_profiles()
        self.mode_manager.save_profiles()

    def load_profiles(self) -> Dict[str, Any]:  # Facade -> mode_manager.load_profiles()
        return self.mode_manager.load_profiles()
    
    def _on_closing(self):
        """Handle window close event: either minimize to tray or fully quit."""
        to_tray = self.get_app_setting("minimize_to_tray", False)
        try:
            debug_log.get_logger().info(
                "window close requested (minimize_to_tray=%s)", to_tray
            )
        except Exception:
            pass
        if to_tray:
            self.minimize_to_tray()
        else:
            self.quit_app()
            
    def minimize_to_tray(self):
        """Hides the UI and spawns the system tray icon in a background thread."""
        self.ui.hide_window()

        image = create_default_icon()
        menu = pystray.Menu(
            pystray.MenuItem("Show OscGoesPurrr", self.restore_from_tray, default=True),
            pystray.MenuItem("Quit", self.quit_from_tray)
        )
        self.tray_icon = pystray.Icon("OscGoesPurrr", image, "OscGoesPurrr", menu)

        # pystray blocks, so we must run it in a daemon thread
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def restore_from_tray(self, icon, item):
        """Restores the UI from the system tray (thread-safe)."""
        icon.stop()
        self.ui.show_window()

    def quit_from_tray(self, icon, item):
        """Fully shuts down the app from the system tray (thread-safe)."""
        icon.stop()
        self.ui.schedule_on_main_thread(self.quit_app)

    def request_restart(self):
        """UI facade: run the normal clean shutdown, then relaunch the
        app. Used by Settings → Appearance so a color-profile switch
        repaints everything without the user manually restarting — the
        palette is baked into every module at import time, so a fresh
        process is the reliable way to apply it. The spawn happens in
        run() only after the Qt loop has fully exited (see
        utilities.relaunch_self)."""
        self._relaunch_requested = True
        self.quit_app()

    def quit_app(self):
        """Executes the final, clean shutdown sequence."""
        try:
            debug_log.get_logger().info("quit_app() called — beginning clean shutdown")
        except Exception:
            pass
        self.log_message("Shutting down...")
        current_geometry = self.ui.get_geometry()
        if current_geometry:
            self.mode_manager.app_settings.update_setting("window_geometry", current_geometry)

        self.save_profiles()

        # Close any active session file with a footer + final flush.
        # Best-effort: if the worker thread is wedged this just times
        # out and the file is what it is.
        try:
            self._session_stop_for_shutdown()
        except Exception:
            pass

        # Finalize the usage-statistics session (records it + flushes
        # stats.json) while the state is still coherent, before the
        # engines are torn down below.
        try:
            self._stats_shutdown()
        except Exception:
            pass

        # Cleanly disconnect Intiface so its log doesn't show an abrupt
        # websocket drop and so it stops scanning when we leave. Best-effort
        # with a short timeout — daemon-killing the async thread on exit is
        # the safe fallback if something hangs.
        try:
            if (self.async_loop and self.haptic_engine
                    and self.haptic_engine.is_connected):
                future = asyncio.run_coroutine_threadsafe(
                    self.haptic_engine.async_disconnect(),
                    self.async_loop,
                )
                future.result(timeout=2.0)
        except Exception:
            pass

        # Hard safety net for integrated mode: make sure any intiface-engine we
        # spawned is stopped even if we weren't "connected" at quit (e.g. it
        # launched but its websocket never came up). The Windows Job Object
        # would also kill it when our process exits; this just doesn't wait.
        try:
            if self.haptic_engine:
                self.haptic_engine.release_managed_server()
        except Exception:
            pass

        # Stop every backend from the lifecycle registry (each stop step is
        # individually guarded, so one wedged engine can't skip the rest),
        # then free the OpenVR runtime — shutdown() is registry-external
        # because it's a teardown of the shared handle, not a router stop.
        for spec in self._backend_specs.values():
            self._stop_backend(spec)
        try:
            self.steamvr_engine.shutdown()
        except Exception:
            pass

        try:
            bridge = getattr(self, "_steamvr_toy_bridge", None)
            if bridge is not None:
                bridge.clear_devices()
                bridge.stop()
        except Exception:
            pass

        # Stop the VRChat OSC manager so its mDNS records are torn down and
        # its sockets released before the process exits. Cheap; the manager's
        # stop() is idempotent.
        try:
            mgr = getattr(self, "osc_manager", None)
            if mgr is not None:
                mgr.stop()
        except Exception:
            pass

        self.ui.shutdown()

    # Engine-specific facade methods live in `controllers/` mixin modules:
    #   - SteamVRFacade            (SteamVR haptics + battery)
    #   - BHapticsFacade           (bHaptics player dot grid)
    # The mixins assume `self.mode_manager`, the engine attributes, and
    # `self.osc_manager` exist on the host controller.

    def run(self):
        """Start the Three-Pillar application"""
        # Start async loop in background thread
        self.start_async_loop()

        # Wait for the worker thread to publish its event loop, with a timeout
        # so a stuck worker doesn't hang startup forever.
        if not self._loop_ready.wait(timeout=5.0):
            self.log_message("Async worker did not start within 5s; continuing anyway")

        # Start auto-connect if enabled. The idempotent guard re-checks the
        # feature flag and is_connected (single source of truth is haptic_engine),
        # and prevents stacking duplicate reconnect loops.
        self._ensure_auto_connect_running()

        # Decoupled routing tick. The rate is user-tunable in Settings
        # (router_poll_rate_hz, default 60 Hz); falls back to the
        # ROUTER_POLL_RATE_MS constant if the setting is missing or
        # malformed. Time-constant math (decay_tau / attack_ms /
        # release_ms) is wall-clock-based so changing the rate at
        # runtime never requires recalibrating tau values.
        #
        # The Tune view's pattern generator is pull-based — the router
        # samples it on each tick — so we keep the tick firing whenever
        # Tune has a motor subscribed even if VRChat is silent.
        def routing_tick():
            # The whole body is guarded and the reschedule lives in
            # `finally`: one unhandled exception must not end this chain for
            # the rest of the session — a dead routing tick doesn't just stop
            # fresh routing, it disables the needs_settling / anti-stuck
            # HARDWARE-SAFETY ticks while the engine keeps commanding the
            # last non-zero targets.
            try:
                needs_tick = getattr(self, '_needs_recalculation', False)
                if not needs_tick and hasattr(self, 'motor_router'):
                    try:
                        needs_tick = self.motor_router.has_tune_subscription()
                    except Exception:
                        pass
                # Hardware safety: keep ticking while ANY motor output is
                # non-zero, regardless of which page the UI shows (the UI
                # trace subscriptions pause while hidden, so they no longer
                # accidentally guarantee this). Smoothing tails settle and
                # the anti-stuck cutoff fires on these ticks; once every
                # output rests at zero the idle ticking stops again.
                if not needs_tick and hasattr(self, 'motor_router'):
                    try:
                        needs_tick = self.motor_router.needs_settling()
                    except Exception:
                        pass
                # Session logging samples on every tick — keep the recompute
                # firing so the motor broadcast hits the logger consistently
                # at the configured router rate, even when VRChat is silent.
                if not needs_tick and hasattr(self, 'is_session_logging_active'):
                    try:
                        if self.is_session_logging_active():
                            needs_tick = True
                    except Exception:
                        pass
                if needs_tick:
                    self._needs_recalculation = False
                    # Direct dispatch: skip the UI queue so the freshly computed
                    # target reaches the engine this tick, not up to 50 ms later.
                    self.force_recalculate(dispatch_direct=True)
                # After recompute, hand the OGB + bHaptics snapshots to the
                # session logger if it's recording. The logger's internal
                # change-diff drops the OGB event when nothing changed, so
                # idle ticks are cheap.
                if hasattr(self, 'is_session_logging_active'):
                    try:
                        if self.is_session_logging_active():
                            self._session_sample_tick()
                    except Exception:
                        pass
            except Exception:
                debug_log.get_logger().exception("routing_tick failed")
            finally:
                # Re-read the rate on each tick so a Settings change takes
                # effect on the very next reschedule with no restart.
                try:
                    hz = int(self.get_app_setting("router_poll_rate_hz", 60))
                    hz = max(10, min(240, hz))
                    interval = max(1, int(round(1000.0 / hz)))
                except Exception:
                    interval = ROUTER_POLL_RATE_MS
                self.ui.schedule_callback(interval, routing_tick)

        # Periodically check for UI updates from async thread. Same rule as
        # routing_tick: the reschedule always runs — this pump carries every
        # cross-thread status/device event, and one malformed message must
        # not silently kill it.
        def check_queue():
            try:
                self.process_async_queue()
            except Exception:
                debug_log.get_logger().exception("check_queue failed")
            finally:
                self.ui.schedule_callback(QUEUE_POLL_RATE_MS, check_queue)

        # Slow heartbeat that re-syncs the per-toy connect dots from
        # the engine's current device list. Defensive against rare
        # event-loss paths where an Intiface device gets dropped or
        # re-added without firing our usual `device_added` /
        # `device_removed` callbacks (e.g. silent BLE re-pair). Cheap
        # at 1 Hz — just a dict comparison + a stylesheet write.
        def refresh_device_states():
            try:
                if self.ui is not None:
                    self.ui.update_stored_devices_ui()
                    # Same heartbeat drives the sidebar's per-backend
                    # status dots (change-gated, so this is ~free).
                    self.ui.update_backend_nav_dots()
            except Exception:
                pass
            # Usage statistics ride the same 1 Hz heartbeat — one cheap
            # sample per second, off every routing hot path. The facade
            # guards its own body so a stats bug can't kill this pump.
            self._stats_sample_tick()
            self.ui.schedule_callback(1000, refresh_device_states)

        # Register clean shutdown handler to auto-save profiles
        self.ui.set_close_handler(self._on_closing)

        self.ui.schedule_callback(UI_REFRESH_RATE_MS, check_queue)

        # Start the routing tick loop
        self.ui.schedule_callback(ROUTER_POLL_RATE_MS, routing_tick)

        # Start the device-state heartbeat (1 Hz).
        self.ui.schedule_callback(1000, refresh_device_states)

        # If the user has opted into auto-starting session logging on
        # launch, open a session file now. No-op otherwise.
        try:
            self._session_auto_start_if_configured()
        except Exception as e:
            self.log_message(f"Session logger auto-start error: {e}")

        # Start every enabled backend from the lifecycle registry (SteamVR
        # engine init stays deferred to its first refresh; the reconnecting
        # engines' supervisor threads idle while their auto-connect is off —
        # which is the deliberate default for the e-stim / shock / moving
        # hardware backends, so nothing dials out unprompted).
        for spec in self._backend_specs.values():
            if self.get_feature_enabled(spec.key):
                self._start_backend(spec)

        # Apply saved SteamVR autostart on boot (no-op if SteamVR is offline).
        if self.mode_manager.steamvr_settings.get_autostart():
            try:
                self.steamvr_engine.setup_autostart(True)
            except Exception:
                pass

        # If auto-connect is enabled, try an immediate refresh so the device
        # list populates without waiting for the first broadcaster tick.
        if self.mode_manager.steamvr_settings.get_auto_connect():
            try:
                self.steamvr_engine.refresh_devices(quiet=True)
            except Exception:
                pass

        # Boot OSC server 500ms after UI launches to prevent freezing
        if self.mode_manager.app_settings.settings.get("auto_connect_osc", True):
            self.ui.schedule_callback(OSC_BOOT_DELAY_MS, self.toggle_osc_connection)

        # Start the OSC debugger UI refresh loop
        self.refresh_debugger_ui()

        # Run GUI event loop on main thread
        self.ui.run()

        # Deferred self-relaunch (Settings → Appearance profile switch).
        # Runs only after the event loop has exited and quit_app's clean
        # shutdown released the OSC/UDP sockets and mDNS advertisement,
        # so the new instance never races this one.
        if getattr(self, "_relaunch_requested", False):
            relaunch_self()


if __name__ == "__main__":
    # Set up durable logging + crash handlers FIRST, so even a failure during
    # app construction lands in the log file (the windowed build has no console).
    debug_log.setup_logging()
    try:
        app = OscGoesPurrrApp()
        app.run()
    except BaseException:
        debug_log.get_logger().critical("fatal error in __main__", exc_info=True)
        raise
