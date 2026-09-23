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
from intiface_external import ExternalIntifaceConnection
from intiface_integrated import (
    IntegratedIntifaceConnection,
    _build_engine_args,
    _find_device_config,
    _resolve_engine_path,
    _ws_host_port,
)


def _run(coro):
    return asyncio.run(coro)


# ----------------------------------------------------------------- external provider

class TestExternalProvider:
    def test_prepare_returns_ws_url(self):
        conn = ExternalIntifaceConnection()
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
