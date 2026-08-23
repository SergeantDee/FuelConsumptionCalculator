from dataclasses import replace
from math import inf, nan

import pytest

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.fuel_tank_service import (
    FuelTankService,
    FuelTankValidationError,
)


@pytest.fixture
def service(tmp_path):
    database = Database(tmp_path / "fuel-batches.db")
    database.initialize()
    with database.connect() as connection:
        connection.executemany(
            "INSERT INTO vessels (id, name, imo, created_at, updated_at) VALUES (?, ?, ?, 'x', 'x')",
            [(1, "Vessel One", "1234567"), (2, "Vessel Two", "7654321")],
        )
    return FuelTankService(FuelTankRepository(database))


def batch(vessel_id=1, **changes):
    values = dict(
        id=None,
        vessel_id=vessel_id,
        batch_name="  Singapore August  ",
        fuel_type="VLSFO",
        density_15_kg_m3=950,
    )
    values.update(changes)
    return FuelBatch(**values)


@pytest.mark.parametrize("fuel_type", ["ULSFO", "VLSFO", "MDO"])
def test_creates_each_supported_fuel_batch_type_and_trims_name(service, fuel_type):
    saved = service.create_fuel_batch(batch(fuel_type=fuel_type))

    assert saved.id is not None
    assert saved.fuel_type == fuel_type
    assert saved.batch_name == "Singapore August"


@pytest.mark.parametrize(
    "changes",
    [
        {"fuel_type": "HFO"},
        {"batch_name": "   "},
        {"density_15_kg_m3": 0},
        {"density_15_kg_m3": -1},
        {"density_15_kg_m3": nan},
        {"density_15_kg_m3": inf},
        {"sulfur_percent": -0.1},
        {"viscosity_50_cst": 0},
        {"water_percent": -0.1},
        {"flash_point_c": inf},
        {"pour_point_c": nan},
    ],
)
def test_rejects_invalid_fuel_batch_values(service, changes):
    with pytest.raises(FuelTankValidationError):
        service.create_fuel_batch(batch(**changes))


def test_lists_and_retrieves_only_the_requested_vessels_batches(service):
    one_b = service.create_fuel_batch(batch(batch_name="Bravo"))
    one_a = service.create_fuel_batch(batch(batch_name="Alpha"))
    two = service.create_fuel_batch(batch(2, batch_name="Other vessel"))

    assert service.list_fuel_batches(1) == [one_a, one_b]
    assert service.list_fuel_batches(2) == [two]
    assert service.get_fuel_batch(one_a.id) == one_a


def test_edits_batch_but_cannot_change_vessel_ownership(service):
    saved = service.create_fuel_batch(batch())
    updated = service.update_fuel_batch(
        replace(saved, batch_name="Updated", density_15_kg_m3=960, water_percent=0.1)
    )

    assert updated.batch_name == "Updated"
    assert updated.density_15_kg_m3 == 960
    with pytest.raises(FuelTankValidationError, match="vessel ownership"):
        service.update_fuel_batch(replace(updated, vessel_id=2))


def _tank(service, vessel_id=1):
    tank = service.create_tank(
        FuelTank(None, vessel_id, f"Tank {vessel_id}", "BUNKER", 500, "SOUNDING")
    )
    service.replace_calibration_points(
        tank.id,
        [
            TankCalibrationPoint(None, tank.id, 0, None, 0, 0),
            TankCalibrationPoint(None, tank.id, 100, None, 0, 200),
        ],
    )
    return tank


def test_assign_change_and_clear_current_batch_without_deleting_it(service):
    tank = _tank(service)
    first = service.create_fuel_batch(batch(batch_name="First"))
    second = service.create_fuel_batch(batch(batch_name="Second"))

    assert service.assign_fuel_batch_to_tank(tank.id, first.id).current_fuel_batch_id == first.id
    assert service.assign_fuel_batch_to_tank(tank.id, second.id).current_fuel_batch_id == second.id
    assert service.clear_fuel_batch_from_tank(tank.id).current_fuel_batch_id is None
    assert service.get_fuel_batch(first.id) == first
    assert service.get_fuel_batch(second.id) == second


def test_rejects_cross_vessel_batch_assignment(service):
    tank = _tank(service, 1)
    other_batch = service.create_fuel_batch(batch(2))

    with pytest.raises(FuelTankValidationError, match="tank vessel"):
        service.assign_fuel_batch_to_tank(tank.id, other_batch.id)


def test_batch_edits_and_current_assignment_changes_do_not_change_history(service):
    tank = _tank(service)
    original_batch = service.create_fuel_batch(batch(density_15_kg_m3=950))
    replacement_batch = service.create_fuel_batch(batch(batch_name="Replacement", density_15_kg_m3=960))
    service.assign_fuel_batch_to_tank(tank.id, original_batch.id)
    saved = service.save_sounding_observation(
        tank_id=tank.id,
        reading_type="SOUNDING",
        reading_cm=80,
        trim_m=0,
        effective_at_utc="2026-01-01T00:00:00+00:00",
        fuel_batch_id=original_batch.id,
        manual_vcf=0.985,
        standard_volume_15_m3=157.6,
        calculated_density_kg_m3=950,
        calculated_mass_mt=149.72,
    )

    service.assign_fuel_batch_to_tank(tank.id, replacement_batch.id)
    service.update_fuel_batch(replace(original_batch, density_15_kg_m3=960))
    historical = service.get_latest_sounding(tank.id)

    assert historical == saved
    assert (
        historical.fuel_batch_id,
        historical.calculated_density_kg_m3,
        historical.manual_vcf,
        historical.standard_volume_15_m3,
        historical.calculated_mass_mt,
    ) == (original_batch.id, 950, 0.985, 157.6, 149.72)
