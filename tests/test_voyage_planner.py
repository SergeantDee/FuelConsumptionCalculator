from __future__ import annotations

from datetime import date, datetime

from fuel_consumption_calculator.calculations.rob_projection_engine import project_schedule_rob
from fuel_consumption_calculator.calculations.bunker_projection_engine import project_schedule_rob_with_bunkers
from fuel_consumption_calculator.calculations.voyage_engine import calculate_consumption_with_voyage, calculate_voyage_plan, interpolate_speed_rates
from fuel_consumption_calculator.domain.bunker import BunkerCapacity, BunkerCapacityProfile
from fuel_consumption_calculator.domain.consumption import ConsumptionProfile, ConsumptionRate, FUEL_TYPES
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline
from fuel_consumption_calculator.domain.voyage import GeneratorSfocPoint, MachineryFuelState, RouteDefinition, SpeedConsumptionPoint, VesselEnergyConfig, VoyageLeg, VoyageLegOverride
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


def test_missing_detailed_me_configuration_marks_sea_calculation_incomplete():
    plan = calculate_voyage_plan([_leg()], _profile(), [_speed_point(10, 24), _speed_point(14, 48)])
    row = plan.legs[0]

    assert row.departure_maneuvering_consumed_mt["ULSFO"] == 1
    assert row.sea_consumed_mt["ULSFO"] is None
    assert row.arrival_maneuvering_consumed_mt["ULSFO"] == 1
    assert row.total_pre_arrival_consumed_mt["ULSFO"] is None
    assert row.sea_calculation_mode == "INCOMPLETE"
    assert any("ME performance/SFOC unavailable" in warning for warning in row.warnings)


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
    assert row.total_pre_arrival_consumed_mt["ULSFO"] is None
    assert row.sea_calculation_mode == "INCOMPLETE"


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

    assert baseline_rob.rows[1].projected_rob_mt["ULSFO"] is None
    assert actual_rob.rows[1].projected_rob_mt["ULSFO"] is None


def test_updated_projected_arrival_rob_changes_max_lift(tmp_path):
    service = BunkerService(BunkerRepository(Database(tmp_path / "unused.db")))
    profile = BunkerCapacityProfile(1, (BunkerCapacity("ULSFO", 1000, 90), BunkerCapacity("VLSFO", 0, 90), BunkerCapacity("MDO", 0, 90)))

    baseline = service.calculate_lift_limits(profile, {"ULSFO": 66, "VLSFO": 0, "MDO": 0})
    actual = service.calculate_lift_limits(profile, {"ULSFO": 63, "VLSFO": 0, "MDO": 0})

    assert baseline["ULSFO"].max_lift_mt == 834
    assert actual["ULSFO"].max_lift_mt == 837


def test_port_load_generator_and_boiler_consumption_are_detailed():
    events = _events()
    leg = _leg(VoyageLegOverride(1, 2, "Origin", "Destination", "2026-01-01T00:00", "2026-01-02T12:00", port_reefers=10))
    plan = calculate_voyage_plan([leg], _profile(), [_speed_point(10, 24, 30)], _energy_config(), _sfoc_points())

    consumption = calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    assert consumption.rows[0].port_consumed_mt["ULSFO"] == 3.6479999999999997
    assert round(consumption.rows[0].port_consumed_mt["MDO"], 2) == 1.2


def test_speed_point_interpolates_main_engine_load_percent():
    plan = calculate_voyage_plan([_leg()], _profile(), [_speed_point(8, 20, 20), _speed_point(12, 28, 30)], _energy_config(), _sfoc_points())

    assert plan.legs[0].required_speed_knots == 10
    assert round(plan.legs[0].predicted_me_load_percent, 2) == 10.21


def test_egb_unavailable_below_25_percent_applies_sea_boiler():
    leg = _leg(route=RouteDefinition("Origin", "Destination", 5, 2, 430.71, 5, 2), override=VoyageLegOverride(1, 2, "Origin", "Destination", "2026-01-01T00:00", "2026-01-02T12:00", departure_reefers=10, use_egb=True))

    row = calculate_voyage_plan([leg], _profile(), [_speed_point(9.96, 23.9, 24.9), _speed_point(12, 28, 30)], _energy_config(), _sfoc_points()).legs[0]

    assert round(row.predicted_me_load_percent, 1) == 24.9
    assert row.egb_available is False
    assert row.egb_used is False
    assert row.sea_boiler_consumed_mt["MDO"] == 3.2


def test_egb_available_at_25_percent_but_boiler_applies_until_selected():
    leg = _leg(VoyageLegOverride(1, 2, "Origin", "Destination", "2026-01-01T00:00", "2026-01-02T12:00", departure_reefers=10, use_egb=False))

    row = calculate_voyage_plan([_leg(route=RouteDefinition("Origin", "Destination", 5, 2, 431.29, 5, 2), override=leg.leg.override if hasattr(leg, "leg") else leg.override)], _profile(), [_speed_point(10, 24, 25), _speed_point(12, 28, 30)], _energy_config(), _sfoc_points()).legs[0]

    assert round(row.predicted_me_load_percent, 1) == 25.0
    assert row.egb_available is True
    assert row.egb_used is False
    assert row.sea_boiler_consumed_mt["MDO"] == 3.2


def test_egb_selected_at_or_above_25_percent_removes_sea_boiler():
    leg = _leg(VoyageLegOverride(1, 2, "Origin", "Destination", "2026-01-01T00:00", "2026-01-02T12:00", departure_reefers=10, use_egb=True))

    row = calculate_voyage_plan([_leg(route=RouteDefinition("Origin", "Destination", 5, 2, 431.29, 5, 2), override=leg.leg.override if hasattr(leg, "leg") else leg.override)], _profile(), [_speed_point(10, 24, 25), _speed_point(12, 28, 30)], _energy_config(), _sfoc_points()).legs[0]

    assert row.egb_available is True
    assert row.egb_used is True
    assert row.sea_boiler_consumed_mt["MDO"] == 0


def test_rolling_drop_below_25_percent_disables_egb_and_changes_max_lift(tmp_path):
    events = _events()
    service = BunkerService(BunkerRepository(Database(tmp_path / "unused.db")))
    capacity = BunkerCapacityProfile(1, (BunkerCapacity("ULSFO", 1000, 90), BunkerCapacity("VLSFO", 0, 90), BunkerCapacity("MDO", 1000, 90)))
    starting_rob = StartingROB(1, (ROBQuantity("ULSFO", 100), ROBQuantity("VLSFO", 0), ROBQuantity("MDO", 100)))
    confirmed = _leg(route=RouteDefinition("Origin", "Destination", 5, 2, 431.29, 5, 2), override=VoyageLegOverride(1, 2, "Origin", "Destination", "2026-01-01T00:00", "2026-01-02T12:00", departure_reefers=10, use_egb=True))
    slowed = _leg(route=RouteDefinition("Origin", "Destination", 5, 2, 430.71, 5, 2), override=VoyageLegOverride(1, 2, "Origin", "Destination", "2026-01-01T00:00", "2026-01-02T12:00", departure_reefers=10, use_egb=True))

    fuel_state = MachineryFuelState(
        vessel_id=1,
        main_engine_fuel_type="ULSFO",
        generators_fuel_type="ULSFO",
        aux_boiler_fuel_type="MDO",
    )
    confirmed_consumption = calculate_consumption_with_voyage(build_schedule_timeline(events), events, calculate_voyage_plan([confirmed], _profile(), [_speed_point(10, 24, 25), _speed_point(12, 28, 30)], _energy_config(), _sfoc_points(), fuel_state), _profile())
    slowed_plan = calculate_voyage_plan([slowed], _profile(), [_speed_point(9.96, 23.9, 24.9), _speed_point(12, 28, 30)], _energy_config(), _sfoc_points(), fuel_state)
    slowed_consumption = calculate_consumption_with_voyage(build_schedule_timeline(events), events, slowed_plan, _profile())
    confirmed_rob = project_schedule_rob_with_bunkers(starting_rob, confirmed_consumption, [])
    slowed_rob = project_schedule_rob_with_bunkers(starting_rob, slowed_consumption, [])

    assert slowed_plan.legs[0].egb_used is False
    assert slowed_rob.rows[1].arrival_rob_mt["MDO"] < confirmed_rob.rows[1].arrival_rob_mt["MDO"]
    assert service.calculate_lift_limits(capacity, slowed_rob.rows[1].arrival_rob_mt)["MDO"].max_lift_mt > service.calculate_lift_limits(capacity, confirmed_rob.rows[1].arrival_rob_mt)["MDO"].max_lift_mt


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


def _speed_point(speed: float, ulsfo_rate: float, me_load: float | None = None) -> SpeedConsumptionPoint:
    return SpeedConsumptionPoint(1, speed, {"ULSFO": ulsfo_rate, "VLSFO": 0.0, "MDO": 0.0}, me_load)


def _leg(override: VoyageLegOverride | None = None, route: RouteDefinition | None = None) -> VoyageLeg:
    return VoyageLeg(
        vessel_id=1,
        sequence_number=2,
        origin_event_id=1,
        destination_event_id=2,
        origin_port="Origin",
        destination_port="Destination",
        scheduled_berth_departure=datetime(2026, 1, 1, 0),
        scheduled_berth_arrival=datetime(2026, 1, 2, 12),
        route=route or RouteDefinition("Origin", "Destination", 5, 2, 320, 5, 2),
        override=override,
    )


def _events() -> list[ScheduleEvent]:
    return [
        ScheduleEvent(1, 1, 1, "Origin", "Port Call", datetime(2025, 12, 31, 12), datetime(2026, 1, 1, 0), "manual", "Fixture", date(2026, 1, 1), "", ""),
        ScheduleEvent(2, 1, 2, "Destination", "Port Call", datetime(2026, 1, 2, 12), None, "manual", "Fixture", date(2026, 1, 1), "", ""),
    ]


def _energy_config() -> VesselEnergyConfig:
    return VesselEnergyConfig(
        vessel_id=1,
        port_base_load_kw=1500,
        sea_base_load_kw=1000,
        reefer_kw_per_unit=100,
        generator_rated_kw=5000,
        port_running_generators=1,
        sea_running_generators=1,
        aux_boiler_mt_per_hour=0.1,
        generator_fuel_type="ULSFO",
        boiler_fuel_type="MDO",
    )


def _sfoc_points() -> list[GeneratorSfocPoint]:
    return [GeneratorSfocPoint(1, 0, 200), GeneratorSfocPoint(1, 100, 200)]

def test_missing_inbound_voyage_leg_is_unavailable_not_zero():
    events = _events()
    timeline = build_schedule_timeline(events)

    plan = calculate_voyage_plan(
        [],
        _profile(),
        [],
        _energy_config(),
        _sfoc_points(),
    )

    consumption = calculate_consumption_with_voyage(
        timeline,
        events,
        plan,
        _profile(),
    )

    assert consumption.rows[0].sea_consumed_mt["ULSFO"] == 0.0
    assert consumption.rows[1].sea_consumed_mt["ULSFO"] is None
    assert consumption.rows[1].consumed_mt["ULSFO"] is None

def test_missing_main_engine_fuel_state_does_not_default_to_vlsfo():
    plan = calculate_voyage_plan(
        [_leg()],
        _profile(),
        [_speed_point(10, 24, 30), _speed_point(14, 48, 40)],
        _energy_config(),
        _sfoc_points(),
    )

    row = plan.legs[0]

    assert row.predicted_me_fuel_mt_per_hour is not None
    assert row.sea_calculation_mode == "INCOMPLETE"
    assert row.sea_consumed_mt["ULSFO"] is None
    assert row.sea_consumed_mt["VLSFO"] is None
    assert row.sea_consumed_mt["MDO"] is None

