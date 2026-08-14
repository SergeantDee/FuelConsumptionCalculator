from __future__ import annotations

from datetime import date, datetime, timezone

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate, ScheduleEvent, ScheduleEventDraft
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
                       source_from_date, created_at, updated_at
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

    def _replace_for_vessel(self, connection, vessel_id: int, candidates: list[ScheduleCandidate]) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        connection.execute("DELETE FROM schedule_events WHERE vessel_id = ?", (vessel_id,))
        for candidate in candidates:
            connection.execute(
                """
                INSERT INTO schedule_events (
                    vessel_id, sequence_number, port, terminal, event_type,
                    arrival_at, departure_at, source, source_vessel_name,
                    source_from_date, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vessel_id,
                    candidate.sequence_number,
                    candidate.port,
                    candidate.terminal,
                    candidate.event_type,
                    candidate.arrival_at.isoformat(timespec="minutes"),
                    candidate.departure_at.isoformat(timespec="minutes") if candidate.departure_at else None,
                    candidate.source,
                    candidate.source_vessel_name,
                    candidate.source_from_date.isoformat(),
                    timestamp,
                    timestamp,
                ),
            )

    def count_for_vessel(self, vessel_id: int) -> int:
        with self._database.connect() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM schedule_events WHERE vessel_id = ?",
                    (vessel_id,),
                ).fetchone()[0]
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
            )
            for index, candidate in enumerate(candidates, start=1)
        ]
