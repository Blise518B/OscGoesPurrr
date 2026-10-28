"""ogp:// links reach the OGP that is already running."""

import os
import sys
import tempfile
import threading
import uuid

import link_handoff
import link_scheme


def _address():
    if sys.platform == "win32":
        return rf"\\.\pipe\ogp-test-{uuid.uuid4().hex}"
    return os.path.join(tempfile.gettempdir(), f"ogp-test-{uuid.uuid4().hex}.sock")


def test_link_from_argv():
    assert link_handoff.link_from_argv(["ogp.exe"]) is None
    assert link_handoff.link_from_argv(["ogp.exe", "--x", "ogp://friend/abc"]) == "ogp://friend/abc"
    assert link_handoff.link_from_argv(["ogp.exe", "OGP://Friend/abc"]) == "OGP://Friend/abc"


def test_nobody_listening_means_start_normally():
    assert not link_handoff.send_to_running("ogp://friend/x", _address())


def test_a_link_reaches_the_running_ogp():
    addr = _address()
    got, heard = [], threading.Event()
    listener = link_handoff.LinkListener(lambda link: (got.append(link), heard.set()), addr)
    assert listener.start()
    try:
        assert link_handoff.send_to_running("not-a-link", addr)       # ignored
        assert link_handoff.send_to_running("ogp:ping", addr)         # ignored
        assert link_handoff.send_to_running("ogp://friend/abc.def", addr)
        assert heard.wait(5)
        assert got == ["ogp://friend/abc.def"]
    finally:
        listener.stop()
    assert not link_handoff.send_to_running("ogp://friend/x", addr)


def test_registered_commands_pass_the_link_through():
    assert link_scheme.windows_command(r"C:\Apps\OGP.exe") == r'"C:\Apps\OGP.exe" "%1"'
    entry = link_scheme.desktop_entry("/home/me/OGP.AppImage")
    assert 'Exec="/home/me/OGP.AppImage" %u' in entry
    assert "MimeType=x-scheme-handler/ogp;" in entry


def test_a_source_run_registers_nothing():
    if not getattr(sys, "frozen", False) and not os.environ.get("APPIMAGE"):
        assert link_scheme.register() is False


def test_a_second_start_finds_the_open_ogp_and_can_bring_it_forward():
    addr = _address()
    assert not link_handoff.another_running(addr, settle_s=0)       # none open
    got, heard = [], threading.Event()
    listener = link_handoff.LinkListener(lambda link: (got.append(link), heard.set()), addr)
    assert listener.start()
    try:
        assert link_handoff.another_running(addr, settle_s=0.05)
        assert link_handoff.send_to_running(link_handoff.SHOW, addr)
        assert heard.wait(5)
        assert got == [link_handoff.SHOW]                          # handed on, as "show"
    finally:
        listener.stop()
    assert not link_handoff.another_running(addr, settle_s=0)       # closed: not open


def test_show_only_brings_the_window_forward():
    import queue
    from controllers.friends_facade import FriendsFacade

    class UI:
        shown = 0

        def show_window(self):
            UI.shown += 1

        def select_view(self, name):
            raise AssertionError("SHOW must not open a page")

    class Host(FriendsFacade):
        pass

    h = Host.__new__(Host)
    h.ui = UI()
    h.thread_queue = queue.Queue()
    h.friends_open_link(link_handoff.SHOW)
    assert UI.shown == 1
