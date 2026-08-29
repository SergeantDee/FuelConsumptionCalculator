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
        "internal_fuel_transfers",
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


def test_schema_version_is_19():
    assert SCHEMA_VERSION == 19


def test_schema_migration_v12_to_v13_adds_nullable_manual_vcf_snapshots_and_preserves_data(tmp_path):
    database_file = tmp_path / "v12.db"
    with sqlite3.connect(database_file) as connection:
        connection.executescript("""
            CREATE TABLE vessels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, imo TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE port_timezones (port_key TEXT PRIMARY KEY, port TEXT NOT NULL, timezone_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, port TEXT NOT NULL, arrival_at TEXT NOT NULL, departure_at TEXT, arrival_at_utc TEXT, timezone_status TEXT);
            CREATE TABLE tank_soundings (id INTEGER PRIMARY KEY, tank_id INTEGER NOT NULL, effective_at_utc TEXT NOT NULL, reading_type TEXT NOT NULL, reading_cm REAL NOT NULL, trim_m REAL NOT NULL, temperature_c REAL, calculated_volume_m3 REAL NOT NULL, calculated_density_kg_m3 REAL, calculated_mass_mt REAL, fuel_batch_id INTEGER, remarks TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            INSERT INTO vessels VALUES (1, 'Existing Vessel', '7654321', 'x', 'x');
            INSERT INTO tank_soundings VALUES (1, 4, '2026-01-01T00:00:00+00:00', 'SOUNDING', 10, 0, 35, 12.5, 950, 11.875, NULL, 'existing', 'x', 'x');
            PRAGMA user_version = 12;
        """)
    database = Database(database_file)
    database.initialize()
    database.initialize()
    with sqlite3.connect(database_file) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tank_soundings)")}
        row = connection.execute("SELECT calculated_volume_m3, calculated_density_kg_m3, calculated_mass_mt, manual_vcf, standard_volume_15_m3, remarks FROM tank_soundings WHERE id = 1").fetchone()
        vessel = connection.execute("SELECT name FROM vessels WHERE id = 1").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"manual_vcf", "standard_volume_15_m3"}.issubset(columns)
    assert row == (12.5, 950.0, 11.875, None, None, "existing")
    assert vessel == ("Existing Vessel",)
    assert version == 19


def test_schema_migration_v14_to_v15_adds_zero_loss_allowances_and_preserves_energy_config(tmp_path):
    database_file = tmp_path / "v14.db"
    with sqlite3.connect(database_file) as connection:
        connection.executescript("""
            CREATE TABLE vessels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, imo TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE port_timezones (port_key TEXT PRIMARY KEY, port TEXT NOT NULL, timezone_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, port TEXT NOT NULL, arrival_at TEXT NOT NULL, departure_at TEXT, arrival_at_utc TEXT, timezone_status TEXT);
            CREATE TABLE vessel_energy_config (vessel_id INTEGER PRIMARY KEY, sea_base_load_kw REAL NOT NULL DEFAULT 0);
            INSERT INTO vessels VALUES (1, 'Existing Vessel', '7654321', 'x', 'x');
            INSERT INTO vessel_energy_config (vessel_id, sea_base_load_kw) VALUES (1, 123.0);
            PRAGMA user_version = 14;
        """)

    database = Database(database_file)
    database.initialize()
    database.initialize()

    with sqlite3.connect(database_file) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(vessel_energy_config)")}
        row = connection.execute(
            "SELECT sea_base_load_kw, main_engine_loss_allowance_mt_per_day, auxiliary_engine_loss_allowance_mt_per_day FROM vessel_energy_config WHERE vessel_id = 1"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"main_engine_loss_allowance_mt_per_day", "auxiliary_engine_loss_allowance_mt_per_day"}.issubset(columns)
    assert row == (123.0, 0.0, 0.0)
    assert version == 19


def test_schema_migration_v15_to_v16_adds_effective_dated_tank_allocation_tables(tmp_path):
    database_file = tmp_path / "v15.db"
    with sqlite3.connect(database_file) as connection:
        connection.executescript("""
            CREATE TABLE vessels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, imo TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE port_timezones (port_key TEXT PRIMARY KEY, port TEXT NOT NULL, timezone_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, port TEXT NOT NULL, arrival_at TEXT NOT NULL, departure_at TEXT, arrival_at_utc TEXT, timezone_status TEXT);
            CREATE TABLE fuel_tanks (id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL, name TEXT NOT NULL);
            INSERT INTO vessels VALUES (1, 'Existing Vessel', '7654321', 'x', 'x');
            INSERT INTO fuel_tanks VALUES (1, 1, 'Existing tank');
            PRAGMA user_version = 15;
        """)
    Database(database_file).initialize()
    Database(database_file).initialize()
    with sqlite3.connect(database_file) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tank = connection.execute("SELECT name FROM fuel_tanks WHERE id = 1").fetchone()
    assert {"tank_consumption_allocation_events", "tank_consumption_allocation_event_tanks"}.issubset(tables)
    assert tank == ("Existing tank",)
    assert version == 19


def test_schema_migration_v17_adds_internal_fuel_transfers_and_preserves_data(tmp_path):
    database_file = tmp_path / "v17.db"
    with sqlite3.connect(database_file) as connection:
        connection.executescript("""
            CREATE TABLE vessels (id INTEGER PRIMARY KEY, name TEXT NOT NULL, imo TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE application_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE port_timezones (port_key TEXT PRIMARY KEY, port TEXT NOT NULL, timezone_id TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE schedule_events (id INTEGER PRIMARY KEY, port TEXT NOT NULL, arrival_at TEXT NOT NULL, departure_at TEXT, arrival_at_utc TEXT, timezone_status TEXT);
            CREATE TABLE fuel_tanks (id INTEGER PRIMARY KEY, vessel_id INTEGER NOT NULL, name TEXT NOT NULL);
            INSERT INTO vessels VALUES (1, 'Existing Vessel', '7654321', 'x', 'x');
            INSERT INTO fuel_tanks VALUES (1, 1, 'Existing tank');
            PRAGMA user_version = 17;
        """)
    Database(database_file).initialize(); Database(database_file).initialize()
    with sqlite3.connect(database_file) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(internal_fuel_transfers)")}
        tank = connection.execute("SELECT name FROM fuel_tanks WHERE id = 1").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert {"vessel_id", "from_tank_id", "to_tank_id", "fuel_type", "quantity_mt", "status", "planned_at_utc", "actual_at_utc"}.issubset(columns)
    assert tank == ("Existing tank",)
    assert version == 19
