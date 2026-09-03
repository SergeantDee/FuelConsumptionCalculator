from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankSounding
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.ui.pages.bunker_page import ReceivingTanksDialog
from fuel_consumption_calculator.ui.pages.fuel_tanks_page import VESSEL_TANK_SET, VESSEL_TANK_CAPACITIES, VesselTankSetDialog


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def receiving_setup(tmp_path):
    database = Database(tmp_path / "receiving-dialog.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO vessels VALUES (1, 'Test Vessel', '1234567', 'x', 'x')")
    tanks = FuelTankRepository(database)
    tank = tanks.save_tank(FuelTank(None, 1, "HFO Deep Tank 1P", "BUNKER", 500, "SOUNDING", True))
    tanks.save_sounding(TankSounding(None, tank.id, "2026-01-01T00:00:00+00:00", "SOUNDING", 1, 0, None, 160))
    batch = tanks.save_fuel_batch(FuelBatch(None, 1, "Incoming VLSFO", "VLSFO", 978))
    service = BunkerService(BunkerRepository(database))
    event = ScheduleEvent(
        id=1, vessel_id=1, sequence_number=1, port="Singapore", event_type="PORT",
        arrival_at=datetime(2026, 1, 1), departure_at=None, source="test",
        source_vessel_name="Test Vessel", source_from_date=None, created_at="created", updated_at="updated",
    )
    return tanks, service, service.build_plan(vessel_id=1, event=event, quantities={"ULSFO": 0, "VLSFO": 0, "MDO": 0}), batch, tank


def test_receiving_dialog_builds_real_tank_rows_and_preserves_plan_inputs(receiving_setup, qapp):
    _tanks, service, plan, batch, tank = receiving_setup
    dialog = ReceivingTanksDialog(service, plan, 90)

    assert dialog.objectName() == "receivingTanksDialog"
    assert dialog.table.horizontalHeaderItem(2).text() == "Capacity (m³)"
    assert dialog.table.horizontalHeaderItem(3).text() == "Latest Actual (m³)"
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == tank.name
    assert dialog.table.item(0, 2).text() == "500.000"
    assert dialog.table.item(0, 3).text() == "160.000"
    assert dialog.table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert dialog.batch_input.count() == 2
    assert dialog.fuel_label is not None
    assert dialog.use_latest_button.text() == "Use Latest Actual"
    assert dialog.use_estimate_button.text() == "Use Estimate"
    assert dialog.save_button.text() == "Save Receiving Plan"
    assert dialog.cancel_button.text() == "Cancel"

    dialog.table.cellWidget(0, 0).setChecked(True)
    dialog.apply_target_input.setValue(95)
    dialog._apply_target_to_selected()
    assert dialog.table.cellWidget(0, 6).value() == 95

    dialog.table.cellWidget(0, 0).setChecked(True)
    dialog.table.cellWidget(0, 4).setText("175.5")
    dialog.table.cellWidget(0, 4).setProperty("manual_override", True)
    dialog.batch_input.setCurrentIndex(1)
    dialog.vcf_input.setText("0.985")
    dialog._save()

    saved = service.list_receiving_tank_plan(plan)
    assert saved[0].tank_id == tank.id
    assert saved[0].projected_arrival_volume_m3 == pytest.approx(175.5)
    assert service.load_incoming_fuel_snapshot(plan).fuel_batch_id == batch.id


def test_receiving_dialog_reads_existing_tank_capacity_after_tank_set_update(tmp_path, qapp):
    database = Database(tmp_path / "receiving-updated-capacity.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO vessels VALUES (1, 'Test Vessel', '1234567', 'x', 'x')")
    repository = FuelTankRepository(database)
    existing = repository.save_tank(FuelTank(None, 1, "HFO Deep Tank 1 PORT", "BUNKER", 500, "SOUNDING", True))
    tank_service = FuelTankService(repository)
    loader = VesselTankSetDialog(tank_service, 1)
    for row, (name, _, _) in enumerate(VESSEL_TANK_SET):
        loader.row_controls[row][0].setChecked(name == "HFO DEEP TK 1P")
    assert loader.create_selected_tanks() == (0, 1, 0)

    service = BunkerService(BunkerRepository(database))
    event = ScheduleEvent(
        id=1, vessel_id=1, sequence_number=1, port="Singapore", event_type="PORT",
        arrival_at=datetime(2026, 1, 1), departure_at=None, source="test",
        source_vessel_name="Test Vessel", source_from_date=None, created_at="created", updated_at="updated",
    )
    plan = service.build_plan(vessel_id=1, event=event, quantities={"ULSFO": 0, "VLSFO": 0, "MDO": 0})
    dialog = ReceivingTanksDialog(service, plan, 90)

    assert repository.get_tank(existing.id).capacity_m3 == VESSEL_TANK_CAPACITIES["HFO DEEP TK 1P"]
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 2).text() == "1515.400"
