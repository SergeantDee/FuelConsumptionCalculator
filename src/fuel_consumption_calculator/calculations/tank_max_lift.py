"""Pure tank-based receiving-capacity calculations for future bunker planning."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence

from fuel_consumption_calculator.calculations.manual_vcf_mass import (
    ManualVcfMassError,
    calculate_manual_vcf_mass,
)


class TankMaxLiftError(ValueError):
    """Raised when selected receiving-tank inputs are physically inconsistent."""


@dataclass(frozen=True, slots=True)
class SelectedReceivingTank:
    tank_id: int
    capacity_m3: float
    arrival_volume_m3: float | None
    target_fill_percent: float
    bunker_receiving_eligible: bool = True


@dataclass(frozen=True, slots=True)
class TankReceivingCapacity:
    tank_id: int
    target_volume_m3: float
    available_volume_m3: float


@dataclass(frozen=True, slots=True)
class TankMaxLiftResult:
    tanks: tuple[TankReceivingCapacity, ...]
    total_available_volume_m3: float
    total_max_lift_mt: float | None


def calculate_tank_max_lift(
    selected_tanks: Sequence[SelectedReceivingTank],
    *,
    incoming_density_15_kg_m3: float | None = None,
    incoming_manual_vcf: float | None = None,
) -> TankMaxLiftResult:
    """Calculate physical lift capacity for only the operator-selected tanks.

    Incoming fuel mass is optional and uses the supplied manual VCF and density;
    existing fuel in the receiving tanks is deliberately not considered for MT.
    """
    capacities = tuple(_calculate_tank_capacity(tank) for tank in selected_tanks)
    total_available_volume_m3 = sum(
        capacity.available_volume_m3 for capacity in capacities
    )
    _validate_optional_incoming_fuel(
        incoming_density_15_kg_m3, incoming_manual_vcf
    )
    total_max_lift_mt = None
    if incoming_density_15_kg_m3 is not None and incoming_manual_vcf is not None:
        try:
            total_max_lift_mt = calculate_manual_vcf_mass(
                total_available_volume_m3,
                incoming_manual_vcf,
                incoming_density_15_kg_m3,
            ).mass_mt
        except ManualVcfMassError as error:
            raise TankMaxLiftError(str(error)) from error
    return TankMaxLiftResult(
        capacities, total_available_volume_m3, total_max_lift_mt
    )


def _calculate_tank_capacity(tank: SelectedReceivingTank) -> TankReceivingCapacity:
    if not tank.bunker_receiving_eligible:
        raise TankMaxLiftError("Selected receiving tanks must be bunker receiving eligible.")
    capacity_m3 = _finite(tank.capacity_m3, "Tank capacity")
    arrival_volume_m3 = _required_finite(tank.arrival_volume_m3, "Arrival volume")
    target_fill_percent = _finite(tank.target_fill_percent, "Target fill percent")
    if capacity_m3 <= 0:
        raise TankMaxLiftError("Tank capacity must be greater than 0.")
    if arrival_volume_m3 < 0:
        raise TankMaxLiftError("Arrival volume must be at least 0.")
    if arrival_volume_m3 > capacity_m3:
        raise TankMaxLiftError("Arrival volume cannot exceed physical tank capacity.")
    if not 0 < target_fill_percent <= 100:
        raise TankMaxLiftError("Target fill percent must be greater than 0 and at most 100.")
    target_volume_m3 = capacity_m3 * target_fill_percent / 100
    return TankReceivingCapacity(
        tank.tank_id,
        target_volume_m3,
        max(0.0, target_volume_m3 - arrival_volume_m3),
    )


def _validate_optional_incoming_fuel(
    density_15_kg_m3: float | None, manual_vcf: float | None
) -> None:
    if density_15_kg_m3 is not None:
        density = _finite(density_15_kg_m3, "Incoming density at 15 C")
        if density <= 0:
            raise TankMaxLiftError("Incoming density at 15 C must be greater than 0.")
    if manual_vcf is not None:
        vcf = _finite(manual_vcf, "Incoming manual VCF")
        if vcf <= 0:
            raise TankMaxLiftError("Incoming manual VCF must be greater than 0.")


def _required_finite(value: float | None, label: str) -> float:
    if value is None:
        raise TankMaxLiftError(f"{label} is required and cannot be unknown.")
    return _finite(value, label)


def _finite(value: object, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise TankMaxLiftError(f"{label} must be numeric.") from error
    if not isfinite(numeric):
        raise TankMaxLiftError(f"{label} must be finite.")
    return numeric
