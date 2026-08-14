from __future__ import annotations

from datetime import datetime

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate


LEGACY_DATE_FORMAT = "%d %b %Y %H:%M"


def parse_legacy_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text or text.upper() == "N/A":
        return None
    try:
        return datetime.strptime(text, LEGACY_DATE_FORMAT)
    except ValueError:
        return None


def validate_schedule_candidates(candidates: list[ScheduleCandidate]) -> None:
    if not candidates:
        raise ValueError("The scraper returned no schedule events.")

    seen: set[tuple[str, str, str]] = set()
    previous_arrival: datetime | None = None
    for candidate in candidates:
        if not candidate.port.strip():
            raise ValueError(f"Schedule event {candidate.sequence_number} is missing a port.")
        if not candidate.event_type.strip():
            raise ValueError(f"Schedule event {candidate.sequence_number} is missing an event type.")
        if candidate.departure_at is not None and candidate.departure_at < candidate.arrival_at:
            raise ValueError(f"Schedule event {candidate.sequence_number} departs before it arrives.")
        if previous_arrival is not None and candidate.arrival_at < previous_arrival:
            raise ValueError("Schedule events are not in chronological order.")
        previous_arrival = candidate.arrival_at
        key = (
            candidate.port.lower(),
            candidate.arrival_at.isoformat(),
            candidate.departure_at.isoformat() if candidate.departure_at else "",
        )
        if key in seen:
            raise ValueError(f"Duplicate schedule event detected for {candidate.port}.")
        seen.add(key)
