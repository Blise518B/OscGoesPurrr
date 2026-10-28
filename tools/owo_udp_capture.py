"""Record exactly what OWO's official SDK sends to the My OWO app.

src/owo_link.py speaks My OWO's UDP protocol natively, so its messages are
pinned against real SDK output -- captured here, never guessed. Two halves:

    python tools/owo_udp_capture.py listen [--seconds 30] [--reply-okay]
        Stands in for My OWO on UDP 54020: logs every datagram verbatim
        (and, with --reply-okay, answers like the app: "okay" to the SDK's
        "ping", "pong" to its AUTH -- after which the SDK counts as
        connected, per OWO's own MIT-licensed C++ SDK in OWODevelopers/
        OWO_GTAV). My OWO must be closed -- it owns that port.

    <a venv with pythonnet>\\Scripts\\python.exe tools/owo_udp_capture.py drive --dll <OWO.dll>
        Loads OWO.dll through pythonnet and runs a fixed script of SDK calls
        against 127.0.0.1: connect, a handful of sensations, stop,
        disconnect, then AutoConnect's broadcast. Nothing reaches a suit:
        the only thing listening is `listen` above.

The log is plain text under %LOCALAPPDATA%\\OscGoesPurrr\\owo_udp_capture\\.
Works on Python 3.10 (the vrc-owo-suit venv) and 3.13 (OGP's).
"""

import argparse
import os
import socket
import sys
import time
from pathlib import Path

PORT = 54020
OUT_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OscGoesPurrr" / "owo_udp_capture"


def cmd_listen(seconds, reply_okay):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / f"listen_{time.strftime('%Y%m%d_%H%M%S')}.log"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", PORT))
    sock.settimeout(0.2)
    t0 = time.monotonic()
    print(f"Listening on UDP {PORT} for {seconds:.0f} s -> {log_path}", flush=True)
    with open(log_path, "w", encoding="utf-8") as log:
        while time.monotonic() - t0 < seconds:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as e:  # Windows: ICMP port-unreachable surfaces here
                log.write(f"{time.monotonic() - t0:8.3f} recv error {e}\n")
                continue
            line = f"{time.monotonic() - t0:8.3f} {addr[0]}:{addr[1]} {data!r}"
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
            reply = None
            if reply_okay and data == b"ping":
                reply = b"okay"
            elif reply_okay and b"*AUTH*" in data:
                reply = b"pong"
            if reply is not None:
                sock.sendto(reply, addr)
                note = f"{time.monotonic() - t0:8.3f} -> {addr[0]}:{addr[1]} {reply!r}"
                print(note, flush=True)
                log.write(note + "\n")
    return 0


def cmd_drive(dll):
    from pythonnet import load
    load("netfx")
    import clr  # noqa: F401
    from System import Array
    from System.Reflection import Assembly
    Assembly.UnsafeLoadFrom(dll)
    from OWOGame import (OWO, ConnectionState, GameAuth, Muscle, MusclesExtensions,
                         SensationExtensions, SensationsFactory)

    def step(label):
        print(f"[{time.strftime('%H:%M:%S')}] {label}", flush=True)

    def wait_connected(timeout):
        end = time.time() + timeout
        while time.time() < end:
            if OWO.ConnectionState == ConnectionState.Connected:
                return True
            time.sleep(0.05)
        return False

    step("Configure(GameAuth.Empty)")
    OWO.Configure(GameAuth.Empty)
    step("Connect(['127.0.0.1'])")
    OWO.Connect(Array[str](["127.0.0.1"]))
    ok = wait_connected(6.0)
    step(f"connected: {ok} ({OWO.ConnectionState})")
    time.sleep(0.5)

    cases = [
        ("A f100 d0.3 i50 Arm_L", SensationsFactory.Create(100, 0.3, 50, 0, 0, 0),
         [Muscle.Arm_L]),
        ("B f25 d1.0 i80 up200 down300 exit0.5 Pectoral_R@60 Lumbar_L@100",
         SensationsFactory.Create(25, 1.0, 80, 200, 300, 0.5),
         [Muscle.Pectoral_R.WithIntensity(60), Muscle.Lumbar_L.WithIntensity(100)]),
        ("C f1 d0.1 i1 all muscles", SensationsFactory.Create(1, 0.1, 1, 0, 0, 0),
         list(Muscle.All)),
        ("D f50 d0.25 i33 Dorsal_R@0", SensationsFactory.Create(50, 0.25, 33, 0, 0, 0),
         [Muscle.Dorsal_R.WithIntensity(0)]),
    ]
    for label, sensation, muscles in cases:
        step(f"Send {label}")
        OWO.Send(sensation, Array[Muscle](muscles))
        time.sleep(0.6)

    seq = SensationExtensions.Append(SensationsFactory.Create(100, 0.4, 20, 0, 0, 0.3),
                                     SensationsFactory.Create(10, 0.4, 40, 0, 0, 0))
    step("Send E sequence (f100 d0.4 i20 exit0.3) + (f10 d0.4 i40) Abdominal_L")
    OWO.Send(seq, Array[Muscle]([Muscle.Abdominal_L]))
    time.sleep(0.6)

    step("Send F WithPriority(3) f100 d0.3 i10 Arm_R")
    OWO.Send(SensationExtensions.WithPriority(SensationsFactory.Create(100, 0.3, 10, 0, 0, 0), 3),
             Array[Muscle]([Muscle.Arm_R]))
    time.sleep(0.6)

    step("Stop()")
    OWO.Stop()
    time.sleep(0.6)
    step("Disconnect()")
    OWO.Disconnect()
    time.sleep(1.0)

    step("Configure(GameAuth.Empty.WithId('12345'))")
    OWO.Configure(GameAuth.Empty.WithId("12345"))
    step("Connect(['127.0.0.1']) with a game id")
    OWO.Connect(Array[str](["127.0.0.1"]))
    step(f"connected: {wait_connected(6.0)}")
    OWO.Send(SensationsFactory.Create(100, 0.3, 50, 0, 0, 0), Array[Muscle]([Muscle.Arm_L]))
    time.sleep(0.6)
    OWO.Disconnect()
    time.sleep(1.0)

    step("AutoConnect() (broadcast discovery)")
    OWO.Configure(GameAuth.Empty)
    OWO.AutoConnect()
    step(f"connected: {wait_connected(6.0)}")
    time.sleep(1.0)
    OWO.Disconnect()
    step("done")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("listen")
    p.add_argument("--seconds", type=float, default=30.0)
    p.add_argument("--reply-okay", action="store_true")
    p = sub.add_parser("drive")
    p.add_argument("--dll", required=True,
                   help="OWO's SDK assembly, e.g. the owo\\OWO.dll vrc-owo-suit ships")
    args = ap.parse_args()
    if args.cmd == "listen":
        return cmd_listen(args.seconds, args.reply_okay)
    return cmd_drive(args.dll)


if __name__ == "__main__":
    sys.exit(main())
