"""Example friends for the Friends page, for trying the page with a full
list: start OGP with OGP_FRIENDS_DEMO=1.

Nothing here touches the network or a toy. The examples are drawn into the
page next to your real friends, their toys move by themselves, and what you
do to them only reaches the log. "Driving your toys" on an example is a
picture, never a level for your router.
"""

import math
import time
from typing import Any, Dict, List, Optional

import param_board as pb
import remote_params as rp
import remote_protocol as proto

ENV = "OGP_FRIENDS_DEMO"


def _id(n: int) -> str:
    return f"de{n:02x}" + "0" * 60     # 64 hex, recognisably made up


_FRIENDS = [
    {"id": _id(1), "nick": "Mika", "path": "direct", "rtt": 18.0, "driving": True,
     "others": ["Sam"],
     "toys": [("Lovense Lush 3", 1), ("Lovense Hush 2", 1)], "allow_toys": True,
     "allow_shock": True, "shockers": ["Collar"], "armed": False, "strength": 0.8,
     "perm": (True, True, True), "board": "mika"},
    {"id": _id(2), "nick": "Kiko", "path": "relay", "rtt": 64.0, "driving": False,
     "toys": [("Lovense Edge 2", 2), ("Lovense Gush", 1), ("Lovense Domi 2", 1)],
     "allow_toys": True, "allow_shock": False, "shockers": [], "armed": False,
     "strength": 1.0, "perm": (True, False, True)},
    {"id": _id(3), "nick": "Nova", "path": "direct", "rtt": 31.0, "driving": False,
     "toys": [("Kiiroo Keon", 1), ("We-Vibe Sync", 2)], "allow_toys": True,
     "allow_shock": True, "shockers": ["Collar", "Cuff", "Thigh"], "armed": True,
     "strength": 0.6, "perm": (True, True, False), "board": "nova"},
    {"id": _id(4), "nick": "Rin", "path": "", "rtt": None, "driving": False, "toys": [],
     "allow_toys": True, "allow_shock": True, "shockers": [], "armed": False,
     "strength": 1.0, "perm": (True, True, True), "offline": True},
]

def _ctl(param, kind, cat, ptype, label=None, **extra):
    return dict({"param": param, "kind": kind, "cat": cat, "ptype": ptype,
                 "label": label or param}, **extra)


# Example avatar boards (the Avatar Remote page's shape), and where their
# values start.
_BOARDS = {
    "mika": {
        "name": "Base V7", "yolo": False,
        "cats": [("outfit", "Outfit", "green", False), ("shader", "Shader", "blue", False),
                 ("haptics", "Haptics", "red", False), ("loco", "Locomotion", "amber", True)],
        "controls": [
            _ctl("BinaryHaloOff", "toggle", "outfit", "Bool"),
            _ctl("JacketOff", "toggle", "outfit", "Bool"),
            _ctl("Outfit", "toggle", "outfit", "Int", "Outfit 1", on=1, off=0),
            _ctl("Outfit", "toggle", "outfit", "Int", "Outfit 2", on=2, off=0),
            _ctl("MaxBrightness", "slider", "shader", "Float", min=0.0, max=1.0),
            _ctl("OutlineThickness", "slider", "shader", "Float", min=0.0, max=1.0),
            _ctl("AudioLinkOff", "toggle", "shader", "Bool"),
            _ctl("518H_HapticsOff", "toggle", "haptics", "Bool"),
            _ctl("Emote", "button", "haptics", "Int", "Wave", on=3, off=0),
            _ctl("CrouchIdle", "int", "loco", "Int", min=0.0, max=8.0),
            _ctl("ProneIdle", "int", "loco", "Int", min=0.0, max=8.0),
        ],
        "values": {"BinaryHaloOff": True, "JacketOff": False, "Outfit": 1,
                   "MaxBrightness": 1.0, "OutlineThickness": 0.5, "AudioLinkOff": False,
                   "518H_HapticsOff": False, "Emote": 0, "CrouchIdle": 5, "ProneIdle": 2},
        "all": {},
    },
    "nova": {
        "name": "Fox", "yolo": True,
        "cats": [("main", "Fox", "purple", False)],
        "controls": [
            _ctl("TailWag", "toggle", "main", "Bool", "Tail wag"),
            _ctl("EarsDown", "toggle", "main", "Bool", "Ears down"),
            _ctl("Blush", "slider", "main", "Float", min=0.0, max=1.0),
        ],
        "values": {"TailWag": True, "EarsDown": False, "Blush": 0.3, "Hue": 0.12,
                   "Glasses": False, "Hat": 0, "FurLength": 0.6},
        "all": {"Hue": "Float", "Glasses": "Bool", "Hat": "Int", "FurLength": "Float"},
    },
}


def _demo_board(key: str) -> Dict[str, Any]:
    spec = _BOARDS[key]
    preset = pb.normalize_preset({
        "name": "Default",
        "categories": [{"id": cid, "name": n, "color": c, "locked": lk}
                       for cid, n, c, lk in spec["cats"]],
        "controls": [dict(c, id=f"{key}{i}") for i, c in enumerate(spec["controls"])],
    })
    types = {c["param"]: c["ptype"] for c in preset["controls"]}
    types.update(spec["all"])
    msg = rp.with_version(rp.public_board(preset, spec["name"], types, spec["yolo"]))
    return rp.read_board(msg)


_GROUPS = [
    {"id": "demo-1", "name": "Night crew", "members": [_id(1), _id(2), _id(3)]},
    {"id": "demo-2", "name": "Pair", "members": [_id(1), _id(3)]},
]


class FriendsDemo:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._friends = {f["id"]: f for f in _FRIENDS}
        self.perms = {f["id"]: list(f["perm"]) for f in _FRIENDS}
        self.groups = [dict(g, members=list(g["members"])) for g in _GROUPS]
        self.selected: Optional[Dict[str, str]] = None
        self._boards = {f["id"]: _demo_board(f["board"]) for f in _FRIENDS if f.get("board")}
        self._values = {f["id"]: dict(_BOARDS[f["board"]]["values"])
                        for f in _FRIENDS if f.get("board")}

    # what is an example
    def is_friend(self, fid: str) -> bool:
        return fid in self._friends

    def is_group(self, gid: str) -> bool:
        return any(g["id"] == gid for g in self.groups)

    def has(self, kind: str, sid: str) -> bool:
        return self.is_friend(sid) if kind == "friend" else self.is_group(sid)

    def nick(self, fid: str) -> str:
        return self._friends[fid]["nick"]

    def group(self, gid: str) -> Optional[Dict[str, Any]]:
        return next((g for g in self.groups if g["id"] == gid), None)

    def targets(self) -> List[str]:
        sel = self.selected or {}
        if sel.get("kind") == "friend":
            return [sel["id"]]
        g = self.group(sel.get("id", "")) if sel.get("kind") == "group" else None
        return list(g["members"]) if g else []

    def set_member(self, gid: str, fid: str, on: bool) -> None:
        g = self.group(gid)
        if g is not None and self.is_friend(fid):
            g["members"] = [m for m in g["members"] if m != fid] + ([fid] if on else [])

    # what the page shows
    def status(self, fid: str, strength: Optional[float] = None) -> Optional[Dict[str, Any]]:
        f = self._friends.get(fid)
        if f is None or f.get("offline"):
            return None
        s = f["strength"] if strength is None else strength
        t = self._clock()
        outputs = {name: round(s * (0.5 + 0.5 * math.sin(t * (0.7 + 0.4 * i) + i)), 3)
                   for i, (name, _m) in enumerate(f["toys"])}
        batteries = {name: 0.9 - 0.25 * i for i, (name, _m) in enumerate(f["toys"])}
        return proto.read_status(proto.make_status(
            f["toys"], outputs, s, False, False, f["allow_toys"], f["allow_shock"],
            f["shockers"], f["armed"], 40, 2000, batteries=batteries))

    def board(self, fid: str) -> Optional[Dict[str, Any]]:
        """An example friend's avatar board, as get_friend_board has it."""
        board = self._boards.get(fid)
        if board is None or self._friends[fid].get("offline"):
            return None
        values = dict(self._values[fid])
        if "Blush" in values:            # something moving by itself
            values["Blush"] = round(0.5 + 0.4 * math.sin(self._clock() * 0.8), 2)
        prm = {"ver": board["ver"], "yolo": board.get("all") is not None, "stop": False}
        return {"prm": prm, "board": board, "values": values, "holds": set()}

    def set_value(self, fid: str, name: str, value: Any) -> None:
        if fid in self._values:
            self._values[fid][name] = value

    def entries(self, my_levels: Dict[str, Dict[str, float]],
                my_strength: Dict[str, Any]) -> List[Dict[str, Any]]:
        out = []
        for f in _FRIENDS:
            fid = f["id"]
            mine = my_strength.get(fid)
            theirs = self.status(fid, mine[1] if mine else None)
            out.append({
                "id": fid, "nick": f["nick"], "toys": self.perms[fid][0],
                "shock": self.perms[fid][1], "params": self.perms[fid][2], "added": 0.0,
                "linked": theirs is not None, "path": f["path"], "rtt": f["rtt"],
                "theirs": theirs, "my_levels": dict(my_levels.get(fid, {})),
                "driving_me": f["driving"] and self.perms[fid][0],
                "others": list(f.get("others", ())) if theirs is not None else [],
                "sync": True,
                "demo": True,
            })
        return out
