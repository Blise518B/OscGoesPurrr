"""RemoteLink's lifecycle and pairing edges, against a fake iroh: a stop
always stops (even before the link is online), the identity key is never
silently replaced, and an unanswered request is not a "no"."""

import asyncio
import time
import types

import pytest

import remote_link
import remote_protocol as proto
import remote_session

PEER = "c" * 64


class FakeEp:
    def __init__(self, online=False, close_s=0.0):
        self._online = online
        self._close_s = close_s

    def id(self):
        return "e" * 64

    async def online(self):
        if not self._online:
            await asyncio.Event().wait()      # no internet: never

    async def accept_next(self):
        await asyncio.Event().wait()

    async def close(self):
        await asyncio.sleep(self._close_s)


def fake_iroh(ep):
    async def bind(_opts):
        return ep
    return types.SimpleNamespace(
        iroh_ffi=types.SimpleNamespace(uniffi_set_event_loop=lambda _loop: None),
        Endpoint=types.SimpleNamespace(bind=bind),
        EndpointOptions=lambda **k: k,
        preset_n0=lambda: None,
        SecretKey=types.SimpleNamespace(
            generate=lambda: types.SimpleNamespace(to_bytes=lambda: b"k" * 32)))


class FakeConn:
    def __init__(self, reason=""):
        self.sent = []
        self.reason = reason

    def send_datagram(self, data):
        self.sent.append(proto.decode(data))

    def close_reason(self):
        return self.reason

    def close(self, code, reason):
        self.reason = self.reason or reason.decode()


def make_link(tmp_path, logs=None, events=None):
    return remote_link.RemoteLink(
        str(tmp_path / "friends_key.bin"),
        log=logs.append if logs is not None else (lambda _m: None),
        on_event=(lambda *e: events.append(e)) if events is not None else (lambda *e: None),
        status_for=lambda _p: None, cmd_for=lambda _p: None)


def until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# --- start / stop -----------------------------------------------------------

def test_a_link_that_never_comes_online_still_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_link, "iroh", fake_iroh(FakeEp(online=False)))
    link = make_link(tmp_path)
    link.start("Me", [])
    assert until(lambda: link.my_id)          # bound, waiting for a home relay
    assert not link.online
    link.stop(timeout=2.0)
    assert not link.running


def test_a_stop_right_after_start_holds(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_link, "iroh", fake_iroh(FakeEp(online=True)))
    link = make_link(tmp_path)
    link.start("Me", [])
    link.stop(timeout=2.0)                    # before its loop even exists
    assert not link.running


def test_no_second_link_starts_while_the_first_is_still_closing(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_link, "iroh", fake_iroh(FakeEp(online=True, close_s=0.6)))
    logs = []
    link = make_link(tmp_path, logs=logs)
    link.start("Me", [])
    assert until(lambda: link.online)
    first = link._thread
    link.stop(timeout=0.05)                   # closing takes longer than that
    assert link.running and "Friends: the link is still closing" in logs
    link.start("Me", [])
    assert link._thread is first              # one link per process
    assert until(lambda: not link.running)


# --- the identity key -------------------------------------------------------

def test_a_missing_key_makes_a_new_one(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_link, "iroh", fake_iroh(FakeEp()))
    link = make_link(tmp_path)
    assert link._load_key() == b"k" * 32
    assert (tmp_path / "friends_key.bin").read_bytes() == b"k" * 32
    assert not (tmp_path / "friends_key.bin.tmp").exists()


def test_an_unreadable_key_stops_the_link_instead_of_making_a_new_id(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_link, "iroh", fake_iroh(FakeEp()))
    (tmp_path / "friends_key.bin").mkdir()    # can't be read as a file
    link = make_link(tmp_path)
    with pytest.raises(OSError, match="couldn't read your Friends key"):
        link._load_key()
    assert (tmp_path / "friends_key.bin").is_dir()


def test_a_damaged_key_is_kept_aside_and_replaced_out_loud(tmp_path, monkeypatch):
    monkeypatch.setattr(remote_link, "iroh", fake_iroh(FakeEp()))
    (tmp_path / "friends_key.bin").write_bytes(b"short")
    logs = []
    link = make_link(tmp_path, logs=logs)
    assert link._load_key() == b"k" * 32
    assert (tmp_path / "friends_key.bin.bad").read_bytes() == b"short"
    assert any("damaged" in m for m in logs)


# --- pairing ----------------------------------------------------------------

def test_an_unanswered_request_is_asked_again_later_not_declined(tmp_path):
    events = []
    link = make_link(tmp_path, events=events)
    link._targets.add(PEER)
    s = remote_session.Session(FakeConn("unanswered"), PEER, "e" * 64)
    link._sessions[PEER] = s
    link._ended(s)
    assert PEER not in link._declined and PEER in link._targets
    assert link._next_try[PEER] - time.monotonic() > 200      # minutes, not seconds
    assert not [e for e in events if e[0] == "declined"]


def test_a_refused_request_is_still_a_no(tmp_path):
    events = []
    link = make_link(tmp_path, events=events)
    link._targets.add(PEER)
    s = remote_session.Session(FakeConn("refused"), PEER, "e" * 64)
    link._sessions[PEER] = s
    link._ended(s)
    assert PEER in link._declined and ("declined", PEER) in [e[:2] for e in events]


def test_a_pasted_id_that_never_answers_is_given_up_on(tmp_path):
    events = []
    link = make_link(tmp_path, events=events)
    link._targets.add(PEER)
    for _ in range(remote_link.ASK_GIVE_UP):
        link._retry_later(PEER)
    assert PEER not in link._targets
    assert ("gave_up", PEER) in [e[:2] for e in events]


def test_the_dialler_says_hello_quickly_while_being_asked(tmp_path, monkeypatch):
    # The asked side listens for the hello for 2 s; one lost datagram must
    # not turn an invite into a plain request.
    monkeypatch.setattr(remote_link, "SEND_S", 0.01)
    link = make_link(tmp_path)
    s = remote_session.Session(FakeConn(), PEER, "e" * 64)

    async def run():
        task = asyncio.ensure_future(link._sender(s))
        await asyncio.sleep(0.2)
        s.closed = True
        await task

    asyncio.run(run())
    hellos = [m for m in s.conn.sent if m and m.get("t") == "hello"]
    assert len(hellos) == 3


# --- a board over a stream ---------------------------------------------------

def test_a_board_goes_over_a_stream_and_only_a_board_does(tmp_path):
    events = []
    link = make_link(tmp_path, events=events)

    class Send:
        def __init__(self, q):
            self.q, self.buf = q, b""

        async def write_all(self, data):
            self.buf += data

        async def finish(self):
            await self.q.put(self.buf)

    class Recv:
        def __init__(self, data):
            self.data = data

        async def read_to_end(self, limit):
            assert limit == remote_link.MAX_BLOB
            return self.data

    class StreamConn(FakeConn):
        def __init__(self):
            super().__init__()
            self.q = asyncio.Queue()

        async def open_uni(self):
            return Send(self.q)

        async def accept_uni(self):
            return Recv(await self.q.get())

    async def run():
        conn = StreamConn()
        s = remote_session.Session(conn, PEER, PEER)
        s.live = True
        link._sessions[PEER] = s
        reader = asyncio.ensure_future(link._blob_reader(s))
        await link._write_blob(s, proto.encode({"t": "shk", "id": "x"}))   # not over a stream
        await link._write_blob(s, proto.encode({"t": "pbd", "b": "v1"}))
        for _ in range(20):
            await asyncio.sleep(0.005)
        s.closed = True
        reader.cancel()

    asyncio.run(run())
    assert events == [("message", PEER, {"t": "pbd", "b": "v1"})]


def test_a_board_too_big_for_a_stream_is_not_sent(tmp_path):
    logs = []
    link = make_link(tmp_path, logs=logs)
    s = remote_session.Session(FakeConn(), PEER, PEER)
    s.live = True
    link._sessions[PEER] = s
    link._send_blob(PEER, {"t": "pbd", "pad": "x" * (remote_link.MAX_BLOB + 1)})
    assert any("too big" in m for m in logs)


# --- the debug log: how each link is doing -----------------------------------

class QualityConn(FakeConn):
    """A connection that can say its path, round trip and QUIC losses."""

    def __init__(self, reason="", path="relay", fail_send=False):
        super().__init__(reason)
        self.path_now = path
        self.fail_send = fail_send

    def send_datagram(self, data):
        if self.fail_send:
            raise RuntimeError("too large")
        super().send_datagram(data)

    def max_datagram_size(self):
        return 1150

    def rtt(self):
        return 42

    def stats(self):
        return types.SimpleNamespace(lost_packets=3, udp_tx_datagrams=120)

    def paths(self):
        if self.path_now == "connecting":
            return []
        return [types.SimpleNamespace(is_selected=True, is_relay=self.path_now == "relay",
                                      remote_addr="192.168.1.5:4000")]


def debug_link(tmp_path):
    lines = []
    link = remote_link.RemoteLink(
        str(tmp_path / "friends_key.bin"), log=lambda _m: None, on_event=lambda *e: None,
        status_for=lambda _p: None, cmd_for=lambda _p: None, debug=lines.append)
    return link, lines


def test_a_link_that_ends_says_how_it_went(tmp_path):
    link, lines = debug_link(tmp_path)
    s = remote_session.Session(QualityConn("timeout"), PEER, PEER)
    s.live, s.path, s.rx_n, s.tx_n = True, "relay", 0, 70
    link._sessions[PEER] = s
    link._ended(s)
    line = lines[-1]
    assert "ended (timeout)" in line and "relay" in line and "round trip 42 ms" in line
    assert "0 datagrams in / 70 out" in line and "QUIC lost 3 of 120" in line


def test_a_path_change_is_logged_once(tmp_path):
    link, lines = debug_link(tmp_path)
    conn = QualityConn(path="relay")
    s = remote_session.Session(conn, PEER, PEER)
    s.live = True
    now = time.monotonic()
    link._watch_path(s, now)
    assert len(lines) == 1 and "goes through a relay now" in lines[0]
    link._watch_path(s, now)                  # unchanged: nothing more
    conn.path_now = "connecting"
    link._watch_path(s, now)
    assert len(lines) == 2 and "has no working path" in lines[1]
    conn.path_now = "direct"
    link._watch_path(s, now)
    assert "is direct (same network) now" in lines[-1]


def test_a_failed_send_says_how_big_it_was():
    s = remote_session.Session(QualityConn(fail_send=True), PEER, PEER)
    s.send({"t": "st", "x": "y"})
    assert "bytes, the path takes 1150" in s.send_error


# --- the web remote -----------------------------------------------------------

class HelloConn(FakeConn):
    """A connection whose other side says one hello, then nothing."""

    def __init__(self, hello):
        super().__init__()
        self._hello = proto.encode(hello)

    async def read_datagram(self):
        if self._hello is not None:
            data, self._hello = self._hello, None
            return data
        await asyncio.Event().wait()


def web_hello(code):
    return {"t": "hello", "nick": "Sam", "v": 2, "ask": 1, "web": 1, "invite": code}


def test_a_browser_with_a_dead_web_link_is_told_so_never_asked_about(tmp_path):
    events = []
    link = make_link(tmp_path, events=events)              # no code works
    conn = HelloConn(web_hello("1" * 16))
    asyncio.run(link._ask_user(conn, PEER))
    assert conn.reason == remote_link.WEB_CLOSED.decode()
    assert not [e for e in events if e[0] == "request"]
    assert PEER not in link._pending


def test_a_browser_with_the_web_link_is_let_in(tmp_path):
    link = remote_link.RemoteLink(
        str(tmp_path / "friends_key.bin"), log=lambda _m: None, on_event=lambda *e: None,
        status_for=lambda _p: None, cmd_for=lambda _p: None,
        invite_ok=lambda _p, code, _n: code == "1" * 16)
    adopted = []
    link._adopt = lambda conn, peer, dialer, live: adopted.append((peer, live))
    asyncio.run(link._ask_user(HelloConn(web_hello("1" * 16)), PEER))
    assert adopted == [(PEER, True)]


def test_dropping_a_browser_says_why(tmp_path):
    link = make_link(tmp_path)
    s = remote_session.Session(FakeConn(), PEER, PEER)
    link._sessions[PEER] = s
    link._drop(PEER, remote_link.WEB_KICKED)
    assert s.conn.reason == "kicked" and s.reason == "kicked"
    link._drop("f" * 64, remote_link.WEB_KICKED)          # nobody there: nothing happens
