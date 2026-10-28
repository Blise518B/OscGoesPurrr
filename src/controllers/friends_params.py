"""Friends: you and a friend's avatar board -- the "Their avatar" part of a
picked friend's panel. Part of FriendsFacade (friends_facade.py); the
owner's half (your board, friends using it) is ParamsFacade
(params_facade.py), the messages are remote_params.py.

You only "watch" one board at a time: the friend picked on the Friends page
while the page is open (`set_friend_params_watch`). Only then does their OGP
send it; when you look away, the link says so and it stops.

A toggle, slider or stepper is a set (`friend_param_set`) -- an event the
link sends a few times, applied once. A hold button is held for as long as
you hold it (`friend_param_hold`): your OGP keeps saying so every SEND_S,
and theirs lets go when it stops -- a dropped link can't leave it pressed.
What you set shows at once and stays shown for _OWN_S, until their avatar
has had time to answer.
"""

import time
from typing import Any, Dict, Optional

import param_board as pb
import remote_params as rp

_OWN_S = 1.5        # your own set is shown over theirs this long


_ASK_AGAIN_S = 4.0          # a board that hasn't come is asked for again this often

class FriendsParamsMixin:

    def _friends_params_init(self) -> None:
        self._pw_peer: Optional[str] = None        # whose board you have open
        self._pw_yolo = False                       # ... with its every-parameter list
        self._pw_was: set = set()                   # told "watching" this session
        self._their_boards: Dict[str, Dict[str, Any]] = {}
        self._their_values: Dict[str, Dict[str, Any]] = {}
        self._my_param_sets: Dict[str, Dict[str, tuple]] = {}   # peer -> name -> (value, t)
        self._my_param_holds: Dict[str, set] = {}               # peer -> control ids held
        self._had_param_holds: set = set()
        self._param_seq = int(time.time() * 1000)   # only grows, across restarts too

    # ------------------------------------------------------------------
    # The page -- GUI thread
    # ------------------------------------------------------------------

    def set_friend_params_watch(self, peer: Optional[str], yolo_open: bool = False) -> None:
        """Whose board the page shows now (None: nobody's)."""
        if peer != self._pw_peer and self._pw_peer is not None:
            self._let_go_holds(self._pw_peer)
        self._pw_peer = peer or None
        self._pw_yolo = bool(yolo_open)
        if peer:
            self._pw_was.add(peer)

    def get_friend_board(self, peer: str) -> Optional[Dict[str, Any]]:
        """What the panel shows of a friend's avatar: None when they share
        none, else {prm, board (None until it came), values, holds}."""
        demo = self._demo_of("friend", peer)
        if demo is not None:
            return demo.board(peer)
        st = self._friend_status.get(peer)
        prm = rp.read_prm(st.get("prm")) if st else None
        if prm is None:
            return None
        board = self._their_boards.get(peer)
        if board is not None and prm["avatar"] and board.get("avatar") != prm["avatar"]:
            # they changed avatar and its board hasn't come yet: never show
            # the old one as theirs ("Getting their board…")
            board = None
        values = dict(self._their_values.get(peer, {})) if board is not None else {}
        now = time.monotonic()
        for name, (value, t) in self._my_param_sets.get(peer, {}).items():
            if now - t < _OWN_S:
                values[name] = value
        return {"prm": prm, "board": board, "values": values,
                "holds": set(self._my_param_holds.get(peer, ()))}

    def friend_param_set(self, peer: str, control_id: str, value: Any) -> None:
        """A toggle, slider or stepper on a friend's board."""
        info = self._their_control(peer, control_id)
        if info is None:
            return
        control, prm = info
        out = pb.send_value(control, value)
        if out is None:
            return
        self._show_own(peer, control["param"], out)
        demo = self._demo_of("friend", peer)
        if demo is not None:
            demo.set_value(peer, control["param"], out)
        else:
            self._param_seq += 1
            self.friends_link.send_event(peer, rp.make_set(self._param_seq, value, control=control_id))
        what = _said(control, out)
        self._friends_note(f"You {what.format(nick=self._friend_nick(peer), label=control['label'])}",
                           key=("prm-out", peer, control_id))

    def friend_param_set_any(self, peer: str, name: str, value: Any) -> None:
        """YOLO: any parameter of a friend's avatar, from the full list."""
        theirs = self.get_friend_board(peer)
        board = theirs.get("board") if theirs else None
        if not board or not theirs["prm"]["yolo"] or not board.get("all"):
            return
        ptype = dict(board["all"]).get(name)
        out = pb.any_value(ptype, value) if ptype else None
        if out is None:
            return
        self._show_own(peer, name, out)
        demo = self._demo_of("friend", peer)
        if demo is not None:
            demo.set_value(peer, name, out)
        else:
            self._param_seq += 1
            self.friends_link.send_event(peer, rp.make_set(self._param_seq, out, param=name))
        what = _said(None, out, ptype)
        self._friends_note(f"You {what.format(nick=self._friend_nick(peer), label=name)} (YOLO)",
                           key=("prm-out", peer, name))

    def friend_param_hold(self, peer: str, control_id: str, held: bool) -> None:
        """A hold button on a friend's board, pressed or let go."""
        info = self._their_control(peer, control_id)
        if info is None or info[0]["kind"] != "button":
            return
        control = info[0]
        holds = set(self._my_param_holds.get(peer, ()))
        if held:
            holds.add(control_id)
        else:
            holds.discard(control_id)
        self._my_param_holds = {**self._my_param_holds, peer: holds}
        if holds:
            self._had_param_holds.add(peer)
        self._show_own(peer, control["param"], pb.send_value(control, held))
        demo = self._demo_of("friend", peer)
        if demo is not None:
            demo.set_value(peer, control["param"], pb.send_value(control, held))
        else:
            # now, not at the link's next look (the slot keeps repeating it)
            self.friends_link.send_event(peer, rp.make_holds(holds), repeat=1)
        if held:
            self._friends_note(f"You held {self._friend_nick(peer)}'s {control['label']}",
                               key=("prm-out", peer, control_id))

    def _their_control(self, peer: str, control_id: str):
        theirs = self.get_friend_board(peer)
        if not theirs or not theirs.get("board") or theirs["prm"]["stop"]:
            return None
        board = theirs["board"]
        control = pb.find_control(board, control_id)
        if control is None:
            return None
        cat = pb.find_category(board, control["cat"])
        if cat and cat.get("locked"):
            return None
        return control, theirs["prm"]

    def _show_own(self, peer: str, name: str, value: Any) -> None:
        sets = dict(self._my_param_sets.get(peer, {}))
        sets[name] = (value, time.monotonic())
        self._my_param_sets = {**self._my_param_sets, peer: sets}

    def _let_go_holds(self, peer: str) -> None:
        if self._my_param_holds.get(peer):
            self._my_param_holds = {**self._my_param_holds, peer: set()}
            if self._demo_of("friend", peer) is None:
                self.friends_link.send_event(peer, rp.make_holds(()), repeat=1)

    # ------------------------------------------------------------------
    # The link's thread
    # ------------------------------------------------------------------

    def _friends_params_more_for(self, peer: str) -> Dict[str, Dict[str, Any]]:
        """Your watch of `peer`'s board and the buttons you hold on it."""
        out: Dict[str, Dict[str, Any]] = {}
        if peer == self._pw_peer:
            st = self._friend_status.get(peer)
            if st and st.get("prm") is not None:
                board = self._their_boards.get(peer)
                have = board["ver"] if board else ""
                want = (rp.read_prm(st.get("prm")) or {}).get("ver", "")
                # a newer board on its way: ask again every few seconds (a
                # stream lost on a shaky link is sent again)
                retry = int(time.monotonic() // _ASK_AGAIN_S) if want and want != have else 0
                out["pw"] = rp.make_watch(have, self._pw_yolo, retry)
            else:
                out["pw"] = rp.WATCH_OFF
        elif peer in self._pw_was:
            out["pw"] = rp.WATCH_OFF
        holds = self._my_param_holds.get(peer)
        if holds or peer in self._had_param_holds:
            out["ph"] = rp.make_holds(holds or ())
        return out

    def _their_board_in(self, peer: str, msg: Dict[str, Any]) -> None:
        board = rp.read_board(msg)
        if board is None:
            return
        old = self._their_boards.get(peer)
        self._their_boards = {**self._their_boards, peer: board}
        self._their_values = {**self._their_values, peer: {}}
        debug = getattr(self, "_friends_debug", None)
        if debug is not None and (old is None or old["ver"] != board["ver"]):
            debug(f"Friends: got {self._friend_nick(peer)}'s board ({board['name'] or 'no name'}, "
                  f"{len(board['controls'])} controls, version {board['ver']})")

    def _their_values_in(self, peer: str, msg: Dict[str, Any]) -> None:
        board = self._their_boards.get(peer)
        if board is None:
            return
        got = rp.read_values(msg, board)
        if got:
            self._their_values = {**self._their_values,
                                  peer: {**self._their_values.get(peer, {}), **got}}

    def _drop_their_board(self, peer: str) -> None:
        self._their_boards = {k: v for k, v in self._their_boards.items() if k != peer}
        self._their_values = {k: v for k, v in self._their_values.items() if k != peer}
        self._my_param_sets = {k: v for k, v in self._my_param_sets.items() if k != peer}
        self._my_param_holds = {k: v for k, v in self._my_param_holds.items() if k != peer}
        self._had_param_holds.discard(peer)


def _said(control: Optional[Dict[str, Any]], value: Any, ptype: str = "") -> str:
    """What you did, for the log: "turned {nick}'s {label} on" ..."""
    ptype = control["ptype"] if control is not None else ptype
    if ptype == "Bool" or (control is not None and pb.is_int_switch(control)):
        on = pb.shows_on(control, value) if control is not None else bool(value)
        return "turned {nick}'s {label} " + ("on" if on else "off")
    if ptype == "Int":
        return "set {nick}'s {label} to " + str(int(value))
    return "set {nick}'s {label} to " + f"{float(value):.2f}"
