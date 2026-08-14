from __future__ import annotations

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate, ScheduleEvent
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.scraper.validation import validate_schedule_candidates


class ScheduleService:
    def __init__(self, repository: ScheduleRepository) -> None:
        self._repository = repository

    def list_events(self, vessel_id: int) -> list[ScheduleEvent]:
        return self._repository.list_for_vessel(vessel_id)

    def confirm_schedule_update(self, vessel_id: int, candidates: list[ScheduleCandidate]) -> list[ScheduleEvent]:
        validate_schedule_candidates(candidates)
        return self._repository.replace_for_vessel(vessel_id, candidates)
