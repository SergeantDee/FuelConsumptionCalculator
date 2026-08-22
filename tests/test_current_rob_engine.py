from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.calculations.current_rob_engine import estimate_current_rob
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, MachineryFuelState, VesselEnergyConfig
from fuel_consumption_calculator.domain.voyage_stages import OperationalStage, StageROB


def test_anchor_at_current_time_is_unchanged():
    now = _dt(10)
    assert estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=now, current_utc=now, stages=[], initial_fuel_state=_state(), fuel_changeovers=()) == _rob(100)


def test_partial_stage_deducts_exact_elapsed_fraction():
    stage = _stage(0, 10, 20.0)
    estimated = estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(5), stages=[stage], initial_fuel_state=_state(), fuel_changeovers=(), energy_config=_config())
    assert estimated == {"ULSFO": 100.0, "VLSFO": 90.0, "MDO": 100.0}


def test_full_stage_plus_partial_next_stage_is_deducted():
    estimated = estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(15), stages=[_stage(0, 10, 20.0), _stage(10, 20, 10.0)], initial_fuel_state=_state(), fuel_changeovers=(), energy_config=_config())
    assert estimated["VLSFO"] == 70.0


def test_elapsed_changeover_splits_consumption_and_future_changeover_does_not():
    change = FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", _dt(5))
    future = FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "MDO", _dt(20))
    estimated = estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(10), stages=[_stage(0, 10, 20.0)], initial_fuel_state=_state(), fuel_changeovers=(change, future), energy_config=_config())
    assert estimated == {"ULSFO": 90.0, "VLSFO": 90.0, "MDO": 100.0}


def test_unknown_elapsed_consumption_propagates_unknown():
    stage = _stage(0, 10, None)
    estimated = estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(5), stages=[stage], initial_fuel_state=_state(), fuel_changeovers=(), energy_config=None)
    assert estimated == {"ULSFO": None, "VLSFO": None, "MDO": None}


def test_partial_maneuvering_uses_me_ae_and_ab_rates_on_their_own_fuels():
    config = VesselEnergyConfig(1, maneuvering_main_engine_mt_per_hour=2.0, maneuvering_generators_mt_per_hour=1.0, maneuvering_aux_boiler_mt_per_hour=0.5)
    state = MachineryFuelState(1, "VLSFO", "ULSFO", "MDO")
    estimated = estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(2), stages=[_stage(0, 10, 0.0)], initial_fuel_state=state, fuel_changeovers=(), energy_config=config)
    assert estimated == {"ULSFO": 98.0, "VLSFO": 96.0, "MDO": 99.0}


def test_unknown_nonzero_machinery_fuel_fails_closed_but_zero_rate_does_not_need_fuel():
    config = VesselEnergyConfig(1, maneuvering_main_engine_mt_per_hour=2.0, maneuvering_generators_mt_per_hour=0.0, maneuvering_aux_boiler_mt_per_hour=0.0)
    state = MachineryFuelState(1, "VLSFO", None, None)  # type: ignore[arg-type]
    estimated = estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(1), stages=[_stage(0, 10, 0.0)], initial_fuel_state=state, fuel_changeovers=(), energy_config=config)
    assert estimated["VLSFO"] == 98.0

    unknown_config = VesselEnergyConfig(1, maneuvering_main_engine_mt_per_hour=2.0, maneuvering_generators_mt_per_hour=1.0, maneuvering_aux_boiler_mt_per_hour=0.0)
    assert estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(1), stages=[_stage(0, 10, 0.0)], initial_fuel_state=state, fuel_changeovers=(), energy_config=unknown_config) == {"ULSFO": None, "VLSFO": None, "MDO": None}


def test_uncovered_elapsed_gap_is_not_treated_as_zero_consumption():
    assert estimate_current_rob(anchor_quantities_mt=_rob(100), anchor_at_utc=_dt(0), current_utc=_dt(3), stages=[_stage(0, 2, 4.0)], initial_fuel_state=_state(), fuel_changeovers=(), energy_config=_config()) == {"ULSFO": None, "VLSFO": None, "MDO": None}


def _stage(start_hour: int, end_hour: int, consumed: float | None) -> OperationalStage:
    values = {"ULSFO": 0.0, "VLSFO": consumed, "MDO": 0.0}
    return OperationalStage("stage", "DEPARTURE_MANEUVERING", "Test", "", "CURRENT", _dt(start_hour), _dt(end_hour), None, None, None, values, StageROB(_rob(0), _rob(0)))


def _state() -> MachineryFuelState:
    return MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO")


def _config() -> VesselEnergyConfig:
    return VesselEnergyConfig(1, maneuvering_main_engine_mt_per_hour=2.0, maneuvering_generators_mt_per_hour=0.0, maneuvering_aux_boiler_mt_per_hour=0.0)


def _rob(value: float) -> dict[str, float]:
    return {"ULSFO": value, "VLSFO": value, "MDO": value}


def _dt(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=timezone.utc)
