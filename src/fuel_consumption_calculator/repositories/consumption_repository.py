from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.consumption import ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.repositories.database import Database


class ConsumptionRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def load_profile(self, vessel_id: int) -> ConsumptionProfile:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT operating_mode, fuel_type, rate_mt_per_day
                FROM vessel_consumption_rates
                WHERE vessel_id = ?
                ORDER BY operating_mode, fuel_type
                """,
                (vessel_id,),
            ).fetchall()
        return ConsumptionProfile(
            vessel_id=vessel_id,
            rates=tuple(
                ConsumptionRate(
                    operating_mode=row["operating_mode"],
                    fuel_type=row["fuel_type"],
                    rate_mt_per_day=float(row["rate_mt_per_day"]),
                )
                for row in rows
            ),
        )

    def save_profile(self, profile: ConsumptionProfile) -> ConsumptionProfile:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            for rate in profile.rates:
                connection.execute(
                    """
                    INSERT INTO vessel_consumption_rates (
                        vessel_id, operating_mode, fuel_type, rate_mt_per_day,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vessel_id, operating_mode, fuel_type)
                    DO UPDATE SET
                        rate_mt_per_day = excluded.rate_mt_per_day,
                        updated_at = excluded.updated_at
                    """,
                    (
                        profile.vessel_id,
                        rate.operating_mode,
                        rate.fuel_type,
                        rate.rate_mt_per_day,
                        timestamp,
                        timestamp,
                    ),
                )
        return self.load_profile(profile.vessel_id)
