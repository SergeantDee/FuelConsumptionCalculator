from __future__ import annotations

from datetime import date

from fuel_consumption_calculator.scraper.legacy_schedule_scraper import scrape_schedule
from fuel_consumption_calculator.scraper.models import RawScheduleRow, ScraperFetchMetadata, ScraperSourceResult
from fuel_consumption_calculator.services.scraper_service import ScraperService


def fake_provider(vessel_name, start_date, **kwargs):
    return ScraperSourceResult(
        vessel_name=vessel_name,
        start_date=start_date,
        raw_text="",
        raw_rows=[RawScheduleRow("Santos", "01 Sep 2026 08:00", "01 Sep 2026 20:00")],
        metadata=ScraperFetchMetadata(vessel_name, "msedge", "url", "visible", False, "url"),
    )


def test_scraper_service_uses_mocked_provider_without_browser():
    service = ScraperService(
        scraper=lambda vessel_name, from_date, **kwargs: scrape_schedule(
            vessel_name,
            from_date,
            month_count=1,
            provider=fake_provider,
            **kwargs,
        )
    )

    candidates = service.scrape_schedule("Maersk Labrea", date(2026, 9, 1))

    assert len(candidates) == 1
    assert candidates[0].port == "Santos"
