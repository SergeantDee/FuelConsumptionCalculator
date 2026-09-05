from datetime import datetime, timedelta, timezone

import pytest

from fuel_consumption_calculator.calculations.tank_consumption_plan_engine import forecast_tank_consumption_plan
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionPlan, TankConsumptionPlanPhase, TankConsumptionPlanPhaseTank
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService


START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _plan(*phases):
    return TankConsumptionPlan(1, 1, "VLSFO", "ACTIVE", START, tuple(TankConsumptionPlanPhase(None, index + 1, tuple(TankConsumptionPlanPhaseTank(tank, share) for tank, share in phase)) for index, phase in enumerate(phases)))


def _interval(hours, amount):
    return FuelDepletionInterval(START, START + timedelta(hours=hours), {"VLSFO": amount})


def test_mid_interval_depletion_switches_remainder_to_next_phase():
    forecast = forecast_tank_consumption_plan(_plan(((1, 1.0),), ((2, 1.0),)), [_interval(10, 10)], {1: 3.0, 2: 20.0}, START + timedelta(hours=10))
    assert forecast.depletion_at_utc[1] == START + timedelta(hours=3)
    assert forecast.phase_starts_utc[2] == START + timedelta(hours=3)
    assert forecast.tank_masses_mt == pytest.approx({1: 0.0, 2: 13.0})
    assert forecast.unallocated_consumption_mt == pytest.approx(0.0)


def test_first_depletion_ends_multi_tank_phase_without_redistribution():
    forecast = forecast_tank_consumption_plan(_plan(((1, .5), (2, .5)), ((3, 1.0),)), [_interval(20, 20)], {1: 10.0, 2: 30.0, 3: 20.0}, START + timedelta(hours=20))
    assert forecast.depletion_at_utc[1] == START + timedelta(hours=20)
    assert forecast.tank_masses_mt[2] == pytest.approx(20.0)
    assert forecast.tank_masses_mt[3] == pytest.approx(20.0)


def test_exhausted_plan_reports_unallocated_consumption_and_never_negative():
    forecast = forecast_tank_consumption_plan(_plan(((1, 1.0),)), [_interval(10, 10)], {1: 3.0}, START + timedelta(hours=10))
    assert forecast.tank_masses_mt[1] == 0.0
    assert forecast.unallocated_consumption_mt == pytest.approx(7.0)
    assert "UNALLOCATED FUTURE CONSUMPTION" in forecast.issues


def test_active_plan_persistence_replaces_only_same_fuel_active_plan(tmp_path):
    database = Database(tmp_path / "plan.db"); database.initialize()
    with database.connect() as connection: connection.execute("INSERT INTO vessels VALUES (1, 'V', '1234567', 'x', 'x')")
    service = FuelTankService(FuelTankRepository(database))
    batch = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO", "VLSFO", 978))
    tank = service.create_tank(FuelTank(None, 1, "1P", "BUNKER", 500, "SOUNDING", current_fuel_batch_id=batch.id))
    phase = TankConsumptionPlanPhase(None, 1, (TankConsumptionPlanPhaseTank(tank.id, 1.0),))
    first = service.save_consumption_plan(TankConsumptionPlan(None, 1, "VLSFO", "ACTIVE", START, (phase,)))
    second = service.save_consumption_plan(TankConsumptionPlan(None, 1, "VLSFO", "ACTIVE", START + timedelta(hours=1), (phase,)))
    assert service.get_active_consumption_plan(1, "VLSFO").id == second.id
    assert [item.status for item in service.list_consumption_plans(1)] == ["ACTIVE", "ARCHIVED"]
    assert first.id != second.id


def test_later_mass_bearing_sounding_reanchors_the_remaining_forecast():
    forecast = forecast_tank_consumption_plan(
        _plan(((1, 1.0),)), [_interval(10, 10)], {1: 20.0}, START + timedelta(hours=10),
        [(START + timedelta(hours=4), "SOUNDING", 1, 30.0)],
    )
    # Four MT are consumed before the observation; the observation then becomes
    # authoritative and only the remaining six MT are deducted from it.
    assert forecast.tank_masses_mt[1] == pytest.approx(24.0)


def test_transfer_and_confirmed_receipt_before_depletion_are_chronological():
    forecast = forecast_tank_consumption_plan(
        _plan(((1, 1.0),)), [_interval(10, 10)], {1: 5.0}, START + timedelta(hours=10),
        [(START + timedelta(hours=2), "TRANSFER_IN", 1, 4.0), (START + timedelta(hours=6), "RECEIPT", 1, 1.0)],
    )
    assert forecast.depletion_at_utc[1] == START + timedelta(hours=10)
    assert forecast.tank_masses_mt[1] == pytest.approx(0.0)


def test_multi_phase_chronology_conserves_consumption_and_never_negative():
    forecast = forecast_tank_consumption_plan(
        _plan(((1, 1.0),), ((2, .5), (3, .5)), ((4, 1.0),)), [_interval(20, 20)],
        {1: 3.0, 2: 4.0, 3: 8.0, 4: 20.0}, START + timedelta(hours=20),
    )
    assert forecast.depletion_at_utc[1] == START + timedelta(hours=3)
    assert forecast.phase_starts_utc[2] == START + timedelta(hours=3)
    assert forecast.depletion_at_utc[2] == START + timedelta(hours=11)
    assert forecast.phase_starts_utc[3] == START + timedelta(hours=11)
    assert all(value is None or value >= 0 for value in forecast.tank_masses_mt.values())
    # 20 authoritative MT = initial physical mass less final physical mass;
    # no allocation invents or loses consumption.
    assert 35.0 - sum(forecast.tank_masses_mt.values()) + forecast.unallocated_consumption_mt == pytest.approx(20.0)
