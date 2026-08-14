from __future__ import annotations

import datetime as dt

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.scraper.models import RawScheduleRow, SOURCE_NAME
from fuel_consumption_calculator.scraper.validation import parse_legacy_datetime, validate_schedule_candidates


def parse_schedule_source(raw_text: str) -> list[RawScheduleRow]:
    # Derived from FOapp/scraper.py: parse rendered Maersk result-card text by the proven line positions.
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    extracted_rows: list[RawScheduleRow] = []
    for index, line in enumerate(lines):
        if not line.startswith("Arrival -"):
            continue
        port = lines[index - 2] if index >= 2 else "Unknown Port"
        arrival = lines[index + 1] if index + 1 < len(lines) else ""
        departure = None
        if index + 2 < len(lines) and lines[index + 2].startswith("Departure -"):
            departure = lines[index + 3] if index + 3 < len(lines) else None
        extracted_rows.append(RawScheduleRow(port=port, arrival=arrival, departure=departure))
    return extracted_rows


def normalize_raw_rows(
    raw_rows: list[RawScheduleRow],
    *,
    vessel_name: str,
    from_date: dt.date,
    source: str = SOURCE_NAME,
) -> list[ScheduleCandidate]:
    normalized: list[ScheduleCandidate] = []
    seen: set[tuple[str, dt.datetime, dt.datetime | None]] = set()

    for raw_row in raw_rows:
        arrival = parse_legacy_datetime(raw_row.arrival)
        departure = parse_legacy_datetime(raw_row.departure or "")
        if arrival is None:
            continue
        if raw_row.departure and raw_row.departure.upper() != "N/A" and departure is None:
            continue
        key = (raw_row.port.strip(), arrival, departure)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            ScheduleCandidate(
                sequence_number=0,
                port=raw_row.port.strip(),
                event_type="Port Call",
                arrival_at=arrival,
                departure_at=departure,
                source=source,
                source_vessel_name=vessel_name,
                source_from_date=from_date,
            )
        )

    normalized.sort(key=lambda candidate: candidate.arrival_at)
    sequenced = [
        ScheduleCandidate(
            sequence_number=index,
            port=candidate.port,
            event_type=candidate.event_type,
            arrival_at=candidate.arrival_at,
            departure_at=candidate.departure_at,
            source=candidate.source,
            source_vessel_name=candidate.source_vessel_name,
            source_from_date=candidate.source_from_date,
            terminal=candidate.terminal,
        )
        for index, candidate in enumerate(normalized, start=1)
    ]
    validate_schedule_candidates(sequenced)
    return sequenced
