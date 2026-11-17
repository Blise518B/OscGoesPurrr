"""Read a session recording's contacts without the app -- for chasing a bug.

    python tools/contact_debug.py [session.jsonl | session id] [--csv out.csv]
                                  [--zone NAME] [--hz 20]

No argument: the newest session in %APPDATA%\\OscGoesPurrr\\sessions. Best with
a session recorded with Settings -> Sessions -> Record raw contacts: then it

1. lists what the avatar has -- each zone by VRChat's own name (SPS 3's
   OGB/Socket, OGB/Plug next to the older Orf / Pen), its constants
   (DepthRadius, LengthMult1/2), OGB/Enabled, OGB/HapticsDisabled, versions;
2. counts every contact's packets (how many, range, last value) -- a contact
   that never moves is as telling as one that does;
3. feeds the packets through OGP's own input path (parameter_store, with
   the recorded arrival times) and samples each zone at --hz: what the
   router reads -- touch level and VRChat's speed, depth self / others,
   the plug length a socket measured -- with every filter on;
4. sums the toys' recorded outputs (the `motor` lines), to set beside 3.

Without raw lines it falls back to the per-tick OGB stream for 1-3 (no
packet timing, and the plug lengths as the app derived them then).
--csv writes step 3's samples, one row per zone per sample.
"""

import argparse
import csv
import json
import math
import os
import sys
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

import sps3_zone  # noqa: E402
from parameter_store import ParameterStore  # noqa: E402
from utilities import classify_ogb_zone  # noqa: E402

_ALL_ON = {"motor_0_touch_self": True, "motor_0_touch_others": True,
           "motor_0_pen_self": True, "motor_0_pen_others": True}


def _sessions_dir():
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    return os.path.join(base, "OscGoesPurrr", "sessions")


def _resolve(arg):
    if arg and os.path.isfile(arg):
        return arg
    d = _sessions_dir()
    if arg:
        path = os.path.join(d, arg if arg.endswith(".jsonl") else arg + ".jsonl")
        if os.path.isfile(path):
            return path
        sys.exit(f"No session {arg!r} (looked in {d})")
    files = [os.path.join(d, f) for f in os.listdir(d)
             if f.startswith("session_") and f.endswith(".jsonl")] \
        if os.path.isdir(d) else []
    if not files:
        sys.exit(f"No sessions in {d}")
    return max(files, key=os.path.getmtime)


def _load(path):
    # Motor lines are totalled while reading -- the session logger writes
    # every motor every tick, millions of lines in a long session.
    header, raw, ogb = {}, [], []
    motor = defaultdict(lambda: {"n": 0, "live": 0, "out": 0.0, "d_raw": 0.0})
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            kind = ev.get("type")
            t = float(ev.get("t_ms", 0.0) or 0.0)
            if kind == "header":
                header = ev
            elif kind == "raw":
                raw.append((t, len(raw), "p", (ev.get("a"), ev.get("v"))))
            elif kind == "raw_snapshot":
                raw.append((t, len(raw), "s", ev))
            elif kind in ("ogb", "ogb_snapshot"):
                ogb.append((t, kind == "ogb_snapshot", ev.get("params") or {}))
            elif kind == "motor":
                m = motor[(ev.get("device"), ev.get("motor"))]
                out = float(ev.get("out", 0) or 0)
                m["n"] += 1
                m["live"] += out > 0.01
                m["out"] = max(m["out"], out)
                m["d_raw"] = max(m["d_raw"], float(ev.get("d_raw", 0) or 0))
    raw.sort(key=lambda r: (r[0], r[1]))
    ogb.sort(key=lambda r: r[0])
    return header, raw, ogb, motor


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.4f}"
    return repr(v)


def _zone_of(name):
    canon = sps3_zone.canon_zone_key(name)
    if canon.startswith("VFH/Zone/"):
        canon = "OGB/" + canon[len("VFH/Zone/"):]
    return classify_ogb_zone(canon)


def report_avatar(raw, ogb):
    print("== The avatar ==")
    snaps = [r[3] for r in raw if r[2] == "s"]
    if not snaps:
        if ogb:
            print("  (no raw snapshot -- recorded without Record raw contacts)")
        else:
            print("  (no contact parameters at all in this recording)")
        return
    for i, snap in enumerate(snaps):
        params = snap.get("params") or {}
        types = snap.get("types") or {}
        print(f"  load {i + 1} at {snap.get('t_ms', 0) / 1000:.1f}s "
              f"({snap.get('source')}): {len(params)} contact parameters")
        zones = defaultdict(list)
        other = []
        for name in sorted(params):
            z = _zone_of(name)
            (zones[(name.split('/')[1] if name.count('/') >= 2 else '?', z)]
             if z else other).append(name)
        for (wire, z), names in sorted(zones.items(), key=lambda kv: str(kv[0])):
            prefix_len = len("/".join(names[0].split("/")[:3])) + 1
            consts = [f"{n[prefix_len:]}={_fmt(params[n])}" for n in names
                      if n.endswith(("DepthRadius", "LengthMult1", "LengthMult2"))]
            print(f"    {wire:>7} {z[1]:<20} -> {z[0]}  "
                  f"{len(names)} params"
                  + (f"  [{', '.join(consts)}]" if consts else "")
                  + ("  SPS 3" if wire in ("Socket", "Plug") else ""))
        for name in other:
            print(f"    {name} = {_fmt(params[name])} ({types.get(name, '?')})")


def report_packets(raw):
    packets = [r[3] for r in raw if r[2] == "p"]
    print(f"\n== Packets: {len(packets)} ==")
    if not packets:
        return
    span = (raw[-1][0] - raw[0][0]) / 1000.0 or 1.0
    stats = {}
    for name, v in packets:
        s = stats.setdefault(name, {"n": 0, "min": None, "max": None, "last": None})
        s["n"] += 1
        s["last"] = v
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            s["min"] = v if s["min"] is None else min(s["min"], v)
            s["max"] = v if s["max"] is None else max(s["max"], v)
        elif isinstance(v, bool):
            s["max"] = v if s["max"] is None else (s["max"] or v)
    print(f"  over {span:.1f}s; per parameter: count, min..max, last")
    for name in sorted(stats):
        s = stats[name]
        rng = (f"{_fmt(s['min'])}..{_fmt(s['max'])}" if s["min"] is not None
               else f"max {s['max']!r}")
        print(f"  {s['n']:>7}  {rng:<22} last {_fmt(s['last']):<10} {name}")


def _replay(raw, ogb):
    """Yield (t_ms, store) after each step, through OGP's own input path."""
    store = ParameterStore()
    if raw:
        for t, _seq, kind, payload in raw:
            if kind == "s":
                store.replay_snapshot(payload.get("params") or {})
            else:
                store.replay_packets([payload], now=t / 1000.0)
            yield t, store
    else:
        state = {}
        for t, full, params in ogb:
            state = dict(params) if full else {**state, **params}
            store.apply_replay_frame(state)
            yield t, store


def report_zones(raw, ogb, hz, only_zone, csv_path):
    from motor_router import MotorRouter
    router = MotorRouter()
    step = 1000.0 / hz
    rows = []
    peaks = defaultdict(lambda: defaultdict(float))
    next_t = None
    for t, store in _replay(raw, ogb):
        if next_t is None:
            next_t = t
        if t < next_t:
            continue
        next_t = t + step
        params, _v, zones = store.snapshot()
        for ztype, zname in sorted(zones):
            if only_zone and zname != only_zone:
                continue
            prefix = f"OGB/{ztype}/{zname}"
            level, speed = router._zone_level_and_speed(
                ztype, zname, _ALL_ON, 0, params)
            sps3 = ztype in ("Orf", "Pen") and sps3_zone.is_sps3_zone(params, prefix)
            row = {"t_s": round(t / 1000.0, 3), "zone": f"{ztype}/{zname}",
                   "sps3": sps3, "level": round(level, 4),
                   "speed": round(speed, 4)}
            if sps3:
                for c in ("DepthSelf", "DepthOthers"):
                    row[f"{c}_prox"] = params.get(f"{prefix}/{c}")
                    row[f"{c}_sep"] = params.get(f"{prefix}/{c}_PointSeparation")
                    row[f"{c}_len"] = params.get(f"{prefix}/{c}{sps3_zone.LENGTH_SUFFIX}")
                    row[f"{c}_depth"] = round(sps3_zone.depth(params, prefix, ztype, c), 4)
                for c in ("TouchSelf", "TouchOthers", "FrotOthers"):
                    row[c] = params.get(f"{prefix}/{c}")
            rows.append(row)
            pk = peaks[row["zone"]]
            for k, v in row.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) \
                        and k != "t_s" and math.isfinite(v):
                    pk[k] = max(pk[k], v)
    print(f"\n== What the router reads, per zone (every filter on, {hz} Hz) ==")
    if not rows:
        print("  no zone ever showed up")
    for zone, pk in sorted(peaks.items()):
        active = sum(1 for r in rows if r["zone"] == zone and r["level"] > 0.01)
        n = sum(1 for r in rows if r["zone"] == zone)
        print(f"  {zone}: peak level {pk['level']:.3f}, peak speed "
              f"{pk['speed']:.3f}, >1% in {active}/{n} samples")
        extra = [f"{k} {v:.3f}" for k, v in sorted(pk.items())
                 if k not in ("level", "speed")]
        if extra:
            print("      peaks: " + ", ".join(extra))
    if csv_path and rows:
        keys = []
        for r in rows:
            keys.extend(k for k in r if k not in keys)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"  samples written to {csv_path}")


def report_motors(motor):
    lines = sum(m["n"] for m in motor.values())
    print(f"\n== Toys' recorded output ({lines} motor lines) ==")
    if not motor:
        print("  none (no toy, or nothing routed)")
        return
    for (dev, idx), m in sorted(motor.items(), key=lambda kv: str(kv[0])):
        print(f"  {dev} motor {idx}: peak out {m['out']:.3f}, peak input "
              f"{m['d_raw']:.3f}, out >1% in {m['live']}/{m['n']} ticks")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("session", nargs="?")
    ap.add_argument("--csv")
    ap.add_argument("--zone")
    ap.add_argument("--hz", type=float, default=20.0)
    args = ap.parse_args(argv)
    path = _resolve(args.session)
    header, raw, ogb, motor = _load(path)
    print(f"{os.path.basename(path)}  app {header.get('app_version', '?')}"
          f"  raw contacts {'yes' if raw else 'no'}  profile "
          f"{header.get('profile', '?')!r}  toys "
          f"{[t.get('name') for t in header.get('toys') or []]}")
    report_avatar(raw, ogb)
    report_packets(raw)
    report_zones(raw, ogb, max(1.0, args.hz), args.zone, args.csv)
    report_motors(motor)


if __name__ == "__main__":
    main()
