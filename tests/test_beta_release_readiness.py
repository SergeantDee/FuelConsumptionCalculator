from __future__ import annotations

import os
import sqlite3
import tomllib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fuel_consumption_calculator.app import build_main_window
from fuel_consumption_calculator.config import APPLICATION_VERSION, SCHEMA_VERSION
from fuel_consumption_calculator.paths import AppPaths
from fuel_consumption_calculator.repositories.database import Database


def test_beta_version_has_display_and_pep440_package_forms():
    assert APPLICATION_VERSION == "1.4.0-beta.1"
    package = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["project"]["version"] == "1.4.0b1"


def test_fresh_release_database_contains_schema_only_and_no_vessel_data(tmp_path):
    paths = AppPaths(tmp_path / "clean-beta")
    paths.ensure_runtime_directories()
    Database(paths.database_file).initialize()

    assert paths.database_file.is_file()
    assert paths.settings_file.exists() is False
    with sqlite3.connect(paths.database_file) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT value FROM application_metadata WHERE key = 'schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
        for table in ("vessels", "schedule_events", "fuel_tanks", "fuel_batches", "tank_soundings", "tank_sounding_surveys", "actual_rob_observations", "internal_fuel_transfers", "planned_bunker_quantities", "fuel_changeover_events"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_first_run_main_window_constructs_without_a_vessel(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = build_main_window(AppPaths(tmp_path / "first-run"))

    assert window.dashboard_page.vessel_name_value.text() == "Not configured"
    assert window.schedule_page.empty_state.isVisible() is False or "No schedule" in window.schedule_page.empty_state.text()
    window.select_page(4)
    assert window.fuel_tanks_page.empty_label.text() == "Configure a vessel before adding fuel oil tanks."
    window.close()
    app.processEvents()
