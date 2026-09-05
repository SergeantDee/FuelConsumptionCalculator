from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, InternalFuelTransfer, TankCalibrationPoint, TankSounding, TankSoundingSurvey
from fuel_consumption_calculator.domain.bunker import BunkerTankReceipt
from fuel_consumption_calculator.domain.tank_forecast import TankConsumptionAllocationEvent, TankConsumptionPlan, TankConsumptionPlanPhase, TankConsumptionPlanPhaseTank
from fuel_consumption_calculator.repositories.database import Database


class FuelTankRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    def vessel_exists(self, vessel_id: int) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM vessels WHERE id = ?", (vessel_id,)
            ).fetchone()
        return row is not None

    def list_tanks(self, vessel_id: int, *, include_inactive: bool = False) -> list[FuelTank]:
        query = "SELECT * FROM fuel_tanks WHERE vessel_id = ?"
        if not include_inactive:
            query += " AND is_active = 1"
        query += " ORDER BY name COLLATE NOCASE, id"
        with self._database.connect() as connection:
            return [_tank_from_row(row) for row in connection.execute(query, (vessel_id,)).fetchall()]

    def get_tank(self, tank_id: int) -> FuelTank | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM fuel_tanks WHERE id = ?", (tank_id,)).fetchone()
        return _tank_from_row(row) if row else None

    def save_tank(self, tank: FuelTank) -> FuelTank:
        timestamp = _timestamp()
        with self._database.connect() as connection:
            if tank.id is None:
                cursor = connection.execute(
                    """INSERT INTO fuel_tanks (vessel_id, name, tank_type, capacity_m3, preferred_measurement_type,
                       bunker_receiving_eligible, is_active, current_fuel_batch_id, notes, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    _tank_values(tank, timestamp, timestamp),
                )
                tank_id = cursor.lastrowid
            else:
                connection.execute(
                    """UPDATE fuel_tanks SET name = ?, tank_type = ?, capacity_m3 = ?, preferred_measurement_type = ?,
                       bunker_receiving_eligible = ?, is_active = ?, current_fuel_batch_id = ?, notes = ?, updated_at = ?
                       WHERE id = ?""",
                    (tank.name, tank.tank_type, tank.capacity_m3, tank.preferred_measurement_type,
                     int(tank.bunker_receiving_eligible), int(tank.is_active), tank.current_fuel_batch_id,
                     tank.notes, timestamp, tank.id),
                )
                tank_id = tank.id
        saved = self.get_tank(tank_id)
        if saved is None:
            raise RuntimeError("Fuel tank could not be read after saving.")
        return saved

    def set_tank_active(self, tank_id: int, is_active: bool) -> FuelTank | None:
        with self._database.connect() as connection:
            connection.execute("UPDATE fuel_tanks SET is_active = ?, updated_at = ? WHERE id = ?", (int(is_active), _timestamp(), tank_id))
        return self.get_tank(tank_id)

    def assign_current_fuel_batch(self, tank_id: int, batch_id: int | None) -> FuelTank | None:
        with self._database.connect() as connection:
            connection.execute("UPDATE fuel_tanks SET current_fuel_batch_id = ?, updated_at = ? WHERE id = ?", (batch_id, _timestamp(), tank_id))
        return self.get_tank(tank_id)

    def list_fuel_batches(self, vessel_id: int) -> list[FuelBatch]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM fuel_batches WHERE vessel_id = ? ORDER BY batch_name COLLATE NOCASE, id", (vessel_id,)).fetchall()
        return [_batch_from_row(row) for row in rows]

    def get_fuel_batch(self, batch_id: int) -> FuelBatch | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM fuel_batches WHERE id = ?", (batch_id,)).fetchone()
        return _batch_from_row(row) if row else None

    def save_fuel_batch(self, batch: FuelBatch) -> FuelBatch:
        timestamp = _timestamp()
        columns = "vessel_id, batch_name, fuel_type, density_15_kg_m3, sulfur_percent, viscosity_50_cst, flash_point_c, pour_point_c, water_percent, lab_reference, bunker_port, bunker_date, remarks"
        values = _batch_values(batch)
        with self._database.connect() as connection:
            if batch.id is None:
                cursor = connection.execute(f"INSERT INTO fuel_batches ({columns}, created_at, updated_at) VALUES ({','.join('?' for _ in range(15))})", (*values, timestamp, timestamp))
                batch_id = cursor.lastrowid
            else:
                assignments = ", ".join(f"{column} = ?" for column in columns.split(", ")[1:])
                connection.execute(f"UPDATE fuel_batches SET {assignments}, updated_at = ? WHERE id = ?", (*values[1:], timestamp, batch.id))
                batch_id = batch.id
        saved = self.get_fuel_batch(batch_id)
        if saved is None:
            raise RuntimeError("Fuel batch could not be read after saving.")
        return saved

    def list_calibration_points(self, tank_id: int) -> list[TankCalibrationPoint]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM tank_calibration_points WHERE tank_id = ? ORDER BY trim_m, sounding_cm, ullage_cm, id", (tank_id,)).fetchall()
        return [_point_from_row(row) for row in rows]

    def replace_calibration_points(self, tank_id: int, points: list[TankCalibrationPoint]) -> list[TankCalibrationPoint]:
        with self._database.connect() as connection:
            connection.execute("DELETE FROM tank_calibration_points WHERE tank_id = ?", (tank_id,))
            connection.executemany(
                "INSERT INTO tank_calibration_points (tank_id, sounding_cm, ullage_cm, trim_m, volume_m3) VALUES (?, ?, ?, ?, ?)",
                [(tank_id, point.sounding_cm, point.ullage_cm, point.trim_m, point.volume_m3) for point in points],
            )
        return self.list_calibration_points(tank_id)

    def save_sounding(self, sounding: TankSounding) -> TankSounding:
        timestamp = _timestamp()
        with self._database.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO tank_soundings (tank_id, effective_at_utc, reading_type, reading_cm, trim_m, temperature_c,
                   calculated_volume_m3, calculated_density_kg_m3, calculated_mass_mt, fuel_batch_id, remarks, created_at, updated_at,
                   manual_vcf, standard_volume_15_m3, survey_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sounding.tank_id, sounding.effective_at_utc, sounding.reading_type, sounding.reading_cm, sounding.trim_m,
                 sounding.temperature_c, sounding.calculated_volume_m3, sounding.calculated_density_kg_m3,
                 sounding.calculated_mass_mt, sounding.fuel_batch_id, sounding.remarks, timestamp, timestamp,
                 sounding.manual_vcf, sounding.standard_volume_15_m3, sounding.survey_id),
            )
        return self._get_sounding(cursor.lastrowid)

    def save_survey(self, survey: TankSoundingSurvey, soundings: list[TankSounding]) -> list[TankSounding]:
        created = _timestamp()
        with self._database.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO tank_sounding_surveys (vessel_id, effective_at_utc, remarks, created_at_utc) VALUES (?, ?, ?, ?)",
                (survey.vessel_id, survey.effective_at_utc, survey.remarks, created),
            )
            survey_id = cursor.lastrowid
            sounding_ids = []
            for sounding in soundings:
                cursor = connection.execute(
                    """INSERT INTO tank_soundings (tank_id, effective_at_utc, reading_type, reading_cm, trim_m, temperature_c,
                    calculated_volume_m3, calculated_density_kg_m3, calculated_mass_mt, fuel_batch_id, remarks, created_at, updated_at,
                    manual_vcf, standard_volume_15_m3, survey_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (sounding.tank_id, sounding.effective_at_utc, sounding.reading_type, sounding.reading_cm, sounding.trim_m,
                     sounding.temperature_c, sounding.calculated_volume_m3, sounding.calculated_density_kg_m3, sounding.calculated_mass_mt,
                     sounding.fuel_batch_id, sounding.remarks, created, created, sounding.manual_vcf, sounding.standard_volume_15_m3, survey_id),
                )
                sounding_ids.append(cursor.lastrowid)
        return [self._get_sounding(sounding_id) for sounding_id in sounding_ids]

    def list_sounding_history(self, tank_id: int) -> list[TankSounding]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM tank_soundings WHERE tank_id = ? ORDER BY effective_at_utc DESC, id DESC", (tank_id,)).fetchall()
        return [_sounding_from_row(row) for row in rows]

    def get_latest_sounding(self, tank_id: int) -> TankSounding | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM tank_soundings WHERE tank_id = ? ORDER BY effective_at_utc DESC, id DESC LIMIT 1", (tank_id,)).fetchone()
        return _sounding_from_row(row) if row else None

    def get_latest_sounding_at_or_before(self, tank_id: int, effective_at_utc: str) -> TankSounding | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tank_soundings WHERE tank_id = ? AND effective_at_utc <= ? ORDER BY effective_at_utc DESC, id DESC LIMIT 1",
                (tank_id, effective_at_utc),
            ).fetchone()
        return _sounding_from_row(row) if row else None

    def list_consumption_allocation_events(self, vessel_id: int) -> list[TankConsumptionAllocationEvent]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT id, vessel_id, effective_at_utc FROM tank_consumption_allocation_events WHERE vessel_id = ? ORDER BY effective_at_utc, id",
                (vessel_id,),
            ).fetchall()
            return [
                TankConsumptionAllocationEvent(
                    row["id"], row["vessel_id"], datetime.fromisoformat(row["effective_at_utc"]),
                    tuple(item["tank_id"] for item in connection.execute(
                        "SELECT tank_id FROM tank_consumption_allocation_event_tanks WHERE event_id = ? ORDER BY tank_id", (row["id"],)
                    ).fetchall()),
                )
                for row in rows
            ]

    def save_consumption_allocation_event(self, event: TankConsumptionAllocationEvent) -> TankConsumptionAllocationEvent:
        timestamp = _timestamp()
        effective = event.effective_at_utc.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            connection.execute(
                "INSERT INTO tank_consumption_allocation_events (vessel_id, effective_at_utc, created_at) VALUES (?, ?, ?) ON CONFLICT(vessel_id, effective_at_utc) DO UPDATE SET created_at = excluded.created_at",
                (event.vessel_id, effective, timestamp),
            )
            row = connection.execute("SELECT id FROM tank_consumption_allocation_events WHERE vessel_id = ? AND effective_at_utc = ?", (event.vessel_id, effective)).fetchone()
            event_id = row["id"]
            connection.execute("DELETE FROM tank_consumption_allocation_event_tanks WHERE event_id = ?", (event_id,))
            connection.executemany(
                "INSERT INTO tank_consumption_allocation_event_tanks (event_id, tank_id) VALUES (?, ?)",
                [(event_id, tank_id) for tank_id in sorted(set(event.tank_ids))],
            )
        return next(item for item in self.list_consumption_allocation_events(event.vessel_id) if item.id == event_id)

    def get_active_consumption_plan(self, vessel_id: int, fuel_type: str) -> TankConsumptionPlan | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM tank_consumption_plans WHERE vessel_id = ? AND fuel_type = ? AND status = 'ACTIVE'",
                (vessel_id, fuel_type),
            ).fetchone()
            return self._plan_from_row(connection, row) if row else None

    def list_consumption_plans(self, vessel_id: int) -> list[TankConsumptionPlan]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM tank_consumption_plans WHERE vessel_id = ? ORDER BY fuel_type, CASE status WHEN 'ACTIVE' THEN 0 ELSE 1 END, id", (vessel_id,)).fetchall()
            return [self._plan_from_row(connection, row) for row in rows]

    def save_consumption_plan(self, plan: TankConsumptionPlan) -> TankConsumptionPlan:
        timestamp = _timestamp()
        effective = plan.effective_from_utc.astimezone(timezone.utc).isoformat(timespec="seconds")
        with self._database.connect() as connection:
            if plan.status == "ACTIVE":
                connection.execute("UPDATE tank_consumption_plans SET status = 'ARCHIVED', updated_at = ? WHERE vessel_id = ? AND fuel_type = ? AND status = 'ACTIVE'", (timestamp, plan.vessel_id, plan.fuel_type))
            cursor = connection.execute(
                "INSERT INTO tank_consumption_plans (vessel_id,fuel_type,status,effective_from_utc,remarks,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (plan.vessel_id, plan.fuel_type, plan.status, effective, plan.remarks, timestamp, timestamp),
            )
            plan_id = cursor.lastrowid
            for phase in plan.phases:
                phase_id = connection.execute(
                    "INSERT INTO tank_consumption_plan_phases (plan_id,sequence_number,end_condition,depletion_threshold_mt,remarks) VALUES (?,?,?,?,?)",
                    (plan_id, phase.sequence_number, phase.end_condition, phase.depletion_threshold_mt, phase.remarks),
                ).lastrowid
                connection.executemany(
                    "INSERT INTO tank_consumption_plan_phase_tanks (phase_id,tank_id,allocation_fraction) VALUES (?,?,?)",
                    [(phase_id, item.tank_id, item.allocation_fraction) for item in phase.tanks],
                )
            row = connection.execute("SELECT * FROM tank_consumption_plans WHERE id = ?", (plan_id,)).fetchone()
            return self._plan_from_row(connection, row)

    def _plan_from_row(self, connection, row) -> TankConsumptionPlan:
        phases = []
        for phase in connection.execute("SELECT * FROM tank_consumption_plan_phases WHERE plan_id = ? ORDER BY sequence_number", (row["id"],)).fetchall():
            tanks = tuple(TankConsumptionPlanPhaseTank(item["tank_id"], float(item["allocation_fraction"])) for item in connection.execute("SELECT tank_id, allocation_fraction FROM tank_consumption_plan_phase_tanks WHERE phase_id = ? ORDER BY tank_id", (phase["id"],)).fetchall())
            phases.append(TankConsumptionPlanPhase(phase["id"], phase["sequence_number"], tanks, phase["end_condition"], float(phase["depletion_threshold_mt"]), phase["remarks"]))
        return TankConsumptionPlan(row["id"], row["vessel_id"], row["fuel_type"], row["status"], datetime.fromisoformat(row["effective_from_utc"]), tuple(phases), row["remarks"])

    def get_internal_fuel_transfer(self, transfer_id: int) -> InternalFuelTransfer | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM internal_fuel_transfers WHERE id = ?", (transfer_id,)).fetchone()
        return _transfer_from_row(row) if row else None

    def list_internal_fuel_transfers(self, vessel_id: int) -> list[InternalFuelTransfer]:
        with self._database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM internal_fuel_transfers WHERE vessel_id = ? ORDER BY COALESCE(actual_at_utc, planned_at_utc) DESC, id DESC",
                (vessel_id,),
            ).fetchall()
        return [_transfer_from_row(row) for row in rows]

    def list_confirmed_complete_bunker_receipts(self, vessel_id: int) -> list[BunkerTankReceipt]:
        """Only complete allocations of confirmed aggregate bunker plans enter tank forecasts."""
        with self._database.connect() as connection:
            rows = connection.execute("""
                SELECT r.tank_id, r.fuel_type, r.quantity_mt, r.effective_at_utc
                FROM bunker_tank_receipts r
                JOIN planned_bunker_quantities p ON p.vessel_id=r.vessel_id
                  AND p.sequence_number=r.sequence_number AND p.port_snapshot=r.port_snapshot
                  AND p.arrival_snapshot=r.arrival_snapshot AND p.fuel_type=r.fuel_type
                WHERE r.vessel_id=? AND p.status='CONFIRMED'
                  AND ABS((SELECT COALESCE(SUM(r2.quantity_mt), 0) FROM bunker_tank_receipts r2
                           WHERE r2.vessel_id=r.vessel_id AND r2.sequence_number=r.sequence_number
                             AND r2.port_snapshot=r.port_snapshot AND r2.arrival_snapshot=r.arrival_snapshot
                             AND r2.fuel_type=r.fuel_type) - p.quantity_mt) <= 0.001
                ORDER BY r.effective_at_utc, r.id
            """, (vessel_id,)).fetchall()
        return [BunkerTankReceipt(row["tank_id"], row["fuel_type"], float(row["quantity_mt"]), row["effective_at_utc"]) for row in rows]

    def save_internal_fuel_transfer(self, transfer: InternalFuelTransfer) -> InternalFuelTransfer:
        timestamp = _timestamp()
        values = (transfer.vessel_id, transfer.from_tank_id, transfer.to_tank_id, transfer.fuel_type,
                  transfer.quantity_mt, transfer.status, transfer.planned_at_utc, transfer.actual_at_utc, transfer.remarks)
        with self._database.connect() as connection:
            if transfer.id is None:
                cursor = connection.execute(
                    """INSERT INTO internal_fuel_transfers
                    (vessel_id, from_tank_id, to_tank_id, fuel_type, quantity_mt, status, planned_at_utc, actual_at_utc, remarks, created_at_utc, updated_at_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (*values, timestamp, timestamp),
                )
                transfer_id = cursor.lastrowid
            else:
                connection.execute(
                    """UPDATE internal_fuel_transfers SET from_tank_id = ?, to_tank_id = ?, fuel_type = ?, quantity_mt = ?,
                    status = ?, planned_at_utc = ?, actual_at_utc = ?, remarks = ?, updated_at_utc = ? WHERE id = ?""",
                    (transfer.from_tank_id, transfer.to_tank_id, transfer.fuel_type, transfer.quantity_mt,
                     transfer.status, transfer.planned_at_utc, transfer.actual_at_utc, transfer.remarks, timestamp, transfer.id),
                )
                transfer_id = transfer.id
        saved = self.get_internal_fuel_transfer(transfer_id)
        if saved is None:
            raise RuntimeError("Internal fuel transfer could not be read after saving.")
        return saved

    def delete_internal_fuel_transfer(self, transfer_id: int) -> None:
        with self._database.connect() as connection:
            connection.execute("DELETE FROM internal_fuel_transfers WHERE id = ?", (transfer_id,))

    def _get_sounding(self, sounding_id: int) -> TankSounding:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM tank_soundings WHERE id = ?", (sounding_id,)).fetchone()
        if row is None:
            raise RuntimeError("Tank sounding could not be read after saving.")
        return _sounding_from_row(row)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tank_values(tank: FuelTank, created_at: str, updated_at: str) -> tuple[object, ...]:
    return (tank.vessel_id, tank.name, tank.tank_type, tank.capacity_m3, tank.preferred_measurement_type,
            int(tank.bunker_receiving_eligible), int(tank.is_active), tank.current_fuel_batch_id, tank.notes, created_at, updated_at)


def _batch_values(batch: FuelBatch) -> tuple[object, ...]:
    return (batch.vessel_id, batch.batch_name, batch.fuel_type, batch.density_15_kg_m3, batch.sulfur_percent,
            batch.viscosity_50_cst, batch.flash_point_c, batch.pour_point_c, batch.water_percent,
            batch.lab_reference, batch.bunker_port, batch.bunker_date, batch.remarks)


def _tank_from_row(row) -> FuelTank:
    return FuelTank(row["id"], row["vessel_id"], row["name"], row["tank_type"], float(row["capacity_m3"]),
                    row["preferred_measurement_type"], bool(row["bunker_receiving_eligible"]), bool(row["is_active"]),
                    row["current_fuel_batch_id"], row["notes"], row["created_at"], row["updated_at"])


def _batch_from_row(row) -> FuelBatch:
    return FuelBatch(row["id"], row["vessel_id"], row["batch_name"], row["fuel_type"], float(row["density_15_kg_m3"]),
                     row["sulfur_percent"], row["viscosity_50_cst"], row["flash_point_c"], row["pour_point_c"], row["water_percent"],
                     row["lab_reference"], row["bunker_port"], row["bunker_date"], row["remarks"], row["created_at"], row["updated_at"])


def _point_from_row(row) -> TankCalibrationPoint:
    return TankCalibrationPoint(row["id"], row["tank_id"], row["sounding_cm"], row["ullage_cm"], float(row["trim_m"]), float(row["volume_m3"]))


def _sounding_from_row(row) -> TankSounding:
    return TankSounding(row["id"], row["tank_id"], row["effective_at_utc"], row["reading_type"], float(row["reading_cm"]),
                         float(row["trim_m"]), row["temperature_c"], float(row["calculated_volume_m3"]), row["calculated_density_kg_m3"],
                         row["calculated_mass_mt"], row["fuel_batch_id"], row["remarks"], row["created_at"], row["updated_at"],
                         row["manual_vcf"], row["standard_volume_15_m3"], row["survey_id"])


def _transfer_from_row(row) -> InternalFuelTransfer:
    return InternalFuelTransfer(
        row["id"], row["vessel_id"], row["from_tank_id"], row["to_tank_id"], row["fuel_type"],
        float(row["quantity_mt"]), row["status"], row["planned_at_utc"], row["actual_at_utc"], row["remarks"],
        row["created_at_utc"], row["updated_at_utc"],
    )
