# Project: OscGoesPurrr

A VRChat OSC → multi-backend haptic router (Buttplug.io toys, SteamVR
tracker haptics, bHaptics suits, hardware-monitor broadcaster, optional
SteamVR Toy Driver). Python 3.10+, PySide6 UI, Windows-first.

Read [`README.md`](README.md) for the feature overview and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the layered design
(sealed engines / stateless routers / controller mixins). The four
anti-tangling rules in ARCHITECTURE.md are load-bearing — don't break
them.

## Cloud sandbox caveat

If you are running in a Linux cloud sandbox (e.g. the mobile Claude
Code app), you **cannot launch the app**. `main.py` requires Windows
plus local hardware: Intiface Central for Buttplug toys, SteamVR for
trackers / toy driver, bHaptics Player for suits, OSC traffic from a
running VRChat instance. None of that exists in the sandbox.

What you **can** do in the sandbox:

- Read and edit any source file.
- Run the test suite: `pip install -r requirements-dev.txt && pytest`.
  Tests are pure-Python and do not need hardware.
- Type-check, lint, refactor.
- Commit and push back to GitHub for the user to pull on Windows.

Do not try to invoke `python main.py`, `run.bat`, or `build.bat` in
the sandbox — they will fail and waste time. State the limitation and
hand the work back if a change genuinely needs a live run.

## Running tests

```
pip install -r requirements-dev.txt
pytest
```

`pytest.ini` treats warnings as errors (except a known
`websocket` `DeprecationWarning`). Tests live under `tests/`.

## Commit & PR style

When drafting commit messages and PR descriptions:

- Describe only the code change and the reason for it.
- Do not mention Claude, AI, "generated with", "co-authored", or this
  tool anywhere in the subject, body, or trailers.
- Treat all code as human-authored; the diff and history speak for
  themselves.
- Keep the subject line under ~70 characters; use the body for the
  "why" when it isn't obvious from the diff.
