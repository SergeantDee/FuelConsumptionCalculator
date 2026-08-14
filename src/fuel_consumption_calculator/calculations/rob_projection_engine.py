from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.calculations.consumption_engine import ScheduleFuelConsumption
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.rob import StartingROB


@dataclass(frozen=True, slots=True)
class EventROBProjection:
    event_id: int
    sequence_number: int
    port: str
    sea_hours: float
    port_hours: float
    consumed_mt: dict[str, float]
    cumulative_consumed_mt: dict[str, float]
    projected_rob_mt: dict[str, float]


@dataclass(frozen=True, slots=True)
class ScheduleROBProjection:
    rows: list[EventROBProjection]
    final_rob_mt: dict[str, float]


def project_schedule_rob(
    starting_rob: StartingROB,
    consumption: ScheduleFuelConsumption,
) -> ScheduleROBProjection:
    projected_rob = {
        fuel_type: starting_rob.quantity_for(fuel_type)
        for fuel_type in FUEL_TYPES
    }
    cumulative_consumed = {fuel_type: 0.0 for fuel_type in FUEL_TYPES}
    rows: list[EventROBProjection] = []

    for consumption_row in consumption.rows:
        for fuel_type in FUEL_TYPES:
            consumed = consumption_row.consumed_mt.get(fuel_type, 0.0)
            cumulative_consumed[fuel_type] += consumed
            projected_rob[fuel_type] -= consumed
        rows.append(
            EventROBProjection(
                event_id=consumption_row.event_id,
                sequence_number=consumption_row.sequence_number,
                port=consumption_row.port,
                sea_hours=consumption_row.sea_hours,
                port_hours=consumption_row.port_hours,
                consumed_mt={fuel_type: consumption_row.consumed_mt.get(fuel_type, 0.0) for fuel_type in FUEL_TYPES},
                cumulative_consumed_mt=dict(cumulative_consumed),
                projected_rob_mt=dict(projected_rob),
            )
        )

    return ScheduleROBProjection(rows=rows, final_rob_mt=dict(projected_rob))
