from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class ScheduleCandidate:
    sequence_number: int
    port: str
    event_type: str
    arrival_at: datetime
    departure_at: datetime | None
    source: str
    source_vessel_name: str
    source_from_date: date
    terminal: str | None = None


@dataclass(frozen=True, slots=True)
class ScheduleEvent:
    id: int
    vessel_id: int
    sequence_number: int
    port: str
    event_type: str
    arrival_at: datetime
    departure_at: datetime | None
    source: str
    source_vessel_name: str
    source_from_date: date
    created_at: str
    updated_at: str
    terminal: str | None = None
