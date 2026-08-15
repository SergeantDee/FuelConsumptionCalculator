from __future__ import annotations

import datetime as dt
import logging
from threading import Event
from typing import Callable

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.scraper.legacy_schedule_scraper import scrape_schedule
from fuel_consumption_calculator.scraper.models import ScraperSessionConfig
from fuel_consumption_calculator.scraper.provider import ProgressCallback


LOGGER = logging.getLogger(__name__)


class ScraperService:
    def __init__(
        self,
        *,
        scraper: Callable[..., list[ScheduleCandidate]] = scrape_schedule,
        session_config: ScraperSessionConfig | None = None,
    ) -> None:
        self._scraper = scraper
        self._session_config = session_config

    def scrape_schedule(
        self,
        vessel_name: str,
        from_date: dt.date,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_event: Event | None = None,
        session_config: ScraperSessionConfig | None = None,
    ) -> list[ScheduleCandidate]:
        LOGGER.info("Starting schedule scrape for %s from %s", vessel_name, from_date.isoformat())
        try:
            candidates = self._scraper(
                vessel_name,
                from_date,
                session_config=session_config or self._session_config,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )
        except Exception:
            LOGGER.exception("Schedule scrape failed for %s from %s", vessel_name, from_date.isoformat())
            raise
        LOGGER.info("Schedule scrape returned %s candidate events.", len(candidates))
        return candidates
