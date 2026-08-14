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
    ordered_events = sorted(events, key=lambda event: (event.sequence_number, event.arrival_at, event.id))
    rows: list[ScheduleTimelineRow] = []
    issues: list[ScheduleTimelineIssue] = []
    previous_anchor = None

    for event in ordered_events:
        port_stay_hours = None
        if event.departure_at is not None:
            if event.departure_at < event.arrival_at:
                issues.append(
                    ScheduleTimelineIssue(
                        event_id=event.id,
                        message=f"{event.port} departs before it arrives.",
                    )
                )
            else:
                port_stay_hours = _hours_between(event.arrival_at, event.departure_at)

        interval_from_previous_hours = None
        if previous_anchor is not None:
            if event.arrival_at < previous_anchor:
                issues.append(
                    ScheduleTimelineIssue(
                        event_id=event.id,
                        message=f"{event.port} occurs before the previous chronological point.",
                    )
                )
            else:
                interval_from_previous_hours = _hours_between(previous_anchor, event.arrival_at)

        rows.append(
            ScheduleTimelineRow(
                event=event,
                port_stay_hours=port_stay_hours,
                interval_from_previous_hours=interval_from_previous_hours,
            )
        )
        previous_anchor = event.departure_at if event.departure_at is not None and event.departure_at >= event.arrival_at else event.arrival_at

    return ScheduleTimeline(rows=rows, issues=issues)


def _hours_between(start, end) -> float:
    return (end - start).total_seconds() / 3600
