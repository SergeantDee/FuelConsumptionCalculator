from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from fuel_consumption_calculator.config import DATABASE_FILENAME, LOG_FILENAME, SETTINGS_FILENAME


def default_application_root() -> Path:
    """Return the writable root for development or a PyInstaller onedir build."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path

    @classmethod
    def default(cls) -> "AppPaths":
        return cls(default_application_root())

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def exports_dir(self) -> Path:
        return self.root / "exports"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def database_file(self) -> Path:
        return self.data_dir / DATABASE_FILENAME

    @property
    def settings_file(self) -> Path:
        return self.data_dir / SETTINGS_FILENAME

    @property
    def log_file(self) -> Path:
        return self.logs_dir / LOG_FILENAME

    def ensure_runtime_directories(self) -> None:
        for directory in (self.data_dir, self.backups_dir, self.exports_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
