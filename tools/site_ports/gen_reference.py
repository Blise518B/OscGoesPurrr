"""Record what the real signal chain does, as the reference the website's
JavaScript port (docs/assets/ogp-chain.js) is checked against.

Drives the real `MotorRouter` with a fake clock through a set of scenarios
(strokes, idle, a held contact, touch, Sleep, Off, strength, live config
edits, uneven tick lengths) and writes every input, every per-stage trace
and the final output per tick to `reference.json`. Also records the
simulator's waves and the fold-bar / stage-card summary strings, the
latter produced by the app's own UI code.

    venv\\Scripts\\python.exe tools\\site_ports\\gen_reference.py
    venv\\Scripts\\python.exe tools\\site_ports\\gen_reference.py --quick --out D:\\tmp\\ports

By default it then runs `node tools/site_ports/check.js` on the result.

The reference is large (43 MB for the full set) and is never written into
the repo: it goes to --out, by default a folder in the system temp dir.

Importing the app's settings package creates its AppData folder as a side
effect, so the home directory is pointed at a scratch folder inside --out
BEFORE any app module is imported. Nothing here reads or writes the real
profile.
"""
import sys
sys.dont_write_bytecode = True   # no __pycache__ in src/ or tools/

import argparse                   # noqa: E402
import ast                        # noqa: E402
import copy                       # noqa: E402
import json                       # noqa: E402
import os                         # noqa: E402
import subprocess                 # noqa: E402
import tempfile                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_OUT = os.path.join(tempfile.gettempdir(), "ogp-site-ports")
REFERENCE_NAME = "reference.json"

DT = 1.0 / 90.0
DEV = "Toy"

TRACE_KEYS = (
    "d_raw", "s_raw", "d_shaped", "s_shaped", "punch",
    "s_in_shaped", "s_out_shaped", "punch_in", "punch_out",
    "mixed", "wake_open", "wake_meter", "wake_out",
    "smoothed", "textured", "out", "duck",
)

# Filled in by load_app() once the home directory has been redirected.
MotorRouter = None
ModeManager = None
preset_motor_mix = None
sample_pattern = None
WAVEFORMS = None
SIM_PEN_ADDRESS = None
SIM_TOUCH_ADDRESS = None
SIM_ADDRESSES = None
APP_ANTISTUCK = None
DEFAULT_APP_SETTINGS = None


def is_inside(path, parent):
    path = os.path.normcase(os.path.realpath(path))
    parent = os.path.normcase(os.path.realpath(parent))
    return path == parent or path.startswith(parent + os.sep)


def redirect_home(out_dir):
    """Point every "where is the user's profile" variable at a scratch
    folder, so the app's import-time `makedirs(AppData/...)` lands there."""
    home = os.path.join(out_dir, "_fakehome")
    os.makedirs(home, exist_ok=True)
    os.environ["USERPROFILE"] = home
    os.environ["HOME"] = home
    os.environ["APPDATA"] = os.path.join(home, "AppData", "Roaming")
    os.environ["LOCALAPPDATA"] = os.path.join(home, "AppData", "Local")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(home, ".config")   # Linux
    # constants.py would otherwise read a colour the developer picked.
    os.environ["OGP_UI_ACCENT"] = "default"
    return home


def load_app():
    """Import the app modules (after redirect_home) into module globals."""
    global MotorRouter, ModeManager, preset_motor_mix, sample_pattern
    global WAVEFORMS, SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS, SIM_ADDRESSES
    global APP_ANTISTUCK, DEFAULT_APP_SETTINGS
    src = os.path.join(REPO, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    import motor_router
    import config_manager
    import constants
    import mixer
    import settings
    MotorRouter = motor_router.MotorRouter
    ModeManager = config_manager.ModeManager
    preset_motor_mix = config_manager.preset_motor_mix
    sample_pattern = mixer.sample_pattern
    WAVEFORMS = mixer.WAVEFORMS
    SIM_PEN_ADDRESS = constants.SIM_PEN_ADDRESS
    SIM_TOUCH_ADDRESS = constants.SIM_TOUCH_ADDRESS
    SIM_ADDRESSES = constants.SIM_ADDRESSES
    DEFAULT_APP_SETTINGS = settings.DEFAULT_APP_SETTINGS
    APP_ANTISTUCK = {
        "enabled": bool(DEFAULT_APP_SETTINGS.get("toy_antistuck_enabled", True)),
        "active_s": int(DEFAULT_APP_SETTINGS.get("toy_antistuck_active_s", 1)),
        "peaked_s": int(DEFAULT_APP_SETTINGS.get("toy_antistuck_peaked_s", 10)),
    }


class FakeClock:
    """Same as tests/conftest.py FakeClock."""

    def __init__(self, start=0.0):
        self._t = float(start)

    def now(self):
        return self._t

    def advance(self, seconds):
        self._t += float(seconds)


# ---------------------------------------------------------------- configs

def cfg_default():
    return preset_motor_mix()


def cfg_mod_a():
    """Different gains, curves, combine=max, speed-sourced wake, long fall,
    zero cut OFF, texture on, output band, add merge, ducking touch."""
    mix = preset_motor_mix()
    pen, touch = mix["chains"]
    pen["depth"].update(gain=0.8, curve="power", curve_param=1.6)
    pen["speed"].update(gain=1.2, gain_out=0.5, curve="s_curve",
                        curve_param=2.0, decay_ms=150.0)
    pen["punch"].update(gain=0.9, gain_out=0.7, decay_ms=60.0)
    pen["combine"] = "max"
    pen["wake"].update(enabled=True, mode="activity", source="speed",
                       wake_threshold=0.2, sleep_delay_s=0.3,
                       attack_s=0.2, release_s=0.3)
    pen["smoothing"].update(rise_ms=30.0, fall_ms=400.0)
    pen["zerocut"].update(enabled=False)
    pen["texture"].update(enabled=True, amount=0.4, rate_hz=3.0,
                          follow_speed=True, depth_follow="down")
    pen["output"].update(gain=1.4, min=0.2, max=0.8)
    touch["depth"].update(gain=1.1, curve="s_curve", curve_param=1.0)
    touch["speed"].update(gain=0.6, decay_ms=90.0)
    touch["combine"] = "multiply"
    touch["duck"].update(enabled=True, release_ms=250.0)
    touch["zerocut"].update(enabled=False)
    touch["output"].update(gain=0.9, min=0.1, max=0.9)
    mix["merge"] = "add"
    return mix


def cfg_mod_b():
    """combine=multiply, strokes-mode wake, zero cut with a threshold, no
    smoothing, texture depth_follow up, multiply merge, depth-sourced wake
    on touch."""
    mix = preset_motor_mix()
    pen, touch = mix["chains"]
    pen["depth"].update(gain=1.7, curve="power", curve_param=0.5)
    pen["speed"].update(gain=2.0, gain_out=1.3, curve="power",
                        curve_param=2.2, decay_ms=600.0)
    pen["punch"].update(gain=2.0, gain_out=0.0, decay_ms=400.0)
    pen["combine"] = "multiply"
    pen["wake"].update(enabled=True, mode="strokes", thrusts=2,
                       window_s=4.0, disarm_after_s=5.0)
    pen["smoothing"].update(rise_ms=0.0, fall_ms=0.0)
    pen["zerocut"].update(enabled=True, threshold=0.1)
    pen["texture"].update(enabled=True, amount=0.9, rate_hz=8.0,
                          follow_speed=False, depth_follow="up")
    pen["output"].update(gain=0.6, min=0.0, max=1.0)
    touch["depth"].update(gain=0.9)
    touch["speed"].update(gain=1.0, gain_out=0.0, decay_ms=300.0)
    touch["combine"] = "max"
    touch["wake"].update(enabled=True, mode="activity", source="depth",
                         wake_threshold=0.3, sleep_delay_s=1.0,
                         attack_s=0.5, release_s=1.5)
    touch["smoothing"].update(rise_ms=300.0, fall_ms=0.0)
    touch["texture"].update(enabled=True, amount=0.25, rate_hz=2.0,
                            follow_speed=True, depth_follow="off")
    touch["zerocut"].update(enabled=True, threshold=0.0)
    touch["output"].update(gain=2.0, min=0.3, max=1.0)
    mix["merge"] = "multiply"
    return mix


def cfg_single_custom():
    """The router's own one-chain DEFAULT_MIX_CONFIG (a `custom` chain with
    no type key): hears pen AND touch, max-wins."""
    return copy.deepcopy(MotorRouter.DEFAULT_MIX_CONFIG)


CONFIGS = {
    "default": cfg_default,
    "modA": cfg_mod_a,
    "modB": cfg_mod_b,
    "singleCustom": cfg_single_custom,
}


# -------------------------------------------------------------- scenarios
# A scenario = duration, input functions of time, and a list of events
# (tick index -> change to strength / off / sleep / a config field).
# Inputs are produced HERE and stored in the JSON, so check.js replays
# exactly these numbers.

def sine(hz, amp=1.0):
    return lambda t: sample_pattern(hz, amp, "sine", t)


def zero(_t):
    return 0.0


def strokes_between(t0, t1, hz, amp=1.0, wave="sine"):
    def f(t):
        if t0 <= t < t1:
            return sample_pattern(hz, amp, wave, t - t0)
        return 0.0
    return f


def piecewise(*parts):
    """parts: (t_end, fn) ... evaluated in order."""
    def f(t):
        for t_end, fn in parts:
            if t < t_end:
                return fn(t)
        return parts[-1][1](t)
    return f


def held_profile(t):
    # ramp to 0.6 in 0.5 s, hold to 15 s, ramp to 1.0 by 16 s, hold to 32 s,
    # drop to 0.3 until 34 s, then release.
    if t < 0.5:
        return 0.6 * (t / 0.5)
    if t < 15.0:
        return 0.6
    if t < 16.0:
        return 0.6 + 0.4 * (t - 15.0)
    if t < 32.0:
        return 1.0
    if t < 34.0:
        return 0.3
    return 0.0


def held_profile_quick(t):
    # the same shape squeezed into 7.5 s (run with peaked_s = 2): 0.6 held
    # past the 1 s fuse, then 1.0 held through its fuse and the 3 s ramp.
    if t < 0.3:
        return 0.6 * (t / 0.3)
    if t < 2.0:
        return 0.6
    if t < 7.2:
        return 1.0
    return 0.0


def sleep_pen(t):
    # 2 strokes (not enough), a 7 s pause (window expires), 5 strokes
    # (arms on the 3rd), ~50 s quiet (disarms after 45 s), then 4 strokes.
    if 1.0 <= t < 3.0:
        return sample_pattern(1.0, 0.9, "sine", t - 1.0)
    if 10.0 <= t < 15.0:
        return sample_pattern(1.0, 1.0, "sine", t - 10.0)
    if 66.0 <= t < 70.0:
        return sample_pattern(1.0, 0.8, "triangle", t - 66.0)
    return 0.0


def live_edit_events(spacing_s, start_s):
    """Twenty config edits, one every `spacing_s` — what dragging sliders
    in the demo does. Paths are into the motor's mix block."""
    edits = [
        (("chains", 0, "punch", "gain"), 0.0),
        (("chains", 0, "punch", "gain"), 1.32),
        (("chains", 0, "punch", "gain_out"), 1.0),
        (("chains", 0, "wake", "enabled"), False),
        (("chains", 0, "wake", "enabled"), True),
        (("chains", 0, "wake", "wake_threshold"), 0.6),
        (("chains", 0, "wake", "mode"), "strokes"),
        (("chains", 0, "wake", "mode"), "activity"),
        (("chains", 0, "wake", "wake_threshold"), 0.05),
        (("chains", 0, "texture", "enabled"), True),
        (("chains", 0, "combine"), "max"),
        (("chains", 0, "smoothing", "rise_ms"), 300.0),
        (("chains", 0, "smoothing", "fall_ms"), 300.0),
        (("chains", 0, "zerocut", "enabled"), False),
        (("chains", 0, "output", "gain"), 1.6),
        (("merge",), "add"),
        (("chains", 1, "duck", "enabled"), True),
        (("chains", 0, "depth", "gain"), 1.0),
        (("chains", 0, "speed", "gain_out"), 0.1),
        (("merge",), "multiply"),
    ]
    return [(int((start_s + i * spacing_s) * 90), "cfg", edit)
            for i, edit in enumerate(edits)]


def full_scenarios():
    return [
        dict(name="sine_1hz_20s", dur=20.0, pen=sine(1.0), touch=zero),
        dict(name="idle_strokes_idle", dur=14.0,
             pen=strokes_between(3.0, 6.0, 1.5, 0.85), touch=zero),
        dict(name="fast_3hz", dur=10.0, pen=sine(3.0), touch=zero),
        dict(name="held_frozen_antistuck_on", dur=37.0, pen=held_profile,
             touch=lambda t: 0.45 if 2.0 <= t < 9.0 else 0.0),
        dict(name="held_frozen_antistuck_off", dur=37.0, pen=held_profile,
             touch=lambda t: 0.45 if 2.0 <= t < 9.0 else 0.0,
             antistuck=None),
        dict(name="touch_only", dur=12.0, pen=zero,
             touch=lambda t: sample_pattern(0.7, 0.8, "triangle", t)),
        dict(name="pen_plus_touch", dur=15.0,
             pen=strokes_between(2.0, 11.0, 1.2, 1.0),
             touch=lambda t: sample_pattern(0.8, 0.9, "random", t)),
        dict(name="sleep_strokes", dur=72.0, pen=sleep_pen,
             touch=lambda t: 0.5 if 20.0 <= t < 20.5 else 0.0,
             sleep=True),
        dict(name="sleep_toggled_midrun", dur=16.0, pen=sine(1.0), touch=zero,
             events=[(int(4.0 * 90), "sleep", True),
                     (int(11.0 * 90), "sleep", False)]),
        dict(name="strength_050", dur=8.0, pen=sine(1.0),
             touch=lambda t: sample_pattern(0.4, 0.6, "sine", t),
             strength=0.5),
        dict(name="strength_moves", dur=10.0, pen=sine(1.0), touch=zero,
             strength=ModeManager.DEFAULT_STRENGTH,
             events=[(int(3.0 * 90), "strength", 0.2),
                     (int(5.0 * 90), "strength", 1.0),
                     (int(7.0 * 90), "strength", 0.005)]),
        dict(name="off", dur=6.0, pen=sine(1.0), touch=sine(0.5), off=True),
        dict(name="off_toggled_midrun", dur=9.0, pen=sine(1.0), touch=zero,
             events=[(int(3.0 * 90), "off", True),
                     (int(6.0 * 90), "off", False)]),
        dict(name="square_saw_random", dur=18.0,
             pen=piecewise(
                 (6.0, lambda t: sample_pattern(1.0, 1.0, "square", t)),
                 (12.0, lambda t: sample_pattern(0.8, 0.7, "sawtooth", t)),
                 (18.0, lambda t: sample_pattern(1.3, 1.0, "random", t))),
             touch=lambda t: sample_pattern(2.0, 0.5, "square", t)),
        # Variable tick length: 60 Hz, 144 Hz, hiccups and one 7 s stall
        # (longer than the stroke-counting window) — proves the time
        # constants are wall-clock, not per-tick.
        dict(name="jittery_dt", dur=20.0, pen=sine(1.1),
             touch=lambda t: sample_pattern(0.5, 0.7, "triangle", t),
             dt_fn=lambda i: (1.0 / 60.0 if i % 7 < 3 else 1.0 / 144.0)
             + (0.25 if i % 211 == 210 else 0.0)
             + (7.0 if i == 600 else 0.0)),
        dict(name="jittery_dt_sleep", dur=30.0, pen=sine(0.9), touch=zero,
             sleep=True,
             dt_fn=lambda i: (1.0 / 60.0 if i % 5 < 2 else 1.0 / 120.0)
             + (6.5 if i == 500 else 0.0) + (50.0 if i == 1500 else 0.0)),
        dict(name="live_edits", dur=16.0, pen=sine(1.0),
             touch=lambda t: sample_pattern(0.6, 0.8, "sine", t),
             only=("default",), events=live_edit_events(0.65, 2.0)),
    ]


def quick_scenarios():
    """A few seconds each: what tests/test_site_ports.py runs. Every stage
    and every toggle is exercised at least once; the long soak (45 s
    disarm, 20 s strokes, the 10 s saturated fuse) is left to the full
    set."""
    return [
        dict(name="q_sine", dur=4.0, pen=sine(1.0), touch=zero,
             strength=ModeManager.DEFAULT_STRENGTH,
             only=("default", "modA", "modB", "singleCustom")),
        dict(name="q_touch", dur=3.0, pen=zero,
             touch=lambda t: sample_pattern(0.7, 0.8, "triangle", t),
             only=("default", "modA")),
        dict(name="q_pen_plus_touch", dur=4.0,
             pen=strokes_between(0.5, 3.0, 1.2, 1.0),
             touch=lambda t: sample_pattern(0.8, 0.9, "random", t),
             only=("default", "modA", "modB")),
        dict(name="q_sleep", dur=6.0,
             pen=strokes_between(0.3, 6.0, 1.5, 0.9),
             touch=lambda t: 0.5 if 1.0 <= t < 1.5 else 0.0,
             sleep=True, events=[(int(5.0 * 90), "sleep", False)],
             only=("default", "modA")),
        dict(name="q_off", dur=3.0, pen=sine(1.0), touch=sine(0.5),
             off=True, events=[(int(1.5 * 90), "off", False)],
             only=("default", "modA")),
        dict(name="q_strength", dur=3.0, pen=sine(1.0),
             touch=lambda t: sample_pattern(0.4, 0.6, "sine", t),
             strength=0.5,
             events=[(int(1.0 * 90), "strength", 0.2),
                     (int(2.0 * 90), "strength", 1.0)],
             only=("default", "modA")),
        dict(name="q_antistuck", dur=7.5, pen=held_profile_quick,
             touch=lambda t: 0.45 if 0.5 <= t < 3.0 else 0.0,
             antistuck={"enabled": True, "active_s": 1, "peaked_s": 2},
             only=("default", "modA")),
        dict(name="q_antistuck_off", dur=3.0, pen=held_profile_quick,
             touch=lambda t: 0.45 if 0.5 <= t < 3.0 else 0.0,
             antistuck=None, only=("default",)),
        dict(name="q_waves", dur=4.0,
             pen=piecewise(
                 (2.0, lambda t: sample_pattern(1.0, 1.0, "square", t)),
                 (4.0, lambda t: sample_pattern(1.3, 1.0, "random", t))),
             touch=lambda t: sample_pattern(2.0, 0.5, "sawtooth", t),
             only=("default", "modB")),
        dict(name="q_jittery_dt", dur=4.0, pen=sine(1.1),
             touch=lambda t: sample_pattern(0.5, 0.7, "triangle", t),
             dt_fn=lambda i: (1.0 / 60.0 if i % 7 < 3 else 1.0 / 144.0)
             + (0.25 if i % 97 == 96 else 0.0),
             only=("default", "modA")),
        dict(name="q_jittery_dt_sleep", dur=12.0, pen=sine(1.2), touch=zero,
             sleep=True,
             dt_fn=lambda i: (1.0 / 60.0 if i % 5 < 2 else 1.0 / 120.0)
             + (6.5 if i == 250 else 0.0),
             only=("default",)),
        dict(name="q_live_edits", dur=6.0, pen=sine(1.0),
             touch=lambda t: sample_pattern(0.6, 0.8, "sine", t),
             only=("default",), events=live_edit_events(0.25, 0.5)),
    ]


def set_path(root, path, value):
    cur = root
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value


def run_scenario(sc, cfg_name):
    mix = CONFIGS[cfg_name]()
    profile = {DEV: {
        "motor_count": 1,
        # "Simulated input" switched on for both chain types, exactly what
        # the Input stage's toggle writes.
        "osc_addresses": {"0": [SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS]},
        "mix": {"0": mix},
    }}
    st = {
        "strength": float(sc.get("strength", 1.0)),
        "off": bool(sc.get("off", False)),
        "sleep": bool(sc.get("sleep", False)),
        "antistuck": copy.deepcopy(sc["antistuck"]) if "antistuck" in sc
        else dict(APP_ANTISTUCK),
    }
    clock = FakeClock()
    router = MotorRouter(
        clock=clock.now,
        get_sleep_active=lambda: st["sleep"],
        get_master_scale=lambda: 0.0 if st["off"] else st["strength"],
    )
    captured = {}
    router.set_session_broadcast(
        lambda dev, motor, payload: captured.update(p=payload))

    n_chains = len(mix["chains"])
    events = sorted(sc.get("events", []), key=lambda e: e[0])
    out = {
        "name": sc["name"], "config": cfg_name,
        "initial": {"strength": st["strength"], "off": st["off"],
                    "sleep": st["sleep"], "antistuck": st["antistuck"]},
        "events": [],
        "dt": [], "pen": [], "touch": [],
        "final": [], "contact": [], "strokes": [],
        "band": None,
        "chains": [{k: [] for k in TRACE_KEYS} for _ in range(n_chains)],
        "wake_mode": [[] for _ in range(n_chains)],
    }
    for tick, kind, value in events:
        if kind == "cfg":
            out["events"].append({"tick": tick, "kind": "cfg",
                                  "path": list(value[0]), "value": value[1]})
        else:
            out["events"].append({"tick": tick, "kind": kind, "value": value})

    dt_fn = sc.get("dt_fn")
    dur = float(sc["dur"])
    i = 0
    ev_i = 0
    while True:
        t = clock.now()
        if t > dur:
            break
        # events scheduled for this tick apply BEFORE it is computed
        while ev_i < len(events) and events[ev_i][0] == i:
            _tick, kind, value = events[ev_i]
            if kind == "cfg":
                set_path(mix, value[0], value[1])
            else:
                st[kind] = value
            ev_i += 1
        pen = float(sc["pen"](t))
        touch = float(sc["touch"](t))
        params = {SIM_PEN_ADDRESS: pen, SIM_TOUCH_ADDRESS: touch}
        captured.clear()
        router.reevaluate_state(profile, params, zones=set(),
                                antistuck=st["antistuck"])
        p = captured["p"]
        final = router.last_outputs[(DEV, 0)]
        assert final == p["out"]
        out["pen"].append(pen)
        out["touch"].append(touch)
        out["final"].append(final)
        out["contact"].append(p["contact"])
        out["strokes"].append(router.thrust_count)
        for ci, emit in enumerate(p["chains"]):
            rec = out["chains"][ci]
            for k in TRACE_KEYS:
                v = emit[k]
                rec[k].append(float(v) if not isinstance(v, bool)
                              else (1.0 if v else 0.0))
            out["wake_mode"][ci].append(emit["wake_mode"])
        # advance the clock for the NEXT tick; that step is the dt the
        # next tick sees (the first tick always sees dt = 0).
        step = DT if dt_fn is None else float(dt_fn(i))
        out["dt"].append(step)
        clock.advance(step)
        i += 1
    out["band"] = list(router.last_output_bands[(DEV, 0)])
    out["ticks"] = i
    return out


def sim_reference(quick):
    """sample_pattern on a time grid, for OGPChain.simWave."""
    rows = []
    n = 240 if quick else 1500
    for wave in tuple(WAVEFORMS) + ("bogus",):
        for hz, amp in ((1.0, 1.0), (0.05, 0.35), (2.37, 0.8), (10.0, 1.0),
                        (0.0, 1.0)):
            ts = [k * 0.0137 - 0.5 for k in range(n)]
            rows.append({"wave": wave, "hz": hz, "amp": amp, "t": ts,
                         "v": [sample_pattern(hz, amp, wave, t) for t in ts]})
    return rows


def load_ui_text_helpers():
    """The app's own summary-string code, WITHOUT importing the UI.

    src/ui/motor_signal_chain.py imports PySide6 at module level, and this
    script must stay a console script. The string helpers themselves are
    pure Python, so their source is lifted out of the module with `ast`
    (by name) and compiled on its own: same code, no Qt."""
    import __future__
    path = os.path.join(REPO, "src", "ui", "motor_signal_chain.py")
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    want_funcs = {
        "_default_chain", "_default_mix", "_read_per_motor", "_read_chain",
        "_clamp_num", "_get_output_stage", "_read_wake_cfg",
        "_chain_summary_line",
    }
    want_names = {
        "OUTPUT_GAIN_MAX", "MAX_CHAINS_PER_MOTOR", "_MERGE_OPS",
        "STAGE_INPUT", "STAGE_DEPTH", "STAGE_SPEED", "STAGE_PUNCH",
        "STAGE_COMBINE", "STAGE_WAKE", "STAGE_ENVELOPE", "STAGE_ZEROCUT",
        "STAGE_OUTPUT", "_KIND_DISPLAY", "_DEFAULT_KIND_DISPLAY",
    }
    body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in want_funcs:
            body.append(node)
        elif isinstance(node, ast.ClassDef) and node.name == "_KindDisplay":
            body.append(node)
        elif isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in want_names
                for t in node.targets):
            body.append(node)
        elif (isinstance(node, ast.AnnAssign)
              and isinstance(node.target, ast.Name)
              and node.target.id in want_names):
            body.append(node)
        elif (isinstance(node, ast.ClassDef)
              and node.name == "MotorSignalChainWidget"):
            for sub in node.body:
                if (isinstance(sub, ast.FunctionDef)
                        and sub.name == "_summary_for_stage"):
                    body.append(sub)      # as a plain function(self, stage)
    found = {n.name for n in body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    missing = (want_funcs | {"_KindDisplay", "_summary_for_stage"}) - found
    if missing:
        raise RuntimeError(
            "src/ui/motor_signal_chain.py no longer defines "
            + ", ".join(sorted(missing))
            + " - update tools/site_ports/gen_reference.py to follow the "
            "rename (and port the change to docs/assets/ogp-chain.js)")
    mod = ast.Module(body=body, type_ignores=[])
    code = compile(mod, path, "exec",
                   flags=__future__.annotations.compiler_flag,
                   dont_inherit=True)
    from typing import Any, Callable, Dict, List, Optional, Tuple
    ns = {"copy": copy, "Any": Any, "Callable": Callable, "Dict": Dict,
          "List": List, "Optional": Optional, "Tuple": Tuple,
          "SIM_ADDRESSES": SIM_ADDRESSES}
    exec(code, ns)
    return ns


def summary_reference():
    """The fold-bar summary line + collapsed-card subtitles for the test
    configs, produced by the app's own UI code (see load_ui_text_helpers)."""
    ns = load_ui_text_helpers()

    class Ctl:
        def __init__(self, cfg):
            self.cfg = cfg

        def get_profile_config(self, dev, key, default=None):
            return self.cfg.get(key, default)

        def get_active_profile_dict(self):
            return {DEV: self.cfg}

    class FakeWidget:
        def __init__(self, ctl, chain_idx, kind="vibrate", linear=False):
            self._controller = ctl
            self._device_name = DEV
            self._motor_idx = 0
            self._chain_idx = chain_idx
            self._motor_kind = kind
            self._is_linear = linear

    stage_ids = [ns[k] for k in (
        "STAGE_DEPTH", "STAGE_SPEED", "STAGE_PUNCH", "STAGE_COMBINE",
        "STAGE_WAKE", "STAGE_ENVELOPE", "STAGE_ZEROCUT", "STAGE_OUTPUT")]
    stages = []
    for cfg_name, make in CONFIGS.items():
        mix = make()
        ctl = Ctl({"mix": {"0": mix}})
        for ci in range(len(mix["chains"])):
            w = FakeWidget(ctl, ci)
            stages.append({
                "config": cfg_name, "chain": ci,
                "subtitles": {sid: ns["_summary_for_stage"](w, sid)
                              for sid in stage_ids},
            })

    rows = []
    for cfg_name, make in CONFIGS.items():
        for sim_on in (False, True):
            for routing in ({}, {"motor_0_zones": "All SPS, Mouth",
                                 "motor_0_self": True},
                            {"motor_0_zones": "", "motor_0_others": False},
                            {"motor_0_zones": "Mouth, Butt"}):
                mix = make()
                cfg = {"mix": {"0": mix}}
                cfg.update(routing)
                params = []
                if sim_on:
                    params = ["MyParam", SIM_PEN_ADDRESS, SIM_TOUCH_ADDRESS]
                    cfg["osc_addresses"] = {"0": list(params)}
                ctl = Ctl(cfg)
                for ci in range(len(mix["chains"])):
                    rows.append({
                        "config": cfg_name, "chain": ci,
                        "routing": {
                            "zones": routing.get("motor_0_zones", None),
                            "self": routing.get("motor_0_self", None),
                            "others": routing.get("motor_0_others", None),
                            "params": params,
                        },
                        "line": ns["_chain_summary_line"](ctl, DEV, 0, ci),
                    })
    return {"error": None, "rows": rows, "stages": stages}


def emit(text):
    """print() that survives a console that cannot show a character, and
    a windowless interpreter that has no stdout at all."""
    out = sys.stdout
    if out is None:
        return
    try:
        out.write(text)
    except UnicodeEncodeError:
        out.write(text.encode("ascii", "backslashreplace").decode("ascii"))
    out.flush()


def run_node(script, args):
    """Run a node script without popping a console window; relay its
    output. Returns the exit code (127 when node is missing)."""
    flags = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW
    try:
        proc = subprocess.run(
            ["node", script] + list(args), cwd=REPO,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, creationflags=flags)
    except FileNotFoundError:
        emit("node is not on PATH - reference written, check not run\n")
        return 127
    emit(proc.stdout.decode("utf-8", "replace"))
    return proc.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="folder for reference.json (default: %(default)s)")
    ap.add_argument("--quick", action="store_true",
                    help="the small scenario set the test suite uses")
    ap.add_argument("--no-check", action="store_true",
                    help="only write the reference, do not run check.js")
    ap.add_argument("--js", default=None,
                    help="check this ogp-chain.js instead of docs/assets/")
    args = ap.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    js = os.path.abspath(args.js) if args.js else None
    if is_inside(out_dir, REPO):
        print("refusing to write the reference inside the repo: " + out_dir)
        return 2
    os.chdir(REPO)
    os.makedirs(out_dir, exist_ok=True)
    redirect_home(out_dir)
    load_app()

    scenarios = quick_scenarios() if args.quick else full_scenarios()
    ref = {
        "dt": DT,
        "quick": bool(args.quick),
        "trace_keys": list(TRACE_KEYS),
        "app_defaults": {
            "strength": ModeManager.DEFAULT_STRENGTH,
            "antistuck": APP_ANTISTUCK,
            "router_poll_rate_hz": DEFAULT_APP_SETTINGS.get("router_poll_rate_hz"),
        },
        "configs": {name: make() for name, make in CONFIGS.items()},
        "sleep_wake_override": MotorRouter.SLEEP_WAKE_OVERRIDE,
        "default_chain": MotorRouter.DEFAULT_MIX_CONFIG,
        "runs": [],
        "sim": sim_reference(args.quick),
        "summary": summary_reference(),
    }
    total = 0
    for sc in scenarios:
        for cfg_name in CONFIGS:
            if "only" in sc and cfg_name not in sc["only"]:
                continue
            run = run_scenario(sc, cfg_name)
            total += run["ticks"]
            ref["runs"].append(run)
            print("%-28s %-13s ticks=%5d max_out=%.4f strokes=%d" % (
                sc["name"], cfg_name, run["ticks"], max(run["final"]),
                run["strokes"][-1]))
    path = os.path.join(out_dir, REFERENCE_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(ref, f, allow_nan=False)
    print("wrote %s: %d runs, %d ticks, %.1f MB" % (
        path, len(ref["runs"]), total, os.path.getsize(path) / 1e6))
    emit("")
    if args.no_check:
        return 0
    node_args = [path]
    if js:
        node_args += ["--js", js]
    return run_node(os.path.join(HERE, "check.js"), node_args)


if __name__ == "__main__":
    sys.exit(main())
