"""Test host for the web remote's link: OGP's real Friends link
(src/remote_link.py) with a throwaway key, one pretend toy and its own
code standing in for the web remote's, so docs/remote.html can be tried
and timed without touching your OGP, its key or its friends.

    python tools/web_guest/test_host.py <work dir> [--seconds 600]

Prints the page link (served by the docs-site preview on :4173) and keeps
<work dir>/host.json up to date: who is linked, the link's own round trip,
and how long each cmd took from the browser to here (its ``ts`` against this
PC's clock -- the page and the host must run on the same PC for that).
"""

import argparse
import json
import os
import secrets
import statistics
import sys
import threading
import time
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

import remote_link  # noqa: E402
import remote_protocol as proto  # noqa: E402

NICK = "Test OGP"
TOY = "Test toy"
PAGE = "http://localhost:4173/remote.html"


class Host:
    def __init__(self, work: str):
        self.work = work
        # one code per work dir, like a "forever" invite: a restart keeps the link working
        code_path = os.path.join(work, "code.txt")
        try:
            with open(code_path, encoding="utf-8") as fh:
                self.code = fh.read().strip()
        except OSError:
            self.code = ""
        if not proto.valid_code(self.code):
            self.code = secrets.token_hex(8)
            with open(code_path, "w", encoding="utf-8") as fh:
                fh.write(self.code)
        self.lock = threading.Lock()
        self.level = 0.0
        self.last_cmd = 0.0
        self.lat = []              # ms, browser -> here, one per cmd
        self.cmds = 0
        self.events = []
        self.link = remote_link.RemoteLink(
            os.path.join(work, "host_key.bin"), log=self.log, on_event=self.on_event,
            status_for=self.status_for, cmd_for=lambda _p: None,
            invite_ok=lambda _p, code, _n: code == self.code, debug=self.log)

    def log(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        with self.lock:
            self.events.append(f"{stamp} {line}")
            del self.events[:-60]
        print(stamp, line, flush=True)

    def status_for(self, _peer):
        with self.lock:
            if self.level and time.monotonic() - self.last_cmd > proto.DRIVE_STALE_S:
                self.level = 0.0                  # their cmds stopped: let go
            level = self.level
        return proto.make_status([(TOY, 1)], {TOY: level}, strength=1.0, off=False,
                                 paused=False, allow_toys=True, allow_shock=False,
                                 shockers=[], armed=False, max_intensity=0, max_pulse_ms=0)

    def on_event(self, kind: str, peer: str, data) -> None:
        if kind == "message" and isinstance(data, dict):
            if data.get("t") == "cmd":
                levels, _ = proto.read_cmd(data)
                level = proto.drive_for(levels, TOY)
                ms = None
                try:
                    ms = time.time() * 1000 - float(data["ts"])
                except (KeyError, TypeError, ValueError):
                    pass
                with self.lock:
                    changed = abs(level - self.level) >= 0.005
                    self.level, self.last_cmd = level, time.monotonic()
                    self.cmds += 1
                    if ms is not None:
                        self.lat.append(ms)
                        del self.lat[:-2000]
                if changed:
                    self.log(f"level {level * 100:.0f} %" + (f" ({ms:.0f} ms)" if ms is not None else ""))
            elif data.get("t") == "lw":
                self.log(f"panel {'open' if data.get('on') else 'closed'}")
        else:
            self.log(f"event {kind} {peer[:8]} {data!r}"[:200])

    def summary(self) -> dict:
        with self.lock:
            lat = list(self.lat)
            out = {"id": self.link.my_id, "online": self.link.online, "level": self.level,
                   "cmds": self.cmds, "peers": self.link.peers(), "events": list(self.events)}
        if lat:
            s = sorted(lat)
            out["latency_ms"] = {"n": len(s), "median": round(statistics.median(s), 1),
                                 "p95": round(s[int(len(s) * 0.95) - 1 if len(s) > 1 else 0], 1),
                                 "max": round(s[-1], 1), "min": round(s[0], 1)}
        return out

    def run(self, seconds: float) -> None:
        self.link.start(NICK, contacts=[])
        t0 = time.monotonic()
        while not self.link.online and time.monotonic() - t0 < 30:
            time.sleep(0.1)
        if not self.link.online:
            self.log(f"never came online ({self.link.error or 'no relay'})")
        link = f"{PAGE}#{self.link.my_id}.{self.code}.{quote(NICK, safe='')}"
        self.log(f"LINK {link}")
        with open(os.path.join(self.work, "link.txt"), "w", encoding="utf-8") as fh:
            fh.write(link)
        try:
            while time.monotonic() - t0 < seconds:
                time.sleep(1.0)
                tmp = os.path.join(self.work, "host.json.tmp")
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self.summary(), fh, indent=1, default=str)
                os.replace(tmp, os.path.join(self.work, "host.json"))
        finally:
            self.link.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("work")
    ap.add_argument("--seconds", type=float, default=600.0)
    args = ap.parse_args()
    os.makedirs(args.work, exist_ok=True)
    Host(args.work).run(args.seconds)


if __name__ == "__main__":
    main()
