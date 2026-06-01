# OscGoesPurrr Test Bench

A standalone tool that drives a known input signal into a **live** VRChat-OSC
haptics app — OscGoesPurrr **or any other on the market** (OSC Goes Brrr, …) —
and reads the resulting toy output, on one clock, so you can plot input vs
output on a shared timeline, **benchmark end-to-end latency** ("program delay"),
and compare apps head to head.

It absorbs the two former standalone tools:

* **Input side** (was `sim/`) — impersonates VRChat: advertises over mDNS,
  answers OSCQuery, and sends avatar OSC parameters, so the target app routes
  real params with the game closed.
* **Output side** (was `toysim/`) — impersonates a Lovense toy on Intiface
  Central's Device Websocket Server, so a fully virtual toy shows up in
  Intiface and the target app drives it through its normal Buttplug path.

```
 [Test Bench] --OSC--> [target app under test] --Buttplug--> [Intiface] --Lovense--> [Test Bench]
   (input, t_in)                                                                     (output, t_out)
                          latency = t_out - t_in   (one perf_counter clock, no clock skew)
```

## Run

```
testbench\run_testbench.bat            # or:  python -m testbench
```

Build a standalone exe (`OGP_TestBench.exe` in `testbench\dist\`):

```
testbench\build_testbench.bat
```

Dependencies (installed by the scripts): PySide6, python-osc, zeroconf,
websocket-client, pyqtgraph, numpy.

## Targets (universal)

The simulator drives **any** VRChat-OSC consumer, not just OscGoesPurrr. The
**Target app** dropdown in the Input panel lists every app discovered on the
network via mDNS/OSCQuery (the bench advertises like real VRChat and connects
to whatever answers) — pick one to drive it. For apps that don't advertise
OSCQuery and just listen on the fixed VRChat port, use the **Manual host:port**
field (default `127.0.0.1:9000`). The first app discovered is auto-selected, so
the single-app case needs no clicks.

## One-time setup (for the output side / benchmarking)

1. **Intiface** → Settings → enable **Device Websocket Server** (default port
   `54817`).
2. Register the bench's identifier in Intiface's user device config
   (`buttplug-user-device-config-v4.json`): under
   `user_configs → protocols → lovense → communication` add
   `{"websocket": {"name": "OGPSim"}}` — the name must match the **Identifier**
   field in the Output panel exactly — then restart the Intiface server.
3. Start your **target app** (OscGoesPurrr, OSC Goes Brrr, …) and connect it to
   Intiface. It appears in the bench's **Target app** dropdown (or set a manual
   host:port).
4. In the bench's **Output** panel pick a model and click **Connect toy** — it
   appears in Intiface and in the target app's device list.
5. In the **target app's routing**, route the input you'll drive (e.g. the
   chosen zone's *PenOthers*) onto that toy's motor.

The virtual toy's identity (its Lovense address/serial) is **saved per model**
under `%APPDATA%\OscGoesPurrr\testbench_state.json`, so it reconnects as the
**same** device every launch — you only route it once in OGB/OGP. (Picking a
different model yields its own, also-persistent, identity.)

## Modes

* **Input** — drive avatar params only (the old VRChat-sim use). No toy needed.
* **Output** — watch a virtual toy's level only (the old toy-sim use). No
  signal generator needed.
* **Benchmark** — both, with edge-paired latency stats + histogram + CSV.

## Benchmarking latency

1. Pick an **avatar preset** and a **drive channel** (which OSC param to move).
2. Connect the toy and pick the **watched motor**.
3. Set a low **frequency** (0.5–1 Hz) — a **square** wave gives clean edges.
4. Click **Run benchmark (N cycles)**. The bench injects N rising edges, pairs
   each with the toy's first output movement, and fills the stats:
   count / min / mean / median / p95 / max / jitter (σ) / misses.
5. **Export CSV** writes `<base>_samples.csv`, `<base>_latencies.csv`, and
   `<base>_summary.csv`.

## Caveats

* The bench measures the **live target app**. It must be running, connected to
  Intiface, the virtual toy connected & routed, and the chosen input mapped to
  that toy. The status bar shows the selected target + Intiface connection.
* Most routers **debounce** (emit only on change) and apply **curve /
  smoothing**, so the output waveform is *shaped*, not identical to the input.
  For clean transport latency, use a square/step and minimal smoothing in the
  target app. Latency is measured as the time from an input rising edge to the
  toy's **first** output movement (set by the *Output edge ≥* threshold).
* Reported latency is the full round trip: UDP → the app's OSCQuery/router tick
  → Intiface → websocket. That is the "program delay".
