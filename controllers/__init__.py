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
from .bhaptics_facade import BHapticsFacade
from .hardware_monitor_facade import HardwareMonitorFacade

__all__ = ["SteamVRFacade", "BHapticsFacade", "HardwareMonitorFacade"]
