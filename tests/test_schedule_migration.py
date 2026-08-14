from __future__ import annotations

import sqlite3

from fuel_consumption_calculator.repositories.database import Database


def test_schema_migration_v1_to_v2_preserves_vessel(tmp_path):
    database_file = tmp_path / "legacy_v1.db"
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
            INSERT INTO vessels VALUES (1, 'Existing Vessel', '7654321', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
            INSERT INTO application_metadata VALUES ('schema_version', '1');
            PRAGMA user_version = 1;
            """
        )

    Database(database_file).initialize()

    with sqlite3.connect(database_file) as connection:
        vessel = connection.execute("SELECT name, imo FROM vessels WHERE id = 1").fetchone()
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schedule_events'"
        ).fetchone()
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]

    assert vessel == ("Existing Vessel", "7654321")
    assert table == ("schedule_events",)
    assert user_version == 2
