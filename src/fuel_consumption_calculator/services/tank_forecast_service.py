from __future__ import annotations

from datetime import datetime

from fuel_consumption_calculator.domain.rob import empty_starting_rob
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankForecast
from fuel_consumption_calculator.domain.voyage_stages import build_voyage_stage_timeline
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.voyage_service import VoyageService


class TankForecastService:
    """Advisory tank forecasts built from the existing authoritative voyage deductions."""

    def __init__(self, tanks: FuelTankService, schedule: ScheduleService, consumption: ConsumptionService, voyage: VoyageService) -> None:
        self._tanks, self._schedule, self._consumption, self._voyage = tanks, schedule, consumption, voyage

    def predict_tank_rob_at(self, vessel_id: int, target_utc: datetime) -> list[TankForecast]:
        events = self._schedule.list_events(vessel_id)
        timeline = self._schedule.get_timeline(vessel_id)
        profile = self._consumption.load_profile(vessel_id)
        plan = self._voyage.calculate_plan(vessel_id, events, profile)
        result = self._voyage.calculate_consumption_for_plan(events=events, timeline=timeline, plan=plan, profile=profile)
        stages = build_voyage_stage_timeline(
            events, plan, empty_starting_rob(vessel_id), port_breakdowns=result.port_breakdowns,
        ).stages
        intervals = [
            FuelDepletionInterval(stage.start_utc, stage.end_utc, stage.consumption_mt)
            for stage in stages if stage.start_utc is not None and stage.end_utc is not None
        ]
        return self._tanks.predict_tank_rob_at(vessel_id, target_utc, intervals)
