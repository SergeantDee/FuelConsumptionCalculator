from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal


FuelTankType = Literal["BUNKER", "SETTLING", "SERVICE", "OTHER"]
MeasurementType = Literal["SOUNDING", "ULLAGE"]
FuelType = Literal["ULSFO", "VLSFO", "MDO"]

FUEL_TANK_TYPES = ("BUNKER", "SETTLING", "SERVICE", "OTHER")
MEASUREMENT_TYPES = ("SOUNDING", "ULLAGE")
FUEL_BATCH_TYPES = ("ULSFO", "VLSFO", "MDO")


@dataclass(frozen=True, slots=True)
class FuelTank:
    id: int | None
    vessel_id: int
    name: str
    tank_type: FuelTankType
    capacity_m3: float
    preferred_measurement_type: MeasurementType
    bunker_receiving_eligible: bool = False
    is_active: bool = True
    current_fuel_batch_id: int | None = None
    notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class FuelBatch:
    id: int | None
    vessel_id: int
    batch_name: str
    fuel_type: FuelType
    density_15_kg_m3: float
    sulfur_percent: float | None = None
    viscosity_50_cst: float | None = None
    flash_point_c: float | None = None
    pour_point_c: float | None = None
    water_percent: float | None = None
    lab_reference: str | None = None
    bunker_port: str | None = None
    bunker_date: str | None = None
    remarks: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class TankCalibrationPoint:
    id: int | None
    tank_id: int
    sounding_cm: float | None
    ullage_cm: float | None
    trim_m: float
    volume_m3: float


@dataclass(frozen=True, slots=True)
class TankSounding:
    id: int | None
    tank_id: int
    effective_at_utc: str
    reading_type: MeasurementType
    reading_cm: float
    trim_m: float
    temperature_c: float | None
    calculated_volume_m3: float
    calculated_density_kg_m3: float | None = None
    calculated_mass_mt: float | None = None
    fuel_batch_id: int | None = None
    remarks: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    manual_vcf: float | None = None
    standard_volume_15_m3: float | None = None

    def __post_init__(self) -> None:
        if self.manual_vcf is not None and (
            not isfinite(self.manual_vcf) or self.manual_vcf <= 0
        ):
            raise ValueError("Manual VCF must be finite and greater than 0.")
        if self.standard_volume_15_m3 is not None and (
            not isfinite(self.standard_volume_15_m3)
            or self.standard_volume_15_m3 < 0
        ):
            raise ValueError("Standard volume at 15 C must be finite and at least 0.")
