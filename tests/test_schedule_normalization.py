from __future__ import annotations

from datetime import date

import pytest

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.scraper.models import RawScheduleRow
from fuel_consumption_calculator.scraper.normalization import normalize_raw_rows, parse_schedule_source
from fuel_consumption_calculator.scraper.validation import validate_schedule_candidates


def test_parse_schedule_source_uses_legacy_rendered_text_positions():
    raw_text = """
    Ignore
    Santos
    Extra
    Arrival -
    01 Sep 2026 08:00
    Departure -
    01 Sep 2026 20:00
    """

    rows = parse_schedule_source(raw_text)

    assert rows == [RawScheduleRow(port="Santos", arrival="01 Sep 2026 08:00", departure="01 Sep 2026 20:00")]


def test_normalization_sorts_deduplicates_and_sequences_raw_rows():
    rows = [
        RawScheduleRow("Paranagua", "03 Sep 2026 08:00", "03 Sep 2026 20:00"),
        RawScheduleRow("Santos", "01 Sep 2026 08:00", "01 Sep 2026 20:00"),
        RawScheduleRow("Santos", "01 Sep 2026 08:00", "01 Sep 2026 20:00"),
    ]

    candidates = normalize_raw_rows(rows, vessel_name="Maersk Labrea", from_date=date(2026, 9, 1))

    assert [(candidate.sequence_number, candidate.port) for candidate in candidates] == [(1, "Santos"), (2, "Paranagua")]


def test_validation_rejects_malformed_candidate_ordering():
    first = ScheduleCandidate(1, "Paranagua", "Port Call", __import__("datetime").datetime(2026, 9, 3), None, "source", "vessel", date(2026, 9, 1))
    second = ScheduleCandidate(2, "Santos", "Port Call", __import__("datetime").datetime(2026, 9, 1), None, "source", "vessel", date(2026, 9, 1))

    with pytest.raises(ValueError, match="chronological"):
        validate_schedule_candidates([first, second])


def test_empty_normalization_is_rejected():
    with pytest.raises(ValueError, match="no schedule events"):
        normalize_raw_rows([], vessel_name="Maersk Labrea", from_date=date(2026, 9, 1))
