from __future__ import annotations

from datetime import timedelta

import pytest

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, InternalFuelTransfer, TankSounding
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService, FuelTankValidationError
from tests.test_tank_depletion_forecast import START, _interval
from fuel_consumption_calculator.calculations.tank_depletion_engine import estimate_tank_empty_time
from fuel_consumption_calculator.domain.tank_forecast import TankConsumptionAllocationEvent


def _service(tmp_path):
    database = Database(tmp_path / "transfers.db"); database.initialize()
    VesselRepository(database).save_active("Vessel", "1234567")
    service = FuelTankService(FuelTankRepository(database))
    vlsfo = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO", "VLSFO", 950))
    ulsfo = service.create_fuel_batch(FuelBatch(None, 1, "ULSFO", "ULSFO", 950))
    source = service.create_tank(FuelTank(None, 1, "Source", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=vlsfo.id))
    destination = service.create_tank(FuelTank(None, 1, "Destination", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=vlsfo.id))
    incompatible = service.create_tank(FuelTank(None, 1, "Other", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=ulsfo.id))
    return service, source, destination, incompatible


def _transfer(source, destination, *, status="PLANNED", hours=10, actual=None, quantity=100):
    return InternalFuelTransfer(None, 1, source.id, destination.id, "VLSFO", quantity, status, (START + timedelta(hours=hours)).isoformat(), actual)


def test_create_and_complete_transfer_persist_with_effective_time(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    planned = service.create_internal_fuel_transfer(_transfer(source, destination))
    assert planned.status == "PLANNED" and planned.effective_at_utc() == planned.planned_at_utc
    completed = service.complete_internal_fuel_transfer(planned.id, START + timedelta(hours=12))
    assert completed.status == "COMPLETED"
    assert completed.effective_at_utc() == (START + timedelta(hours=12)).isoformat()
    assert service.get_internal_fuel_transfer(planned.id) == completed


@pytest.mark.parametrize("quantity", [0, -1])
def test_transfer_quantity_and_tanks_are_validated(tmp_path, quantity):
    service, source, destination, _ = _service(tmp_path)
    with pytest.raises(FuelTankValidationError, match="quantity"):
        service.create_internal_fuel_transfer(_transfer(source, destination, quantity=quantity))
    with pytest.raises(FuelTankValidationError, match="different"):
        service.create_internal_fuel_transfer(_transfer(source, source))


def test_transfer_fuel_compatibility_and_vessel_ownership(tmp_path):
    service, source, destination, incompatible = _service(tmp_path)
    with pytest.raises(FuelTankValidationError, match="same fuel"):
        service.create_internal_fuel_transfer(_transfer(source, incompatible))
    bad = InternalFuelTransfer(None, 2, source.id, destination.id, "VLSFO", 1, "PLANNED", START.isoformat())
    with pytest.raises(FuelTankValidationError, match="selected vessel"):
        service.create_internal_fuel_transfer(bad)
    unknown = service.create_tank(FuelTank(None, 1, "Unknown", "BUNKER", 100, "SOUNDING"))
    with pytest.raises(FuelTankValidationError, match="assigned fuel batch"):
        service.create_internal_fuel_transfer(_transfer(unknown, destination))


def test_transfers_change_only_individual_tank_forecasts_and_reanchor(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    repository = service._repository
    for tank, mass in ((source, 300), (destination, 100)):
        repository.save_sounding(TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=mass, fuel_batch_id=tank.current_fuel_batch_id))
    service.apply_consumption_tanks(1, [source.id], START)
    service.create_internal_fuel_transfer(_transfer(source, destination))
    forecasts = {item.tank_id: item for item in service.predict_tank_rob_at(1, START + timedelta(hours=20), [_interval(20, VLSFO=40)])}
    assert forecasts[source.id].predicted_mass_mt == pytest.approx(160)
    assert forecasts[destination.id].predicted_mass_mt == pytest.approx(200)
    assert sum(item.predicted_mass_mt for item in forecasts.values() if item.predicted_mass_mt is not None) == pytest.approx(360)
    repository.save_sounding(TankSounding(None, source.id, (START + timedelta(hours=15)).isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=190, fuel_batch_id=source.current_fuel_batch_id))
    reanchored = {item.tank_id: item for item in service.predict_tank_rob_at(1, START + timedelta(hours=20), [_interval(20, VLSFO=40)])}
    assert reanchored[source.id].predicted_mass_mt == pytest.approx(180)
    assert len(service.list_consumption_allocation_events(1)) == 1


def test_completed_transfer_uses_actual_time_only_and_empty_forecast_reflects_movements(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    completed = service.create_internal_fuel_transfer(_transfer(source, destination, status="COMPLETED", actual=(START + timedelta(hours=12)).isoformat()))
    repository = service._repository
    for tank in (source, destination):
        repository.save_sounding(TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=100, fuel_batch_id=tank.current_fuel_batch_id))
    before_actual = {item.tank_id: item for item in service.predict_tank_rob_at(1, START + timedelta(hours=11), [_interval(20, VLSFO=0)])}
    after_actual = {item.tank_id: item for item in service.predict_tank_rob_at(1, START + timedelta(hours=13), [_interval(20, VLSFO=0)])}
    assert before_actual[source.id].predicted_mass_mt == 100
    assert after_actual[source.id].predicted_mass_mt == 0
    assert after_actual[destination.id].predicted_mass_mt == 200
    assert completed.effective_at_utc() == (START + timedelta(hours=12)).isoformat()
    interval = _interval(20, VLSFO=80)
    allocation = TankConsumptionAllocationEvent(None, 1, START, (source.id,))
    no_transfer = estimate_tank_empty_time(source.id, "VLSFO", 50, START, [interval], [allocation], {source.id: "VLSFO"})
    with_out = estimate_tank_empty_time(source.id, "VLSFO", 50, START, [interval], [allocation], {source.id: "VLSFO"}, [_transfer(source, destination, quantity=30)])
    with_in = estimate_tank_empty_time(destination.id, "VLSFO", 50, START, [interval], [TankConsumptionAllocationEvent(None, 1, START, (destination.id,))], {destination.id: "VLSFO"}, [_transfer(source, destination, quantity=30)])
    assert with_out[0] < no_transfer[0]
    assert with_in[0] > no_transfer[0]
