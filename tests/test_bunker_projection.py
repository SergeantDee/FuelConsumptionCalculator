from __future__ import annotations

from datetime import date, datetime

from fuel_consumption_calculator.calculations.bunker_projection_engine import project_schedule_rob_with_bunkers
from fuel_consumption_calculator.calculations.consumption_engine import EventFuelConsumption, ScheduleFuelConsumption
from fuel_consumption_calculator.domain.bunker import BunkerCapacity, BunkerCapacityProfile, complete_bunker_plan
from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.repositories.bunker_repository import BunkerRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.bunker_service import BunkerService


def starting_rob(ulsfo: float = 0.0, vlsfo: float = 0.0, mdo: float = 0.0) -> StartingROB:
    return StartingROB(
        vessel_id=1,
        quantities=(
            ROBQuantity("ULSFO", ulsfo),
            ROBQuantity("VLSFO", vlsfo),
            ROBQuantity("MDO", mdo),
        ),
    )


def consumption_row(sequence: int, *, ulsfo: float = 0.0, vlsfo: float = 0.0, mdo: float = 0.0) -> EventFuelConsumption:
    return EventFuelConsumption(
        event_id=sequence,
        sequence_number=sequence,
        port=f"Port {sequence}",
        sea_hours=0.0,
        port_hours=0.0,
        consumed_mt={"ULSFO": ulsfo, "VLSFO": vlsfo, "MDO": mdo},
        sea_consumed_mt={"ULSFO": ulsfo, "VLSFO": vlsfo, "MDO": mdo},
        port_consumed_mt={"ULSFO": 0.0, "VLSFO": 0.0, "MDO": 0.0},
    )


def consumption_result(rows: list[EventFuelConsumption]) -> ScheduleFuelConsumption:
    return ScheduleFuelConsumption(
        rows=rows,
        totals_mt={
            "ULSFO": sum(row.consumed_mt["ULSFO"] for row in rows),
            "VLSFO": sum(row.consumed_mt["VLSFO"] for row in rows),
            "MDO": sum(row.consumed_mt["MDO"] for row in rows),
        },
    )


def _one_event_bunker_context(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    schedule_repository = ScheduleRepository(database)
    events = schedule_repository.replace_for_vessel(
        vessel.id,
        [
            ScheduleCandidate(
                sequence_number=1,
                port="Original Port",
                event_type="Port Call",
                arrival_at=datetime(2026, 9, 1, 8),
                departure_at=None,
                source="manual",
                source_vessel_name=vessel.name,
                source_from_date=date(2026, 9, 1),
            )
        ],
    )
    service = BunkerService(BunkerRepository(database))
    return database, vessel, schedule_repository, events, service


def test_max_lift_uses_target_percent_and_arrival_rob():
    service = BunkerService(BunkerRepository(Database(":memory:")))
    profile = BunkerCapacityProfile(
        vessel_id=1,
        capacities=(BunkerCapacity("ULSFO", 1000, 90), BunkerCapacity("VLSFO", 1000, 80), BunkerCapacity("MDO", 1000, 90)),
    )

    limits = service.calculate_lift_limits(profile, {"ULSFO": 320, "VLSFO": 320, "MDO": 950})

    assert limits["ULSFO"].target_rob_mt == 900
    assert limits["ULSFO"].max_lift_mt == 580
    assert limits["VLSFO"].target_rob_mt == 800
    assert limits["VLSFO"].max_lift_mt == 480
    assert limits["MDO"].max_lift_mt == 0


def test_bunker_projection_sequence_uses_arrival_bunker_departure_order():
    plan = complete_bunker_plan(
        vessel_id=1,
        sequence_number=1,
        port_snapshot="Port 1",
        arrival_snapshot=None,
        quantities={"ULSFO": 50},
    )

    projection = project_schedule_rob_with_bunkers(
        starting_rob(ulsfo=100),
        consumption_result(
            [
                EventFuelConsumption(
                    event_id=1,
                    sequence_number=1,
                    port="Port 1",
                    sea_hours=1,
                    port_hours=1,
                    consumed_mt={"ULSFO": 15, "VLSFO": 0, "MDO": 0},
                    sea_consumed_mt={"ULSFO": 10, "VLSFO": 0, "MDO": 0},
                    port_consumed_mt={"ULSFO": 5, "VLSFO": 0, "MDO": 0},
                )
            ]
        ),
        [plan],
    )

    assert projection.rows[0].arrival_rob_mt["ULSFO"] == 90
    assert projection.rows[0].post_bunker_rob_mt["ULSFO"] == 140
    assert projection.rows[0].departure_rob_mt["ULSFO"] == 135


def test_bunker_projection_keeps_fuels_independent_and_negative_before_bunker():
    plan = complete_bunker_plan(
        vessel_id=1,
        sequence_number=1,
        port_snapshot="Port 1",
        arrival_snapshot=None,
        quantities={"MDO": 10},
    )

    projection = project_schedule_rob_with_bunkers(
        starting_rob(ulsfo=100, mdo=7),
        consumption_result([consumption_row(1, ulsfo=5, mdo=10)]),
        [plan],
    )

    assert projection.rows[0].arrival_rob_mt["ULSFO"] == 95
    assert projection.rows[0].arrival_rob_mt["MDO"] == -3
    assert projection.rows[0].post_bunker_rob_mt["MDO"] == 7


def test_stale_bunker_plan_is_not_applied(tmp_path):
    _database, vessel, schedule_repository, events, service = _one_event_bunker_context(tmp_path)
    service.save_plan(service.build_plan(vessel_id=vessel.id, event=events[0], quantities={"ULSFO": 50}))

    changed_events = schedule_repository.replace_for_vessel(
        vessel.id,
        [
            ScheduleCandidate(
                sequence_number=1,
                port="Original Port",
                event_type="Port Call",
                arrival_at=datetime(2026, 9, 1, 9),
                departure_at=None,
                source="manual",
                source_vessel_name=vessel.name,
                source_from_date=date(2026, 9, 1),
            )
        ],
    )

    statuses = service.list_plan_statuses(vessel.id, changed_events)

    assert statuses[0].status == "STALE"
    assert service.active_plans(vessel.id, changed_events) == []


def test_new_saved_bunker_plan_is_draft(tmp_path):
    _database, vessel, _schedule_repository, events, service = _one_event_bunker_context(tmp_path)

    saved_plan = service.save_plan(service.build_plan(vessel_id=vessel.id, event=events[0], quantities={"ULSFO": 50}))
    statuses = service.list_plan_statuses(vessel.id, events)

    assert saved_plan is not None
    assert saved_plan.status == "DRAFT"
    assert statuses[0].status == "DRAFT"
    assert service.active_plans(vessel.id, events) == []


def test_confirmed_bunker_plan_is_applied_to_projection(tmp_path):
    _database, vessel, _schedule_repository, events, service = _one_event_bunker_context(tmp_path)
    draft_plan = service.save_plan(service.build_plan(vessel_id=vessel.id, event=events[0], quantities={"ULSFO": 50}))

    confirmed_plan = service.confirm_plan(draft_plan)
    projection = project_schedule_rob_with_bunkers(
        starting_rob(ulsfo=100),
        consumption_result([consumption_row(1, ulsfo=10)]),
        service.active_plans(vessel.id, events),
    )

    assert confirmed_plan is not None
    assert confirmed_plan.status == "CONFIRMED"
    assert service.list_plan_statuses(vessel.id, events)[0].status == "CONFIRMED"
    assert projection.rows[0].arrival_rob_mt["ULSFO"] == 90
    assert projection.rows[0].post_bunker_rob_mt["ULSFO"] == 140


def test_editing_confirmed_plan_returns_to_draft_and_is_not_applied(tmp_path):
    _database, vessel, _schedule_repository, events, service = _one_event_bunker_context(tmp_path)
    draft_plan = service.save_plan(service.build_plan(vessel_id=vessel.id, event=events[0], quantities={"ULSFO": 50}))
    service.confirm_plan(draft_plan)

    edited_plan = service.save_plan(service.build_plan(vessel_id=vessel.id, event=events[0], quantities={"ULSFO": 70}))
    projection = project_schedule_rob_with_bunkers(
        starting_rob(ulsfo=100),
        consumption_result([consumption_row(1, ulsfo=10)]),
        service.active_plans(vessel.id, events),
    )

    assert edited_plan is not None
    assert edited_plan.status == "DRAFT"
    assert service.list_plan_statuses(vessel.id, events)[0].status == "DRAFT"
    assert projection.rows[0].post_bunker_rob_mt["ULSFO"] == 90
