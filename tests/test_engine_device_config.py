"""The device list the bundled engine starts with is Buttplug's own, minus
the match that made it connect to every Bluetooth serial device.

src/intiface-engine/buttplug-device-config-v4.json replaces the engine's
built-in list (tools/make_engine_device_config.py says why). These tests
catch the drift: a Nordic UART match creeping back, the file going missing
from the folder the engine is started from, or an engine rebuild without
regenerating the file (then toys added upstream would go missing).
"""

import importlib.util
import json
from pathlib import Path

import pytest

from intiface_integrated import _find_device_config

REPO = Path(__file__).resolve().parent.parent
SHIPPED = REPO / "src" / "intiface-engine" / "buttplug-device-config-v4.json"


def _tool():
    path = REPO / "tools" / "make_engine_device_config.py"
    spec = importlib.util.spec_from_file_location("make_engine_device_config", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _btle(config, protocol):
    return [c["btle"] for c in config["protocols"][protocol].get("communication") or []
            if "btle" in c]


def test_no_protocol_matches_on_the_nordic_uart_service_alone():
    nus = _tool().NORDIC_UART_SERVICE
    config = _load(SHIPPED)
    for protocol in config["protocols"]:
        for btle in _btle(config, protocol):
            advertised = [u.lower() for u in btle.get("advertised_services") or []]
            assert nus not in advertised, (
                f"{protocol} matches every Bluetooth serial device again -- "
                "run tools/make_engine_device_config.py")


def test_lovense_toys_are_still_found_and_talk_over_it():
    nus = _tool().NORDIC_UART_SERVICE
    btle = _btle(_load(SHIPPED), "lovense")
    assert any("LVS-*" in b.get("names", []) for b in btle)
    assert any(b.get("advertised_services") for b in btle)
    assert any(nus in {u.lower() for u in b.get("services", {})} for b in btle)


def test_the_engine_is_started_with_it():
    assert _find_device_config(SHIPPED.parent) == SHIPPED


def test_it_is_the_engine_checkouts_config_minus_that_match():
    tool = _tool()
    if not tool.SOURCE.is_file():
        pytest.skip("no engine checkout in _engine_build/buttplug")
    assert tool.corrected(_load(tool.SOURCE)) == _load(SHIPPED), (
        "the engine checkout's device config changed -- run tools/make_engine_device_config.py")


def test_a_buttplug_fix_is_reported_not_hidden():
    tool = _tool()
    config = _load(SHIPPED)  # already without the match
    with pytest.raises(ValueError, match="no longer matches"):
        tool.corrected(config)
