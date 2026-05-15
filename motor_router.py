import fnmatch
from typing import Dict, List, Tuple, Any
from utilities import normalize_osc_value

class MotorRouter:
    """
    Stateless routing engine. 
    It evaluates the UI Profile against the live VRChat 'Shadow State' (all_parameters) 
    to determine exact motor values with zero memory ghosting.
    """
    def __init__(self):
        # We no longer need an internal memory dictionary! 
        # We rely on the absolute truth of VRChat's live parameter cache.
        # Tracks the last calculated output to prevent flooding the UI thread
        self.last_outputs: Dict[tuple, float] = {}

    def _calculate_motor_target(self, device_name: str, motor_idx: int, config: Dict[str, Any], all_params: Dict[str, Any]) -> float:
        target_val = 0.0
        
        # --- 1. Check Custom Override Box ---
        osc_addresses = config.get("osc_addresses", {})
        custom_addr = osc_addresses.get(str(motor_idx), "").strip()
        if custom_addr:
            # Clean prefix if user typed it
            if custom_addr.startswith("/avatar/parameters/"):
                custom_addr = custom_addr.replace("/avatar/parameters/", "")
            elif custom_addr.startswith("/"):
                custom_addr = custom_addr[1:]
                
            # Scan Shadow State for a match
            for param_name, param_val in all_params.items():
                if param_name == custom_addr or fnmatch.fnmatch(param_name, custom_addr):
                    try:
                        v = float(param_val)
                        target_val = max(target_val, normalize_osc_value(v))
                    except (ValueError, TypeError):
                        pass
        
        # --- 2. Check SPS Zones ---
        zones_str = config.get(f"motor_{motor_idx}_zones", config.get(f"motor_{motor_idx}_zone", ""))
        allowed_zones = [z.strip() for z in zones_str.split(",") if z.strip() and z.strip() != "None"]
        
        # If no zones are selected, just return whatever the custom override calculated
        if not allowed_zones:
            return target_val
            
        # Build valid suffixes based on UI filters
        allow_touch = config.get(f"motor_{motor_idx}_touch", True)
        allow_pen = config.get(f"motor_{motor_idx}_pen", True)
        allow_self = config.get(f"motor_{motor_idx}_self", False)
        allow_others = config.get(f"motor_{motor_idx}_others", True)
        
        valid_suffixes = []
        if allow_touch and allow_self: valid_suffixes.append("TouchSelf")
        if allow_touch and allow_others: valid_suffixes.append("TouchOthers")
        if allow_pen and allow_self: valid_suffixes.extend(["PenetratingSelf", "PenSelf"])
        if allow_pen and allow_others: valid_suffixes.extend(["PenetratingOthers", "PenOthers", "FrotOthers"])
        
        if not valid_suffixes:
            return target_val
            
        is_all_sps = "All SPS" in allowed_zones
        active_vals = [target_val] # Include the custom override target as a baseline
        
        # Sweep the entire Shadow State for matching SPS interactions
        for path, val in all_params.items():
            parts = path.split("/")
            if len(parts) >= 4 and parts[0] == "OGB":
                zone_name = parts[2]
                suffix = parts[3]
                
                if is_all_sps or zone_name in allowed_zones:
                    if suffix in valid_suffixes:
                        try:
                            v = float(val)
                            active_vals.append(normalize_osc_value(v))
                        except (ValueError, TypeError):
                            pass
                            
        return max(active_vals)

    def reevaluate_state(self, active_profile: Dict[str, Any], all_params: Dict[str, Any]) -> List[Tuple[str, float, int]]:
        """Instantly recalculates all motor outputs based on the shadow state."""
        updates = []
        for device_name, config in active_profile.items():
            motor_count = config.get("motor_count", 0)
            for motor_idx in range(motor_count):
                target_val = self._calculate_motor_target(device_name, motor_idx, config, all_params)
                
                # CRITICAL FIX: Only queue a UI/Hardware update if the target value actually changed!
                state_key = (device_name, motor_idx)
                if self.last_outputs.get(state_key) != target_val:
                    self.last_outputs[state_key] = target_val
                    updates.append((device_name, target_val, motor_idx))
        return updates

