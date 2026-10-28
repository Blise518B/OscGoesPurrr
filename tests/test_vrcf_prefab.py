"""The VRCFury menu prefab must keep matching the app.

`docs/unity/OscGoesPurrr-VRCFury.unitypackage` is what an avatar owner drags
in to get the OGP menu. It is built by `tools/build_vrcf_prefab.py`, which
needs Unity and also tests the package on avatars there -- so these tests
only read the committed package: it adds exactly the parameters the app
listens to, with the types the app reads, unsynced, under names VRCFury
leaves alone; the menu uses all of them; and its GUIDs are the pinned ones,
without which importing a newer package next to an older one duplicates
every asset instead of updating it.

A failure here after changing an OGP_* parameter means: change
`docs/unity/OGP_MenuInstaller.cs` to match and rebuild the package.
"""

import hashlib
import re
import tarfile
from pathlib import Path

import pytest

import constants
from config_manager import ModeManager

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "docs" / "unity" / "OscGoesPurrr-VRCFury.unitypackage"
INSTALLER = REPO / "docs" / "unity" / "OGP_MenuInstaller.cs"
ICONS = REPO / "docs" / "unity" / "icons"
ROOT = "Assets/OGP"   # the package's own folder, nothing outside it
DIR = f"{ROOT}/Menu"   # the parts the prefabs use
# Three prefabs, alone at the top: (prefab, its assets' suffix)
VARIANTS = {"Both": ("OscGoesPurrr Menu", ""),
            "Self": ("OscGoesPurrr Menu (Self)", "_Self"),
            "Friends": ("OscGoesPurrr Menu (Friends)", "_Friends")}

# VRCExpressionParameters.ValueType: Int 0, Float 1, Bool 2.
SELF_PARAMETERS = {
    constants.OGP_STRENGTH_PARAMETER: 1,
    constants.OGP_MODE_PARAMETER: 0,
    constants.OGP_OFF_PARAMETER: 2,
    constants.OGP_SLEEP_PARAMETER: 2,
    constants.OGP_TEST_PARAMETER: 2,
}
FRIEND_PARAMETERS = {
    constants.OGP_FRIEND_LEVEL_PARAMETER: 1,
    **{name: 2 for name in constants.OGP_FRIEND_TOY_PARAMETERS},
    constants.OGP_FRIEND_MODE_PARAMETER: 0,
    constants.OGP_FRIEND_SPEED_PARAMETER: 1,
    constants.OGP_FRIEND_RANGE_PARAMETER: 1,
    constants.OGP_FRIEND_OVERRIDE_PARAMETER: 2,
    constants.OGP_FRIEND_STOP_TOYS_PARAMETER: 2,
    constants.OGP_FRIEND_STRENGTH_PARAMETER: 1,
    constants.OGP_FRIEND_SHOCK_PARAMETER: 2,
    constants.OGP_FRIEND_VIBRATE_PARAMETER: 2,
    constants.OGP_FRIEND_BEEP_PARAMETER: 2,
    constants.OGP_FRIEND_STOP_SHOCK_PARAMETER: 2,
    constants.OGP_FRIEND_SHOCK_STRENGTH_PARAMETER: 1,
    constants.OGP_FRIEND_SHOCK_LENGTH_PARAMETER: 1,
    constants.OGP_FRIEND_WARNING_PARAMETER: 2,
    **{name: 2 for name in constants.OGP_FRIEND_SHOCKER_PARAMETERS},
    constants.OGP_BOTH_LEVEL_PARAMETER: 1,
    constants.OGP_BOTH_MODE_PARAMETER: 0,
    constants.OGP_BOTH_SPEED_PARAMETER: 1,
    constants.OGP_BOTH_STOP_PARAMETER: 2,
    constants.OGP_BOTH_SHOCK_PARAMETER: 2,
    constants.OGP_BOTH_VIBRATE_PARAMETER: 2,
    constants.OGP_BOTH_STRENGTH_PARAMETER: 1,
    constants.OGP_BOTH_LENGTH_PARAMETER: 1,
}
APP_PARAMETERS = {**SELF_PARAMETERS, **FRIEND_PARAMETERS}
PARAMETERS_OF = {"Both": APP_PARAMETERS, "Self": SELF_PARAMETERS, "Friends": FRIEND_PARAMETERS}
# Which toys / Which shockers start all on: the menu reaches everything.
ALL_ON = (*constants.OGP_FRIEND_TOY_PARAMETERS, *constants.OGP_FRIEND_SHOCKER_PARAMETERS)
# The nested menus, each an asset of its own in Menu/, shared by the prefabs.
SUBMENUS = ("Modes", "Friends", "FriendToys", "FriendAuto", "FriendWhichToys",
            "FriendShockers", "FriendWhichShockers", "FriendBoth", "BothAuto")


@pytest.fixture(scope="module")
def package():
    """{asset path: (guid, asset bytes or None for a folder)}"""
    entries = {}
    with tarfile.open(PACKAGE, "r:gz") as tar:
        members = {m.name: m for m in tar.getmembers()}
        for name, member in members.items():
            if not name.endswith("/pathname"):
                continue
            guid = name.split("/")[0]
            path = tar.extractfile(member).read().decode("utf-8").splitlines()[0]
            asset = members.get(f"{guid}/asset")
            entries[path] = (guid, tar.extractfile(asset).read() if asset else None)
    return entries


def text(package, path):
    return package[path][1].decode("utf-8")


def test_holds_the_three_prefabs_and_their_assets(package):
    icons = sorted(f.stem for f in ICONS.glob("*.png"))
    assert icons, "no icons in docs/unity/icons -- run tools/make_menu_icons.py"
    assert set(package) == {
        ROOT,
        DIR,
        f"{DIR}/Icons",
        f"{DIR}/OGP_MenuIcon.png",
        *(f"{DIR}/Icons/{name}.png" for name in icons),
        *(f"{ROOT}/{prefab}.prefab" for prefab, _ in VARIANTS.values()),
        *(f"{DIR}/OGP_VRCF_{kind}{suffix}.asset" for _, suffix in VARIANTS.values()
          for kind in ("Parameters", "Controls", "Menu")),
        *(f"{DIR}/OGP_VRCF_{key}.asset" for key in SUBMENUS),
    }


def test_the_icons_are_the_drawn_ones(package):
    for f in ICONS.glob("*.png"):
        assert package[f"{DIR}/Icons/{f.name}"][1] == f.read_bytes(), f.name


def test_guids_are_pinned(package):
    for path, (guid, _) in package.items():
        assert guid == hashlib.md5(f"OscGoesPurrr:{path}".encode()).hexdigest(), path


@pytest.mark.parametrize("variant", VARIANTS)
def test_parameters_are_the_apps_unsynced_and_unsaved(package, variant):
    suffix = VARIANTS[variant][1]
    found = {m["name"]: m for m in re.finditer(
        r"- name: (?P<name>\S+)\n\s+valueType: (?P<type>\d)\n"
        r"\s+saved: (?P<saved>\d)\n\s+defaultValue: (?P<default>\S+)\n"
        r"\s+networkSynced: (?P<synced>\d)",
        text(package, f"{DIR}/OGP_VRCF_Parameters{suffix}.asset"))}
    wanted = PARAMETERS_OF[variant]
    assert set(found) == set(wanted)
    for name, value_type in wanted.items():
        assert int(found[name]["type"]) == value_type, name
        assert found[name]["saved"] == "0", name
        assert found[name]["synced"] == "0", name
    for name in ALL_ON:
        if name in wanted:
            assert float(found[name]["default"]) == 1.0, name
    if constants.OGP_STRENGTH_PARAMETER in wanted:
        strength = float(found[constants.OGP_STRENGTH_PARAMETER]["default"])
        assert strength == pytest.approx(ModeManager.DEFAULT_STRENGTH)


@pytest.mark.parametrize("variant", VARIANTS)
def test_vrcfury_keeps_the_names(package, variant):
    # VRCFury renames every parameter its globalParams don't match, and OSC
    # reaches a parameter by its name only.
    prefab = VARIANTS[variant][0]
    block = re.search(r"globalParams:\n((?:\s+- .*\n)+)", text(package, f"{ROOT}/{prefab}.prefab"))
    patterns = [line.strip()[2:] for line in block.group(1).splitlines()]
    for name in PARAMETERS_OF[variant]:
        assert any(name == p or (p.endswith("*") and name.startswith(p[:-1]))
                   for p in patterns), name


def test_menu_uses_every_parameter(package):
    controls = "".join(text(package, f"{DIR}/OGP_VRCF_{key}.asset")
                       for key in ("Controls",) + SUBMENUS)
    for name in APP_PARAMETERS:
        assert f"name: {name}\n" in controls, name


def test_auto_modes_are_the_apps_in_its_order(package):
    # OGP/Friend/Mode and OGP/Both/Mode n is friend_patterns.WAVES[n - 1].
    import friend_patterns
    for key in ("FriendAuto", "BothAuto"):
        names = re.findall(r"- name: (.+)\n", text(package, f"{DIR}/OGP_VRCF_{key}.asset"))
        assert names == [friend_patterns.LABELS[w] for w in friend_patterns.WAVES], key


def test_installer_names_the_apps_parameters():
    # The package is built from the installer's table; a renamed parameter
    # must change both.
    names = set(re.findall(r'const string \w+Param = "([^"]+)";',
                           INSTALLER.read_text(encoding="utf-8")))
    assert names == set(APP_PARAMETERS)
