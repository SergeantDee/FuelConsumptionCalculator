from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from math import inf, nan

import pytest

from fuel_consumption_calculator.calculations.tank_calibration_engine import CalibrationError, calculate_calibrated_volume_m3
from fuel_consumption_calculator.calculations.automatic_vcf import calculate_automatic_vcf
from fuel_consumption_calculator.config import SCHEMA_VERSION
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService, FuelTankValidationError


def point(reading: float, trim: float, volume: float, *, ullage: bool = False) -> TankCalibrationPoint:
    return TankCalibrationPoint(None, 1, None if ullage else reading, reading if ullage else None, trim, volume)


def test_calibration_interpolation_behaviors():
    grid = [point(0, -1, 0), point(0, 1, 10), point(100, -1, 100), point(100, 1, 130)]
    assert calculate_calibrated_volume_m3(grid, "SOUNDING", 0, -1) == 0
    assert calculate_calibrated_volume_m3(grid, "SOUNDING", 50, -1) == 50
    assert calculate_calibrated_volume_m3(grid, "SOUNDING", 0, 0) == 5
    assert calculate_calibrated_volume_m3(grid, "SOUNDING", 50, 0) == 60
    ullage_grid = [point(0, 0, 100, ullage=True), point(100, 0, 0, ullage=True)]
    assert calculate_calibrated_volume_m3(ullage_grid, "ULLAGE", 50, 0) == 50


def test_calibration_rejects_out_of_range_and_missing_corner():
    grid = [point(0, -1, 0), point(0, 1, 10), point(100, -1, 100), point(100, 1, 130)]
    with pytest.raises(CalibrationError, match="outside"):
        calculate_calibrated_volume_m3(grid, "SOUNDING", 101, 0)
    with pytest.raises(CalibrationError, match="outside"):
        calculate_calibrated_volume_m3(grid, "SOUNDING", 50, 2)
    with pytest.raises(CalibrationError, match="missing required"):
        calculate_calibrated_volume_m3(grid[:-1], "SOUNDING", 50, 0)


def test_calibration_engine_rejects_duplicate_selected_axis_points_and_non_finite_values():
    with pytest.raises(CalibrationError, match="duplicate sounding"):
        calculate_calibrated_volume_m3([
            TankCalibrationPoint(None, 1, 0, 100, 0, 0),
            TankCalibrationPoint(None, 1, 0, 90, 0, 1),
        ], "SOUNDING", 0, 0)
    valid = [point(0, 0, 0), point(100, 0, 100)]
    for reading, trim in ((nan, 0), (inf, 0), (0, nan), (0, -inf)):
        with pytest.raises(CalibrationError, match="finite"):
            calculate_calibrated_volume_m3(valid, "SOUNDING", reading, trim)
    for invalid_point in (
        TankCalibrationPoint(None, 1, nan, None, 0, 0),
        TankCalibrationPoint(None, 1, 0, None, inf, 0),
        TankCalibrationPoint(None, 1, 0, None, 0, nan),
    ):
        with pytest.raises(CalibrationError, match="finite"):
            calculate_calibrated_volume_m3([invalid_point], "SOUNDING", 0, 0)


def test_fresh_database_and_v11_migration_include_fuel_tanks(tmp_path):
    fresh_file = tmp_path / "fresh.db"
    Database(fresh_file).initialize()
    with sqlite3.connect(fresh_file) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"fuel_batches", "fuel_tanks", "tank_calibration_points", "tank_soundings"}.issubset(tables)

    legacy_file = tmp_path / "v11.db"
    with sqlite3.connect(legacy_file) as connection:
        connection.executescript("""
            CREATE TABLE vessels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, imo TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE port_timezones (port_key TEXT PRIMARY KEY, port TEXT NOT NULL, timezone_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, port TEXT NOT NULL, arrival_at TEXT NOT NULL, departure_at TEXT, arrival_at_utc TEXT, timezone_status TEXT);
            INSERT INTO vessels VALUES (1, 'Existing Vessel', '1234567', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            PRAGMA user_version = 11;
        """)
    Database(legacy_file).initialize()
    with sqlite3.connect(legacy_file) as connection:
        assert connection.execute("SELECT name FROM vessels WHERE id = 1").fetchone()[0] == "Existing Vessel"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_tank_batch_calibration_and_sounding_workflow(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO vessels (id, name, imo, created_at, updated_at) VALUES (1, 'Test Vessel', '1234567', 'x', 'x')")
        connection.execute("INSERT INTO vessels (id, name, imo, created_at, updated_at) VALUES (2, 'Other Vessel', '7654321', 'x', 'x')")
    service = FuelTankService(FuelTankRepository(database))
    batch = service.create_fuel_batch(FuelBatch(None, 1, "Singapore Aug", "VLSFO", 991.2, water_percent=0.1))
    tank = service.create_tank(FuelTank(None, 1, "No. 1 P/S", "BUNKER", 500, "SOUNDING"))
    tank = service.assign_current_fuel_batch(tank.id, batch.id)
    assert tank.current_fuel_batch_id == batch.id
    assert service.list_tanks(1) == [tank]
    service.replace_calibration_points(tank.id, [
        TankCalibrationPoint(None, tank.id, 0, None, 0, 0),
        TankCalibrationPoint(None, tank.id, 100, None, 0, 100),
    ])
    later = service.save_sounding_observation(
        tank_id=tank.id, reading_type="SOUNDING", reading_cm=50, trim_m=0, temperature_c=42,
        fuel_batch_id=batch.id, effective_at_utc=datetime(2026, 8, 2, tzinfo=timezone.utc), remarks="No issues",
    )
    earlier = service.save_sounding_observation(
        tank_id=tank.id, reading_type="SOUNDING", reading_cm=25, trim_m=0,
        effective_at_utc="2026-08-01T00:00:00+00:00",
    )
    assert later.calculated_volume_m3 == 50
    expected_vcf = calculate_automatic_vcf(batch.density_15_kg_m3, 42, batch.fuel_type)
    assert later.standard_volume_15_m3 == pytest.approx(50 * expected_vcf)
    assert later.calculated_density_kg_m3 == batch.density_15_kg_m3
    assert later.calculated_mass_mt == pytest.approx(50 * expected_vcf * batch.density_15_kg_m3 / 1000)
    assert later.temperature_c == 42 and later.fuel_batch_id == batch.id
    assert later.effective_at_utc.endswith("+00:00")
    assert service.get_latest_sounding(tank.id) == later
    assert service.list_sounding_history(tank.id) == [later, earlier]
    assert service.set_tank_active(tank.id, False).is_active is False


def test_calibration_duplicate_axes_and_vessel_ownership_updates_are_rejected(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute("INSERT INTO vessels (id, name, imo, created_at, updated_at) VALUES (1, 'Test Vessel', '1234567', 'x', 'x')")
        connection.execute("INSERT INTO vessels (id, name, imo, created_at, updated_at) VALUES (2, 'Other Vessel', '7654321', 'x', 'x')")
    service = FuelTankService(FuelTankRepository(database))
    tank = service.create_tank(FuelTank(None, 1, "No. 1 P/S", "BUNKER", 500, "SOUNDING"))
    with pytest.raises(FuelTankValidationError, match="duplicate sounding"):
        service.replace_calibration_points(tank.id, [
            TankCalibrationPoint(None, tank.id, 10, 100, 0, 10),
            TankCalibrationPoint(None, tank.id, 10, 90, 0, 11),
        ])
    with pytest.raises(FuelTankValidationError, match="duplicate ullage"):
        service.replace_calibration_points(tank.id, [
            TankCalibrationPoint(None, tank.id, 10, 100, 0, 10),
            TankCalibrationPoint(None, tank.id, 20, 100, 0, 11),
        ])
    batch = service.create_fuel_batch(FuelBatch(None, 1, "Singapore Aug", "VLSFO", 991.2))
    with pytest.raises(FuelTankValidationError, match="tank vessel ownership"):
        service.update_tank(replace(tank, vessel_id=2))
    with pytest.raises(FuelTankValidationError, match="batch vessel ownership"):
        service.update_fuel_batch(replace(batch, vessel_id=2))
