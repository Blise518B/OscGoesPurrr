"""Tests for the self-updater (updater.py).

Network-free and filesystem-safe: every download test drives a fake
`requests` module, and nothing here ever spawns the swap helper or touches
a real exe.

The load-bearing property under test is that a download which fails
verification NEVER becomes an installed exe — a truncated stream, a wrong
digest or an oversized asset must leave no file behind and return None, so
apply_update is never reached with junk.
"""

import hashlib
import os

import pytest

import updater


# ---------------------------------------------------------------- helpers


class _FakeResponse:
    def __init__(self, body: bytes, status_code: int = 200, headers=None,
                 chunk: int = 7):
        self.status_code = status_code
        self.headers = headers if headers is not None else {
            "Content-Length": str(len(body))
        }
        self._body = body
        self._chunk = chunk

    def iter_content(self, chunk_size=None):
        step = chunk_size or self._chunk
        for i in range(0, len(self._body), step):
            yield self._body[i:i + step]


class _FakeRequests:
    """Stands in for the `requests` module inside updater."""

    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


@pytest.fixture
def fake_requests(monkeypatch):
    def _install(response):
        fake = _FakeRequests(response)
        monkeypatch.setattr(updater, "requests", fake)
        return fake
    return _install


def _pick_windows(assets):
    return updater.pick_exe_asset(assets, platform="win32")


def _apply_windows(downloaded, target):
    return updater.apply_update(downloaded, target, platform="win32")


def _asset(body: bytes, *, with_digest=True, size=None, url=None):
    return {
        "name": "OscGoesPurrr_0.9.1.exe",
        "url": url or "https://github.com/x/y/releases/download/v0.9.1/a.exe",
        "size": len(body) if size is None else size,
        "sha256": hashlib.sha256(body).hexdigest() if with_digest else None,
    }


# ---------------------------------------------------------------- asset pick


class TestPickExeAsset:
    def test_picks_the_windows_exe(self):
        got = _pick_windows([
            {"name": "source.zip",
             "browser_download_url": "https://x/source.zip", "size": 1},
            {"name": "OscGoesPurrr_0.9.1.exe",
             "browser_download_url": "https://x/OscGoesPurrr_0.9.1.exe",
             "size": 42},
        ])
        assert got["name"] == "OscGoesPurrr_0.9.1.exe"
        assert got["size"] == 42

    def test_picks_the_stable_asset_name_releases_carry(self):
        # release.bat uploads the exe as OscGoesPurrr-Windows.exe so the
        # README's releases/latest/download/... button always resolves.
        # Copies already installed must still find it.
        got = _pick_windows([{
            "name": "OscGoesPurrr-Windows.exe",
            "browser_download_url": "https://x/OscGoesPurrr-Windows.exe",
            "size": 7,
        }])
        assert got["name"] == "OscGoesPurrr-Windows.exe"

    def test_the_download_button_and_release_script_agree_on_the_name(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def read(*parts):
            with open(os.path.join(repo, *parts), encoding="utf-8") as fh:
                return fh.read()

        link = "releases/latest/download/OscGoesPurrr-Windows.exe"
        assert link in read("README.md")
        assert link in read("docs", "index.html")
        assert 'ASSET=dist\\OscGoesPurrr-Windows.exe' in read("tools", "release.bat")

    def test_parses_a_sha256_digest(self):
        digest = "a" * 64
        got = _pick_windows([{
            "name": "OscGoesPurrr.exe",
            "browser_download_url": "https://x/OscGoesPurrr.exe",
            "size": 1, "digest": f"sha256:{digest}",
        }])
        assert got["sha256"] == digest

    def test_ignores_a_digest_that_is_not_sha256(self):
        got = _pick_windows([{
            "name": "OscGoesPurrr.exe",
            "browser_download_url": "https://x/OscGoesPurrr.exe",
            "size": 1, "digest": "md5:abc",
        }])
        assert got["sha256"] is None

    def test_rejects_a_non_https_url(self):
        # A plain-http asset URL would be a downgrade on a binary we are
        # about to execute; no asset is better than that one.
        assert _pick_windows([{
            "name": "OscGoesPurrr.exe",
            "browser_download_url": "http://x/OscGoesPurrr.exe", "size": 1,
        }]) is None

    def test_ignores_someone_elses_exe(self):
        assert _pick_windows([{
            "name": "SomethingElse.exe",
            "browser_download_url": "https://x/SomethingElse.exe", "size": 1,
        }]) is None

    @pytest.mark.parametrize("assets", [None, [], "nope", [None], [{}]])
    def test_junk_asset_lists_yield_none(self, assets):
        assert _pick_windows(assets) is None


# ---------------------------------------------------------------- download


class TestDownloadUpdate:
    def test_verified_download_lands_on_disk(self, fake_requests):
        body = b"MZ" + b"payload" * 100
        fake_requests(_FakeResponse(body))
        path = updater.download_update(_asset(body))
        assert path is not None
        try:
            with open(path, "rb") as fh:
                assert fh.read() == body
        finally:
            os.unlink(path)

    def test_progress_is_reported_and_ends_at_the_total(self, fake_requests):
        body = b"x" * 50
        fake_requests(_FakeResponse(body, chunk=10))
        seen = []
        path = updater.download_update(
            _asset(body), progress=lambda d, t: seen.append((d, t)))
        assert path is not None
        os.unlink(path)
        assert seen[-1] == (50, 50)
        assert [d for d, _ in seen] == sorted(d for d, _ in seen)

    def test_a_raising_progress_callback_cannot_fail_the_download(
            self, fake_requests):
        body = b"x" * 20
        fake_requests(_FakeResponse(body))

        def _boom(done, total):
            raise RuntimeError("UI went away mid-download")

        path = updater.download_update(_asset(body), progress=_boom)
        assert path is not None
        os.unlink(path)

    def test_wrong_digest_is_rejected_and_leaves_nothing_behind(
            self, fake_requests):
        body = b"the real build"
        fake_requests(_FakeResponse(b"a tampered build"))
        asset = _asset(body)
        asset["size"] = len(b"a tampered build")   # size agrees, hash won't
        before = _temp_exe_count()
        assert updater.download_update(asset) is None
        assert _temp_exe_count() == before

    def test_truncated_stream_is_rejected(self, fake_requests):
        body = b"x" * 100
        fake_requests(_FakeResponse(b"x" * 40,
                                    headers={"Content-Length": "100"}))
        # Declared 100 bytes, delivered 40: a mid-download disconnect.
        assert updater.download_update(_asset(body, with_digest=False)) is None

    def test_empty_download_is_rejected(self, fake_requests):
        fake_requests(_FakeResponse(b"", headers={}))
        asset = _asset(b"", with_digest=False)
        asset["size"] = 0
        assert updater.download_update(asset) is None

    def test_oversized_declared_asset_is_refused_before_any_request(
            self, fake_requests):
        fake = fake_requests(_FakeResponse(b"x"))
        asset = _asset(b"x", with_digest=False, size=updater._MAX_ASSET_BYTES + 1)
        assert updater.download_update(asset) is None
        assert fake.calls == []          # never even asked

    def test_non_200_is_rejected(self, fake_requests):
        fake_requests(_FakeResponse(b"nope", status_code=404))
        assert updater.download_update(_asset(b"nope")) is None

    def test_network_error_collapses_to_none(self, fake_requests):
        fake_requests(OSError("network unreachable"))
        assert updater.download_update(_asset(b"x")) is None

    def test_missing_requests_collapses_to_none(self, monkeypatch):
        monkeypatch.setattr(updater, "requests", None)
        assert updater.download_update(_asset(b"x")) is None

    @pytest.mark.parametrize("asset", [None, {}, "nope", {"url": "ftp://x/a"}])
    def test_junk_assets_collapse_to_none(self, asset, fake_requests):
        fake_requests(_FakeResponse(b"x"))
        assert updater.download_update(asset) is None


def _temp_exe_count() -> int:
    import glob
    import tempfile
    return len(glob.glob(os.path.join(
        tempfile.gettempdir(), "OscGoesPurrr_update_*" + updater._DOWNLOAD_SUFFIX)))


# ---------------------------------------------------------------- apply


class TestApplyUpdate:
    @pytest.fixture(autouse=True)
    def _release_lock(self):
        """apply_update deliberately never closes its liveness lock -- in
        production the OS does it when the process exits. A test process
        does not exit, so release it here or the handle leaks into the next
        test as an unclosed-file warning (which pytest.ini turns into an
        error)."""
        yield
        handle, updater._lock_handle = updater._lock_handle, None
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass

    def test_refuses_a_missing_download(self, tmp_path):
        target = tmp_path / "OscGoesPurrr.exe"
        target.write_bytes(b"old")
        assert updater.apply_update(str(tmp_path / "nope.exe"),
                                    str(target)) is False
        assert target.read_bytes() == b"old"       # untouched

    def test_refuses_a_missing_target(self, tmp_path):
        new = tmp_path / "new.exe"
        new.write_bytes(b"new")
        assert updater.apply_update(str(new),
                                    str(tmp_path / "gone.exe")) is False

    def test_spawn_failure_is_reported_not_raised(self, tmp_path, monkeypatch):
        new = tmp_path / "new.exe"
        new.write_bytes(b"new")
        target = tmp_path / "OscGoesPurrr.exe"
        target.write_bytes(b"old")

        def _boom(*a, **k):
            raise OSError("cmd.exe missing")

        monkeypatch.setattr(updater.subprocess, "Popen", _boom)
        assert _apply_windows(str(new), str(target)) is False
        assert target.read_bytes() == b"old"

    def test_helper_gets_target_download_and_lock(self, tmp_path, monkeypatch):
        new = tmp_path / "new.exe"
        new.write_bytes(b"new")
        target = tmp_path / "OscGoesPurrr.exe"
        target.write_bytes(b"old")
        captured = {}

        def _fake_popen(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return object()

        monkeypatch.setattr(updater.subprocess, "Popen", _fake_popen)
        assert _apply_windows(str(new), str(target)) is True

        args = captured["args"]
        assert args[0] == "cmd.exe"
        assert args[2].endswith("apply_update.cmd")
        assert args[3] == os.path.abspath(str(target))
        assert args[4] == str(new)
        assert args[5].endswith("running.lock")
        # The helper must outlive us or it can never do the swap.
        assert captured["kwargs"]["close_fds"] is True
        # ...and the exe it relaunches must unpack its own files, not look
        # for ours (deleted by then).
        assert captured["kwargs"]["env"]["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
        with open(args[2], encoding="ascii") as fh:
            script = fh.read()
        assert "move /y" in script

    def test_the_lock_exists_and_is_still_held_when_we_return(
            self, tmp_path, monkeypatch):
        """The helper waits on this file, so it must outlive apply_update.

        A closed handle would let the helper delete it immediately and swap
        the exe out from under the still-running app -- which ends with two
        instances fighting over the OSC ports.
        """
        new = tmp_path / "new.exe"
        new.write_bytes(b"new")
        target = tmp_path / "OscGoesPurrr.exe"
        target.write_bytes(b"old")
        captured = {}
        monkeypatch.setattr(updater.subprocess, "Popen",
                            lambda args, **kw: captured.setdefault("args", args))
        assert _apply_windows(str(new), str(target)) is True

        lock = captured["args"][5]
        assert os.path.isfile(lock)
        assert updater._lock_handle is not None
        assert not updater._lock_handle.closed

    def test_the_script_never_swaps_while_the_lock_survives(self, tmp_path,
                                                            monkeypatch):
        """Pin the safety branch: if the lock is never released the helper
        writes a note and leaves the installed exe alone."""
        new = tmp_path / "new.exe"
        new.write_bytes(b"new")
        target = tmp_path / "OscGoesPurrr.exe"
        target.write_bytes(b"old")
        captured = {}
        monkeypatch.setattr(updater.subprocess, "Popen",
                            lambda args, **kw: captured.setdefault("args", args))
        _apply_windows(str(new), str(target))
        with open(captured["args"][2], encoding="ascii") as fh:
            script = fh.read()
        # The wait must come first and must be able to give up without
        # reaching the move.
        assert script.index(":waitloop") < script.index(":moveloop")
        assert "goto stillrunning" in script

        # Just the give-up branch: from its label to the next one. Slicing
        # to end-of-file would sweep in :relaunch and prove nothing.
        lines = script.splitlines()
        start = lines.index(":stillrunning") + 1
        end = next(i for i in range(start, len(lines))
                   if lines[i].startswith(":"))
        branch = "\n".join(lines[start:end])

        assert "move /y" not in branch      # the exe is left alone
        assert "start " not in branch       # and nothing is relaunched
        assert "goto cleanup" in branch     # it just tidies up and stops
        assert "update_failed.txt" in branch    # having said why


class TestIsSelfUpdatable:
    def test_false_from_a_source_checkout(self):
        # No sys.frozen under pytest, so this is the real answer for a
        # source tree: the UI must fall back to the releases link.
        assert updater.is_self_updatable() is False

    def test_false_for_a_onedir_build(self, monkeypatch):
        # frozen but no _MEIPASS = --onedir, where replacing one file
        # would leave the app half-updated.
        monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
        monkeypatch.setattr(updater.sys, "platform", "win32")
        monkeypatch.delattr(updater.sys, "_MEIPASS", raising=False)
        assert updater.is_self_updatable() is False

    def test_windows_needs_no_relaunch_from_the_app(self):
        # The swap helper starts the new exe itself.
        assert updater.relaunch_after_apply("win32") is False


# ---------------------------------------------------------------- Linux


class TestLinuxAppImage:
    """The Linux release is an AppImage: the asset, the swap and the
    restart differ from Windows; download and verification are shared."""

    _ASSETS = [
        {"name": "OscGoesPurrr-Windows.exe",
         "browser_download_url": "https://x/OscGoesPurrr-Windows.exe", "size": 9},
        {"name": "OscGoesPurrr-Linux-x86_64.AppImage.zsync",
         "browser_download_url": "https://x/a.zsync", "size": 2},
        {"name": "OscGoesPurrr-Linux-x86_64.AppImage",
         "browser_download_url": "https://x/OscGoesPurrr-Linux-x86_64.AppImage",
         "size": 5},
    ]

    def test_linux_picks_the_appimage_not_the_exe_or_zsync(self):
        got = updater.pick_exe_asset(self._ASSETS, platform="linux")
        assert got["name"] == "OscGoesPurrr-Linux-x86_64.AppImage"
        assert got["size"] == 5

    def test_windows_still_picks_the_exe_from_the_same_release(self):
        assert _pick_windows(self._ASSETS)["name"] == "OscGoesPurrr-Windows.exe"

    def test_a_release_without_the_appimage_yet_has_no_linux_asset(self):
        # release.bat publishes the exe first; the AppImage arrives from
        # GitHub Actions minutes later.
        assert updater.pick_exe_asset(self._ASSETS[:1], platform="linux") is None

    def test_the_download_button_and_workflow_agree_on_the_name(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        def read(*parts):
            with open(os.path.join(repo, *parts), encoding="utf-8") as fh:
                return fh.read()

        name = "OscGoesPurrr-Linux-x86_64.AppImage"
        assert f"releases/latest/download/{name}" in read("README.md")
        assert f"releases/latest/download/{name}" in read("docs", "index.html")
        assert f"dist/{name}" in read(".github", "workflows", "linux.yml")
        assert 'OUT_NAME="$APP-Linux-$ARCH.AppImage"' in read("tools", "build_linux.sh")

    def test_swap_replaces_the_appimage_and_keeps_it_runnable(self, tmp_path):
        new = tmp_path / "download.AppImage"
        new.write_bytes(b"new")
        target = tmp_path / "OscGoesPurrr.AppImage"
        target.write_bytes(b"old")
        os.chmod(target, 0o755)
        assert updater.apply_update(str(new), str(target), platform="linux") is True
        assert target.read_bytes() == b"new"
        assert not new.exists()                         # download tidied up
        assert not (tmp_path / "OscGoesPurrr.AppImage.update").exists()
        if os.name == "posix":
            assert os.stat(target).st_mode & 0o111 == 0o111

    def test_a_failed_swap_leaves_the_old_appimage(self, tmp_path, monkeypatch):
        new = tmp_path / "download.AppImage"
        new.write_bytes(b"new")
        target = tmp_path / "OscGoesPurrr.AppImage"
        target.write_bytes(b"old")

        def _boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(updater.os, "replace", _boom)
        assert updater.apply_update(str(new), str(target), platform="linux") is False
        assert target.read_bytes() == b"old"
        assert not (tmp_path / "OscGoesPurrr.AppImage.update").exists()
        assert new.exists()                             # still there to retry

    def test_linux_spawns_no_helper(self, tmp_path, monkeypatch):
        new = tmp_path / "download.AppImage"
        new.write_bytes(b"new")
        target = tmp_path / "OscGoesPurrr.AppImage"
        target.write_bytes(b"old")

        def _no_spawn(*a, **k):
            raise AssertionError("Linux swaps in place; nothing to spawn")

        monkeypatch.setattr(updater.subprocess, "Popen", _no_spawn)
        assert updater.apply_update(str(new), str(target), platform="linux") is True

    def test_linux_restarts_itself_after_the_swap(self):
        assert updater.relaunch_after_apply("linux") is True

    def test_an_appimage_in_a_writable_folder_can_update(self, tmp_path, monkeypatch):
        appimage = tmp_path / "OscGoesPurrr.AppImage"
        appimage.write_bytes(b"x")
        monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
        monkeypatch.setattr(updater.sys, "platform", "linux")
        monkeypatch.setenv("APPIMAGE", str(appimage))
        assert updater.is_self_updatable() is True
        assert updater.current_exe_path() == os.path.abspath(str(appimage))

    def test_frozen_linux_outside_an_appimage_cannot(self, monkeypatch):
        monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
        monkeypatch.setattr(updater.sys, "platform", "linux")
        monkeypatch.delenv("APPIMAGE", raising=False)
        assert updater.is_self_updatable() is False
