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
