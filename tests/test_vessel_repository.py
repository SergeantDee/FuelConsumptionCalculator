from __future__ import annotations

from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository


def initialized_repository(tmp_path) -> VesselRepository:
    database = Database(tmp_path / "vessels.db")
    database.initialize()
    return VesselRepository(database)


def test_repository_creates_and_reads_active_vessel(tmp_path):
    repository = initialized_repository(tmp_path)

    assert repository.get_active() is None
    saved = repository.save_active("MV Ocean Star", "9876543")

    assert saved.id == 1
    assert saved.name == "MV Ocean Star"
    assert saved.imo == "9876543"
    assert saved.created_at
    assert saved.updated_at
    assert repository.get_active() == saved


def test_repository_updates_the_single_active_vessel(tmp_path):
    repository = initialized_repository(tmp_path)
    original = repository.save_active("Original Name", "1234567")

    updated = repository.save_active("Updated Name", "7654321")

    assert updated.id == original.id == 1
    assert updated.created_at == original.created_at
    assert updated.name == "Updated Name"
    assert updated.imo == "7654321"
