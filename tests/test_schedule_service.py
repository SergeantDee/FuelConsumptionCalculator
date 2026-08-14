from __future__ import annotations

from datetime import date, datetime

import pytest

from fuel_consumption_calculator.domain.schedule import ScheduleEventDraft
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from tests.test_schedule_repository import candidate


def draft(sequence: int = 1, port: str = "Santos") -> ScheduleEventDraft:
    return ScheduleEventDraft(
        sequence_number=sequence,
        port=port,
        event_type="Port Call",
        arrival_at=datetime(2026, 9, sequence, 8, 0),
        departure_at=datetime(2026, 9, sequence, 20, 0),
        source="manual",
        source_vessel_name="Maersk Labrea",
        source_from_date=date(2026, 9, 1),
    )


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


def test_schedule_service_add_edit_delete_persists_manual_event(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    service = ScheduleService(ScheduleRepository(database))

    events = service.create_event(vessel.id, draft(port="Original"))
    events = service.update_event(vessel.id, events[0].id, draft(port="Edited"))
    events = service.delete_event(vessel.id, events[0].id)

    assert events == []
    assert service.list_events(vessel.id) == []


def test_schedule_service_resequences_and_rejects_blank_event(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    service = ScheduleService(ScheduleRepository(database))

    service.confirm_schedule_update(vessel.id, [candidate(1, "First"), candidate(2, "Second")])
    events = service.create_event(vessel.id, draft(sequence=1, port="Inserted"))

    assert [(event.sequence_number, event.port) for event in events] == [
        (1, "Inserted"),
        (2, "First"),
        (3, "Second"),
    ]
    with pytest.raises(ValueError, match="Port is required"):
        service.create_event(vessel.id, draft(port=""))
