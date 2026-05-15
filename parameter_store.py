import threading
from typing import Dict, Any, List


class ParameterStore:
    """
    Central thread-safe repository for all VRChat avatar parameters and detected zones.
    Acts as the single source of truth for the Router and the UI.
    """
    def __init__(self):
        self.all_parameters: Dict[str, Any] = {}
        self.detected_zones: Dict[str, List[str]] = {"Orifices": [], "Penetrators": []}
        self.lock = threading.Lock()

    def _parse_oscquery_node(self, node: dict, prefix: str = ""):
        """Recursively flattens the OSCQuery JSON tree."""
        if "CONTENTS" in node:
            for key, child in node["CONTENTS"].items():
                new_prefix = f"{prefix}/{key}" if prefix else key
                self._parse_oscquery_node(child, new_prefix)
        else:
            # Leaf node (actual parameter)
            val = 0.0
            if "VALUE" in node and isinstance(node["VALUE"], list) and len(node["VALUE"]) > 0:
                val = node["VALUE"][0]
            self.all_parameters[prefix] = val

    def rebuild_from_json(self, data: dict) -> int:
        """
        Clears and rebuilds the entire parameter cache from a fresh VRChat OSCQuery JSON.
        Returns the total number of parameters loaded.
        """
        with self.lock:
            self.all_parameters.clear()
            self._parse_oscquery_node(data)
            
            orifices = set()
            penetrators = set()
            
            for path in self.all_parameters.keys():
                parts = path.split("/")
                if len(parts) >= 3 and parts[0] == "OGB":
                    category = parts[1]
                    zone_name = parts[2]
                    if category in ["Orifice", "Orf"]:
                        orifices.add(zone_name)
                    elif category in ["Penetrator", "Pen"]:
                        penetrators.add(zone_name)
                        
            self.detected_zones = {
                "Orifices": sorted(list(orifices)), 
                "Penetrators": sorted(list(penetrators))
            }
            
            return len(self.all_parameters)

    def update_parameter(self, address: str, value: Any):
        """Updates a single parameter in real-time when a UDP packet arrives."""
        with self.lock:
            self.all_parameters[address] = value

    def get_all_parameters(self) -> Dict[str, Any]:
        """Safely returns a copy of the current parameter state."""
        with self.lock:
            return self.all_parameters.copy()
            
    def get_detected_zones(self) -> Dict[str, List[str]]:
        """Safely returns a copy of the detected zones."""
        with self.lock:
            return {
                "Orifices": list(self.detected_zones["Orifices"]),
                "Penetrators": list(self.detected_zones["Penetrators"])
            }


# Global Singleton instance to be imported by other modules
store = ParameterStore()