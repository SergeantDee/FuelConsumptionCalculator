from __future__ import annotations

from datetime import datetime

from fuel_consumption_calculator.domain.rob import empty_starting_rob
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankForecast, TankEmptyForecast
from fuel_consumption_calculator.calculations.tank_depletion_engine import estimate_tank_empty_time
from fuel_consumption_calculator.domain.voyage_stages import build_voyage_stage_timeline
from fuel_consumption_calculator.services.consumption_service import ConsumptionService
from fuel_consumption_calculator.services.fuel_tank_service import FuelTankService
from fuel_consumption_calculator.services.schedule_service import ScheduleService
from fuel_consumption_calculator.services.voyage_service import VoyageService
from fuel_consumption_calculator.domain.fuel_tank import TankSounding


class TankForecastService:
    """Advisory tank forecasts built from the existing authoritative voyage deductions."""

    def __init__(self, tanks: FuelTankService, schedule: ScheduleService, consumption: ConsumptionService, voyage: VoyageService) -> None:
        self._tanks, self._schedule, self._consumption, self._voyage = tanks, schedule, consumption, voyage

    def predict_tank_rob_at(self, vessel_id: int, target_utc: datetime) -> list[TankForecast]:
        intervals = self._future_intervals(vessel_id)
        return self._tanks.predict_tank_rob_at(vessel_id, target_utc, intervals)

    def anchor_sounding_at(self, tank_id: int, target_utc: datetime) -> TankSounding | None:
        """Return the exact historical sounding anchor used by arrival forecasting."""
        return self._tanks.get_latest_sounding_at_or_before(tank_id, target_utc)

    def predict_tank_empty_times(self, vessel_id: int, forecast_start_utc: datetime) -> list[TankEmptyForecast]:
        intervals = self._future_intervals(vessel_id)
        tanks = self._tanks.list_tanks(vessel_id); batches = {item.id: item for item in self._tanks.list_fuel_batches(vessel_id)}
        fuels = {tank.id: (batches[tank.current_fuel_batch_id].fuel_type if tank.current_fuel_batch_id in batches else None) for tank in tanks}
        events = self._tanks.list_consumption_allocation_events(vessel_id)
        transfers = self._tanks.list_internal_fuel_transfers(vessel_id)
        receipts = self._tanks.list_confirmed_complete_bunker_receipts(vessel_id)
        results = []
        for tank in tanks:
            anchor = self._tanks.get_latest_sounding(tank.id)
            anchor_time = _as_utc(anchor.effective_at_utc) if anchor else forecast_start_utc
            relevant_transfers = [item for item in transfers if _as_utc(item.effective_at_utc()) > anchor_time]
            empty_at, state, issue = estimate_tank_empty_time(tank.id, fuels[tank.id], anchor.calculated_mass_mt if anchor else None, forecast_start_utc, intervals, events, fuels, relevant_transfers, [item for item in receipts if _as_utc(item.effective_at_utc) > anchor_time])
            results.append(TankEmptyForecast(tank.id, fuels[tank.id], forecast_start_utc, _as_utc(anchor.effective_at_utc) if anchor else None, anchor.calculated_mass_mt if anchor else None, None, empty_at, state, issue))
        return results

    def _future_intervals(self, vessel_id: int) -> list[FuelDepletionInterval]:
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
        return intervals


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=__import__("datetime").timezone.utc)
