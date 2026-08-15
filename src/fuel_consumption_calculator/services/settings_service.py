from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SettingsService:
    """Small JSON-backed store for future non-operational UI preferences."""

    def __init__(self, settings_file: Path) -> None:
        self._settings_file = Path(settings_file)

    def load(self) -> dict[str, Any]:
        if not self._settings_file.exists():
            return {}
        try:
            data = json.loads(self._settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Application settings could not be read.") from exc
        if not isinstance(data, dict):
            raise RuntimeError("Application settings must contain a JSON object.")
        return data

    def save(self, settings: dict[str, Any]) -> None:
        self._settings_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self._settings_file.with_suffix(".tmp")
        temporary_file.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")
        temporary_file.replace(self._settings_file)

    def scraper_browser_mode(self) -> str:
        value = str(self.load().get("scraper_browser_mode", "visible")).lower()
        return value if value in {"visible", "headless"} else "visible"

    def save_scraper_browser_mode(self, mode: str) -> None:
        normalized = mode.lower()
        if normalized not in {"visible", "headless"}:
            raise ValueError("Scraper browser mode must be visible or headless.")
        settings = self.load()
        settings["scraper_browser_mode"] = normalized
        self.save(settings)
