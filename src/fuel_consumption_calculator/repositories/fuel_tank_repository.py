from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint, TankSounding
from fuel_consumption_calculator.repositories.database import Database


class FuelTankRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

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
                   manual_vcf, standard_volume_15_m3)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sounding.tank_id, sounding.effective_at_utc, sounding.reading_type, sounding.reading_cm, sounding.trim_m,
                 sounding.temperature_c, sounding.calculated_volume_m3, sounding.calculated_density_kg_m3,
                 sounding.calculated_mass_mt, sounding.fuel_batch_id, sounding.remarks, timestamp, timestamp,
                 sounding.manual_vcf, sounding.standard_volume_15_m3),
            )
        return self._get_sounding(cursor.lastrowid)

    def list_sounding_history(self, tank_id: int) -> list[TankSounding]:
        with self._database.connect() as connection:
            rows = connection.execute("SELECT * FROM tank_soundings WHERE tank_id = ? ORDER BY effective_at_utc DESC, id DESC", (tank_id,)).fetchall()
        return [_sounding_from_row(row) for row in rows]

    def get_latest_sounding(self, tank_id: int) -> TankSounding | None:
        with self._database.connect() as connection:
            row = connection.execute("SELECT * FROM tank_soundings WHERE tank_id = ? ORDER BY effective_at_utc DESC, id DESC LIMIT 1", (tank_id,)).fetchone()
        return _sounding_from_row(row) if row else None

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
                         row["manual_vcf"], row["standard_volume_15_m3"])
