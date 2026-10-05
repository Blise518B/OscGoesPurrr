# Site ports: keeping the website demo honest

The demo on the website (`docs/index.html`) does not fake its signal. It
runs two JavaScript ports of app code:

| Port | Mirrors |
|---|---|
| `docs/assets/ogp-chain.js` | the signal chain: `src/motor_router.py` (`_calculate_motor_target` and its detectors), `src/mixer.py` (curves, combine, wake meter, smoothing, the simulator's waves), the shipped preset in `src/config_manager.py` (`preset_motor_mix`), plus the fold-bar summary line, the stage-card subtitles and the on-card controls from `src/ui/motor_signal_chain.py` |
| `docs/assets/ogp-accent.js` | the colour picker's maths: `src/accent_shift.py` |

A port is only worth having while it matches. The scripts here drive the
**real Python** and replay the same inputs through the JavaScript.

## When to run

After any change to:

- `src/motor_router.py`
- `src/mixer.py`
- the preset in `src/config_manager.py` (`_DEFAULT_FEEL`, `_TOUCH_FEEL`, `preset_motor_mix`)
- `src/accent_shift.py`
- the on-card controls or summary strings in `src/ui/motor_signal_chain.py`
  (`_chain_summary_line`, `_summary_for_stage`, the quick sliders/toggles)
- either port

`pytest` runs a reduced version of both checks on every suite run
(`tests/test_site_ports.py`, about 3 s, skipped when `node` is missing).
Run the full set below before a release that touched any of the files above.

## Commands

From the repo root. Needs `node` on PATH.

```
venv\Scripts\python.exe tools\site_ports\gen_reference.py
venv\Scripts\python.exe tools\site_ports\check_accent.py
```

Each writes its reference and then runs the matching node check; exit code
0 means the port matches. The chain run takes about 7 s (65 runs, 114 000
ticks, every per-stage trace within 1e-9), the colour run about 5 s (50 000
colours, strings identical).

Options, same for both scripts:

| Option | Meaning |
|---|---|
| `--out DIR` | where the reference goes. Default: `ogp-site-ports` in the system temp folder. A folder inside the repo is refused: the chain reference is 43 MB |
| `--quick` | the small set the test suite uses |
| `--no-check` | write the reference only |
| `--js FILE` | check that file instead of the one in `docs/assets/` |

The node halves can be run on their own against an existing reference:

```
node tools\site_ports\check.js [reference.json or its folder] [--js FILE] [--all]
node tools\site_ports\check_accent.js [accent_reference.json or its folder] [--js FILE]
```

## When a check fails

The Python is the truth. Change the port in `docs/assets/` until the check
passes again; do not adjust the reference or loosen the tolerance. If the
Python gained a stage, a config key or a control, port it, and add a
scenario that exercises it to `full_scenarios()` and `quick_scenarios()` in
`gen_reference.py`.

`gen_reference.py` lifts the summary-string functions out of
`src/ui/motor_signal_chain.py` by name (so it never imports Qt). Renaming
one of them makes it stop with a message naming the function.

## What the scripts touch

Nothing in the repo and nothing in the real profile. Importing the app's
settings package creates its AppData folder, so both scripts point the home
directory at `<out>\_fakehome` before importing anything, and they never
write bytecode caches.

One known, accepted difference: `hueOf` / `deltaFor` return numbers that
can differ from Python's in the last digits (about 6e-14 degrees), because
V8 and the Microsoft C runtime round `atan2` and `pow` differently in the
last bit. The colour strings are identical.
