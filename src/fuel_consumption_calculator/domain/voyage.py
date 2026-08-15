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
    port_reefers: float | None = None
    departure_reefers: float | None = None
    use_egb: bool = False


@dataclass(frozen=True, slots=True)
class SpeedConsumptionPoint:
    vessel_id: int
    speed_knots: float
    rates_mt_per_day: dict[str, float]
    main_engine_load_percent: float | None = None

    def rate_for(self, fuel_type: str) -> float:
        return self.rates_mt_per_day.get(fuel_type, 0.0)


@dataclass(frozen=True, slots=True)
class VesselEnergyConfig:
    vessel_id: int
    port_base_load_kw: float = 0.0
    sea_base_load_kw: float = 0.0
    reefer_kw_per_unit: float = 0.0
    generator_rated_kw: float = 0.0
    port_running_generators: float = 0.0
    sea_running_generators: float = 0.0
    aux_boiler_mt_per_hour: float = 0.0
    generator_fuel_type: str = "MDO"
    boiler_fuel_type: str = "MDO"


@dataclass(frozen=True, slots=True)
class GeneratorSfocPoint:
    vessel_id: int
    load_percent: float
    sfoc_g_per_kwh: float


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
    predicted_me_load_percent: float | None = None
    egb_available: bool = False
    egb_used: bool = False
    sea_generator_consumed_mt: dict[str, float] | None = None
    sea_boiler_consumed_mt: dict[str, float] | None = None
    sea_total_electrical_load_kw: float | None = None
    sea_generator_load_percent: float | None = None
    sea_generator_sfoc_g_per_kwh: float | None = None
    sea_calculation_mode: str = "FALLBACK"
    warnings: tuple[str, ...] = ()

    @property
    def sea_distance_nm(self) -> float:
        return self.leg.override.sea_distance_nm if self.leg.override and self.leg.override.sea_distance_nm is not None else self.leg.route.sea_distance_nm


@dataclass(frozen=True, slots=True)
class PortEnergyBreakdown:
    event_id: int
    port: str
    port_hours: float
    reefers: float
    total_electrical_load_kw: float
    generator_load_percent: float | None
    generator_sfoc_g_per_kwh: float | None
    generator_consumed_mt: dict[str, float]
    boiler_consumed_mt: dict[str, float]
    total_consumed_mt: dict[str, float]
    calculation_mode: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoyagePlan:
    legs: list[CalculatedVoyageLeg]
    warnings: list[str]
    port_breakdowns: dict[int, PortEnergyBreakdown] | None = None
    energy_config: VesselEnergyConfig | None = None
    generator_sfoc_points: tuple[GeneratorSfocPoint, ...] = ()


def empty_fuel_totals() -> dict[str, float]:
    return {fuel_type: 0.0 for fuel_type in FUEL_TYPES}
