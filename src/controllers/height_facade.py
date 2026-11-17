"""Params, part 3: your height -- the Avatar Remote page's Height box
(Blise's calls, 2026-11-14), like Height Shift OSC and the other OSC scaler
tools.

VRChat's ``/avatar/eyeheight`` (avatar_height.py says what VRChat does with
it): the OSC thread hands what VRChat says to `_height_on_osc` (one set
lookup in osc_facade.on_osc_message, nothing on the parameter path), and a
write goes straight out from whichever thread asked -- the page, a friend
(the link's thread), your avatar menu's radial slot (the OSC thread) --
unless one went out less than a tenth of a second ago; the params tick
(every 100 ms) sends what was held back and steps a glide. Sent on change
only, never outside 0.1-100 m.

Decided (docs/ROADMAP.md): it stays -- when a friend stops or leaves, your
height stays where they put it (it isn't a held control); it comes with
each friend's AVATAR switch, plus the box's own switch (on by default; off,
friends and the web remote don't see it and nothing they send changes it);
Grow (glides there) and Right away (jumps); one compact box. Your lowest
and highest height (VRChat's menu range, 0.2-5 m, by default) bound
everything a friend sends -- they can't widen it. Pause all friends, the
box's lock and a world that forbids scaling refuse them (Pause also stops a
glide a friend started); your own avatar menu ignores the lock, as it does
for everything.

Mixed into ParamsFacade (params_facade.py), which owns the settings
(`params_settings`), the share friends work from (`_params_share`) and
the log.
"""

import threading
from typing import Any, Dict, Optional

import avatar_height as ah
import remote_params as rp
from event_log import IN

_PROBE_S = 1.5          # after an avatar change, VRChat's OSCQuery is asked this much later
_SEEN = "@height"       # a friend's newest height set, in ParamsFacade's _params_seen


class HeightMixin:
    """Mixin: the Height box -- yours, and a friend's use of it."""

    def _height_init(self) -> None:
        self._height = ah.HeightControl()
        self._height.double_s = self.params_settings.get_height()["double_s"]

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------

    def get_height_status(self) -> Dict[str, Any]:
        """What the box shows: the settings, VRChat's word on your height
        and the world, and a glide."""
        st = self._height.state()
        st.update(self.params_settings.get_height())
        osc = getattr(self, "osc_manager", None)
        st["vrchat"] = bool(osc is not None and getattr(osc, "is_connected", False))
        return st

    def height_go(self, height: float, mode: str = ah.GROW) -> bool:
        """You, on the box: Grow (glide) or Right away (jump) to `height`,
        kept between your lowest and highest."""
        h = ah.num(height)
        if h is None or mode not in (ah.GROW, ah.NOW):
            return False
        s = self.params_settings.get_height()
        return self._height_apply(mode, ah.clamp(h, s["lo"], s["hi"]))

    def height_reset(self) -> bool:
        """Back to your own height, right away."""
        return self._height_apply(ah.RESET, None)

    def height_set_option(self, key: str, value: Any) -> Dict[str, Any]:
        """One of the box's settings: on (friends see it), locked
        (look-only for friends), lo / hi (your lowest / highest height),
        double_s (Grow's speed). Saved; friends get it at once."""
        old = self.params_settings.get_height()
        s = dict(old)
        if key in ("lo", "hi"):
            v = ah.num(value)
            if v is None:
                return old
            s = ah.with_range(s, **{key: v})
        elif key == "double_s":
            s["double_s"] = value
        elif key in ("on", "locked"):
            s[key] = bool(value)
        else:
            raise ValueError(f"not a height setting: {key}")
        new = self.params_settings.set_height(s)
        self._height.double_s = new["double_s"]
        if new == old:
            return new
        if not new["on"] or new["locked"]:
            self._height.stop_friends()          # what a friend started stops there
        if key == "on":
            self.log_message("Avatar Remote: the Height box is on - friends you allow see it"
                             if new["on"] else
                             "Avatar Remote: the Height box is off - friends don't see it")
        self._params_rebuild_share()
        self._params_refresh_ui()
        return new

    # ------------------------------------------------------------------
    # VRChat
    # ------------------------------------------------------------------

    def _height_on_osc(self, address: str, value: Any) -> None:
        """OSC thread: one of VRChat's height messages. Friends hear of the
        world's say at the next params tick."""
        self._height.heard(address, value)

    def _height_write(self, height: float) -> bool:
        """One write to VRChat, now (any thread)."""
        osc = getattr(self, "osc_manager", None)
        if osc is None or not getattr(osc, "is_connected", False):
            return False
        try:
            osc.send_parameter(ah.EYE_HEIGHT, float(ah.safe(height)), ignore_rate_limit=True,
                               default_type="f")
        except Exception:
            return False
        return True

    def _height_apply(self, mode: str, height: Optional[float], by: Any = None) -> bool:
        """Grow / Right away / Reset, from anyone (`by`: a friend's peer id,
        None for you). False when it was refused (the world forbids scaling,
        or Reset without your own height known)."""
        c = self._height
        if c.allowed is False or (mode == ah.RESET and c.own is None):
            return False
        if mode == ah.NOW:
            out = c.jump(height, by)
        elif mode == ah.GROW:
            out = c.grow(height, by)
        else:
            out = c.reset(by)
        if out is not None:
            self._height_write(out)
        return True

    def _height_tick(self) -> None:
        """GUI tick (every 100 ms): a held-back write or a glide's step; and
        friends get the box again when the world's say on it changed."""
        out = self._height.tick()
        if out is not None:
            self._height_write(out)
        if self._height_share() != self._params_share.get("height"):
            self._params_rebuild_share()

    def _height_avatar_changed(self) -> None:
        """GUI thread: another avatar -- its own height is what VRChat says
        next (asked of its OSCQuery too: connected mid-session, nothing
        would come until something changes)."""
        self._height.avatar_changed()
        osc = getattr(self, "osc_manager", None)
        if osc is not None and getattr(osc, "query_value", None) is not None:
            timer = threading.Timer(_PROBE_S, self._height_probe)
            timer.daemon = True
            timer.start()

    def _height_probe(self) -> None:
        osc = getattr(self, "osc_manager", None)
        query = getattr(osc, "query_value", None) if osc is not None else None
        if query is None or not getattr(osc, "is_connected", False):
            return
        for key in (ah.KEY_ALLOWED, ah.KEY_MIN, ah.KEY_MAX, ah.KEY_HEIGHT):
            value = query("/" + key)
            if value is not None:
                self._height.heard(key, value)

    def _height_vrchat_gone(self) -> None:
        self._height.gone()

    # ------------------------------------------------------------------
    # Your avatar menu: a radial slot
    # ------------------------------------------------------------------

    def _height_from_menu(self, value: Any) -> None:
        """OSC thread: a Radial that holds the Height box moved -- right
        away, across your lowest..highest (the lock is about friends)."""
        x = ah.num(value)
        if x is None:
            return
        s = self.params_settings.get_height()
        self._height_apply(ah.NOW, ah.from_slider(x, s["lo"], s["hi"]))

    def _height_menu_state(self) -> Optional[float]:
        """Where the Radial goes for your height now (None: not known)."""
        s = self.params_settings.get_height()
        return ah.to_slider(self._height.height, s["lo"], s["hi"])

    # ------------------------------------------------------------------
    # Friends
    # ------------------------------------------------------------------

    def _height_share(self) -> Optional[Dict[str, Any]]:
        """The board's ``ht`` (None while the box is off)."""
        s = self.params_settings.get_height()
        if not s["on"]:
            return None
        return rp.make_height_box(s["lo"], s["hi"], s["locked"], self._height.allowed is False)

    def _height_on_set(self, peer: str, msg: Dict[str, Any]) -> None:
        """The link's thread: a friend's Grow / Right away / Reset. Inside
        your range, through their AVATAR switch, Pause all, the box's switch
        and lock and the world's say -- from the snapshot friends work from."""
        got = rp.read_height_set(msg)
        if got is None:
            return
        seq, mode, value = got
        key = (peer, _SEEN)
        with self._params_lock:
            if seq <= self._params_seen.get(key, -1):
                return                      # a copy, or older than what landed
            self._params_seen[key] = seq
        share = self._params_share
        box = share.get("height")
        if (not share["ver"] or box is None or box.get("lk") or box.get("no")
                or not self._params_allowed(peer) or self._height_blocked(peer)):
            return
        before = self._height.height
        height = None if value is None else ah.clamp(value, box["lo"], box["hi"])
        spend = getattr(self, "_params_spend", None)      # how often (inbound_rate)
        if spend is not None and not spend(peer):
            return
        if not self._height_apply(mode, height, by=peer):
            return
        if mode == ah.NOW:
            text = f"{{who}} set your height to {ah.fmt(height)}"
        elif mode == ah.GROW:
            shrink = before is not None and height < before
            text = f"{{who}} {'shrank' if shrink else 'grew'} you to {ah.fmt(height)}"
        else:
            text = f"{{who}} put your height back to {ah.fmt(self._height.own)}"
        self._params_note(text, key=("prm-in", peer, _SEEN), who=peer, op="height", dir=IN)

    def _height_blocked(self, peer: str) -> bool:
        """Pause all friends refuses everyone -- and, with "only friends in
        my instance" (friends_instance.py: there `_params_blocked` takes the
        peer and `_params_refused` says in the log why), a friend who isn't
        in your instance, like any Avatar Remote set."""
        refused = getattr(self, "_params_refused", None)
        if refused is None:
            return self._params_blocked()
        if self._params_blocked(peer):
            refused(peer, "set your height")
            return True
        return False
