from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.vessel_service import VesselService
from fuel_consumption_calculator.ui.pages.fuel_tanks_page import (
    FUEL_COLORS,
    FuelBatchDialog,
    FuelTanksPage,
    TankCard,
    TankDetailsDialog,
    TankFuelBatchDialog,
    TankLevelWidget,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def services(tmp_path):
    database = Database(tmp_path / "fuel-batch-ui.db")
    database.initialize()
    vessel_service = VesselService(VesselRepository(database))
    vessel = vessel_service.configure_active_vessel("Test Vessel", "1234567")
    tank_service = FuelTankService(FuelTankRepository(database))
    tank = tank_service.create_tank(
        FuelTank(None, vessel.id, "HFO DEEP TK 1P", "BUNKER", 500, "SOUNDING")
    )
    return vessel_service, tank_service, vessel, tank


def _batch(service, vessel_id, fuel_type="VLSFO", name="Batch 26-08", density=950):
    return service.create_fuel_batch(
        FuelBatch(None, vessel_id, name, fuel_type, density)
    )


def test_fuel_batch_action_depends_on_tank_selection(services, qapp):
    vessel_service, tank_service, _vessel, tank = services
    page = FuelTanksPage(vessel_service, tank_service)
    page.refresh()

    assert not page.fuel_batch_button.isEnabled()
    page._select_tank(tank.id)
    assert page.fuel_batch_button.isEnabled()


def test_batch_dialog_lists_vessel_batches_and_create_edit(services, qapp):
    _vessel_service, tank_service, vessel, tank = services
    existing = _batch(tank_service, vessel.id, "ULSFO", "Initial", 920)
    dialog = TankFuelBatchDialog(tank_service, tank)
    assert dialog.batch_table.rowCount() == 1
    assert dialog.batch_table.item(0, 0).text() == "Initial"

    create = FuelBatchDialog(tank_service, vessel.id)
    create.batch_name_input.setText("Created")
    create.fuel_type_input.setCurrentText("MDO")
    create.density_input.setValue(860)
    create._save()
    created = next(
        item for item in tank_service.list_fuel_batches(vessel.id)
        if item.batch_name == "Created"
    )
    assert created.batch_name == "Created" and created.fuel_type == "MDO"

    edit = FuelBatchDialog(tank_service, vessel.id, existing)
    edit.batch_name_input.setText("Edited")
    edit.density_input.setValue(925)
    edit._save()
    assert tank_service.get_fuel_batch(existing.id).batch_name == "Edited"


def test_assign_and_clear_batch_through_dialog(services, qapp, monkeypatch):
    _vessel_service, tank_service, vessel, tank = services
    batch = _batch(tank_service, vessel.id)
    dialog = TankFuelBatchDialog(tank_service, tank)
    dialog.batch_table.selectRow(0)
    dialog._assign()
    assert tank_service.get_tank(tank.id).current_fuel_batch_id == batch.id
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog._clear()
    assert tank_service.get_tank(tank.id).current_fuel_batch_id is None
    assert tank_service.get_fuel_batch(batch.id) == batch


@pytest.mark.parametrize("fuel_type", ["ULSFO", "VLSFO", "MDO"])
def test_tank_card_fuel_indicator_and_gauge_color(fuel_type, services, qapp):
    _vessel_service, _tank_service, _vessel, tank = services
    card = TankCard(tank, fuel_type, "B26-08", None, "deep")

    assert card.findChild(QLabel, "fuelIndicator").text() == f"● {fuel_type}"
    assert card.findChild(TankLevelWidget)._color.name() == FUEL_COLORS[fuel_type]


def test_unassigned_card_and_tank_details_show_no_mass_and_batch_data(services, qapp):
    vessel_service, tank_service, vessel, tank = services
    unassigned = TankCard(tank, None, None, None, "deep")
    assert unassigned.findChild(QLabel, "fuelIndicator").text() == "FUEL --"
    assert "MT --" in {label.text() for label in unassigned.findChildren(QLabel)}

    batch = _batch(tank_service, vessel.id, "VLSFO", "B26-08", 950)
    tank_service.assign_fuel_batch_to_tank(tank.id, batch.id)
    details = TankDetailsDialog(tank_service, tank_service.get_tank(tank.id), "VLSFO", "B26-08", None)
    assert details.current_fuel_value.text() == "VLSFO"
    assert details.current_batch_value.text() == "B26-08"
    assert details.density_value.text() == "950 kg/m3"

    page = FuelTanksPage(vessel_service, tank_service)
    page.refresh()
    assigned_card = next(card for card in page.tank_cards if card._tank_id == tank.id)
    assert "MT --" in {label.text() for label in assigned_card.findChildren(QLabel)}
