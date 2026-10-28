"""Controller mixins. Each module here contains a `*Facade` mixin class that
extends `OscGoesPurrrApp` with one subsystem's UI-facing API. The base
controller in `main.py` inherits from all of them so the call surface for
the UI is unchanged — only the file boundaries move.

Each mixin assumes the host controller has these attributes/methods:
  - `self.mode_manager` (modes + all `*_settings` managers)
  - the relevant engine attribute (`self.haptic_engine`, etc.)
  - `self.osc_manager` (for OSC send helpers)
  - `self.log_message(str)`
"""

from .intiface_facade import IntifaceFacade
from .osc_facade import OscFacade
from .modes_facade import ModesFacade
from .sessions_facade import SessionsFacade
from .sps_sources_facade import SpsSourcesFacade
from .stats_facade import StatsFacade
from .people_facade import PeopleFacade
from .thrust_params_facade import ThrustParamsFacade
from .replay_facade import ReplayFacade
from .steamvr_toys_facade import SteamVRToysFacade
from .pishock_facade import PiShockFacade
from .suits_facade import SuitsFacade
from .friends_facade import FriendsFacade
from .params_facade import ParamsFacade
from .toy_sounds_facade import ToySoundsFacade
from .toy_presence_facade import ToyPresenceFacade
from .whats_new_facade import WhatsNewFacade
from .interests_facade import InterestsFacade

__all__ = [
    "IntifaceFacade",
    "OscFacade",
    "ModesFacade",
    "SessionsFacade",
    "SpsSourcesFacade",
    "StatsFacade",
    "PeopleFacade",
    "ThrustParamsFacade",
    "ReplayFacade",
    "SteamVRToysFacade",
    "PiShockFacade",
    "SuitsFacade",
    "FriendsFacade",
    "ParamsFacade",
    "ToySoundsFacade",
    "ToyPresenceFacade",
    "WhatsNewFacade",
    "InterestsFacade",
]
