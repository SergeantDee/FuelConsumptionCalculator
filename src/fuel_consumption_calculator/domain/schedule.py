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
    port_timezone_id: str | None = None
    arrival_at_utc: datetime | None = None
    departure_at_utc: datetime | None = None
    timezone_status: str = "RESOLVED"


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
    port_timezone_id: str | None = None
    arrival_at_utc: datetime | None = None
    departure_at_utc: datetime | None = None
    timezone_status: str = "RESOLVED"

    @property
    def effective_arrival_at(self) -> datetime:
        return self.arrival_at_utc or self.arrival_at

    @property
    def effective_departure_at(self) -> datetime | None:
        return self.departure_at_utc or self.departure_at


@dataclass(frozen=True, slots=True)
class ScheduleEventDraft:
    sequence_number: int
    port: str
    event_type: str
    arrival_at: datetime
    departure_at: datetime | None
    source: str
    source_vessel_name: str
    source_from_date: date
    terminal: str | None = None
    port_timezone_id: str | None = None
    arrival_at_utc: datetime | None = None
    departure_at_utc: datetime | None = None
    timezone_status: str = "RESOLVED"
