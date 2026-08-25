from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from fuel_consumption_calculator.calculations.voyage_engine import (
    _maneuvering_operational_losses,
    _port_consumption,
    _sea_consumption,
)
from fuel_consumption_calculator.domain.consumption import ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.domain.schedule import ScheduleEvent
from fuel_consumption_calculator.domain.voyage import FuelChangeoverEvent, GeneratorSfocPoint, MachineryFuelState, VesselEnergyConfig
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.voyage_repository import VoyageRepository


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
STATE = MachineryFuelState(1, "VLSFO", "VLSFO", "VLSFO")
SFOC = [GeneratorSfocPoint(1, 0, 200), GeneratorSfocPoint(1, 100, 200)]


def _config(**changes) -> VesselEnergyConfig:
    values = dict(
        vessel_id=1, port_base_load_kw=1000, sea_base_load_kw=1000,
        generator_rated_kw=1000, port_running_generators=1, sea_running_generators=1,
        aux_boiler_mt_per_hour=0.1, maneuvering_main_engine_mt_per_hour=1.0,
        maneuvering_generators_mt_per_hour=0.2, maneuvering_aux_boiler_mt_per_hour=0.0,
    )
    values.update(changes)
    return VesselEnergyConfig(**values)


def _profile() -> ConsumptionProfile:
    return ConsumptionProfile(1, tuple(ConsumptionRate(mode, fuel, 0.0) for mode in ("SEA", "PORT", "MANEUVERING") for fuel in ("ULSFO", "VLSFO", "MDO")))


def _event(hours: float) -> ScheduleEvent:
    return ScheduleEvent(1, 1, 1, "Port", "", START, START + timedelta(hours=hours), "manual", "Vessel", date(2026, 1, 1), "", "")


def test_zero_allowances_leave_port_total_unchanged():
    result = _port_consumption(_event(12), 12, None, _profile(), _config(), SFOC, STATE, [], START, START + timedelta(hours=12))
    assert result.total_consumed_mt == {"ULSFO": 0.0, "VLSFO": pytest.approx(3.6), "MDO": 0.0}
    assert result.auxiliary_engine_operational_loss_mt == {"ULSFO": 0.0, "VLSFO": 0.0, "MDO": 0.0}


def test_port_ae_loss_is_collective_and_independent_of_dg_sfoc_completeness():
    config = _config(port_running_generators=3, generator_rated_kw=0, auxiliary_engine_loss_allowance_mt_per_day=0.4)
    result = _port_consumption(_event(12), 12, None, _profile(), config, SFOC, STATE, [], START, START + timedelta(hours=12))
    assert result.main_engine_operational_loss_mt == {"ULSFO": 0.0, "VLSFO": 0.0, "MDO": 0.0}
    assert result.auxiliary_engine_operational_loss_mt == {"ULSFO": 0.0, "VLSFO": 0.2, "MDO": 0.0}
    assert result.generator_consumed_mt["VLSFO"] is None
    assert result.total_consumed_mt["VLSFO"] is None


def test_sea_losses_are_proportional_and_follow_independent_fuel_changeovers():
    changes = [
        FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", START + timedelta(hours=12)),
        FuelChangeoverEvent(None, 1, "GENERATORS", "VLSFO", "MDO", START + timedelta(hours=12)),
    ]
    result = _sea_consumption(
        24, 10, _profile(), [], _config(main_engine_loss_allowance_mt_per_day=1.2, auxiliary_engine_loss_allowance_mt_per_day=0.6), SFOC,
        0, 50, 1.0, False, [], STATE, changes, START, START + timedelta(hours=24),
    )
    assert result["main_engine_loss"] == {"ULSFO": 0.6, "VLSFO": 0.6, "MDO": 0.0}
    assert result["auxiliary_engine_loss"] == {"ULSFO": 0.0, "VLSFO": 0.3, "MDO": 0.3}
    assert sum(result["main_engine_loss"].values()) == pytest.approx(1.2)
    assert sum(result["auxiliary_engine_loss"].values()) == pytest.approx(0.6)


def test_actual_changeover_time_and_interval_boundaries_control_loss_allocation():
    at_start = FuelChangeoverEvent(None, 1, "MAIN_ENGINE", "VLSFO", "ULSFO", START + timedelta(hours=20), actual_at_utc=START)
    at_end = FuelChangeoverEvent(None, 1, "GENERATORS", "VLSFO", "MDO", START + timedelta(hours=4), actual_at_utc=START + timedelta(hours=24))
    me_loss, ae_loss = _maneuvering_operational_losses(
        _config(main_engine_loss_allowance_mt_per_day=1.0, auxiliary_engine_loss_allowance_mt_per_day=1.0), STATE,
        [at_start, at_end], START, START + timedelta(hours=2),
    )
    assert me_loss == {"ULSFO": pytest.approx(2 / 24), "VLSFO": 0.0, "MDO": 0.0}
    assert ae_loss == {"ULSFO": 0.0, "VLSFO": pytest.approx(2 / 24), "MDO": 0.0}


def test_maneuvering_losses_use_maneuvering_duration():
    me_loss, ae_loss = _maneuvering_operational_losses(
        _config(main_engine_loss_allowance_mt_per_day=1.0, auxiliary_engine_loss_allowance_mt_per_day=0.5), STATE, [], START, START + timedelta(hours=2)
    )
    assert sum(me_loss.values()) == pytest.approx(2 / 24)
    assert sum(ae_loss.values()) == pytest.approx(1 / 24)


def test_loss_settings_persist_and_default_to_zero(tmp_path):
    database = Database(tmp_path / "losses.db")
    database.initialize()
    repository = VoyageRepository(database)
    assert repository.load_energy_config(1).main_engine_loss_allowance_mt_per_day == 0.0
    with database.connect() as connection:
        connection.execute("INSERT INTO vessels (id, name, imo, created_at, updated_at) VALUES (1, 'Vessel', '1234567', 'x', 'x')")
    saved = repository.save_energy_config(_config(main_engine_loss_allowance_mt_per_day=1.25, auxiliary_engine_loss_allowance_mt_per_day=0.375))
    assert saved.main_engine_loss_allowance_mt_per_day == 1.25
    assert saved.auxiliary_engine_loss_allowance_mt_per_day == 0.375
