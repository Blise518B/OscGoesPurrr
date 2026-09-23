"""The status pill's truth table (osc_link_state.link_state).

The rule under test: a handshake alone is never green. Green requires a
packet inside the live window; the carrier (direct vs 518 router) picks
which green; everything else is yellow or red.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from osc_link_state import (  # noqa: E402
    LIVE_WINDOW_S, STATE_DISCONNECTED, STATE_LIVE, STATE_LIVE_ROUTER,
    STATE_WAITING, link_state,
)


def test_disconnected_wins_over_everything():
    # Even fresh packet ages mean nothing without a connection — a stale
    # manager object keeps its timestamps after a disconnect.
    assert link_state(False, None, None) == STATE_DISCONNECTED
    assert link_state(False, 0.1, 0.1) == STATE_DISCONNECTED


def test_handshake_alone_is_waiting_not_connected():
    # The exact bug this exists for: OSCQuery handshake done, zero packets.
    assert link_state(True, None, None) == STATE_WAITING


def test_stale_stream_drops_back_to_waiting():
    assert link_state(True, LIVE_WINDOW_S, LIVE_WINDOW_S) == STATE_WAITING
    assert link_state(True, LIVE_WINDOW_S + 10.0, None) == STATE_WAITING


def test_fresh_direct_stream_is_live():
    assert link_state(True, 0.2, 0.2) == STATE_LIVE
    # Just inside the window still counts.
    assert link_state(True, LIVE_WINDOW_S - 0.01,
                      LIVE_WINDOW_S - 0.01) == STATE_LIVE


def test_router_only_stream_is_live_router():
    # Packets flowing, but none ever came straight from VRChat: the 518
    # fallback is carrying the session (dead mDNS listener).
    assert link_state(True, 0.2, None) == STATE_LIVE_ROUTER
    # ...or the direct stream died mid-session and the router took over.
    assert link_state(True, 0.2, LIVE_WINDOW_S + 60.0) == STATE_LIVE_ROUTER


def test_direct_resuming_reclaims_plain_live():
    # VRChat rediscovered us: direct packets are fresh again, so the pill
    # returns to the unqualified green even while router traffic continues.
    assert link_state(True, 0.1, 1.0) == STATE_LIVE
