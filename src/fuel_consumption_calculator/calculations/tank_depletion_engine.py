from __future__ import annotations

from datetime import datetime, timezone

from fuel_consumption_calculator.domain.consumption import FUEL_TYPES
from fuel_consumption_calculator.domain.tank_forecast import FuelDepletionInterval, TankConsumptionAllocationEvent


def allocate_tank_depletion(
    intervals: list[FuelDepletionInterval],
    allocation_events: list[TankConsumptionAllocationEvent],
    tank_fuels: dict[int, str | None],
    start_utc: datetime,
    target_utc: datetime,
) -> tuple[dict[int, float | None], dict[int, str]]:
    """Equally distribute existing per-fuel deductions without changing them."""
    allocations: dict[int, float | None] = {tank_id: 0.0 for tank_id in tank_fuels}
    issues: dict[int, str] = {}
    events = sorted(allocation_events, key=lambda event: _utc(event.effective_at_utc))
    for interval in intervals:
        interval_start, interval_end = max(_utc(interval.start_utc), _utc(start_utc)), min(_utc(interval.end_utc), _utc(target_utc))
        if interval_end <= interval_start:
            continue
        original_start, original_end = _utc(interval.start_utc), _utc(interval.end_utc)
        duration = (original_end - original_start).total_seconds()
        if duration <= 0:
            continue
        boundaries = [interval_start, *(_utc(event.effective_at_utc) for event in events if interval_start < _utc(event.effective_at_utc) < interval_end), interval_end]
        for segment_start, segment_end in zip(boundaries, boundaries[1:]):
            share = (segment_end - segment_start).total_seconds() / duration
            state = _state_at(events, segment_start)
            for fuel in FUEL_TYPES:
                deduction = interval.deductions_mt.get(fuel)
                if deduction is None:
                    for tank_id, tank_fuel in tank_fuels.items():
                        if tank_fuel == fuel:
                            allocations[tank_id] = None
                            issues[tank_id] = f"Authoritative {fuel} depletion is unavailable"
                    continue
                active = [tank_id for tank_id in state if tank_fuels.get(tank_id) == fuel]
                if not active:
                    issues_for_fuel = f"No active {fuel} consumption tank selected"
                    for tank_id, tank_fuel in tank_fuels.items():
                        if tank_fuel == fuel:
                            issues[tank_id] = issues_for_fuel
                    continue
                amount = float(deduction) * share / len(active)
                for tank_id in active:
                    if allocations[tank_id] is not None:
                        allocations[tank_id] = float(allocations[tank_id]) + amount
    return allocations, issues


def estimate_tank_empty_time(
    tank_id: int, fuel_type: str | None, anchor_mass_mt: float | None, forecast_start_utc: datetime,
    intervals: list[FuelDepletionInterval], allocation_events: list[TankConsumptionAllocationEvent],
    tank_fuels: dict[int, str | None],
) -> tuple[datetime | None, str, str | None]:
    if anchor_mass_mt is None:
        return None, "UNAVAILABLE", "No mass-bearing sounding available"
    if fuel_type is None:
        return None, "UNAVAILABLE", "Fuel type unknown"
    mass = anchor_mass_mt
    if mass <= 0:
        return forecast_start_utc, "ALREADY_DEPLETED", "Tank is already depleted"
    events = sorted(allocation_events, key=lambda item: _utc(item.effective_at_utc))
    saw_active = False
    for interval in sorted(intervals, key=lambda item: _utc(item.start_utc)):
        start, end = max(_utc(interval.start_utc), _utc(forecast_start_utc)), _utc(interval.end_utc)
        if end <= start:
            continue
        deduction = interval.deductions_mt.get(fuel_type)
        if deduction is None:
            return None, "UNAVAILABLE", f"Authoritative {fuel_type} depletion is unavailable"
        duration = (_utc(interval.end_utc) - _utc(interval.start_utc)).total_seconds()
        if duration <= 0:
            continue
        boundaries = [start, *(_utc(event.effective_at_utc) for event in events if start < _utc(event.effective_at_utc) < end), end]
        for segment_start, segment_end in zip(boundaries, boundaries[1:]):
            active = [item for item in _state_at(events, segment_start) if tank_fuels.get(item) == fuel_type]
            if tank_id not in active:
                continue
            saw_active = True
            amount = float(deduction) * (segment_end - segment_start).total_seconds() / duration / len(active)
            if amount <= 0:
                continue
            if mass <= amount:
                fraction = mass / amount
                return segment_start + (segment_end - segment_start) * fraction, "ESTIMATED", None
            mass -= amount
    if not saw_active:
        return None, "UNAVAILABLE", f"No active {fuel_type} consumption tank selected"
    return None, "BEYOND_PLAN", "Beyond current voyage plan"


def _state_at(events: list[TankConsumptionAllocationEvent], instant: datetime) -> tuple[int, ...]:
    state: tuple[int, ...] = ()
    for event in events:
        if _utc(event.effective_at_utc) <= instant:
            state = event.tank_ids
        else:
            break
    return state


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
