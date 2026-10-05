"""The website demo must keep telling the truth about the app.

`docs/assets/ogp-chain.js` and `docs/assets/ogp-accent.js` are JavaScript
ports of the signal chain (motor_router / mixer / the shipped preset, plus
the summary strings of the chain UI) and of accent_shift. The demo on the
website runs them, so a change to the Python that is not ported makes the
site show something the app no longer does.

These tests run a reduced version of the checks in `tools/site_ports/`:
the real Python writes a small reference (a few seconds of signal per
scenario: default preset and modified configs, touch, Sleep, Off, strength,
anti-stuck, live edits, uneven ticks), and node replays it through the
ports. The full set is `tools/site_ports/gen_reference.py` and
`check_accent.py` -- see the README there.

Everything runs in subprocesses with the home directory pointed at a
temporary folder (the generators redirect it again themselves), so nothing
here can touch the real profile, and nothing is written into the repo.
Skipped when `node` is not on PATH.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools" / "site_ports"
CHAIN_JS = REPO / "docs" / "assets" / "ogp-chain.js"
ACCENT_JS = REPO / "docs" / "assets" / "ogp-accent.js"

# Largest allowed |JS - Python| on any signal. The ports agree to ~1e-14;
# the slack only covers exp()/sin() differing in the last bit between
# JavaScript engines and C runtimes.
TOL = 1e-9

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
_TIMEOUT_S = 180


def _child_env(home: Path) -> dict:
    """The environment for every subprocess: a throwaway profile, no
    bytecode caches, and the house green (constants.py would otherwise
    pick up a colour chosen in the developer's own settings)."""
    env = dict(os.environ)
    env["USERPROFILE"] = str(home)
    env["HOME"] = str(home)
    env["APPDATA"] = str(home / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    env["XDG_CONFIG_HOME"] = str(home / ".config")      # Linux: settings root
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["OGP_UI_ACCENT"] = "default"
    return env


def _run(cmd, home: Path):
    """Run a console program with no window; (exit code, decoded output)."""
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=str(REPO), env=_child_env(home),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=_TIMEOUT_S,
        creationflags=_NO_WINDOW)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def _tail(output: str, lines: int = 40) -> str:
    return "\n".join(output.splitlines()[-lines:])


def _result(output: str) -> dict:
    """The machine-readable last line the node checks print."""
    rows = [ln for ln in output.splitlines() if ln.startswith("RESULT ")]
    assert rows, "the check printed no RESULT line:\n" + _tail(output)
    return json.loads(rows[-1][len("RESULT "):])


def _mutated_copy(source: Path, dest_dir: Path, old: bytes, new: bytes) -> Path:
    """A copy of a port with ONE constant changed -- never the real file."""
    data = source.read_bytes()
    assert data.count(old) == 1, (
        f"{source.name} no longer contains {old!r} exactly once; pick "
        "another constant for this self-test")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source.name
    dest.write_bytes(data.replace(old, new))
    return dest


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def node() -> str:
    exe = shutil.which("node")
    if exe is None:
        pytest.skip("node is not on PATH; the site-port checks need it")
    return exe


@pytest.fixture(scope="module")
def workdir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("site_ports")


@pytest.fixture(scope="module")
def home(workdir) -> Path:
    path = workdir / "home"
    path.mkdir()
    return path


@pytest.fixture(scope="module")
def chain_reference(node, workdir, home) -> Path:
    """The real MotorRouter's output for the quick scenario set."""
    out = workdir / "chain"
    code, output = _run(
        [sys.executable, "-B", TOOLS / "gen_reference.py",
         "--quick", "--no-check", "--out", out], home)
    assert code == 0, "gen_reference.py failed:\n" + _tail(output)
    ref = out / "reference.json"
    assert ref.is_file()
    return ref


@pytest.fixture(scope="module")
def chain_check(node, chain_reference, home):
    """(exit code, RESULT dict, output) of the chain port's check."""
    assert CHAIN_JS.is_file(), f"the port is missing: {CHAIN_JS}"
    code, output = _run([node, TOOLS / "check.js", chain_reference], home)
    return code, _result(output), output


@pytest.fixture(scope="module")
def accent_reference(node, workdir, home) -> Path:
    """accent_shift.py's output for the quick colour set."""
    out = workdir / "accent"
    code, output = _run(
        [sys.executable, "-B", TOOLS / "check_accent.py",
         "--quick", "--no-check", "--out", out], home)
    assert code == 0, "check_accent.py failed:\n" + _tail(output)
    ref = out / "accent_reference.json"
    assert ref.is_file()
    return ref


@pytest.fixture(scope="module")
def accent_check(node, accent_reference, home):
    assert ACCENT_JS.is_file(), f"the port is missing: {ACCENT_JS}"
    code, output = _run(
        [node, TOOLS / "check_accent.js", accent_reference], home)
    return code, _result(output), output


# ------------------------------------------------------------ signal chain

class TestChainPort:
    def test_every_signal_matches_the_router(self, chain_check):
        code, result, output = chain_check
        assert code == 0 and result["ok"], (
            "docs/assets/ogp-chain.js no longer matches the Python signal "
            "chain -- port the change (see tools/site_ports/README.md):\n"
            + _tail(output))
        assert result["worst"] is not None and result["worst"] <= TOL
        assert result["discrete_mismatches"] == 0

    def test_the_reference_is_not_trivially_small(self, chain_check):
        # A reference that lost its scenarios would pass everything.
        _code, result, _output = chain_check
        assert result["scenarios"] >= 10
        assert result["runs"] >= 20
        assert result["ticks"] >= 5000

    def test_defaults_match_the_shipped_preset(self, chain_check):
        _code, result, output = chain_check
        assert result["defaults_ok"], _tail(output, 80)

    def test_simulator_waves_match(self, chain_check):
        _code, result, output = chain_check
        assert result["sim_samples"] >= 1000
        assert result["sim_worst"] is not None and result["sim_worst"] <= TOL, \
            _tail(output)

    def test_summary_strings_match_the_chain_ui(self, chain_check):
        _code, result, output = chain_check
        assert result["summary_lines"] >= 40
        assert result["stage_subtitles"] >= 40
        assert result["summary_lines_bad"] == 0, _tail(output)
        assert result["stage_subtitles_bad"] == 0, _tail(output)

    def test_a_drifted_constant_is_caught(self, node, chain_reference,
                                          workdir, home):
        # The guard itself: one constant off in a COPY of the port must
        # fail the check, or a green run above proves nothing.
        copy = _mutated_copy(
            CHAIN_JS, workdir / "mutated",
            b"var SPEED_NORMALIZATION = 0.75;",
            b"var SPEED_NORMALIZATION = 0.76;")
        code, output = _run(
            [node, TOOLS / "check.js", chain_reference, "--js", copy], home)
        result = _result(output)
        assert code == 1 and not result["ok"], _tail(output)
        assert result["worst"] is None or result["worst"] > TOL

    def test_drifted_defaults_are_caught(self, node, chain_reference,
                                         workdir, home):
        copy = _mutated_copy(
            CHAIN_JS, workdir / "mutated_defaults",
            b"depth_gain: 0.38,", b"depth_gain: 0.39,")
        code, output = _run(
            [node, TOOLS / "check.js", chain_reference, "--js", copy], home)
        result = _result(output)
        assert code == 1 and not result["defaults_ok"], _tail(output)


# ------------------------------------------------------------------ colour

class TestAccentPort:
    def test_every_colour_matches_accent_shift(self, accent_check):
        code, result, output = accent_check
        assert code == 0 and result["ok"], (
            "docs/assets/ogp-accent.js no longer matches accent_shift.py "
            "-- port the change (see tools/site_ports/README.md):\n"
            + _tail(output))
        assert result["strings_bad"] == 0
        assert result["strings"] >= 2000
        assert result["token_cases"] >= 250

    def test_hue_numbers_agree(self, accent_check):
        # Not bit-identical by nature (atan2/pow round differently across
        # runtimes), but far inside anything a colour could show.
        _code, result, output = accent_check
        for key in ("worst_hue_diff", "worst_delta_diff"):
            assert result[key] is not None and result[key] <= TOL, \
                _tail(output)

    def test_a_drifted_constant_is_caught(self, node, accent_reference,
                                          workdir, home):
        copy = _mutated_copy(
            ACCENT_JS, workdir / "mutated_accent",
            b"var KEEP_CHROMA = 0.8;", b"var KEEP_CHROMA = 0.7;")
        code, output = _run(
            [node, TOOLS / "check_accent.js", accent_reference,
             "--js", copy], home)
        result = _result(output)
        assert code == 1 and not result["ok"], _tail(output)
        assert result["strings_bad"] > 0


# ------------------------------------------------------- where things land

class TestNothingLeaks:
    def test_app_imports_landed_in_the_scratch_profile(self, chain_reference):
        # Importing the app's settings package creates its AppData folder.
        # It must have been created under the reference folder's fake
        # home -- which proves the redirect is still in front of the
        # import, not that we got lucky.
        home = chain_reference.parent / "_fakehome"
        roaming = (home / "AppData" / "Roaming" if sys.platform == "win32"
                   else home / ".config")
        assert roaming.is_dir() and any(roaming.iterdir())

    @pytest.mark.parametrize("script", ["gen_reference.py", "check_accent.py"])
    def test_a_reference_is_refused_inside_the_repo(self, script, tmp_path):
        # The chain reference is 43 MB; it must never be able to land in
        # the working tree. No node needed: the script stops before work.
        target = TOOLS / "_must_not_exist"
        code, output = _run(
            [sys.executable, "-B", TOOLS / script,
             "--quick", "--no-check", "--out", target], tmp_path)
        assert code == 2, _tail(output)
        assert "refusing" in output
        assert not target.exists()
