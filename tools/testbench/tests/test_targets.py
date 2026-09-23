"""Tests for the simulator's universal target tracking.

Pure — constructs a VRChatSimNetwork WITHOUT calling start() (no mDNS / HTTP /
UDP servers come up), and exercises the discovery/selection logic directly.
SimpleUDPClient creation binds no peer, so select/manual work offline; the
fixture's teardown clears the target so the UDP socket is closed deterministically.
"""

from __future__ import annotations

import pytest

from testbench.sim_network import VRChatSimNetwork


@pytest.fixture
def net_ctx():
    targets, active, status = [], [], []
    net = VRChatSimNetwork(
        on_targets_changed=lambda names: targets.append(list(names)),
        on_target_changed=lambda label: active.append(label),
        on_status=lambda m: status.append(m),
    )
    net._service_name = "VRChat-Client-Sim-TEST"
    try:
        yield net, targets, active
    finally:
        net.clear_target()  # closes any open UDP socket


def test_instance_label_strips_service_suffix():
    assert VRChatSimNetwork._instance_label(
        "OSC Goes Brrr._osc._udp.local.", "_osc._udp.local.") == "OSC Goes Brrr"
    assert VRChatSimNetwork._instance_label(
        "OscGoesPurrr._oscjson._tcp.local.", "_oscjson._tcp.local.") == "OscGoesPurrr"


def test_is_self_excludes_own_advertisement(net_ctx):
    net, _, _ = net_ctx
    assert net._is_self("VRChat-Client-Sim-TEST._osc._udp.local.") is True
    assert net._is_self("OSC Goes Brrr._osc._udp.local.") is False
    # before start(), service name is empty -> nothing counts as self
    fresh = VRChatSimNetwork()
    assert fresh._is_self("anything") is False


def test_add_discovers_and_auto_selects_first(net_ctx):
    net, targets, active = net_ctx
    net._add_discovered("OSC Goes Brrr", "127.0.0.1", 9001)
    assert net.discovered_targets() == ["OSC Goes Brrr"]
    assert net.active_target_label() == "OSC Goes Brrr"   # auto-selected
    assert targets[-1] == ["OSC Goes Brrr"]
    assert active[-1] == "OSC Goes Brrr"


def test_second_discovery_does_not_change_auto_selection(net_ctx):
    net, _, _ = net_ctx
    net._add_discovered("OSC Goes Brrr", "127.0.0.1", 9001)
    net._add_discovered("OscGoesPurrr", "127.0.0.1", 9100)
    assert sorted(net.discovered_targets()) == ["OSC Goes Brrr", "OscGoesPurrr"]
    assert net.active_target_label() == "OSC Goes Brrr"   # first pick stands


def test_user_selection_sticks_against_later_auto(net_ctx):
    net, _, _ = net_ctx
    net._add_discovered("OSC Goes Brrr", "127.0.0.1", 9001)
    assert net.select_target("OscGoesPurrr") is False     # not discovered yet
    net._add_discovered("OscGoesPurrr", "127.0.0.1", 9100)
    assert net.select_target("OscGoesPurrr", user=True) is True
    assert net.active_target_label() == "OscGoesPurrr"
    # a new app appearing must NOT steal the user's explicit choice
    net._add_discovered("Some Other App", "127.0.0.1", 9200)
    assert net.active_target_label() == "OscGoesPurrr"


def test_remove_active_clears_it(net_ctx):
    net, _, active = net_ctx
    net._add_discovered("OSC Goes Brrr", "127.0.0.1", 9001)
    net._remove_discovered("OSC Goes Brrr")
    assert net.discovered_targets() == []
    assert net.active_target_label() is None
    assert active[-1] is None


def test_remove_non_active_keeps_active(net_ctx):
    net, _, _ = net_ctx
    net._add_discovered("OSC Goes Brrr", "127.0.0.1", 9001)   # auto-active
    net._add_discovered("OscGoesPurrr", "127.0.0.1", 9100)
    net._remove_discovered("OscGoesPurrr")                     # not the active one
    assert net.active_target_label() == "OSC Goes Brrr"
    assert net.discovered_targets() == ["OSC Goes Brrr"]


def test_manual_target(net_ctx):
    net, _, active = net_ctx
    net.set_manual_target("127.0.0.1", 9000)
    assert net.active_target_label() == "Manual 127.0.0.1:9000"
    assert active[-1] == "Manual 127.0.0.1:9000"


def test_listen_info_exposes_target_key(net_ctx):
    net, _, _ = net_ctx
    info = net.listen_info()
    assert "target" in info and info["target"] is None
    net.set_manual_target("127.0.0.1", 9000)
    assert net.listen_info()["target"] == "Manual 127.0.0.1:9000"
