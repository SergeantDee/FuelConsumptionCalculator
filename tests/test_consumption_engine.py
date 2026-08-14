from __future__ import annotations

from datetime import date, datetime

import pytest

from fuel_consumption_calculator.calculations.consumption_engine import calculate_schedule_consumption
from fuel_consumption_calculator.domain.consumption import ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline


def event(
    sequence: int,
    *,
    arrival_at: datetime,
    departure_at: datetime | None,
    port: str = "Santos",
) -> ScheduleEvent:
    return ScheduleEvent(
        id=sequence,
        vessel_id=1,
        sequence_number=sequence,
        port=port,
        event_type="Port Call",
        arrival_at=arrival_at,
        departure_at=departure_at,
        source="manual",
        source_vessel_name="Maersk Labrea",
        source_from_date=date(2026, 9, 1),
        created_at="2026-09-01T00:00:00+00:00",
        updated_at="2026-09-01T00:00:00+00:00",
    )


def profile(*, sea_ulsfo: float = 0.0, port_mdo: float = 0.0, sea_vlsfo: float = 0.0) -> ConsumptionProfile:
    rates = {
        ("SEA", "ULSFO"): sea_ulsfo,
        ("SEA", "VLSFO"): sea_vlsfo,
        ("SEA", "MDO"): 0.0,
        ("PORT", "ULSFO"): 0.0,
        ("PORT", "VLSFO"): 0.0,
        ("PORT", "MDO"): port_mdo,
    }
    return ConsumptionProfile(
        vessel_id=1,
        rates=tuple(
            ConsumptionRate(mode, fuel_type, value)
            for (mode, fuel_type), value in rates.items()
        ),
    )


def test_engine_calculates_known_sea_consumption():
    timeline = build_schedule_timeline(
        [
            event(1, arrival_at=datetime(2026, 9, 1, 8), departure_at=datetime(2026, 9, 1, 20)),
            event(2, arrival_at=datetime(2026, 9, 3, 8), departure_at=None),
        ]
    )

    result = calculate_schedule_consumption(timeline, profile(sea_ulsfo=24.0))

    assert result.rows[1].sea_hours == 36
    assert result.rows[1].consumed_mt["ULSFO"] == 36
    assert result.totals_mt["ULSFO"] == 36


def test_engine_calculates_known_port_consumption():
    timeline = build_schedule_timeline(
        [event(1, arrival_at=datetime(2026, 9, 1, 8), departure_at=datetime(2026, 9, 1, 20))]
    )

    result = calculate_schedule_consumption(timeline, profile(port_mdo=4.0))

    assert result.rows[0].port_hours == 12
    assert result.rows[0].consumed_mt["MDO"] == 2
    assert result.totals_mt["MDO"] == 2


def test_engine_calculates_multi_event_multi_fuel_totals():
    timeline = build_schedule_timeline(
        [
            event(1, arrival_at=datetime(2026, 9, 1, 8), departure_at=datetime(2026, 9, 1, 20)),
            event(2, arrival_at=datetime(2026, 9, 2, 20), departure_at=datetime(2026, 9, 3, 20)),
        ]
    )

    result = calculate_schedule_consumption(timeline, profile(sea_ulsfo=24.0, sea_vlsfo=12.0, port_mdo=4.0))

    assert result.totals_mt["ULSFO"] == 24
    assert result.totals_mt["VLSFO"] == 12
    assert result.totals_mt["MDO"] == 6


def test_engine_rejects_invalid_timeline_chronology():
    timeline = build_schedule_timeline(
        [
            event(1, arrival_at=datetime(2026, 9, 2, 8), departure_at=datetime(2026, 9, 2, 20)),
            event(2, arrival_at=datetime(2026, 9, 1, 8), departure_at=None),
        ]
    )

    with pytest.raises(ValueError, match="chronology is invalid"):
        calculate_schedule_consumption(timeline, profile(sea_ulsfo=24.0))
