import pytest

from fuel_consumption_calculator.domain.fuel_tank import FuelBatch, FuelTank, TankCalibrationPoint
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository
from fuel_consumption_calculator.services.fuel_tank_service import (
    FuelTankService,
    FuelTankValidationError,
)
from fuel_consumption_calculator.calculations.automatic_vcf import calculate_automatic_vcf
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionPlan, TankConsumptionPlanPhase, TankConsumptionPlanPhaseTank
from datetime import datetime, timedelta, timezone


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


@pytest.mark.parametrize("fuel,density,temperature", [("VLSFO", 978, 15), ("ULSFO", 950, 35), ("MDO", 840, 5)])
def test_automatic_sounding_snapshot_uses_assigned_batch_and_temperature(service_and_tank, fuel, density, temperature):
    service, tank = service_and_tank
    batch = service.create_fuel_batch(FuelBatch(None, 1, f"{fuel} basis", fuel, density))
    service.assign_fuel_batch_to_tank(tank.id, batch.id)

    saved = save_observation(service, tank, temperature_c=temperature)

    expected_vcf = calculate_automatic_vcf(density, temperature, fuel)
    assert saved.manual_vcf is None
    assert saved.calculated_density_kg_m3 == density
    assert saved.standard_volume_15_m3 == pytest.approx(saved.calculated_volume_m3 * expected_vcf)
    assert saved.calculated_mass_mt == pytest.approx(saved.calculated_volume_m3 * expected_vcf * density / 1000)


def test_missing_temperature_or_batch_leaves_auto_mass_unavailable(service_and_tank):
    service, tank = service_and_tank
    no_basis = save_observation(service, tank, temperature_c=25)
    batch = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO basis", "VLSFO", 978)); service.assign_fuel_batch_to_tank(tank.id, batch.id)
    no_temperature = save_observation(service, tank, temperature_c=None)
    assert no_basis.calculated_mass_mt is None and no_temperature.calculated_mass_mt is None


def test_unknown_fuel_basis_is_unavailable_for_automatic_sounding_vcf(service_and_tank):
    service, _tank = service_and_tank
    unknown = FuelBatch(None, 1, "Unknown", "UNKNOWN", 978)
    with pytest.raises(FuelTankValidationError, match="fuel type"):
        service.calculate_tank_sounding_mass(100, 25, unknown)


def test_manual_override_and_clearing_it_returns_to_auto(service_and_tank):
    service, tank = service_and_tank
    batch = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO basis", "VLSFO", 978)); service.assign_fuel_batch_to_tank(tank.id, batch.id)
    manual = save_observation(service, tank, temperature_c=35, manual_vcf=.985)
    automatic = save_observation(service, tank, temperature_c=35, manual_vcf=None, effective_at_utc="2026-01-02T00:00:00+00:00")
    assert manual.manual_vcf == .985
    assert automatic.manual_vcf is None
    assert automatic.standard_volume_15_m3 == pytest.approx(automatic.calculated_volume_m3 * calculate_automatic_vcf(978, 35, "VLSFO"))


def test_auto_snapshot_is_historical_after_batch_changes_and_reassignment(service_and_tank):
    service, tank = service_and_tank
    first = service.create_fuel_batch(FuelBatch(None, 1, "Original", "VLSFO", 978)); second = service.create_fuel_batch(FuelBatch(None, 1, "Later", "VLSFO", 930))
    service.assign_fuel_batch_to_tank(tank.id, first.id)
    saved = save_observation(service, tank, temperature_c=25)
    service.update_fuel_batch(FuelBatch(first.id, 1, "Original", "VLSFO", 990))
    service.assign_fuel_batch_to_tank(tank.id, second.id)
    historical = service.get_latest_sounding(tank.id)
    assert (historical.fuel_batch_id, historical.calculated_density_kg_m3, historical.standard_volume_15_m3, historical.calculated_mass_mt) == (first.id, 978, saved.standard_volume_15_m3, saved.calculated_mass_mt)


def test_automatic_mass_soundings_anchor_the_v21_multi_phase_forecast(service_and_tank):
    service, first = service_and_tank
    batch = service.create_fuel_batch(FuelBatch(None, 1, "VLSFO basis", "VLSFO", 978))
    second = service.create_tank(FuelTank(None, 1, "HFO Deep Tank 2P", "BUNKER", 500, "SOUNDING", current_fuel_batch_id=batch.id))
    third = service.create_tank(FuelTank(None, 1, "HFO Deep Tank 2S", "BUNKER", 500, "SOUNDING", current_fuel_batch_id=batch.id))
    for tank in (first, second, third):
        service.assign_fuel_batch_to_tank(tank.id, batch.id)
        service.replace_calibration_points(tank.id, [TankCalibrationPoint(None, tank.id, 0, None, 0, 0), TankCalibrationPoint(None, tank.id, 100, None, 0, 100)])
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for tank in (first, second, third):
        service.save_sounding_observation(tank_id=tank.id, reading_type="SOUNDING", reading_cm=100, trim_m=0, temperature_c=15, effective_at_utc=start)
    plan = TankConsumptionPlan(None, 1, "VLSFO", "ACTIVE", start, (
        TankConsumptionPlanPhase(None, 1, (TankConsumptionPlanPhaseTank(first.id, 1.0),)),
        TankConsumptionPlanPhase(None, 2, (TankConsumptionPlanPhaseTank(second.id, .5), TankConsumptionPlanPhaseTank(third.id, .5))),
    ))
    service.save_consumption_plan(plan)
    forecast = {item.tank_id: item for item in service.predict_tank_rob_at(1, start + timedelta(hours=150), [FuelDepletionInterval(start, start + timedelta(hours=150), {"VLSFO": 150.0})])}
    assert all(item.anchor_mass_mt is not None for item in forecast.values())
    assert forecast[first.id].estimated_depleted_at_utc is not None
    assert forecast[second.id].predicted_mass_mt is not None and forecast[third.id].predicted_mass_mt is not None
    assert all(item.predicted_mass_mt is None or item.predicted_mass_mt >= 0 for item in forecast.values())
