from __future__ import annotations

from datetime import date, datetime

from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline


def event(
    sequence: int,
    *,
    arrival_at: datetime,
    departure_at: datetime | None,
    port: str = "Santos",
) -> ScheduleEvent:
    return ScheduleEvent(
        id=sequence,
        vessel_id=1,
        sequence_number=sequence,
        port=port,
        event_type="Port Call",
        arrival_at=arrival_at,
        departure_at=departure_at,
        source="manual",
        source_vessel_name="Maersk Labrea",
        source_from_date=date(2026, 9, 1),
        created_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00",
    )


def test_timeline_calculates_port_stay_duration():
    timeline = build_schedule_timeline(
        [
            event(
                1,
                arrival_at=datetime(2026, 9, 1, 8, 0),
                departure_at=datetime(2026, 9, 1, 20, 30),
            )
        ]
    )

    assert timeline.rows[0].port_stay_hours == 12.5
    assert timeline.rows[0].interval_from_previous_hours is None
    assert timeline.issues == []


def test_timeline_calculates_interval_from_previous_departure():
    timeline = build_schedule_timeline(
        [
            event(2, port="Second", arrival_at=datetime(2026, 9, 3, 8, 0), departure_at=None),
            event(1, port="First", arrival_at=datetime(2026, 9, 1, 8, 0), departure_at=datetime(2026, 9, 1, 20, 0)),
        ]
    )

    assert [row.event.port for row in timeline.rows] == ["First", "Second"]
    assert timeline.rows[1].interval_from_previous_hours == 36
    assert timeline.issues == []


def test_timeline_detects_reverse_chronology():
    timeline = build_schedule_timeline(
        [
            event(1, port="First", arrival_at=datetime(2026, 9, 2, 8, 0), departure_at=datetime(2026, 9, 2, 20, 0)),
            event(2, port="Second", arrival_at=datetime(2026, 9, 1, 8, 0), departure_at=None),
        ]
    )

    assert timeline.rows[1].interval_from_previous_hours is None
    assert len(timeline.issues) == 1
    assert "before the previous chronological point" in timeline.issues[0].message
