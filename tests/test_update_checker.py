"""Tests for the sealed GitHub update checker (update_checker.py).

Never hits the network: `requests` is monkeypatched inside the module
with stubs whose .get returns canned responses (or raises).
"""

from types import SimpleNamespace

import pytest

import update_checker
from update_checker import _parse_version, _pre_release, check_for_update, compare_versions


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
                        "url": "https://x/rel", "asset": None}
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

    def test_an_alpha_is_offered_its_release(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v0.14.0")))
        info = check_for_update("0.14.0-alpha.1")
        assert info is not None and info["available"] is True

    def test_an_alpha_is_not_offered_the_release_before_it(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v0.13.0")))
        info = check_for_update("0.14.0-alpha.1")
        assert info is not None and info["available"] is False

    def test_a_release_is_never_offered_its_own_alpha(self, monkeypatch):
        _install_requests(monkeypatch, resp=_Resp(payload=_release("v0.14.0-alpha.1")))
        info = check_for_update("0.14.0")
        assert info is not None and info["available"] is False
        assert info["latest"] == "0.14.0-alpha.1"


class TestPreReleases:
    @pytest.mark.parametrize("older, newer", [
        ("0.14.0-alpha.1", "0.14.0"),
        ("0.14.0-alpha.1", "0.14.0-alpha.2"),
        ("0.14.0-alpha.9", "0.14.0-beta"),
        ("0.14.0-beta.3", "0.14.0-rc.1"),
        ("0.14.0-rc.2", "v0.14.0"),
        ("0.13.0", "0.14.0-alpha.1"),
    ])
    def test_stages_come_before_their_release(self, older, newer):
        assert compare_versions(older, newer) == -1
        assert compare_versions(newer, older) == 1

    @pytest.mark.parametrize("build, version", [
        ("0.13.0-dev(3)", "0.13.0"),                  # a branch build is its release
        ("0.14.0-alpha.1-dev(3)", "0.14.0-alpha.1"),  # ... or its alpha
        ("0.13.0-alpha(2)", "0.13.0"),                # a branch called alpha is no stage
    ])
    def test_branch_suffixes_take_no_part(self, build, version):
        assert compare_versions(build, version) == 0

    def test_the_numeric_core_is_unchanged(self):
        assert _parse_version("v0.14.0-alpha.1") == (0, 14, 0)
        assert _pre_release("0.14.0-rc.2") == (2, 2)

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


class TestShouldShowPopup:
    """The update window: launch check only, and not for the one version
    the user said "don't remind me" about."""

    AVAILABLE = {"available": True, "latest": "0.10.1", "url": "u", "asset": None}

    def test_launch_check_with_a_newer_release_pops_up(self):
        assert update_checker.should_show_popup(self.AVAILABLE, False, "") is True

    def test_the_skipped_version_stays_quiet(self):
        assert update_checker.should_show_popup(self.AVAILABLE, False, "0.10.1") is False

    def test_a_later_release_pops_up_again(self):
        newer = dict(self.AVAILABLE, latest="0.11.0")
        assert update_checker.should_show_popup(newer, False, "0.10.1") is True

    def test_manual_check_never_pops_up(self):
        assert update_checker.should_show_popup(self.AVAILABLE, True, "") is False

    @pytest.mark.parametrize("info", [None, {"available": False, "latest": "0.10.0"}])
    def test_no_update_no_popup(self, info):
        assert update_checker.should_show_popup(info, False, "") is False
