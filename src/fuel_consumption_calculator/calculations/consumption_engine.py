from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, ConsumptionProfile
from fuel_consumption_calculator.domain.schedule_timeline import ScheduleTimeline


@dataclass(frozen=True, slots=True)
class EventFuelConsumption:
    event_id: int
    sequence_number: int
    port: str
    sea_hours: float
    port_hours: float
    consumed_mt: dict[str, float]


@dataclass(frozen=True, slots=True)
class ScheduleFuelConsumption:
    rows: list[EventFuelConsumption]
    totals_mt: dict[str, float]


def calculate_schedule_consumption(
    timeline: ScheduleTimeline,
    profile: ConsumptionProfile,
) -> ScheduleFuelConsumption:
    if timeline.issues:
        raise ValueError(f"Cannot calculate consumption while schedule chronology is invalid: {timeline.issues[0].message}")

    rows: list[EventFuelConsumption] = []
    totals = {fuel_type: 0.0 for fuel_type in FUEL_TYPES}
    for timeline_row in timeline.rows:
        sea_hours = max(0.0, timeline_row.interval_from_previous_hours or 0.0)
        port_hours = max(0.0, timeline_row.port_stay_hours or 0.0)
        consumed = {
            fuel_type: _consume(sea_hours, profile.rate_for("SEA", fuel_type))
            + _consume(port_hours, profile.rate_for("PORT", fuel_type))
            for fuel_type in FUEL_TYPES
        }
        for fuel_type, value in consumed.items():
            totals[fuel_type] += value
        rows.append(
            EventFuelConsumption(
                event_id=timeline_row.event.id,
                sequence_number=timeline_row.event.sequence_number,
                port=timeline_row.event.port,
                sea_hours=sea_hours,
                port_hours=port_hours,
                consumed_mt=consumed,
            )
        )

    return ScheduleFuelConsumption(rows=rows, totals_mt=totals)


def _consume(hours: float, rate_mt_per_day: float) -> float:
    return hours / 24 * rate_mt_per_day
