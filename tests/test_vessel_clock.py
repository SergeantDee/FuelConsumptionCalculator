from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.services.settings_service import SettingsService
from fuel_consumption_calculator.ui.widgets.vessel_clock import (
    MAX_OFFSET_MINUTES,
    MIN_OFFSET_MINUTES,
    clamp_offset_minutes,
    format_gmt_offset,
    vessel_local_time,
)


def test_formats_whole_and_half_hour_gmt_offsets():
    assert format_gmt_offset(0) == "GMT +00:00"
    assert format_gmt_offset(480) == "GMT +08:00"
    assert format_gmt_offset(-180) == "GMT -03:00"
    assert format_gmt_offset(330) == "GMT +05:30"


def test_vessel_local_time_rolls_dates_without_changing_utc():
    utc = datetime(2026, 8, 23, 23, 30, tzinfo=timezone.utc)
    assert vessel_local_time(utc, 60) == datetime(2026, 8, 24, 0, 30, tzinfo=timezone.utc)
    assert vessel_local_time(utc, -180) == datetime(2026, 8, 23, 20, 30, tzinfo=timezone.utc)
    assert utc == datetime(2026, 8, 23, 23, 30, tzinfo=timezone.utc)


def test_hour_adjustments_keep_half_hour_component_and_clamp_limits():
    assert clamp_offset_minutes(330 + 60) == 390
    assert format_gmt_offset(390) == "GMT +06:30"
    assert clamp_offset_minutes(MAX_OFFSET_MINUTES + 60) == MAX_OFFSET_MINUTES
    assert clamp_offset_minutes(MIN_OFFSET_MINUTES - 60) == MIN_OFFSET_MINUTES


def test_vessel_time_offset_persists_and_restores(tmp_path):
    settings_file = tmp_path / "settings.json"
    service = SettingsService(settings_file)
    service.save_vessel_time_offset_minutes(-210)

    restored = SettingsService(settings_file)
    assert restored.vessel_time_offset_minutes() == -210
