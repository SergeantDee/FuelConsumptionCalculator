from __future__ import annotations

from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.vessel_service import VesselService, VesselValidationError


def test_vessel_persists_across_new_service_instances(tmp_path):
    database_file = tmp_path / "persistent.db"
    first_database = Database(database_file)
    first_database.initialize()
    first_service = VesselService(VesselRepository(first_database))
    first_service.configure_active_vessel("  MV   Persistent  ", " 9876543 ")

    second_database = Database(database_file)
    second_database.initialize()
    second_service = VesselService(VesselRepository(second_database))

    vessel = second_service.get_active_vessel()
    assert vessel is not None
    assert vessel.name == "MV Persistent"
    assert vessel.imo == "9876543"


def test_service_rejects_invalid_vessel_details(tmp_path):
    database = Database(tmp_path / "validation.db")
    database.initialize()
    service = VesselService(VesselRepository(database))

    try:
        service.configure_active_vessel("", "123")
    except VesselValidationError as exc:
        assert "Vessel name" in str(exc)
    else:
        raise AssertionError("Expected invalid vessel details to be rejected")
