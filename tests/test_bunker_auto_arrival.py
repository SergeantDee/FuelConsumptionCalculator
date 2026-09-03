from datetime import datetime, timezone

import pytest

from fuel_consumption_calculator.domain.bunker import BunkerReceivingTankPlan
from fuel_consumption_calculator.domain.fuel_tank import FuelTank, TankSounding
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.tank_forecast import TankForecast
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.bunker_service import BunkerService


ARRIVAL = datetime(2026, 1, 2, tzinfo=timezone.utc)


class ForecastStub:
    def __init__(self, forecast, anchor):
        self.forecast, self.anchor = forecast, anchor
        self.targets = []

    def predict_tank_rob_at(self, vessel_id, target_utc):
        self.targets.append(target_utc)
        return [self.forecast]

    def anchor_sounding_at(self, tank_id, target_utc):
        return self.anchor


@pytest.fixture
def setup(tmp_path):
    database = Database(tmp_path / "arrival.db"); database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO vessels VALUES (1, 'V', '1234567', 'x', 'x')")
    tanks = FuelTankRepository(database)
    tank = tanks.save_tank(FuelTank(None, 1, "Receiving", "BUNKER", 500, "SOUNDING", True))
    event = ScheduleEvent(1, 1, 1, "SG", "PORT", ARRIVAL, None, "x", "x", None, "x", "x")
    return database, tank, event


def service_for(database, tank, event, *, mass=80, volume=100, predicted=60):
    anchor = TankSounding(None, tank.id, "2026-01-01T00:00:00+00:00", "SOUNDING", 1, 0, None, volume, calculated_mass_mt=mass)
    forecast = TankForecast(tank.id, "VLSFO", ARRIVAL, mass, None if mass is None else mass - predicted, predicted)
    stub = ForecastStub(forecast, anchor)
    service = BunkerService(BunkerRepository(database), stub)
    plan = service.build_plan(vessel_id=1, event=event, quantities={"ULSFO": 0, "VLSFO": 0, "MDO": 0})
    return service, plan, stub


def test_estimate_uses_forecast_mass_and_historical_sounding_ratio(setup):
    database, tank, event = setup; service, plan, stub = service_for(database, tank, event)
    result = service.resolve_receiving_tank_arrivals(plan, [BunkerReceivingTankPlan(tank.id, None, 90)])[tank.id]
    assert result.source == "ESTIMATED"
    assert result.projected_arrival_volume_m3 == pytest.approx(75)  # 60 MT * (100 m3 / 80 MT)
    assert stub.targets == [ARRIVAL]  # canonical bunker arrival, never completion/departure


def test_manual_override_including_zero_wins_and_clearing_returns_estimate(setup):
    database, tank, event = setup; service, plan, _stub = service_for(database, tank, event)
    manual = service.resolve_receiving_tank_arrivals(plan, [BunkerReceivingTankPlan(tank.id, 0.0, 90)])[tank.id]
    automatic = service.resolve_receiving_tank_arrivals(plan, [BunkerReceivingTankPlan(tank.id, None, 90)])[tank.id]
    assert (manual.source, manual.projected_arrival_volume_m3) == ("MANUAL", 0.0)
    assert (automatic.source, automatic.projected_arrival_volume_m3) == ("ESTIMATED", pytest.approx(75))


@pytest.mark.parametrize("mass,volume,predicted,reason", [
    (None, 100, 60, "mass"),
    (0, 100, 60, "mass"),
])
def test_invalid_anchor_mass_is_unavailable(setup, mass, volume, predicted, reason):
    database, tank, event = setup; service, plan, _stub = service_for(database, tank, event, mass=mass, volume=volume, predicted=predicted)
    result = service.resolve_receiving_tank_arrivals(plan, [BunkerReceivingTankPlan(tank.id, None, 90)])[tank.id]
    assert result.source == "UNAVAILABLE" and reason in result.issue.lower()


def test_depleted_forecast_becomes_zero_volume_with_advisory_issue(setup):
    database, tank, event = setup; service, plan, _stub = service_for(database, tank, event, predicted=-1)
    result = service.resolve_receiving_tank_arrivals(plan, [BunkerReceivingTankPlan(tank.id, None, 90)])[tank.id]
    assert result.projected_arrival_volume_m3 == 0 and "depleted" in result.issue.lower()


def test_auto_estimate_feeds_tank_max_lift_without_persisting_it(setup):
    database, tank, event = setup; service, plan, _stub = service_for(database, tank, event)
    service.save_receiving_tank_plan(plan, [BunkerReceivingTankPlan(tank.id, None, 90)], None, None)
    result = service.tank_based_max_lift(plan)
    assert service.list_receiving_tank_plan(plan)[0].projected_arrival_volume_m3 is None
    assert result.total_available_volume_m3 == pytest.approx(375)
    assert result.total_max_lift_mt is None


def test_bunker_tank_rob_is_advisory_and_excludes_non_eligible_tanks(setup):
    database, tank, event = setup
    excluded = FuelTankRepository(database).save_tank(FuelTank(None, 1, "Service", "SERVICE", 500, "SOUNDING", False))
    forecast = TankForecast(tank.id, "VLSFO", ARRIVAL, 100, 0, 75)
    service = BunkerService(BunkerRepository(database), ForecastStub(forecast, None))

    values, issue = service.bunker_tank_rob_at(1, ARRIVAL)

    assert values == {"ULSFO": None, "VLSFO": 75.0, "MDO": None}
    assert issue is None
