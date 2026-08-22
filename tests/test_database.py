from __future__ import annotations

import sqlite3

from fuel_consumption_calculator.config import SCHEMA_VERSION
from fuel_consumption_calculator.repositories.database import Database


def test_database_initialization_creates_deterministic_schema(tmp_path):
    database_file = tmp_path / "data" / "test.db"
    database = Database(database_file)

    database.initialize()
    database.initialize()

    assert database_file.is_file()
    with sqlite3.connect(database_file) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        schema_version = connection.execute(
            "SELECT value FROM application_metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert {
        "vessels",
        "application_metadata",
        "schedule_events",
        "vessel_consumption_rates",
        "vessel_starting_rob",
        "planned_bunker_quantities",
        "vessel_bunker_capacities",
        "route_definitions",
        "voyage_leg_overrides",
        "vessel_speed_consumption_points",
        "vessel_energy_config",
        "generator_sfoc_points",
    }.issubset(tables)
    assert schema_version == str(SCHEMA_VERSION)
    assert user_version == SCHEMA_VERSION


def test_schema_migration_v10_to_v11_preserves_energy_config_and_leaves_maneuvering_unconfigured(tmp_path):
    database_file = tmp_path / "v10.db"
    with sqlite3.connect(database_file) as connection:
        connection.executescript(
            """
            CREATE TABLE vessels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, imo TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE vessel_energy_config (
                vessel_id INTEGER PRIMARY KEY,
                port_base_load_kw REAL NOT NULL DEFAULT 0, sea_base_load_kw REAL NOT NULL DEFAULT 0,
                reefer_kw_per_unit REAL NOT NULL DEFAULT 0, generator_rated_kw REAL NOT NULL DEFAULT 0,
                port_running_generators REAL NOT NULL DEFAULT 0, sea_running_generators REAL NOT NULL DEFAULT 0,
                aux_boiler_mt_per_hour REAL NOT NULL DEFAULT 0, generator_fuel_type TEXT NOT NULL DEFAULT 'MDO',
                boiler_fuel_type TEXT NOT NULL DEFAULT 'MDO', main_engine_slip_percent REAL NOT NULL DEFAULT 10,
                speed_rpm_factor REAL NOT NULL DEFAULT 0.3221598, power_coefficient REAL NOT NULL DEFAULT 0.0967741935483871,
                mcr_power_kw REAL NOT NULL DEFAULT 38880, port_ambient_c REAL NOT NULL DEFAULT 20,
                sea_ambient_c REAL NOT NULL DEFAULT 20, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE port_timezones (port_key TEXT PRIMARY KEY, port TEXT NOT NULL, timezone_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, port TEXT NOT NULL, arrival_at TEXT NOT NULL, departure_at TEXT, arrival_at_utc TEXT, timezone_status TEXT);
            INSERT INTO vessels VALUES (1, 'Existing Vessel', '7654321', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            INSERT INTO vessel_energy_config (vessel_id, sea_base_load_kw, created_at, updated_at) VALUES (1, 123.0, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            PRAGMA user_version = 10;
            """
        )

    Database(database_file).initialize()

    with sqlite3.connect(database_file) as connection:
        row = connection.execute(
            "SELECT sea_base_load_kw, maneuvering_main_engine_mt_per_hour, maneuvering_generators_mt_per_hour, maneuvering_aux_boiler_mt_per_hour FROM vessel_energy_config WHERE vessel_id = 1"
        ).fetchone()
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert row == (123.0, None, None, None)
    assert user_version == SCHEMA_VERSION
