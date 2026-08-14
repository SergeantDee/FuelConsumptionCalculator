from __future__ import annotations

from fuel_consumption_calculator.domain.schedule import ScheduleCandidate, ScheduleEvent, ScheduleEventDraft
from fuel_consumption_calculator.domain.schedule_timeline import ScheduleTimeline, build_schedule_timeline
from fuel_consumption_calculator.repositories.schedule_repository import ScheduleRepository
from fuel_consumption_calculator.scraper.validation import validate_schedule_candidates


class ScheduleService:
    def __init__(self, repository: ScheduleRepository) -> None:
        self._repository = repository

    def list_events(self, vessel_id: int) -> list[ScheduleEvent]:
        return self._repository.list_for_vessel(vessel_id)

    def get_timeline(self, vessel_id: int) -> ScheduleTimeline:
        return build_schedule_timeline(self.list_events(vessel_id))

    def confirm_schedule_update(self, vessel_id: int, candidates: list[ScheduleCandidate]) -> list[ScheduleEvent]:
        validate_schedule_candidates(candidates)
        return self._repository.replace_for_vessel(vessel_id, candidates)

    def create_event(self, vessel_id: int, draft: ScheduleEventDraft) -> list[ScheduleEvent]:
        self._validate_draft(draft)
        return self._repository.create_event(vessel_id, draft)

    def update_event(self, vessel_id: int, event_id: int, draft: ScheduleEventDraft) -> list[ScheduleEvent]:
        self._validate_draft(draft)
        return self._repository.update_event(vessel_id, event_id, draft)

    def delete_event(self, vessel_id: int, event_id: int) -> list[ScheduleEvent]:
        return self._repository.delete_event(vessel_id, event_id)

    def _validate_draft(self, draft: ScheduleEventDraft) -> None:
        if not draft.port.strip():
            raise ValueError("Port is required.")
        if not draft.event_type.strip():
            raise ValueError("Event type is required.")
        if not draft.source.strip():
            raise ValueError("Source is required.")
        if not draft.source_vessel_name.strip():
            raise ValueError("Source vessel name is required.")
        if draft.departure_at is not None and draft.departure_at < draft.arrival_at:
            raise ValueError("Departure cannot be earlier than arrival.")
