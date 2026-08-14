from __future__ import annotations

from fuel_consumption_calculator.paths import AppPaths


def test_paths_are_centralized_below_application_root(tmp_path):
    paths = AppPaths(tmp_path)
    paths.ensure_runtime_directories()

    assert paths.data_dir == tmp_path / "data"
    assert paths.database_file.parent == paths.data_dir
    assert paths.settings_file.parent == paths.data_dir
    assert paths.log_file.parent == paths.logs_dir
    assert paths.data_dir.is_dir()
    assert paths.backups_dir.is_dir()
    assert paths.exports_dir.is_dir()
    assert paths.logs_dir.is_dir()
