# Unified test bench — strictly stand-alone, never imported by the main app.
#
# Drives a known input signal into the LIVE OscGoesPurrr app (impersonating
# VRChat over OSC) and reads the resulting toy output (impersonating a Lovense
# toy on Intiface), on a single clock, so input vs output can be plotted on a
# shared timeline and end-to-end "program delay" benchmarked.
#
# Absorbs the former standalone `sim/` and `toysim/` tools as flat modules:
#   * sim_network.py / sim_avatar.py     — VRChat OSC + OSCQuery (was sim/)
#   * lovense_device.py / lovense_protocol.py — Lovense virtual toy (was toysim/)
