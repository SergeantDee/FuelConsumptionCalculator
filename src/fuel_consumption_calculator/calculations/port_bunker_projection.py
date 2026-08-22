from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fuel_consumption_calculator.domain.bunker import BunkerCapacityProfile, BunkerPlanStatus
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.voyage import ActualROBObservation
from fuel_consumption_calculator.domain.voyage_stages import OperationalStage, VoyageStageTimeline


@dataclass(frozen=True, slots=True)
class PortBunkerProjectionRow:
    event: ScheduleEvent
    status: str
    arrival_rob_mt: dict[str, float | None]
    rob_source: str
    max_lift_mt: dict[str, float | None]
    planned_bunker_mt: dict[str, float]
    plan_status: str
    port_consumption_mt: dict[str, float | None]
    departure_rob_mt: dict[str, float | None]
    issue: str | None = None


def build_port_bunker_projection(
    events: list[ScheduleEvent],
    timeline: VoyageStageTimeline,
    plan_statuses: list[BunkerPlanStatus],
    capacity_profile: BunkerCapacityProfile,
    observations: list[ActualROBObservation],
    now_utc: datetime | None = None,
) -> list[PortBunkerProjectionRow]:
    now = _utc(now_utc or datetime.now(timezone.utc))
    statuses = {status.plan.sequence_number: status for status in plan_statuses}
    port_stages = {stage.event.id: stage for stage in timeline.stages if stage.event is not None and stage.stage_type == "PORT_STAY"}
    rows: list[PortBunkerProjectionRow] = []
    for index, event in enumerate(sorted(events, key=lambda item: (item.sequence_number, item.effective_arrival_at, item.id))):
        stage = port_stages.get(event.id)
        status = statuses.get(event.sequence_number)
        planned = {fuel: status.plan.quantity_for(fuel) if status else 0.0 for fuel in FUEL_TYPES}
        plan_status = status.status if status else "NO PLAN"
        arrival = dict(stage.rob.start_mt) if stage else _unknown()
        departure = dict(stage.rob.end_mt) if stage else _unknown()
        consumption = dict(stage.consumption_mt) if stage else _unknown()
        max_lift = {
            fuel: None if arrival[fuel] is None else max(0.0, capacity_profile.capacity_for(fuel).target_rob_mt - float(arrival[fuel]))
            for fuel in FUEL_TYPES
        }
        rows.append(PortBunkerProjectionRow(
            event=event,
            status=_port_display_status(stage, index, now),
            arrival_rob_mt=arrival,
            rob_source=_rob_source(arrival, stage.start_utc if stage else None, observations, index),
            max_lift_mt=max_lift,
            planned_bunker_mt=planned,
            plan_status=plan_status,
            port_consumption_mt=consumption,
            departure_rob_mt=departure,
            issue="Unavailable ROB" if any(value is None for value in arrival.values()) else None,
        ))
    next_index = next((index for index, row in enumerate(rows) if row.status == "FUTURE"), None)
    if next_index is not None:
        row = rows[next_index]
        rows[next_index] = PortBunkerProjectionRow(
            event=row.event, status="NEXT", arrival_rob_mt=row.arrival_rob_mt, rob_source=row.rob_source,
            max_lift_mt=row.max_lift_mt, planned_bunker_mt=row.planned_bunker_mt, plan_status=row.plan_status,
            port_consumption_mt=row.port_consumption_mt, departure_rob_mt=row.departure_rob_mt, issue=row.issue,
        )
    return rows


def _port_display_status(stage: OperationalStage | None, index: int, now: datetime) -> str:
    if stage is None or stage.start_utc is None or stage.end_utc is None:
        return "FUTURE"
    start, end = _utc(stage.start_utc), _utc(stage.end_utc)
    if end <= now:
        return "COMPLETED"
    if start <= now < end:
        return "CURRENT"
    return "FUTURE"


def _rob_source(arrival, boundary, observations, index: int) -> str:
    if any(value is None for value in arrival.values()):
        return "UNKNOWN"
    if boundary is not None and any(_utc(item.effective_at_utc) <= _utc(boundary) for item in observations):
        return "ACTUAL ANCHORED"
    return "STARTING ROB" if index == 0 else "ESTIMATED"


def _unknown() -> dict[str, None]:
    return {fuel: None for fuel in FUEL_TYPES}


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
