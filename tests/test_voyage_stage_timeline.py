from __future__ import annotations

from datetime import date, datetime, timezone

from fuel_consumption_calculator.calculations.voyage_engine import calculate_consumption_with_voyage, calculate_voyage_plan
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline
from fuel_consumption_calculator.domain.voyage import (
    ActualROBObservation,
    FuelChangeoverEvent,
    GeneratorSfocPoint,
    MachineryFuelState,
    RouteDefinition,
    VesselEnergyConfig,
    VoyageLeg,
    VoyageLegOverride,
)
from fuel_consumption_calculator.domain.voyage_stages import (
    STATUS_COMPLETED,
    STATUS_CURRENT,
    STAGE_ARRIVAL_MANEUVERING,
    STAGE_DEPARTURE_MANEUVERING,
    STAGE_PORT_STAY,
    STAGE_SEA_PASSAGE,
    build_voyage_stage_timeline,
)


def test_stage_timeline_uses_port_departure_sea_arrival_sequence():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc))

    assert [stage.stage_type for stage in timeline.stages] == [
        STAGE_PORT_STAY,
        STAGE_DEPARTURE_MANEUVERING,
        STAGE_SEA_PASSAGE,
        STAGE_ARRIVAL_MANEUVERING,
        STAGE_PORT_STAY,
    ]
    assert timeline.stages[0].rob.end_mt == timeline.stages[1].rob.start_mt


def test_pre_voyage_timeline_keeps_current_rob_at_starting_anchor():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc))

    assert timeline.current_stage is None
    assert timeline.current_predicted_rob_mt == {"ULSFO": 100.0, "VLSFO": 100.0, "MDO": 100.0}
    assert timeline.next_port == "Origin"


def test_actual_departure_moves_port_stay_to_completed_and_departure_to_current():
    events = _events()
    override = VoyageLegOverride(
        1,
        2,
        "Origin",
        "Destination",
        "2026-01-01T00:00+00:00",
        "2026-01-02T12:00+00:00",
        actual_berth_departure=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
    )
    plan = _plan(override)
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2026, 1, 1, 1, tzinfo=timezone.utc))

    assert timeline.stages[0].status == STATUS_COMPLETED
    assert timeline.stages[1].status == STATUS_CURRENT
    assert timeline.current_stage is timeline.stages[1]


def test_stage_changeovers_include_actual_timestamp_and_do_not_create_default_events():
    events = _events()
    changeover = FuelChangeoverEvent(
        None,
        1,
        "MAIN_ENGINE",
        "VLSFO",
        "ULSFO",
        planned_at_utc=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        actual_at_utc=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
    )
    plan = _plan(changeovers=[changeover], detailed=True)
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc))
    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)

    assert sea_stage.changeovers == (changeover,)
    assert sea_stage.changeovers[0].effective_at_utc == datetime(2026, 1, 1, 18, tzinfo=timezone.utc)


def test_actual_rob_observation_resets_downstream_forecast_anchor():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())
    observation = ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 1, 2, tzinfo=timezone.utc),
        {"ULSFO": 90.0, "VLSFO": 80.0, "MDO": 70.0},
    )

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc), rob_observations=[observation])

    departure_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_DEPARTURE_MANEUVERING)
    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)
    assert departure_stage.rob.end_mt == {"ULSFO": 90.0, "VLSFO": 80.0, "MDO": 70.0}
    assert sea_stage.rob.start_mt == departure_stage.rob.end_mt


def test_actual_rob_observation_inside_sea_stage_splits_remaining_consumption():
    events = _events()
    changeover = FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", datetime(2026, 1, 1, 12, tzinfo=timezone.utc))
    plan = _plan(changeovers=[changeover], detailed=True)
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())
    observation = ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
        {"ULSFO": 50.0, "VLSFO": 60.0, "MDO": 70.0},
    )

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc), rob_observations=[observation])

    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)
    assert sea_stage.rob.end_mt["VLSFO"] < 60.0
    assert sea_stage.rob.end_mt["ULSFO"] <= 50.0


def test_actual_rob_observation_restores_forecast_after_unknown_stage():
    events = _events()
    plan = _plan()
    calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())
    observation = ActualROBObservation(
        None,
        1,
        datetime(2026, 1, 2, 11, tzinfo=timezone.utc),
        {"ULSFO": 70.0, "VLSFO": 80.0, "MDO": 90.0},
    )

    timeline = build_voyage_stage_timeline(events, plan, _starting_rob(), now_utc=datetime(2025, 12, 30, tzinfo=timezone.utc), rob_observations=[observation])

    sea_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_SEA_PASSAGE)
    arrival_stage = next(stage for stage in timeline.stages if stage.stage_type == STAGE_ARRIVAL_MANEUVERING)
    assert sea_stage.rob.end_mt == {"ULSFO": None, "VLSFO": None, "MDO": None}
    assert arrival_stage.rob.start_mt == {"ULSFO": None, "VLSFO": None, "MDO": None}
    assert arrival_stage.rob.end_mt["ULSFO"] == 70.0


def _plan(override: VoyageLegOverride | None = None, changeovers: list[FuelChangeoverEvent] | None = None, detailed: bool = False):
    leg = VoyageLeg(
        vessel_id=1,
        sequence_number=2,
        origin_event_id=1,
        destination_event_id=2,
        origin_port="Origin",
        destination_port="Destination",
        scheduled_berth_departure=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
        scheduled_berth_arrival=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        route=RouteDefinition("Origin", "Destination", 5, 2, 320, 5, 2),
        override=override,
    )
    return calculate_voyage_plan(
        [leg],
        _profile(),
        [],
        _energy_config() if detailed else None,
        _sfoc_points() if detailed else None,
        initial_fuel_state=MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO"),
        fuel_changeovers=changeovers or [],
    )


def _events() -> list[ScheduleEvent]:
    return [
        ScheduleEvent(
            1,
            1,
            1,
            "Origin",
            "Port Call",
            datetime(2025, 12, 31, 12),
            datetime(2026, 1, 1, 0),
            "manual",
            "Fixture",
            date(2026, 1, 1),
            "",
            "",
            port_timezone_id="UTC",
            arrival_at_utc=datetime(2025, 12, 31, 12, tzinfo=timezone.utc),
            departure_at_utc=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
        ),
        ScheduleEvent(
            2,
            1,
            2,
            "Destination",
            "Port Call",
            datetime(2026, 1, 2, 12),
            None,
            "manual",
            "Fixture",
            date(2026, 1, 1),
            "",
            "",
            port_timezone_id="UTC",
            arrival_at_utc=datetime(2026, 1, 2, 12, tzinfo=timezone.utc),
        ),
    ]


def _profile() -> ConsumptionProfile:
    return ConsumptionProfile(
        1,
        tuple(
            ConsumptionRate(mode, fuel, 24.0 if fuel == "VLSFO" else 0.0)
            for mode in ("SEA", "MANEUVERING", "PORT")
            for fuel in FUEL_TYPES
        ),
    )


def _starting_rob() -> StartingROB:
    return StartingROB(1, tuple(ROBQuantity(fuel, 100.0) for fuel in FUEL_TYPES))


def _energy_config() -> VesselEnergyConfig:
    return VesselEnergyConfig(
        vessel_id=1,
        sea_base_load_kw=1000,
        generator_rated_kw=5000,
        sea_running_generators=1,
        aux_boiler_mt_per_hour=0.1,
        generator_fuel_type="VLSFO",
        boiler_fuel_type="MDO",
    )


def _sfoc_points() -> list[GeneratorSfocPoint]:
    return [GeneratorSfocPoint(1, 0, 220), GeneratorSfocPoint(1, 100, 200)]
