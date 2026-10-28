"""An avatar's name from VRChat's own OSC files (vrchat_avatars): read
only, only the top of the file, and nothing for an id that has none."""
import json

import vrchat_avatars

AID = "avtr_191b82bf-05d5-404d-acc2-ae19064a493c"


def _vrchat(tmp_path, user, aid, data, bom=True):
    folder = tmp_path / "OSC" / user / "Avatars"
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2)
    (folder / f"{aid}.json").write_bytes(
        (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    return folder / f"{aid}.json"


def test_the_name_from_vrchats_file(tmp_path):
    params = [{"name": f"Param{i}", "input": {"address": f"/a/{i}", "type": "Float"}}
              for i in range(3000)]       # far longer than the bit that is read
    _vrchat(tmp_path, "usr_1", AID, {"id": AID, "name": "Moth \"Girl\"",
                                     "hash": 1, "parameters": params})
    assert vrchat_avatars.avatar_name(AID, [tmp_path]) == 'Moth "Girl"'


def test_nothing_without_a_file_or_a_name(tmp_path):
    assert vrchat_avatars.avatar_name(AID, [tmp_path]) == ""
    _vrchat(tmp_path, "usr_1", AID, {"id": AID, "parameters": [{"name": "Hoodie"}]})
    assert vrchat_avatars.avatar_name(AID, [tmp_path]) == ""    # never a parameter's


def test_only_real_avatar_ids_are_looked_up(tmp_path):
    for junk in ("", "local:sdk-123", "avtr_*", "../avtr_191b82bf", "avtr_191b82bf/../x"):
        assert vrchat_avatars.avatar_name(junk, [tmp_path]) == ""


def test_with_two_accounts_the_newest_file_wins(tmp_path):
    import os
    old = _vrchat(tmp_path, "usr_a", AID, {"id": AID, "name": "Old"})
    _vrchat(tmp_path, "usr_b", AID, {"id": AID, "name": "New"}, bom=False)
    os.utime(old, (1, 1))
    assert vrchat_avatars.avatar_name(AID, [tmp_path]) == "New"


def test_every_parameter_the_avatar_has(tmp_path):
    params = [{"name": "bOSC/v2/VestFront/0/self"}, {"name": "owo_suit_Arm_L"},
              {"name": 5}, "junk", {"input": {}}]
    path = _vrchat(tmp_path, "usr_1", AID, {"id": AID, "name": "A", "parameters": params})
    assert vrchat_avatars.avatar_parameters(AID, [tmp_path]) == {
        "bOSC/v2/VestFront/0/self", "owo_suit_Arm_L"}
    assert vrchat_avatars.avatar_parameters("not an id", [tmp_path]) is None
    path.write_text("{ broken", encoding="utf-8")
    import os
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))   # a changed file is read again
    assert vrchat_avatars.avatar_parameters(AID, [tmp_path]) is None
