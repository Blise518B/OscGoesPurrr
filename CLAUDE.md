# Project: OscGoesPurrr

A VRChat OSC → multi-backend haptic router (Buttplug.io toys, SteamVR
tracker haptics, bHaptics suits, optional SteamVR Toy Driver).
Python 3.10+, PySide6 UI, Windows-first.

Read [`README.md`](README.md) for the feature overview and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for the layered design
(sealed engines / stateless routers / controller mixins). The four
anti-tangling rules in ARCHITECTURE.md are load-bearing — don't break
them.

**Low latency is load-bearing too.** This is a real-time haptics router:
minimizing OSC-in → device-out latency is a first-class priority for
*every* backend (Buttplug toys, strokers, bHaptics, SteamVR), not a
nice-to-have. Don't add queue hops, fixed delays, or ack-blocking waits to
any routing / engine / dispatch path; prefer direct dispatch,
fire-and-forget sends, fast (~60 Hz) polling, and per-feature send caps for
hardware safety. See ARCHITECTURE.md § "Latency budget" before touching a
hot path.

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

Do not try to invoke `python main.py`, `run.bat`, or `build_OGP.bat` in
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
