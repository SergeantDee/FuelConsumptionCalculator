from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from fuel_consumption_calculator.config import SCHEMA_VERSION
from fuel_consumption_calculator.domain.fuel_tank import FuelTank, TankSounding
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService, FuelTankValidationError
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService


START = datetime(2026, 9, 8, 8, tzinfo=timezone.utc)


def _tank_service(tmp_path):
    database = Database(tmp_path / "manual-rob.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("MV Test", "1234567")
    repository = FuelTankRepository(database)
    service = FuelTankService(repository)
    tank = service.create_tank(FuelTank(None, vessel.id, "Bunker 1P", "BUNKER", 500, "SOUNDING"))
    return database, repository, service, tank


def _interval(start: datetime, end: datetime, vlsfo: float) -> FuelDepletionInterval:
    return FuelDepletionInterval(start, end, {"ULSFO": 0.0, "VLSFO": vlsfo, "MDO": 0.0})


def test_fresh_database_initializes_directly_to_schema_22(tmp_path):
    database = Database(tmp_path / "fresh.db")
    database.initialize()
    with database.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tank_mass_observations)")}
    assert SCHEMA_VERSION == version == 22
    assert "tank_mass_observations" in tables
    assert {"tank_id", "observed_at_utc", "fuel_type", "mass_mt", "source", "remarks", "created_at_utc"} <= columns


def test_schema_21_migrates_additively_and_preserves_historical_sounding(tmp_path):
    database_file = tmp_path / "v21.db"
    with sqlite3.connect(database_file) as connection:
        connection.executescript(
            """
            CREATE TABLE vessels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, imo TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE port_timezones (port_key TEXT PRIMARY KEY, port TEXT NOT NULL, timezone_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, port TEXT NOT NULL, arrival_at TEXT NOT NULL, departure_at TEXT, arrival_at_utc TEXT, departure_at_utc TEXT, port_timezone_id TEXT, timezone_status TEXT);
            CREATE TABLE fuel_tanks (id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL, name TEXT NOT NULL);
            CREATE TABLE tank_soundings (
                id INTEGER PRIMARY KEY, tank_id INTEGER NOT NULL, effective_at_utc TEXT NOT NULL,
                reading_type TEXT NOT NULL, reading_cm REAL NOT NULL, trim_m REAL NOT NULL,
                temperature_c REAL, calculated_volume_m3 REAL NOT NULL,
                calculated_density_kg_m3 REAL, calculated_mass_mt REAL, fuel_batch_id INTEGER,
                remarks TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                manual_vcf REAL, standard_volume_15_m3 REAL, survey_id INTEGER
            );
            INSERT INTO vessels VALUES (1, 'Existing', '1234567', 'x', 'x');
            INSERT INTO fuel_tanks VALUES (7, 1, 'Existing tank');
            INSERT INTO tank_soundings VALUES (9, 7, '2026-09-01T00:00:00+00:00', 'SOUNDING', 42, 0, 25, 123.4, 950, 115.2, NULL, 'preserve me', 'x', 'x', 0.985, 121.53, NULL);
            INSERT INTO application_metadata VALUES ('schema_version', '21');
            PRAGMA user_version = 21;
            """
        )
    Database(database_file).initialize()
    with sqlite3.connect(database_file) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        sounding = connection.execute(
            "SELECT id, reading_type, reading_cm, calculated_volume_m3, calculated_mass_mt, remarks FROM tank_soundings WHERE id = 9"
        ).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM tank_mass_observations").fetchone()[0]
    assert version == 22
    assert sounding == (9, "SOUNDING", 42.0, 123.4, 115.2, "preserve me")
    assert count == 0


def test_manual_mass_needs_no_calibration_temperature_density_vcf_or_batch(tmp_path):
    _database, _repository, service, tank = _tank_service(tmp_path)
    saved = service.save_manual_tank_rob(
        tank_id=tank.id, fuel_type="VLSFO", mass_mt=100, observed_at_utc=START
    )
    assert saved.mass_mt == 100
    assert saved.fuel_type == "VLSFO"
    assert saved.source == "MANUAL_INITIAL_ROB"


def test_manual_zero_is_known_and_negative_mass_is_rejected(tmp_path):
    _database, _repository, service, tank = _tank_service(tmp_path)
    zero = service.save_manual_tank_rob(
        tank_id=tank.id, fuel_type="MDO", mass_mt=0.0, observed_at_utc=START
    )
    assert service.get_latest_physical_mass_anchor(tank.id).mass_mt == zero.mass_mt == 0.0
    with pytest.raises(FuelTankValidationError, match="at least 0"):
        service.save_manual_tank_rob(tank_id=tank.id, fuel_type="MDO", mass_mt=-0.01)


def test_manual_anchor_survives_restart_and_is_aggregate_neutral(tmp_path):
    database, _repository, service, tank = _tank_service(tmp_path)
    service.save_manual_tank_rob(tank_id=tank.id, fuel_type="ULSFO", mass_mt=45, observed_at_utc=START)
    restarted = FuelTankService(FuelTankRepository(database))
    assert restarted.get_latest_physical_mass_anchor(tank.id).mass_mt == 45
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM vessel_starting_rob").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM actual_rob_observations").fetchone()[0] == 0


def test_later_sounding_reanchors_manual_mass_forecast(tmp_path):
    _database, repository, service, tank = _tank_service(tmp_path)
    service.save_manual_tank_rob(tank_id=tank.id, fuel_type="VLSFO", mass_mt=100, observed_at_utc=START)
    service.apply_consumption_tanks(1, [tank.id], START)
    sounding_at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    repository.save_sounding(TankSounding(None, tank.id, sounding_at.isoformat(), "SOUNDING", 1, 0, None, 100, calculated_mass_mt=92))
    target = sounding_at + timedelta(hours=2)
    forecast = service.predict_tank_rob_at(1, target, [_interval(START, target, 30)])[0]
    assert forecast.anchor_effective_at_utc == sounding_at
    assert forecast.anchor_mass_mt == 92
    assert forecast.predicted_mass_mt == pytest.approx(90)


def test_later_manual_observation_supersedes_older_sounding(tmp_path):
    _database, repository, service, tank = _tank_service(tmp_path)
    repository.save_sounding(TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 100, calculated_mass_mt=90))
    later = START + timedelta(hours=1)
    service.save_manual_tank_rob(tank_id=tank.id, fuel_type="VLSFO", mass_mt=88, observed_at_utc=later)
    anchor = service.get_latest_physical_mass_anchor_at_or_before(tank.id, later)
    assert (anchor.source, anchor.mass_mt) == ("MANUAL_INITIAL_ROB", 88)


def test_equal_time_sounding_deterministically_beats_manual_observation(tmp_path):
    _database, repository, service, tank = _tank_service(tmp_path)
    service.save_manual_tank_rob(tank_id=tank.id, fuel_type="VLSFO", mass_mt=88, observed_at_utc=START)
    sounding = repository.save_sounding(
        TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 100, calculated_mass_mt=90)
    )
    anchor = service.get_latest_physical_mass_anchor_at_or_before(tank.id, START)
    assert anchor.source == "SOUNDING"
    assert anchor.source_id == sounding.id
    assert anchor.mass_mt == 90


def test_manual_anchor_supplies_fuel_basis_and_supports_mass_forecast(tmp_path):
    _database, _repository, service, tank = _tank_service(tmp_path)
    service.save_manual_tank_rob(tank_id=tank.id, fuel_type="VLSFO", mass_mt=100, observed_at_utc=START)
    service.apply_consumption_tanks(1, [tank.id], START)
    target = START + timedelta(hours=10)
    forecast = service.predict_tank_rob_at(1, target, [_interval(START, target, 10)])[0]
    assert forecast.fuel_type == "VLSFO"
    assert forecast.anchor_mass_mt == 100
    assert forecast.predicted_mass_mt == pytest.approx(90)


def test_manual_mass_has_no_volume_basis_and_later_sounding_restores_it(tmp_path):
    _database, repository, service, tank = _tank_service(tmp_path)
    service.save_manual_tank_rob(tank_id=tank.id, fuel_type="VLSFO", mass_mt=100, observed_at_utc=START)
    forecast_service = TankForecastService(service, None, None, None)
    assert forecast_service.anchor_sounding_at(tank.id, START) is None

    later = START + timedelta(hours=1)
    sounding = repository.save_sounding(
        TankSounding(None, tank.id, later.isoformat(), "SOUNDING", 1, 0, None, 80, calculated_mass_mt=72)
    )
    assert forecast_service.anchor_sounding_at(tank.id, later) == sounding


def test_newer_manual_mass_removes_older_sounding_volume_authority(tmp_path):
    _database, repository, service, tank = _tank_service(tmp_path)
    repository.save_sounding(
        TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 80, calculated_mass_mt=72)
    )
    later = START + timedelta(hours=1)
    service.save_manual_tank_rob(tank_id=tank.id, fuel_type="VLSFO", mass_mt=70, observed_at_utc=later)
    forecast_service = TankForecastService(service, None, None, None)
    assert forecast_service.anchor_sounding_at(tank.id, later) is None
