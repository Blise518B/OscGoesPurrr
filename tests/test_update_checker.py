"""Tests for the sealed GitHub update checker (update_checker.py).

Never hits the network: `requests` is monkeypatched inside the module
with stubs whose .get returns canned responses (or raises).
"""

from types import SimpleNamespace

import pytest

import update_checker
from update_checker import _parse_version, check_for_update


# ---------------------------------------------------------------- _parse_version

class TestParseVersion:
    def test_v_prefix(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_capital_v_prefix(self):
        assert _parse_version("V2.0") == (2, 0)

    def test_two_part(self):
        assert _parse_version("1.2") == (1, 2)

    def test_dev_suffix_uses_numeric_prefix(self):
        # The app's own __version__ carries branch suffixes off main.
        assert _parse_version("1.2.51-dev(3)") == (1, 2, 51)

    def test_whitespace_tolerated(self):
        assert _parse_version("  v1.2.3  ") == (1, 2, 3)

    @pytest.mark.parametrize("junk", [
        "junk", "", "v", "1.two.3", None, "1..2", "release", 123, "..",
    ])
    def test_junk_is_none(self, junk):
        assert _parse_version(junk) is None


# ---------------------------------------------------------------- check_for_update

class _Resp:
    def __init__(self, status=200, payload=None, json_exc=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self._json_exc = json_exc

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


def _release(tag, url="https://github.com/Blise518B/OscGoesPurrr/releases/tag/x"):
    return {"tag_name": tag, "html_url": url}


def _install_requests(monkeypatch, resp=None, exc=None):
    """Replace update_checker.requests with a stub; returns the call log."""
    calls = {}

    def _get(url, timeout=None, headers=None):
        calls["url"] = url
        calls["timeout"] = timeout
        calls["headers"] = headers or {}
        if exc is not None:
            raise exc
        return resp

    monkeypatch.setattr(update_checker, "requests",
                        SimpleNamespace(get=_get))
    return calls


class TestCheckForUpdate:
    def test_newer_remote_is_available(self, monkeypatch):
        calls = _install_requests(
            monkeypatch, resp=_Resp(payload=_release("v1.3.0", "https://x/rel")))
        info = check_for_update("1.2.3")
        assert info == {"available": True, "latest": "1.3.0",
                        "url": "https://x/rel"}
        # Sanity: it really targets the project's releases endpoint.
        assert "Blise518B/OscGoesPurrr/releases/latest" in calls["url"]
        assert calls["timeout"] == 5.0

    def test_same_version_not_available(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v1.2.3")))
        info = check_for_update("1.2.3")
        assert info is not None and info["available"] is False

    def test_older_remote_not_available(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v0.9")))
        info = check_for_update("1.2.3")
        assert info is not None and info["available"] is False

    def test_short_vs_padded_versions_equal(self, monkeypatch):
        # "1.2" vs "v1.2.0" must not read as an update.
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v1.2.0")))
        info = check_for_update("1.2")
        assert info is not None and info["available"] is False

    def test_dev_suffix_current_version_compares(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v1.2.52")))
        info = check_for_update("1.2.51-dev(3)")
        assert info is not None and info["available"] is True

    def test_network_error_is_none(self, monkeypatch):
        _install_requests(monkeypatch, exc=OSError("no route to host"))
        assert check_for_update("1.2.3") is None

    def test_any_exception_is_swallowed(self, monkeypatch):
        _install_requests(monkeypatch, exc=RuntimeError("boom"))
        assert check_for_update("1.2.3") is None

    def test_malformed_json_is_none(self, monkeypatch):
        _install_requests(
            monkeypatch, resp=_Resp(json_exc=ValueError("bad json")))
        assert check_for_update("1.2.3") is None

    def test_non_dict_payload_is_none(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=["not", "a", "dict"]))
        assert check_for_update("1.2.3") is None

    def test_rate_limited_is_none(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(status=403))
        assert check_for_update("1.2.3") is None

    def test_junk_tag_is_none(self, monkeypatch):
        _install_requests(
            monkeypatch, resp=_Resp(payload=_release("latest-release")))
        assert check_for_update("1.2.3") is None

    def test_junk_current_version_is_none(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v1.3.0")))
        assert check_for_update("garbage") is None

    def test_requests_missing_is_none(self, monkeypatch):
        monkeypatch.setattr(update_checker, "requests", None)
        assert check_for_update("1.2.3") is None

    def test_custom_timeout_forwarded(self, monkeypatch):
        calls = _install_requests(
            monkeypatch, resp=_Resp(payload=_release("v1.3.0")))
        check_for_update("1.2.3", timeout_s=1.5)
        assert calls["timeout"] == 1.5
