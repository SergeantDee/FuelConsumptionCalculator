from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.calculations.consumption_engine import ScheduleFuelConsumption
from fuel_consumption_calculator.domain.bunker import PlannedBunker
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.rob import StartingROB


@dataclass(frozen=True, slots=True)
class EventBunkerROBProjection:
    event_id: int
    sequence_number: int
    port: str
    sea_hours: float
    port_hours: float
    consumed_mt: dict[str, float | None]
    arrival_rob_mt: dict[str, float | None]
    bunker_mt: dict[str, float]
    post_bunker_rob_mt: dict[str, float | None]
    departure_rob_mt: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class ScheduleBunkerROBProjection:
    rows: list[EventBunkerROBProjection]
    final_rob_mt: dict[str, float | None]


def project_schedule_rob_with_bunkers(
    starting_rob: StartingROB,
    consumption: ScheduleFuelConsumption,
    active_bunker_plans: list[PlannedBunker],
) -> ScheduleBunkerROBProjection:
    projected_rob = {
        fuel_type: starting_rob.quantity_for(fuel_type)
        for fuel_type in FUEL_TYPES
    }
    plans_by_sequence = {
        plan.sequence_number: plan
        for plan in active_bunker_plans
    }
    rows: list[EventBunkerROBProjection] = []

    for consumption_row in consumption.rows:
        for fuel_type in FUEL_TYPES:
            sea_consumed = consumption_row.sea_consumed_mt.get(fuel_type, 0.0)
            projected_rob[fuel_type] = None if projected_rob[fuel_type] is None or sea_consumed is None else projected_rob[fuel_type] - sea_consumed
        arrival_rob = dict(projected_rob)
        plan = plans_by_sequence.get(consumption_row.sequence_number)
        bunker = {
            fuel_type: plan.quantity_for(fuel_type) if plan else 0.0
            for fuel_type in FUEL_TYPES
        }
        for fuel_type in FUEL_TYPES:
            projected_rob[fuel_type] = None if projected_rob[fuel_type] is None else projected_rob[fuel_type] + bunker[fuel_type]
        post_bunker_rob = dict(projected_rob)
        for fuel_type in FUEL_TYPES:
            port_consumed = consumption_row.port_consumed_mt.get(fuel_type, 0.0)
            projected_rob[fuel_type] = None if projected_rob[fuel_type] is None or port_consumed is None else projected_rob[fuel_type] - port_consumed
        rows.append(
            EventBunkerROBProjection(
                event_id=consumption_row.event_id,
                sequence_number=consumption_row.sequence_number,
                port=consumption_row.port,
                sea_hours=consumption_row.sea_hours,
                port_hours=consumption_row.port_hours,
                consumed_mt={fuel_type: consumption_row.consumed_mt.get(fuel_type, 0.0) for fuel_type in FUEL_TYPES},
                arrival_rob_mt=arrival_rob,
                bunker_mt=bunker,
                post_bunker_rob_mt=post_bunker_rob,
                departure_rob_mt=dict(projected_rob),
            )
        )

    return ScheduleBunkerROBProjection(rows=rows, final_rob_mt=dict(projected_rob))
