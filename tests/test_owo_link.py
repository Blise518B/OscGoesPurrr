"""owo_link speaks My OWO's UDP protocol, so its bytes are pinned here
against what OWO's own SDK (OWO.dll) sent in a capture
(tools/owo_udp_capture.py, 2026-10-23), and its handshake against a fake
app: "ping" -> "okay", AUTH -> "pong"."""

import socket

import owo_link as ol

# Captured from OWO.dll talking to a stand-in app on 127.0.0.1:54020.
CAPTURED = {
    "auth": b"0*AUTH*",
    "auth_id": b"12345*AUTH*",
    "arm_l": b"0*SENSATION*100,3,50,0,0,0,|5%100",
    "ramps": b"0*SENSATION*25,10,80,2000,2000,5,|0%60,9%100",
    "all": b"0*SENSATION*1,1,1,0,0,0,|0%100,1%100,2%100,3%100,4%100,5%100,6%100,7%100,8%100,9%100",
    "quarter": b"0*SENSATION*50,2,33,0,0,0,|6%0",
    "arm_l_id": b"12345*SENSATION*100,3,50,0,0,0,|5%100",
    "stop": b"0*STOP",
    "unavailable": b"0*GAMEUNAVAILABLE",
}


def test_auth_and_stop_match_the_sdk():
    assert ol.build_auth() == CAPTURED["auth"]
    assert ol.build_auth("12345") == CAPTURED["auth_id"]
    assert ol.build_auth("") == CAPTURED["auth"]
    assert ol.build_stop() == CAPTURED["stop"]
    assert ol.build_unavailable() == CAPTURED["unavailable"]


def test_sensations_match_the_sdk():
    assert ol.build_sensation("0", ol.sensation_text(100, 0.3, 50), {"Arm_L": 100}) == CAPTURED["arm_l"]
    assert ol.build_sensation(
        "0", ol.sensation_text(25, 1.0, 80, 2000, 2000, 0.5),
        {"Pectoral_R": 60, "Lumbar_L": 100}) == CAPTURED["ramps"]
    assert ol.build_sensation("0", ol.sensation_text(1, 0.1, 1),
                              {m: 100 for m in ol.MUSCLES}) == CAPTURED["all"]
    assert ol.build_sensation("0", ol.sensation_text(50, 0.25, 33), {"Dorsal_R": 0}) == CAPTURED["quarter"]
    assert ol.build_sensation("12345", ol.sensation_text(100, 0.3, 50), {5: 100}) == CAPTURED["arm_l_id"]


def test_sensation_values_clamp_like_the_sdk():
    assert ol.sensation_text(0, 0.0, 150, 9999, -5, 9) == "1,1,100,2000,0,20,"
    assert ol.sensation_text(250, 99, -3) == "100,200,0,0,0,0,"
    assert ol.sensation_text(float("nan"), "x", None) == "1,1,0,0,0,0,"
    assert ol.sensation_text(10, 0.3, 5, name="a,b|c") == "10,3,5,0,0,0,abc"


def test_muscle_groups_drop_unknowns():
    assert ol.muscles_text({"Arm_R": 50, "Tail": 100, 12: 3, "Lumbar_R": 300}) == "4%50,8%100"
    assert ol.build_sensation("0", "1,1,1,0,0,0,", {}) == b"0*SENSATION*1,1,1,0,0,0,"


class FakeApp:
    """A fake My OWO at `ip`: answers ping with okay, AUTH with pong."""

    def __init__(self, ip="127.0.0.1", answers_auth=True):
        self.ip = ip
        self.answers_auth = answers_auth


class FakeSocket:
    def __init__(self, app=None, local_ip="192.168.1.20"):
        self.app = app
        self.local_ip = local_ip
        self.sent = []
        self.queue = []
        self.closed = False

    def sendto(self, data, addr):
        self.sent.append((data, addr))
        app = self.app
        if app is None:
            return
        host, port = addr
        assert port == ol.PORT
        reached = host == app.ip or host == ol.BROADCAST
        if not reached:
            return
        if data == ol.PING:
            self.queue.append((ol.PRESENCE, (app.ip, ol.PORT)))
        elif b"*AUTH*" in data and app.answers_auth:
            self.queue.append((ol.VERIFIED, (app.ip, ol.PORT)))

    def settimeout(self, t):
        pass

    def recvfrom(self, n):
        if self.queue:
            return self.queue.pop(0)
        raise socket.timeout()

    def close(self):
        self.closed = True


def test_connect_handshake_on_this_pc():
    sock = FakeSocket(FakeApp("127.0.0.1"))
    link = ol.OwoLink(socket_factory=lambda: sock)
    assert link.connect([ol.LOCALHOST, ol.BROADCAST], "0", 0.01) == "127.0.0.1"
    assert sock.sent == [(b"ping", ("127.0.0.1", ol.PORT)), (b"0*AUTH*", ("127.0.0.1", ol.PORT))]
    assert link.send(ol.build_stop()) is True
    assert sock.sent[-1] == (b"0*STOP", ("127.0.0.1", ol.PORT))


def test_connect_falls_back_to_the_broadcast():
    sock = FakeSocket(FakeApp("192.168.1.50"))
    link = ol.OwoLink(socket_factory=lambda: sock)
    assert link.connect([ol.LOCALHOST, ol.BROADCAST], "7", 0.01) == "192.168.1.50"
    assert [d for d, _a in sock.sent] == [b"ping", b"ping", b"7*AUTH*"]
    assert sock.sent[1][1] == (ol.BROADCAST, ol.PORT)
    assert sock.sent[2][1] == ("192.168.1.50", ol.PORT)     # AUTH goes to whoever answered


def test_no_pong_means_not_connected():
    sock = FakeSocket(FakeApp("127.0.0.1", answers_auth=False))
    link = ol.OwoLink(socket_factory=lambda: sock)
    assert link.connect([ol.LOCALHOST], "0", 0.01) is None
    assert link.send(b"x") is False


def test_nobody_home():
    sock = FakeSocket(None)
    link = ol.OwoLink(socket_factory=lambda: sock)
    assert link.connect([ol.LOCALHOST, ol.BROADCAST], "0", 0.01) is None
    link.close()
    assert sock.closed


def test_poll_hears_the_app_leave():
    sock = FakeSocket(FakeApp())
    link = ol.OwoLink(socket_factory=lambda: sock)
    link.connect([ol.LOCALHOST], "0", 0.01)
    assert link.poll() is None
    sock.queue.append((ol.APP_CLOSED, ("127.0.0.1", ol.PORT)))
    assert link.poll() == b"OWO_Close"
