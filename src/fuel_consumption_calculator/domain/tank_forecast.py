from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TankConsumptionAllocationEvent:
    id: int | None
    vessel_id: int
    effective_at_utc: datetime
    tank_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class FuelDepletionInterval:
    start_utc: datetime
    end_utc: datetime
    deductions_mt: dict[str, float | None]


@dataclass(frozen=True, slots=True)
class TankForecast:
    tank_id: int
    fuel_type: str | None
    anchor_effective_at_utc: datetime | None
    anchor_mass_mt: float | None
    allocated_depletion_mt: float | None
    predicted_mass_mt: float | None
    issue: str | None = None


@dataclass(frozen=True, slots=True)
class TankEmptyForecast:
    tank_id: int
    fuel_type: str | None
    forecast_start_utc: datetime
    anchor_effective_at_utc: datetime | None
    anchor_mass_mt: float | None
    estimated_current_mass_mt: float | None
    estimated_empty_at_utc: datetime | None
    state: str
    issue: str | None = None
    stage_context: str | None = None
