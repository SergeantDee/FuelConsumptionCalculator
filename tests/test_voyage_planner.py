from __future__ import annotations

from datetime import date, datetime

from fuel_consumption_calculator.calculations.rob_projection_engine import project_schedule_rob
from fuel_consumption_calculator.calculations.voyage_engine import calculate_consumption_with_voyage, calculate_voyage_plan, interpolate_speed_rates
from fuel_consumption_calculator.domain.bunker import BunkerCapacity, BunkerCapacityProfile
from fuel_consumption_calculator.domain.consumption import ConsumptionProfile, ConsumptionRate, FUEL_TYPES
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline
from fuel_consumption_calculator.domain.voyage import RouteDefinition, SpeedConsumptionPoint, VoyageLeg, VoyageLegOverride
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.services.bunker_service import BunkerService


def test_pilot_times_and_required_speed_are_derived_from_berth_times():
    plan = calculate_voyage_plan([_leg()], _profile(), [])
    row = plan.legs[0]

    assert row.pilot_off == datetime(2026, 1, 1, 2)
    assert row.pilot_on == datetime(2026, 1, 2, 10)
    assert row.sea_hours == 32
    assert row.required_speed_knots == 10


def test_speed_consumption_interpolates_between_fixture_points():
    rates = interpolate_speed_rates(12, [_speed_point(10, 24), _speed_point(14, 48)])

    assert rates is not None
    assert rates["ULSFO"] == 36


def test_full_leg_consumption_includes_departure_sea_and_arrival_maneuvering():
    plan = calculate_voyage_plan([_leg()], _profile(), [_speed_point(10, 24), _speed_point(14, 48)])
    row = plan.legs[0]

    assert row.departure_maneuvering_consumed_mt["ULSFO"] == 1
    assert row.sea_consumed_mt["ULSFO"] == 32
    assert row.arrival_maneuvering_consumed_mt["ULSFO"] == 1
    assert row.total_pre_arrival_consumed_mt["ULSFO"] == 34


def test_actual_pilot_off_changes_available_sea_time_and_required_speed():
    leg = _leg(
        VoyageLegOverride(
            vessel_id=1,
            sequence_number=2,
            origin_port_snapshot="Origin",
            destination_port_snapshot="Destination",
            origin_departure_snapshot="2026-01-01T00:00",
            destination_arrival_snapshot="2026-01-02T12:00",
            actual_pilot_off=datetime(2026, 1, 1, 4),
        )
    )

    row = calculate_voyage_plan([leg], _profile(), [_speed_point(10, 24), _speed_point(14, 48)]).legs[0]

    assert row.sea_hours == 30
    assert round(row.required_speed_knots, 2) == 10.67
    assert round(row.total_pre_arrival_consumed_mt["ULSFO"], 2) == 37


def test_updated_voyage_consumption_changes_projected_rob():
    events = _events()
    baseline_plan = calculate_voyage_plan([_leg()], _profile(), [_speed_point(10, 24), _speed_point(14, 48)])
    actual_plan = calculate_voyage_plan(
        [
            _leg(
                VoyageLegOverride(
                    vessel_id=1,
                    sequence_number=2,
                    origin_port_snapshot="Origin",
                    destination_port_snapshot="Destination",
                    origin_departure_snapshot="2026-01-01T00:00",
                    destination_arrival_snapshot="2026-01-02T12:00",
                    actual_pilot_off=datetime(2026, 1, 1, 4),
                )
            )
        ],
        _profile(),
        [_speed_point(10, 24), _speed_point(14, 48)],
    )
    timeline = build_schedule_timeline(events)
    starting_rob = StartingROB(1, tuple(ROBQuantity(fuel, 100 if fuel == "ULSFO" else 0) for fuel in FUEL_TYPES))

    baseline_rob = project_schedule_rob(starting_rob, calculate_consumption_with_voyage(timeline, events, baseline_plan, _profile()))
    actual_rob = project_schedule_rob(starting_rob, calculate_consumption_with_voyage(timeline, events, actual_plan, _profile()))

    assert baseline_rob.rows[1].projected_rob_mt["ULSFO"] == 66
    assert round(actual_rob.rows[1].projected_rob_mt["ULSFO"], 2) == 63


def test_updated_projected_arrival_rob_changes_max_lift(tmp_path):
    service = BunkerService(BunkerRepository(Database(tmp_path / "unused.db")))
    profile = BunkerCapacityProfile(1, (BunkerCapacity("ULSFO", 1000, 90), BunkerCapacity("VLSFO", 0, 90), BunkerCapacity("MDO", 0, 90)))

    baseline = service.calculate_lift_limits(profile, {"ULSFO": 66, "VLSFO": 0, "MDO": 0})
    actual = service.calculate_lift_limits(profile, {"ULSFO": 63, "VLSFO": 0, "MDO": 0})

    assert baseline["ULSFO"].max_lift_mt == 834
    assert actual["ULSFO"].max_lift_mt == 837


def _profile() -> ConsumptionProfile:
    return ConsumptionProfile(
        vessel_id=1,
        rates=tuple(
            ConsumptionRate(mode, fuel, _rate(mode, fuel))
            for mode in ("SEA", "MANEUVERING", "PORT")
            for fuel in FUEL_TYPES
        ),
    )


def _rate(mode: str, fuel: str) -> float:
    if fuel != "ULSFO":
        return 0.0
    return {"SEA": 24.0, "MANEUVERING": 12.0, "PORT": 0.0}[mode]


def _speed_point(speed: float, ulsfo_rate: float) -> SpeedConsumptionPoint:
    return SpeedConsumptionPoint(1, speed, {"ULSFO": ulsfo_rate, "VLSFO": 0.0, "MDO": 0.0})


def _leg(override: VoyageLegOverride | None = None) -> VoyageLeg:
    return VoyageLeg(
        vessel_id=1,
        sequence_number=2,
        origin_event_id=1,
        destination_event_id=2,
        origin_port="Origin",
        destination_port="Destination",
        scheduled_berth_departure=datetime(2026, 1, 1, 0),
        scheduled_berth_arrival=datetime(2026, 1, 2, 12),
        route=RouteDefinition("Origin", "Destination", 5, 2, 320, 5, 2),
        override=override,
    )


def _events() -> list[ScheduleEvent]:
    return [
        ScheduleEvent(1, 1, 1, "Origin", "Port Call", datetime(2025, 12, 31, 12), datetime(2026, 1, 1, 0), "manual", "Fixture", date(2026, 1, 1), "", ""),
        ScheduleEvent(2, 1, 2, "Destination", "Port Call", datetime(2026, 1, 2, 12), None, "manual", "Fixture", date(2026, 1, 1), "", ""),
    ]
