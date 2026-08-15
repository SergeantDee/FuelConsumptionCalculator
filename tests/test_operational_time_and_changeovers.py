from __future__ import annotations

from datetime import date, datetime, timezone

from fuel_consumption_calculator.calculations.bunker_projection_engine import project_schedule_rob_with_bunkers
from fuel_consumption_calculator.calculations.voyage_engine import calculate_consumption_with_voyage, calculate_voyage_plan
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline
from fuel_consumption_calculator.domain.time_model import local_to_utc, utc_to_vessel_time
from fuel_consumption_calculator.domain.voyage import (
    FuelChangeoverEvent,
    GeneratorSfocPoint,
    MachineryFuelState,
    RouteDefinition,
    SpeedConsumptionPoint,
    VesselEnergyConfig,
    VoyageLeg,
    VoyageLegOverride,
)


def test_port_local_timestamp_converts_to_utc_with_iana_timezone():
    result = local_to_utc(datetime(2026, 8, 16, 19, 0), "America/Sao_Paulo")

    assert result.status == "RESOLVED"
    assert result.utc_value == datetime(2026, 8, 16, 22, 0, tzinfo=timezone.utc)


def test_utc_timeline_elapsed_ignores_port_local_clock_difference():
    events = [
        _event(1, "Santos", datetime(2026, 8, 16, 19), datetime(2026, 8, 16, 20), datetime(2026, 8, 16, 22, tzinfo=timezone.utc), datetime(2026, 8, 16, 23, tzinfo=timezone.utc)),
        _event(2, "Rotterdam", datetime(2026, 8, 17, 10), None, datetime(2026, 8, 17, 8, tzinfo=timezone.utc), None),
    ]

    timeline = build_schedule_timeline(events)

    assert not timeline.issues
    assert timeline.rows[1].interval_from_previous_hours == 9


def test_vessel_clock_adjustment_changes_display_not_utc_duration():
    start_utc = datetime(2026, 1, 1, 0, tzinfo=timezone.utc)
    end_utc = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    assert (end_utc - start_utc).total_seconds() / 3600 == 12
    assert utc_to_vessel_time(end_utc, 60) - utc_to_vessel_time(start_utc, 0) != (end_utc - start_utc)


def test_missing_port_timezone_remains_unresolved_not_assumed_utc():
    result = local_to_utc(datetime(2026, 1, 1, 12), None)

    assert result.status == "UNRESOLVED"
    assert result.utc_value is None


def test_mixed_resolved_and_unresolved_schedule_does_not_raise_type_error():
    events = [
        _event(1, "Paranagua", datetime(2026, 10, 4, 21), datetime(2026, 10, 5, 17), datetime(2026, 10, 5, tzinfo=timezone.utc), datetime(2026, 10, 5, 20, tzinfo=timezone.utc)),
        ScheduleEvent(2, 1, 2, "Unknown Port", "Port Call", datetime(2026, 10, 8, 3), datetime(2026, 10, 9, 3), "maersk", "Fixture", date(2026, 8, 16), "", "", timezone_status="UNRESOLVED"),
        _event(3, "Itapoa", datetime(2026, 10, 14, 12), datetime(2026, 10, 15, 4), datetime(2026, 10, 14, 15, tzinfo=timezone.utc), datetime(2026, 10, 15, 7, tzinfo=timezone.utc)),
    ]

    timeline = build_schedule_timeline(events)

    assert timeline.issues[0].message == "Unknown Port timezone conversion is unresolved."
    assert timeline.rows[1].interval_from_previous_hours is None


def test_me_fuel_change_splits_main_engine_consumption():
    plan = _plan_with_changeovers(
        [FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", datetime(2026, 1, 1, 12, tzinfo=timezone.utc))]
    )

    sea = plan.legs[0].sea_consumed_mt

    main_vlsfo = sea["VLSFO"] - plan.legs[0].sea_generator_consumed_mt["VLSFO"] - plan.legs[0].sea_boiler_consumed_mt["VLSFO"]
    main_ulsfo = sea["ULSFO"] - plan.legs[0].sea_generator_consumed_mt["ULSFO"] - plan.legs[0].sea_boiler_consumed_mt["ULSFO"]
    assert main_vlsfo > 0
    assert main_ulsfo > 0
    assert round(main_vlsfo + main_ulsfo, 2) == round(plan.legs[0].predicted_me_fuel_mt_per_hour * 24, 2)


def test_dg_changeover_is_independent_from_main_engine():
    plan = _plan_with_changeovers(
        [
            FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", datetime(2026, 1, 1, 12, tzinfo=timezone.utc)),
            FuelChangeoverEvent(None, 1, "GENERATORS", "VLSFO", "MDO", datetime(2026, 1, 1, 18, tzinfo=timezone.utc)),
        ]
    )

    generator = plan.legs[0].sea_generator_consumed_mt

    assert generator["VLSFO"] > 0
    assert generator["MDO"] > 0
    assert plan.legs[0].sea_consumed_mt["MDO"] == generator["MDO"]


def test_aux_boiler_port_changeover_splits_by_utc_hours():
    events = [_event(1, "Santos", datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))]
    timeline = build_schedule_timeline(events)
    plan = calculate_voyage_plan(
        [],
        _profile(),
        [],
        VesselEnergyConfig(1, generator_rated_kw=1000, port_running_generators=1, sea_running_generators=1, aux_boiler_mt_per_hour=0.1),
        _sfoc_points(),
        MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO"),
        [FuelChangeoverEvent(None, 1, "AUX_BOILER", "VLSFO", "ULSFO", datetime(2026, 1, 1, 12, tzinfo=timezone.utc))],
    )

    result = calculate_consumption_with_voyage(timeline, events, plan, _profile())

    assert round(result.rows[0].port_consumed_mt["VLSFO"], 2) == 1.2
    assert round(result.rows[0].port_consumed_mt["ULSFO"], 2) == 1.2


def test_egb_selected_removes_boiler_when_available_and_resumes_when_unavailable():
    available = _plan_with_changeovers([], me_load=30, use_egb=True)
    unavailable = _plan_with_changeovers([], me_load=20, use_egb=True)

    assert available.legs[0].predicted_me_load_percent >= 25
    assert sum(available.legs[0].sea_boiler_consumed_mt.values()) == 0
    assert unavailable.legs[0].sea_boiler_consumed_mt["VLSFO"] > 0


def test_actual_changeover_timestamp_overrides_planned_and_changes_rob_allocation():
    changeover = FuelChangeoverEvent(
        None,
        1,
        "MAIN_ENGINE",
        "VLSFO",
        "ULSFO",
        planned_at_utc=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        actual_at_utc=datetime(2026, 1, 1, 18, tzinfo=timezone.utc),
    )
    events = _events_for_leg()
    plan = _plan_with_changeovers([changeover])
    consumption = calculate_consumption_with_voyage(build_schedule_timeline(events), events, plan, _profile())
    rob = project_schedule_rob_with_bunkers(
        StartingROB(1, tuple(ROBQuantity(fuel, 100) for fuel in FUEL_TYPES)),
        consumption,
        [],
    )

    main_vlsfo = consumption.rows[1].sea_consumed_mt["VLSFO"] - plan.legs[0].sea_generator_consumed_mt["VLSFO"] - plan.legs[0].sea_boiler_consumed_mt["VLSFO"]
    assert round(main_vlsfo, 2) == round(plan.legs[0].predicted_me_fuel_mt_per_hour * 18, 2)
    assert rob.rows[1].arrival_rob_mt["VLSFO"] < rob.rows[1].arrival_rob_mt["ULSFO"]


def _plan_with_changeovers(changeovers: list[FuelChangeoverEvent], *, me_load: float = 30, use_egb: bool = False):
    events = _events_for_leg()
    leg = VoyageLeg(
        vessel_id=1,
        sequence_number=2,
        origin_event_id=1,
        destination_event_id=2,
        origin_port="Santos",
        destination_port="Rotterdam",
        scheduled_berth_departure=events[0].effective_departure_at,
        scheduled_berth_arrival=events[1].effective_arrival_at,
        route=RouteDefinition("Santos", "Rotterdam", 0, 0, _distance_for_me_load(me_load), 0, 0),
        override=VoyageLegOverride(1, 2, "Santos", "Rotterdam", "2026-01-01T00:00+00:00", "2026-01-02T00:00+00:00", use_egb=use_egb),
    )
    return calculate_voyage_plan(
        [leg],
        _profile(),
        [SpeedConsumptionPoint(1, 10, {"ULSFO": 24, "VLSFO": 24, "MDO": 24}, me_load)],
        _energy_config(),
        _sfoc_points(),
        MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO"),
        changeovers,
    )


def _distance_for_me_load(load_percent: float) -> float:
    rpm = ((load_percent / 100 * 38880.0) / 0.0967741935483871) ** (1 / 3)
    speed = rpm * 0.3221598 * 0.9
    return speed * 24


def _events_for_leg() -> list[ScheduleEvent]:
    return [
        _event(1, "Santos", datetime(2026, 1, 1), datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)),
        _event(2, "Rotterdam", datetime(2026, 1, 2), None, datetime(2026, 1, 2, tzinfo=timezone.utc), None),
    ]


def _event(sequence: int, port: str, arrival, departure, arrival_utc, departure_utc) -> ScheduleEvent:
    return ScheduleEvent(sequence, 1, sequence, port, "Port Call", arrival, departure, "manual", "Fixture", date(2026, 1, 1), "", "", port_timezone_id="UTC", arrival_at_utc=arrival_utc, departure_at_utc=departure_utc, timezone_status="RESOLVED")


def _profile() -> ConsumptionProfile:
    return ConsumptionProfile(1, tuple(ConsumptionRate(mode, fuel, 0.0) for mode in ("SEA", "MANEUVERING", "PORT") for fuel in FUEL_TYPES))


def _energy_config() -> VesselEnergyConfig:
    return VesselEnergyConfig(1, port_base_load_kw=100, sea_base_load_kw=100, generator_rated_kw=1000, port_running_generators=1, sea_running_generators=1, aux_boiler_mt_per_hour=0.1)


def _sfoc_points() -> list[GeneratorSfocPoint]:
    from fuel_consumption_calculator.domain.voyage import GeneratorSfocPoint

    return [GeneratorSfocPoint(1, 0, 200), GeneratorSfocPoint(1, 100, 200)]
