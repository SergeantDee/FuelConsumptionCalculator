from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fuel_consumption_calculator.config import SCHEMA_VERSION


LOGGER = logging.getLogger(__name__)


class Database:
    def __init__(self, database_file: Path) -> None:
        self.database_file = Path(database_file)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_file, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.database_file.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            current_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {current_version} is newer than supported version {SCHEMA_VERSION}."
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vessels (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    imo TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS application_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            if current_version < 2:
                self._migrate_to_v2(connection)
            if current_version < 3:
                self._migrate_to_v3(connection)
            if current_version < 4:
                self._migrate_to_v4(connection)
            if current_version < 5:
                self._migrate_to_v5(connection)
            if current_version < 6:
                self._migrate_to_v6(connection)
            if current_version < 7:
                self._migrate_to_v7(connection)
            if current_version < 8:
                self._migrate_to_v8(connection)
            connection.execute(
                "INSERT OR REPLACE INTO application_metadata (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        LOGGER.info("Database initialized at %s with schema version %s", self.database_file, SCHEMA_VERSION)

    def _migrate_to_v2(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schedule_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                port TEXT NOT NULL,
                terminal TEXT,
                event_type TEXT NOT NULL,
                arrival_at TEXT NOT NULL,
                departure_at TEXT,
                source TEXT NOT NULL,
                source_vessel_name TEXT NOT NULL,
                source_from_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (vessel_id, sequence_number)
            );

            CREATE INDEX IF NOT EXISTS idx_schedule_events_vessel_sequence
                ON schedule_events (vessel_id, sequence_number);
            """
        )
        LOGGER.info("Database migrated to schema version 2.")

    def _migrate_to_v3(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS vessel_consumption_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                operating_mode TEXT NOT NULL,
                fuel_type TEXT NOT NULL,
                rate_mt_per_day REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (vessel_id, operating_mode, fuel_type),
                CHECK (rate_mt_per_day >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_consumption_rates_vessel
                ON vessel_consumption_rates (vessel_id);
            """
        )
        LOGGER.info("Database migrated to schema version 3.")

    def _migrate_to_v4(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS vessel_starting_rob (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                fuel_type TEXT NOT NULL,
                quantity_mt REAL NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (vessel_id, fuel_type),
                CHECK (quantity_mt >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_starting_rob_vessel
                ON vessel_starting_rob (vessel_id);
            """
        )
        LOGGER.info("Database migrated to schema version 4.")

    def _migrate_to_v5(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS planned_bunker_quantities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                port_snapshot TEXT NOT NULL,
                arrival_snapshot TEXT,
                fuel_type TEXT NOT NULL,
                quantity_mt REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (vessel_id, sequence_number, port_snapshot, arrival_snapshot, fuel_type),
                CHECK (quantity_mt >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_planned_bunkers_vessel_sequence
                ON planned_bunker_quantities (vessel_id, sequence_number);

            CREATE TABLE IF NOT EXISTS vessel_bunker_capacities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                fuel_type TEXT NOT NULL,
                maximum_capacity_mt REAL NOT NULL,
                target_fill_percent REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (vessel_id, fuel_type),
                CHECK (maximum_capacity_mt >= 0),
                CHECK (target_fill_percent >= 0 AND target_fill_percent <= 100)
            );

            CREATE INDEX IF NOT EXISTS idx_bunker_capacities_vessel
                ON vessel_bunker_capacities (vessel_id);
            """
        )
        LOGGER.info("Database migrated to schema version 5.")

    def _migrate_to_v6(self, connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(planned_bunker_quantities)").fetchall()
        }
        if "status" not in columns:
            connection.execute(
                """
                ALTER TABLE planned_bunker_quantities
                ADD COLUMN status TEXT NOT NULL DEFAULT 'DRAFT'
                """
            )
        connection.execute(
            """
            UPDATE planned_bunker_quantities
            SET status = 'DRAFT'
            WHERE status IS NULL OR status NOT IN ('DRAFT', 'CONFIRMED')
            """
        )
        LOGGER.info("Database migrated to schema version 6.")

    def _migrate_to_v7(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS route_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origin_port TEXT NOT NULL,
                destination_port TEXT NOT NULL,
                departure_pilot_distance_nm REAL NOT NULL DEFAULT 0,
                departure_pilotage_hours REAL NOT NULL DEFAULT 1,
                sea_distance_nm REAL NOT NULL DEFAULT 0,
                arrival_pilot_distance_nm REAL NOT NULL DEFAULT 0,
                arrival_pilotage_hours REAL NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (origin_port, destination_port),
                CHECK (departure_pilot_distance_nm >= 0),
                CHECK (departure_pilotage_hours >= 0),
                CHECK (sea_distance_nm >= 0),
                CHECK (arrival_pilot_distance_nm >= 0),
                CHECK (arrival_pilotage_hours >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_route_definitions_pair
                ON route_definitions (origin_port, destination_port);

            CREATE TABLE IF NOT EXISTS voyage_leg_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                origin_port_snapshot TEXT NOT NULL,
                destination_port_snapshot TEXT NOT NULL,
                origin_departure_snapshot TEXT,
                destination_arrival_snapshot TEXT NOT NULL,
                departure_pilot_distance_nm REAL,
                departure_pilotage_hours REAL,
                sea_distance_nm REAL,
                arrival_pilot_distance_nm REAL,
                arrival_pilotage_hours REAL,
                actual_berth_departure TEXT,
                actual_pilot_off TEXT,
                actual_pilot_on TEXT,
                actual_berth_arrival TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (
                    vessel_id, sequence_number, origin_port_snapshot,
                    destination_port_snapshot, origin_departure_snapshot,
                    destination_arrival_snapshot
                ),
                CHECK (departure_pilot_distance_nm IS NULL OR departure_pilot_distance_nm >= 0),
                CHECK (departure_pilotage_hours IS NULL OR departure_pilotage_hours >= 0),
                CHECK (sea_distance_nm IS NULL OR sea_distance_nm >= 0),
                CHECK (arrival_pilot_distance_nm IS NULL OR arrival_pilot_distance_nm >= 0),
                CHECK (arrival_pilotage_hours IS NULL OR arrival_pilotage_hours >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_voyage_leg_overrides_vessel_sequence
                ON voyage_leg_overrides (vessel_id, sequence_number);

            CREATE TABLE IF NOT EXISTS vessel_speed_consumption_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                speed_knots REAL NOT NULL,
                ulsfo_mt_per_day REAL NOT NULL DEFAULT 0,
                vlsfo_mt_per_day REAL NOT NULL DEFAULT 0,
                mdo_mt_per_day REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (vessel_id, speed_knots),
                CHECK (speed_knots > 0),
                CHECK (ulsfo_mt_per_day >= 0),
                CHECK (vlsfo_mt_per_day >= 0),
                CHECK (mdo_mt_per_day >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_speed_consumption_points_vessel_speed
                ON vessel_speed_consumption_points (vessel_id, speed_knots);
            """
        )
        LOGGER.info("Database migrated to schema version 7.")

    def _migrate_to_v8(self, connection: sqlite3.Connection) -> None:
        def add_column_if_missing(table: str, column: str, ddl: str) -> None:
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

        add_column_if_missing("vessel_speed_consumption_points", "main_engine_load_percent", "main_engine_load_percent REAL")
        add_column_if_missing("voyage_leg_overrides", "port_reefers", "port_reefers REAL")
        add_column_if_missing("voyage_leg_overrides", "departure_reefers", "departure_reefers REAL")
        add_column_if_missing("voyage_leg_overrides", "use_egb", "use_egb INTEGER NOT NULL DEFAULT 0")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS vessel_energy_config (
                vessel_id INTEGER PRIMARY KEY,
                port_base_load_kw REAL NOT NULL DEFAULT 0,
                sea_base_load_kw REAL NOT NULL DEFAULT 0,
                reefer_kw_per_unit REAL NOT NULL DEFAULT 0,
                generator_rated_kw REAL NOT NULL DEFAULT 0,
                port_running_generators REAL NOT NULL DEFAULT 0,
                sea_running_generators REAL NOT NULL DEFAULT 0,
                aux_boiler_mt_per_hour REAL NOT NULL DEFAULT 0,
                generator_fuel_type TEXT NOT NULL DEFAULT 'MDO',
                boiler_fuel_type TEXT NOT NULL DEFAULT 'MDO',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                CHECK (port_base_load_kw >= 0),
                CHECK (sea_base_load_kw >= 0),
                CHECK (reefer_kw_per_unit >= 0),
                CHECK (generator_rated_kw >= 0),
                CHECK (port_running_generators >= 0),
                CHECK (sea_running_generators >= 0),
                CHECK (aux_boiler_mt_per_hour >= 0),
                CHECK (generator_fuel_type IN ('ULSFO', 'VLSFO', 'MDO')),
                CHECK (boiler_fuel_type IN ('ULSFO', 'VLSFO', 'MDO'))
            );

            CREATE TABLE IF NOT EXISTS generator_sfoc_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                load_percent REAL NOT NULL,
                sfoc_g_per_kwh REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                UNIQUE (vessel_id, load_percent),
                CHECK (load_percent >= 0),
                CHECK (sfoc_g_per_kwh >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_generator_sfoc_points_vessel_load
                ON generator_sfoc_points (vessel_id, load_percent);
            """
        )
        LOGGER.info("Database migrated to schema version 8.")
