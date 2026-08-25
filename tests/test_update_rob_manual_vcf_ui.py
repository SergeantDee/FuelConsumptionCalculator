from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.pages.fuel_tank_operational_dialogs import UpdateTankROBDialog
from fuel_consumption_calculator.ui.pages.fuel_tanks_page import FuelBatchDialog, FuelTanksPage, TankDetailsDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def configured_tank(tmp_path):
    database = Database(tmp_path / "manual-vcf-ui.db")
    database.initialize()
    vessel_service = VesselService(VesselRepository(database))
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    service = FuelTankService(FuelTankRepository(database))
    tank = service.create_tank(FuelTank(None, vessel.id, "HFO DEEP TK 1P", "BUNKER", 500, "SOUNDING"))
    service.replace_calibration_points(tank.id, [
        TankCalibrationPoint(None, tank.id, 0, None, 0, 0),
        TankCalibrationPoint(None, tank.id, 100, None, 0, 200),
    ])
    return vessel_service, service, vessel, tank


def _save_dialog(dialog: UpdateTankROBDialog, vcf: str = ""):
    dialog.reading.setText("80"); dialog.trim.setText("0"); dialog.manual_vcf.setText(vcf)
    dialog.update_preview(); dialog.save()


def test_update_rob_blank_inputs_keep_preview_neutral(configured_tank, qapp):
    _vessel_service, service, _vessel, tank = configured_tank
    dialog = UpdateTankROBDialog(service, tank)

    assert dialog.preview.text() == "Enter reading and trim to calculate volume."
    assert "could not convert string to float" not in dialog.preview.text()
    dialog.temperature.setText("")
    dialog.manual_vcf.setText("")
    dialog.update_preview()
    assert "could not convert string to float" not in dialog.preview.text()


def test_update_rob_save_requires_reading_with_operator_message(configured_tank, qapp, monkeypatch):
    _vessel_service, service, _vessel, tank = configured_tank
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args[2]))
    dialog = UpdateTankROBDialog(service, tank)
    dialog.save()

    assert warnings == ["Reading is required."]


def test_update_rob_invalid_nonempty_value_uses_clean_validation_message(configured_tank, qapp):
    _vessel_service, service, _vessel, tank = configured_tank
    dialog = UpdateTankROBDialog(service, tank)
    dialog.reading.setText("not-a-number")
    dialog.update_preview()

    assert dialog.preview.text() == "Reading must be numeric."


def test_density_editor_rejects_kg_per_litre_style_entry(configured_tank, qapp, monkeypatch):
    _vessel_service, service, vessel, _tank = configured_tank
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args[2]))
    dialog = FuelBatchDialog(service, vessel.id)
    dialog.batch_name_input.setText("Bad density")
    dialog.density_input.setValue(0.978)
    dialog._save()

    assert warnings == ["Density must be entered in kg/m³ (for example 978, not 0.978)."]
    assert service.list_fuel_batches(vessel.id) == []


def test_physical_only_update_rob_saves_without_mass_snapshot(configured_tank, qapp):
    _vessel_service, service, _vessel, tank = configured_tank
    dialog = UpdateTankROBDialog(service, tank)
    _save_dialog(dialog)

    saved = service.get_latest_sounding(tank.id)
    assert saved.calculated_volume_m3 == 160
    assert (saved.manual_vcf, saved.standard_volume_15_m3, saved.calculated_density_kg_m3, saved.calculated_mass_mt) == (None, None, None, None)


def test_batch_without_manual_vcf_still_saves_physical_only(configured_tank, qapp):
    _vessel_service, service, vessel, tank = configured_tank
    batch = service.create_fuel_batch(FuelBatch(None, vessel.id, "TEST-VLSFO", "VLSFO", 978))
    tank = service.assign_fuel_batch_to_tank(tank.id, batch.id)
    dialog = UpdateTankROBDialog(service, tank)
    _save_dialog(dialog)

    saved = service.get_latest_sounding(tank.id)
    assert saved.fuel_batch_id == batch.id
    assert (saved.manual_vcf, saved.standard_volume_15_m3, saved.calculated_density_kg_m3, saved.calculated_mass_mt) == (None, None, None, None)


def test_manual_vcf_update_rob_saves_full_snapshot_and_refreshes_ui(configured_tank, qapp):
    vessel_service, service, vessel, tank = configured_tank
    batch = service.create_fuel_batch(FuelBatch(None, vessel.id, "TEST-VLSFO", "VLSFO", 978))
    tank = service.assign_fuel_batch_to_tank(tank.id, batch.id)
    dialog = UpdateTankROBDialog(service, tank)
    _save_dialog(dialog, "0.985")

    saved = service.get_latest_sounding(tank.id)
    assert saved.calculated_volume_m3 == 160
    assert saved.manual_vcf == pytest.approx(0.985)
    assert saved.standard_volume_15_m3 == pytest.approx(157.6)
    assert saved.calculated_density_kg_m3 == 978
    assert saved.calculated_mass_mt == pytest.approx(154.1328)
    assert "Calculated Mass: 154.133 MT" in dialog.preview.text()

    page = FuelTanksPage(vessel_service, service); page.refresh()
    card = page.tank_cards[0]
    assert "154.133 MT" in {label.text() for label in card.findChildren(type(dialog.preview))}
    details = TankDetailsDialog(service, service.get_tank(tank.id), "VLSFO", batch.batch_name, saved)
    assert details.current_fuel_value.text() == "VLSFO"
    assert any("0.98500" in label.text() for label in details.findChildren(type(dialog.preview)))
    assert page.history_table.item(0, 7).text() == "0.98500"
    assert page.history_table.item(0, 8).text() == "157.60"
    assert page.history_table.item(0, 9).text() == "154.13"


def test_card_double_click_refresh_does_not_access_deleted_card(configured_tank, qapp):
    vessel_service, service, _vessel, _tank = configured_tank
    page = FuelTanksPage(vessel_service, service); page.show(); page.refresh(); qapp.processEvents()
    card = page.tank_cards[0]
    card.activated.disconnect()
    card.activated.connect(lambda _tank_id: page.refresh())

    QTest.mouseDClick(card, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert page.tank_cards
