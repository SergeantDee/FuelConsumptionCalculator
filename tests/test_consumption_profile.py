from __future__ import annotations

import sqlite3

import pytest

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES, OPERATING_MODES, ConsumptionProfile, ConsumptionRate
from fuel_consumption_calculator.repositories.consumption_repository import ConsumptionRepository
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.consumption_service import ConsumptionService


def initialized_service(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    return database, ConsumptionService(ConsumptionRepository(database)), vessel


def test_consumption_profile_save_and_load_persists_complete_matrix(tmp_path):
    _, service, vessel = initialized_service(tmp_path)
    profile = service.build_profile(
        vessel.id,
        {
            ("SEA", "ULSFO"): 12.5,
            ("SEA", "VLSFO"): 14.25,
            ("SEA", "MDO"): 1.5,
            ("PORT", "ULSFO"): 2.0,
            ("PORT", "VLSFO"): 2.5,
            ("PORT", "MDO"): 0.75,
        },
    )

    service.save_profile(profile)
    loaded = service.load_profile(vessel.id)

    assert loaded.rate_for("SEA", "ULSFO") == 12.5
    assert loaded.rate_for("PORT", "MDO") == 0.75
    assert len(loaded.rates) == len(OPERATING_MODES) * len(FUEL_TYPES)


def test_consumption_profile_update_does_not_create_duplicates(tmp_path):
    database, service, vessel = initialized_service(tmp_path)
    service.save_profile(service.build_profile(vessel.id, {("SEA", "ULSFO"): 10.0}))
    service.save_profile(service.build_profile(vessel.id, {("SEA", "ULSFO"): 11.0}))

    loaded = service.load_profile(vessel.id)
    with sqlite3.connect(database.database_file) as connection:
        row_count = connection.execute(
            "SELECT COUNT(*) FROM vessel_consumption_rates WHERE vessel_id = ?",
            (vessel.id,),
        ).fetchone()[0]

    assert loaded.rate_for("SEA", "ULSFO") == 11.0
    assert row_count == len(OPERATING_MODES) * len(FUEL_TYPES)


def test_consumption_profile_rejects_negative_rate(tmp_path):
    _, service, vessel = initialized_service(tmp_path)
    profile = ConsumptionProfile(
        vessel_id=vessel.id,
        rates=tuple(
            ConsumptionRate(mode, fuel_type, -1.0 if (mode, fuel_type) == ("SEA", "ULSFO") else 0.0)
            for mode in OPERATING_MODES
            for fuel_type in FUEL_TYPES
        ),
    )

    with pytest.raises(ValueError, match="cannot be negative"):
        service.save_profile(profile)
