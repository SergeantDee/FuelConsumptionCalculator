from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from fuel_consumption_calculator.config import SCHEMA_VERSION
from fuel_consumption_calculator.domain.time_model import DEFAULT_PORT_TIMEZONES, local_to_utc, normalize_port_name


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
            if current_version < 9:
                self._migrate_to_v9(connection)
            if current_version < 10:
                self._migrate_to_v10(connection)
            if current_version < 11:
                self._migrate_to_v11(connection)
            if current_version < 12:
                self._migrate_to_v12(connection)
            if current_version < 13:
                self._migrate_to_v13(connection)
            if current_version < 14:
                self._migrate_to_v14(connection)
            if current_version < 15:
                self._migrate_to_v15(connection)
            if current_version >= 9:
                self._ensure_default_port_timezones(connection)
                self._resolve_existing_schedule_timezones(connection)
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
            if not columns:
                return
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
                main_engine_loss_allowance_mt_per_day REAL NOT NULL DEFAULT 0,
                auxiliary_engine_loss_allowance_mt_per_day REAL NOT NULL DEFAULT 0,
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
                CHECK (main_engine_loss_allowance_mt_per_day >= 0),
                CHECK (auxiliary_engine_loss_allowance_mt_per_day >= 0),
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

    def _migrate_to_v9(self, connection: sqlite3.Connection) -> None:
        def add_column_if_missing(table: str, column: str, ddl: str) -> None:
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            if not columns:
                return
            if column not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

        add_column_if_missing("schedule_events", "port_timezone_id", "port_timezone_id TEXT")
        add_column_if_missing("schedule_events", "arrival_at_utc", "arrival_at_utc TEXT")
        add_column_if_missing("schedule_events", "departure_at_utc", "departure_at_utc TEXT")
        add_column_if_missing("schedule_events", "timezone_status", "timezone_status TEXT NOT NULL DEFAULT 'UNRESOLVED'")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS port_timezones (
                port_key TEXT PRIMARY KEY,
                port TEXT NOT NULL,
                timezone_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS vessel_initial_machinery_fuel_state (
                vessel_id INTEGER PRIMARY KEY,
                main_engine_fuel_type TEXT NOT NULL DEFAULT 'VLSFO',
                generators_fuel_type TEXT NOT NULL DEFAULT 'VLSFO',
                aux_boiler_fuel_type TEXT NOT NULL DEFAULT 'VLSFO',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                CHECK (main_engine_fuel_type IN ('ULSFO', 'VLSFO', 'MDO')),
                CHECK (generators_fuel_type IN ('ULSFO', 'VLSFO', 'MDO')),
                CHECK (aux_boiler_fuel_type IN ('ULSFO', 'VLSFO', 'MDO'))
            );

            CREATE TABLE IF NOT EXISTS vessel_clock_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                effective_at_utc TEXT NOT NULL,
                adjustment_minutes INTEGER NOT NULL,
                previous_offset_minutes INTEGER NOT NULL,
                resulting_offset_minutes INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_vessel_clock_adjustments_vessel_time
                ON vessel_clock_adjustments (vessel_id, effective_at_utc);

            CREATE TABLE IF NOT EXISTS fuel_changeover_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                machinery TEXT NOT NULL,
                from_fuel_type TEXT NOT NULL,
                to_fuel_type TEXT NOT NULL,
                planned_at_utc TEXT NOT NULL,
                actual_at_utc TEXT,
                time_basis TEXT NOT NULL DEFAULT 'UTC',
                status TEXT NOT NULL DEFAULT 'PLANNED',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                CHECK (machinery IN ('MAIN_ENGINE', 'GENERATORS', 'AUX_BOILER')),
                CHECK (from_fuel_type IN ('ULSFO', 'VLSFO', 'MDO')),
                CHECK (to_fuel_type IN ('ULSFO', 'VLSFO', 'MDO'))
            );

            CREATE INDEX IF NOT EXISTS idx_fuel_changeover_events_vessel_time
                ON fuel_changeover_events (vessel_id, planned_at_utc, actual_at_utc);
            """
        )
        self._ensure_default_port_timezones(connection)
        self._resolve_existing_schedule_timezones(connection)
        LOGGER.info("Database migrated to schema version 9.")

    def _migrate_to_v10(self, connection: sqlite3.Connection) -> None:
        def add_column_if_missing(table: str, column: str, ddl: str) -> None:
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            if not columns:
                return
            if column not in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

        add_column_if_missing("voyage_leg_overrides", "actual_departure_reefers", "actual_departure_reefers REAL")
        add_column_if_missing("voyage_leg_overrides", "port_ambient_c", "port_ambient_c REAL")
        add_column_if_missing("voyage_leg_overrides", "sea_ambient_c", "sea_ambient_c REAL")
        for column, ddl in (
            ("main_engine_slip_percent", "main_engine_slip_percent REAL NOT NULL DEFAULT 10.0"),
            ("speed_rpm_factor", "speed_rpm_factor REAL NOT NULL DEFAULT 0.3221598"),
            ("power_coefficient", "power_coefficient REAL NOT NULL DEFAULT 0.0967741935483871"),
            ("mcr_power_kw", "mcr_power_kw REAL NOT NULL DEFAULT 38880.0"),
            ("port_ambient_c", "port_ambient_c REAL NOT NULL DEFAULT 20.0"),
            ("sea_ambient_c", "sea_ambient_c REAL NOT NULL DEFAULT 20.0"),
        ):
            add_column_if_missing("vessel_energy_config", column, ddl)
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS main_engine_sfoc_points (
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

            CREATE INDEX IF NOT EXISTS idx_main_engine_sfoc_points_vessel_load
                ON main_engine_sfoc_points (vessel_id, load_percent);

            CREATE TABLE IF NOT EXISTS actual_rob_observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                effective_at_utc TEXT NOT NULL,
                ulsfo_mt REAL NOT NULL DEFAULT 0,
                vlsfo_mt REAL NOT NULL DEFAULT 0,
                mdo_mt REAL NOT NULL DEFAULT 0,
                remarks TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                CHECK (ulsfo_mt >= 0),
                CHECK (vlsfo_mt >= 0),
                CHECK (mdo_mt >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_actual_rob_observations_vessel_time
                ON actual_rob_observations (vessel_id, effective_at_utc);
            """
        )
        LOGGER.info("Database migrated to schema version 10.")

    def _migrate_to_v11(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(vessel_energy_config)").fetchall()}
        if columns:
            for column in (
                "maneuvering_main_engine_mt_per_hour",
                "maneuvering_generators_mt_per_hour",
                "maneuvering_aux_boiler_mt_per_hour",
            ):
                if column not in columns:
                    connection.execute(f"ALTER TABLE vessel_energy_config ADD COLUMN {column} REAL")
        LOGGER.info("Database migrated to schema version 11.")

    def _migrate_to_v12(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS fuel_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                batch_name TEXT NOT NULL,
                fuel_type TEXT NOT NULL,
                density_15_kg_m3 REAL NOT NULL,
                sulfur_percent REAL,
                viscosity_50_cst REAL,
                flash_point_c REAL,
                pour_point_c REAL,
                water_percent REAL,
                lab_reference TEXT,
                bunker_port TEXT,
                bunker_date TEXT,
                remarks TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                CHECK (fuel_type IN ('ULSFO', 'VLSFO', 'MDO')),
                CHECK (density_15_kg_m3 > 0),
                CHECK (sulfur_percent IS NULL OR sulfur_percent >= 0),
                CHECK (viscosity_50_cst IS NULL OR viscosity_50_cst >= 0),
                CHECK (water_percent IS NULL OR water_percent >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_fuel_batches_vessel
                ON fuel_batches (vessel_id, batch_name);

            CREATE TABLE IF NOT EXISTS fuel_tanks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vessel_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                tank_type TEXT NOT NULL,
                capacity_m3 REAL NOT NULL,
                preferred_measurement_type TEXT NOT NULL,
                bunker_receiving_eligible INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                current_fuel_batch_id INTEGER,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (vessel_id) REFERENCES vessels(id) ON DELETE CASCADE,
                FOREIGN KEY (current_fuel_batch_id) REFERENCES fuel_batches(id) ON DELETE SET NULL,
                UNIQUE (vessel_id, name),
                CHECK (tank_type IN ('BUNKER', 'SETTLING', 'SERVICE', 'OTHER')),
                CHECK (capacity_m3 > 0),
                CHECK (preferred_measurement_type IN ('SOUNDING', 'ULLAGE')),
                CHECK (bunker_receiving_eligible IN (0, 1)),
                CHECK (is_active IN (0, 1))
            );

            CREATE INDEX IF NOT EXISTS idx_fuel_tanks_vessel_active
                ON fuel_tanks (vessel_id, is_active, name);

            CREATE TABLE IF NOT EXISTS tank_calibration_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tank_id INTEGER NOT NULL,
                sounding_cm REAL,
                ullage_cm REAL,
                trim_m REAL NOT NULL,
                volume_m3 REAL NOT NULL,
                FOREIGN KEY (tank_id) REFERENCES fuel_tanks(id) ON DELETE CASCADE,
                UNIQUE (tank_id, sounding_cm, ullage_cm, trim_m),
                CHECK (sounding_cm IS NOT NULL OR ullage_cm IS NOT NULL),
                CHECK (sounding_cm IS NULL OR sounding_cm >= 0),
                CHECK (ullage_cm IS NULL OR ullage_cm >= 0),
                CHECK (volume_m3 >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_tank_calibration_points_tank
                ON tank_calibration_points (tank_id, trim_m);

            CREATE TABLE IF NOT EXISTS tank_soundings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tank_id INTEGER NOT NULL,
                effective_at_utc TEXT NOT NULL,
                reading_type TEXT NOT NULL,
                reading_cm REAL NOT NULL,
                trim_m REAL NOT NULL,
                temperature_c REAL,
                calculated_volume_m3 REAL NOT NULL,
                calculated_density_kg_m3 REAL,
                calculated_mass_mt REAL,
                fuel_batch_id INTEGER,
                remarks TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (tank_id) REFERENCES fuel_tanks(id) ON DELETE CASCADE,
                FOREIGN KEY (fuel_batch_id) REFERENCES fuel_batches(id) ON DELETE SET NULL,
                CHECK (reading_type IN ('SOUNDING', 'ULLAGE')),
                CHECK (reading_cm >= 0),
                CHECK (calculated_volume_m3 >= 0),
                CHECK (calculated_density_kg_m3 IS NULL OR calculated_density_kg_m3 > 0),
                CHECK (calculated_mass_mt IS NULL OR calculated_mass_mt >= 0)
            );

            CREATE INDEX IF NOT EXISTS idx_tank_soundings_tank_time
                ON tank_soundings (tank_id, effective_at_utc DESC, id DESC);
            """
        )
        LOGGER.info("Database migrated to schema version 12.")

    def _migrate_to_v13(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tank_soundings)").fetchall()}
        if "manual_vcf" not in columns:
            connection.execute("ALTER TABLE tank_soundings ADD COLUMN manual_vcf REAL")
        if "standard_volume_15_m3" not in columns:
            connection.execute("ALTER TABLE tank_soundings ADD COLUMN standard_volume_15_m3 REAL")
        LOGGER.info("Database migrated to schema version 13.")

    def _migrate_to_v14(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS bunker_receiving_tank_plans (
                vessel_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                port_snapshot TEXT NOT NULL,
                arrival_snapshot TEXT NOT NULL,
                tank_id INTEGER NOT NULL,
                projected_arrival_volume_m3 REAL,
                target_fill_percent REAL NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (vessel_id, sequence_number, port_snapshot, arrival_snapshot, tank_id),
                FOREIGN KEY (tank_id) REFERENCES fuel_tanks(id) ON DELETE CASCADE,
                CHECK (projected_arrival_volume_m3 IS NULL OR projected_arrival_volume_m3 >= 0),
                CHECK (target_fill_percent > 0 AND target_fill_percent <= 100)
            );
            CREATE TABLE IF NOT EXISTS bunker_incoming_fuel_snapshots (
                vessel_id INTEGER NOT NULL,
                sequence_number INTEGER NOT NULL,
                port_snapshot TEXT NOT NULL,
                arrival_snapshot TEXT NOT NULL,
                fuel_batch_id INTEGER,
                density_15_kg_m3 REAL,
                manual_vcf REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (vessel_id, sequence_number, port_snapshot, arrival_snapshot),
                FOREIGN KEY (fuel_batch_id) REFERENCES fuel_batches(id) ON DELETE SET NULL,
                CHECK (density_15_kg_m3 IS NULL OR density_15_kg_m3 > 0),
                CHECK (manual_vcf IS NULL OR manual_vcf > 0)
            );
            """
        )
        LOGGER.info("Database migrated to schema version 14.")

    def _migrate_to_v15(self, connection: sqlite3.Connection) -> None:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(vessel_energy_config)").fetchall()}
        if columns and "main_engine_loss_allowance_mt_per_day" not in columns:
            connection.execute("ALTER TABLE vessel_energy_config ADD COLUMN main_engine_loss_allowance_mt_per_day REAL NOT NULL DEFAULT 0")
        if columns and "auxiliary_engine_loss_allowance_mt_per_day" not in columns:
            connection.execute("ALTER TABLE vessel_energy_config ADD COLUMN auxiliary_engine_loss_allowance_mt_per_day REAL NOT NULL DEFAULT 0")
        LOGGER.info("Database migrated to schema version 15.")

    def _ensure_default_port_timezones(self, connection: sqlite3.Connection) -> None:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for port, timezone_id in DEFAULT_PORT_TIMEZONES.items():
            key = normalize_port_name(port)
            connection.execute(
                """
                INSERT INTO port_timezones (port_key, port, timezone_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(port_key) DO NOTHING
                """,
                (key, port, timezone_id, timestamp, timestamp),
            )

    def _resolve_existing_schedule_timezones(self, connection: sqlite3.Connection) -> None:
        timezone_by_key = {
            row["port_key"]: row["timezone_id"]
            for row in connection.execute("SELECT port_key, timezone_id FROM port_timezones").fetchall()
        }
        rows = connection.execute(
            """
            SELECT id, port, arrival_at, departure_at
            FROM schedule_events
            WHERE arrival_at_utc IS NULL OR timezone_status = 'UNRESOLVED'
            """
        ).fetchall()
        for row in rows:
            timezone_id = timezone_by_key.get(normalize_port_name(row["port"]))
            arrival_result = local_to_utc(datetime.fromisoformat(row["arrival_at"]), timezone_id)
            departure_result = local_to_utc(datetime.fromisoformat(row["departure_at"]), timezone_id) if row["departure_at"] else None
            status = arrival_result.status
            if arrival_result.status == "RESOLVED" and departure_result is None:
                status = "RESOLVED"
            if departure_result is not None and departure_result.status != "RESOLVED":
                status = departure_result.status
            elif departure_result is not None and arrival_result.status == "RESOLVED":
                status = "RESOLVED"
            connection.execute(
                """
                UPDATE schedule_events
                SET port_timezone_id = ?, arrival_at_utc = ?, departure_at_utc = ?, timezone_status = ?
                WHERE id = ?
                """,
                (
                    timezone_id,
                    arrival_result.utc_value.isoformat(timespec="minutes") if arrival_result.utc_value else None,
                    departure_result.utc_value.isoformat(timespec="minutes") if departure_result and departure_result.utc_value else None,
                    status,
                    row["id"],
                ),
            )
