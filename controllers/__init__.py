"""Controller mixins. Each module here contains a `*Facade` mixin class that
extends `OscGoesPurrrApp` with one engine's UI-facing API. The base
controller in `main.py` inherits from all of them so the call surface for
the UI is unchanged — only the file boundaries move.

Each mixin assumes the host controller has these attributes/methods:
  - `self.profile_manager` (for `*_settings` getters)
  - the relevant engine attribute (`self.steamvr_engine`, etc.)
  - `self.osc_manager` (for OSC send helpers)
  - `self.log_message(str)`
"""

from .steamvr_facade import SteamVRFacade
from .steamvr_toys_facade import SteamVRToysFacade
from .bhaptics_facade import BHapticsFacade
from .osc_facade import OscFacade
from .profiles_facade import ProfilesFacade
from .sessions_facade import SessionsFacade
from .sps_sources_facade import SpsSourcesFacade

__all__ = [
    "SteamVRFacade",
    "SteamVRToysFacade",
    "BHapticsFacade",
    "OscFacade",
    "ProfilesFacade",
    "SessionsFacade",
    "SpsSourcesFacade",
]
