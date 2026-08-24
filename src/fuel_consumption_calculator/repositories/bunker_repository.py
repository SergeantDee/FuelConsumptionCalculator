from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from fuel_consumption_calculator.domain.bunker import BunkerCapacity, BunkerCapacityProfile, BunkerIncomingFuelSnapshot, BunkerQuantity, BunkerReceivingTankPlan, PlannedBunker
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.repositories.database import Database


class BunkerRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def list_plans(self, vessel_id: int) -> list[PlannedBunker]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence_number, port_snapshot, arrival_snapshot, fuel_type, quantity_mt, status
                FROM planned_bunker_quantities
                WHERE vessel_id = ?
                ORDER BY sequence_number, port_snapshot, arrival_snapshot, fuel_type
                """,
                (vessel_id,),
            ).fetchall()

        grouped: dict[tuple[int, str, str | None, str], dict[str, float]] = defaultdict(dict)
        for row in rows:
            key = (row["sequence_number"], row["port_snapshot"], row["arrival_snapshot"], row["status"])
            grouped[key][row["fuel_type"]] = float(row["quantity_mt"])
        return [
            PlannedBunker(
                vessel_id=vessel_id,
                sequence_number=sequence_number,
                port_snapshot=port_snapshot,
                arrival_snapshot=arrival_snapshot,
                quantities=tuple(
                    BunkerQuantity(fuel_type=fuel_type, quantity_mt=quantities.get(fuel_type, 0.0))
                    for fuel_type in FUEL_TYPES
                ),
                status=status,
            )
            for (sequence_number, port_snapshot, arrival_snapshot, status), quantities in grouped.items()
        ]

    def save_plan(self, plan: PlannedBunker, status: str = "DRAFT") -> PlannedBunker | None:
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
                        fuel_type, quantity_mt, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.vessel_id,
                        plan.sequence_number,
                        plan.port_snapshot,
                        plan.arrival_snapshot,
                        quantity.fuel_type,
                        quantity.quantity_mt,
                        status,
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

    def confirm_plan(self, plan: PlannedBunker) -> PlannedBunker | None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE planned_bunker_quantities
                SET status = 'CONFIRMED', updated_at = ?
                WHERE vessel_id = ?
                  AND sequence_number = ?
                  AND port_snapshot = ?
                  AND arrival_snapshot = ?
                """,
                (timestamp, plan.vessel_id, plan.sequence_number, plan.port_snapshot, plan.arrival_snapshot),
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
                connection.execute("DELETE FROM bunker_receiving_tank_plans WHERE vessel_id = ? AND sequence_number = ? AND port_snapshot = ?", (vessel_id, sequence_number, port_snapshot))
                connection.execute("DELETE FROM bunker_incoming_fuel_snapshots WHERE vessel_id = ? AND sequence_number = ? AND port_snapshot = ?", (vessel_id, sequence_number, port_snapshot))
                connection.execute(
                    """
                    DELETE FROM planned_bunker_quantities
                    WHERE vessel_id = ? AND sequence_number = ? AND port_snapshot = ?
                    """,
                    (vessel_id, sequence_number, port_snapshot),
                )
            else:
                connection.execute("DELETE FROM bunker_receiving_tank_plans WHERE vessel_id = ? AND sequence_number = ? AND port_snapshot = ? AND arrival_snapshot = ?", (vessel_id, sequence_number, port_snapshot, arrival_snapshot))
                connection.execute("DELETE FROM bunker_incoming_fuel_snapshots WHERE vessel_id = ? AND sequence_number = ? AND port_snapshot = ? AND arrival_snapshot = ?", (vessel_id, sequence_number, port_snapshot, arrival_snapshot))
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

    def list_eligible_receiving_tanks(self, vessel_id: int) -> list[tuple[FuelTank, float | None]]:
        with self._database.connect() as connection:
            rows = connection.execute("""SELECT t.*, (SELECT calculated_volume_m3 FROM tank_soundings s WHERE s.tank_id=t.id ORDER BY effective_at_utc DESC, id DESC LIMIT 1) latest_volume FROM fuel_tanks t WHERE t.vessel_id=? AND t.tank_type='BUNKER' AND t.bunker_receiving_eligible=1 AND t.is_active=1 ORDER BY t.name COLLATE NOCASE, t.id""", (vessel_id,)).fetchall()
        return [(FuelTank(row["id"], row["vessel_id"], row["name"], row["tank_type"], float(row["capacity_m3"]), row["preferred_measurement_type"], bool(row["bunker_receiving_eligible"]), bool(row["is_active"]), row["current_fuel_batch_id"], row["notes"], row["created_at"], row["updated_at"]), float(row["latest_volume"]) if row["latest_volume"] is not None else None) for row in rows]

    def list_receiving_tank_plan(self, plan: PlannedBunker) -> list[BunkerReceivingTankPlan]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT tank_id, projected_arrival_volume_m3, target_fill_percent FROM bunker_receiving_tank_plans WHERE vessel_id=? AND sequence_number=? AND port_snapshot=? AND arrival_snapshot=? ORDER BY tank_id", (plan.vessel_id, plan.sequence_number, plan.port_snapshot, plan.arrival_snapshot)).fetchall()
        return [BunkerReceivingTankPlan(row["tank_id"], row["projected_arrival_volume_m3"], float(row["target_fill_percent"])) for row in rows]

    def save_receiving_tank_plan(self, plan: PlannedBunker, rows: list[BunkerReceivingTankPlan], incoming: BunkerIncomingFuelSnapshot) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            key = (plan.vessel_id, plan.sequence_number, plan.port_snapshot, plan.arrival_snapshot)
            connection.execute("DELETE FROM bunker_receiving_tank_plans WHERE vessel_id=? AND sequence_number=? AND port_snapshot=? AND arrival_snapshot=?", key)
            connection.executemany("INSERT INTO bunker_receiving_tank_plans (vessel_id,sequence_number,port_snapshot,arrival_snapshot,tank_id,projected_arrival_volume_m3,target_fill_percent,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", [(*key, row.tank_id, row.projected_arrival_volume_m3, row.target_fill_percent, timestamp, timestamp) for row in rows])
            connection.execute("INSERT INTO bunker_incoming_fuel_snapshots (vessel_id,sequence_number,port_snapshot,arrival_snapshot,fuel_batch_id,density_15_kg_m3,manual_vcf,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(vessel_id,sequence_number,port_snapshot,arrival_snapshot) DO UPDATE SET fuel_batch_id=excluded.fuel_batch_id,density_15_kg_m3=excluded.density_15_kg_m3,manual_vcf=excluded.manual_vcf,updated_at=excluded.updated_at", (*key, incoming.fuel_batch_id, incoming.density_15_kg_m3, incoming.manual_vcf, timestamp, timestamp))
            connection.execute("UPDATE planned_bunker_quantities SET status='DRAFT', updated_at=? WHERE vessel_id=? AND sequence_number=? AND port_snapshot=? AND arrival_snapshot=? AND status='CONFIRMED'", (timestamp, *key))

    def load_incoming_fuel_snapshot(self, plan: PlannedBunker) -> BunkerIncomingFuelSnapshot:
        with self._database.connect() as connection:
            row = connection.execute("SELECT fuel_batch_id,density_15_kg_m3,manual_vcf FROM bunker_incoming_fuel_snapshots WHERE vessel_id=? AND sequence_number=? AND port_snapshot=? AND arrival_snapshot=?", (plan.vessel_id,plan.sequence_number,plan.port_snapshot,plan.arrival_snapshot)).fetchone()
        return BunkerIncomingFuelSnapshot(None,None,None) if row is None else BunkerIncomingFuelSnapshot(row["fuel_batch_id"], row["density_15_kg_m3"], row["manual_vcf"])

    def list_fuel_batches(self, vessel_id: int) -> list[FuelBatch]:
        with self._database.connect() as connection:
            rows=connection.execute("SELECT * FROM fuel_batches WHERE vessel_id=? ORDER BY batch_name COLLATE NOCASE,id",(vessel_id,)).fetchall()
        return [FuelBatch(row["id"],row["vessel_id"],row["batch_name"],row["fuel_type"],float(row["density_15_kg_m3"]),row["sulfur_percent"],row["viscosity_50_cst"],row["flash_point_c"],row["pour_point_c"],row["water_percent"],row["lab_reference"],row["bunker_port"],row["bunker_date"],row["remarks"],row["created_at"],row["updated_at"]) for row in rows]

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
