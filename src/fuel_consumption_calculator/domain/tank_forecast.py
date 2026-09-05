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
class TankConsumptionPlanPhaseTank:
    tank_id: int
    allocation_fraction: float


@dataclass(frozen=True, slots=True)
class TankConsumptionPlanPhase:
    id: int | None
    sequence_number: int
    tanks: tuple[TankConsumptionPlanPhaseTank, ...]
    end_condition: str = "FIRST_DEPLETION"
    depletion_threshold_mt: float = 0.0
    remarks: str | None = None


@dataclass(frozen=True, slots=True)
class TankConsumptionPlan:
    id: int | None
    vessel_id: int
    fuel_type: str
    status: str
    effective_from_utc: datetime
    phases: tuple[TankConsumptionPlanPhase, ...]
    remarks: str | None = None


@dataclass(frozen=True, slots=True)
class TankPlanForecast:
    tank_masses_mt: dict[int, float | None]
    depletion_at_utc: dict[int, datetime | None]
    phase_starts_utc: dict[int, datetime | None]
    active_phase_sequence: int | None
    unallocated_consumption_mt: float
    issues: tuple[str, ...] = ()


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
    estimated_depleted_at_utc: datetime | None = None
    active_phase_sequence: int | None = None
    next_phase_sequence: int | None = None
    planned_phase_start_utc: datetime | None = None


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
