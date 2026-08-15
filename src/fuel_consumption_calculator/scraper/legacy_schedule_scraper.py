from __future__ import annotations

import datetime as dt
from threading import Event
from typing import Callable

from fuel_consumption_calculator.config import SCRAPER_MONTH_COUNT
from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.scraper.models import ScraperSessionConfig, ScraperStageError
from fuel_consumption_calculator.scraper.normalization import normalize_raw_rows
from fuel_consumption_calculator.scraper.provider import ProgressCallback, fetch_schedule_source


def scrape_schedule(
    vessel_name: str,
    from_date: dt.date,
    *,
    month_count: int = SCRAPER_MONTH_COUNT,
    session_config: ScraperSessionConfig | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_event: Event | None = None,
    provider: Callable[..., object] = fetch_schedule_source,
) -> list[ScheduleCandidate]:
    all_raw_rows = []
    for month_offset in range(month_count):
        start_date = _add_months(from_date, month_offset)
        try:
            source_result = provider(
                vessel_name,
                start_date,
                session_config=session_config,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
            )
        except ScraperStageError:
            if all_raw_rows:
                if progress_callback is not None:
                    progress_callback("partial_results", f"No further schedule rows found from {start_date:%d %b %Y}; using prior results.")
                break
            raise
        all_raw_rows.extend(source_result.raw_rows)
    return normalize_raw_rows(all_raw_rows, vessel_name=vessel_name, from_date=from_date)


def _add_months(value: dt.date, months: int) -> dt.date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, _days_in_month(year, month))
    return dt.date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (dt.date(year, month + 1, 1) - dt.timedelta(days=1)).day
