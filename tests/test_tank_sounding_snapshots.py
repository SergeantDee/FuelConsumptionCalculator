from math import inf, nan

import pytest

from fuel_consumption_calculator.domain.fuel_tank import FuelTank, TankSounding
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.fuel_tank_repository import FuelTankRepository


def sounding(**changes):
    values = dict(id=None, tank_id=1, effective_at_utc="2026-01-01T00:00:00+00:00", reading_type="SOUNDING", reading_cm=10, trim_m=0, temperature_c=None, calculated_volume_m3=12)
    values.update(changes)
    return TankSounding(**values)


def test_snapshot_fields_default_to_none_and_accept_valid_values():
    assert sounding().manual_vcf is None and sounding().standard_volume_15_m3 is None
    result = sounding(manual_vcf=0.985, standard_volume_15_m3=11.82)
    assert result.manual_vcf == 0.985 and result.standard_volume_15_m3 == 11.82


@pytest.mark.parametrize("value", [0, -1, nan, inf, -inf])
def test_rejects_invalid_manual_vcf(value):
    with pytest.raises(ValueError, match="Manual VCF"):
        sounding(manual_vcf=value)


@pytest.mark.parametrize("value", [-1, nan, inf, -inf])
def test_rejects_invalid_standard_volume(value):
    with pytest.raises(ValueError, match="Standard volume"):
        sounding(standard_volume_15_m3=value)


def _repository_with_tank(tmp_path):
    database = Database(tmp_path / "soundings.db")
    database.initialize()
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO vessels (id, name, imo, created_at, updated_at) VALUES (1, 'Test Vessel', '1234567', 'x', 'x')"
        )
    repository = FuelTankRepository(database)
    tank = repository.save_tank(
        FuelTank(None, 1, "HFO Deep Tank 1", "BUNKER", 100, "SOUNDING")
    )
    return repository, tank


def test_repository_persists_and_reads_full_manual_vcf_snapshot(tmp_path):
    repository, tank = _repository_with_tank(tmp_path)
    saved = repository.save_sounding(
        sounding(
            tank_id=tank.id,
            effective_at_utc="2026-01-01T12:00:00+00:00",
            calculated_volume_m3=160.0,
            calculated_density_kg_m3=950.0,
            calculated_mass_mt=149.72,
            manual_vcf=0.985,
            standard_volume_15_m3=157.6,
        )
    )

    assert saved.calculated_volume_m3 == 160.0
    assert saved.manual_vcf == 0.985
    assert saved.standard_volume_15_m3 == 157.6
    assert saved.calculated_density_kg_m3 == 950.0
    assert saved.calculated_mass_mt == 149.72
    assert repository.get_latest_sounding(tank.id) == saved
    assert repository.list_sounding_history(tank.id) == [saved]


def test_repository_preserves_null_snapshots_in_latest_and_history_reads(tmp_path):
    repository, tank = _repository_with_tank(tmp_path)
    earlier = repository.save_sounding(
        sounding(tank_id=tank.id, effective_at_utc="2026-01-01T00:00:00+00:00")
    )
    later = repository.save_sounding(
        sounding(
            tank_id=tank.id,
            effective_at_utc="2026-01-02T00:00:00+00:00",
            manual_vcf=0.985,
            standard_volume_15_m3=11.82,
        )
    )

    assert earlier.manual_vcf is None
    assert earlier.standard_volume_15_m3 is None
    assert repository.get_latest_sounding(tank.id) == later
    assert repository.list_sounding_history(tank.id) == [later, earlier]
    reloaded_earlier = repository.list_sounding_history(tank.id)[1]
    assert reloaded_earlier.manual_vcf is None
    assert reloaded_earlier.standard_volume_15_m3 is None
