from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.rob import ROBQuantity, StartingROB
from fuel_consumption_calculator.repositories.database import Database


class ROBRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def load_starting_rob(self, vessel_id: int) -> StartingROB:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT fuel_type, quantity_mt
                FROM vessel_starting_rob
                WHERE vessel_id = ?
                ORDER BY fuel_type
                """,
                (vessel_id,),
            ).fetchall()
        return StartingROB(
            vessel_id=vessel_id,
            quantities=tuple(
                ROBQuantity(fuel_type=row["fuel_type"], quantity_mt=float(row["quantity_mt"]))
                for row in rows
            ),
        )

    def has_starting_rob(self, vessel_id: int) -> bool:
        """Return whether a complete aggregate projection anchor was explicitly saved."""
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(DISTINCT fuel_type) AS fuel_count
                FROM vessel_starting_rob
                WHERE vessel_id = ?
                  AND fuel_type IN ('ULSFO', 'VLSFO', 'MDO')
                """,
                (vessel_id,),
            ).fetchone()
        return bool(row and int(row["fuel_count"]) == 3)

    def save_starting_rob(self, starting_rob: StartingROB) -> StartingROB:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            for quantity in starting_rob.quantities:
                connection.execute(
                    """
                    INSERT INTO vessel_starting_rob (
                        vessel_id, fuel_type, quantity_mt, updated_at
                    )
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(vessel_id, fuel_type)
                    DO UPDATE SET
                        quantity_mt = excluded.quantity_mt,
                        updated_at = excluded.updated_at
                    """,
                    (
                        starting_rob.vessel_id,
                        quantity.fuel_type,
                        quantity.quantity_mt,
                        timestamp,
                    ),
                )
        return self.load_starting_rob(starting_rob.vessel_id)
