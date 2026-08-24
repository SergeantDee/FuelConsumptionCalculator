"""Pure discrete complete-mixing fuel changeover calculation."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


TIME_STEP_HOURS = 0.1
MAX_DURATION_HOURS = 200.0
MINIMUM_SYSTEM_MASS_MT = 0.001


class FuelChangeoverCalculationError(ValueError):
    """Raised when a complete-mixing changeover cannot be modelled safely."""


@dataclass(frozen=True, slots=True)
class FuelChangeoverTracePoint:
    time_hours: float
    sulfur_percent: float


@dataclass(frozen=True, slots=True)
class FuelChangeoverResult:
    changeover_time_hours: float
    final_sulfur_percent: float
    steps: int
    time_step_hours: float
    entered_replacement_sulfur_percent: float
    calculation_replacement_sulfur_percent: float
    trace: tuple[FuelChangeoverTracePoint, ...]


def calculate_fuel_changeover(
    fuel_flow_mt_per_hour: float,
    system_mass_mt: float,
    from_sulfur_percent: float,
    to_sulfur_percent: float,
    target_sulfur_percent: float,
) -> FuelChangeoverResult:
    """Return the first 0.1-hour complete-mixing step meeting the target."""
    flow = _finite(fuel_flow_mt_per_hour, "Fuel flow")
    mass = _finite(system_mass_mt, "Service-system fuel quantity")
    start = _finite(from_sulfur_percent, "FROM sulphur")
    entered_replacement = _finite(to_sulfur_percent, "TO sulphur")
    target = _finite(target_sulfur_percent, "Target sulphur")
    if flow <= 0:
        raise FuelChangeoverCalculationError("Fuel flow must be greater than 0 MT/h.")
    if mass < MINIMUM_SYSTEM_MASS_MT:
        raise FuelChangeoverCalculationError("Service-system fuel quantity must be at least 0.001 MT.")
    if min(start, entered_replacement, target) < 0:
        raise FuelChangeoverCalculationError("Sulphur values must be at least 0.")
    replacement = _calculation_replacement_sulfur(entered_replacement)
    if start == target:
        return FuelChangeoverResult(0.0, start, 0, TIME_STEP_HOURS, entered_replacement, replacement, (FuelChangeoverTracePoint(0.0, start),))
    decreasing = replacement < start
    if (decreasing and not replacement <= target < start) or (not decreasing and not start < target <= replacement):
        raise FuelChangeoverCalculationError("Target sulphur is unreachable from the selected replacement fuel.")
    fraction = flow * TIME_STEP_HOURS / mass
    if not 0 < fraction <= 1:
        raise FuelChangeoverCalculationError("Fuel flow/system-mass combination exceeds the supported 0.1-hour complete-mixing step.")
    sulfur = start
    trace = [FuelChangeoverTracePoint(0.0, sulfur)]
    max_steps = int(MAX_DURATION_HOURS / TIME_STEP_HOURS)
    for step in range(1, max_steps + 1):
        sulfur = sulfur + fraction * (replacement - sulfur)
        trace.append(FuelChangeoverTracePoint(step * TIME_STEP_HOURS, sulfur))
        if (decreasing and sulfur <= target) or (not decreasing and sulfur >= target):
            return FuelChangeoverResult(step * TIME_STEP_HOURS, sulfur, step, TIME_STEP_HOURS, entered_replacement, replacement, tuple(trace))
    raise FuelChangeoverCalculationError("Target sulphur was not reached within the 200-hour modelling horizon.")


def _calculation_replacement_sulfur(value: float) -> float:
    return {0.10: 0.099, 0.50: 0.499}.get(value, value)


def _finite(value: object, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as error:
        raise FuelChangeoverCalculationError(f"{label} must be numeric.") from error
    if not isfinite(numeric):
        raise FuelChangeoverCalculationError(f"{label} must be finite.")
    return numeric
