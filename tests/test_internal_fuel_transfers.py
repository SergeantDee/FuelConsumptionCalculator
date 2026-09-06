from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from fuel_consumption_calculator.domain.bunker import BunkerTankReceipt
from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, InternalFuelTransfer, TankSounding
from fuel_consumption_calculator.domain.tank_forecast import (
    TankConsumptionAllocationEvent,
    TankConsumptionPlan,
    TankConsumptionPlanPhase,
    TankConsumptionPlanPhaseTank,
)
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService, FuelTankValidationError
from fuel_consumption_calculator.services.tank_forecast_service import TankForecastService
from tests.test_tank_depletion_forecast import START, _interval
from fuel_consumption_calculator.calculations.tank_depletion_engine import estimate_tank_empty_time


def _service(tmp_path):
    database = Database(tmp_path / "transfers.db"); database.initialize()
    VesselRepository(database).save_active("Vessel", "1234567")
    service = FuelTankService(FuelTankRepository(database))
    vlsfo = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO", "VLSFO", 950))
    ulsfo = service.create_fuel_batch(FuelBatch(None, 1, "ULSFO", "ULSFO", 950))
    source = service.create_tank(FuelTank(None, 1, "Source", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=vlsfo.id))
    destination = service.create_tank(FuelTank(None, 1, "Destination", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=vlsfo.id))
    incompatible = service.create_tank(FuelTank(None, 1, "Other", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=ulsfo.id))
    for tank in (source, destination):
        service._repository.save_sounding(TankSounding(None, tank.id, START.isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=100, fuel_batch_id=tank.current_fuel_batch_id))
    _use_intervals(service, [])
    return service, source, destination, incompatible


def _use_intervals(service, intervals):
    service.set_internal_transfer_mass_authority(lambda transfer: service.available_tank_mass_at(
        transfer.vessel_id,
        transfer.from_tank_id,
        datetime.fromisoformat(transfer.effective_at_utc()),
        intervals,
        exclude_transfer_id=transfer.id,
    ))


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


@pytest.mark.parametrize(
    ("quantity", "accepted"),
    [(99.99, True), (100.0, True), (100.01, False)],
)
def test_transfer_quantity_is_checked_against_authoritative_source_mass(tmp_path, quantity, accepted):
    service, source, destination, _ = _service(tmp_path)
    if accepted:
        assert service.create_internal_fuel_transfer(_transfer(source, destination, quantity=quantity)).quantity_mt == quantity
    else:
        with pytest.raises(FuelTankValidationError, match=r"(?s)Insufficient source ROB.*Available: 100\.00 MT.*Requested: 100\.01 MT"):
            service.create_internal_fuel_transfer(_transfer(source, destination, quantity=quantity))


def test_future_transfer_uses_consumption_forecast_at_effective_utc(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    service.apply_consumption_tanks(1, [source.id], START)
    _use_intervals(service, [_interval(10, VLSFO=100)])

    with pytest.raises(FuelTankValidationError, match=r"(?s)Available: 20\.00 MT.*Requested: 30\.00 MT"):
        service.create_internal_fuel_transfer(_transfer(source, destination, hours=8, quantity=30))


def test_tank_forecast_service_wires_authority_into_transfer_save(tmp_path, monkeypatch):
    service, source, destination, _ = _service(tmp_path)
    service.apply_consumption_tanks(1, [source.id], START)
    forecast_service = TankForecastService(service, None, None, None)
    monkeypatch.setattr(forecast_service, "_future_intervals", lambda vessel_id: [_interval(10, VLSFO=100)])

    with pytest.raises(FuelTankValidationError, match=r"(?s)Available: 20\.00 MT.*Requested: 30\.00 MT"):
        service.create_internal_fuel_transfer(_transfer(source, destination, hours=8, quantity=30))


def test_consumption_before_transfer_reduces_available_source_mass(tmp_path):
    service, source, _, _ = _service(tmp_path)
    service.apply_consumption_tanks(1, [source.id], START)
    available = service.available_tank_mass_at(1, source.id, START + timedelta(hours=5), [_interval(10, VLSFO=40)])
    assert available == pytest.approx(80)


def test_earlier_transfer_in_increases_available_source_mass(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    service.create_internal_fuel_transfer(_transfer(destination, source, hours=2, quantity=30))
    assert service.create_internal_fuel_transfer(_transfer(source, destination, hours=5, quantity=130)).quantity_mt == 130


def test_earlier_transfer_out_reduces_available_source_mass(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    service.create_internal_fuel_transfer(_transfer(source, destination, hours=2, quantity=40))
    with pytest.raises(FuelTankValidationError, match=r"(?s)Available: 60\.00 MT.*Requested: 61\.00 MT"):
        service.create_internal_fuel_transfer(_transfer(source, destination, hours=5, quantity=61))


def test_confirmed_receipt_before_transfer_increases_available_source_mass(tmp_path, monkeypatch):
    service, source, destination, _ = _service(tmp_path)
    monkeypatch.setattr(
        service._repository,
        "list_confirmed_complete_bunker_receipts",
        lambda vessel_id: [BunkerTankReceipt(source.id, "VLSFO", 50, (START + timedelta(hours=2)).isoformat())],
    )
    assert service.create_internal_fuel_transfer(_transfer(source, destination, hours=5, quantity=150)).quantity_mt == 150


def test_later_mass_bearing_sounding_reanchors_transfer_availability(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    service._repository.save_sounding(TankSounding(None, source.id, (START + timedelta(hours=5)).isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=175, fuel_batch_id=source.current_fuel_batch_id))
    assert service.create_internal_fuel_transfer(_transfer(source, destination, quantity=175)).quantity_mt == 175


def test_later_non_mass_sounding_is_ignored_and_post_transfer_sounding_cannot_affect_history(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    service._repository.save_sounding(TankSounding(None, source.id, (START + timedelta(hours=5)).isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=None, fuel_batch_id=source.current_fuel_batch_id))
    service._repository.save_sounding(TankSounding(None, source.id, (START + timedelta(hours=12)).isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=500, fuel_batch_id=source.current_fuel_batch_id))

    with pytest.raises(FuelTankValidationError, match=r"(?s)Available: 100\.00 MT.*Requested: 101\.00 MT"):
        service.create_internal_fuel_transfer(_transfer(source, destination, hours=10, quantity=101))


def test_missing_authoritative_source_mass_is_rejected(tmp_path):
    service, _, destination, _ = _service(tmp_path)
    batch = service.get_fuel_batch(destination.current_fuel_batch_id)
    unknown = service.create_tank(FuelTank(None, 1, "Unknown mass", "BUNKER", 100, "SOUNDING", current_fuel_batch_id=batch.id))
    with pytest.raises(FuelTankValidationError, match="Source tank ROB at transfer time is unavailable"):
        service.create_internal_fuel_transfer(_transfer(unknown, destination, quantity=1))


def test_same_timestamp_proposal_follows_saved_transfer_outs_but_not_later_precedence_events(tmp_path, monkeypatch):
    service, source, destination, _ = _service(tmp_path)
    service.create_internal_fuel_transfer(_transfer(source, destination, quantity=60))
    service.create_internal_fuel_transfer(_transfer(destination, source, quantity=10))
    service._repository.save_sounding(TankSounding(None, source.id, (START + timedelta(hours=10)).isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=500, fuel_batch_id=source.current_fuel_batch_id))
    monkeypatch.setattr(
        service._repository,
        "list_confirmed_complete_bunker_receipts",
        lambda vessel_id: [BunkerTankReceipt(source.id, "VLSFO", 500, (START + timedelta(hours=10)).isoformat())],
    )

    with pytest.raises(FuelTankValidationError, match=r"(?s)Available: 40\.00 MT.*Requested: 40\.01 MT"):
        service.create_internal_fuel_transfer(_transfer(source, destination, quantity=40.01))


def test_editing_existing_transfer_replaces_old_record_for_validation(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    service._repository.save_sounding(TankSounding(None, source.id, START.isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=40, fuel_batch_id=source.current_fuel_batch_id))
    existing = service.create_internal_fuel_transfer(_transfer(source, destination, quantity=20))
    updated = service.update_internal_fuel_transfer(replace(existing, quantity_mt=30))
    assert updated.quantity_mt == 30


def test_valid_transfer_remains_aggregate_rob_neutral(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    before = service.predict_tank_rob_at(1, START + timedelta(hours=11), [])
    service.create_internal_fuel_transfer(_transfer(source, destination, quantity=25))
    after = service.predict_tank_rob_at(1, START + timedelta(hours=11), [])
    before_total = sum(item.predicted_mass_mt for item in before if item.predicted_mass_mt is not None)
    after_total = sum(item.predicted_mass_mt for item in after if item.predicted_mass_mt is not None)
    assert before_total == pytest.approx(after_total)


def test_transfer_out_advances_active_plan_depletion_time(tmp_path):
    service, source, destination, _ = _service(tmp_path)
    service._repository.save_sounding(TankSounding(None, source.id, START.isoformat(), "SOUNDING", 1, 0, None, 1, calculated_mass_mt=10, fuel_batch_id=source.current_fuel_batch_id))
    service.save_consumption_plan(TankConsumptionPlan(
        None, 1, "VLSFO", "ACTIVE", START,
        (TankConsumptionPlanPhase(None, 1, (TankConsumptionPlanPhaseTank(source.id, 1.0),)),),
    ))
    intervals = [_interval(20, VLSFO=20)]
    _use_intervals(service, intervals)
    before = {item.tank_id: item for item in service.predict_tank_rob_at(1, START + timedelta(hours=20), intervals)}[source.id].estimated_depleted_at_utc
    service.create_internal_fuel_transfer(_transfer(source, destination, hours=2, quantity=4))
    after = {item.tank_id: item for item in service.predict_tank_rob_at(1, START + timedelta(hours=20), intervals)}[source.id].estimated_depleted_at_utc
    assert before == START + timedelta(hours=10)
    assert after == START + timedelta(hours=6)
