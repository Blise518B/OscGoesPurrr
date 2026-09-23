"""Truthful VRChat OSC link state for the UI.

A successful OSCQuery handshake only proves VRChat's HTTP endpoint answered;
it says nothing about whether VRChat's mDNS listener actually discovered us
and is pushing data (518Hub/docs/PROBLEM.md — the "connected but silent"
failure). The status pill therefore distinguishes:

  disconnected  — no handshake; the OSC server may not even be running.
  waiting       — handshake OK, but no OSC packet in the last LIVE_WINDOW_S.
                  Shown yellow: "connected" would be a lie the user pays for
                  in silent toys.
  live          — packets are arriving straight from VRChat.
  live_router   — packets are arriving, but only via the OSC Router 518
                  fallback (Tier 1). Green — data is data — with the carrier
                  named so a dead direct link is never mistaken for health.

Pure and stdlib-only, mirroring osc_router_518.is_starved: the rule the UI
shows is testable on its own, away from sockets and Qt.
"""
from __future__ import annotations

from typing import Optional

#: How fresh the newest packet must be to call the stream "live". VRChat
#: streams tracking data continuously during gameplay, so 5 s of total
#: silence really is a stalled link (menus and loading screens pause the
#: stream — the pill dropping to yellow there is truthful, not noise).
LIVE_WINDOW_S = 5.0

STATE_DISCONNECTED = "disconnected"
STATE_WAITING = "waiting"
STATE_LIVE = "live"
STATE_LIVE_ROUTER = "live_router"


def link_state(connected: bool,
               since_any_s: Optional[float],
               since_direct_s: Optional[float],
               window_s: float = LIVE_WINDOW_S) -> str:
    """Classify the link. ``since_any_s``/``since_direct_s`` are seconds since
    the newest packet from anywhere / straight from VRChat, or None if no such
    packet has arrived this session (NOT the advertisement age —
    ``seconds_since_direct_packet`` measures that for the fallback ladder and
    would make a freshly-advertised silent link look live here)."""
    if not connected:
        return STATE_DISCONNECTED
    if since_any_s is None or since_any_s >= window_s:
        return STATE_WAITING
    if since_direct_s is not None and since_direct_s < window_s:
        return STATE_LIVE
    return STATE_LIVE_ROUTER
