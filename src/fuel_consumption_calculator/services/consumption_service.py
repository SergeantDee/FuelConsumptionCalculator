from __future__ import annotations

from fuel_consumption_calculator.domain.consumption import (
    FUEL_TYPES,
    OPERATING_MODES,
    ConsumptionProfile,
    ConsumptionRate,
)
from fuel_consumption_calculator.calculations.consumption_engine import (
    ScheduleFuelConsumption,
    calculate_schedule_consumption,
)
from fuel_consumption_calculator.domain.schedule_timeline import ScheduleTimeline
from fuel_consumption_calculator.repositories.consumption_repository import ConsumptionRepository


class ConsumptionService:
    def __init__(self, repository: ConsumptionRepository) -> None:
        self._repository = repository

    def load_profile(self, vessel_id: int) -> ConsumptionProfile:
        stored_profile = self._repository.load_profile(vessel_id)
        stored_rates = {
            (rate.operating_mode, rate.fuel_type): rate.rate_mt_per_day
            for rate in stored_profile.rates
        }
        complete_rates = tuple(
            ConsumptionRate(
                operating_mode=operating_mode,
                fuel_type=fuel_type,
                rate_mt_per_day=stored_rates.get((operating_mode, fuel_type), 0.0),
            )
            for operating_mode in OPERATING_MODES
            for fuel_type in FUEL_TYPES
        )
        return ConsumptionProfile(vessel_id=vessel_id, rates=complete_rates)

    def save_profile(self, profile: ConsumptionProfile) -> ConsumptionProfile:
        self._validate_profile(profile)
        return self.load_profile(self._repository.save_profile(profile).vessel_id)

    def calculate_schedule_consumption(
        self,
        vessel_id: int,
        timeline: ScheduleTimeline,
    ) -> ScheduleFuelConsumption:
        profile = self.load_profile(vessel_id)
        return calculate_schedule_consumption(timeline, profile)

    def build_profile(self, vessel_id: int, rates: dict[tuple[str, str], float]) -> ConsumptionProfile:
        profile = ConsumptionProfile(
            vessel_id=vessel_id,
            rates=tuple(
                ConsumptionRate(
                    operating_mode=operating_mode,
                    fuel_type=fuel_type,
                    rate_mt_per_day=float(rates.get((operating_mode, fuel_type), 0.0)),
                )
                for operating_mode in OPERATING_MODES
                for fuel_type in FUEL_TYPES
            ),
        )
        self._validate_profile(profile)
        return profile

    def _validate_profile(self, profile: ConsumptionProfile) -> None:
        expected_keys = {(mode, fuel_type) for mode in OPERATING_MODES for fuel_type in FUEL_TYPES}
        seen_keys = set()
        for rate in profile.rates:
            key = (rate.operating_mode, rate.fuel_type)
            if key not in expected_keys:
                raise ValueError(f"Unsupported consumption rate: {rate.operating_mode} / {rate.fuel_type}.")
            if key in seen_keys:
                raise ValueError(f"Duplicate consumption rate: {rate.operating_mode} / {rate.fuel_type}.")
            if rate.rate_mt_per_day < 0:
                raise ValueError("Consumption rates cannot be negative.")
            seen_keys.add(key)
        if seen_keys != expected_keys:
            raise ValueError("Consumption profile must include SEA and PORT rates for ULSFO, VLSFO, and MDO.")
