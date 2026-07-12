"""Controller mixins. Each module here contains a `*Facade` mixin class that
extends `OscGoesPurrrApp` with one engine's UI-facing API. The base
controller in `main.py` inherits from all of them so the call surface for
the UI is unchanged — only the file boundaries move.

Each mixin assumes the host controller has these attributes/methods:
  - `self.mode_manager` (modes + all `*_settings` managers)
  - the relevant engine attribute (`self.steamvr_engine`, etc.)
  - `self.osc_manager` (for OSC send helpers)
  - `self.log_message(str)`
"""

from .intiface_facade import IntifaceFacade
from .steamvr_facade import SteamVRFacade
from .steamvr_toys_facade import SteamVRToysFacade
from .bhaptics_facade import BHapticsFacade
from .pishock_facade import PiShockFacade
from .coyote_facade import CoyoteFacade
from .owo_facade import OwoFacade
from .handy_facade import HandyFacade
from .osc_facade import OscFacade
from .modes_facade import ModesFacade
from .sessions_facade import SessionsFacade
from .sps_sources_facade import SpsSourcesFacade
from .stats_facade import StatsFacade

__all__ = [
    "IntifaceFacade",
    "SteamVRFacade",
    "SteamVRToysFacade",
    "BHapticsFacade",
    "PiShockFacade",
    "CoyoteFacade",
    "OwoFacade",
    "HandyFacade",
    "OscFacade",
    "ModesFacade",
    "SessionsFacade",
    "SpsSourcesFacade",
    "StatsFacade",
]
