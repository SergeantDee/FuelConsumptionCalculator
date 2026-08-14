from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.vessel import Vessel
from fuel_consumption_calculator.repositories.database import Database


ACTIVE_VESSEL_ID = 1


class VesselRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def get_active(self) -> Vessel | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, name, imo, created_at, updated_at FROM vessels WHERE id = ?",
                (ACTIVE_VESSEL_ID,),
            ).fetchone()
        if row is None:
            return None
        return Vessel(
            id=row["id"],
            name=row["name"],
            imo=row["imo"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def save_active(self, name: str, imo: str) -> Vessel:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO vessels (id, name, imo, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    imo = excluded.imo,
                    updated_at = excluded.updated_at
                """,
                (ACTIVE_VESSEL_ID, name, imo, timestamp, timestamp),
            )
        vessel = self.get_active()
        if vessel is None:
            raise RuntimeError("The active vessel could not be read after saving.")
        return vessel
