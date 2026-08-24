from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from fuel_consumption_calculator.calculations.voyage_engine import _split_quantity_consumption
from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, MachineryFuelState


START = datetime(2026, 8, 25, tzinfo=timezone.utc)
STATE = MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO")


def _event(machinery: str, hour: float, from_fuel: str, to_fuel: str, *, actual_hour: float | None = None) -> FuelChangeoverEvent:
    return FuelChangeoverEvent(
        None,
        1,
        machinery,
        from_fuel,
        to_fuel,
        START + timedelta(hours=hour),
        START + timedelta(hours=actual_hour) if actual_hour is not None else None,
    )


def _split(machinery: str, events: list[FuelChangeoverEvent], *, hours: float = 10, rate: float = 2) -> dict[str, float]:
    return _split_quantity_consumption(
        machinery,
        START,
        START + timedelta(hours=hours),
        STATE,
        events,
        lambda interval_hours: interval_hours * rate,
    )


def _total(allocation: dict[str, float]) -> float:
    return sum(allocation[fuel] for fuel in FUEL_TYPES)


def test_midpoint_main_engine_changeover_reallocates_without_changing_total():
    baseline = _split("MAIN_ENGINE", [])
    split = _split("MAIN_ENGINE", [_event("MAIN_ENGINE", 6, "VLSFO", "ULSFO")])

    assert split == {"ULSFO": 8.0, "VLSFO": 12.0, "MDO": 0.0}
    assert _total(split) == pytest.approx(20.0)
    assert _total(split) == pytest.approx(_total(baseline))


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, {"ULSFO": 20.0, "VLSFO": 0.0, "MDO": 0.0}),
        (10, {"ULSFO": 0.0, "VLSFO": 20.0, "MDO": 0.0}),
    ],
)
def test_changeover_at_interval_boundary_has_no_overlap_or_gap(hour, expected):
    split = _split("MAIN_ENGINE", [_event("MAIN_ENGINE", hour, "VLSFO", "ULSFO")])

    assert split == expected
    assert _total(split) == pytest.approx(20.0)


def test_sequential_changeovers_charge_each_subinterval_once():
    split = _split(
        "MAIN_ENGINE",
        [
            _event("MAIN_ENGINE", 3, "VLSFO", "ULSFO"),
            _event("MAIN_ENGINE", 7, "ULSFO", "MDO"),
        ],
    )

    assert split == {"ULSFO": 8.0, "VLSFO": 6.0, "MDO": 6.0}
    assert _total(split) == pytest.approx(20.0)


def test_outside_changeover_has_no_effect_and_actual_timestamp_overrides_planned():
    outside = _split("MAIN_ENGINE", [_event("MAIN_ENGINE", 11, "VLSFO", "ULSFO")])
    actual_override = _split("MAIN_ENGINE", [_event("MAIN_ENGINE", 3, "VLSFO", "ULSFO", actual_hour=8)])

    assert outside == _split("MAIN_ENGINE", [])
    assert actual_override == {"ULSFO": 4.0, "VLSFO": 16.0, "MDO": 0.0}
    assert _total(actual_override) == pytest.approx(20.0)


@pytest.mark.parametrize(
    "machinery",
    ("MAIN_ENGINE", "GENERATORS", "AUX_BOILER"),
)
def test_each_machinery_changeover_only_reallocates_its_own_timeline(machinery):
    events = [_event(machinery, 6, "VLSFO", "ULSFO")]

    allocations = {name: _split(name, events) for name in ("MAIN_ENGINE", "GENERATORS", "AUX_BOILER")}

    assert allocations[machinery] == {"ULSFO": 8.0, "VLSFO": 12.0, "MDO": 0.0}
    for other_machinery, allocation in allocations.items():
        assert _total(allocation) == pytest.approx(20.0)
        if other_machinery != machinery:
            assert allocation == {"ULSFO": 0.0, "VLSFO": 20.0, "MDO": 0.0}
