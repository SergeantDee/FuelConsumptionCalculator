from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fuel_consumption_calculator.calculations.tank_depletion_engine import allocate_tank_depletion
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankSounding
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionAllocationEvent
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService


START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(hours: float, tank_ids: tuple[int, ...]) -> TankConsumptionAllocationEvent:
    return TankConsumptionAllocationEvent(None, 1, START + timedelta(hours=hours), tank_ids)


def _interval(hours: float, **deductions: float) -> FuelDepletionInterval:
    return FuelDepletionInterval(START, START + timedelta(hours=hours), {"ULSFO": deductions.get("ULSFO", 0.0), "VLSFO": deductions.get("VLSFO", 0.0), "MDO": deductions.get("MDO", 0.0)})


def test_equal_split_allocation_preserves_each_fuel_total():
    intervals = [_interval(24, VLSFO=6.0, ULSFO=3.0)]
    allocations, issues = allocate_tank_depletion(intervals, [_event(0, (1, 2, 3, 4))], {1: "VLSFO", 2: "VLSFO", 3: "VLSFO", 4: "ULSFO"}, START, START + timedelta(hours=24))
    assert allocations[1] == allocations[2] == allocations[3] == pytest.approx(2.0)
    assert allocations[4] == pytest.approx(3.0)
    assert sum(allocations.values()) == pytest.approx(9.0)
    assert not issues


def test_unknown_or_incompatible_tank_fuel_never_receives_other_fuel():
    allocations, issues = allocate_tank_depletion([_interval(12, VLSFO=4.0)], [_event(0, (1, 2, 3))], {1: "VLSFO", 2: "ULSFO", 3: None}, START, START + timedelta(hours=12))
    assert allocations == {1: 4.0, 2: 0.0, 3: 0.0}
    assert not issues


def test_no_active_tank_reports_issue_without_allocating():
    allocations, issues = allocate_tank_depletion([_interval(12, VLSFO=4.0)], [], {1: "VLSFO"}, START, START + timedelta(hours=12))
    assert allocations[1] == 0.0
    assert issues[1] == "No active VLSFO consumption tank selected"


def test_unknown_authoritative_depletion_remains_unknown():
    interval = FuelDepletionInterval(START, START + timedelta(hours=12), {"ULSFO": 0.0, "VLSFO": None, "MDO": 0.0})
    allocations, issues = allocate_tank_depletion([interval], [_event(0, (1,))], {1: "VLSFO"}, START, START + timedelta(hours=12))
    assert allocations[1] is None
    assert issues[1] == "Authoritative VLSFO depletion is unavailable"


def test_effective_dated_selection_splits_interval_without_gap_or_overlap():
    allocations, _ = allocate_tank_depletion(
        [_interval(24, VLSFO=6.0)], [_event(0, (1, 2)), _event(12, (2, 3))],
        {1: "VLSFO", 2: "VLSFO", 3: "VLSFO"}, START, START + timedelta(hours=24),
    )
    assert allocations == {1: pytest.approx(1.5), 2: pytest.approx(3.0), 3: pytest.approx(1.5)}
    assert sum(allocations.values()) == pytest.approx(6.0)


def test_latest_mass_sounding_reanchors_prediction_and_missing_mass_stays_unknown(tmp_path):
    database = Database(tmp_path / "forecast.db"); database.initialize()
    VesselRepository(database).save_active("Vessel", "1234567")
    repository = FuelTankRepository(database); service = FuelTankService(repository)
    batch = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO", "VLSFO", 950))
    tank = service.create_tank(FuelTank(None, 1, "Tank", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    repository.save_sounding(TankSounding(None, tank.id, (START - timedelta(hours=12)).isoformat(), "SOUNDING", 1, 0, None, 10, calculated_mass_mt=100, fuel_batch_id=batch.id))
    repository.save_sounding(TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 9, calculated_mass_mt=80, fuel_batch_id=batch.id))
    service.apply_consumption_tanks(1, [tank.id], START)
    forecast = service.predict_tank_rob_at(1, START + timedelta(hours=12), [_interval(24, VLSFO=24.0)])[0]
    assert forecast.anchor_mass_mt == 80
    assert forecast.allocated_depletion_mt == pytest.approx(12.0)
    assert forecast.predicted_mass_mt == pytest.approx(68.0)
    repository.save_sounding(TankSounding(None, tank.id, (START + timedelta(hours=13)).isoformat(), "SOUNDING", 1, 0, None, 8, calculated_mass_mt=None, fuel_batch_id=batch.id))
    unavailable = service.predict_tank_rob_at(1, START + timedelta(hours=14), [_interval(24, VLSFO=24.0)])[0]
    assert unavailable.predicted_mass_mt is None
    assert "no mass snapshot" in unavailable.issue


def test_depletion_is_not_clamped_below_zero(tmp_path):
    database = Database(tmp_path / "negative.db"); database.initialize(); VesselRepository(database).save_active("Vessel", "1234567")
    repository = FuelTankRepository(database); service = FuelTankService(repository)
    batch = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO", "VLSFO", 950))
    tank = service.create_tank(FuelTank(None, 1, "Tank", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    repository.save_sounding(TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=1, fuel_batch_id=batch.id))
    service.apply_consumption_tanks(1, [tank.id], START)
    forecast = service.predict_tank_rob_at(1, START + timedelta(hours=12), [_interval(12, VLSFO=2.0)])[0]
    assert forecast.predicted_mass_mt == pytest.approx(-1.0)
