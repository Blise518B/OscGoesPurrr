"""The Friends link — a sealed engine that keeps one live connection to every
friend who is online.

Built on iroh (QUIC between two PCs, dialled by public key): hole punching
for a direct path, n0's free relays when that fails, so nobody runs a
server. This OGP's identity is a key pair in its own file (never in a
settings backup: two PCs sharing it would be one friend twice); the public
half is the ID friends paste.

Runs its own asyncio loop on a worker thread, like `haptic_engine`. The
outside world only uses the primitive methods below; everything the link
learns comes back through `on_event(kind, peer, data)` — called on the
link's thread, so it must be cheap and thread-safe:

  * ``online``                 — reachable; ``my_id`` is final
  * ``request``  (nick)        — an unknown ID asks to become a friend;
                                 answer with `answer()`
  * ``request_over``           — that question went away (answered, or the
                                 asker gave up)
  * ``linked``   (nick)        — a friend is connected
  * ``unlinked`` (reason)      — that connection ended: "bye" (they closed
                                 OGP), "timeout", "removed", "lost"
  * ``declined``               — the ID we asked turned us down
  * ``gave_up``                — a pasted ID never answered; we stopped asking
  * ``removed``                — they unfriended us (we stop dialling them)
  * ``nick``     (nick)        — a friend renamed themselves
  * ``message``  (dict)        — anything else they sent (``st``, ``cmd``,
                                 ``shk`` — see remote_protocol.py; the
                                 avatar board's ``pw`` ``pbd`` ``pv``
                                 ``pst`` ``ph`` — remote_params.py)

Light on the network, so n0's free relays never see us as a nuisance:

  * No polling of offline friends. An OGP that comes online dials each of
    its friends once (one at a time, DIAL_GAP_S apart) -- whoever is online
    answers, and whoever comes online later dials us. Retries after a
    failed dial back off (RETRY_S: 10 s ... then every 30 min); a friend who
    closed OGP is next tried after 30 min (they dial us when they're back);
    a link that dropped is redialled at once. However long the list, those
    retries share one budget -- one per BACKGROUND_GAP_S, the fewest failed
    dials first -- so a thousand friends cost the network what 180 do. A
    pasted ID or invite retries faster (ASK_RETRY_S), since someone is
    waiting for it, and is given up after ASK_GIVE_UP tries.
  * On a live link, `status_for(peer)` and `cmd_for(peer)` are looked at
    four times a second but only sent when they changed (plus REPEATS
    copies, since datagrams can get lost, and the status every
    STATE_REFRESH_S). The one exception is a cmd that drives toys: it goes
    out every SEND_S while any level is up, because the receiver drops a
    friend's levels after DRIVE_STALE_S without a word. `more_for(peer)`
    adds further slots the same way (an avatar board's watch, values and
    held buttons -- remote_session.drives / refreshes say which repeat).
  * Datagrams only, except a whole avatar board: `send_blob` opens a
    stream for it (one message, at most remote_params.MAX_BLOB), only when
    a friend looks at a board they don't have yet.
  * A ping only when nothing else went out for PING_S; DEAD_S without a
    word and the link is dropped and dialled again.

One RemoteLink per process: the iroh bindings keep a single asyncio loop
for every call (`uniffi_set_event_loop` is global), so a second link on its
own thread would steal the first one's loop.

Pairing: whoever pastes the other's ID dials; the other side is asked (the
asker's link stays up meanwhile with ``wait`` datagrams). An invite link
carries a code the dialler sends in its ``hello``; when
`invite_ok(peer, code)` says it is one of ours, nobody is asked. Friends
dial each other by themselves from then on; if both dial at once, both keep
the connection the lower ID dialled.

A browser on your web remote (docs/remote.html, iroh in WebAssembly from
tools/web_guest -- always through a relay) speaks the same protocol and
says ``web`` in its hello. `invite_ok` lets it in with your web remote's
code (the facade makes it a web guest, never a contact, so nobody dials
it); with any other code it is told WEB_CLOSED and never asked about.
"""

import asyncio
import os
import random
import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional

import remote_protocol as proto
from version import VERSION as APP_VERSION
from remote_session import CMD_HZ, DEAD_S, HELLO_S, PING_S, SEND_S, Session, path_kind

IROH_ERROR = ""             # why iroh didn't load, for the log
try:
    import iroh
except Exception as _e:  # missing wheel: the Friends page says so
    iroh = None
    IROH_ERROR = f"{type(_e).__name__}: {_e}"

DIAL_GAP_S = 0.25    # new dials go out one at a time
RETRY_S = (10.0, 30.0, 120.0, 600.0, 1800.0)    # after failed dials in a row
BACKGROUND_GAP_S = 10.0     # those retries, all friends together: one per this at most
ASK_RETRY_S = (3.0, 5.0, 10.0, 30.0, 60.0, 300.0)
ASK_GIVE_UP = len(ASK_RETRY_S) + 3   # tries before a pasted ID is given up on (~20 min)
DIAL_TIMEOUT_S = 6.0
LAG_TICK_S = 0.25              # the link loop's own heartbeat ...
LAG_WARN_S = 0.5               # ... running this much late is logged
QUALITY_EVERY_S = 300.0        # a quality line per friend in the debug log
SLOW_BUILD_S = 0.05            # building one friend's sends taking this long is logged
MAX_BLOB = 256 * 1024          # remote_params.MAX_BLOB
BLOB_KINDS = ("pbd",)          # what may come over a stream
REQUEST_TIMEOUT_S = 120.0
# Why a browser on the web remote is let go (its page says so and stops):
# the link doesn't work (off, replaced, never was) / you kicked it.
WEB_CLOSED = b"nolink"
WEB_KICKED = b"kicked"


def available() -> bool:
    return iroh is not None


def valid_id(text: str) -> bool:
    return proto.valid_id(text)


def short_id(peer: str) -> str:
    return str(peer)[:8]


def _duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 120:
        return f"{seconds} s"
    if seconds < 7200:
        return f"{seconds // 60} min"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


class RemoteLink:
    def __init__(self, key_path: str, log: Callable[[str], None],
                 on_event: Callable[[str, str, Any], None],
                 status_for: Callable[[str], Optional[Dict[str, Any]]],
                 cmd_for: Callable[[str], Optional[Dict[str, Any]]],
                 invite_ok: Optional[Callable[[str, str, str], bool]] = None,
                 more_for: Optional[Callable[[str], Dict[str, Dict[str, Any]]]] = None,
                 debug: Optional[Callable[[str], None]] = None):
        self._key_path = str(key_path)
        self._log = log
        # the debug log only: how each link is doing (paths, losses, stalls)
        self._debug = debug or (lambda _m: None)
        self._on_event = on_event
        self._status_for = status_for
        self._cmd_for = cmd_for
        self._invite_ok = invite_ok or (lambda _peer, _code, _nick: False)
        self._more_for = more_for or (lambda _peer: {})
        self._early: list = []                     # calls made before the loop existed
        self._early_lock = threading.Lock()
        self._invites_out: Dict[str, str] = {}    # peer -> the code their invite gave us
        self._unfriended: set = set()              # told "removed" when they redial
        self._nick = ""
        self._contacts: set = set()
        self._targets: set = set()     # pasted IDs that have not accepted yet
        self._declined: set = set()
        self._sessions: Dict[str, Session] = {}
        self._pending: Dict[str, asyncio.Future] = {}
        self._nicks: Dict[str, str] = {}
        self._apps: Dict[str, str] = {}       # peer -> their OGP version ("" = says none)
        self._versions: Dict[str, int] = {}   # peer -> the protocol their hello says
        self._next_try: Dict[str, float] = {}
        self._fails: Dict[str, int] = {}          # failed dials in a row
        self._last_retry = float("-inf")          # the last background retry (BACKGROUND_GAP_S)
        self._dialing: set = set()
        self._tasks: set = set()       # running fire-and-forget tasks (_spawn)
        self._snapshot: Dict[str, Dict[str, Any]] = {}
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_ev: Optional[asyncio.Event] = None
        self._stopping = False
        self.my_id = ""
        self.online = False
        self.error = ""

    # ------------------------------------------------------------------
    # Facade — called from any thread
    # ------------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, nickname: str, contacts: Iterable[str],
              unfriended: Iterable[str] = ()) -> None:
        if self.running or iroh is None:
            return
        self._nick = proto.clean_nick(nickname)
        self._contacts = set(contacts)
        self._unfriended = set(unfriended)
        # coming online dials every friend once, whatever the last time online left
        self._next_try, self._fails, self._last_retry = {}, {}, float("-inf")
        self._stopping = False
        self.online = False
        self._thread = threading.Thread(target=self._run, name="friends-link", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.5) -> None:
        # Flagged first: a stop that comes before the link's loop exists (or
        # while it still waits to come online) holds as well.
        self._stopping = True
        loop, thread = self._loop, self._thread
        if loop is not None:
            try:
                loop.call_soon_threadsafe(self._begin_stop)
            except RuntimeError:
                pass
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                # Still closing: `running` stays true until it has, so
                # nothing starts a second link next to it (one per process).
                self._log("Friends: the link is still closing")
            else:
                self._thread = None
        self._snapshot = {}
        self.online = False

    def forget_identity(self) -> bool:
        """Only while stopped: delete the key, so the next start has a new
        ID. Nobody who knew the old one -- friends, invite links -- can
        reach this OGP any more."""
        if self.running:
            return False
        try:
            os.remove(self._key_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            self._log(f"Friends: couldn't delete the old key ({e})")
            return False
        self.my_id, self.error = "", ""
        self._contacts, self._targets, self._declined, self._dialing = set(), set(), set(), set()
        self._invites_out, self._nicks, self._next_try = {}, {}, {}
        self._apps, self._versions = {}, {}
        self._unfriended, self._fails = set(), {}
        self._sessions, self._pending, self._snapshot = {}, {}, {}
        return True

    def set_nickname(self, nickname: str) -> None:
        self._nick = proto.clean_nick(nickname)
        self._call(self._say_hello_all)

    def set_contacts(self, contacts: Iterable[str]) -> None:
        self._call(self._set_contacts, set(contacts))

    def set_unfriended(self, ids: Iterable[str]) -> None:
        """IDs we unfriended: when their OGP redials us by itself, it is
        told "removed" (and drops us) instead of popping up as a request.
        Dialling us on purpose -- a pasted ID, an invite -- still asks."""
        self._unfriended = set(ids)

    def pair_with(self, peer: str, invite: str = "") -> None:
        """Dial a pasted ID; with `invite`, the code from their invite link."""
        self._call(self._pair_with, str(peer), str(invite or ""))

    def answer(self, peer: str, accept: bool) -> None:
        self._call(self._answer, str(peer), bool(accept))

    def push_cmd(self, peer: str) -> None:
        """Send this friend's cmd now (or within 1/60 s): a control moved."""
        self._call(self._push_cmd, str(peer))

    def send_event(self, peer: str, msg: Dict[str, Any], repeat: int = 3) -> None:
        """A one-off message (a shock): sent `repeat` times 30 ms apart; the
        receiver acts on its id once."""
        self._call(self._send_event, str(peer), dict(msg), int(repeat))

    def send_blob(self, peer: str, msg: Dict[str, Any]) -> None:
        """A message too big for a datagram (an avatar board): over a
        stream of its own, in the background."""
        self._call(self._send_blob, str(peer), dict(msg))

    def drop(self, peer: str, reason: bytes = WEB_CLOSED) -> None:
        """Close the link to `peer` now, saying `reason` -- a browser on
        the web remote whose link went off or that was kicked. Nobody
        redials it: it was never a contact."""
        self._call(self._drop, str(peer), bytes(reason))

    def peer_version(self, peer: str) -> int:
        """The protocol their OGP's hello said (0 before one came). The
        link's thread -- `status_for` asks it."""
        return self._versions.get(peer, 0)

    def peers(self) -> Dict[str, Dict[str, Any]]:
        """{peer: {linked, nick, path, rtt, asking, waiting, declined}} —
        refreshed twice a second on the link's thread, read here without a
        lock."""
        return self._snapshot

    # ------------------------------------------------------------------
    # The link's own thread
    # ------------------------------------------------------------------

    def _call(self, fn, *args) -> None:
        if self._stopping:
            return
        with self._early_lock:
            loop = self._loop
            if loop is None:
                if self.running:
                    self._early.append((fn, args))   # starting: run once the loop is up
                return
        try:
            loop.call_soon_threadsafe(fn, *args)
        except RuntimeError:
            pass

    def _emit(self, kind: str, peer: str = "", data: Any = None) -> None:
        try:
            self._on_event(kind, peer, data)
        except Exception as e:
            self._log(f"Friends: event handler failed ({kind}): {e}")

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as e:
            self.error = str(e)
            self._log(f"Friends link stopped: {e}")
        finally:
            self._loop = None

    def _load_key(self) -> bytes:
        """The Friends ID's secret. Only a missing file makes a new one: a
        file that can't be read right now (antivirus, a sync tool) stops
        the link with the reason instead -- a new ID would lose every
        friend. A damaged one is kept aside as .bad and replaced, loudly."""
        try:
            with open(self._key_path, "rb") as fh:
                key = fh.read()
        except FileNotFoundError:
            key = b""
        except OSError as e:
            raise OSError(f"couldn't read your Friends key ({e}) - try again in a moment") from e
        if len(key) == 32:
            return key
        if key:
            os.replace(self._key_path, self._key_path + ".bad")
            self._log(f"Friends: your key file was damaged ({len(key)} bytes) - kept it as "
                      f"{os.path.basename(self._key_path)}.bad and made a new ID")
        key = iroh.SecretKey.generate().to_bytes()
        os.makedirs(os.path.dirname(self._key_path) or ".", exist_ok=True)
        tmp = self._key_path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(key)
        os.replace(tmp, self._key_path)
        return key

    async def _main(self) -> None:
        loop = asyncio.get_running_loop()
        iroh.iroh_ffi.uniffi_set_event_loop(loop)
        self._stop_ev = asyncio.Event()
        with self._early_lock:
            self._loop = loop
            early, self._early = self._early, []
        if self._stopping:                  # stopped before the loop was up
            self._stop_ev.set()
        for fn, args in early:
            loop.call_soon(fn, *args)
        self._ep = await iroh.Endpoint.bind(iroh.EndpointOptions(
            preset=iroh.preset_n0(), secret_key=self._load_key(), alpns=[proto.ALPN]))
        self.my_id = str(self._ep.id())
        stopper = loop.create_task(self._stop_ev.wait())
        tasks = [loop.create_task(self._accept_loop()), loop.create_task(self._lag_loop()),
                 stopper]
        t0 = time.monotonic()
        # online() only returns once a home relay answers -- never, without
        # internet -- so a stop must not wait for it.
        coming = loop.create_task(self._ep.online())
        await asyncio.wait({coming, stopper}, return_when=asyncio.FIRST_COMPLETED)
        if coming.done():
            coming.result()                 # a failure ends the link (`error`)
            self.online = True
            self._log(f"Friends: online after {time.monotonic() - t0:.1f} s")
            self._emit("online")
            tasks += [loop.create_task(self._dial_loop()), loop.create_task(self._snapshot_loop())]
            await stopper
        else:
            coming.cancel()
        for s in list(self._sessions.values()):
            s.close(0, b"bye")
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result(False)
        await asyncio.sleep(0.05)
        for t in tasks:
            t.cancel()
        try:
            await asyncio.wait_for(self._ep.close(), 1.0)
        except Exception:
            pass

    def _begin_stop(self) -> None:
        self._stopping = True
        if self._stop_ev is not None:
            self._stop_ev.set()

    async def _lag_loop(self) -> None:
        """This loop carries every friend's datagrams: when it runs late,
        everyone's updates wait -- a friend's drive can go stale with the
        network fine. Says so in the debug log (once per 10 s at most)."""
        said = 0.0
        while True:
            t = time.monotonic()
            await asyncio.sleep(LAG_TICK_S)
            now = time.monotonic()
            late = now - t - LAG_TICK_S
            if late >= LAG_WARN_S and now - said >= 10.0:
                said = now
                self._debug(f"Friends: the link was held up for {late:.1f} s "
                            "- every friend's updates waited")

    def _name(self, peer: str) -> str:
        return self._nicks.get(peer) or short_id(peer)

    def _watch_path(self, s: Session, now: float) -> str:
        """The path now; a change, and every QUALITY_EVERY_S a quality
        line, go to the debug log."""
        path = path_kind(s.conn)
        if path != s.path:
            if s.path or path not in ("", "connecting"):
                what = {"relay": "goes through a relay", "connecting": "has no working path",
                        "": "has no path"}.get(path, f"is {path}")
                s.path = path
                self._debug(f"Friends: the link to {self._name(s.peer)} {what} now "
                            f"({s.quality()})")
            s.path = path
        if now - s.reported >= QUALITY_EVERY_S:
            s.reported = now
            self._debug(f"Friends: the link to {self._name(s.peer)}: {s.quality()}")
        return path

    async def _snapshot_loop(self) -> None:
        while True:
            snap: Dict[str, Dict[str, Any]] = {}
            now = time.monotonic()
            for peer in self._contacts | self._targets | set(self._sessions):
                s = self._sessions.get(peer)
                live = bool(s and s.live and not s.closed)
                snap[peer] = {
                    "linked": live,
                    "nick": self._nicks.get(peer, ""),
                    "path": self._watch_path(s, now) if live else "",
                    "rtt": s.rtt if live else None,
                    "asking": peer in self._targets and not live,
                    "waiting": bool(s and s.waiting),
                    "declined": peer in self._declined,
                }
            self._snapshot = snap
            await asyncio.sleep(0.5)

    # contacts, pairing
    def _set_contacts(self, contacts: set) -> None:
        removed = self._contacts - contacts
        self._contacts = contacts
        self._targets -= contacts
        for peer in removed:
            s = self._sessions.get(peer)
            if s:
                s.close(7, b"removed")

    def _pair_with(self, peer: str, invite: str = "") -> None:
        if peer == self.my_id:
            return
        if invite:
            self._invites_out[peer] = invite
        self._declined.discard(peer)
        if peer not in self._contacts:
            self._targets.add(peer)
        self._next_try[peer] = 0.0
        self._fails[peer] = 0

    def _drop(self, peer: str, reason: bytes) -> None:
        s = self._sessions.get(peer)
        if s is not None and not s.closed:
            s.close(5, reason)

    def _answer(self, peer: str, accept: bool) -> None:
        fut = self._pending.get(peer)
        if fut is not None and not fut.done():
            fut.set_result(accept)

    def _hello(self, peer: str) -> Dict[str, Any]:
        msg: Dict[str, Any] = {"t": "hello", "nick": self._nick, "v": proto.PROTOCOL_VERSION,
                               "app": APP_VERSION}
        code = self._invites_out.get(peer)
        if code:
            msg["invite"] = code
        if peer in self._targets:
            msg["ask"] = 1            # dialled on purpose, not a friend's redial
        return msg

    def _say_hello_all(self) -> None:
        for s in self._sessions.values():
            if s.live:
                s.send(self._hello(s.peer))

    # incoming
    async def _accept_loop(self) -> None:
        while True:
            inc = await self._ep.accept_next()
            if inc is None:
                return
            self._spawn(self._incoming(inc))

    async def _incoming(self, inc) -> None:
        try:
            conn = await (await inc.accept()).connect()
        except Exception as e:
            self._log(f"Friends: an incoming connection failed ({type(e).__name__})")
            self._debug(f"Friends: the incoming connection failed with: {str(e)[:200] or '-'}")
            return
        peer = str(conn.remote_id())
        if self._stopping:
            conn.close(0, b"bye")
            return
        if peer in self._contacts or peer in self._targets:
            self._adopt(conn, peer, dialer=peer, live=True)
            return
        if peer in self._pending:
            conn.close(4, b"busy")
            return
        await self._ask_user(conn, peer)

    async def _ask_user(self, conn, peer: str) -> None:
        """An unknown ID: hear its nickname, then ask the user, keeping the
        asker's link alive while they decide."""
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[peer] = fut
        try:
            await self._ask_user_with(conn, peer, fut)
        finally:
            self._pending.pop(peer, None)

    async def _ask_user_with(self, conn, peer: str, fut) -> None:
        loop = asyncio.get_running_loop()
        heard = asyncio.Event()
        said: Dict[str, Any] = {}      # what this connection's hello carried

        async def listen():
            try:
                while True:
                    msg = proto.decode(await conn.read_datagram())
                    if msg and msg.get("t") == "hello":
                        self._nicks[peer] = proto.clean_nick(msg.get("nick"))
                        if msg.get("invite"):
                            said["invite"] = str(msg["invite"])[:16]
                        if msg.get("ask"):
                            said["ask"] = True
                        if msg.get("web"):
                            said["web"] = True
                        heard.set()
            except Exception:
                heard.set()

        reader = loop.create_task(listen())
        try:
            await asyncio.wait_for(heard.wait(), 2.0)
        except asyncio.TimeoutError:
            pass
        code = said.get("invite", "")
        if code and not self._stopping and self._invite_ok(peer, code, self._nicks.get(peer, "")):
            # They came with one of our invite links: no question to ask.
            reader.cancel()
            self._pending.pop(peer, None)
            self._log(f"Friends: {self._nicks.get(peer) or short_id(peer)} came with your invite link")
            self._adopt(conn, peer, dialer=peer, live=True)
            return
        if said.get("web"):
            # A browser (docs/remote.html) with a web remote link that doesn't
            # work any more -- or never did: told so, never a friend request.
            reader.cancel()
            self._pending.pop(peer, None)
            conn.close(5, WEB_CLOSED)
            return
        if peer in self._unfriended and not said.get("ask"):
            # Someone we unfriended, their OGP redialling by itself: tell it.
            reader.cancel()
            self._pending.pop(peer, None)
            conn.close(7, b"removed")
            return
        self._log(f"Friends: {self._nicks.get(peer) or short_id(peer)} asks to be your friend")
        self._emit("request", peer, self._nicks.get(peer, ""))
        t0 = time.monotonic()
        last_wait = -PING_S
        ok = False
        try:
            while not fut.done() and not conn.close_reason() and time.monotonic() - t0 < REQUEST_TIMEOUT_S:
                if time.monotonic() - last_wait >= PING_S:
                    # keeps the asker's link alive (DEAD_S) while you decide
                    last_wait = time.monotonic()
                    try:
                        conn.send_datagram(b'{"t":"wait"}')
                    except Exception:
                        pass
                try:
                    await asyncio.wait_for(asyncio.shield(fut), 0.5)
                except asyncio.TimeoutError:
                    pass
            ok = fut.done() and fut.result()
        finally:
            reader.cancel()
            self._pending.pop(peer, None)
            self._emit("request_over", peer)
        if conn.close_reason():
            return
        if not fut.done() or self._stopping:
            # nobody answered, or this OGP is closing: not a no -- they ask again later
            conn.close(5, b"unanswered")
            return
        if not ok:
            conn.close(5, b"refused")
            return
        self._adopt(conn, peer, dialer=peer, live=True)

    # outgoing
    async def _dial_loop(self) -> None:
        while True:
            # one new dial per DIAL_GAP_S, so a long list never goes out in a burst
            peer = self._next_dial(time.monotonic())
            if peer is not None:
                self._dialing.add(peer)
                self._spawn(self._dial(peer))
            await asyncio.sleep(DIAL_GAP_S)

    def _next_dial(self, now: float) -> Optional[str]:
        """Who to dial now, if anyone. Pasted IDs first (someone is
        waiting), then a friend's first try since coming online and a
        dropped link -- both at once. A retry of a friend who wasn't there
        waits for the shared budget (BACKGROUND_GAP_S): the one with the
        fewest failed dials goes first (a link that just dropped before
        someone who has been offline all day), then the longest overdue."""
        due = [peer for peer in sorted(self._targets) + sorted(self._contacts - self._targets)
               if not (peer in self._sessions or peer in self._dialing or peer in self._declined
                       or peer in self._pending or now < self._next_try.get(peer, 0.0))]
        for peer in due:
            if peer in self._targets or not self._fails.get(peer):
                return peer
        if due and now - self._last_retry >= BACKGROUND_GAP_S:
            self._last_retry = now
            return min(due, key=lambda p: (self._fails.get(p, 0), self._next_try.get(p, 0.0)))
        return None

    def _retry_later(self, peer: str) -> None:
        steps = ASK_RETRY_S if peer in self._targets else RETRY_S
        n = self._fails.get(peer, 0)
        self._fails[peer] = n + 1
        if peer in self._targets and n + 1 >= ASK_GIVE_UP:
            # a mistyped ID, or someone never online: stop asking
            self._targets.discard(peer)
            self._invites_out.pop(peer, None)
            self._log(f"Friends: gave up asking {self._nicks.get(peer) or short_id(peer)}")
            self._emit("gave_up", peer)
            return
        delay = steps[min(n, len(steps) - 1)] * (0.9 + 0.2 * random.random())
        self._next_try[peer] = time.monotonic() + delay

    async def _dial(self, peer: str) -> None:
        try:
            addr = iroh.EndpointAddr(iroh.EndpointId.from_string(peer), None, [])
            conn = await asyncio.wait_for(self._ep.connect(addr, proto.ALPN), DIAL_TIMEOUT_S)
            self._adopt(conn, peer, dialer=self.my_id, live=False)
        except Exception:
            self._retry_later(peer)
        finally:
            self._dialing.discard(peer)

    def _adopt(self, conn, peer: str, dialer: str, live: bool) -> None:
        if self._stopping:
            conn.close(0, b"bye")
            return
        cur = self._sessions.get(peer)
        if cur is not None and not cur.closed:
            if cur.dialer != dialer and dialer != min(self.my_id, peer):
                # both dialled at once: both sides keep the one the lower ID dialled
                conn.close(3, b"duplicate")
                return
            cur.close(3, b"duplicate")
        s = Session(conn, peer, dialer)
        self._sessions[peer] = s
        self._spawn(self._reader(s))
        self._spawn(self._sender(s))
        self._spawn(self._blob_reader(s))
        s.send(self._hello(peer))
        if live:
            self._went_live(s)

    def _went_live(self, s: Session) -> None:
        s.live, s.waiting = True, False
        self._fails.pop(s.peer, None)
        self._targets.discard(s.peer)
        self._invites_out.pop(s.peer, None)
        self._declined.discard(s.peer)
        nick = self._nicks.get(s.peer, "")
        self._log(f"Friends: linked with {nick or short_id(s.peer)} "
                  f"({'they' if s.dialer == s.peer else 'we'} dialled)")
        self._emit("linked", s.peer, nick)

    async def _reader(self, s: Session) -> None:
        try:
            while True:
                data = await s.conn.read_datagram()
                s.last_rx = time.monotonic()
                s.rx_n += 1
                msg = proto.decode(data)
                if msg is not None:
                    self._on_msg(s, msg)
        except Exception as e:
            s.err = str(e)
        self._ended(s)

    async def _blob_reader(self, s: Session) -> None:
        """A friend's streams: one message each (an avatar board)."""
        try:
            while not s.closed:
                recv = await s.conn.accept_uni()
                data = await recv.read_to_end(MAX_BLOB)
                s.last_rx = time.monotonic()
                msg = proto.decode(data)
                if msg is not None and msg.get("t") in BLOB_KINDS:
                    self._on_msg(s, msg)
        except Exception:
            pass          # the connection ended (the datagram reader says why)

    def _on_msg(self, s: Session, msg: Dict[str, Any]) -> None:
        t = msg["t"]
        if t == "ping":
            s.send({"t": "pong", "n": msg.get("n")})
        elif t == "pong":
            try:
                s.rtt = (time.perf_counter_ns() - int(msg["n"])) / 1e6
            except (KeyError, TypeError, ValueError):
                pass
        elif t == "wait":
            s.waiting = True
        elif t == "hello":
            nick = proto.clean_nick(msg.get("nick"))
            renamed = nick != self._nicks.get(s.peer)
            self._nicks[s.peer] = nick
            self._versions[s.peer] = proto.read_version(msg)
            if not s.live:
                self._went_live(s)
            elif renamed:
                self._emit("nick", s.peer, nick)
            # their OGP's version: said once, again only if it changes
            app = proto.clean_version(msg.get("app"))
            if self._apps.get(s.peer) != app:
                self._apps[s.peer] = app
                self._emit("version", s.peer, app)
        elif s.live and self._sessions.get(s.peer) is s:
            self._emit("message", s.peer, msg)

    async def _sender(self, s: Session) -> None:
        n = 0
        last_hello = 0.0
        slow_said = 0.0
        while not s.closed:
            await asyncio.sleep(SEND_S)
            n += 1
            now = time.monotonic()
            if s.live and self._sessions.get(s.peer) is s:
                took: Dict[str, float] = {}         # what building each part cost
                for slot, make in (("st", self._status_for), ("cmd", self._cmd_for)):
                    t0 = time.perf_counter()
                    try:
                        msg = make(s.peer)
                    except Exception as e:
                        msg = None
                        if n % 40 == 1:
                            self._log(f"Friends: building a message failed: {e}")
                    if msg:
                        s.send_state(slot, msg, now)
                    took[slot] = time.perf_counter() - t0
                t0 = time.perf_counter()
                try:
                    more = self._more_for(s.peer) or {}
                except Exception as e:
                    more = {}
                    if n % 40 == 1:
                        self._log(f"Friends: building a message failed: {e}")
                for slot, msg in more.items():
                    if slot not in ("st", "cmd") and msg:
                        s.send_state(slot, msg, now)
                took[f"{len(more)} more"] = time.perf_counter() - t0
                spent = sum(took.values())
                # this loop serves every friend: one slow friend holds up all
                if spent >= SLOW_BUILD_S and time.monotonic() - slow_said >= 10.0:
                    slow_said = time.monotonic()
                    parts = ", ".join(f"{k} {v * 1000:.0f} ms" for k, v in took.items())
                    self._debug(f"Friends: building what goes to {self._name(s.peer)} took "
                                f"{spent * 1000:.0f} ms ({parts})")
                if s.hellos > 0 or now - last_hello >= HELLO_S:
                    s.hellos = max(0, s.hellos - 1)
                    last_hello = now
                    s.send(self._hello(s.peer))
            elif not s.live and (s.early_hellos > 0 or now - last_hello >= PING_S):
                # still being asked about: keep telling them who we are --
                # quickly at first (they listen for it for 2 s), then slowly
                s.early_hellos = max(0, s.early_hellos - 1)
                last_hello = now
                s.send(self._hello(s.peer))
            if s.send_error and s.send_error != "logged":
                self._log(f"Friends: sending to {self._nicks.get(s.peer) or short_id(s.peer)} "
                          f"failed ({s.send_error})")
                s.send_error = "logged"
            if now - s.last_tx >= PING_S:
                s.send({"t": "ping", "n": time.perf_counter_ns()})
            if now - s.last_rx > DEAD_S:
                s.close(2, b"timeout")

    def _ended(self, s: Session) -> None:
        word = s.ended_word()
        if s.live:
            now = time.monotonic()
            try:
                closed_by = str(s.conn.close_reason() or "")
            except Exception:
                closed_by = ""
            self._debug(
                f"Friends: the link to {self._name(s.peer)} ended ({word}) after "
                f"{_duration(now - s.linked_at)}, last heard {now - s.last_rx:.1f} s before; "
                f"{s.quality()}; why: {(s.reason or closed_by or s.err or '-')[:200]}")
        s.closed = True
        if self._sessions.get(s.peer) is not s:
            return
        del self._sessions[s.peer]
        if word == "refused":
            self._declined.add(s.peer)
            self._targets.discard(s.peer)
            self._emit("declined", s.peer)
        elif word == "removed":
            self._declined.add(s.peer)       # no redialling: pasting their ID asks again
            self._targets.discard(s.peer)
            self._emit("removed", s.peer)
        if self._stopping:
            return
        if word == "duplicate":
            return
        if word == "unanswered" and s.peer in self._targets:
            # they didn't answer (or closed OGP): ask again, but not soon
            self._fails[s.peer] = max(self._fails.get(s.peer, 0), len(ASK_RETRY_S) - 1)
        if word in ("timeout", "lost") and s.live:
            # a dropped link comes back at once (then backs off)
            self._fails[s.peer] = 0
            self._next_try[s.peer] = time.monotonic()
        elif word == "bye":
            # they closed OGP: they dial us when they're back
            self._fails[s.peer] = len(RETRY_S) - 1
            self._next_try[s.peer] = time.monotonic() + RETRY_S[-1]
        else:
            self._retry_later(s.peer)
        if s.live:
            self._log(f"Friends: link to {self._nicks.get(s.peer) or short_id(s.peer)} ended ({word})")
            self._emit("unlinked", s.peer, word)

    def _spawn(self, coro) -> None:
        """A task of its own, kept until it ends (the loop holds tasks only
        weakly); a crash is logged instead of vanishing."""
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)

    def _task_done(self, task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            e = task.exception()
            self._log(f"Friends: a link task failed ({type(e).__name__}: {e})")

    # sending
    def _push_cmd(self, peer: str) -> None:
        s = self._sessions.get(peer)
        if s is None or not s.live or s.cmd_handle is not None:
            return
        delay = s.last_cmd + 1.0 / CMD_HZ - time.monotonic()
        if delay <= 0:
            self._flush_cmd(s)
        else:
            s.cmd_handle = asyncio.get_running_loop().call_later(delay, self._flush_cmd, s)

    def _flush_cmd(self, s: Session) -> None:
        s.cmd_handle = None
        s.last_cmd = time.monotonic()
        if s.closed:
            return
        try:
            msg = self._cmd_for(s.peer)
        except Exception:
            msg = None
        if msg:
            s.send_state("cmd", msg, s.last_cmd)

    def _send_blob(self, peer: str, msg: Dict[str, Any]) -> None:
        s = self._sessions.get(peer)
        if s is None or not s.live:
            return
        data = proto.encode(msg)
        if len(data) > MAX_BLOB:
            self._log(f"Friends: a board for {self._nicks.get(peer) or short_id(peer)} "
                      f"is too big to send ({len(data) // 1024} KB)")
            return
        self._spawn(self._write_blob(s, data))

    async def _write_blob(self, s: Session, data: bytes) -> None:
        try:
            send = await s.conn.open_uni()
            await send.write_all(data)
            await send.finish()
            s.last_tx = time.monotonic()
        except Exception as e:
            if not s.closed:
                self._log(f"Friends: sending a board to {self._nicks.get(s.peer) or short_id(s.peer)} "
                          f"failed ({type(e).__name__})")

    def _send_event(self, peer: str, msg: Dict[str, Any], repeat: int) -> None:
        s = self._sessions.get(peer)
        if s is None or not s.live:
            return
        loop = asyncio.get_running_loop()
        for i in range(max(1, repeat)):
            loop.call_later(0.03 * i, s.send, msg)
