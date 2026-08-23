import pytest

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.fuel_tank_service import (
    FuelTankService,
    FuelTankValidationError,
)


@pytest.fixture
def service_and_tank(tmp_path):
    database = Database(tmp_path / "service-snapshots.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO vessels (id, name, imo, created_at, updated_at) "
            "VALUES (1, 'Test Vessel', '1234567', 'x', 'x')"
        )
    service = FuelTankService(FuelTankRepository(database))
    tank = service.create_tank(
        FuelTank(None, 1, "HFO Deep Tank 1", "BUNKER", 500, "SOUNDING")
    )
    service.replace_calibration_points(
        tank.id,
        [
            TankCalibrationPoint(None, tank.id, 0, None, 0, 0),
            TankCalibrationPoint(None, tank.id, 100, None, 0, 200),
        ],
    )
    return service, tank


def save_observation(service, tank, **changes):
    values = {
        "tank_id": tank.id,
        "reading_type": "SOUNDING",
        "reading_cm": 80,
        "trim_m": 0,
        "effective_at_utc": "2026-01-01T00:00:00+00:00",
    }
    values.update(changes)
    return service.save_sounding_observation(**values)


def test_physical_volume_only_sounding_remains_supported(service_and_tank):
    service, tank = service_and_tank

    saved = save_observation(service, tank)

    assert saved.calculated_volume_m3 == 160
    assert (saved.manual_vcf, saved.standard_volume_15_m3) == (None, None)
    assert (saved.calculated_density_kg_m3, saved.calculated_mass_mt) == (None, None)


def test_service_delegates_manual_vcf_calculation(service_and_tank):
    service, _ = service_and_tank

    result = service.calculate_manual_vcf_mass(160, 0.985, 950)

    assert result.standard_volume_15_m3 == pytest.approx(157.6)
    assert result.mass_mt == pytest.approx(149.72)


def test_full_snapshot_saves_and_reloads_without_batch_density_derivation(service_and_tank):
    service, tank = service_and_tank
    batch = service.create_fuel_batch(
        FuelBatch(None, 1, "Current batch", "VLSFO", 990)
    )

    saved = save_observation(
        service,
        tank,
        fuel_batch_id=None,
        manual_vcf=0.985,
        standard_volume_15_m3=157.6,
        calculated_density_kg_m3=950,
        calculated_mass_mt=149.72,
    )

    assert saved.fuel_batch_id is None
    assert (
        saved.calculated_volume_m3,
        saved.manual_vcf,
        saved.standard_volume_15_m3,
        saved.calculated_density_kg_m3,
        saved.calculated_mass_mt,
    ) == (160, 0.985, 157.6, 950, 149.72)
    assert service.get_latest_sounding(tank.id) == saved
    assert batch.density_15_kg_m3 != saved.calculated_density_kg_m3


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"manual_vcf": 0.985, "standard_volume_15_m3": 150, "calculated_density_kg_m3": 950, "calculated_mass_mt": 149.72}, "Standard volume"),
        ({"manual_vcf": 0.985, "standard_volume_15_m3": 157.6, "calculated_density_kg_m3": 950, "calculated_mass_mt": 140}, "Calculated mass"),
        ({"manual_vcf": 0.985}, "Mass snapshot requires"),
        ({"calculated_density_kg_m3": 950}, "Mass snapshot requires"),
        ({"calculated_mass_mt": 149.72}, "Mass snapshot requires"),
        ({"standard_volume_15_m3": 157.6}, "Mass snapshot requires"),
    ],
)
def test_rejects_inconsistent_or_partial_mass_snapshots(service_and_tank, changes, message):
    service, tank = service_and_tank

    with pytest.raises(FuelTankValidationError, match=message):
        save_observation(service, tank, **changes)
