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
