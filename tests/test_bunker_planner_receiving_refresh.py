from __future__ import annotations

import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from fuel_consumption_calculator.domain.bunker import BunkerReceivingTankPlan
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.calculations.port_bunker_projection import PortBunkerProjectionRow
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.bunker_service import BunkerService
from fuel_consumption_calculator.ui.pages.bunker_page import BunkerPage


class _VesselService:
    def __init__(self):
        self.vessel = type("Vessel", (), {"id": 1, "name": "Test Vessel", "imo": "1234567"})()

    def get_active_vessel(self):
        return self.vessel


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def planner(tmp_path, qapp):
    database = Database(tmp_path / "planner-refresh.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO vessels VALUES (1, 'Test Vessel', '1234567', 'x', 'x')")
    tanks = FuelTankRepository(database)
    tank = tanks.save_tank(FuelTank(None, 1, "HFO Deep Tank 1 PORT", "BUNKER", 1515.4, "SOUNDING", True))
    batch = tanks.save_fuel_batch(FuelBatch(None, 1, "Incoming VLSFO", "VLSFO", 978))
    service = BunkerService(BunkerRepository(database))
    event = ScheduleEvent(1, 1, 1, "Singapore", "PORT", datetime(2026, 1, 2), None, "test", "V", None, "created", "updated")
    vessel_service = _VesselService()
    vessel_service.vessel = None
    page = BunkerPage(vessel_service, service, object(), object(), object(), object())
    vessel_service.vessel = _VesselService().vessel
    page._events = [event]
    page.event_combo.addItem("#1 Singapore")
    page._capacity_inputs["VLSFO"].setValue(6000)
    plan = service.build_plan(vessel_id=1, event=event, quantities={"ULSFO": 0, "VLSFO": 0, "MDO": 0})
    return page, service, plan, tank, batch


def test_receiving_plan_refreshes_selected_capacity_and_tank_max_lift(planner):
    page, service, plan, tank, batch = planner
    service.save_receiving_tank_plan(plan, [BunkerReceivingTankPlan(tank.id, 160, 90)], batch.id, .985)

    page._update_lift_limits()

    assert page._capacity_field_labels["VLSFO"].text() == "Receiving Capacity"
    assert page._vlsfo_capacity_label.text() == "1515.400 m³"
    assert page._vlsfo_capacity_label.text() != "6000.00 MT"
    assert "1 tank selected" in page.receiving_summary_label.text()
    assert page._max_lift_labels["VLSFO"].text() != "—"
    assert page._max_lift_labels["ULSFO"].text() == "0.00 MT"


def test_incomplete_receiving_basis_has_specific_reason_and_use_max_is_safe(planner):
    page, service, plan, tank, batch = planner
    service.save_receiving_tank_plan(plan, [BunkerReceivingTankPlan(tank.id, 160, 90)], batch.id, None)

    page._update_lift_limits()

    assert "Incoming bunker temperature required" in page.receiving_summary_label.text()
    assert page._max_lift_labels["VLSFO"].text() == "—"
    page._use_max_lift()  # Regression: incomplete Max Lift must not pass None to QDoubleSpinBox.
    assert page._planned_inputs["VLSFO"].value() == 0


def test_unknown_projected_arrival_is_not_treated_as_zero(planner):
    page, service, plan, tank, batch = planner
    service.save_receiving_tank_plan(plan, [BunkerReceivingTankPlan(tank.id, None, 90)], batch.id, .985)

    page._update_lift_limits()

    assert "Projected arrival unavailable for 1 selected tank" in page.receiving_summary_label.text()
    assert page._max_lift_labels["VLSFO"].text() == "—"


def test_receiving_plan_save_refreshes_the_current_bunker_event(planner, monkeypatch):
    page, _service, _plan, _tank, _batch = planner
    refreshed = []
    monkeypatch.setattr(page, "_refresh_projection", lambda vessel_id: refreshed.append(vessel_id))
    monkeypatch.setattr(page, "_selection_changed", lambda: refreshed.append("selection"))

    page._refresh_after_receiving_plan_save(1)

    assert refreshed == [1, "selection"]
    assert page.status_label.text() == "Receiving tank plan saved as DRAFT."


def test_port_bunker_details_builds_separate_aggregate_and_bunker_tank_summary(planner, monkeypatch):
    page, _service, _plan, _tank, _batch = planner
    event = page._events[0]
    row = PortBunkerProjectionRow(
        event, "FUTURE", {"ULSFO": 10.0, "VLSFO": 20.0, "MDO": 30.0}, "ACTUAL ANCHORED",
        {"ULSFO": None, "VLSFO": None, "MDO": None}, {"ULSFO": 0.0, "VLSFO": 0.0, "MDO": 0.0},
        "NO PLAN", {"ULSFO": 0.0, "VLSFO": 1.0, "MDO": 0.0}, {"ULSFO": 10.0, "VLSFO": 19.0, "MDO": 30.0},
    )
    page.projection_model.set_rows([row])
    monkeypatch.setattr("fuel_consumption_calculator.ui.pages.bunker_page.QDialog.exec", lambda _dialog: 0)

    page._open_port_details(page.projection_model.index(0, 0))

    assert page.plan_panel.parent() is page.content
