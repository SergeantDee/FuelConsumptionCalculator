from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pytest

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate
from fuel_consumption_calculator.repositories.database import Database
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.repositories.vessel_repository import VesselRepository


def candidate(sequence: int = 1, port: str = "Santos") -> ScheduleCandidate:
    return ScheduleCandidate(
        sequence_number=sequence,
        port=port,
        event_type="Port Call",
        arrival_at=datetime(2026, 9, sequence, 8, 0),
        departure_at=datetime(2026, 9, sequence, 20, 0),
        source="maersk_vessel_schedules",
        source_vessel_name="Maersk Labrea",
        source_from_date=date(2026, 9, 1),
    )


def initialized_repository(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    vessel = VesselRepository(database).save_active("Maersk Labrea", "1234567")
    return database, ScheduleRepository(database), vessel


def test_schedule_repository_persists_events(tmp_path):
    _, repository, vessel = initialized_repository(tmp_path)

    events = repository.replace_for_vessel(vessel.id, [candidate(1), candidate(2, "Paranagua")])

    assert [event.port for event in events] == ["Santos", "Paranagua"]
    assert repository.count_for_vessel(vessel.id) == 2


def test_schedule_replacement_is_transactional(tmp_path):
    _, repository, vessel = initialized_repository(tmp_path)
    repository.replace_for_vessel(vessel.id, [candidate(1, "Original")])

    repository.replace_for_vessel(vessel.id, [candidate(1, "Replacement"), candidate(2, "Second")])

    assert [event.port for event in repository.list_for_vessel(vessel.id)] == ["Replacement", "Second"]


def test_schedule_replacement_rolls_back_on_failed_insert(tmp_path):
    _, repository, vessel = initialized_repository(tmp_path)
    repository.replace_for_vessel(vessel.id, [candidate(1, "Original")])
    bad_candidate = candidate(1, "Broken")
    object.__setattr__(bad_candidate, "port", None)

    with pytest.raises(sqlite3.IntegrityError):
        repository.replace_for_vessel(vessel.id, [bad_candidate])

    assert [event.port for event in repository.list_for_vessel(vessel.id)] == ["Original"]
