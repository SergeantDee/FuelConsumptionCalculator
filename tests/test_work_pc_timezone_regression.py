from __future__ import annotations

import sqlite3

from fuel_consumption_calculator.repositories.database import Database


def test_existing_v9_database_resolves_real_work_pc_ports_after_default_mapping_added(tmp_path):
    database_file = tmp_path / "work_pc_v9.db"
    with sqlite3.connect(database_file) as connection:
        connection.executescript(
            """
            CREATE TABLE vessels (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                imo TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE application_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE schedule_events (
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
                port_timezone_id TEXT,
                arrival_at_utc TEXT,
                departure_at_utc TEXT,
                timezone_status TEXT NOT NULL DEFAULT 'UNRESOLVED'
            );
            CREATE TABLE port_timezones (
                port_key TEXT PRIMARY KEY,
                port TEXT NOT NULL,
                timezone_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO vessels VALUES (1, 'MAERSK LABREA', '9527063', '2026-08-15T11:54:56+00:00', '2026-08-15T11:54:56+00:00');
            INSERT INTO application_metadata VALUES ('schema_version', '9');
            INSERT INTO schedule_events (
                vessel_id, sequence_number, port, event_type, arrival_at, departure_at,
                source, source_vessel_name, source_from_date, created_at, updated_at,
                timezone_status
            )
            VALUES
                (1, 11, 'Montevideo', 'Port Call', '2026-10-08T03:00', '2026-10-09T03:00', 'maersk', 'MAERSK LABREA', '2026-08-16', '', '', 'UNRESOLVED'),
                (1, 12, 'Buenos Aires', 'Port Call', '2026-10-10T07:00', '2026-10-11T19:30', 'maersk', 'MAERSK LABREA', '2026-08-16', '', '', 'UNRESOLVED');
            PRAGMA user_version = 9;
            """
        )

    Database(database_file).initialize()

    with sqlite3.connect(database_file) as connection:
        rows = connection.execute(
            """
            SELECT port, port_timezone_id, arrival_at_utc, departure_at_utc, timezone_status
            FROM schedule_events
            ORDER BY sequence_number
            """
        ).fetchall()

    assert rows == [
        ("Montevideo", "America/Montevideo", "2026-10-08T06:00+00:00", "2026-10-09T06:00+00:00", "RESOLVED"),
        ("Buenos Aires", "America/Argentina/Buenos_Aires", "2026-10-10T10:00+00:00", "2026-10-11T22:30+00:00", "RESOLVED"),
    ]
