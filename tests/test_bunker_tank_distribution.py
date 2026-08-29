from datetime import datetime, timezone

import pytest

from fuel_consumption_calculator.domain.bunker import BunkerReceivingTankPlan, BunkerTankReceipt
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.bunker_service import BunkerService


@pytest.fixture
def setup(tmp_path):
    database = Database(tmp_path / "distribution.db"); database.initialize()
    with database.connect() as connection: connection.execute("INSERT INTO vessels VALUES (1,'V','1234567','x','x')")
    tanks = FuelTankRepository(database); batch = tanks.save_fuel_batch(FuelBatch(None, 1, "Incoming", "VLSFO", 978))
    first = tanks.save_tank(FuelTank(None, 1, "1P", "BUNKER", 500, "SOUNDING", True, current_fuel_batch_id=batch.id))
    second = tanks.save_tank(FuelTank(None, 1, "2P", "BUNKER", 500, "SOUNDING", True, current_fuel_batch_id=batch.id))
    event = ScheduleEvent(1, 1, 1, "SG", "PORT", datetime(2026, 1, 2, tzinfo=timezone.utc), None, "x", "x", None, "x", "x")
    service = BunkerService(BunkerRepository(database)); plan = service.build_plan(vessel_id=1, event=event, quantities={"ULSFO": 0, "VLSFO": 300, "MDO": 0}); service.save_plan(plan); service.confirm_plan(plan)
    service.save_receiving_tank_plan(plan, [BunkerReceivingTankPlan(first.id, 0, 90), BunkerReceivingTankPlan(second.id, 0, 90)], batch.id, .985)
    return service, plan, first, second


def test_complete_distribution_conserves_confirmed_aggregate(setup):
    service, plan, first, second = setup
    service.save_tank_receipts(plan, [BunkerTankReceipt(first.id, "VLSFO", 100, ""), BunkerTankReceipt(second.id, "VLSFO", 200, "")])
    receipts = service.list_tank_receipts(plan)
    assert sum(item.quantity_mt for item in receipts) == pytest.approx(plan.quantity_for("VLSFO"))
    assert {item.tank_id for item in receipts} == {first.id, second.id}


@pytest.mark.parametrize("amount", [299, 301])
def test_incomplete_or_excess_distribution_is_rejected(setup, amount):
    service, plan, first, _second = setup
    with pytest.raises(ValueError, match="equal"):
        service.save_tank_receipts(plan, [BunkerTankReceipt(first.id, "VLSFO", amount, "")])


def test_nonselected_or_incompatible_tank_is_rejected(setup):
    service, plan, first, _second = setup
    with pytest.raises(ValueError, match="fuel"):
        service.save_tank_receipts(plan, [BunkerTankReceipt(first.id, "ULSFO", 300, "")])
