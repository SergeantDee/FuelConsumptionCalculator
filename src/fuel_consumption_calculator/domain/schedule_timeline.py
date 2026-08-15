from __future__ import annotations

from dataclasses import dataclass

from fuel_consumption_calculator.domain.schedule import ScheduleEvent


@dataclass(frozen=True, slots=True)
class ScheduleTimelineIssue:
    event_id: int
    message: str


@dataclass(frozen=True, slots=True)
class ScheduleTimelineRow:
    event: ScheduleEvent
    port_stay_hours: float | None
    interval_from_previous_hours: float | None


@dataclass(frozen=True, slots=True)
class ScheduleTimeline:
    rows: list[ScheduleTimelineRow]
    issues: list[ScheduleTimelineIssue]


def build_schedule_timeline(events: list[ScheduleEvent]) -> ScheduleTimeline:
    ordered_events = sorted(events, key=lambda event: (event.sequence_number, event.effective_arrival_at, event.id))
    rows: list[ScheduleTimelineRow] = []
    issues: list[ScheduleTimelineIssue] = []
    previous_anchor = None

    for event in ordered_events:
        port_stay_hours = None
        arrival_at = event.effective_arrival_at
        departure_at = event.effective_departure_at
        if event.timezone_status != "RESOLVED":
            issues.append(
                ScheduleTimelineIssue(
                    event_id=event.id,
                    message=f"{event.port} timezone conversion is unresolved.",
                )
            )
        if departure_at is not None:
            if departure_at < arrival_at:
                issues.append(
                    ScheduleTimelineIssue(
                        event_id=event.id,
                        message=f"{event.port} departs before it arrives.",
                    )
                )
            else:
                port_stay_hours = _hours_between(arrival_at, departure_at)

        interval_from_previous_hours = None
        if previous_anchor is not None:
            if arrival_at < previous_anchor:
                issues.append(
                    ScheduleTimelineIssue(
                        event_id=event.id,
                        message=f"{event.port} occurs before the previous chronological point.",
                    )
                )
            else:
                interval_from_previous_hours = _hours_between(previous_anchor, arrival_at)

        rows.append(
            ScheduleTimelineRow(
                event=event,
                port_stay_hours=port_stay_hours,
                interval_from_previous_hours=interval_from_previous_hours,
            )
        )
        previous_anchor = departure_at if departure_at is not None and departure_at >= arrival_at else arrival_at

    return ScheduleTimeline(rows=rows, issues=issues)


def _hours_between(start, end) -> float:
    return (end - start).total_seconds() / 3600
