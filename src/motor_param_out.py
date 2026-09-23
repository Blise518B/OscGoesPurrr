# motor_param_out.py
# Pure resolver for the per-motor "mirror to VRChat parameter" feature.
#
# A motor's computed 0..1 output can optionally be sent back to VRChat as an
# avatar parameter (OSC out), so the same routing that drives a toy can also
# drive an avatar visual (a glow, a blendshape, a fill meter). This module
# holds only the pure mapping config -> (osc address, value); the actual
# fire-and-forget send lives on the controller (main.py) which owns the OSC
# manager. Keeping the mapping pure makes it unit-testable without hardware.
#
# Storage: two per-motor keys live next to the motor's other flags in the
# profile device-config dict (motor_<idx>_touch, motor_<idx>_zones, ...):
#   * motor_<idx>_param_out_enabled : bool  (default False)
#   * motor_<idx>_param_out_address : str   (bare avatar parameter name)
# Absent keys default to "off", so no profile migration is needed.

from typing import Any, Dict, Optional, Tuple

from utilities import strip_param_prefix

# VRChat avatar parameters are addressed under this OSC namespace.
_PARAM_PREFIX = "/avatar/parameters/"


def param_out_keys(motor_idx: int) -> Tuple[str, str]:
    """Return the (enabled_key, address_key) profile keys for a motor."""
    return (
        f"motor_{motor_idx}_param_out_enabled",
        f"motor_{motor_idx}_param_out_address",
    )


def resolve_param_out(device_config: Optional[Dict[str, Any]],
                      motor_idx: int,
                      value: float) -> Optional[Tuple[str, float]]:
    """Map a motor's computed output to an outbound VRChat parameter send.

    Returns ``(full_osc_address, clamped_value)`` when this motor has
    param-out enabled with a non-blank address, or ``None`` when the feature
    is off / unconfigured / the value isn't numeric. The address is always
    the fully-qualified ``/avatar/parameters/<name>`` form; the stored name is
    normalised with ``strip_param_prefix`` so a pasted full path still works.
    The value is clamped to 0..1 (the float range VRChat expects for a
    proximity-style parameter)."""
    if not isinstance(device_config, dict):
        return None
    enabled_key, address_key = param_out_keys(motor_idx)
    if not device_config.get(enabled_key, False):
        return None
    name = strip_param_prefix(device_config.get(address_key, ""))
    if not name:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    v = max(0.0, min(1.0, v))
    return _PARAM_PREFIX + name, v
