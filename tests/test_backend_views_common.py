"""Tests for the shared backend-view scaffolding (ui/views/_backend_common)
and the PiShock API-key preservation contract.

Widget tests run headless against a real QApplication (same pattern as
test_motor_signal_chain_import). The settings test points FILE_PATH at
tmp_path so nothing touches the real AppData directory.
"""

import sys

import pytest

from PySide6.QtWidgets import QApplication, QComboBox

from settings.pishock import PiShockSettingsManager
from ui.views._backend_common import on_zone_type_changed, populate_zone_combo


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


class FakeController:
    def __init__(self):
        self.zones = {"Orifices": ["Booty", "Mouth"], "Penetrators": ["Shaft"]}
        self.sources = {"Orifices": ["GSpot"], "Penetrators": []}

    def get_detected_zones(self):
        return self.zones

    def get_sps_source_names_by_type(self):
        return self.sources


class TestPopulateZoneCombo:
    def test_orf_lists_zones_plus_sources(self, qapp):
        combo = QComboBox(); combo.setEditable(True)
        populate_zone_combo(FakeController(), combo, "Orf")
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items == ["Booty", "Mouth", "GSpot"]

    def test_pen_lists_pen_zones(self, qapp):
        combo = QComboBox(); combo.setEditable(True)
        populate_zone_combo(FakeController(), combo, "Pen")
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items == ["Shaft"]

    def test_current_text_survives_repopulate(self, qapp):
        # A hand-typed / not-yet-detected name must not be wiped by the
        # page-arrival repopulate.
        combo = QComboBox(); combo.setEditable(True)
        combo.setEditText("CustomZone")
        populate_zone_combo(FakeController(), combo, "Orf")
        assert combo.currentText() == "CustomZone"
        assert combo.findText("CustomZone") >= 0

    def test_populate_never_emits_signals(self, qapp):
        pushes = []
        combo = QComboBox(); combo.setEditable(True)
        combo.editTextChanged.connect(lambda _t: pushes.append(1))
        populate_zone_combo(FakeController(), combo, "Orf")
        assert pushes == []          # populating must not push config

    def test_facade_errors_degrade_to_empty(self, qapp):
        class Broken:
            def get_detected_zones(self):
                raise RuntimeError("boom")

            def get_sps_source_names_by_type(self):
                raise RuntimeError("boom")

        combo = QComboBox(); combo.setEditable(True)
        populate_zone_combo(Broken(), combo, "Orf")
        assert combo.count() == 0    # no crash, just empty


class TestZoneTypeChanged:
    def test_switch_clears_stale_name_and_repopulates(self, qapp):
        # Regression: switching Orf->Pen used to keep the orifice name in
        # the combo, so the config silently resolved to 0 forever.
        combo = QComboBox(); combo.setEditable(True)
        populate_zone_combo(FakeController(), combo, "Orf")
        combo.setEditText("Booty")
        pushes = []
        on_zone_type_changed(FakeController(), combo, "Pen",
                             lambda: pushes.append(combo.currentText()))
        assert combo.currentText() == ""             # stale name cleared
        items = [combo.itemText(i) for i in range(combo.count())]
        assert items == ["Shaft"]                    # new type's list
        assert pushes == [""]                        # pushed once, blank zone


class TestPiShockApiKeyPreserved:
    def _mgr(self, tmp_path):
        cls = type("TmpPiShock", (PiShockSettingsManager,),
                   {"FILE_PATH": tmp_path / "pishock.json"})
        return cls()

    def test_none_keeps_stored_key(self, tmp_path):
        m = self._mgr(tmp_path)
        m.set_cloud("user", "secret-key", "code", "name")
        # The UI never round-trips the key, so a later Apply submits None.
        m.set_cloud("user2", None, "code2", "name2")
        assert m.settings["apikey"] == "secret-key"  # kept
        assert m.settings["username"] == "user2"     # rest updated

    def test_empty_string_clears_key(self, tmp_path):
        m = self._mgr(tmp_path)
        m.set_cloud("user", "secret-key", "code", "name")
        m.set_cloud("user", "", "code", "name")      # explicit Clear key
        assert m.settings["apikey"] == ""
