from __future__ import annotations

import pytest

from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from tests.test_schedule_repository import candidate


def test_schedule_service_confirms_valid_candidates(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    service = ScheduleService(ScheduleRepository(database))

    events = service.confirm_schedule_update(vessel.id, [candidate(1)])

    assert len(events) == 1
    assert events[0].port == "Santos"


def test_schedule_service_rejects_empty_candidates(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    service = ScheduleService(ScheduleRepository(database))

    with pytest.raises(ValueError, match="no schedule events"):
        service.confirm_schedule_update(1, [])
