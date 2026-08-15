from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fuel_consumption_calculator.domain.bunker import BunkerCapacity, BunkerCapacityProfile, BunkerQuantity, PlannedBunker
from fuel_consumption_calculator.repositories.database import Database


class BunkerRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_plans(self, vessel_id: int) -> list[PlannedBunker]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence_number, port_snapshot, arrival_snapshot, fuel_type, quantity_mt
                FROM planned_bunker_quantities
                WHERE vessel_id = ?
                ORDER BY sequence_number, port_snapshot, arrival_snapshot, fuel_type
                """,
                (vessel_id,),
            ).fetchall()

        grouped: dict[tuple[int, str, str | None], list[BunkerQuantity]] = defaultdict(list)
        for row in rows:
            key = (row["sequence_number"], row["port_snapshot"], row["arrival_snapshot"])
            grouped[key].append(
                BunkerQuantity(fuel_type=row["fuel_type"], quantity_mt=float(row["quantity_mt"]))
            )
        return [
            PlannedBunker(
                vessel_id=vessel_id,
                sequence_number=sequence_number,
                port_snapshot=port_snapshot,
                arrival_snapshot=arrival_snapshot,
                quantities=tuple(quantities),
            )
            for (sequence_number, port_snapshot, arrival_snapshot), quantities in grouped.items()
        ]

    def save_plan(self, plan: PlannedBunker) -> PlannedBunker | None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        non_zero_quantities = [quantity for quantity in plan.quantities if quantity.quantity_mt > 0]
        with self._database.connect() as connection:
            connection.execute(
                """
                DELETE FROM planned_bunker_quantities
                WHERE vessel_id = ?
                  AND sequence_number = ?
                  AND port_snapshot = ?
                  AND arrival_snapshot = ?
                """,
                (plan.vessel_id, plan.sequence_number, plan.port_snapshot, plan.arrival_snapshot),
            )
            for quantity in non_zero_quantities:
                connection.execute(
                    """
                    INSERT INTO planned_bunker_quantities (
                        vessel_id, sequence_number, port_snapshot, arrival_snapshot,
                        fuel_type, quantity_mt, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.vessel_id,
                        plan.sequence_number,
                        plan.port_snapshot,
                        plan.arrival_snapshot,
                        quantity.fuel_type,
                        quantity.quantity_mt,
                        timestamp,
                        timestamp,
                    ),
                )
        for saved_plan in self.list_plans(plan.vessel_id):
            if (
                saved_plan.sequence_number == plan.sequence_number
                and saved_plan.port_snapshot == plan.port_snapshot
                and saved_plan.arrival_snapshot == plan.arrival_snapshot
            ):
                return saved_plan
        return None

    def clear_plan(
        self,
        vessel_id: int,
        sequence_number: int,
        port_snapshot: str,
        arrival_snapshot: str | None = None,
    ) -> None:
        with self._database.connect() as connection:
            if arrival_snapshot is None:
                connection.execute(
                    """
                    DELETE FROM planned_bunker_quantities
                    WHERE vessel_id = ? AND sequence_number = ? AND port_snapshot = ?
                    """,
                    (vessel_id, sequence_number, port_snapshot),
                )
            else:
                connection.execute(
                    """
                    DELETE FROM planned_bunker_quantities
                    WHERE vessel_id = ?
                      AND sequence_number = ?
                      AND port_snapshot = ?
                      AND arrival_snapshot = ?
                    """,
                    (vessel_id, sequence_number, port_snapshot, arrival_snapshot),
                )

    def load_capacity_profile(self, vessel_id: int) -> BunkerCapacityProfile:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT fuel_type, maximum_capacity_mt, target_fill_percent
                FROM vessel_bunker_capacities
                WHERE vessel_id = ?
                ORDER BY fuel_type
                """,
                (vessel_id,),
            ).fetchall()
        return BunkerCapacityProfile(
            vessel_id=vessel_id,
            capacities=tuple(
                BunkerCapacity(
                    fuel_type=row["fuel_type"],
                    maximum_capacity_mt=float(row["maximum_capacity_mt"]),
                    target_fill_percent=float(row["target_fill_percent"]),
                )
                for row in rows
            ),
        )

    def save_capacity_profile(self, profile: BunkerCapacityProfile) -> BunkerCapacityProfile:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            for capacity in profile.capacities:
                connection.execute(
                    """
                    INSERT INTO vessel_bunker_capacities (
                        vessel_id, fuel_type, maximum_capacity_mt,
                        target_fill_percent, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(vessel_id, fuel_type)
                    DO UPDATE SET
                        maximum_capacity_mt = excluded.maximum_capacity_mt,
                        target_fill_percent = excluded.target_fill_percent,
                        updated_at = excluded.updated_at
                    """,
                    (
                        profile.vessel_id,
                        capacity.fuel_type,
                        capacity.maximum_capacity_mt,
                        capacity.target_fill_percent,
                        timestamp,
                        timestamp,
                    ),
                )
        return self.load_capacity_profile(profile.vessel_id)
