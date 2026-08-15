from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    origin_port: str
    destination_port: str
    departure_pilot_distance_nm: float = 0.0
    departure_pilotage_hours: float = 1.0
    sea_distance_nm: float = 0.0
    arrival_pilot_distance_nm: float = 0.0
    arrival_pilotage_hours: float = 1.0


@dataclass(frozen=True, slots=True)
class VoyageLegOverride:
    vessel_id: int
    sequence_number: int
    origin_port_snapshot: str
    destination_port_snapshot: str
    origin_departure_snapshot: str | None
    destination_arrival_snapshot: str
    departure_pilot_distance_nm: float | None = None
    departure_pilotage_hours: float | None = None
    sea_distance_nm: float | None = None
    arrival_pilot_distance_nm: float | None = None
    arrival_pilotage_hours: float | None = None
    actual_berth_departure: datetime | None = None
    actual_pilot_off: datetime | None = None
    actual_pilot_on: datetime | None = None
    actual_berth_arrival: datetime | None = None


@dataclass(frozen=True, slots=True)
class SpeedConsumptionPoint:
    vessel_id: int
    speed_knots: float
    rates_mt_per_day: dict[str, float]

    def rate_for(self, fuel_type: str) -> float:
        return self.rates_mt_per_day.get(fuel_type, 0.0)


@dataclass(frozen=True, slots=True)
class VoyageLeg:
    vessel_id: int
    sequence_number: int
    origin_event_id: int
    destination_event_id: int
    origin_port: str
    destination_port: str
    scheduled_berth_departure: datetime
    scheduled_berth_arrival: datetime
    route: RouteDefinition
    override: VoyageLegOverride | None = None
    status: str = "OK"
    message: str = ""


@dataclass(frozen=True, slots=True)
class CalculatedVoyageLeg:
    leg: VoyageLeg
    effective_berth_departure: datetime
    pilot_off: datetime
    pilot_on: datetime
    effective_berth_arrival: datetime
    departure_pilotage_hours: float
    sea_hours: float
    arrival_pilotage_hours: float
    required_speed_knots: float | None
    departure_maneuvering_consumed_mt: dict[str, float]
    sea_consumed_mt: dict[str, float]
    arrival_maneuvering_consumed_mt: dict[str, float]
    total_pre_arrival_consumed_mt: dict[str, float]
    warnings: tuple[str, ...] = ()

    @property
    def sea_distance_nm(self) -> float:
        return self.leg.override.sea_distance_nm if self.leg.override and self.leg.override.sea_distance_nm is not None else self.leg.route.sea_distance_nm


@dataclass(frozen=True, slots=True)
class VoyagePlan:
    legs: list[CalculatedVoyageLeg]
    warnings: list[str]


def empty_fuel_totals() -> dict[str, float]:
    return {fuel_type: 0.0 for fuel_type in FUEL_TYPES}
