from __future__ import annotations

from datetime import date, datetime, timezone

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate, ScheduleEvent, ScheduleEventDraft
from fuel_consumption_calculator.domain.time_model import PortTimezone, local_to_utc, normalize_port_name
from fuel_consumption_calculator.repositories.database import Database


class ScheduleRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_for_vessel(self, vessel_id: int) -> list[ScheduleEvent]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, vessel_id, sequence_number, port, terminal, event_type,
                       arrival_at, departure_at, source, source_vessel_name,
                       source_from_date, created_at, updated_at,
                       port_timezone_id, arrival_at_utc, departure_at_utc, timezone_status
                FROM schedule_events
                WHERE vessel_id = ?
                ORDER BY sequence_number
                """,
                (vessel_id,),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def replace_for_vessel(self, vessel_id: int, candidates: list[ScheduleCandidate]) -> list[ScheduleEvent]:
        with self._database.connect() as connection:
            self._replace_for_vessel(connection, vessel_id, candidates)
        return self.list_for_vessel(vessel_id)

    def create_event(self, vessel_id: int, draft: ScheduleEventDraft) -> list[ScheduleEvent]:
        events = self.list_for_vessel(vessel_id)
        candidates = [self._event_to_candidate(event) for event in events]
        insert_at = max(1, min(draft.sequence_number, len(candidates) + 1))
        candidates.insert(insert_at - 1, self._draft_to_candidate(draft, insert_at))
        candidates = self._resequence(candidates)
        with self._database.connect() as connection:
            self._replace_for_vessel(connection, vessel_id, candidates)
        return self.list_for_vessel(vessel_id)

    def update_event(self, vessel_id: int, event_id: int, draft: ScheduleEventDraft) -> list[ScheduleEvent]:
        events = self.list_for_vessel(vessel_id)
        if not any(event.id == event_id for event in events):
            raise ValueError("Schedule event was not found.")
        remaining = [self._event_to_candidate(event) for event in events if event.id != event_id]
        insert_at = max(1, min(draft.sequence_number, len(remaining) + 1))
        remaining.insert(insert_at - 1, self._draft_to_candidate(draft, insert_at))
        candidates = self._resequence(remaining)
        with self._database.connect() as connection:
            self._replace_for_vessel(connection, vessel_id, candidates)
        return self.list_for_vessel(vessel_id)

    def delete_event(self, vessel_id: int, event_id: int) -> list[ScheduleEvent]:
        events = self.list_for_vessel(vessel_id)
        if not any(event.id == event_id for event in events):
            raise ValueError("Schedule event was not found.")
        candidates = self._resequence(
            [self._event_to_candidate(event) for event in events if event.id != event_id]
        )
        with self._database.connect() as connection:
            self._replace_for_vessel(connection, vessel_id, candidates)
        return self.list_for_vessel(vessel_id)

    def count_for_vessel(self, vessel_id: int) -> int:
        with self._database.connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM schedule_events WHERE vessel_id = ?",
                    (vessel_id,),
                ).fetchone()[0]
            )

    def list_port_timezones(self) -> list[PortTimezone]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT port, timezone_id FROM port_timezones ORDER BY port").fetchall()
        return [PortTimezone(row["port"], row["timezone_id"]) for row in rows]

    def save_port_timezone(self, port: str, timezone_id: str) -> PortTimezone:
        port = port.strip()
        timezone_id = timezone_id.strip()
        if not port:
            raise ValueError("Port is required.")
        if not timezone_id:
            raise ValueError("Timezone ID is required.")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO port_timezones (port_key, port, timezone_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(port_key)
                DO UPDATE SET port = excluded.port, timezone_id = excluded.timezone_id, updated_at = excluded.updated_at
                """,
                (normalize_port_name(port), port, timezone_id, timestamp, timestamp),
            )
            vessel_ids = [
                row["vessel_id"]
                for row in connection.execute(
                    "SELECT DISTINCT vessel_id FROM schedule_events WHERE port = ?",
                    (port,),
                ).fetchall()
            ]
        for vessel_id in vessel_ids:
            events = self.list_for_vessel(vessel_id)
            self.replace_for_vessel(vessel_id, [self._event_to_candidate(event) for event in events])
        return PortTimezone(port, timezone_id)

    def timezone_for_port(self, port: str) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT timezone_id FROM port_timezones WHERE port_key = ?",
                (normalize_port_name(port),),
            ).fetchone()
        return row["timezone_id"] if row else None

    def _replace_for_vessel(self, connection, vessel_id: int, candidates: list[ScheduleCandidate]) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute("DELETE FROM schedule_events WHERE vessel_id = ?", (vessel_id,))
        for candidate in candidates:
            resolved = self._resolve_candidate_timezone(candidate)
            connection.execute(
                """
                INSERT INTO schedule_events (
                    vessel_id, sequence_number, port, terminal, event_type,
                    arrival_at, departure_at, source, source_vessel_name,
                    source_from_date, created_at, updated_at,
                    port_timezone_id, arrival_at_utc, departure_at_utc, timezone_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vessel_id,
                    resolved.sequence_number,
                    resolved.port,
                    resolved.terminal,
                    resolved.event_type,
                    resolved.arrival_at.isoformat(timespec="minutes"),
                    resolved.departure_at.isoformat(timespec="minutes") if resolved.departure_at else None,
                    resolved.source,
                    resolved.source_vessel_name,
                    resolved.source_from_date.isoformat(),
                    timestamp,
                    timestamp,
                    resolved.port_timezone_id,
                    _dt_to_text(resolved.arrival_at_utc),
                    _dt_to_text(resolved.departure_at_utc),
                    resolved.timezone_status,
                ),
            )

    def _row_to_event(self, row) -> ScheduleEvent:
        return ScheduleEvent(
            id=row["id"],
            vessel_id=row["vessel_id"],
            sequence_number=row["sequence_number"],
            port=row["port"],
            terminal=row["terminal"],
            event_type=row["event_type"],
            arrival_at=datetime.fromisoformat(row["arrival_at"]),
            departure_at=datetime.fromisoformat(row["departure_at"]) if row["departure_at"] else None,
            source=row["source"],
            source_vessel_name=row["source_vessel_name"],
            source_from_date=date.fromisoformat(row["source_from_date"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            port_timezone_id=row["port_timezone_id"],
            arrival_at_utc=_text_to_dt(row["arrival_at_utc"]),
            departure_at_utc=_text_to_dt(row["departure_at_utc"]),
            timezone_status=row["timezone_status"],
        )

    def _event_to_candidate(self, event: ScheduleEvent) -> ScheduleCandidate:
        return ScheduleCandidate(
            sequence_number=event.sequence_number,
            port=event.port,
            event_type=event.event_type,
            arrival_at=event.arrival_at,
            departure_at=event.departure_at,
            source=event.source,
            source_vessel_name=event.source_vessel_name,
            source_from_date=event.source_from_date,
            terminal=event.terminal,
            port_timezone_id=event.port_timezone_id,
            arrival_at_utc=event.arrival_at_utc,
            departure_at_utc=event.departure_at_utc,
            timezone_status=event.timezone_status,
        )

    def _draft_to_candidate(self, draft: ScheduleEventDraft, sequence_number: int) -> ScheduleCandidate:
        return ScheduleCandidate(
            sequence_number=sequence_number,
            port=draft.port,
            event_type=draft.event_type,
            arrival_at=draft.arrival_at,
            departure_at=draft.departure_at,
            source=draft.source,
            source_vessel_name=draft.source_vessel_name,
            source_from_date=draft.source_from_date,
            terminal=draft.terminal,
            port_timezone_id=draft.port_timezone_id,
            arrival_at_utc=draft.arrival_at_utc,
            departure_at_utc=draft.departure_at_utc,
            timezone_status=draft.timezone_status,
        )

    def _resequence(self, candidates: list[ScheduleCandidate]) -> list[ScheduleCandidate]:
        return [
            ScheduleCandidate(
                sequence_number=index,
                port=candidate.port,
                event_type=candidate.event_type,
                arrival_at=candidate.arrival_at,
                departure_at=candidate.departure_at,
                source=candidate.source,
                source_vessel_name=candidate.source_vessel_name,
                source_from_date=candidate.source_from_date,
                terminal=candidate.terminal,
                port_timezone_id=candidate.port_timezone_id,
                arrival_at_utc=candidate.arrival_at_utc,
                departure_at_utc=candidate.departure_at_utc,
                timezone_status=candidate.timezone_status,
            )
            for index, candidate in enumerate(candidates, start=1)
        ]

    def _resolve_candidate_timezone(self, candidate: ScheduleCandidate) -> ScheduleCandidate:
        timezone_id = candidate.port_timezone_id or (self.timezone_for_port(candidate.port) if candidate.port else None)
        arrival = candidate.arrival_at_utc
        departure = candidate.departure_at_utc
        status = candidate.timezone_status
        if arrival is None:
            result = local_to_utc(candidate.arrival_at, timezone_id)
            arrival = result.utc_value
            timezone_id = result.timezone_id
            status = result.status
        if candidate.departure_at and departure is None:
            result = local_to_utc(candidate.departure_at, timezone_id)
            departure = result.utc_value
            status = result.status if result.status != "RESOLVED" else status
        if arrival is not None and (candidate.departure_at is None or departure is not None) and status == "UNRESOLVED":
            status = "RESOLVED"
        return ScheduleCandidate(
            sequence_number=candidate.sequence_number,
            port=candidate.port,
            event_type=candidate.event_type,
            arrival_at=candidate.arrival_at,
            departure_at=candidate.departure_at,
            source=candidate.source,
            source_vessel_name=candidate.source_vessel_name,
            source_from_date=candidate.source_from_date,
            terminal=candidate.terminal,
            port_timezone_id=timezone_id,
            arrival_at_utc=arrival,
            departure_at_utc=departure,
            timezone_status=status,
        )


def _dt_to_text(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat(timespec="minutes") if value and value.tzinfo else value.isoformat(timespec="minutes") if value else None


def _text_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
