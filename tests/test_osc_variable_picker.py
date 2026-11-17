"""The Add Variable picker's filter chips (ui/osc_variable_picker.py): a
lit chip hides its group, Show everything turns them all off, the chips
are one app setting for every picker, a mapped parameter is never hidden,
a search finds hidden ones under "Hidden by filters", and the Shockers'
picker keeps PhysBone states."""

import sys

import pytest
from PySide6.QtWidgets import QApplication

import param_filters as pf
from ui.osc_variable_picker import OscVariablePicker


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class FakeSettings:
    """The controller's get_app_setting / set_app_setting."""

    def __init__(self, saved=None):
        self.store = {} if saved is None else {pf.SETTING_KEY: saved}
        self.writes = 0

    def get_app_setting(self, key, default=None):
        return self.store.get(key, default)

    def set_app_setting(self, key, value):
        self.store[key] = value
        self.writes += 1


PARAMS = {"AFK": False, "Go/Float": 0.0, "FT/v2/JawOpen": 0.25, "MPB_L_IsGrabbed": True,
          "Cheek_L_Angle": 0.5, "OGB/Orf/Pussy/PenSelfNewRoot": 0.0, "VF10_Outfit": 1,
          "Hat": True, "TailWag": 0.75}


def make(qapp, picks=None, **kw):
    picks = [] if picks is None else picks
    dlg = OscVariablePicker(None, picks.append, **kw)
    dlg.refresh(dict(PARAMS))
    return dlg


def visible_chips(dlg):
    return {k for k, b in dlg.chips.items() if not b.isHidden()}


def test_the_defaults_hide_the_well_known_groups(qapp):
    dlg = make(qapp)
    assert dlg.listed() == {"shown": ["Hat", "TailWag", "VF10_Outfit"], "hidden": []}
    # a chip per group this avatar has, with its count; lit = hidden
    assert visible_chips(dlg) == {pf.VRCHAT, pf.GOGO, pf.FACE, pf.PHYSBONES, pf.SPS,
                                  pf.VF_TOGGLES}
    assert dlg.chips[pf.PHYSBONES].text() == "PhysBone states · 2"
    assert dlg.chips[pf.FACE].isChecked()
    assert not dlg.chips[pf.VF_TOGGLES].isChecked()          # shown by default
    assert dlg.show_all_btn.isEnabled()
    dlg.deleteLater()


def test_a_chip_hides_its_group_and_is_remembered(qapp):
    settings = FakeSettings()
    dlg = make(qapp, settings=settings)
    dlg.chips[pf.VF_TOGGLES].setChecked(True)
    assert "VF10_Outfit" not in dlg.listed()["shown"]
    dlg.chips[pf.FACE].setChecked(False)
    assert "FT/v2/JawOpen" in dlg.listed()["shown"]
    saved = settings.store[pf.SETTING_KEY]
    assert saved[pf.VF_TOGGLES] is True and saved[pf.FACE] is False
    assert set(saved) == set(pf.GROUP_KEYS)
    dlg.deleteLater()
    # the next picker -- any picker -- opens with the same chips
    again = make(qapp, settings=settings)
    assert again.chips[pf.VF_TOGGLES].isChecked() and not again.chips[pf.FACE].isChecked()
    assert "VF10_Outfit" not in again.listed()["shown"]
    again.deleteLater()


def test_show_everything_turns_every_chip_off(qapp):
    settings = FakeSettings()
    dlg = make(qapp, settings=settings)
    dlg.show_all_btn.click()
    assert dlg.listed()["shown"] == sorted(PARAMS)
    assert not any(b.isChecked() for b in dlg.chips.values())
    assert not dlg.show_all_btn.isEnabled()
    assert not any(settings.store[pf.SETTING_KEY].values())
    dlg.deleteLater()


def test_a_mapped_parameter_is_never_hidden(qapp):
    dlg = make(qapp, mapped=["MPB_L_IsGrabbed", "OGB/Orf/*"])
    shown = dlg.listed()["shown"]
    assert "MPB_L_IsGrabbed" in shown and "OGB/Orf/Pussy/PenSelfNewRoot" in shown
    assert "Cheek_L_Angle" not in shown
    dlg.deleteLater()


def test_a_search_lists_hidden_matches_under_their_own_header(qapp):
    picks = []
    dlg = make(qapp, picks)
    dlg.search.setText("an")
    dlg.refresh(dict(PARAMS))
    assert dlg.listed() == {"shown": [], "hidden": ["Cheek_L_Angle"]}
    head, row = dlg.tree.topLevelItem(0), dlg.tree.topLevelItem(1)
    assert head.text(0) == "Hidden by filters (1)"
    dlg._pick_item(head)                     # the header picks nothing
    assert picks == []
    dlg._pick_item(row)                      # a hidden one can still be picked
    assert picks == ["Cheek_L_Angle"]
    dlg.deleteLater()


def test_the_shockers_picker_keeps_physbone_states(qapp):
    settings = FakeSettings({pf.PHYSBONES: True})
    dlg = make(qapp, settings=settings, keep=(pf.PHYSBONES,))
    assert pf.PHYSBONES not in dlg.chips
    assert {"MPB_L_IsGrabbed", "Cheek_L_Angle"} <= set(dlg.listed()["shown"])
    dlg.show_everything()
    # the other pickers still hide them: this one never showed that chip
    assert settings.store[pf.SETTING_KEY][pf.PHYSBONES] is True
    dlg.deleteLater()


def test_the_shockers_picker_lists_shockosc_first_under_its_heading(qapp):
    settings = FakeSettings({pf.SHOCKOSC: True})
    dlg = OscVariablePicker(None, lambda _n: None, settings=settings,
                            keep=(pf.PHYSBONES,), first=(pf.SHOCKOSC,))
    dlg.refresh({**PARAMS, "ShockOsc/Collar": False, "ShockOsc/Tail_Stretch": 0.0})
    listed = dlg.listed()
    assert listed["first"] == ["ShockOsc/Collar", "ShockOsc/Tail_Stretch"]
    assert dlg.headings() == ["ShockOSC (2)", "Everything else"]
    assert dlg.tree.topLevelItem(1).text(0) == "ShockOsc/Collar"     # right under it
    assert "MPB_L_IsGrabbed" in listed["shown"]
    assert pf.SHOCKOSC not in dlg.chips            # never hidden here: no chip
    dlg.deleteLater()
    # the toys' pickers hide them by default -- a search still finds them
    other = OscVariablePicker(None, lambda _n: None)
    other.refresh({**PARAMS, "ShockOsc/Collar": False})
    assert "first" not in other.listed()
    assert "ShockOsc/Collar" not in other.listed()["shown"]
    assert other.chips[pf.SHOCKOSC].isChecked()
    other.search.setText("collar")
    other.refresh({**PARAMS, "ShockOsc/Collar": False})
    assert other.listed()["hidden"] == ["ShockOsc/Collar"]
    other.deleteLater()


def test_values_follow_without_rebuilding(qapp):
    dlg = make(qapp)
    row = dlg.tree.topLevelItem(1)
    assert (row.text(0), row.text(1)) == ("TailWag", "0.75")
    dlg.refresh({**PARAMS, "TailWag": 0.5})
    assert dlg.tree.topLevelItem(1) is row and row.text(1) == "0.50"
    dlg.deleteLater()


def test_what_the_empty_list_says(qapp):
    dlg = OscVariablePicker(None, lambda _n: None)
    dlg.refresh({})
    assert dlg.empty_lbl.text() == "No avatar parameters seen yet."
    assert dlg.chip_row.isHidden()
    dlg.refresh({"AFK": False, "Go/Float": 0.0})
    assert dlg.empty_lbl.text().startswith("The filters hide every parameter here.")
    dlg.search.setText("zzz")
    dlg.refresh({"AFK": False})
    assert dlg.empty_lbl.text() == "Nothing matches that search."
    dlg.deleteLater()


def test_without_settings_nothing_is_saved_and_nothing_breaks(qapp):
    class Broken:
        def get_app_setting(self, key, default=None):
            raise RuntimeError("no settings here")

        def set_app_setting(self, key, value):
            raise RuntimeError("no settings here")

    for settings in (None, Broken()):
        dlg = make(qapp, settings=settings)
        assert dlg.hidden_groups() == pf.default_hidden()
        dlg.chips[pf.FACE].setChecked(False)
        assert "FT/v2/JawOpen" in dlg.listed()["shown"]
        dlg.deleteLater()


def test_picking_by_name_and_by_hand(qapp):
    picks = []
    dlg = make(qapp, picks)
    dlg.tree.topLevelItem(0).setSelected(True)
    dlg._add_selected()
    dlg.manual_entry.setText("  Contact/Mine  ")
    dlg._submit_manual()
    assert picks == ["Hat", "Contact/Mine"]
    dlg.deleteLater()
