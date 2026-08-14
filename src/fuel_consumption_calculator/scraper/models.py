from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PROVIDER_URL = "https://www.maersk.com/schedules/vesselSchedules"
DEFAULT_BROWSER_CHANNEL = "msedge"
DEFAULT_TIMEOUT_MS = 60_000
RESULT_CARD_SELECTOR = '[data-test="vessel-title-arriving"]'
SOURCE_NAME = "maersk_vessel_schedules"


class ScraperStageError(RuntimeError):
    def __init__(
        self,
        stage: str,
        message: str,
        *,
        diagnostics_path: Path | None = None,
        html_fragment_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.diagnostics_path = diagnostics_path
        self.html_fragment_path = html_fragment_path


@dataclass(frozen=True, slots=True)
class ScraperSessionConfig:
    provider_url: str = DEFAULT_PROVIDER_URL
    browser_channel: str = DEFAULT_BROWSER_CHANNEL
    headless: bool = False
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    diagnostics_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class ScraperFetchMetadata:
    vessel_name: str
    browser_channel: str
    provider_url: str
    browser_mode: str
    login_required: bool
    current_url: str


@dataclass(frozen=True, slots=True)
class RawScheduleRow:
    port: str
    arrival: str
    departure: str | None


@dataclass(frozen=True, slots=True)
class ScraperSourceResult:
    vessel_name: str
    start_date: dt.date
    raw_text: str
    raw_rows: list[RawScheduleRow]
    metadata: ScraperFetchMetadata
