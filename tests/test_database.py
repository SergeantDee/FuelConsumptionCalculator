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

    assert {"vessels", "application_metadata", "schedule_events", "vessel_consumption_rates"}.issubset(tables)
    assert schema_version == str(SCHEMA_VERSION)
    assert user_version == SCHEMA_VERSION
