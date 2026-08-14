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
