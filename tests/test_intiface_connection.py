"""Tests for the Intiface connection providers and the selecting factory.

All hardware-free: the external provider is pure, the integrated provider's
pure helpers are exercised directly, and prepare() is only driven down its
binary-missing path (which raises before any subprocess is spawned). Nothing
here launches intiface-engine or imports `buttplug`, so it runs on CI.
"""

import asyncio
from pathlib import Path

import pytest

import intiface_integrated
from constants import INTIFACE_WS_URL
from intiface_connection import (
    MODE_EXTERNAL,
    MODE_INTEGRATED,
    make_intiface_connection,
)
from intiface_discovery import SERVICE_TYPE, IntifaceFinder, _usable_ipv4, instance_label
from intiface_external import ExternalIntifaceConnection, address_url, normalize_address
from intiface_integrated import (
    IntegratedIntifaceConnection,
    _build_engine_args,
    _find_device_config,
    _resolve_engine_path,
    _ws_host_port,
)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _short_first_look(monkeypatch):
    # The first look waits up to 1.2 s for a phone's mDNS answer; the fake
    # finders below answer at once or never.
    import intiface_external
    monkeypatch.setattr(intiface_external, "_FIRST_LOOK_S", 0.0)


# ----------------------------------------------------------------- external provider

class _FakeFinder:
    """Stands in for intiface_discovery.IntifaceFinder: no zeroconf, no
    sockets. `servers` is what mDNS "shows"."""

    instances = []

    def __init__(self, log=None, servers=None, start_ok=True):
        self._servers = list(servers or [])
        self.start_ok = start_ok
        self.started = self.closed = False
        _FakeFinder.instances.append(self)

    def start(self):
        self.started = True
        return self.start_ok

    def servers(self):
        return list(self._servers)

    def close(self):
        self.closed = True


def _finder(servers=None, start_ok=True):
    return lambda log=None: _FakeFinder(log=log, servers=servers, start_ok=start_ok)


_PHONE = {"name": "Intiface Ab12Cd", "host": "192.168.1.50", "port": 12345}


class TestExternalProvider:
    def test_prepare_returns_ws_url(self):
        # Nothing typed, nothing on the network: this PC, as it always was.
        conn = ExternalIntifaceConnection(finder_factory=_finder())
        assert _run(conn.prepare()) == INTIFACE_WS_URL

    def test_status_label_unchanged(self):
        # Must stay "Intiface" so the UI reads identically in external mode.
        assert ExternalIntifaceConnection().status_label == "Intiface"

    def test_mode_tag(self):
        assert ExternalIntifaceConnection().mode == MODE_EXTERNAL

    def test_teardown_is_noop(self):
        conn = ExternalIntifaceConnection()
        conn.terminate()          # no process ever owned
        _run(conn.shutdown())     # idempotent, no raise

    def test_typed_address_is_dialled_and_no_finder_runs(self):
        made = []
        conn = ExternalIntifaceConnection(
            address="192.168.1.50", finder_factory=lambda log=None: made.append(1))
        assert _run(conn.prepare()) == "ws://192.168.1.50:12345"
        assert _run(conn.prepare()) == "ws://192.168.1.50:12345"   # always that one
        assert made == []

    def test_unparsable_setting_means_find_it(self):
        conn = ExternalIntifaceConnection(address="not an address",
                                          finder_factory=_finder())
        assert conn.address == ""
        assert _run(conn.prepare()) == INTIFACE_WS_URL

    def test_found_phone_goes_first_then_this_pc_takes_a_turn(self):
        conn = ExternalIntifaceConnection(finder_factory=_finder([_PHONE]))
        assert _run(conn.prepare()) == "ws://192.168.1.50:12345"
        # That attempt failed (no note_connected): the next tries this PC,
        # so a PC whose Central announces itself but listens only locally
        # still connects.
        assert _run(conn.prepare()) == INTIFACE_WS_URL
        assert _run(conn.prepare()) == "ws://192.168.1.50:12345"

    def test_the_one_that_worked_goes_first_after_a_drop(self):
        conn = ExternalIntifaceConnection(finder_factory=_finder([_PHONE]))
        _run(conn.prepare())                      # phone: failed
        assert _run(conn.prepare()) == INTIFACE_WS_URL
        conn.note_connected()                     # this PC worked
        assert _run(conn.prepare()) == INTIFACE_WS_URL

    def test_logs_each_place_once_not_every_retry(self):
        seen = []
        conn = ExternalIntifaceConnection(log=seen.append, finder_factory=_finder([_PHONE]))
        for _ in range(6):
            _run(conn.prepare())
        tries = [m for m in seen if m.startswith("Connecting to Intiface")]
        assert len(tries) == 2
        assert any("192.168.1.50:12345 (Intiface Ab12Cd" in m for m in tries)
        assert any("on this PC" in m for m in tries)

    def test_finder_that_cannot_start_leaves_this_pc(self):
        conn = ExternalIntifaceConnection(finder_factory=_finder(start_ok=False))
        assert _run(conn.prepare()) == INTIFACE_WS_URL
        assert conn.describe()["searching"] is False

    def test_describe_reports_target_and_found(self):
        conn = ExternalIntifaceConnection(finder_factory=_finder([_PHONE]))
        _run(conn.prepare())
        d = conn.describe()
        assert d["auto"] is True and d["address"] == ""
        assert d["target"] == "192.168.1.50:12345"
        assert d["target_name"] == "Intiface Ab12Cd"
        assert d["target_local"] is False
        assert d["found"] == [_PHONE]

    def test_shutdown_and_terminate_close_the_finder(self):
        _FakeFinder.instances.clear()
        conn = ExternalIntifaceConnection(finder_factory=_finder())
        _run(conn.prepare())
        _run(conn.shutdown())
        assert _FakeFinder.instances[-1].closed
        conn2 = ExternalIntifaceConnection(finder_factory=_finder())
        _run(conn2.prepare())
        conn2.terminate()
        assert _FakeFinder.instances[-1].closed


class TestNormalizeAddress:
    @pytest.mark.parametrize("typed, stored", [
        ("", ""),
        ("   ", ""),
        ("192.168.1.50", "192.168.1.50:12345"),
        (" 192.168.1.50:12346 ", "192.168.1.50:12346"),
        ("ws://192.168.1.50:12345/", "192.168.1.50:12345"),
        ("WS://192.168.1.50", "192.168.1.50:12345"),
        ("wss://phone.local:1234", "wss://phone.local:1234"),
        ("pixel-7.local", "pixel-7.local:12345"),
        ("localhost", "localhost:12345"),
        ("[fe80::1]:12345", "[fe80::1]:12345"),
    ])
    def test_accepted(self, typed, stored):
        assert normalize_address(typed) == stored

    @pytest.mark.parametrize("typed", [
        "http://192.168.1.50", "192.168.1.50:99999", "192.168.1.50:0",
        "192.168 .1.50", "user@192.168.1.50", "192.168.1.50/path",
        "bad_host!", "192.168.1.50:abc",
    ])
    def test_refused(self, typed):
        assert normalize_address(typed) is None

    def test_url_built_from_stored_form(self):
        assert address_url("192.168.1.50:12345") == "ws://192.168.1.50:12345"
        assert address_url("wss://phone.local:1234") == "wss://phone.local:1234"


class TestFinder:
    def test_newest_server_first_one_entry_per_address(self):
        f = IntifaceFinder()
        f.add("Intiface Old._intiface_engine._tcp.local.", ["192.168.1.40"], 12345)
        f.add("Intiface New._intiface_engine._tcp.local.", ["192.168.1.50", "10.0.0.5"], 12345)
        hosts = [(s["name"], s["host"]) for s in f.servers()]
        assert hosts[0][0] == "Intiface New"
        assert ("Intiface Old", "192.168.1.40") in hosts
        assert len(hosts) == 3

    def test_removed_server_is_dropped(self):
        f = IntifaceFinder()
        name = "Intiface X._intiface_engine._tcp.local."
        f.add(name, ["192.168.1.50"], 12345)

        class _Removed:
            name = "Removed"

        f._on_change(None, SERVICE_TYPE, name, _Removed())
        assert f.servers() == []

    def test_only_usable_ipv4_addresses(self):
        assert _usable_ipv4(["fe80::1", "169.254.3.4", "127.0.0.1",
                             "192.168.1.50", "junk"]) == ["192.168.1.50"]

    def test_instance_label(self):
        assert instance_label("Intiface Ab12Cd._intiface_engine._tcp.local.") == "Intiface Ab12Cd"
        assert instance_label("") == "Intiface"

    def test_close_without_start_is_safe(self):
        IntifaceFinder().close()


# ----------------------------------------------------------------- factory

class TestFactory:
    def test_external_selected(self):
        conn = make_intiface_connection(MODE_EXTERNAL)
        assert isinstance(conn, ExternalIntifaceConnection)
        assert conn.mode == MODE_EXTERNAL

    def test_integrated_selected(self):
        conn = make_intiface_connection(MODE_INTEGRATED)
        assert isinstance(conn, IntegratedIntifaceConnection)
        assert conn.mode == MODE_INTEGRATED

    def test_unknown_mode_defaults_to_integrated(self):
        # A malformed setting must never leave the engine without a strategy.
        conn = make_intiface_connection("garbage")
        assert isinstance(conn, IntegratedIntifaceConnection)

    def test_log_callback_passed_through(self):
        seen = []
        conn = make_intiface_connection(MODE_INTEGRATED, log=seen.append)
        conn._log("hi")
        assert seen == ["hi"]

    def test_address_passed_to_external(self):
        conn = make_intiface_connection(MODE_EXTERNAL, address="192.168.1.50")
        assert conn.address == "192.168.1.50:12345"


# ----------------------------------------------------------------- integrated pure helpers

class TestIntegratedHelpers:
    def test_ws_host_port_matches_constant(self):
        assert _ws_host_port() == ("127.0.0.1", 12345)

    def test_engine_args_have_required_flags(self):
        args = _build_engine_args(12345)
        assert "--websocket-port" in args
        # port immediately follows its flag
        assert args[args.index("--websocket-port") + 1] == "12345"
        assert "--use-bluetooth-le" in args
        # --stay-open is NOT a valid intiface-engine v1.4.8 flag; passing it
        # would make the engine reject the args and exit on launch.
        assert "--stay-open" not in args

    def test_engine_args_omit_device_config_when_absent(self, tmp_path):
        args = _build_engine_args(12345, engine_dir=tmp_path)
        assert "--device-config-file" not in args

    def test_engine_args_include_device_config_when_present(self, tmp_path):
        cfg = tmp_path / "buttplug-device-config.json"
        cfg.write_text("{}", encoding="utf-8")
        args = _build_engine_args(12345, engine_dir=tmp_path)
        assert "--device-config-file" in args
        assert args[args.index("--device-config-file") + 1] == str(cfg)

    def test_find_device_config_none_in_empty_dir(self, tmp_path):
        assert _find_device_config(tmp_path) is None

    def test_resolve_engine_path_shape(self):
        p = _resolve_engine_path()
        assert p.parent.name == "intiface-engine"
        assert p.name in ("intiface-engine.exe", "intiface-engine")


# ----------------------------------------------------------------- integrated prepare (no spawn)

class TestIntegratedPrepareMissingBinary:
    def test_missing_binary_raises_actionable_error(self, monkeypatch):
        missing = Path("does-not-exist") / "intiface-engine" / "intiface-engine.exe"
        monkeypatch.setattr(intiface_integrated, "_resolve_engine_path", lambda: missing)

        conn = IntegratedIntifaceConnection()
        with pytest.raises(FileNotFoundError) as exc:
            _run(conn.prepare())
        # Message should point the user at the fix (drop binary or switch mode).
        msg = str(exc.value)
        assert "intiface-engine" in msg
        assert "External" in msg
        # Nothing was spawned.
        assert conn._proc is None

    def test_status_label_distinct_from_external(self):
        assert IntegratedIntifaceConnection().status_label != "Intiface"

    def test_terminate_without_process_is_noop(self):
        IntegratedIntifaceConnection().terminate()


class TestIntegratedPrepareReuse:
    def test_prepare_reuses_live_engine_without_respawn_or_probe(self, monkeypatch):
        # A live engine must be reused as-is: no respawn, and crucially no
        # socket probe (a bare TCP connect makes intiface-engine exit on
        # HandshakeIncomplete — the bug this guards against).
        conn = IntegratedIntifaceConnection()

        class _AliveProc:
            returncode = None

            def poll(self):
                return None  # still running

        conn._proc = _AliveProc()

        def _must_not_respawn():
            raise AssertionError("prepare must not respawn while a live engine exists")

        monkeypatch.setattr(intiface_integrated, "_resolve_engine_path", _must_not_respawn)
        assert _run(conn.prepare()) == INTIFACE_WS_URL


# ----------------------------------------------------------------- engine-crash logging

class TestIntegratedEngineCrashLogging:
    def test_dead_engine_records_exit_before_respawn(self, monkeypatch):
        # When prepare() finds the engine already dead, it must capture the exit
        # code BEFORE tearing it down / respawning (which truncates the engine's
        # own log), so a "randomly closed" session leaves durable evidence.
        conn = IntegratedIntifaceConnection()

        class _DeadProc:
            returncode = 3

            def poll(self):
                return 3  # already exited

        conn._proc = _DeadProc()

        recorded = []
        monkeypatch.setattr(
            IntegratedIntifaceConnection,
            "_record_engine_exit",
            staticmethod(lambda code, tail: recorded.append((code, tail))),
        )
        # Force the missing-binary path so prepare() raises right after the
        # crash capture instead of actually spawning a replacement engine.
        missing = Path("does-not-exist") / "intiface-engine" / "intiface-engine.exe"
        monkeypatch.setattr(intiface_integrated, "_resolve_engine_path", lambda: missing)

        with pytest.raises(FileNotFoundError):
            _run(conn.prepare())

        assert recorded and recorded[0][0] == 3   # the exit code was captured
        assert conn._proc is None                 # stale handle released

    def test_record_engine_exit_classifies_crash_vs_clean(self):
        # A non-zero/unknown exit is an ERROR ("CRASH"); a clean code-0 exit is
        # a WARNING. Capture via a private handler so the test is hermetic and
        # doesn't depend on setup_logging() having run.
        import logging

        records = []

        class _Capture(logging.Handler):
            def emit(self, record):
                records.append(record)

        logger = logging.getLogger("ogp.engine")
        handler = _Capture()
        logger.addHandler(handler)
        old_level = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            IntegratedIntifaceConnection._record_engine_exit(139, "panic tail")
            IntegratedIntifaceConnection._record_engine_exit(0, "clean shutdown")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(old_level)

        levels = {r.levelno for r in records}
        assert logging.ERROR in levels    # non-zero exit -> CRASH
        assert logging.WARNING in levels  # clean exit -> warning
        assert any("CRASH" in r.getMessage() for r in records)
