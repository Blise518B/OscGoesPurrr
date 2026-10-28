"""Avatar parameter boards -- VRC Parameter Relay's board, inside OGP.

One *profile* per avatar: its name, the parameter list it had when it was
last worn (so its board can be edited while you wear something else), and
one or more named *presets*. Each preset is a board: categories (a name, a
colour, a lock) and the controls in them. A control drives one avatar
parameter:

  * ``toggle``  -- on / off (a Bool, or an Int that is set to its own ON
    value; several Int toggles on one parameter switch each other off,
    like VRChat's own menu: Outfit = 1, 2, 3 ...)
  * ``button``  -- held: the ON value while pressed, OFF on release
  * ``slider``  -- a Float (or an Int) between its min and max
  * ``int``     -- a number stepper

A Bool toggle can be inverted (ON sends the parameter OFF). A locked
category is look-only for friends.

`BoardBook` is the Relay's AppCore without the network: which avatar is
worn (`live_avatar_id`), which one is open on the page (`avatar_id` --
the worn one, or any saved one for editing offline), and every edit. It is
pure: profiles come from and go to a store object (`load(avatar_id)`,
`save(profile)`, `list_profiles()` -- settings/param_boards.py), values
are not kept here (they live in OGP's parameter store), and nothing is sent
from here -- `send_value` says what a control would send. Same file shape
as the Relay's `avatars/*.json`, so its boards import as they are
(`relay_profile`).
"""

import copy
import re
import secrets
from typing import Any, Dict, List, Optional, Tuple

CONTROL_KINDS = ("toggle", "button", "slider", "int")

# Which control kinds make sense for each parameter type. An Int can be a
# toggle / hold button the way VRChat's own menu does it: ON sets the
# parameter to the control's value, OFF (or letting go) sets it back.
KINDS_FOR_PTYPE = {
    "Bool": ("toggle", "button"),
    "Int": ("int", "slider", "toggle", "button"),
    "Float": ("slider",),
}
PTYPES = tuple(KINDS_FOR_PTYPE)
INT_MIN, INT_MAX = 0, 255          # VRChat's Int parameter range
FLOAT_MIN, FLOAT_MAX = -1.0, 1.0   # ... and its Float range over OSC

# OSCQuery's type tags -> ours
OSC_TYPES = {"T": "Bool", "F": "Bool", "i": "Int", "f": "Float"}

# A category's colour: OGP's own hues (ui/theme.PALETTE), so a board follows
# the colour picker like every other page.
CATEGORY_HUES = ("green", "pink", "red", "amber", "yellow", "cyan", "blue", "purple")
CATEGORY_HUE_LABELS = {
    "green": "Green", "pink": "Pink", "red": "Red", "amber": "Orange",
    "yellow": "Yellow", "cyan": "Cyan", "blue": "Blue", "purple": "Purple",
}
# The order a new category picks an unused colour in (the Relay's six first).
_NEW_CATEGORY_HUES = ("green", "blue", "cyan", "amber", "red", "purple", "pink", "yellow")
DEFAULT_CATEGORY_COUNT = 4                 # a 2x2 grid out of the box
DEFAULT_CATEGORY_HUES = ("red", "green", "amber", "blue")
# The Relay's "yellow" is an orange (#ffb454): OGP's amber.
_RELAY_HUES = {"yellow": "amber"}

NAME_MAX = 60
LABEL_MAX = 80
AVATAR_NAME_MAX = 80


def new_id() -> str:
    return secrets.token_hex(6)


def short_avatar_name(avatar_id: Optional[str]) -> str:
    m = re.match(r"^avtr_([0-9a-fA-F]{8})", str(avatar_id or ""))
    return f"Avatar {m.group(1)}" if m else str(avatar_id or "?")


def display_name(profile: Dict[str, Any]) -> str:
    """What an avatar is called: the name you gave it, else VRChat's own
    name for it (`vrc_name`, read from VRChat's OSC files by
    vrchat_avatars), else a piece of its id. `name` stays the one you
    gave it -- an avatar you never named is still one you never named."""
    short = short_avatar_name(profile.get("avatar_id"))
    name = profile.get("name") or short
    if name == short and profile.get("vrc_name"):
        return str(profile["vrc_name"])
    return name


def ptype_of(value: Any) -> Optional[str]:
    """The type a live OSC value has (python-osc hands over bool / int /
    float as they were sent)."""
    if isinstance(value, bool):
        return "Bool"
    if isinstance(value, int):
        return "Int"
    if isinstance(value, float):
        return "Float"
    return None


def _clamp_int(value: Any, default: int) -> int:
    try:
        return max(INT_MIN, min(INT_MAX, int(round(float(value)))))
    except (TypeError, ValueError, OverflowError):
        return default


def int_switch_values(control: Dict[str, Any]) -> Tuple[int, int]:
    """(value sent when ON / held, value sent when OFF / released) for an
    Int toggle or hold button. A toggle shows ON while the parameter equals
    the ON value, so several toggles on one Int behave like VRChat's radial
    menu (Outfit = 1, Outfit = 2, ...)."""
    return (_clamp_int(control.get("on"), 1), _clamp_int(control.get("off"), 0))


def is_int_switch(control: Dict[str, Any]) -> bool:
    return control.get("ptype") == "Int" and control.get("kind") in ("toggle", "button")


def default_kind(ptype: str) -> str:
    """The control a parameter gets when added without asking."""
    return {"Bool": "toggle", "Int": "int", "Float": "slider"}.get(ptype, "slider")


def retype_control(control: Dict[str, Any], ptype: str) -> None:
    """Adapt a control to a parameter whose type changed (an avatar update
    turned a Bool toggle into an Int, say). Sending the old type does
    nothing in VRChat, so the control follows the avatar."""
    old_ptype = control.get("ptype")
    control["ptype"] = ptype
    kind = control.get("kind")
    if kind not in KINDS_FOR_PTYPE.get(ptype, ()):
        kind = control["kind"] = default_kind(ptype)
    if kind in ("slider", "int") and (old_ptype != ptype or "min" not in control):
        control["min"] = 0
        control["max"] = 1 if ptype == "Float" else INT_MAX
    if ptype == "Int" and kind in ("toggle", "button") and "on" not in control:
        # a Bool toggle becoming an Int one keeps its meaning: ON -> 1
        inverted = bool(control.get("invert"))
        control["on"], control["off"] = (0, 1) if inverted else (1, 0)
    if ptype != "Bool":
        control.pop("invert", None)


def send_value(control: Dict[str, Any], value: Any) -> Any:
    """What setting `control` to `value` sends to VRChat (None: nothing --
    a value that isn't one). A toggle / button takes its on/off state, a
    slider / stepper its number, kept inside the control's min..max."""
    ptype = control.get("ptype")
    try:
        if ptype == "Bool":
            out = bool(value)
            return (not out) if control.get("invert") else out
        if ptype == "Int" and control.get("kind") in ("toggle", "button"):
            on, off = int_switch_values(control)
            return on if bool(value) else off
        if ptype in ("Int", "Float"):
            v = float(value)
            if v != v:                       # NaN
                return None
            lo, hi = control.get("min"), control.get("max")
            if lo is not None:
                v = max(float(lo), v)
            if hi is not None:
                v = min(float(hi), v)
            if ptype == "Int":
                return max(INT_MIN, min(INT_MAX, int(round(v))))
            return max(FLOAT_MIN, min(FLOAT_MAX, v))
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def any_value(ptype: str, value: Any) -> Any:
    """YOLO: any parameter set straight, kept inside VRChat's OSC ranges
    (Float -1..1, Int 0..255). None when it isn't a value."""
    try:
        if ptype == "Bool":
            return bool(value)
        if ptype == "Int":
            return max(INT_MIN, min(INT_MAX, int(round(float(value)))))
        if ptype == "Float":
            v = float(value)
            return None if v != v else max(FLOAT_MIN, min(FLOAT_MAX, v))
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def shows_on(control: Dict[str, Any], value: Any) -> bool:
    """Whether a toggle shows ON for the parameter's value."""
    if value is None:
        return False
    if is_int_switch(control):
        try:
            return int(round(float(value))) == int_switch_values(control)[0]
        except (TypeError, ValueError, OverflowError):
            return False
    return bool(value) != bool(control.get("invert"))


# ----------------------------------------------------------------------------
# Profiles and presets: cleaned on the way in
# ----------------------------------------------------------------------------

def default_categories() -> List[Dict[str, Any]]:
    order = DEFAULT_CATEGORY_HUES
    return [{"id": new_id(), "name": f"Category {i + 1}", "locked": False,
             "color": order[i % len(order)]}
            for i in range(DEFAULT_CATEGORY_COUNT)]


def _clean_control(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict) or not str(raw.get("param") or "").strip():
        return None
    c = dict(raw)
    c["id"] = str(c.get("id") or new_id())[:32]
    c["param"] = str(c["param"]).strip()[:200]
    if c.get("ptype") not in PTYPES:
        c["ptype"] = {"toggle": "Bool", "button": "Bool", "int": "Int"}.get(c.get("kind"), "Float")
    if c.get("kind") not in KINDS_FOR_PTYPE[c["ptype"]]:
        c["kind"] = default_kind(c["ptype"])
    c["label"] = str(c.get("label") or c["param"])[:LABEL_MAX]
    if c["kind"] in ("slider", "int"):
        for key, dflt in (("min", 0.0), ("max", 1.0 if c["ptype"] == "Float" else float(INT_MAX))):
            try:
                c[key] = float(c.get(key, dflt))
            except (TypeError, ValueError):
                c[key] = dflt
            if c[key] != c[key]:
                c[key] = dflt
    if c["ptype"] != "Bool":
        c.pop("invert", None)
    elif "invert" in c:
        c["invert"] = bool(c["invert"])
    if is_int_switch(c):
        c["on"], c["off"] = int_switch_values(c)
    return c


def normalize_preset(preset: Dict[str, Any]) -> Dict[str, Any]:
    """A preset with an id, a name, at least one category and controls that
    each sit in one of them."""
    preset["id"] = str(preset.get("id") or new_id())[:32]
    preset["name"] = str(preset.get("name") or "Default")[:NAME_MAX]
    cats = preset.get("categories")
    if not isinstance(cats, list) or not [c for c in cats if isinstance(c, dict)]:
        cats = default_categories()
    clean_cats = []
    for cat in cats:
        if not isinstance(cat, dict):
            continue
        cat["id"] = str(cat.get("id") or new_id())[:32]
        cat["name"] = str(cat.get("name") or "Category")[:NAME_MAX]
        cat["locked"] = bool(cat.get("locked"))
        if cat.get("color") not in CATEGORY_HUES:
            cat["color"] = "green"
        clean_cats.append(cat)
    preset["categories"] = clean_cats
    controls = []
    valid = {c["id"] for c in clean_cats}
    for raw in preset.get("controls") if isinstance(preset.get("controls"), list) else []:
        c = _clean_control(raw)
        if c is None:
            continue
        if c.get("cat") not in valid:
            c["cat"] = clean_cats[0]["id"]
        controls.append(c)
    preset["controls"] = controls
    return preset


def normalize_profile(data: Dict[str, Any], avatar_id: Optional[str]) -> Dict[str, Any]:
    """An avatar profile with a name, its saved parameter list and at least
    one preset. Old single-board files (the Relay up to v1.1.0: categories
    and controls at the top) become a profile with one "Default" preset."""
    data = data if isinstance(data, dict) else {}
    data["avatar_id"] = avatar_id
    data["name"] = str(data.get("name") or short_avatar_name(avatar_id))[:AVATAR_NAME_MAX]
    vrc_name = " ".join(str(data.get("vrc_name") or "").split())[:AVATAR_NAME_MAX]
    if vrc_name:
        data["vrc_name"] = vrc_name
    else:
        data.pop("vrc_name", None)
    params = data.get("params")
    data["params"] = ({str(n): p for n, p in params.items() if p in PTYPES}
                      if isinstance(params, dict) else {})
    presets = data.get("presets")
    if not isinstance(presets, list) or not [p for p in presets if isinstance(p, dict)]:
        presets = [{"id": new_id(), "name": "Default",
                    "categories": data.get("categories"), "controls": data.get("controls")}]
    data["presets"] = [normalize_preset(p) for p in presets if isinstance(p, dict)]
    data.pop("categories", None)
    data.pop("controls", None)
    if data.get("active_preset") not in {p["id"] for p in data["presets"]}:
        data["active_preset"] = data["presets"][0]["id"]
    return data


def relay_profile(data: Any) -> Optional[Dict[str, Any]]:
    """One of VRC Parameter Relay's avatars/*.json as an OGP profile (its
    orange "yellow" becomes amber), or None when it isn't one."""
    if not isinstance(data, dict) or not str(data.get("avatar_id") or "").strip():
        return None
    data = copy.deepcopy(data)
    for preset in data.get("presets") or []:
        if isinstance(preset, dict):
            for cat in preset.get("categories") or []:
                if isinstance(cat, dict) and cat.get("color") in _RELAY_HUES:
                    cat["color"] = _RELAY_HUES[cat["color"]]
    for cat in data.get("categories") or []:     # an old single-board file
        if isinstance(cat, dict) and cat.get("color") in _RELAY_HUES:
            cat["color"] = _RELAY_HUES[cat["color"]]
    return normalize_profile(data, str(data["avatar_id"]).strip())


def active_preset(profile: Dict[str, Any]) -> Dict[str, Any]:
    active = profile.get("active_preset")
    for preset in profile["presets"]:
        if preset["id"] == active:
            return preset
    return profile["presets"][0]


def board_params(board: Dict[str, Any]) -> List[str]:
    """The parameters a board's controls drive, in board order, each once."""
    return list(dict.fromkeys(c["param"] for c in board.get("controls") or []))


def find_control(board: Dict[str, Any], control_id: str) -> Optional[Dict[str, Any]]:
    return next((c for c in board.get("controls") or [] if c["id"] == control_id), None)


def find_category(board: Dict[str, Any], cat_id: Any) -> Optional[Dict[str, Any]]:
    return next((c for c in board.get("categories") or [] if c["id"] == cat_id), None)


# ----------------------------------------------------------------------------
# The book: every avatar's board, which one is worn, which one is open
# ----------------------------------------------------------------------------

class BoardBook:
    """The Relay's AppCore, minus OSC and sharing. Every edit returns
    whether it changed something; the caller saves nothing itself -- an
    edit saves the profile through the store."""

    def __init__(self, store, last_avatar_id: Optional[str] = None):
        self.store = store
        self.live_avatar_id: Optional[str] = None
        self.avatar_id: Optional[str] = last_avatar_id or None
        self.types: Dict[str, str] = {}          # the worn avatar's parameters
        self.profile = self._load(self.avatar_id)
        self.board = active_preset(self.profile)
        self._live_profile: Optional[Dict[str, Any]] = None

    # -- the avatar ----------------------------------------------------------

    def _load(self, avatar_id: Optional[str]) -> Dict[str, Any]:
        if not avatar_id:
            return normalize_profile({"name": "No avatar yet"}, None)
        return normalize_profile(self.store.load(avatar_id) or {}, avatar_id)

    def _save(self) -> None:
        if self.avatar_id:
            self.store.save(self.profile)

    @property
    def avatar_name(self) -> str:
        return display_name(self.profile)

    @property
    def is_live(self) -> bool:
        """Is the open avatar the one worn in VRChat?"""
        return self.live_avatar_id is not None and self.avatar_id == self.live_avatar_id

    def live_profile(self) -> Optional[Dict[str, Any]]:
        """The worn avatar's profile -- the open one when it is worn."""
        if self.live_avatar_id is None:
            return None
        if self.is_live:
            return self.profile
        if self._live_profile is None or self._live_profile["avatar_id"] != self.live_avatar_id:
            self._live_profile = self._load(self.live_avatar_id)
        return self._live_profile

    def live_board(self) -> Optional[Dict[str, Any]]:
        """The board friends see: the worn avatar's active preset."""
        profile = self.live_profile()
        return active_preset(profile) if profile is not None else None

    def params(self) -> Dict[str, str]:
        """{name: type} of the open avatar: live while it is worn, else the
        list saved with it."""
        if self.is_live:
            return dict(self.types)
        return dict(self.profile.get("params") or {})

    def param_type(self, name: str) -> Optional[str]:
        return self.params().get(name)

    def list_avatars(self) -> List[Dict[str, Any]]:
        """The saved-avatar menu: named ones, plus the open and the worn one."""
        out = [p for p in self.store.list_profiles()
               if p["named"] or p["avatar_id"] in (self.avatar_id, self.live_avatar_id)]
        ids = {p["avatar_id"] for p in out}
        if self.avatar_id and self.avatar_id not in ids:
            out.append({"avatar_id": self.avatar_id, "name": self.avatar_name, "named": False})
        return out

    def open_avatar(self, avatar_id: str) -> bool:
        """Open an avatar on the page (a saved one, or the worn one)."""
        if not avatar_id or avatar_id == self.avatar_id:
            return False
        self.avatar_id = avatar_id
        if self._live_profile is not None and self._live_profile["avatar_id"] == avatar_id:
            self.profile = self._live_profile       # edits made on it stay one copy
        else:
            self.profile = self._load(avatar_id)
        self._live_profile = None
        self.board = active_preset(self.profile)
        return True

    def rename_avatar(self, name: str) -> bool:
        new = " ".join(str(name).split())[:AVATAR_NAME_MAX] or short_avatar_name(self.avatar_id)
        if new in (self.profile.get("name"), self.avatar_name) or not self.avatar_id:
            return False         # leaving the field unedited must not rebuild the page
        self.profile["name"] = new
        self._save()             # naming an avatar is what keeps it in the menu
        return True

    def avatar_changed(self, avatar_id: str) -> bool:
        """VRChat says which avatar is worn. Only a change moves the page to
        it; the worn avatar's parameter types start over."""
        avatar_id = str(avatar_id or "").strip()
        if not avatar_id or avatar_id == self.live_avatar_id:
            return False
        self.live_avatar_id = avatar_id
        self.types = {}
        if not self.open_avatar(avatar_id):
            self._live_profile = None
        return True

    def set_vrchat_name(self, name: str) -> bool:
        """VRChat's own name for the worn avatar (vrchat_avatars): what it
        is called until you name it. True when that changed (it is saved
        with the avatar, so the menu has it while VRChat is closed)."""
        profile = self.live_profile()
        name = " ".join(str(name or "").split())[:AVATAR_NAME_MAX]
        if profile is None or not name or profile.get("vrc_name") == name:
            return False
        profile["vrc_name"] = name
        self.store.save(profile)
        return True

    def avatar_gone(self) -> None:
        """VRChat closed: nothing is worn (the page stays where it is)."""
        if self.live_avatar_id is not None and not self.is_live:
            self._live_profile = None
        self.live_avatar_id = None
        self.types = {}

    def sync_params(self, types: Dict[str, str]) -> Tuple[bool, bool]:
        """The worn avatar's whole parameter list. Remembered with its
        profile (for offline editing) when the set changed; controls follow
        a parameter whose type changed. Returns (list changed, a control
        changed)."""
        profile = self.live_profile()
        if profile is None:
            return False, False
        types = {str(n): p for n, p in types.items() if p in PTYPES}
        changed = types != self.types
        self.types = types
        remember = bool(types) and profile.get("params") != types
        if remember:
            profile["params"] = dict(types)
        retyped = False
        for preset in profile["presets"]:
            for control in preset["controls"]:
                live = types.get(control["param"])
                if live in KINDS_FOR_PTYPE and live != control.get("ptype"):
                    retype_control(control, live)
                    retyped = True
        if remember or retyped:
            self.store.save(profile)
        return changed, retyped

    # -- controls --------------------------------------------------------------

    def next_on_value(self, param: str, exclude: Optional[str] = None) -> int:
        """ON value for a new Int toggle / button on `param`: the lowest one
        no other toggle / button for it uses yet, so adding the same Int
        three times gives Outfit = 1, 2, 3."""
        used = {int_switch_values(c)[0] for c in self.board["controls"]
                if c["param"] == param and c["id"] != exclude and is_int_switch(c)}
        return next((v for v in range(1, INT_MAX + 1) if v not in used), 1)

    def _insert(self, control: Dict[str, Any], cat: str, index: Optional[int]) -> None:
        controls = self.board["controls"]
        siblings = [i for i, c in enumerate(controls) if c["cat"] == cat]
        if index is None or index >= len(siblings):
            at = (siblings[-1] + 1) if siblings else len(controls)
        else:
            at = siblings[max(0, index)]
        controls.insert(at, control)

    def add_control(self, param: str, kind: str, label: Optional[str] = None,
                    vmin: Optional[float] = None, vmax: Optional[float] = None,
                    category: Optional[str] = None, invert: bool = False,
                    index: Optional[int] = None, on: Optional[int] = None,
                    off: Optional[int] = None) -> Optional[Dict[str, Any]]:
        param = str(param or "").strip()
        if kind not in CONTROL_KINDS or not param or not self.avatar_id:
            return None
        on_default = self.next_on_value(param)
        ptype = self.param_type(param) or {"toggle": "Bool", "button": "Bool",
                                           "slider": "Float", "int": "Int"}[kind]
        if kind not in KINDS_FOR_PTYPE.get(ptype, CONTROL_KINDS):
            kind = default_kind(ptype)           # e.g. a stepper asked for a Bool
        cat_ids = {c["id"] for c in self.board["categories"]}
        cat = category if category in cat_ids else self.board["categories"][0]["id"]
        control: Dict[str, Any] = {"id": new_id(), "param": param, "ptype": ptype,
                                   "kind": kind, "label": (label or param)[:LABEL_MAX], "cat": cat}
        if kind in ("slider", "int"):
            control["min"] = float(vmin) if vmin is not None else 0.0
            control["max"] = (float(vmax) if vmax is not None
                              else (1.0 if kind == "slider" and ptype == "Float" else float(INT_MAX)))
        if ptype == "Bool" and invert:
            control["invert"] = True
        if ptype == "Int" and kind in ("toggle", "button"):
            control["on"] = _clamp_int(on, on_default)
            control["off"] = _clamp_int(off, 0)
        self._insert(control, cat, index)
        self._save()
        return control

    def update_control(self, control_id: str, **changes: Any) -> bool:
        control = find_control(self.board, control_id)
        if control is None:
            return False
        live = self.param_type(control["param"])
        if live in KINDS_FOR_PTYPE and live != control.get("ptype"):
            retype_control(control, live)        # edit against the avatar's real type
        if changes.get("kind") not in KINDS_FOR_PTYPE.get(control["ptype"], CONTROL_KINDS):
            changes.pop("kind", None)
        for key in ("label", "min", "max", "kind", "invert"):
            if key in changes and changes[key] is not None:
                control[key] = changes[key]
        control["label"] = str(control.get("label") or control["param"])[:LABEL_MAX]
        if control["kind"] in ("slider", "int"):
            control.setdefault("min", 0.0)
            control.setdefault("max", 1.0 if control["ptype"] == "Float" else float(INT_MAX))
        if control["ptype"] != "Bool":
            control.pop("invert", None)
        if is_int_switch(control):
            on = changes.get("on", control.get("on"))
            off = changes.get("off", control.get("off"))
            control["on"] = _clamp_int(on, self.next_on_value(control["param"], control_id))
            control["off"] = _clamp_int(off, 0)
        self._save()
        return True

    def remove_control(self, control_id: str) -> bool:
        before = len(self.board["controls"])
        self.board["controls"] = [c for c in self.board["controls"] if c["id"] != control_id]
        if len(self.board["controls"]) == before:
            return False
        self._save()
        return True

    def move_control(self, control_id: str, cat_id: str, index: Optional[int] = None) -> bool:
        """Drag & drop: a control into a category, at a position in it."""
        control = find_control(self.board, control_id)
        if control is None or find_category(self.board, cat_id) is None:
            return False
        self.board["controls"].remove(control)
        control["cat"] = cat_id
        self._insert(control, cat_id, index)
        self._save()
        return True

    # -- categories --------------------------------------------------------------

    def add_category(self, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.avatar_id:
            return None
        cats = self.board["categories"]
        used = {c.get("color") for c in cats}
        # a colour not on the board yet; cycle once all are used
        color = next((c for c in _NEW_CATEGORY_HUES if c not in used),
                     _NEW_CATEGORY_HUES[len(cats) % len(_NEW_CATEGORY_HUES)])
        cat = {"id": new_id(), "name": (name or f"Category {len(cats) + 1}")[:NAME_MAX],
               "locked": False, "color": color}
        cats.append(cat)
        self._save()
        return cat

    def move_category(self, cat_id: str, target_id: str) -> bool:
        """Drag & drop: `cat_id` to where `target_id` is."""
        cats = self.board["categories"]
        src = next((i for i, c in enumerate(cats) if c["id"] == cat_id), None)
        dst = next((i for i, c in enumerate(cats) if c["id"] == target_id), None)
        if src is None or dst is None or src == dst:
            return False
        cats.insert(dst, cats.pop(src))
        self._save()
        return True

    def rename_category(self, cat_id: str, name: str) -> bool:
        cat = find_category(self.board, cat_id)
        new = str(name)[:NAME_MAX]
        if cat is None or not new or new == cat["name"]:
            return False          # focus left without an edit: no save, no rebuild
        cat["name"] = new
        self._save()
        return True

    def set_category_locked(self, cat_id: str, locked: bool) -> bool:
        cat = find_category(self.board, cat_id)
        if cat is None or cat["locked"] == bool(locked):
            return False
        cat["locked"] = bool(locked)
        self._save()
        return True

    def set_category_color(self, cat_id: str, color: str) -> bool:
        cat = find_category(self.board, cat_id)
        if cat is None or color not in CATEGORY_HUES:
            return False
        cat["color"] = color
        self._save()
        return True

    def remove_category(self, cat_id: str) -> bool:
        """Delete a category; its controls move to the first one left."""
        cats = self.board["categories"]
        if len(cats) <= 1:
            return False          # a board always keeps one
        idx = next((i for i, c in enumerate(cats) if c["id"] == cat_id), None)
        if idx is None:
            return False
        cats.pop(idx)
        for control in self.board["controls"]:
            if control.get("cat") == cat_id:
                control["cat"] = cats[0]["id"]
        self._save()
        return True

    # -- presets --------------------------------------------------------------------

    def list_presets(self) -> List[Dict[str, str]]:
        return [{"id": p["id"], "name": p["name"]} for p in self.profile["presets"]]

    def add_preset(self, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.avatar_id:
            return None
        presets = self.profile["presets"]
        preset = normalize_preset({"name": (name or f"Preset {len(presets) + 1}")[:NAME_MAX]})
        presets.append(preset)
        self.profile["active_preset"] = preset["id"]
        self.board = preset
        self._save()
        return preset

    def rename_preset(self, preset_id: str, name: str) -> bool:
        preset = next((p for p in self.profile["presets"] if p["id"] == preset_id), None)
        new = " ".join(str(name).split())[:NAME_MAX]
        if preset is None or not new or new == preset["name"]:
            return False
        preset["name"] = new
        self._save()
        return True

    def remove_preset(self, preset_id: str) -> bool:
        """Delete a preset (one always stays)."""
        presets = self.profile["presets"]
        if len(presets) <= 1:
            return False
        idx = next((i for i, p in enumerate(presets) if p["id"] == preset_id), None)
        if idx is None:
            return False
        presets.pop(idx)
        if self.profile.get("active_preset") == preset_id:
            self.profile["active_preset"] = presets[0]["id"]
        self.board = active_preset(self.profile)
        self._save()
        return True

    def switch_preset(self, preset_id: str) -> bool:
        if (preset_id not in {p["id"] for p in self.profile["presets"]}
                or self.profile.get("active_preset") == preset_id):
            return False
        self.profile["active_preset"] = preset_id
        self.board = active_preset(self.profile)
        self._save()
        return True

    def copy_category_to_preset(self, cat_id: str, preset_id: str) -> bool:
        """A category and its controls, copied into another preset."""
        source = find_category(self.board, cat_id)
        target = next((p for p in self.profile["presets"] if p["id"] == preset_id), None)
        if source is None or target is None or target is self.board:
            return False
        new_cat = dict(copy.deepcopy(source), id=new_id())
        target["categories"].append(new_cat)
        for control in self.board["controls"]:
            if control.get("cat") == cat_id:
                target["controls"].append(dict(copy.deepcopy(control), id=new_id(),
                                               cat=new_cat["id"]))
        self._save()
        return True

    # -- what a control sends ------------------------------------------------------

    def live_control(self, control_id: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """A control on the worn avatar's board, and whether its category
        is locked -- (None, False) when it isn't there."""
        board = self.live_board()
        if board is None:
            return None, False
        control = find_control(board, control_id)
        if control is None:
            return None, False
        cat = find_category(board, control.get("cat"))
        return control, bool(cat and cat.get("locked"))
