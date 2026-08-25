from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from fuel_consumption_calculator.calculations.voyage_engine import _port_consumption, _port_hours
from fuel_consumption_calculator.domain.consumption import ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.schedule_timeline import build_schedule_timeline
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, GeneratorSfocPoint, MachineryFuelState, VesselEnergyConfig


START = datetime(2026, 9, 3, 6, tzinfo=timezone.utc)
STATE = MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO")
SFOC = [GeneratorSfocPoint(1, 0, 200), GeneratorSfocPoint(1, 100, 200)]


def _event(departure: datetime | None = None) -> ScheduleEvent:
    return ScheduleEvent(
        1, 1, 1, "Test Port", "Port Call", START, departure, "manual", "Test Vessel", date(2026, 9, 1), "", ""
    )


def _config(**changes) -> VesselEnergyConfig:
    values = {
        "vessel_id": 1,
        "port_base_load_kw": 1000,
        "generator_rated_kw": 1000,
        "port_running_generators": 1,
        "aux_boiler_mt_per_hour": 0.1,
    }
    values.update(changes)
    return VesselEnergyConfig(**values)


def _breakdown(*, config: VesselEnergyConfig | None = None, changes: list[FuelChangeoverEvent] | None = None, hours: float = 10):
    return _port_consumption(
        _event(START + timedelta(hours=hours)),
        hours,
        None,
        _profile(),
        config or _config(),
        SFOC,
        STATE,
        changes or [],
        START,
        START + timedelta(hours=hours),
    )


def _profile() -> ConsumptionProfile:
    return ConsumptionProfile(1, tuple(ConsumptionRate(mode, fuel, 0) for mode in ("SEA", "PORT", "MANEUVERING") for fuel in ("ULSFO", "VLSFO", "MDO")))


def test_valid_port_stay_runs_generator_and_always_running_aux_boiler():
    result = _breakdown()

    assert result.port_hours == 10
    assert result.generator_consumed_mt == {"ULSFO": 0.0, "VLSFO": 2.0, "MDO": 0.0}
    assert result.boiler_consumed_mt == {"ULSFO": 0.0, "VLSFO": 1.0, "MDO": 0.0}
    assert result.total_consumed_mt == {"ULSFO": 0.0, "VLSFO": 3.0, "MDO": 0.0}


def test_missing_dg_configuration_does_not_suppress_known_boiler_consumption():
    result = _breakdown(config=_config(generator_rated_kw=0))

    assert result.calculation_mode == "INCOMPLETE"
    assert result.generator_consumed_mt["VLSFO"] is None
    assert result.boiler_consumed_mt == {"ULSFO": 0.0, "VLSFO": 1.0, "MDO": 0.0}
    assert all(value is None for value in result.total_consumed_mt.values())
    assert result.warnings


def test_aux_boiler_changeover_during_port_stay_reallocates_without_changing_total():
    changeover = FuelChangeoverEvent(None, 1, "AUX_BOILER", "VLSFO", "ULSFO", START + timedelta(hours=5))
    result = _breakdown(changes=[changeover])

    assert result.boiler_consumed_mt == {"ULSFO": 0.5, "VLSFO": 0.5, "MDO": 0.0}
    assert sum(result.total_consumed_mt.values()) == pytest.approx(3.0)


def test_port_hours_keep_actual_or_schedule_duration_and_timeline_distinguishes_missing_duration():
    event = _event(START + timedelta(hours=10))

    assert _port_hours(event, START, START + timedelta(hours=8), 10) == 8
    assert _port_hours(event, None, None, 10) == 10
    assert build_schedule_timeline([_event(None)]).rows[0].port_stay_hours is None
    assert _port_hours(_event(None), None, None, None) is None
    assert _port_hours(event, START, START, 10) == 0
