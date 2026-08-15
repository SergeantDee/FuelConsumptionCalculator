from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES


MACHINERY_TYPES = ("MAIN_ENGINE", "GENERATORS", "AUX_BOILER")


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
    actual_departure_reefers: float | None = None
    port_ambient_c: float | None = None
    sea_ambient_c: float | None = None
    use_egb: bool = False


@dataclass(frozen=True, slots=True)
class SpeedConsumptionPoint:
    vessel_id: int
    speed_knots: float
    rates_mt_per_day: dict[str, float]
    main_engine_load_percent: float | None = None
    rpm: float | None = None
    power_kw: float | None = None
    main_engine_sfoc_g_per_kwh: float | None = None

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
    main_engine_slip_percent: float = 10.0
    speed_rpm_factor: float = 0.3221598
    power_coefficient: float = 0.0967741935483871
    mcr_power_kw: float = 38880.0
    port_ambient_c: float = 20.0
    sea_ambient_c: float = 20.0


@dataclass(frozen=True, slots=True)
class MachineryFuelState:
    vessel_id: int
    main_engine_fuel_type: str = "VLSFO"
    generators_fuel_type: str = "VLSFO"
    aux_boiler_fuel_type: str = "VLSFO"

    def fuel_for(self, machinery: str) -> str:
        if machinery == "MAIN_ENGINE":
            return self.main_engine_fuel_type
        if machinery == "GENERATORS":
            return self.generators_fuel_type
        if machinery == "AUX_BOILER":
            return self.aux_boiler_fuel_type
        raise ValueError(f"Unsupported machinery: {machinery}")


@dataclass(frozen=True, slots=True)
class FuelChangeoverEvent:
    id: int | None
    vessel_id: int
    machinery: str
    from_fuel_type: str
    to_fuel_type: str
    planned_at_utc: datetime
    actual_at_utc: datetime | None = None
    time_basis: str = "UTC"
    status: str = "PLANNED"

    @property
    def effective_at_utc(self) -> datetime:
        return self.actual_at_utc or self.planned_at_utc


@dataclass(frozen=True, slots=True)
class VesselClockAdjustment:
    id: int | None
    vessel_id: int
    effective_at_utc: datetime
    adjustment_minutes: int
    previous_offset_minutes: int
    resulting_offset_minutes: int


@dataclass(frozen=True, slots=True)
class GeneratorSfocPoint:
    vessel_id: int
    load_percent: float
    sfoc_g_per_kwh: float


@dataclass(frozen=True, slots=True)
class MainEngineSfocPoint:
    vessel_id: int
    load_percent: float
    sfoc_g_per_kwh: float


@dataclass(frozen=True, slots=True)
class ActualROBObservation:
    id: int | None
    vessel_id: int
    effective_at_utc: datetime
    quantities_mt: dict[str, float]
    remarks: str | None = None

    def quantity_for(self, fuel_type: str) -> float:
        return self.quantities_mt.get(fuel_type, 0.0)


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
    predicted_rpm: float | None = None
    predicted_me_power_kw: float | None = None
    predicted_me_sfoc_g_per_kwh: float | None = None
    predicted_me_fuel_mt_per_hour: float | None = None
    hull_coefficient: float | None = None
    departure_reefer_kw_per_unit: float | None = None
    egb_available: bool = False
    egb_used: bool = False
    sea_generator_consumed_mt: dict[str, float] | None = None
    sea_boiler_consumed_mt: dict[str, float] | None = None
    sea_total_electrical_load_kw: float | None = None
    sea_generator_load_percent: float | None = None
    sea_generator_sfoc_g_per_kwh: float | None = None
    sea_calculation_mode: str = "INCOMPLETE"
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
    reefer_kw_per_unit: float | None
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
    initial_fuel_state: MachineryFuelState | None = None
    fuel_changeovers: tuple[FuelChangeoverEvent, ...] = ()


def empty_fuel_totals() -> dict[str, float]:
    return {fuel_type: 0.0 for fuel_type in FUEL_TYPES}
