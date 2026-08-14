from __future__ import annotations

from datetime import date, datetime, timezone

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate, ScheduleEvent
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
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
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
        return self.list_for_vessel(vessel_id)

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
